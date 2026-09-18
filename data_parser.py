"""
Parsers for CSV/TSV, JSON, and Plain Text files in RakuTrans AI.
Provides:
- CsvTranslator: Handles .csv and .tsv spreadsheets with dialect and encoding support.
- JsonTranslator: Handles .json localization and config files preserving keys & variables.
- TextTranslator: Handles .txt plain text documents with chunked translation.
"""

import csv
import json
import re
from pathlib import Path
from typing import List, Dict, Set, Callable, Optional, Any, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from base_translator import BaseTranslator, safe_save_file
from config import AppConfig, TranslationOptions, get_smart_output_path
from llm_manager import LLMManager
from translation_cache import TranslationCache


def _should_translate_cell(val: Any) -> bool:
    """Checks if a cell or string value should be translated."""
    if val is None:
        return False
    if not isinstance(val, str):
        return False
    trimmed = val.strip()
    if not trimmed:
        return False
    if trimmed.startswith("="):
        return False
    try:
        float(trimmed.replace(",", ""))
        return False
    except ValueError:
        pass
    return any(c.isalnum() for c in trimmed)


def _detect_encoding(file_path: Path) -> str:
    """Detects encoding with priority for UTF-8-SIG, UTF-8, Shift-JIS, and Latin-1."""
    for enc in ["utf-8-sig", "utf-8", "shift_jis", "cp1252", "latin-1"]:
        try:
            with open(file_path, "r", encoding=enc) as f:
                f.read(8192)
            return enc
        except (UnicodeDecodeError, LookupError):
            continue
    return "utf-8"


class CsvTranslator(BaseTranslator):
    """
    Handles translation of CSV (.csv) and TSV (.tsv) spreadsheet files.
    Preserves table structure, delimiters, quotes, and numeric data.
    Outputs UTF-8-SIG to ensure Microsoft Excel correctly displays accents on all OSes.
    """

    @classmethod
    def _detect_delimiter(cls, file_path: Path, encoding: str) -> str:
        """Determines whether file uses comma, tab, or semicolon."""
        if file_path.suffix.lower() == ".tsv":
            return "\t"
        try:
            with open(file_path, "r", encoding=encoding, errors="replace") as f:
                sample = f.read(4096)
                dialect = csv.Sniffer().sniff(sample, delimiters=[",", "\t", ";", "|"])
                return dialect.delimiter
        except Exception:
            return ","

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects CSV/TSV to count rows, columns, and translatable cells."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "csv", "error": "File not found"}

        try:
            enc = _detect_encoding(path)
            delimiter = cls._detect_delimiter(path, enc)
            row_count = 0
            max_cols = 0
            translatable_cells = 0
            unique_texts: Set[str] = set()

            with open(path, "r", encoding=enc, errors="replace") as f:
                reader = csv.reader(f, delimiter=delimiter)
                for row in reader:
                    if not row:
                        continue
                    row_count += 1
                    max_cols = max(max_cols, len(row))
                    for cell in row:
                        if _should_translate_cell(cell):
                            translatable_cells += 1
                            unique_texts.add(cell.strip())

            return {
                "type": "csv",
                "rows": row_count,
                "columns": max_cols,
                "translatable_cells": translatable_cells,
                "unique_texts": len(unique_texts),
                "delimiter": delimiter
            }
        except Exception as e:
            return {"type": "csv", "error": str(e)}

    def process_file(
        self,
        file_path: str,
        target_lang: Optional[str] = None,
        source_lang: Optional[str] = "auto",
        options: Optional[TranslationOptions] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        custom_output_path: Optional[str] = None,
        *args,
        **kwargs
    ) -> str:
        """Translates CSV/TSV table rows."""
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang = target_lang or "Vietnamese"
        options = options or self.config.translation_options

        if progress_callback:
            progress_callback(5, 100, "Reading CSV table...")

        enc = _detect_encoding(src)
        delimiter = self._detect_delimiter(src, enc)

        rows: List[List[str]] = []
        with open(src, "r", encoding=enc, errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            for row in reader:
                rows.append(row)

        unique_texts = list({cell.strip() for row in rows for cell in row if _should_translate_cell(cell)})
        total_unique = len(unique_texts)

        if not unique_texts:
            out_path = get_smart_output_path(src, target_lang=target_lang, custom_output_path=custom_output_path)
            safe_save_file(lambda p: self._write_csv(p, rows, delimiter), out_path)
            if progress_callback:
                progress_callback(100, 100, "File contains no translatable text.")
            return str(out_path)

        if progress_callback:
            progress_callback(10, 100, f"Found {total_unique} unique cells. Checking cache...")

        translation_map: Dict[str, str] = {}
        uncached_texts: List[str] = []

        for text in unique_texts:
            cached = self.cache.get(text, target_lang)
            if cached:
                translation_map[text] = cached
            else:
                uncached_texts.append(text)

        if uncached_texts:
            batch_size = max(5, getattr(self.config, "batch_size", 20))
            batches = [uncached_texts[i:i + batch_size] for i in range(0, len(uncached_texts), batch_size)]
            total_batches = len(batches)
            completed_batches = 0

            def translate_worker(batch: List[str]) -> List[str]:
                if self.is_cancelled:
                    raise InterruptedError("Translation cancelled by user.")
                return self.llm_manager.translate_batch(
                    texts=batch,
                    target_lang=target_lang,
                    source_lang=source_lang,
                    options=options
                )

            max_workers = min(3, max(1, total_batches))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(translate_worker, b): b for b in batches}
                for future in as_completed(futures):
                    if self.is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise InterruptedError("Translation cancelled by user.")

                    orig_batch = futures[future]
                    try:
                        translated_batch = future.result()
                        for orig, trans in zip(orig_batch, translated_batch):
                            translation_map[orig] = trans
                            self.cache.set(orig, target_lang, trans)
                    except Exception as e:
                        if self.is_cancelled:
                            raise InterruptedError("Translation cancelled by user.")
                        raise e

                    completed_batches += 1
                    pct = 10 + int(completed_batches / total_batches * 75)
                    if progress_callback:
                        progress_callback(pct, 100, f"Translating batch {completed_batches}/{total_batches}...")

        if self.is_cancelled:
            raise InterruptedError("Translation cancelled by user.")

        if progress_callback:
            progress_callback(90, 100, "Applying translations to CSV...")

        # Apply translations
        translated_rows: List[List[str]] = []
        for row in rows:
            new_row = []
            for cell in row:
                trimmed = cell.strip()
                if _should_translate_cell(cell) and trimmed in translation_map:
                    # Preserve original leading/trailing whitespace if any
                    prefix = cell[:len(cell) - len(cell.lstrip())]
                    suffix = cell[len(cell.rstrip()):]
                    new_row.append(f"{prefix}{translation_map[trimmed]}{suffix}")
                else:
                    new_row.append(cell)
            translated_rows.append(new_row)

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=src.suffix,
            custom_output_path=custom_output_path
        )
        saved_path = safe_save_file(lambda p: self._write_csv(p, translated_rows, delimiter), out_path)

        if progress_callback:
            progress_callback(100, 100, f"Saved: {saved_path.name}")

        return str(saved_path)

    @staticmethod
    def _write_csv(target_path: Path, rows: List[List[str]], delimiter: str):
        """Writes rows to file using UTF-8-SIG."""
        with open(target_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
            writer.writerows(rows)


class JsonTranslator(BaseTranslator):
    """
    Handles translation of JSON (.json) files, tailored for localization (i18n).
    Strictly preserves object keys, numeric/boolean data, and interpolation variables
    (e.g., {username}, %s, {{count}}), translating only string values.
    """

    @classmethod
    def _traverse_json(cls, data: Any, on_string: Callable[[str], None]):
        """Recursively traverses JSON data and calls on_string for string values."""
        if isinstance(data, dict):
            for k, v in data.items():
                cls._traverse_json(v, on_string)
        elif isinstance(data, list):
            for item in data:
                cls._traverse_json(item, on_string)
        elif isinstance(data, str):
            if _should_translate_cell(data):
                on_string(data)

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects JSON to count keys, translatable string values, and unique texts."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "json", "error": "File not found"}

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)

            key_count = 0
            string_count = 0
            unique_texts: Set[str] = set()

            def count_visitor(node: Any):
                nonlocal key_count, string_count
                if isinstance(node, dict):
                    key_count += len(node)
                    for v in node.values():
                        count_visitor(v)
                elif isinstance(node, list):
                    for item in node:
                        count_visitor(item)
                elif isinstance(node, str):
                    if _should_translate_cell(node):
                        string_count += 1
                        unique_texts.add(node.strip())

            count_visitor(data)
            return {
                "type": "json",
                "total_keys": key_count,
                "translatable_strings": string_count,
                "unique_texts": len(unique_texts)
            }
        except Exception as e:
            return {"type": "json", "error": str(e)}

    def process_file(
        self,
        file_path: str,
        target_lang: Optional[str] = None,
        source_lang: Optional[str] = "auto",
        options: Optional[TranslationOptions] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        custom_output_path: Optional[str] = None,
        *args,
        **kwargs
    ) -> str:
        """Translates string values in JSON."""
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang = target_lang or "Vietnamese"
        options = options or self.config.translation_options

        if progress_callback:
            progress_callback(5, 100, "Reading JSON document...")

        with open(src, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        unique_texts: Set[str] = set()
        self._traverse_json(data, lambda s: unique_texts.add(s.strip()))

        unique_list = list(unique_texts)
        total_unique = len(unique_list)

        if not unique_list:
            out_path = get_smart_output_path(src, target_lang=target_lang, custom_output_path=custom_output_path)
            safe_save_file(lambda p: self._save_json(p, data), out_path)
            if progress_callback:
                progress_callback(100, 100, "File contains no translatable text.")
            return str(out_path)

        if progress_callback:
            progress_callback(10, 100, f"Found {total_unique} translatable phrases. Checking cache...")

        translation_map: Dict[str, str] = {}
        uncached_texts: List[str] = []

        for text in unique_list:
            cached = self.cache.get(text, target_lang)
            if cached:
                translation_map[text] = cached
            else:
                uncached_texts.append(text)

        if uncached_texts:
            batch_size = max(5, getattr(self.config, "batch_size", 20))
            batches = [uncached_texts[i:i + batch_size] for i in range(0, len(uncached_texts), batch_size)]
            total_batches = len(batches)
            completed_batches = 0

            def translate_worker(batch: List[str]) -> List[str]:
                if self.is_cancelled:
                    raise InterruptedError("Translation cancelled by user.")
                return self.llm_manager.translate_batch(
                    texts=batch,
                    target_lang=target_lang,
                    source_lang=source_lang,
                    options=options
                )

            max_workers = min(3, max(1, total_batches))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(translate_worker, b): b for b in batches}
                for future in as_completed(futures):
                    if self.is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise InterruptedError("Translation cancelled by user.")

                    orig_batch = futures[future]
                    try:
                        translated_batch = future.result()
                        for orig, trans in zip(orig_batch, translated_batch):
                            translation_map[orig] = trans
                            self.cache.set(orig, target_lang, trans)
                    except Exception as e:
                        if self.is_cancelled:
                            raise InterruptedError("Translation cancelled by user.")
                        raise e

                    completed_batches += 1
                    pct = 10 + int(completed_batches / total_batches * 75)
                    if progress_callback:
                        progress_callback(pct, 100, f"Translating batch {completed_batches}/{total_batches}...")

        if self.is_cancelled:
            raise InterruptedError("Translation cancelled by user.")

        if progress_callback:
            progress_callback(90, 100, "Reconstructing translated JSON...")

        def replace_values(node: Any) -> Any:
            if isinstance(node, dict):
                return {k: replace_values(v) for k, v in node.items()}
            elif isinstance(node, list):
                return [replace_values(item) for item in node]
            elif isinstance(node, str):
                trimmed = node.strip()
                if _should_translate_cell(node) and trimmed in translation_map:
                    prefix = node[:len(node) - len(node.lstrip())]
                    suffix = node[len(node.rstrip()):]
                    return f"{prefix}{translation_map[trimmed]}{suffix}"
                return node
            return node

        translated_data = replace_values(data)

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=".json",
            custom_output_path=custom_output_path
        )
        saved_path = safe_save_file(lambda p: self._save_json(p, translated_data), out_path)

        if progress_callback:
            progress_callback(100, 100, f"Saved: {saved_path.name}")

        return str(saved_path)

    @staticmethod
    def _save_json(target_path: Path, data: Any):
        """Saves data to JSON with UTF-8 and 2-space indentation."""
        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


class TextTranslator(BaseTranslator):
    """
    Handles translation of plain text (.txt) files.
    Chunks text into readable sections, translates with LLM, and preserves blank lines.
    """

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects plain text to count lines, words, and characters."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "txt", "error": "File not found"}

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            lines = content.splitlines()
            words = len(content.split())
            return {
                "type": "txt",
                "char_count": len(content),
                "word_count": words,
                "line_count": len(lines)
            }
        except Exception as e:
            return {"type": "txt", "error": str(e)}

    def process_file(
        self,
        file_path: str,
        target_lang: Optional[str] = None,
        source_lang: Optional[str] = "auto",
        options: Optional[TranslationOptions] = None,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        custom_output_path: Optional[str] = None,
        *args,
        **kwargs
    ) -> str:
        """Translates plain text document."""
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang = target_lang or "Vietnamese"
        options = options or self.config.translation_options

        if progress_callback:
            progress_callback(5, 100, "Reading text file...")

        with open(src, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        if not content.strip():
            out_path = get_smart_output_path(src, target_lang=target_lang, custom_output_path=custom_output_path)
            safe_save_file(lambda p: p.write_text(content, encoding="utf-8"), out_path)
            return str(out_path)

        # Chunk into double-newline sections
        sections = content.split("\n\n")
        chunks: List[str] = []
        curr_chunk: List[str] = []
        curr_len = 0

        for sec in sections:
            sec_len = len(sec)
            if curr_len + sec_len > 1500 and curr_chunk:
                chunks.append("\n\n".join(curr_chunk))
                curr_chunk = [sec]
                curr_len = sec_len
            else:
                curr_chunk.append(sec)
                curr_len += sec_len

        if curr_chunk:
            chunks.append("\n\n".join(curr_chunk))

        translated_chunks: List[str] = []
        total_chunks = len(chunks)

        for idx, chunk in enumerate(chunks):
            if self.is_cancelled:
                raise InterruptedError("Translation cancelled by user.")

            if not chunk.strip():
                translated_chunks.append(chunk)
                continue

            cached = self.cache.get(chunk, target_lang)
            if cached:
                translated_chunks.append(cached)
            else:
                translated = self.llm_manager.translate_markdown_text(
                    markdown_text=chunk,
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang
                )
                self.cache.set(chunk, target_lang, translated)
                translated_chunks.append(translated)

            pct = 10 + int((idx + 1) / total_chunks * 80)
            if progress_callback:
                progress_callback(pct, 100, f"Translated section {idx + 1}/{total_chunks}...")

        final_content = "\n\n".join(translated_chunks)
        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=".txt",
            custom_output_path=custom_output_path
        )
        saved_path = safe_save_file(lambda p: p.write_text(final_content, encoding="utf-8"), out_path)

        if progress_callback:
            progress_callback(100, 100, f"Saved: {saved_path.name}")

        return str(saved_path)
