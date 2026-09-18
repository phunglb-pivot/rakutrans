"""
Central Translator Registry for RakuTrans AI.
Implements the Strategy Pattern to map file formats to their corresponding
translator engines dynamically, providing clean extensible document handling.
"""

from pathlib import Path
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

    @classmethod
    def _init_registry(cls):
        """Lazily populates the registry mapping."""
        if cls._initialized:
            return

        from excel_parser import ExcelTranslator
        from markdown_parser import MarkdownTranslator
        from docx_parser import DocxTranslator
        from pptx_parser import PptxTranslator
        from data_parser import CsvTranslator, JsonTranslator, TextTranslator

        cls._registry = {
            ".xlsx": ExcelTranslator,
            ".md": MarkdownTranslator,
            ".docx": DocxTranslator,
            ".pptx": PptxTranslator,
            ".csv": CsvTranslator,
            ".tsv": CsvTranslator,
            ".json": JsonTranslator,
            ".txt": TextTranslator,
        }
        cls._initialized = True

    @classmethod
    def register(cls, extension: str, translator_cls: Type[BaseTranslator]):
        """Registers or overrides a translator class for an extension."""
        cls._init_registry()
        ext = extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        cls._registry[ext] = translator_cls

    @classmethod
    def get_supported_extensions(cls) -> List[str]:
        """Returns sorted list of supported file extensions (e.g. ['.csv', '.docx', ...])."""
        cls._init_registry()
        return sorted(list(cls._registry.keys()))

    @classmethod
    def is_supported(cls, file_path_or_ext: Union[str, Path]) -> bool:
        """Returns True if the file extension is supported."""
        cls._init_registry()
        raw = str(file_path_or_ext).lower().strip()
        if raw.startswith("."):
            ext = raw
        else:
            ext = Path(raw).suffix.lower()
            if not ext and raw:
                ext = f".{raw}"
        return ext in cls._registry

    @classmethod
    def get_translator_class(cls, file_path_or_ext: Union[str, Path]) -> Type[BaseTranslator]:
        """Returns the translator class for a given file or extension."""
        cls._init_registry()
        raw = str(file_path_or_ext).lower().strip()
        if raw.startswith("."):
            ext = raw
        else:
            ext = Path(raw).suffix.lower()
            if not ext and raw:
                ext = f".{raw}"

        if ext not in cls._registry:
            supported = ", ".join(cls.get_supported_extensions())
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
