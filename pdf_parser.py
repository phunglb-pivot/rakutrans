"""
PDF translation engine for RakuTrans AI.
Translates PDF documents using a flow-based pipeline:
    Input PDF -> Convert to Word (.docx) -> Translate Document -> Convert back to PDF.

This architectural pipeline combines the best of both worlds:
- Full paragraph flow, table structures, and typography are preserved during translation via DocxTranslator.
- The final output document remains a clean, professional, portable PDF document.
- Fixed-layout text distortion, font clipping, and text overlapping from direct in-place PDF editing are completely eliminated.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Set, Callable, Optional, Any

# Fast PDF inspection engines
try:
    import pymupdf
    HAS_PYMUPDF = True
except ImportError:
    try:
        import fitz as pymupdf
        HAS_PYMUPDF = True
    except ImportError:
        pymupdf = None
        HAS_PYMUPDF = False

import pypdf

from base_translator import BaseTranslator
from config import AppConfig, TranslationOptions, get_smart_output_path
from llm_manager import LLMManager
from translation_cache import TranslationCache
from docx_parser import DocxTranslator
from format_converter import pdf_to_docx, docx_to_pdf


def _should_translate(text: Optional[str]) -> bool:
    """Checks if a string has translatable content."""
    if not text:
        return False
    trimmed = text.strip()
    if not trimmed:
        return False

    # Skip pure numbers and currency figures (e.g. "123", "45.6", "1,000", "$100")
    cleaned_num = re.sub(r"^[$\€\£\¥\₫]?\s*", "", trimmed)
    try:
        float(cleaned_num.replace(",", ""))
        return False
    except ValueError:
        pass

    # Must contain at least one alphanumeric character
    return any(c.isalnum() for c in trimmed)


class PdfTranslator(BaseTranslator):
    """
    Translates Adobe PDF (.pdf) documents via high-fidelity pipeline:
    PDF -> DOCX -> Translate -> PDF.
    Output is a professionally formatted PDF document (.pdf).
    """

    def __init__(
        self,
        config: AppConfig,
        llm_manager: LLMManager,
        cache: Optional[TranslationCache] = None,
    ):
        super().__init__(config, llm_manager, cache)
        self._docx_translator: Optional[DocxTranslator] = None

    def cancel(self):
        """Cancels any ongoing translation operations, including child docx translation."""
        super().cancel()
        if self._docx_translator:
            self._docx_translator.cancel()

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects PDF to count pages, words, characters, and translatable segments."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "pdf", "error": "File not found"}

        try:
            if HAS_PYMUPDF:
                doc = pymupdf.open(str(path))
                page_count = len(doc)
                total_words = 0
                total_chars = 0
                unique_texts: Set[str] = set()

                for page in doc:
                    text = page.get_text() or ""
                    for line in text.splitlines():
                        trimmed = line.strip()
                        if trimmed:
                            total_chars += len(trimmed)
                            total_words += len(trimmed.split())
                            if _should_translate(trimmed):
                                unique_texts.add(trimmed)

                doc.close()
                return {
                    "type": "pdf",
                    "page_count": page_count,
                    "word_count": total_words,
                    "char_count": total_chars,
                    "translatable_segments": len(unique_texts),
                }
            else:
                reader = pypdf.PdfReader(str(path))
                page_count = len(reader.pages)
                total_words = 0
                total_chars = 0
                unique_texts = set()

                for page in reader.pages:
                    text = page.extract_text() or ""
                    for line in text.splitlines():
                        trimmed = line.strip()
                        if trimmed:
                            total_chars += len(trimmed)
                            total_words += len(trimmed.split())
                            if _should_translate(trimmed):
                                unique_texts.add(trimmed)

                return {
                    "type": "pdf",
                    "page_count": page_count,
                    "word_count": total_words,
                    "char_count": total_chars,
                    "translatable_segments": len(unique_texts),
                }
        except Exception as e:
            return {"type": "pdf", "error": str(e)}

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
        Translates a PDF document via:
        1. Converting PDF to Word (.docx) to reconstruct flow-based paragraphs and tables.
        2. Translating the Word document via DocxTranslator.
        3. Converting the translated Word document back to a final PDF (.pdf).
        """
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang = target_lang or kwargs.get("target_lang") or self.config.target_language
        options = options or self.config.translation_options

        # Step 1: Progress (0-10%)
        if progress_callback:
            progress_callback(5, 100, "Converting PDF to Word (.docx)...")

        # Create temporary working directory for the intermediate DOCX conversion
        temp_dir = tempfile.mkdtemp(prefix="rakutrans_pdf_")
        raw_docx_path = Path(temp_dir) / f"{src.stem}_raw.docx"
        translated_docx_path = Path(temp_dir) / f"{src.stem}_trans.docx"

        try:
            pdf_to_docx(str(src), str(raw_docx_path))

            if self.is_cancelled:
                raise InterruptedError("Translation cancelled by user.")

            # Step 2: Progress (10-85%)
            if progress_callback:
                progress_callback(12, 100, "Translating document content...")

            # Determine final target path with .pdf extension
            if custom_output_path:
                out_path = Path(custom_output_path)
                if out_path.suffix.lower() != ".pdf":
                    out_path = out_path.with_suffix(".pdf")
            else:
                out_path = get_smart_output_path(
                    source_path=src,
                    target_lang=target_lang,
                    target_format=".pdf",
                )

            # Wrapper for scaling child docx progress from 12% to 85%
            def docx_progress(current: int, total: int, msg: str):
                if progress_callback:
                    pct = 12 + int((current / max(1, total)) * 73)
                    progress_callback(min(85, pct), 100, msg)

            self._docx_translator = DocxTranslator(self.config, self.llm_manager, self.cache)
            if self.is_cancelled:
                self._docx_translator.cancel()
                raise InterruptedError("Translation cancelled by user.")

            self._docx_translator.process_file(
                file_path=str(raw_docx_path),
                target_lang=target_lang,
                source_lang=source_lang,
                options=options,
                progress_callback=docx_progress,
                custom_output_path=str(translated_docx_path),
                *args,
                **kwargs,
            )

            if self.is_cancelled:
                raise InterruptedError("Translation cancelled by user.")

            # Step 3: Progress (88-100%) - Convert translated docx back to PDF
            if progress_callback:
                progress_callback(88, 100, "Converting translated document to final PDF...")

            docx_to_pdf(str(translated_docx_path), str(out_path))

            if progress_callback:
                progress_callback(100, 100, f"Saved: {Path(out_path).name}")

            return str(out_path)

        finally:
            # Clean up intermediate temporary files
            try:
                if raw_docx_path.exists():
                    raw_docx_path.unlink()
                if translated_docx_path.exists():
                    translated_docx_path.unlink()
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except Exception:
                pass
