"""
PDF translation engine for RakuTrans AI.
Translates PDF documents using a flow-based pipeline:
    Input PDF -> Convert to Word (.docx) -> Translate Document -> Convert back to PDF.

This architectural pipeline combines the best of both worlds:
- Full paragraph flow, table structures, and typography are preserved during translation via DocxTranslator.
- The final output document remains a clean, professional, portable PDF document.
- Fixed-layout text distortion, font clipping, and text overlapping from direct in-place PDF editing are completely eliminated.
"""

import shutil
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

from base_translator import (
    BaseTranslator,
    count_words_multilingual,
    safe_save_file,
    should_translate_text,
)
from config import AppConfig, TranslationOptions, get_smart_output_path
from llm_manager import LLMManager
from translation_cache import TranslationCache
from docx_parser import DocxTranslator, _iter_all_paragraphs
from format_converter import pdf_to_docx, docx_to_pdf, _is_cjk_char


def _clean_pdf2docx_soft_breaks(docx_path: Path) -> None:
    """
    Removes visual line-wrap <w:br/> tags inside intermediate DOCX paragraphs produced by pdf2docx
    (while keeping page/column breaks intact) so split words and sentences translate continuously.
    """
    try:
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        doc = Document(str(docx_path))
        changed = False
        for p in _iter_all_paragraphs(doc):
            brs = p._p.xpath(".//w:br")
            if not brs:
                continue
            for br in brs:
                br_type = br.get(qn("w:type"))
                if br_type in ("page", "column"):
                    continue
                parent_r = br.getparent()
                if parent_r is None:
                    continue
                # Find adjacent text around this break inside paragraph
                all_nodes = list(p._p.iter())
                try:
                    br_pos = all_nodes.index(br)
                except ValueError:
                    continue
                prev_char = ""
                for node in reversed(all_nodes[:br_pos]):
                    if node.tag == qn("w:t") and node.text:
                        prev_char = node.text[-1]
                        break
                next_char = ""
                for node in all_nodes[br_pos + 1 :]:
                    if node.tag == qn("w:t") and node.text:
                        next_char = node.text[0]
                        break
                if prev_char and next_char:
                    if not prev_char.isspace() and not next_char.isspace():
                        if not _is_cjk_char(prev_char) and not _is_cjk_char(next_char):
                            space_t = OxmlElement("w:t")
                            space_t.set(qn("xml:space"), "preserve")
                            space_t.text = " "
                            idx_in_r = list(parent_r).index(br)
                            parent_r.insert(idx_in_r, space_t)
                    parent_r.remove(br)
                    changed = True
        if changed:
            doc.save(str(docx_path))
    except Exception:
        pass


def _should_translate(text: Optional[str]) -> bool:
    """Checks if a string has translatable content."""
    return should_translate_text(text, ignore_formulas=False)


def _is_scanned_image_pdf(src: Path) -> bool:
    """Returns True if the PDF has pages and images but zero selectable text."""
    try:
        if HAS_PYMUPDF:
            doc = pymupdf.open(str(src))
            try:
                if len(doc) == 0:
                    return False
                has_text = any((page.get_text() or "").strip() for page in doc)
                if has_text:
                    return False
                return any(bool(page.get_images()) for page in doc)
            finally:
                doc.close()
        else:
            reader = pypdf.PdfReader(str(src))
            if not reader.pages:
                return False
            has_text = any((page.extract_text() or "").strip() for page in reader.pages)
            if has_text:
                return False
            return any(bool(getattr(page, "images", None)) for page in reader.pages)
    except Exception:
        return False


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
                try:
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
                                total_words += count_words_multilingual(trimmed)
                                if _should_translate(trimmed):
                                    unique_texts.add(trimmed)
                finally:
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
                            total_words += count_words_multilingual(trimmed)
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
        if self.is_cancelled:
            raise InterruptedError("Translation cancelled by user.")

        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        if _is_scanned_image_pdf(src):
            raise ValueError(
                "This PDF appears to be a scanned/image-only document with no selectable text layer. "
                "Please run OCR on the PDF before translating."
            )

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )

        if progress_callback:
            progress_callback(5, 100, "Converting PDF to Word (.docx)...")

        temp_dir = tempfile.mkdtemp(prefix="rakutrans_pdf_")
        raw_docx_path = Path(temp_dir) / f"{src.stem}_raw.docx"
        translated_docx_path = Path(temp_dir) / f"{src.stem}_trans.docx"

        try:
            pdf_to_docx(str(src), str(raw_docx_path))
            _clean_pdf2docx_soft_breaks(raw_docx_path)

            if self.is_cancelled:
                raise InterruptedError("Translation cancelled by user.")

            if progress_callback:
                progress_callback(12, 100, "Translating document content...")

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
                raise InterruptedError("Translation was cancelled by user.")

            if progress_callback:
                progress_callback(88, 100, "Converting translated document to final PDF...")

            saved_path = safe_save_file(
                lambda p: docx_to_pdf(str(translated_docx_path), str(p)),
                out_path,
            )

            if progress_callback:
                progress_callback(100, 100, f"Saved: {saved_path.name}")

            return str(saved_path)

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
