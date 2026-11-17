"""
Central Translator Registry for RakuTrans AI.
Implements the Strategy Pattern to map file formats to their corresponding
translator engines dynamically, providing clean extensible document handling.
"""

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Dict, Type, List, Optional, Any, Tuple, Union

from base_translator import BaseTranslator
from config import AppConfig
from llm_manager import LLMManager
from translation_cache import TranslationCache


@dataclass(frozen=True)
class FormatMetadata:
    """Pure UI/CLI descriptor for a supported document format."""
    icon_name: str
    badge: str
    inspect_badge_key: str
    inspect_fields: Dict[str, str]
    badge_i18n_key: Optional[str] = None


_CSV_METADATA = FormatMetadata(
    icon_name="file_excel",
    badge="CSV/TSV",
    inspect_badge_key="inspect_csv_badge",
    inspect_fields={
        "rows": "rows",
        "cols": "columns",
        "cells": "translatable_cells",
        "unique": "unique_texts",
    },
)

FORMAT_METADATA: Dict[str, FormatMetadata] = {
    ".xlsx": FormatMetadata(
        icon_name="file_excel",
        badge="Excel",
        inspect_badge_key="inspect_excel_badge",
        inspect_fields={
            "sheets": "sheet_count",
            "cells": "translatable_cells",
            "unique": "unique_texts",
            "formulas": "formula_count",
        },
    ),
    ".csv": _CSV_METADATA,
    ".tsv": _CSV_METADATA,
    ".docx": FormatMetadata(
        icon_name="file_word",
        badge="Word",
        inspect_badge_key="inspect_docx_badge",
        inspect_fields={
            "paragraphs": "paragraphs",
            "tables": "tables",
            "words": "word_count",
            "segments": "translatable_segments",
        },
    ),
    ".pptx": FormatMetadata(
        icon_name="file_ppt",
        badge="PowerPoint",
        inspect_badge_key="inspect_pptx_badge",
        inspect_fields={
            "slides": "slides",
            "shapes": "shapes",
            "words": "word_count",
            "segments": "translatable_segments",
        },
    ),
    ".pdf": FormatMetadata(
        icon_name="file_pdf",
        badge="PDF",
        inspect_badge_key="inspect_pdf_badge",
        inspect_fields={
            "pages": "page_count",
            "words": "word_count",
            "segments": "translatable_segments",
            "chars": "char_count",
        },
    ),
    ".md": FormatMetadata(
        icon_name="file_md",
        badge="Markdown",
        inspect_badge_key="inspect_md_badge",
        inspect_fields={
            "words": "word_count",
            "sections": "section_count",
            "chars": "char_count",
        },
    ),
    ".json": FormatMetadata(
        icon_name="file_json",
        badge="JSON",
        inspect_badge_key="inspect_json_badge",
        inspect_fields={
            "keys": "total_keys",
            "strings": "translatable_strings",
            "unique": "unique_texts",
        },
    ),
    ".txt": FormatMetadata(
        icon_name="file_text",
        badge="Plain Text",
        badge_i18n_key="badge_plain_text",
        inspect_badge_key="inspect_txt_badge",
        inspect_fields={
            "lines": "line_count",
            "words": "word_count",
            "chars": "char_count",
        },
    ),
}

FILE_DIALOG_FILTER_GROUPS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("filetype_pdf", (".pdf",)),
    ("filetype_office", (".docx", ".pptx")),
    ("filetype_spreadsheets", (".xlsx", ".csv", ".tsv")),
    ("filetype_text", (".md", ".txt")),
    ("filetype_json", (".json",)),
)


class TranslatorRegistry:
    """
    Central registry for format translators.
    Enables unified inspection, instantiation, and validation across GUI and CLI.
    """

    _registry: Dict[str, Type[BaseTranslator]] = {}
    _initialized: bool = False
    _lock = threading.RLock()

    @classmethod
    def _init_registry(cls):
        """Lazily populates the registry mapping in a thread-safe manner."""
        if cls._initialized:
            return
        with cls._lock:
            if cls._initialized:
                return

            from excel_parser import ExcelTranslator
            from markdown_parser import MarkdownTranslator
            from docx_parser import DocxTranslator
            from pptx_parser import PptxTranslator
            from data_parser import CsvTranslator, JsonTranslator, TextTranslator
            from pdf_parser import PdfTranslator

            cls._registry = {
                ".xlsx": ExcelTranslator,
                ".md": MarkdownTranslator,
                ".docx": DocxTranslator,
                ".pptx": PptxTranslator,
                ".pdf": PdfTranslator,
                ".csv": CsvTranslator,
                ".tsv": CsvTranslator,
                ".json": JsonTranslator,
                ".txt": TextTranslator,
            }
            cls._initialized = True

    @staticmethod
    def _extract_extension(file_path_or_ext: Union[str, Path]) -> str:
        raw = str(file_path_or_ext).lower().strip()
        if not raw:
            return ""
        if raw.startswith(".") and "/" not in raw and "\\" not in raw:
            return raw
        ext = Path(raw).suffix.lower()
        if not ext and "/" not in raw and "\\" not in raw:
            return f".{raw}"
        return ext

    @classmethod
    def register(cls, extension: str, translator_cls: Type[BaseTranslator]):
        """Registers or overrides a translator class for an extension."""
        cls._init_registry()
        ext = extension.lower().strip()
        if not ext.startswith("."):
            ext = f".{ext}"
        with cls._lock:
            cls._registry[ext] = translator_cls

    @classmethod
    def get_supported_extensions(cls) -> List[str]:
        """Returns sorted list of supported file extensions (e.g. ['.csv', '.docx', ...])."""
        cls._init_registry()
        with cls._lock:
            return sorted(list(cls._registry.keys()))

    @classmethod
    def is_supported(cls, file_path_or_ext: Union[str, Path]) -> bool:
        """Returns True if the file extension is supported."""
        cls._init_registry()
        ext = cls._extract_extension(file_path_or_ext)
        with cls._lock:
            return ext in cls._registry

    @classmethod
    def supports_bilingual(cls, file_path_or_ext: Union[str, Path]) -> bool:
        """Returns True if the registered translator for this file/extension supports bilingual output."""
        cls._init_registry()
        ext = cls._extract_extension(file_path_or_ext)
        with cls._lock:
            translator_cls = cls._registry.get(ext)
            return bool(translator_cls and getattr(translator_cls, "SUPPORTS_BILINGUAL", False))

    @classmethod
    def get_bilingual_extensions(cls) -> List[str]:
        """Returns sorted list of extensions whose translator supports bilingual output."""
        cls._init_registry()
        with cls._lock:
            return sorted(
                ext
                for ext, t_cls in cls._registry.items()
                if getattr(t_cls, "SUPPORTS_BILINGUAL", False)
            )

    @classmethod
    def get_format_metadata(cls, file_path_or_ext: Union[str, Path]) -> Optional[FormatMetadata]:
        """Returns UI/CLI descriptor metadata for a file extension if available."""
        ext = cls._extract_extension(file_path_or_ext)
        return FORMAT_METADATA.get(ext)

    @classmethod
    def get_translator_class(cls, file_path_or_ext: Union[str, Path]) -> Type[BaseTranslator]:
        """Returns the translator class for a given file or extension."""
        cls._init_registry()
        ext = cls._extract_extension(file_path_or_ext)
        with cls._lock:
            if ext not in cls._registry:
                supported = ", ".join(sorted(list(cls._registry.keys())))
                raise ValueError(f"Unsupported file format '{ext}'. Supported formats: {supported}")
            return cls._registry[ext]

    @classmethod
    def create_translator(
        cls,
        file_path_or_ext: Union[str, Path],
        config: AppConfig,
        llm_manager: LLMManager,
        cache: Optional[TranslationCache] = None,
        i18n: Optional[Any] = None,
    ) -> BaseTranslator:
        """Instantiates the appropriate translator for the given file or extension."""
        translator_cls = cls.get_translator_class(file_path_or_ext)
        translator = translator_cls(config, llm_manager, cache)
        if i18n is not None and hasattr(translator, "_i18n"):
            translator._i18n = i18n
        return translator

    @classmethod
    def inspect(cls, file_path: Union[str, Path]) -> Dict[str, Any]:
        """Runs pre-scan inspection on the target file using its registered translator."""
        path = Path(file_path)
        if not path.exists():
            return {"error": "File not found"}

        try:
            translator_cls = cls.get_translator_class(path)
            return translator_cls.inspect_file(str(path))
        except Exception as e:
            return {"error": str(e)}
