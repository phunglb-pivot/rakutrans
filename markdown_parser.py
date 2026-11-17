"""
Markdown parsing and translation engine for RakuTrans AI.
Handles .md files using structure-aware block tokenization that keeps fenced code blocks
intact, splits oversized tables strictly at row boundaries without breaking table continuity,
and preserves exact inter-block separators.
"""

from pathlib import Path
import re
from typing import List, Tuple, Callable, Optional

from base_translator import (
    BaseTranslator,
    count_words_multilingual,
    detect_text_encoding,
    safe_save_file,
)
from config import AppConfig, TranslationOptions, get_smart_output_path, resolve_config_int
from llm_manager import LLMManager
from translation_cache import TranslationCache

_DEFAULT_MD_CHUNK_CHARS = 3500

# Backtick fence info strings cannot contain backticks (CommonMark spec),
# preventing lines starting with inline ```code``` spans from hijacking tokenization.
_FENCE_OPEN_RE = re.compile(r"^\s*(?:(`{3,})([^`]*)|(~{3,})(.*))$")


def match_code_fence_open(line: str) -> Optional[Tuple[str, int]]:
    """Returns (fence_char, fence_len) if line opens a fenced code block, else None."""
    m = _FENCE_OPEN_RE.match(line)
    if not m:
        return None
    fence_seq = m.group(1) or m.group(3)
    return fence_seq[0], len(fence_seq)


def build_close_fence_regex(fence_char: str, fence_len: int) -> re.Pattern:
    """Builds regex matching the closing delimiter of an open fenced code block."""
    return re.compile(rf"^\s*{re.escape(fence_char)}{{{fence_len},}}\s*$")


def is_md_table_line(line: str) -> bool:
    """Returns True when a line looks like a pipe-delimited Markdown table row."""
    stripped = line.strip()
    return len(stripped) >= 2 and stripped.startswith("|") and stripped.endswith("|")


def _has_translatable_markdown(chunk_text: str) -> bool:
    """Returns True if chunk contains at least one non-empty prose/heading/table block outside code fences."""
    if not chunk_text or not chunk_text.strip():
        return False
    return any(kind != "code_fence" and block_text.strip() for kind, block_text, _ in _tokenize_markdown_blocks(chunk_text))


def _consume_trailing_blanks(lines: List[str], idx: int) -> Tuple[int, str]:
    """Consumes blank lines after a block and returns (next_idx, separator_text)."""
    n = len(lines)
    if idx >= n:
        return idx, ""
    blank_run = 0
    while idx < n and not lines[idx].strip():
        blank_run += 1
        idx += 1
    return idx, "\n" * (1 + blank_run)


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

        fence_open = match_code_fence_open(lines[i])
        if fence_open:
            fence_char, fence_len = fence_open
            close_re = build_close_fence_regex(fence_char, fence_len)

            buf = [lines[i]]
            i += 1
            while i < n:
                buf.append(lines[i])
                if close_re.match(lines[i]):
                    i += 1
                    break
                i += 1
            i, sep = _consume_trailing_blanks(lines, i)
            blocks.append(("code_fence", "\n".join(buf), sep))
            continue

        if is_md_table_line(lines[i]):
            buf = [lines[i]]
            i += 1
            while i < n and is_md_table_line(lines[i]):
                buf.append(lines[i])
                i += 1
            i, sep = _consume_trailing_blanks(lines, i)
            blocks.append(("table", "\n".join(buf), sep))
            continue

        # Prose / heading / list paragraph until blank line, fence, or table
        buf = [lines[i]]
        i += 1
        while i < n:
            if not lines[i].strip() or match_code_fence_open(lines[i]) or is_md_table_line(lines[i]):
                break
            buf.append(lines[i])
            i += 1
        i, sep = _consume_trailing_blanks(lines, i)
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
        self, text: str, max_chars: int = _DEFAULT_MD_CHUNK_CHARS
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
                for ln in b_lines:
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
            if not buf_text and not pending_sep:
                buf_text = unit_text
                pending_sep = unit_sep
                continue

            if not buf_text and pending_sep:
                # Preserve leading blank lines from blocks[0] == ("prose", "", "\n...")
                chunks.append(("", pending_sep))
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
            output_path = safe_save_file(
                lambda p: p.write_text(content, encoding="utf-8"), target_path
            )
            if progress_callback:
                progress_callback(100, 100, self._t("progress_saved_file", filename=output_path.name))
            return str(output_path)

        section_max_chars = resolve_config_int(self.config, "section_max_chars")
        chunk_specs = self._split_into_chunk_specs(content, max_chars=section_max_chars)
        total_chunks = len(chunk_specs)
        section_inputs = [
            chunk_text for chunk_text, _ in chunk_specs if _has_translatable_markdown(chunk_text)
        ]

        def _on_cache_checked(cache_hits: int, _total_unique: int) -> None:
            if progress_callback:
                progress_callback(
                    5,
                    100,
                    self._t("progress_prepared_md", total=total_chunks, cached=cache_hits),
                )

        section_map = self.translate_unique_sections(
            sections=section_inputs,
            target_lang=target_lang,
            source_lang=source_lang,
            options=options,
            mode="markdown",
            plain_text=False,
            progress_callback=progress_callback,
            progress_start=10,
            progress_span=80,
            on_cache_checked=_on_cache_checked,
        )

        if self._is_cancelled:
            raise InterruptedError("Translation was cancelled by user.")

        if progress_callback:
            progress_callback(95, 100, self._t("progress_saving_md"))

        parts: List[str] = []
        for orig_chunk, sep_after in chunk_specs:
            if not orig_chunk.strip():
                parts.append(orig_chunk)
            else:
                parts.append(section_map.get(orig_chunk, orig_chunk))
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
        output_path = safe_save_file(
            lambda p: p.write_text(final_markdown, encoding="utf-8"), target_path
        )

        if progress_callback:
            note_key = "progress_saved_lock_note" if output_path.name != target_path.name else "progress_saved_to"
            note = self._t(note_key, filename=output_path.name)
            progress_callback(100, 100, self._t("progress_completed_note", note=note))

        return str(output_path)
