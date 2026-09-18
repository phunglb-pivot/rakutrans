"""
Base translator abstraction and file-saving utilities for RakuTrans AI.
Provides a unified contract for all document and data format parsers.
"""

from abc import ABC, abstractmethod
from pathlib import Path
import re
from typing import Callable, Optional, Dict, Any

from config import AppConfig, TranslationOptions
from llm_manager import LLMManager
from translation_cache import TranslationCache


def safe_save_file(save_fn: Callable[[Path], None], target_path: Path) -> Path:
    """
    Executes save_fn(target_path). If target_path is locked or busy
    (e.g. file is open in Microsoft Office or another application),
    automatically falls back to target_path (1).ext, target_path (2).ext, etc.
    """
    out_path = target_path
    stem = target_path.stem
    suffix = target_path.suffix

    m = re.match(r"^(.*?)\s*\((\d+)\)$", stem)
    if m:
        base_stem = m.group(1).rstrip()
        counter = int(m.group(2)) + 1
    else:
        base_stem = stem
        counter = 1

    while True:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            save_fn(out_path)
            return out_path
        except PermissionError:
            out_path = target_path.parent / f"{base_stem} ({counter}){suffix}"
            counter += 1
            if counter > 50:
                raise


class BaseTranslator(ABC):
    """
    Abstract base class for all file translators in RakuTrans AI.
    All format implementations (Excel, Markdown, Word, PowerPoint, CSV, JSON, TXT)
    must adhere to this interface.
    """

    def __init__(
        self,
        config: AppConfig,
        llm_manager: LLMManager,
        cache: Optional[TranslationCache] = None
    ):
        self.config = config
        self.llm_manager = llm_manager
        self.cache = cache or TranslationCache()
        self._is_cancelled = False

    def cancel(self) -> None:
        """Signals the translation process to abort."""
        self._is_cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Returns True if user requested cancellation."""
        return self._is_cancelled

    @classmethod
    @abstractmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """
        Quickly inspects a document before translation to count cells, words,
        paragraphs, slides, or sections for UI badge feedback.
        """
        pass

    @abstractmethod
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
        """
        Main translation flow. Translates content while preserving formatting and layout,
        and saves output file. Returns the path of the saved file.
        """
        pass
