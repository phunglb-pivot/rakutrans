"""
Parsers for CSV/TSV, JSON, and Plain Text files in RakuTrans AI.
Provides:
- CsvTranslator: Handles .csv and .tsv spreadsheets with dialect and encoding support.
- JsonTranslator: Handles .json localization and config files preserving keys & variables.
- TextTranslator: Handles .txt plain text documents with chunked concurrent translation.
"""

import csv
import json
import sys
from pathlib import Path
from typing import List, Dict, Set, Callable, Optional, Any, Tuple

_MAX_CSV_FIELD_LIMIT_BYTES = 10 * 1024 * 1024
_MIN_CSV_FIELD_LIMIT_BYTES = 131072
_CSV_SNIFF_BYTES = 8192
_CSV_SNIFF_MAX_LINES = 20
_CSV_CANDIDATE_DELIMITERS = (",", "\t", ";", "|")
_CSV_OUTPUT_ENCODING = "utf-8-sig"
_DEFAULT_TEXT_CHUNK_CHARS = 3000


def _ensure_large_csv_field_limit() -> None:
    """Raises csv.field_size_limit safely (up to 10 MiB) to handle large CSV cells."""
    target = min(sys.maxsize, _MAX_CSV_FIELD_LIMIT_BYTES)
    if csv.field_size_limit() >= target:
        return
    while target > _MIN_CSV_FIELD_LIMIT_BYTES:
        try:
            csv.field_size_limit(target)
            return
        except OverflowError:
            target //= 2

from rakutrans.parsers.base_translator import (
    BaseTranslator,
    count_words_multilingual,
    detect_text_encoding,
    safe_save_file,
    should_translate_text,
)
from rakutrans.core.config import TranslationOptions, get_smart_output_path, resolve_config_int


def _apply_trimmed_translation(raw: str, translation_map: Dict[str, str]) -> str:
    """Replaces trimmed translatable content while preserving leading/trailing whitespace."""
    trimmed = raw.strip()
    if should_translate_text(raw, ignore_formulas=True) and trimmed in translation_map:
        prefix = raw[: len(raw) - len(raw.lstrip())]
        suffix = raw[len(raw.rstrip()) :]
        return f"{prefix}{translation_map[trimmed]}{suffix}"
    return raw


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
                sample = f.read(_CSV_SNIFF_BYTES)
            non_empty = [ln for ln in sample.splitlines() if ln.strip()]
            if not non_empty:
                return ","
            sniff_sample = "\n".join(non_empty[:_CSV_SNIFF_MAX_LINES])
            try:
                dialect = csv.Sniffer().sniff(sniff_sample, delimiters=list(_CSV_CANDIDATE_DELIMITERS))
                if dialect.delimiter in _CSV_CANDIDATE_DELIMITERS:
                    return dialect.delimiter
            except Exception:
                # Fallback for single-row files where Sniffer refuses to guess
                first_line = non_empty[0]
                best_delim = ","
                best_count = 0
                for cand in (",", ";", "\t", "|"):
                    parsed_cols = next(csv.reader([first_line], delimiter=cand), [])
                    if len(parsed_cols) > best_count:
                        best_count = len(parsed_cols)
                        best_delim = cand
                if best_count > 1:
                    return best_delim
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
            _ensure_large_csv_field_limit()
            enc = detect_text_encoding(path)
            delimiter = cls._detect_delimiter(path, enc)
            row_count = 0
            max_cols = 0
            translatable_cells = 0
            total_chars = 0
            unique_texts: Set[str] = set()

            with open(path, "r", encoding=enc, errors="replace") as f:
                reader = csv.reader(f, delimiter=delimiter)
                for row in reader:
                    if not row:
                        continue
                    row_count += 1
                    max_cols = max(max_cols, len(row))
                    for cell in row:
                        if should_translate_text(cell, ignore_formulas=True):
                            trimmed = cell.strip()
                            translatable_cells += 1
                            total_chars += len(trimmed)
                            unique_texts.add(trimmed)

            return {
                "type": "csv",
                "rows": row_count,
                "columns": max_cols,
                "translatable_cells": translatable_cells,
                "unique_texts": len(unique_texts),
                "char_count": total_chars,
                "unique_char_count": sum(len(t) for t in unique_texts),
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
            progress_callback(5, 100, self._t("progress_reading_csv"))

        _ensure_large_csv_field_limit()
        enc = detect_text_encoding(src)
        delimiter = self._detect_delimiter(src, enc)

        rows: List[List[str]] = []
        with open(src, "r", encoding=enc, errors="replace") as f:
            reader = csv.reader(f, delimiter=delimiter)
            for row in reader:
                rows.append(row)

        unique_texts = list(
            dict.fromkeys(
                cell.strip() for row in rows for cell in row
                if should_translate_text(cell, ignore_formulas=True)
            )
        )
        total_unique = len(unique_texts)

        if not unique_texts:
            out_path = get_smart_output_path(
                src, target_lang=target_lang, custom_output_path=custom_output_path
            )
            saved_path = safe_save_file(lambda p: self._write_csv(p, rows, delimiter), out_path)
            if progress_callback:
                progress_callback(100, 100, self._t("progress_no_translatable_file"))
            return str(saved_path)

        if progress_callback:
            progress_callback(10, 100, self._t("progress_found_cells", count=total_unique))

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
            progress_callback(90, 100, self._t("progress_applying_csv"))

        translated_rows: List[List[str]] = [
            [_apply_trimmed_translation(cell, translation_map) for cell in row]
            for row in rows
        ]

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=src.suffix,
            custom_output_path=custom_output_path,
        )
        saved_path = safe_save_file(lambda p: self._write_csv(p, translated_rows, delimiter), out_path)

        if progress_callback:
            progress_callback(100, 100, self._t("progress_saved_file", filename=saved_path.name))

        return str(saved_path)

    @staticmethod
    def _write_csv(target_path: Path, rows: List[List[str]], delimiter: str):
        """Writes rows to file using UTF-8-SIG."""
        with open(target_path, "w", encoding=_CSV_OUTPUT_ENCODING, newline="") as f:
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
        """Iteratively traverses JSON data (immune to deep-nesting RecursionError) and calls on_string for translatable strings."""
        stack = [data]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                stack.extend(reversed(list(node.values())))
            elif isinstance(node, list):
                stack.extend(reversed(node))
            elif isinstance(node, str):
                if should_translate_text(node, ignore_formulas=True):
                    on_string(node)

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects JSON to count keys, translatable string values, and unique texts."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "json", "error": "File not found"}

        try:
            enc = detect_text_encoding(path)
            with open(path, "r", encoding=enc, errors="replace") as f:
                data = json.load(f)

            key_count = 0
            string_count = 0
            total_chars = 0
            unique_texts: Set[str] = set()

            stack = [data]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    key_count += len(node)
                    stack.extend(reversed(list(node.values())))
                elif isinstance(node, list):
                    stack.extend(reversed(node))
                elif isinstance(node, str):
                    if should_translate_text(node, ignore_formulas=True):
                        trimmed = node.strip()
                        string_count += 1
                        total_chars += len(trimmed)
                        unique_texts.add(trimmed)

            return {
                "type": "json",
                "total_keys": key_count,
                "translatable_strings": string_count,
                "unique_texts": len(unique_texts),
                "char_count": total_chars,
                "unique_char_count": sum(len(t) for t in unique_texts),
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
            progress_callback(5, 100, self._t("progress_reading_json"))

        enc = detect_text_encoding(src)
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
                progress_callback(100, 100, self._t("progress_no_translatable_file"))
            return str(saved_path)

        if progress_callback:
            progress_callback(10, 100, self._t("progress_found_phrases", count=total_unique))

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
            progress_callback(90, 100, self._t("progress_rebuilding_json"))

        def replace_values(root: Any) -> Any:
            if not isinstance(root, (dict, list)):
                if isinstance(root, str):
                    return _apply_trimmed_translation(root, translation_map)
                return root

            root_copy: Any = {} if isinstance(root, dict) else []
            stack: List[Tuple[Any, Any]] = [(root, root_copy)]
            while stack:
                src_node, dst_node = stack.pop()
                if isinstance(src_node, dict):
                    for k, v in src_node.items():
                        if isinstance(v, dict):
                            child_d: Dict[str, Any] = {}
                            dst_node[k] = child_d
                            stack.append((v, child_d))
                        elif isinstance(v, list):
                            child_l: List[Any] = []
                            dst_node[k] = child_l
                            stack.append((v, child_l))
                        elif isinstance(v, str):
                            dst_node[k] = _apply_trimmed_translation(v, translation_map)
                        else:
                            dst_node[k] = v
                else:
                    for item in src_node:
                        if isinstance(item, dict):
                            child_d = {}
                            dst_node.append(child_d)
                            stack.append((item, child_d))
                        elif isinstance(item, list):
                            child_l = []
                            dst_node.append(child_l)
                            stack.append((item, child_l))
                        elif isinstance(item, str):
                            dst_node.append(_apply_trimmed_translation(item, translation_map))
                        else:
                            dst_node.append(item)
            return root_copy

        translated_data = replace_values(data)

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=".json",
            custom_output_path=custom_output_path,
        )
        saved_path = safe_save_file(lambda p: self._save_json(p, translated_data), out_path)

        if progress_callback:
            progress_callback(100, 100, self._t("progress_saved_file", filename=saved_path.name))

        return str(saved_path)

    @staticmethod
    def _save_json(target_path: Path, data: Any):
        """Saves data to JSON with UTF-8 and 2-space indentation (falling back to iterative dump on deep nesting)."""
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except RecursionError:
            with open(target_path, "w", encoding="utf-8") as f:
                JsonTranslator._dump_json_iterative(f, data, indent=2)

    @staticmethod
    def _dump_json_iterative(fp, data: Any, indent: int = 2) -> None:
        """Iterative JSON encoder for arbitrarily deep JSON trees beyond Python's recursion limit."""
        stack: List[Tuple[str, Any, int]] = [("val", data, 0)]
        while stack:
            op, payload, depth = stack.pop()
            if op == "str":
                fp.write(payload)
            elif op == "val":
                if isinstance(payload, dict):
                    if not payload:
                        fp.write("{}")
                    else:
                        fp.write("{\n")
                        pad = " " * ((depth + 1) * indent)
                        close_pad = " " * (depth * indent)
                        stack.append(("str", f"\n{close_pad}}}", depth))
                        items = list(payload.items())
                        for idx in range(len(items) - 1, -1, -1):
                            k, v = items[idx]
                            if idx < len(items) - 1:
                                stack.append(("str", ",\n", depth))
                            stack.append(("val", v, depth + 1))
                            stack.append(("str", f"{pad}{json.dumps(str(k), ensure_ascii=False)}: ", depth))
                elif isinstance(payload, list):
                    if not payload:
                        fp.write("[]")
                    else:
                        fp.write("[\n")
                        pad = " " * ((depth + 1) * indent)
                        close_pad = " " * (depth * indent)
                        stack.append(("str", f"\n{close_pad}]", depth))
                        for idx in range(len(payload) - 1, -1, -1):
                            if idx < len(payload) - 1:
                                stack.append(("str", ",\n", depth))
                            stack.append(("val", payload[idx], depth + 1))
                            stack.append(("str", pad, depth))
                else:
                    fp.write(json.dumps(payload, ensure_ascii=False))


class TextTranslator(BaseTranslator):
    """
    Handles translation of plain text (.txt) files.
    Chunks text along paragraph/line boundaries, translates concurrently with LLM,
    and preserves blank lines and original structure.
    """

    @staticmethod
    def _split_long_line(line: str, max_chars: int) -> List[str]:
        """Splits an oversized single line (> max_chars) along whitespace without dropping chars."""
        if len(line) <= max_chars:
            return [line]
        parts: List[str] = []
        start = 0
        n = len(line)
        while start < n:
            if n - start <= max_chars:
                parts.append(line[start:])
                break
            split_at = line.rfind(" ", start, start + max_chars + 1)
            if split_at <= start:
                split_at = start + max_chars
            else:
                split_at += 1  # Keep trailing space with left piece so exact join == original
            parts.append(line[start:split_at])
            start = split_at
        return parts

    @classmethod
    def _split_text_chunks(
        cls, content: str, max_chars: int = _DEFAULT_TEXT_CHUNK_CHARS
    ) -> List[Tuple[str, str]]:
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
                    if len(ln) <= max_chars:
                        atomic_units.append((ln, l_sep))
                    else:
                        sub_parts = cls._split_long_line(ln, max_chars)
                        for s_idx, sub in enumerate(sub_parts):
                            s_sep = "" if s_idx < len(sub_parts) - 1 else l_sep
                            atomic_units.append((sub, s_sep))

        chunks: List[Tuple[str, str]] = []
        buf_text = ""
        pending_sep = ""

        for unit, sep_after in atomic_units:
            if not buf_text and not pending_sep:
                buf_text = unit
                pending_sep = sep_after
                continue

            if not buf_text and pending_sep:
                # Leading blank lines before any non-empty content
                chunks.append(("", pending_sep))
                buf_text = unit
                pending_sep = sep_after
                continue

            if not unit and sep_after:
                # Consecutive blank lines: keep whitespace in separator rather than inside buf_text
                pending_sep += sep_after
                continue

            candidate_len = len(buf_text) + len(pending_sep) + len(unit)
            if candidate_len > max_chars:
                chunks.append((buf_text, pending_sep))
                buf_text = unit
                pending_sep = sep_after
            else:
                buf_text = f"{buf_text}{pending_sep}{unit}"
                pending_sep = sep_after

        if buf_text or pending_sep:
            chunks.append((buf_text, pending_sep))

        return chunks

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects plain text to count lines, words, and characters."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "txt", "error": "File not found"}

        try:
            enc = detect_text_encoding(path)
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
            progress_callback(5, 100, self._t("progress_reading_txt"))

        enc = detect_text_encoding(src)
        with open(src, "r", encoding=enc, errors="replace") as f:
            content = f.read()

        if not content.strip():
            out_path = get_smart_output_path(
                src, target_lang=target_lang, custom_output_path=custom_output_path
            )
            saved_path = safe_save_file(lambda p: p.write_text(content, encoding="utf-8"), out_path)
            if progress_callback:
                progress_callback(100, 100, self._t("progress_no_translatable_file"))
            return str(saved_path)

        section_max_chars = resolve_config_int(self.config, "section_max_chars")
        chunk_specs = self._split_text_chunks(content, max_chars=section_max_chars)
        section_inputs = [chunk_text for chunk_text, _ in chunk_specs if chunk_text.strip()]
        section_map = self.translate_unique_sections(
            sections=section_inputs,
            target_lang=target_lang,
            source_lang=source_lang,
            options=options,
            mode="text",
            plain_text=True,
            progress_callback=progress_callback,
            progress_start=10,
            progress_span=80,
            progress_formatter=lambda done, total, _hits: self._t(
                "progress_text_section", done=done, total=total
            ),
        )

        parts: List[str] = []
        for chunk_text, sep_after in chunk_specs:
            if not chunk_text.strip():
                parts.append(chunk_text)
            else:
                parts.append(section_map.get(chunk_text, chunk_text))
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
            progress_callback(100, 100, self._t("progress_saved_file", filename=saved_path.name))

        return str(saved_path)
