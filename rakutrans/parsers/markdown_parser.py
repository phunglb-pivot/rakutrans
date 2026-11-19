"""
Markdown parsing and translation engine for RakuTrans AI.
Handles .md files using structure-aware block tokenization that keeps fenced code blocks
intact, splits oversized tables strictly at row boundaries without breaking table continuity,
and preserves exact inter-block separators.
"""

from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

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
_STANDALONE_CODE_FENCE_MIN_CHARS = 150
_CODE_PLACEHOLDER_BASE = "RAKUTRANS_CODE_"

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


def _choose_placeholder_prefix(content: str) -> str:
    """Chooses a placeholder prefix guaranteed not to collide with source Markdown text."""
    prefix = _CODE_PLACEHOLDER_BASE
    while f"<<<{prefix}" in content:
        prefix = f"X{prefix}"
    return prefix


def _normalize_and_validate_placeholders(
    translated: str, tokens: Iterable[str]
) -> Optional[str]:
    """
    Validates that every placeholder token appears exactly once in translated text
    (tolerating accidental single-backtick wrapping by the model) and returns normalized text.
    """
    out = translated
    for token in tokens:
        if f"`{token}`" in out:
            out = out.replace(f"`{token}`", token)
        if out.count(token) != 1:
            return None
    return out


def _restore_masked_placeholders(
    translated: str, placeholders: Dict[str, str]
) -> Optional[str]:
    """Restores verbatim code blocks for each placeholder, or returns None if validation fails."""
    if not placeholders:
        return translated
    normalized = _normalize_and_validate_placeholders(translated, placeholders.keys())
    if normalized is None:
        return None
    for token, orig_gap in placeholders.items():
        normalized = normalized.replace(token, orig_gap, 1)
    return normalized


def _build_masked_chunk_plan(
    chunk_specs: List[Tuple[str, str]],
    max_chars: int,
    placeholder_prefix: str,
) -> List[Dict[str, Any]]:
    """
    Coalesces consecutive translatable Markdown chunks separated by isolated code fences
    into masked chunks up to max_chars, avoiding extra API calls for interleaved code blocks.
    """
    plan: List[Dict[str, Any]] = []
    active: Optional[Dict[str, Any]] = None

    def _flush_active() -> None:
        nonlocal active
        if active is None:
            return
        trailing_gap = active["pending_gap"]
        plan.append({
            "kind": "masked",
            "masked_text": "".join(active["parts"]),
            "placeholders": active["placeholders"],
            "sep": active["pending_sep"],
            "sub_specs": active["sub_specs"],
        })
        active = None
        for gap_text, gap_sep in trailing_gap:
            plan.append({"kind": "literal", "text": gap_text, "sep": gap_sep})

    def _start_active(chunk_text: str, sep_after: str) -> None:
        nonlocal active
        active = {
            "parts": [chunk_text],
            "cur_len": len(chunk_text),
            "pending_sep": sep_after,
            "pending_gap": [],
            "placeholders": {},
            "sub_specs": [(chunk_text, sep_after)],
        }

    for chunk_text, sep_after in chunk_specs:
        if not _has_translatable_markdown(chunk_text):
            if active is None:
                plan.append({"kind": "literal", "text": chunk_text, "sep": sep_after})
            else:
                active["pending_gap"].append((chunk_text, sep_after))
            continue

        if active is None:
            _start_active(chunk_text, sep_after)
            continue

        pending_gap = active["pending_gap"]
        if not pending_gap or not any(g_text for g_text, _ in pending_gap):
            extra_sep = active["pending_sep"] + "".join(g_text + g_sep for g_text, g_sep in pending_gap)
            candidate_len = active["cur_len"] + len(extra_sep) + len(chunk_text)
            if candidate_len <= max_chars:
                active["parts"].extend((extra_sep, chunk_text))
                active["cur_len"] = candidate_len
                active["pending_sep"] = sep_after
                active["pending_gap"] = []
                active["sub_specs"].extend(pending_gap)
                active["sub_specs"].append((chunk_text, sep_after))
            else:
                _flush_active()
                _start_active(chunk_text, sep_after)
            continue

        sep_before = active["pending_sep"]
        sep_after_tok = pending_gap[-1][1]
        token = f"<<<{placeholder_prefix}{len(active['placeholders'])}>>>"
        candidate_len = (
            active["cur_len"]
            + len(sep_before)
            + len(token)
            + len(sep_after_tok)
            + len(chunk_text)
        )
        can_mask_safely = (
            candidate_len <= max_chars
            and sep_before.endswith("\n")
            and sep_after_tok.startswith("\n")
        )
        if can_mask_safely:
            gap_body = "".join(g_text + g_sep for g_text, g_sep in pending_gap[:-1]) + pending_gap[-1][0]
            active["placeholders"][token] = gap_body
            active["parts"].extend((sep_before, token, sep_after_tok, chunk_text))
            active["cur_len"] = candidate_len
            active["pending_sep"] = sep_after
            active["pending_gap"] = []
            active["sub_specs"].extend(pending_gap)
            active["sub_specs"].append((chunk_text, sep_after))
        else:
            _flush_active()
            _start_active(chunk_text, sep_after)

    _flush_active()
    return plan


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
            blocks = _tokenize_markdown_blocks(content)
            sections = [b for _, b, _ in blocks if b.strip()]
            translatable_chars = sum(
                len(b) + len(sep)
                for kind, b, sep in blocks
                if b.strip() and not (kind == "code_fence" and len(b) >= _STANDALONE_CODE_FENCE_MIN_CHARS)
            )

            return {
                "type": "markdown",
                "char_count": len(content),
                "translatable_char_count": translatable_chars,
                "word_count": words,
                "line_count": len(lines),
                "section_count": len(sections),
            }
        except Exception as e:
            return {"type": "markdown", "error": str(e)}

    @staticmethod
    def _split_long_prose_line(line: str, max_chars: int) -> List[str]:
        """Splits an oversized single prose line (> max_chars) along whitespace without dropping chars."""
        if len(line) <= max_chars:
            return [line]
        parts: List[str] = []
        start = 0
        n = len(line)
        while start < n:
            if n - start <= max_chars:
                parts.append(line[start:])
                break
            split_at = line.rfind(" ", start, start + max_chars + 1)
            if split_at <= start:
                split_at = start + max_chars
            else:
                split_at += 1  # Keep trailing space with left piece so exact join == original
            parts.append(line[start:split_at])
            start = split_at
        return parts

    def _split_into_chunk_specs(
        self, text: str, max_chars: int = _DEFAULT_MD_CHUNK_CHARS
    ) -> List[Tuple[str, str]]:
        """
        Splits Markdown into (chunk_text, sep_after_chunk) specs respecting fenced code blocks
        and table row boundaries, while isolating large fenced code blocks so they bypass LLM calls.
        """
        if not text:
            return [("", "")]

        trailing_nl = "\n" if text.endswith("\n") else ""
        standalone_fence_min = min(_STANDALONE_CODE_FENCE_MIN_CHARS, max(60, max_chars // 4))
        blocks = _tokenize_markdown_blocks(text)
        has_standalone_fence = any(
            kind == "code_fence" and len(block_text) >= standalone_fence_min
            for kind, block_text, _ in blocks
        )
        if len(text) <= max_chars and not has_standalone_fence:
            return [(text, "")]

        # Expand oversized blocks safely without ever breaking a fenced code block
        atomic_units: List[Tuple[str, str, str]] = []
        for kind, block_text, sep_after in blocks:
            if len(block_text) <= max_chars or kind == "code_fence":
                atomic_units.append((kind, block_text, sep_after))
            else:
                # Split oversized table or prose block along line (and sub-line whitespace) boundaries
                b_lines = block_text.splitlines()
                cur_lines: List[str] = []
                cur_len = 0
                for l_idx, ln in enumerate(b_lines):
                    is_last_line = l_idx == len(b_lines) - 1
                    line_sep = sep_after if is_last_line else "\n"
                    if len(ln) > max_chars and kind == "prose":
                        if cur_lines:
                            atomic_units.append((kind, "\n".join(cur_lines), "\n"))
                            cur_lines = []
                            cur_len = 0
                        sub_parts = self._split_long_prose_line(ln, max_chars)
                        for s_idx, sub in enumerate(sub_parts):
                            s_sep = "" if s_idx < len(sub_parts) - 1 else line_sep
                            atomic_units.append((kind, sub, s_sep))
                        continue

                    ln_len = len(ln) + (1 if cur_lines else 0)
                    if cur_lines and cur_len + ln_len > max_chars:
                        atomic_units.append((kind, "\n".join(cur_lines), "\n"))
                        cur_lines = [ln]
                        cur_len = len(ln)
                    else:
                        cur_lines.append(ln)
                        cur_len += ln_len
                if cur_lines:
                    atomic_units.append((kind, "\n".join(cur_lines), sep_after))

        chunks: List[Tuple[str, str]] = []
        buf_text = ""
        pending_sep = ""
        buf_is_isolated = False

        for unit_kind, unit_text, unit_sep in atomic_units:
            is_isolated_fence = unit_kind == "code_fence" and len(unit_text) >= standalone_fence_min

            if not buf_text and not pending_sep:
                buf_text = unit_text
                pending_sep = unit_sep
                buf_is_isolated = is_isolated_fence
                continue

            if not buf_text and pending_sep:
                # Preserve leading blank lines from blocks[0] == ("prose", "", "\n...")
                chunks.append(("", pending_sep))
                buf_text = unit_text
                pending_sep = unit_sep
                buf_is_isolated = is_isolated_fence
                continue

            candidate_len = len(buf_text) + len(pending_sep) + len(unit_text)
            if buf_is_isolated or is_isolated_fence or candidate_len > max_chars:
                chunks.append((buf_text, pending_sep))
                buf_text = unit_text
                pending_sep = unit_sep
                buf_is_isolated = is_isolated_fence
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
        placeholder_prefix = _choose_placeholder_prefix(content)
        plan = _build_masked_chunk_plan(chunk_specs, section_max_chars, placeholder_prefix)
        total_chunks = len(plan)

        section_inputs: List[str] = []
        expected_tokens_by_text: Dict[str, Tuple[str, ...]] = {}
        for seg in plan:
            if seg["kind"] == "masked":
                masked_text = seg["masked_text"]
                section_inputs.append(masked_text)
                if seg["placeholders"] and masked_text not in expected_tokens_by_text:
                    expected_tokens_by_text[masked_text] = tuple(seg["placeholders"].keys())

        def _validate_masked_cache(src_chunk: str, translated_chunk: str) -> bool:
            tokens = expected_tokens_by_text.get(src_chunk)
            if not tokens:
                return True
            return _normalize_and_validate_placeholders(translated_chunk, tokens) is not None

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
            cache_validator=_validate_masked_cache,
        )

        if self._is_cancelled:
            raise InterruptedError("Translation was cancelled by user.")

        if progress_callback:
            progress_callback(95, 100, self._t("progress_saving_md"))

        resolved_segments: List[Optional[str]] = []
        fallback_indices: List[int] = []
        fallback_inputs: List[str] = []

        for idx, seg in enumerate(plan):
            if seg["kind"] == "literal":
                resolved_segments.append(f"{seg['text']}{seg['sep']}")
                continue
            raw_translated = section_map.get(seg["masked_text"], seg["masked_text"])
            restored = _restore_masked_placeholders(raw_translated, seg["placeholders"])
            if restored is None:
                resolved_segments.append(None)
                fallback_indices.append(idx)
                for sub_text, _ in seg["sub_specs"]:
                    if _has_translatable_markdown(sub_text):
                        fallback_inputs.append(sub_text)
            else:
                resolved_segments.append(f"{restored}{seg['sep']}")

        if fallback_indices:
            fb_map = self.translate_unique_sections(
                sections=fallback_inputs,
                target_lang=target_lang,
                source_lang=source_lang,
                options=options,
                mode="markdown",
                plain_text=False,
                progress_callback=progress_callback,
                progress_start=90,
                progress_span=5,
            )
            for idx in fallback_indices:
                seg = plan[idx]
                sub_parts: List[str] = []
                for orig_sub, sub_sep in seg["sub_specs"]:
                    if not _has_translatable_markdown(orig_sub):
                        sub_parts.append(orig_sub)
                    else:
                        sub_parts.append(fb_map.get(orig_sub, orig_sub))
                    if sub_sep:
                        sub_parts.append(sub_sep)
                resolved_segments[idx] = "".join(sub_parts)

        final_markdown = "".join(part or "" for part in resolved_segments)

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
