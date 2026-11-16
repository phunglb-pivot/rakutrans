"""
Excel parsing and translation engine for RakuTrans AI.
Uses openpyxl to translate multi-sheet workbooks while strictly preserving
all formulas, formatting, styles, dimensions, and structural properties.
"""

from pathlib import Path
from typing import List, Tuple, Dict, Callable, Optional, Set
import openpyxl

from base_translator import BaseTranslator, safe_save_file, should_translate_text
from config import AppConfig, TranslationOptions, get_smart_output_path
from llm_manager import LLMManager
from translation_cache import TranslationCache


def safe_save_workbook(workbook: openpyxl.Workbook, target_path: Path) -> Path:
    """
    Saves workbook to target_path. If target_path is locked (e.g. open in Microsoft Excel),
    automatically falls back to target_path (1).xlsx, target_path (2).xlsx to avoid crashing.
    """
    return safe_save_file(lambda p: workbook.save(str(p)), target_path)


def _unique_orig_sheet_title(sheet_name: str, existing_names: Set[str]) -> str:
    """Generates a unique <=31 char archive worksheet title avoiding prefix collisions."""
    candidate = f"{sheet_name[:26]}_Orig"
    if candidate not in existing_names:
        return candidate
    idx = 1
    while True:
        suffix = f"_Orig_{idx}"
        candidate = f"{sheet_name[: max(1, 31 - len(suffix))]}{suffix}"
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

    def __init__(
        self,
        config: AppConfig,
        llm_manager: LLMManager,
        cache: Optional[TranslationCache] = None,
    ):
        super().__init__(config, llm_manager, cache)

    @staticmethod
    def should_translate_cell(value: any) -> bool:
        """
        Determines whether a cell value should be translated.
        Strictly ignores numbers, booleans, empty cells, punctuation-only strings, and formulas.
        """
        return should_translate_text(value, ignore_formulas=True)

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
            wb = openpyxl.load_workbook(filename=file_path, data_only=False, read_only=False)
            try:
                sheet_names = wb.sheetnames
                translatable_cells = 0
                formula_count = 0
                unique_set = set()

                for name in sheet_names:
                    ws = wb[name]
                    for row in ws.iter_rows():
                        for cell in row:
                            val = cell.value
                            if val is not None and isinstance(val, str) and val.strip().startswith("="):
                                formula_count += 1
                            elif cls.should_translate_cell(val):
                                translatable_cells += 1
                                unique_set.add(val.strip())

                return {
                    "type": "excel",
                    "sheet_count": len(sheet_names),
                    "sheet_names": sheet_names,
                    "translatable_cells": translatable_cells,
                    "unique_texts": len(unique_set),
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
            progress_callback(0, 100, "Loading workbook structure & styles...")

        # Strict requirement: data_only=False preserves formulas (=SUM, etc.)
        workbook = openpyxl.load_workbook(filename=file_path, data_only=False)
        try:
            translatable_cells: List[Tuple[str, str, str]] = []

            for sheet_name in workbook.sheetnames:
                ws = workbook[sheet_name]
                for row in ws.iter_rows():
                    for cell in row:
                        if self.should_translate_cell(cell.value):
                            translatable_cells.append((sheet_name, cell.coordinate, cell.value))

            total_cells = len(translatable_cells)
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
                out_file = safe_save_workbook(workbook, target_path)
                if progress_callback:
                    progress_callback(100, 100, "Workbook contains no translatable text.")
                return str(out_file)

            unique_texts: List[str] = list(
                dict.fromkeys(item[2].strip() for item in translatable_cells)
            )
            unique_count = len(unique_texts)
            duplicate_saved = total_cells - unique_count

            if progress_callback:
                progress_callback(
                    5,
                    100,
                    f"Deduplication: {unique_count} unique texts ({duplicate_saved} duplicate cells saved)...",
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
                    progress_callback(90, 100, "Bilingual mode: Archiving original worksheets...")
                orig_sheetnames = list(workbook.sheetnames)
                existing_names = set(orig_sheetnames)
                for s_name in orig_sheetnames:
                    orig_ws = workbook[s_name]
                    copy_ws = workbook.copy_worksheet(orig_ws)
                    new_title = _unique_orig_sheet_title(s_name, existing_names)
                    copy_ws.title = new_title
                    existing_names.add(new_title)

            if progress_callback:
                progress_callback(92, 100, f"Re-injecting {total_cells} cells into workbook...")

            for sheet_name, coord, orig_val in translatable_cells:
                trimmed = orig_val.strip()
                if trimmed in unique_translations:
                    prefix = orig_val[: len(orig_val) - len(orig_val.lstrip())]
                    suffix = orig_val[len(orig_val.rstrip()) :]
                    workbook[sheet_name][coord].value = f"{prefix}{unique_translations[trimmed]}{suffix}"

            if progress_callback:
                progress_callback(96, 100, "Saving translated workbook...")

            target_path = (
                Path(custom_output_path)
                if custom_output_path
                else get_smart_output_path(
                    source_path=src_path,
                    target_lang=target_lang,
                    is_bilingual=is_bilingual,
                )
            )
            output_path = safe_save_workbook(workbook, target_path)

            if progress_callback:
                note = f"Saved to {output_path.name}"
                if output_path.name != target_path.name:
                    note += " (safe-renamed to avoid file lock)"
                progress_callback(100, 100, f"Completed! {note}")

            return str(output_path)
        finally:
            workbook.close()
