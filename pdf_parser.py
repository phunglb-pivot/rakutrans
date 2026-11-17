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
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Set, Callable, Optional, Any, Tuple

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
    (while keeping page/column breaks and consecutive blank-line breaks intact) and de-hyphenates
    split ASCII words so sentences translate continuously.
    """
    try:
        from docx import Document
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        w_br_tag = qn("w:br")
        w_t_tag = qn("w:t")
        w_type_attr = qn("w:type")
        xml_space_attr = qn("xml:space")

        doc = Document(str(docx_path))
        changed = False
        for p in _iter_all_paragraphs(doc):
            brs = p._p.xpath(".//w:br")
            if not brs:
                continue

            # Walk paragraph XML once in document order instead of recomputing list(p._p.iter()) per <w:br>
            all_nodes = list(p._p.iter())
            t_positions = [idx for idx, nd in enumerate(all_nodes) if nd.tag == w_t_tag]
            br_positions = {id(nd): idx for idx, nd in enumerate(all_nodes) if nd.tag == w_br_tag}

            for b_idx, br in enumerate(brs):
                br_type = br.get(w_type_attr)
                if br_type in ("page", "column"):
                    continue
                parent_r = br.getparent()
                if parent_r is None:
                    continue
                br_pos = br_positions.get(id(br))
                if br_pos is None:
                    continue

                # Preserve consecutive <w:br/> breaks used as intentional blank lines
                if b_idx > 0:
                    prev_br_pos = br_positions.get(id(brs[b_idx - 1]))
                    if prev_br_pos is not None and not any(
                        prev_br_pos < tp < br_pos and (all_nodes[tp].text or "").strip()
                        for tp in t_positions
                    ):
                        continue

                prev_t = None
                for tp in reversed(t_positions):
                    if tp < br_pos and all_nodes[tp].text:
                        prev_t = all_nodes[tp]
                        break

                next_t = None
                for tp in t_positions:
                    if tp > br_pos and all_nodes[tp].text:
                        next_t = all_nodes[tp]
                        break

                if prev_t is not None and next_t is not None:
                    prev_text = prev_t.text or ""
                    next_text = next_t.text or ""
                    prev_char = prev_text[-1]
                    next_char = next_text[0]

                    # De-hyphenate wrapped English/Latin words like "trans-\nlation" -> "translation"
                    if (
                        len(prev_text) >= 2
                        and prev_char == "-"
                        and prev_text[-2].isascii()
                        and prev_text[-2].isalpha()
                        and next_char.isascii()
                        and next_char.islower()
                    ):
                        prev_t.text = prev_text[:-1]
                        parent_r.remove(br)
                        changed = True
                        continue

                    if not prev_char.isspace() and not next_char.isspace():
                        if not _is_cjk_char(prev_char) and not _is_cjk_char(next_char):
                            space_t = OxmlElement("w:t")
                            space_t.set(xml_space_attr, "preserve")
                            space_t.text = " "
                            idx_in_r = list(parent_r).index(br)
                            parent_r.insert(idx_in_r, space_t)
                    parent_r.remove(br)
                    changed = True
        if changed:
            doc.save(str(docx_path))
    except Exception as e:
        print(f"[Warning] Failed to clean pdf2docx soft breaks: {e}")


_SCANNED_MIN_ALNUM_PER_PAGE = 10
_SCANNED_AVG_ALNUM_PER_PAGE = 5


@contextmanager
def _open_pdf_pages(src: Path) -> Iterator[Tuple[int, Iterator[Tuple[str, bool]]]]:
    """Yields (page_count, iterator of (page_text, has_images)) using PyMuPDF or pypdf."""
    if HAS_PYMUPDF:
        doc = pymupdf.open(str(src))
        try:
            yield len(doc), ((p.get_text() or "", bool(p.get_images())) for p in doc)
        finally:
            doc.close()
    else:
        reader = pypdf.PdfReader(str(src))
        yield len(reader.pages), (
            (p.extract_text() or "", bool(getattr(p, "images", None)))
            for p in reader.pages
        )


def _is_scanned_image_pdf(src: Path) -> bool:
    """Returns True if the PDF is image-based with little or no meaningful selectable text."""
    try:
        with _open_pdf_pages(src) as (page_count, pages):
            if page_count == 0:
                return False
            total_alnum = 0
            max_page_alnum = 0
            pages_with_images = 0
            for txt, has_images in pages:
                alnum_cnt = sum(1 for ch in txt if ch.isalnum())
                if alnum_cnt > _SCANNED_MIN_ALNUM_PER_PAGE:
                    return False
                total_alnum += alnum_cnt
                if alnum_cnt > max_page_alnum:
                    max_page_alnum = alnum_cnt
                if has_images:
                    pages_with_images += 1
            if pages_with_images == 0:
                return False
            if total_alnum == 0:
                return True
            return (
                pages_with_images >= max(1, page_count // 2)
                and max_page_alnum <= _SCANNED_MIN_ALNUM_PER_PAGE
                and total_alnum <= _SCANNED_AVG_ALNUM_PER_PAGE * page_count
            )
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
            with _open_pdf_pages(path) as (page_count, pages):
                total_words = 0
                total_chars = 0
                unique_texts: Set[str] = set()

                for text, _has_images in pages:
                    for line in text.splitlines():
                        trimmed = line.strip()
                        if trimmed:
                            total_chars += len(trimmed)
                            total_words += count_words_multilingual(trimmed)
                            if should_translate_text(trimmed, ignore_formulas=False):
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
            raise ValueError(self._t("err_scanned_pdf_ocr"))

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )

        if progress_callback:
            progress_callback(5, 100, self._t("progress_pdf_to_docx"))

        temp_dir = tempfile.mkdtemp(prefix="rakutrans_pdf_")
        raw_docx_path = Path(temp_dir) / f"{src.stem}_raw.docx"
        translated_docx_path = Path(temp_dir) / f"{src.stem}_trans.docx"

        try:
            pdf_to_docx(
                str(src),
                str(raw_docx_path),
                cancel_check=lambda: self.is_cancelled,
            )
            _clean_pdf2docx_soft_breaks(raw_docx_path)

            if self.is_cancelled:
                raise InterruptedError("Translation cancelled by user.")

            if progress_callback:
                progress_callback(12, 100, self._t("progress_translating_content"))

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

            self._docx_translator = DocxTranslator(
                self.config, self.llm_manager, self.cache, i18n=self._i18n
            )
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
                progress_callback(88, 100, self._t("progress_docx_to_pdf"))

            saved_path = safe_save_file(
                lambda p: docx_to_pdf(
                    str(translated_docx_path),
                    str(p),
                    cancel_check=lambda: self.is_cancelled,
                ),
                out_path,
            )

            if progress_callback:
                progress_callback(100, 100, self._t("progress_saved_file", filename=saved_path.name))

            return str(saved_path)

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
