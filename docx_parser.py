"""
Word (.docx) parsing and translation engine for RakuTrans AI.
Uses python-docx to translate documents while preserving paragraphs,
tables, formatting, and structural properties.
"""

from pathlib import Path
from typing import List, Dict, Set, Callable, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
import docx
from docx import Document
from docx.text.paragraph import Paragraph
from docx.table import Table

from base_translator import BaseTranslator, safe_save_file
from config import AppConfig, TranslationOptions, get_smart_output_path
from llm_manager import LLMManager
from translation_cache import TranslationCache


def _should_translate(text: Optional[str]) -> bool:
    """Checks if a string has translatable content."""
    if not text:
        return False
    trimmed = text.strip()
    if not trimmed:
        return False
    # Skip pure numbers and single symbols
    try:
        float(trimmed.replace(",", ""))
        return False
    except ValueError:
        pass
    return any(c.isalnum() for c in trimmed)


class DocxTranslator(BaseTranslator):
    """
    Handles translation of Microsoft Word (.docx) documents.
    Preserves document structure, headings, lists, table cells, and run styles.
    Features text deduplication, SQLite translation memory cache, and concurrent batching.
    """

    @classmethod
    def inspect_file(cls, file_path: str) -> Dict[str, Any]:
        """Inspects Word document to count paragraphs, tables, words, and translatable segments."""
        path = Path(file_path)
        if not path.exists():
            return {"type": "docx", "error": "File not found"}

        try:
            doc = Document(str(path))
            p_count = len(doc.paragraphs)
            t_count = len(doc.tables)
            total_words = 0
            unique_texts: Set[str] = set()

            def scan_paragraph(p: Paragraph):
                nonlocal total_words
                text = p.text
                if text:
                    total_words += len(text.split())
                    if _should_translate(text):
                        unique_texts.add(text.strip())

            for p in doc.paragraphs:
                scan_paragraph(p)

            for table in doc.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for p in cell.paragraphs:
                            scan_paragraph(p)

            for section in doc.sections:
                for p in section.header.paragraphs:
                    scan_paragraph(p)
                for p in section.footer.paragraphs:
                    scan_paragraph(p)

            return {
                "type": "docx",
                "paragraphs": p_count,
                "tables": t_count,
                "word_count": total_words,
                "translatable_segments": len(unique_texts)
            }
        except Exception as e:
            return {"type": "docx", "error": str(e)}

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
        Translates a Word document into the target language.
        Extracts translatable text segments, translates via LLM in concurrent batches,
        and saves output file with style preservation.
        """
        src = Path(file_path)
        if not src.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang = target_lang or "Vietnamese"
        options = options or self.config.translation_options

        if progress_callback:
            progress_callback(5, 100, "Reading Word document structure...")

        doc = Document(str(src))

        # Collect paragraphs to translate
        paragraphs_to_process: List[Paragraph] = []

        def collect_from_p(p: Paragraph):
            if _should_translate(p.text):
                paragraphs_to_process.append(p)

        for p in doc.paragraphs:
            collect_from_p(p)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        collect_from_p(p)

        for section in doc.sections:
            for p in section.header.paragraphs:
                collect_from_p(p)
            for p in section.footer.paragraphs:
                collect_from_p(p)

        if not paragraphs_to_process:
            # Document has no translatable text
            out_path = get_smart_output_path(src, target_lang=target_lang, custom_output_path=custom_output_path)
            safe_save_file(lambda p: doc.save(str(p)), out_path)
            if progress_callback:
                progress_callback(100, 100, "Document contains no text to translate.")
            return str(out_path)

        # Collect unique texts for batch translation
        unique_texts = list({p.text.strip() for p in paragraphs_to_process if _should_translate(p.text)})
        total_unique = len(unique_texts)

        if progress_callback:
            progress_callback(10, 100, f"Found {total_unique} unique text blocks. Checking cache...")

        translation_map: Dict[str, str] = {}
        uncached_texts: List[str] = []

        for text in unique_texts:
            cached = self.cache.get(text, target_lang)
            if cached:
                translation_map[text] = cached
            else:
                uncached_texts.append(text)

        if uncached_texts:
            batch_size = max(5, getattr(self.config, "batch_size", 20))
            batches = [uncached_texts[i:i + batch_size] for i in range(0, len(uncached_texts), batch_size)]
            total_batches = len(batches)

            completed_batches = 0

            def translate_worker(batch: List[str]) -> List[str]:
                if self.is_cancelled:
                    raise InterruptedError("Translation cancelled by user.")
                return self.llm_manager.translate_batch(
                    texts=batch,
                    target_lang=target_lang,
                    source_lang=source_lang,
                    options=options
                )

            max_workers = min(3, max(1, total_batches))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {executor.submit(translate_worker, b): b for b in batches}
                for future in as_completed(futures):
                    if self.is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise InterruptedError("Translation cancelled by user.")

                    orig_batch = futures[future]
                    try:
                        translated_batch = future.result()
                        for orig, trans in zip(orig_batch, translated_batch):
                            translation_map[orig] = trans
                            self.cache.set(orig, target_lang, trans)
                    except Exception as e:
                        if self.is_cancelled:
                            raise InterruptedError("Translation cancelled by user.")
                        raise e

                    completed_batches += 1
                    pct = 10 + int(completed_batches / total_batches * 75)
                    if progress_callback:
                        progress_callback(pct, 100, f"Translating batch {completed_batches}/{total_batches}...")

        if self.is_cancelled:
            raise InterruptedError("Translation cancelled by user.")

        if progress_callback:
            progress_callback(90, 100, "Applying translations to Word document...")

        # Apply translations back to paragraphs
        for p in paragraphs_to_process:
            orig_text = p.text.strip()
            translated = translation_map.get(orig_text)
            if not translated:
                continue

            if len(p.runs) <= 1:
                # Direct replacement preserving overall paragraph formatting
                if p.runs:
                    p.runs[0].text = translated
                else:
                    p.text = translated
            else:
                # Multiple runs: preserve formatting of first run and clear subsequent runs
                p.runs[0].text = translated
                for r in p.runs[1:]:
                    r.text = ""

        if progress_callback:
            progress_callback(95, 100, "Saving translated Word document...")

        out_path = get_smart_output_path(
            source_path=src,
            target_lang=target_lang,
            target_format=".docx",
            custom_output_path=custom_output_path
        )
        saved_path = safe_save_file(lambda p: doc.save(str(p)), out_path)

        if progress_callback:
            progress_callback(100, 100, f"Saved: {saved_path.name}")

        return str(saved_path)
