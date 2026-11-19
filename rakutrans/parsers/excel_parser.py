"""
Excel parsing and translation engine for RakuTrans AI.
Uses openpyxl to translate multi-sheet workbooks while strictly preserving
all formulas, formatting, styles, dimensions, and structural properties.
"""

from pathlib import Path
from typing import List, Tuple, Callable, Optional, Set, Any
import openpyxl
from openpyxl.comments import Comment
try:
    from openpyxl.cell.rich_text import CellRichText
except ImportError:
    CellRichText = None
try:
    from openpyxl.worksheet.formula import ArrayFormula
except ImportError:
    ArrayFormula = None

from rakutrans.parsers.base_translator import BaseTranslator, safe_save_file, should_translate_text
from rakutrans.core.config import AppConfig, TranslationOptions, get_smart_output_path
from rakutrans.llm.llm_manager import LLMManager
from rakutrans.llm.translation_cache import TranslationCache

_EXCEL_SHEET_TITLE_MAX_LEN = 31
_ARCHIVE_SHEET_SUFFIX = "_Orig"
_ARCHIVE_PREFIX_MAX_LEN = _EXCEL_SHEET_TITLE_MAX_LEN - len(_ARCHIVE_SHEET_SUFFIX)


def _is_excel_formula(val: Any) -> bool:
    if val is None:
        return False
    if ArrayFormula is not None and isinstance(val, ArrayFormula):
        return True
    return isinstance(val, str) and val.strip().startswith("=")


def _extract_cell_str(val: Any) -> Any:
    if CellRichText is not None and isinstance(val, CellRichText):
        return str(val)
    return val


def load_workbook_safe(file_path: str, data_only: bool = False, read_only: bool = True) -> openpyxl.Workbook:
    """Loads an Excel workbook, falling back to read_only=False when openpyxl hits Chartsheet read_only bugs."""
    try:
        return openpyxl.load_workbook(filename=file_path, data_only=data_only, read_only=read_only)
    except AttributeError:
        if read_only:
            return openpyxl.load_workbook(filename=file_path, data_only=data_only, read_only=False)
        raise


def _unique_orig_sheet_title(sheet_name: str, existing_names: Set[str]) -> str:
    """Generates a unique <=31 char archive worksheet title avoiding prefix collisions."""
    candidate = f"{sheet_name[:_ARCHIVE_PREFIX_MAX_LEN]}{_ARCHIVE_SHEET_SUFFIX}"
    if candidate not in existing_names:
        return candidate
    idx = 1
    while True:
        suffix = f"{_ARCHIVE_SHEET_SUFFIX}_{idx}"
        candidate = f"{sheet_name[: max(1, _EXCEL_SHEET_TITLE_MAX_LEN - len(suffix))]}{suffix}"
        if candidate not in existing_names:
            return candidate
        idx += 1


class ExcelTranslator(BaseTranslator):
    """
    Handles translation of Excel (.xlsx) files.
    Preserves formulas, sheet order, cell styles, merged cells, and formatting.
    Features in-file deduplication and local Translation Memory to avoid redundant API calls.
    Supports concurrent multi-threaded batching for maximum translation speed.
    Supports safe-save against Excel file locking and optional bilingual sheet export.
    """

    SUPPORTS_BILINGUAL: bool = True

    def __init__(
        self,
        config: AppConfig,
        llm_manager: LLMManager,
        cache: Optional[TranslationCache] = None,
    ):
        super().__init__(config, llm_manager, cache)

    @staticmethod
    def should_translate_cell(value: Any) -> bool:
        """
        Determines whether a cell value should be translated.
        Strictly ignores numbers, booleans, empty cells, punctuation-only strings, and formulas.
        Supports openpyxl CellRichText values.
        """
        if _is_excel_formula(value):
            return False
        return should_translate_text(_extract_cell_str(value), ignore_formulas=True)

    @classmethod
    def inspect_file(cls, file_path: str) -> dict:
        """
        Quickly inspects an Excel workbook to extract metadata:
        sheet count, translatable cell count, and formula count.
        """
        path = Path(file_path)
        if not path.exists():
            return {"error": "File not found"}

        try:
            wb = load_workbook_safe(file_path, data_only=False, read_only=True)
            try:
                worksheets = list(wb.worksheets)
                sheet_names = [ws.title for ws in worksheets]
                translatable_cells = 0
                formula_count = 0
                total_chars = 0
                unique_set = set()

                for ws in worksheets:
                    for row in ws.iter_rows(values_only=True):
                        for val in row:
                            if val is None:
                                continue
                            if _is_excel_formula(val):
                                formula_count += 1
                            else:
                                text_val = _extract_cell_str(val)
                                if should_translate_text(text_val, ignore_formulas=True):
                                    trimmed = text_val.strip()
                                    translatable_cells += 1
                                    total_chars += len(trimmed)
                                    unique_set.add(trimmed)

                return {
                    "type": "excel",
                    "sheet_count": len(sheet_names),
                    "sheet_names": sheet_names,
                    "translatable_cells": translatable_cells,
                    "unique_texts": len(unique_set),
                    "char_count": total_chars,
                    "unique_char_count": sum(len(t) for t in unique_set),
                    "formula_count": formula_count,
                }
            finally:
                wb.close()
        except Exception as e:
            return {"type": "excel", "error": str(e)}

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
        """
        Main processing method for Excel files.
        Extracts translatable text cells, deduplicates unique strings,
        batches uncached items, translates via LLM (with concurrent batching),
        and re-injects translations while strictly preserving formulas and styling.
        Supports safe saving against file lock and optional bilingual sheet duplication.
        Returns the output file path.
        """
        self._is_cancelled = False
        src_path = Path(file_path)
        if not src_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )
        is_bilingual = bool(getattr(options, "bilingual_mode", False))

        if progress_callback:
            progress_callback(0, 100, self._t("progress_loading_excel"))

        # Strict requirement: data_only=False preserves formulas (=SUM, etc.)
        workbook = openpyxl.load_workbook(filename=file_path, data_only=False)
        try:
            translatable_cells: List[Tuple[Any, str]] = []
            translatable_comments: List[Tuple[Any, str]] = []

            for ws in workbook.worksheets:
                for row in ws.iter_rows():
                    for cell in row:
                        val = cell.value
                        if val is not None and self.should_translate_cell(val):
                            translatable_cells.append((cell, str(_extract_cell_str(val))))
                        if cell.comment and should_translate_text(cell.comment.text, ignore_formulas=False):
                            translatable_comments.append((cell, str(cell.comment.text)))

            total_cells = len(translatable_cells) + len(translatable_comments)
            if total_cells == 0:
                target_path = (
                    Path(custom_output_path)
                    if custom_output_path
                    else get_smart_output_path(
                        source_path=src_path,
                        target_lang=target_lang,
                        is_bilingual=is_bilingual,
                    )
                )
                out_file = safe_save_file(lambda p: workbook.save(str(p)), target_path)
                if progress_callback:
                    progress_callback(100, 100, self._t("progress_no_translatable_excel"))
                return str(out_file)

            unique_texts: List[str] = list(
                dict.fromkeys(
                    [orig_val.strip() for _, orig_val in translatable_cells]
                    + [orig_c.strip() for _, orig_c in translatable_comments]
                )
            )
            unique_count = len(unique_texts)
            duplicate_saved = total_cells - unique_count

            if progress_callback:
                progress_callback(
                    5,
                    100,
                    self._t("progress_dedup_excel", unique=unique_count, dedup=duplicate_saved),
                )

            unique_translations = self.translate_unique_texts(
                unique_texts=unique_texts,
                target_lang=target_lang,
                source_lang=source_lang,
                options=options,
                progress_callback=progress_callback,
                progress_start=10,
                progress_span=80,
                duplicate_saved=duplicate_saved,
            )

            if self._is_cancelled:
                raise InterruptedError("Translation was cancelled by user.")

            if is_bilingual:
                if progress_callback:
                    progress_callback(90, 100, self._t("progress_bilingual_excel"))
                orig_worksheets = list(workbook.worksheets)
                existing_names = set(workbook.sheetnames)
                for orig_ws in orig_worksheets:
                    copy_ws = workbook.copy_worksheet(orig_ws)
                    new_title = _unique_orig_sheet_title(orig_ws.title, existing_names)
                    copy_ws.title = new_title
                    existing_names.add(new_title)

            if progress_callback:
                progress_callback(92, 100, self._t("progress_injecting_excel", total=total_cells))

            for cell, orig_val in translatable_cells:
                trimmed = orig_val.strip()
                if trimmed in unique_translations:
                    prefix = orig_val[: len(orig_val) - len(orig_val.lstrip())]
                    suffix = orig_val[len(orig_val.rstrip()) :]
                    cell.value = f"{prefix}{unique_translations[trimmed]}{suffix}"

            for cell, orig_c in translatable_comments:
                trimmed = orig_c.strip()
                if trimmed in unique_translations and cell.comment is not None:
                    prefix = orig_c[: len(orig_c) - len(orig_c.lstrip())]
                    suffix = orig_c[len(orig_c.rstrip()) :]
                    new_comment = Comment(
                        f"{prefix}{unique_translations[trimmed]}{suffix}",
                        cell.comment.author,
                    )
                    new_comment.width = cell.comment.width
                    new_comment.height = cell.comment.height
                    cell.comment = new_comment

            if progress_callback:
                progress_callback(96, 100, self._t("progress_saving_excel"))

            target_path = (
                Path(custom_output_path)
                if custom_output_path
                else get_smart_output_path(
                    source_path=src_path,
                    target_lang=target_lang,
                    is_bilingual=is_bilingual,
                )
            )
            output_path = safe_save_file(lambda p: workbook.save(str(p)), target_path)

            if progress_callback:
                note_key = "progress_saved_lock_note" if output_path.name != target_path.name else "progress_saved_to"
                note = self._t(note_key, filename=output_path.name)
                progress_callback(100, 100, self._t("progress_completed_note", note=note))

            return str(output_path)
        finally:
            workbook.close()
