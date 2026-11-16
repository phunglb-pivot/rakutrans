"""
Parsers for CSV/TSV, JSON, and Plain Text files in RakuTrans AI.
Provides:
- CsvTranslator: Handles .csv and .tsv spreadsheets with dialect and encoding support.
- JsonTranslator: Handles .json localization and config files preserving keys & variables.
- TextTranslator: Handles .txt plain text documents with chunked concurrent translation.
"""

import csv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import List, Dict, Set, Callable, Optional, Any, Tuple

from base_translator import (
    BaseTranslator,
    count_words_multilingual,
    detect_text_encoding,
    safe_save_file,
    should_translate_text,
)
from config import TranslationOptions, get_smart_output_path


def _should_translate_cell(val: Any) -> bool:
    """Checks if a cell or string value should be translated."""
    return should_translate_text(val, ignore_formulas=True)


def _detect_encoding(file_path: Path) -> str:
    """Detects encoding deterministically using BOM, strict UTF-8, and charset detection."""
    return detect_text_encoding(file_path)


class CsvTranslator(BaseTranslator):
    """
    Handles translation of CSV (.csv) and TSV (.tsv) spreadsheet files.
    Preserves table structure, delimiters, quotes, and numeric data.
    Outputs UTF-8-SIG to ensure Microsoft Excel correctly displays accents on all OSes.
    """

    @classmethod
    def _detect_delimiter(cls, file_path: Path, encoding: str) -> str:
        """Determines whether file uses comma, tab, semicolon, or pipe deterministically."""
        if file_path.suffix.lower() == ".tsv":
            return "\t"
        try:
            with open(file_path, "r", encoding=encoding, errors="replace") as f:
                sample = f.read(8192)
            lines = [ln for ln in sample.splitlines() if ln.strip()][:20]
            if len(lines) >= 2:
                dialect = csv.Sniffer().sniff("\n".join(lines), delimiters=[",", "\t", ";", "|"])
                if dialect.delimiter in (",", "\t", ";", "|"):
                    return dialect.delimiter
        except Exception:
            pass
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
                "delimiter": delimiter,
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
        **kwargs,
    ) -> str:
        """Translates CSV/TSV table rows."""
        self._is_cancelled = False
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )

        if progress_callback:
            progress_callback(5, 100, "Reading CSV table...")

        enc = _detect_encoding(src)
        delimiter = self._detect_delimiter(src, enc)

        rows: List[List[str]] = []
        with open(src, "r", encoding=enc, errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            for row in reader:
                rows.append(row)

        unique_texts = list(
            dict.fromkeys(
                cell.strip() for row in rows for cell in row if _should_translate_cell(cell)
            )
        )
        total_unique = len(unique_texts)

        if not unique_texts:
            out_path = get_smart_output_path(
                src, target_lang=target_lang, custom_output_path=custom_output_path
            )
            saved_path = safe_save_file(lambda p: self._write_csv(p, rows, delimiter), out_path)
            if progress_callback:
                progress_callback(100, 100, "File contains no translatable text.")
            return str(saved_path)

        if progress_callback:
            progress_callback(10, 100, f"Found {total_unique} unique cells. Checking cache...")

        translation_map = self.translate_unique_texts(
            unique_texts=unique_texts,
            target_lang=target_lang,
            source_lang=source_lang,
            options=options,
            progress_callback=progress_callback,
            progress_start=10,
            progress_span=75,
        )

        if self.is_cancelled:
            raise InterruptedError("Translation cancelled by user.")

        if progress_callback:
            progress_callback(90, 100, "Applying translations to CSV...")

        translated_rows: List[List[str]] = []
        for row in rows:
            new_row = []
            for cell in row:
                trimmed = cell.strip()
                if _should_translate_cell(cell) and trimmed in translation_map:
                    prefix = cell[: len(cell) - len(cell.lstrip())]
                    suffix = cell[len(cell.rstrip()) :]
                    new_row.append(f"{prefix}{translation_map[trimmed]}{suffix}")
                else:
                    new_row.append(cell)
            translated_rows.append(new_row)

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=src.suffix,
            custom_output_path=custom_output_path,
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
            for v in data.values():
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
            enc = _detect_encoding(path)
            with open(path, "r", encoding=enc, errors="replace") as f:
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
                "unique_texts": len(unique_texts),
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
        **kwargs,
    ) -> str:
        """Translates string values in JSON."""
        self._is_cancelled = False
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )

        if progress_callback:
            progress_callback(5, 100, "Reading JSON document...")

        enc = _detect_encoding(src)
        with open(src, "r", encoding=enc, errors="replace") as f:
            data = json.load(f)

        ordered_unique: Dict[str, None] = {}
        self._traverse_json(data, lambda s: ordered_unique.setdefault(s.strip(), None))
        unique_list = list(ordered_unique.keys())
        total_unique = len(unique_list)

        if not unique_list:
            out_path = get_smart_output_path(
                src, target_lang=target_lang, custom_output_path=custom_output_path
            )
            saved_path = safe_save_file(lambda p: self._save_json(p, data), out_path)
            if progress_callback:
                progress_callback(100, 100, "File contains no translatable text.")
            return str(saved_path)

        if progress_callback:
            progress_callback(10, 100, f"Found {total_unique} translatable phrases. Checking cache...")

        translation_map = self.translate_unique_texts(
            unique_texts=unique_list,
            target_lang=target_lang,
            source_lang=source_lang,
            options=options,
            progress_callback=progress_callback,
            progress_start=10,
            progress_span=75,
        )

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
                    prefix = node[: len(node) - len(node.lstrip())]
                    suffix = node[len(node.rstrip()) :]
                    return f"{prefix}{translation_map[trimmed]}{suffix}"
                return node
            return node

        translated_data = replace_values(data)

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=".json",
            custom_output_path=custom_output_path,
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
    Chunks text along paragraph/line boundaries, translates concurrently with LLM,
    and preserves blank lines and original structure.
    """

    @staticmethod
    def _split_text_chunks(content: str, max_chars: int = 3000) -> List[Tuple[str, str]]:
        """
        Splits text into (chunk_text, join_sep_after_chunk) tuples preserving exact paragraph/line boundaries.
        """
        if len(content) <= max_chars:
            return [(content, "")]

        paragraphs = content.split("\n\n")
        atomic_units: List[Tuple[str, str]] = []

        for p_idx, para in enumerate(paragraphs):
            sep_after = "\n\n" if p_idx < len(paragraphs) - 1 else ""
            if len(para) <= max_chars:
                atomic_units.append((para, sep_after))
            else:
                lines = para.split("\n")
                for l_idx, ln in enumerate(lines):
                    l_sep = "\n" if l_idx < len(lines) - 1 else sep_after
                    atomic_units.append((ln, l_sep))

        chunks: List[Tuple[str, str]] = []
        buf_parts: List[str] = []
        buf_len = 0

        for idx, (unit, sep_after) in enumerate(atomic_units):
            unit_len = len(unit)
            if buf_parts and (buf_len + unit_len > max_chars):
                # Flush previous accumulated chunk without trailing sep; sep belongs between chunks
                prev_text = "".join(buf_parts[:-1]) if len(buf_parts) > 1 else buf_parts[0]
                prev_sep = buf_parts[-1] if len(buf_parts) > 1 else ""
                chunks.append((prev_text, prev_sep))
                buf_parts = [unit]
                if sep_after and idx < len(atomic_units) - 1:
                    buf_parts.append(sep_after)
                buf_len = unit_len + len(sep_after)
            else:
                buf_parts.append(unit)
                buf_len += unit_len
                if sep_after and idx < len(atomic_units) - 1:
                    buf_parts.append(sep_after)
                    buf_len += len(sep_after)

        if buf_parts:
            chunks.append(("".join(buf_parts), ""))

        return chunks

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects plain text to count lines, words, and characters."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "txt", "error": "File not found"}

        try:
            enc = _detect_encoding(path)
            with open(path, "r", encoding=enc, errors="replace") as f:
                content = f.read()

            lines = content.splitlines()
            words = count_words_multilingual(content)
            return {
                "type": "txt",
                "char_count": len(content),
                "word_count": words,
                "line_count": len(lines),
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
        **kwargs,
    ) -> str:
        """Translates plain text document concurrently with option-aware caching."""
        self._is_cancelled = False
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )

        if progress_callback:
            progress_callback(5, 100, "Reading text file...")

        enc = _detect_encoding(src)
        with open(src, "r", encoding=enc, errors="replace") as f:
            content = f.read()

        if not content.strip():
            out_path = get_smart_output_path(
                src, target_lang=target_lang, custom_output_path=custom_output_path
            )
            saved_path = safe_save_file(lambda p: p.write_text(content, encoding="utf-8"), out_path)
            if progress_callback:
                progress_callback(100, 100, "File contains no translatable text.")
            return str(saved_path)

        chunk_specs = self._split_text_chunks(content)
        total_chunks = len(chunk_specs)
        translated_texts: List[Optional[str]] = [None] * total_chunks

        translatable_indices: List[int] = []
        translatable_inputs: List[str] = []
        for idx, (chunk_text, _) in enumerate(chunk_specs):
            if not chunk_text.strip():
                translated_texts[idx] = chunk_text
            else:
                translatable_indices.append(idx)
                translatable_inputs.append(chunk_text)

        model_id = self._get_cache_model_id()
        cached_map, uncached_items = self.cache.get_batch(
            texts=translatable_inputs,
            target_lang=target_lang,
            options=options,
            source_lang=source_lang,
            mode="text",
            model_id=model_id,
        )

        for local_idx, trans_val in cached_map.items():
            translated_texts[translatable_indices[local_idx]] = trans_val

        completed_count = len(cached_map)
        total_translatable = len(translatable_inputs)

        if uncached_items:
            def translate_chunk(item: Tuple[int, str]) -> Tuple[int, str]:
                local_idx, chunk_text = item
                if self.is_cancelled:
                    raise InterruptedError("Translation cancelled by user.")
                trans = self.llm_manager.translate_markdown_text(
                    markdown_text=chunk_text,
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang,
                    cancel_check=lambda: self.is_cancelled,
                    plain_text=True,
                )
                self.cache.save_batch(
                    source_texts=[chunk_text],
                    translated_texts=[trans],
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang,
                    mode="text",
                    model_id=model_id,
                )
                return local_idx, trans

            max_workers = self.get_max_workers(len(uncached_items))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(translate_chunk, item): item[0] for item in uncached_items}
                for future in as_completed(futures):
                    if self.is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise InterruptedError("Translation cancelled by user.")
                    local_idx, trans = future.result()
                    translated_texts[translatable_indices[local_idx]] = trans
                    completed_count += 1
                    pct = 10 + int((completed_count / max(1, total_translatable)) * 80)
                    if progress_callback:
                        progress_callback(
                            pct, 100, f"Translated section {completed_count}/{total_translatable}..."
                        )

        parts: List[str] = []
        for idx, (chunk_text, sep_after) in enumerate(chunk_specs):
            t_val = translated_texts[idx]
            parts.append(chunk_text if t_val is None else t_val)
            if sep_after:
                parts.append(sep_after)
        final_content = "".join(parts)

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=".txt",
            custom_output_path=custom_output_path,
        )
        saved_path = safe_save_file(lambda p: p.write_text(final_content, encoding="utf-8"), out_path)

        if progress_callback:
            progress_callback(100, 100, f"Saved: {saved_path.name}")

        return str(saved_path)
