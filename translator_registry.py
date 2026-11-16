"""
Central Translator Registry for RakuTrans AI.
Implements the Strategy Pattern to map file formats to their corresponding
translator engines dynamically, providing clean extensible document handling.
"""

from pathlib import Path
import threading
from typing import Dict, Type, List, Optional, Any, Union

from base_translator import BaseTranslator
from config import AppConfig
from llm_manager import LLMManager
from translation_cache import TranslationCache


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
        cache: Optional[TranslationCache] = None
    ) -> BaseTranslator:
        """Instantiates the appropriate translator for the given file or extension."""
        translator_cls = cls.get_translator_class(file_path_or_ext)
        return translator_cls(config, llm_manager, cache)

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
