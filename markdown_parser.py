"""
Markdown parsing and translation engine for RakuTrans AI.
Handles .md files, chunking large documents intelligently along section boundaries,
and preserving code blocks, markdown syntax, and links.
"""

from pathlib import Path
from typing import List, Tuple, Callable, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import re
from config import AppConfig, TranslationOptions, get_smart_output_path
from llm_manager import LLMManager
from translation_cache import TranslationCache

try:
    from markitdown import MarkItDown
    HAS_MARKITDOWN = True
except ImportError:
    HAS_MARKITDOWN = False


from base_translator import BaseTranslator, safe_save_file


def safe_save_markdown(content: str, target_path: Path) -> Path:
    """
    Saves markdown string to target_path. If target_path is locked,
    automatically falls back to target_path (1).md, target_path (2).md to avoid crashing.
    """
    def _save(p: Path):
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    return safe_save_file(_save, target_path)


class MarkdownTranslator(BaseTranslator):
    """
    Handles translation of Markdown (.md) documents.
    Preserves markdown structure, code blocks, and formatting.
    Integrates local Translation Memory Cache and concurrent section processing.
    Integrates Microsoft MarkItDown for document reading and standardization.
    Supports safe-save against file locking and custom output path.
    """

    def __init__(
        self,
        config: AppConfig,
        llm_manager: LLMManager,
        cache: Optional[TranslationCache] = None
    ):
        super().__init__(config, llm_manager, cache)
        self._markitdown = MarkItDown() if HAS_MARKITDOWN else None

    @classmethod
    def inspect_file(cls, file_path: str) -> dict:
        """
        Quickly inspects a Markdown file to report line count, word count,
        character count, and estimated sections.
        """
        path = Path(file_path)
        if not path.exists():
            return {"error": "File not found"}

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            lines = content.splitlines()
            words = len(content.split())
            sections = [s for s in content.split("\n\n") if s.strip()]

            return {
                "type": "markdown",
                "char_count": len(content),
                "word_count": words,
                "line_count": len(lines),
                "section_count": len(sections)
            }
        except Exception as e:
            return {"type": "markdown", "error": str(e)}

    def _split_into_chunks(self, text: str, max_chars: int = 3500) -> List[str]:
        """
        Splits markdown text into semantic sections along header boundaries or paragraphs
        to avoid cutting in the middle of code blocks or sentences.
        """
        if len(text) <= max_chars:
            return [text]

        sections = text.split("\n\n")
        chunks: List[str] = []
        current_chunk = []
        current_length = 0

        for section in sections:
            sec_len = len(section) + 2
            if current_length + sec_len > max_chars and current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [section]
                current_length = sec_len
            else:
                current_chunk.append(section)
                current_length += sec_len

        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks

    def read_content(self, src_path: Path) -> str:
        """Reads markdown or converts document content via markitdown when beneficial."""
        try:
            with open(src_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            if self._markitdown:
                try:
                    res = self._markitdown.convert(str(src_path))
                    if res and res.text_content:
                        return res.text_content
                except Exception:
                    pass
            with open(src_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read()

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
        Main processing method for Markdown files.
        Chunks large files, checks Translation Memory Cache, translates uncached
        chunks via LLM with concurrent execution, and writes output file.
        Supports safe saving against file lock and custom output path.
        """
        # Resolve target_lang and source_lang flexibly
        if target_lang is None:
            target_lang = kwargs.get("target_lang", "Vietnamese")

        if isinstance(source_lang, TranslationOptions):
            options = source_lang
            source_lang = "auto"
        elif isinstance(source_lang, str) and source_lang != "auto" and "target_lang" not in kwargs and len(args) > 0:
            legacy_src = target_lang
            legacy_tgt = source_lang
            target_lang = legacy_tgt
            source_lang = legacy_src
            if args:
                options = args[0]
        elif source_lang is None:
            source_lang = "auto"

        self._is_cancelled = False
        src_path = Path(file_path)
        if not src_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        content = self.read_content(src_path)
        chunks = self._split_into_chunks(content)
        total_chunks = len(chunks)
        translated_chunks = [None] * total_chunks

        # Check cache for all chunks
        cached_map, uncached_items = self.cache.get_batch(
            texts=chunks,
            target_lang=target_lang,
            options=options,
            source_lang=source_lang
        )

        for idx, trans_val in cached_map.items():
            translated_chunks[idx] = trans_val

        cache_hits = len(cached_map)
        completed_count = cache_hits

        if progress_callback:
            progress_callback(
                5, 100, 
                f"Prepared {total_chunks} sections ({cache_hits} from memory cache)..."
            )

        if uncached_items:
            def translate_single_chunk(item: Tuple[int, str]) -> Tuple[int, str]:
                idx, chunk_text = item
                if self._is_cancelled:
                    raise InterruptedError("Translation was cancelled by user.")

                trans = self.llm_manager.translate_markdown_text(
                    markdown_text=chunk_text,
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang
                )
                self.cache.save_batch(
                    source_texts=[chunk_text],
                    translated_texts=[trans],
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang
                )
                return idx, trans

            max_workers = min(3, len(uncached_items)) if len(uncached_items) > 1 else 1

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_chunk = {
                    executor.submit(translate_single_chunk, item): item[0]
                    for item in uncached_items
                }

                for future in as_completed(future_to_chunk):
                    if self._is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise InterruptedError("Translation was cancelled by user.")

                    idx, trans = future.result()
                    translated_chunks[idx] = trans
                    completed_count += 1
                    pct = 10 + int((completed_count / total_chunks) * 80)
                    if progress_callback:
                        progress_callback(
                            pct, 100,
                            f"Section {completed_count}/{total_chunks} completed ({cache_hits} cached)..."
                        )

        if self._is_cancelled:
            raise InterruptedError("Translation was cancelled by user.")

        if progress_callback:
            progress_callback(95, 100, "Saving translated markdown document...")

        target_path = Path(custom_output_path) if custom_output_path else get_smart_output_path(
            source_path=src_path,
            target_lang=target_lang,
            is_bilingual=False
        )
        output_path = safe_save_markdown("\n\n".join(translated_chunks), target_path)

        if progress_callback:
            note = f"Saved to {output_path.name}"
            if output_path.name != target_path.name:
                note += " (safe-renamed to avoid file lock)"
            progress_callback(100, 100, f"Completed! {note}")

        return str(output_path)
