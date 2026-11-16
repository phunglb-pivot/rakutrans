"""
Markdown parsing and translation engine for RakuTrans AI.
Handles .md files using structure-aware block tokenization that keeps fenced code blocks
intact, splits oversized tables strictly at row boundaries without breaking table continuity,
and preserves exact inter-block separators.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
from typing import List, Tuple, Callable, Optional

from base_translator import (
    BaseTranslator,
    count_words_multilingual,
    detect_text_encoding,
    safe_save_file,
)
from config import AppConfig, TranslationOptions, get_smart_output_path
from llm_manager import LLMManager
from translation_cache import TranslationCache

try:
    from markitdown import MarkItDown
    HAS_MARKITDOWN = True
except ImportError:
    HAS_MARKITDOWN = False

_FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def safe_save_markdown(content: str, target_path: Path) -> Path:
    """
    Saves markdown string to target_path. If target_path is locked,
    automatically falls back to target_path (1).md, target_path (2).md to avoid crashing.
    """
    def _save(p: Path):
        with open(p, "w", encoding="utf-8") as f:
            f.write(content)

    return safe_save_file(_save, target_path)


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return len(stripped) >= 2 and stripped.startswith("|") and stripped.endswith("|")


def _tokenize_markdown_blocks(text: str) -> List[Tuple[str, str, str]]:
    """
    Tokenizes Markdown into (kind, block_text, sep_after) blocks.
    kind is one of: 'code_fence', 'table', 'prose'.
    sep_after preserves the exact blank-line / newline separator following the block.
    """
    lines = text.splitlines(keepends=False)
    blocks: List[Tuple[str, str, str]] = []
    n = len(lines)
    i = 0

    while i < n:
        # Collect leading blank lines if the document starts with blank lines
        if not lines[i].strip():
            blank_count = 0
            while i < n and not lines[i].strip():
                blank_count += 1
                i += 1
            if blocks:
                prev_k, prev_t, prev_s = blocks[-1]
                blocks[-1] = (prev_k, prev_t, prev_s + ("\n" * blank_count))
            else:
                blocks.append(("prose", "", "\n" * blank_count))
            continue

        fence_m = _FENCE_OPEN_RE.match(lines[i])
        if fence_m:
            fence_seq = fence_m.group(1)
            fence_char = fence_seq[0]
            fence_len = len(fence_seq)
            close_re = re.compile(rf"^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$")

            buf = [lines[i]]
            i += 1
            while i < n:
                buf.append(lines[i])
                if close_re.match(lines[i]):
                    i += 1
                    break
                i += 1
            sep = ""
            if i < n:
                blank_run = 0
                while i < n and not lines[i].strip():
                    blank_run += 1
                    i += 1
                sep = "\n" * (1 + blank_run)
            blocks.append(("code_fence", "\n".join(buf), sep))
            continue

        if _is_table_line(lines[i]):
            buf = [lines[i]]
            i += 1
            while i < n and _is_table_line(lines[i]):
                buf.append(lines[i])
                i += 1
            sep = ""
            if i < n:
                blank_run = 0
                while i < n and not lines[i].strip():
                    blank_run += 1
                    i += 1
                sep = "\n" * (1 + blank_run)
            blocks.append(("table", "\n".join(buf), sep))
            continue

        # Prose / heading / list paragraph until blank line, fence, or table
        buf = [lines[i]]
        i += 1
        while i < n:
            if not lines[i].strip() or _FENCE_OPEN_RE.match(lines[i]) or _is_table_line(lines[i]):
                break
            buf.append(lines[i])
            i += 1
        sep = ""
        if i < n:
            blank_run = 0
            while i < n and not lines[i].strip():
                blank_run += 1
                i += 1
            sep = "\n" * (1 + blank_run)
        blocks.append(("prose", "\n".join(buf), sep))

    return blocks


class MarkdownTranslator(BaseTranslator):
    """
    Handles translation of Markdown (.md) documents.
    Preserves markdown structure, code blocks, tables, and formatting.
    Integrates local Translation Memory Cache and concurrent section processing.
    Supports safe-save against file locking and custom output path.
    """

    def __init__(
        self,
        config: AppConfig,
        llm_manager: LLMManager,
        cache: Optional[TranslationCache] = None,
    ):
        super().__init__(config, llm_manager, cache)
        self._markitdown = None
        if HAS_MARKITDOWN:
            try:
                self._markitdown = MarkItDown()
            except Exception:
                self._markitdown = None

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
            enc = detect_text_encoding(path)
            with open(path, "r", encoding=enc, errors="replace") as f:
                content = f.read()

            lines = content.splitlines()
            words = count_words_multilingual(content)
            sections = [b for _, b, _ in _tokenize_markdown_blocks(content) if b.strip()]

            return {
                "type": "markdown",
                "char_count": len(content),
                "word_count": words,
                "line_count": len(lines),
                "section_count": len(sections),
            }
        except Exception as e:
            return {"type": "markdown", "error": str(e)}

    def _split_into_chunk_specs(
        self, text: str, max_chars: int = 3500
    ) -> List[Tuple[str, str]]:
        """
        Splits Markdown into (chunk_text, sep_after_chunk) specs respecting fenced code blocks
        and table row boundaries.
        """
        if not text:
            return [("", "")]

        trailing_nl = "\n" if text.endswith("\n") else ""
        if len(text) <= max_chars:
            return [(text, "")]

        blocks = _tokenize_markdown_blocks(text)

        # Expand oversized blocks safely without ever breaking a fenced code block
        atomic_units: List[Tuple[str, str]] = []
        for kind, block_text, sep_after in blocks:
            if len(block_text) <= max_chars or kind == "code_fence":
                atomic_units.append((block_text, sep_after))
            else:
                # Split oversized table or prose block along line boundaries
                b_lines = block_text.splitlines()
                cur_lines: List[str] = []
                cur_len = 0
                for ln_idx, ln in enumerate(b_lines):
                    ln_len = len(ln) + (1 if cur_lines else 0)
                    if cur_lines and cur_len + ln_len > max_chars:
                        atomic_units.append(("\n".join(cur_lines), "\n"))
                        cur_lines = [ln]
                        cur_len = len(ln)
                    else:
                        cur_lines.append(ln)
                        cur_len += ln_len
                if cur_lines:
                    atomic_units.append(("\n".join(cur_lines), sep_after))

        chunks: List[Tuple[str, str]] = []
        buf_text = ""
        pending_sep = ""

        for unit_text, unit_sep in atomic_units:
            if not buf_text:
                buf_text = unit_text
                pending_sep = unit_sep
                continue

            candidate_len = len(buf_text) + len(pending_sep) + len(unit_text)
            if candidate_len > max_chars:
                chunks.append((buf_text, pending_sep))
                buf_text = unit_text
                pending_sep = unit_sep
            else:
                buf_text = f"{buf_text}{pending_sep}{unit_text}"
                pending_sep = unit_sep

        if buf_text or pending_sep:
            chunks.append((buf_text, pending_sep or trailing_nl))

        return chunks

    def _split_into_chunks(self, text: str, max_chars: int = 3500) -> List[str]:
        """Splits markdown text into structure-safe chunks."""
        return [chunk for chunk, _ in self._split_into_chunk_specs(text, max_chars=max_chars)]

    def read_content(self, src_path: Path) -> str:
        """Reads markdown using deterministic encoding detection."""
        enc = detect_text_encoding(src_path)
        with open(src_path, "r", encoding=enc, errors="replace") as f:
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
        **kwargs,
    ) -> str:
        """
        Main processing method for Markdown files.
        Chunks files along block/row boundaries, checks Translation Memory Cache,
        translates uncached chunks via LLM concurrently, and writes output file.
        """
        self._is_cancelled = False
        src_path = Path(file_path)
        if not src_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        target_lang, source_lang, options = self._resolve_params(
            target_lang, source_lang, options, kwargs
        )

        content = self.read_content(src_path)
        if not content.strip():
            target_path = (
                Path(custom_output_path)
                if custom_output_path
                else get_smart_output_path(source_path=src_path, target_lang=target_lang, is_bilingual=False)
            )
            output_path = safe_save_markdown(content, target_path)
            if progress_callback:
                progress_callback(100, 100, f"Saved: {output_path.name}")
            return str(output_path)

        chunk_specs = self._split_into_chunk_specs(content)
        total_chunks = len(chunk_specs)
        translated_chunks: List[Optional[str]] = [None] * total_chunks

        translatable_indices: List[int] = []
        translatable_inputs: List[str] = []
        for idx, (chunk_text, _) in enumerate(chunk_specs):
            if not chunk_text.strip():
                translated_chunks[idx] = chunk_text
            else:
                translatable_indices.append(idx)
                translatable_inputs.append(chunk_text)

        model_id = self._get_cache_model_id()
        cached_map, uncached_items = self.cache.get_batch(
            texts=translatable_inputs,
            target_lang=target_lang,
            options=options,
            source_lang=source_lang,
            mode="markdown",
            model_id=model_id,
        )

        for local_idx, trans_val in cached_map.items():
            translated_chunks[translatable_indices[local_idx]] = trans_val

        cache_hits = len(cached_map)
        completed_count = cache_hits
        total_translatable = len(translatable_inputs)

        if progress_callback:
            progress_callback(
                5,
                100,
                f"Prepared {total_chunks} sections ({cache_hits} from memory cache)...",
            )

        if uncached_items:
            def translate_single_chunk(item: Tuple[int, str]) -> Tuple[int, str]:
                local_idx, chunk_text = item
                if self._is_cancelled:
                    raise InterruptedError("Translation was cancelled by user.")

                trans = self.llm_manager.translate_markdown_text(
                    markdown_text=chunk_text,
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang,
                    cancel_check=lambda: self._is_cancelled,
                )
                self.cache.save_batch(
                    source_texts=[chunk_text],
                    translated_texts=[trans],
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang,
                    mode="markdown",
                    model_id=model_id,
                )
                return local_idx, trans

            max_workers = self.get_max_workers(len(uncached_items))

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_chunk = {
                    executor.submit(translate_single_chunk, item): item[0]
                    for item in uncached_items
                }

                for future in as_completed(future_to_chunk):
                    if self._is_cancelled:
                        executor.shutdown(wait=False, cancel_futures=True)
                        raise InterruptedError("Translation was cancelled by user.")

                    local_idx, trans = future.result()
                    translated_chunks[translatable_indices[local_idx]] = trans
                    completed_count += 1
                    pct = 10 + int((completed_count / max(1, total_translatable)) * 80)
                    if progress_callback:
                        progress_callback(
                            pct,
                            100,
                            f"Section {completed_count}/{total_translatable} completed ({cache_hits} cached)...",
                        )

        if self._is_cancelled:
            raise InterruptedError("Translation was cancelled by user.")

        if progress_callback:
            progress_callback(95, 100, "Saving translated markdown document...")

        parts: List[str] = []
        for idx, (orig_chunk, sep_after) in enumerate(chunk_specs):
            t_val = translated_chunks[idx]
            parts.append(orig_chunk if t_val is None else t_val)
            if sep_after:
                parts.append(sep_after)
        final_markdown = "".join(parts)

        target_path = (
            Path(custom_output_path)
            if custom_output_path
            else get_smart_output_path(
                source_path=src_path,
                target_lang=target_lang,
                is_bilingual=False,
            )
        )
        output_path = safe_save_markdown(final_markdown, target_path)

        if progress_callback:
            note = f"Saved to {output_path.name}"
            if output_path.name != target_path.name:
                note += " (safe-renamed to avoid file lock)"
            progress_callback(100, 100, f"Completed! {note}")

        return str(output_path)
