"""
Base translator abstraction, text-filtering, encoding detection, and file-saving utilities for RakuTrans AI.
Provides a unified contract for all document and data format parsers.
"""

from abc import ABC, abstractmethod
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import replace
import errno
import math
from pathlib import Path
import re
import threading
from typing import Callable, Optional, Dict, Any, List, Tuple, TypeVar

T = TypeVar("T")

from config import (
    AppConfig,
    NUMERIC_SETTING_SPECS,
    TranslationOptions,
    resolve_config_int,
)
from llm_manager import LLMManager
from model_fetcher import get_model_metadata
from translation_cache import TranslationCache

_ESTIMATE_CHAR_RATIO = 0.7
_APPEND_ORIGINAL_CHAR_RATIO = 0.75
_INLINE_TAG_CHAR_WEIGHT = 24
_ENCODING_SNIFF_BYTES = 65536
_LEGACY_FALLBACK_ENCODINGS = ("cp932", "shift_jis", "euc_jp", "gbk", "cp1252", "latin-1")
_WIN_LOCK_ERRNOS = frozenset({32, 33})
_SAFE_SAVE_MAX_ATTEMPTS = 50
_SMALL_MODEL_OUTPUT_TOKEN_CAP = 2048
_SMALL_MODEL_CHAR_MULTIPLIER = 1.5
_MIN_CHAR_BUDGET = int(NUMERIC_SETTING_SPECS["batch_max_chars"].min_val)
_WORKER_POLL_TIMEOUT_S = 0.25
_DEFAULT_PROGRESS_START = 10
_DEFAULT_PROGRESS_BATCH_SPAN = 75
_DEFAULT_PROGRESS_SECTION_SPAN = 80


def compute_effective_batch_char_limit(
    config: Optional[AppConfig],
    options: Optional[TranslationOptions] = None,
    max_chars: Optional[int] = None,
) -> int:
    """
    Computes the effective per-batch character budget honoring configured batch_max_chars,
    small model output token limits, and output expansion when append_original_words is enabled.
    """
    configured_chars = resolve_config_int(config, "batch_max_chars")
    if max_chars is not None:
        return max(_MIN_CHAR_BUDGET, min(configured_chars, max_chars))

    char_limit = configured_chars
    if config is not None:
        provider = getattr(config, "active_provider", "") or ""
        model = config.get_active_model() if hasattr(config, "get_active_model") else ""
        if provider and model:
            meta = get_model_metadata(provider, model)
            out_lim = meta.get("output_token_limit") or meta.get("max_tokens")
            if isinstance(out_lim, int) and not isinstance(out_lim, bool) and 0 < out_lim <= _SMALL_MODEL_OUTPUT_TOKEN_CAP:
                char_limit = min(char_limit, max(_MIN_CHAR_BUDGET, int(out_lim * _SMALL_MODEL_CHAR_MULTIPLIER)))

    effective_options = options if options is not None else getattr(config, "translation_options", None)
    if effective_options is not None and getattr(effective_options, "append_original_words", False):
        char_limit = max(_MIN_CHAR_BUDGET, int(char_limit * _APPEND_ORIGINAL_CHAR_RATIO))

    return max(_MIN_CHAR_BUDGET, char_limit)


def estimate_batch_item_chars(text: str) -> int:
    """
    Estimates effective character budget consumed by a batch item, accounting for
    synthetic inline style tags (<s0>...</s0>) that require strict structural preservation.
    """
    if not text:
        return 0
    tag_count = len(_INLINE_TAG_TOKEN_RE.findall(text))
    return len(text) + (tag_count * _INLINE_TAG_CHAR_WEIGHT)


def estimate_translation_requests(
    inspect_info: Optional[Dict[str, Any]],
    config: Optional[AppConfig],
) -> int:
    """Estimates approximate API request count from inspect_file metadata and config."""
    if not inspect_info or "error" in inspect_info:
        return 0

    batch_size = resolve_config_int(config, "batch_size")
    batch_max_chars = compute_effective_batch_char_limit(config)
    section_max_chars = resolve_config_int(config, "section_max_chars")
    opts = getattr(config, "translation_options", None) if config is not None else None
    if opts is not None and getattr(opts, "append_original_words", False):
        section_max_chars = max(_MIN_CHAR_BUDGET, int(section_max_chars * _APPEND_ORIGINAL_CHAR_RATIO))

    doc_type = str(inspect_info.get("type", "") or "").lower()
    if doc_type in ("markdown", "txt"):
        raw_trans_chars = inspect_info.get("translatable_char_count")
        chars = max(
            0,
            int(raw_trans_chars if raw_trans_chars is not None else (inspect_info.get("char_count", 0) or 0)),
        )
        if chars == 0:
            return 0
        return max(1, math.ceil(chars / section_max_chars))

    items = int(
        inspect_info.get("unique_texts")
        or inspect_info.get("translatable_segments")
        or 0
    )
    if items <= 0:
        return 0
    by_items = math.ceil(items / batch_size)
    unique_chars = int(inspect_info.get("unique_char_count", 0) or 0)
    if unique_chars > 0:
        by_chars = math.ceil(unique_chars / batch_max_chars)
        return max(1, by_items, by_chars)
    chars = int(inspect_info.get("char_count", 0) or 0)
    if chars > 0:
        by_chars = math.ceil((chars * _ESTIMATE_CHAR_RATIO) / batch_max_chars)
        return max(1, by_items, by_chars)
    return max(1, by_items)

_NUMERIC_PATTERN = re.compile(
    r"^[+-]?\s*(?:[$€£¥₫₩₹]\s*)?(?:\d{1,3}(?:,\d{3})+|\d{1,3}(?:\.\d{3})+|\d+)(?:[.,]\d+)?\s*(?:[$€£¥₫₩₹]|%)?$"
)
_NON_TRANSLATABLE_TOKEN_RE = re.compile(
    r"^(?:"
    r"https?://\S+"
    r"|mailto:\S+"
    r"|#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})"
    r"|\d{4}[-/]\d{2}[-/]\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r")$"
)
_LOCK_ERRNOS = frozenset(
    err for err in (
        getattr(errno, "EACCES", None),
        getattr(errno, "EPERM", None),
        getattr(errno, "EBUSY", None),
        getattr(errno, "ETXTBSY", None),
    )
    if err is not None
)
_CJK_CHAR_RE = re.compile(
    r"[\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)
_NON_CJK_TOKEN_RE = re.compile(
    r"[^\s\u3040-\u309f\u30a0-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]+"
)
_INLINE_TAG_TOKEN_RE = re.compile(r"</?s\d+>")
_INLINE_SPAN_RE = re.compile(r"<s(\d+)>(.*?)</s\1>", flags=re.DOTALL)


def count_words_multilingual(text: str) -> int:
    """
    Counts words accurately for both space-delimited scripts (Latin, Cyrillic, etc.)
    and unspaced CJK/Kana/Hangul characters.
    """
    if not text:
        return 0
    cjk_count = len(_CJK_CHAR_RE.findall(text))
    non_cjk_count = len(_NON_CJK_TOKEN_RE.findall(text))
    return cjk_count + non_cjk_count


def contains_literal_inline_tags(text: str) -> bool:
    """Returns True if source text already contains literal <sN> or </sN> markup."""
    return bool(_INLINE_TAG_TOKEN_RE.search(text or ""))


def strip_inline_tags(text: str) -> str:
    """Removes synthetic <sN>...</sN> markers from text."""
    return _INLINE_TAG_TOKEN_RE.sub("", text or "")


def build_inline_tagged_text(groups: List[Tuple[Any, str]]) -> str:
    """Formats style-grouped segments into deterministic <s0>...</s0><s1>...</s1> markup."""
    return "".join(f"<s{idx}>{seg_text}</s{idx}>" for idx, (_, seg_text) in enumerate(groups))


def parse_inline_tagged_text(
    translated: str, group_count: int
) -> Optional[List[Tuple[int, str]]]:
    """
    Parses translated <sN>...</sN> output into an ordered list of (group_idx, text) pairs.
    Preserves any text emitted outside tags by attaching leading text to the first tag
    and inter-tag/trailing text to the adjacent tag. Returns None if tags are incomplete/invalid.
    """
    matches = list(_INLINE_SPAN_RE.finditer(translated or ""))
    if not matches:
        return None

    ordered_segments: List[Tuple[int, str]] = []
    seen_indices = set()
    last_end = 0

    for m in matches:
        idx = int(m.group(1))
        if idx < 0 or idx >= group_count:
            return None
        gap = translated[last_end : m.start()]
        inner = m.group(2)
        if not ordered_segments:
            ordered_segments.append((idx, gap + inner))
        else:
            if gap:
                prev_idx, prev_text = ordered_segments[-1]
                ordered_segments[-1] = (prev_idx, prev_text + gap)
            ordered_segments.append((idx, inner))
        seen_indices.add(idx)
        last_end = m.end()

    tail = translated[last_end:]
    if tail and ordered_segments:
        prev_idx, prev_text = ordered_segments[-1]
        ordered_segments[-1] = (prev_idx, prev_text + tail)

    if seen_indices != set(range(group_count)):
        return None

    return ordered_segments


def should_translate_text(value: Any, ignore_formulas: bool = True) -> bool:
    """
    Determines whether a text value contains translatable human language content.
    Strictly skips non-strings, empty text, formulas, pure numbers/currency, and punctuation-only strings.
    """
    if value is None or not isinstance(value, str):
        return False

    trimmed = value.strip()
    if not trimmed:
        return False

    if ignore_formulas and trimmed.startswith("="):
        return False

    if _NUMERIC_PATTERN.fullmatch(trimmed):
        return False

    if _NON_TRANSLATABLE_TOKEN_RE.fullmatch(trimmed):
        return False

    return any(c.isalnum() for c in trimmed)


def detect_text_encoding(file_path: Path) -> str:
    """
    Deterministically detects text encoding with BOM checks first, then strict UTF-8,
    then charset_normalizer (if available) / common legacy encodings.
    """
    try:
        with open(file_path, "rb") as fb:
            raw = fb.read(_ENCODING_SNIFF_BYTES)
    except OSError:
        return "utf-8"

    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    if raw.startswith(b"\xff\xfe"):
        return "utf-16-le"
    if raw.startswith(b"\xfe\xff"):
        return "utf-16-be"

    try:
        raw.decode("utf-8", errors="strict")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        from charset_normalizer import from_bytes
        best = from_bytes(raw).best()
        if best and best.encoding:
            return best.encoding
    except Exception:
        pass

    for enc in _LEGACY_FALLBACK_ENCODINGS:
        try:
            raw.decode(enc, errors="strict")
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    return "utf-8"


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

    attempts = 0
    while True:
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            save_fn(out_path)
            return out_path
        except OSError as e:
            is_lock_error = (
                isinstance(e, PermissionError)
                or e.errno in _LOCK_ERRNOS
                or getattr(e, "winerror", None) in _WIN_LOCK_ERRNOS
            )
            if not is_lock_error:
                raise
            attempts += 1
            if attempts > _SAFE_SAVE_MAX_ATTEMPTS:
                raise
            out_path = target_path.parent / f"{base_stem} ({counter}){suffix}"
            counter += 1


class BaseTranslator(ABC):
    """
    Abstract base class for all file translators in RakuTrans AI.
    All format implementations (Excel, Markdown, Word, PowerPoint, CSV, JSON, TXT, PDF)
    must adhere to this interface.
    """

    SUPPORTS_BILINGUAL: bool = False

    def __init__(
        self,
        config: AppConfig,
        llm_manager: LLMManager,
        cache: Optional[TranslationCache] = None,
        i18n: Optional[Any] = None,
    ):
        self.config = config
        self.llm_manager = llm_manager
        self.cache = cache or TranslationCache()
        self._i18n = i18n
        self._cancel_flag = False
        self._cancel_event = threading.Event()

    def _t(self, key: str, **kwargs: Any) -> str:
        """Formats localized status/progress strings honoring config.ui_language."""
        lang = getattr(self.config, "ui_language", "en") or "en"
        if self._i18n is None:
            from i18n import I18nManager
            self._i18n = I18nManager(lang)
        elif hasattr(self._i18n, "set_language"):
            self._i18n.set_language(lang)
        return self._i18n.t(key, **kwargs)

    @property
    def _is_cancelled(self) -> bool:
        return self._cancel_flag

    @_is_cancelled.setter
    def _is_cancelled(self, value: bool) -> None:
        self._cancel_flag = bool(value)
        if not self._cancel_flag:
            # Allocate a fresh event per run so lingering cancelled workers keep seeing their own set event
            self._cancel_event = threading.Event()
        else:
            self._cancel_event.set()

    def cancel(self) -> None:
        """Signals the translation process to abort."""
        self._is_cancelled = True

    @property
    def is_cancelled(self) -> bool:
        """Returns True if user requested cancellation."""
        return self._cancel_flag

    def _resolve_params(
        self,
        target_lang: Optional[str],
        source_lang: Optional[str],
        options: Optional[TranslationOptions],
        kwargs: Dict[str, Any],
    ) -> Tuple[str, str, TranslationOptions]:
        """Resolves effective target language, source language, and options deterministically."""
        resolved_target = target_lang or kwargs.get("target_lang") or self.config.target_language
        resolved_source = (source_lang or kwargs.get("source_lang") or "auto").strip() or "auto"
        resolved_options = options if options is not None else self.config.translation_options
        if not self.SUPPORTS_BILINGUAL and getattr(resolved_options, "bilingual_mode", False):
            resolved_options = replace(resolved_options, bilingual_mode=False)
        return resolved_target, resolved_source, resolved_options

    def _get_cache_model_id(self) -> str:
        """Returns stable provider:model identifier for cache key isolation."""
        provider = getattr(self.config, "active_provider", "") or ""
        if hasattr(self.config, "get_active_model"):
            try:
                model = self.config.get_active_model() or ""
            except Exception:
                model = ""
        else:
            model = ""
        if provider and model:
            return f"{provider}:{model}"
        return provider or model

    def pack_batches(
        self,
        items: List[T],
        text_fn: Callable[[T], str] = lambda x: str(x),
        max_items: Optional[int] = None,
        max_chars: Optional[int] = None,
        options: Optional[TranslationOptions] = None,
    ) -> List[List[T]]:
        """Partitions uncached items into batches bounded by configured item count and character budget."""
        if not items:
            return []

        configured_items = resolve_config_int(self.config, "batch_size")
        item_limit = max(1, min(configured_items, max_items)) if max_items is not None else configured_items
        char_limit = compute_effective_batch_char_limit(
            self.config,
            options=options,
            max_chars=max_chars,
        )

        batches: List[List[T]] = []
        curr_batch: List[T] = []
        curr_chars = 0

        for item in items:
            item_chars = estimate_batch_item_chars(text_fn(item))
            if curr_batch and (len(curr_batch) >= item_limit or (curr_chars + item_chars > char_limit)):
                batches.append(curr_batch)
                curr_batch = [item]
                curr_chars = item_chars
            else:
                curr_batch.append(item)
                curr_chars += item_chars

        if curr_batch:
            batches.append(curr_batch)

        return batches

    def get_max_workers(self, total_tasks: int) -> int:
        """Returns bounded worker count for concurrent API requests."""
        if total_tasks <= 1:
            return 1

        configured_workers = resolve_config_int(self.config, "max_concurrent_requests")
        return min(configured_workers, total_tasks)

    def _run_concurrent_tasks(
        self,
        tasks: List[T],
        worker_fn: Callable[[T, Callable[[], bool]], Any],
        on_result: Callable[[T, Any], None],
    ) -> None:
        """
        Executes tasks in a bounded ThreadPoolExecutor using a sliding window of
        in-flight futures, per-run cancellation, and non-blocking abort shutdown.
        """
        if not tasks:
            return
        run_event = self._cancel_event
        abort_event = threading.Event()
        is_run_cancelled = lambda: abort_event.is_set() or run_event.is_set()

        if is_run_cancelled():
            raise InterruptedError("Translation cancelled by user.")

        max_workers = self.get_max_workers(len(tasks))
        in_flight_limit = max_workers * 2
        executor = ThreadPoolExecutor(max_workers=max_workers)
        wait_on_exit = True
        try:
            task_iter = iter(tasks)
            pending: Dict[Future, T] = {}

            def _refill_window() -> None:
                while len(pending) < in_flight_limit and not is_run_cancelled():
                    try:
                        next_task = next(task_iter)
                    except StopIteration:
                        break
                    fut = executor.submit(worker_fn, next_task, is_run_cancelled)
                    pending[fut] = next_task

            _refill_window()
            while pending:
                if is_run_cancelled():
                    raise InterruptedError("Translation cancelled by user.")

                done, _ = wait(pending.keys(), timeout=_WORKER_POLL_TIMEOUT_S, return_when=FIRST_COMPLETED)
                if is_run_cancelled():
                    raise InterruptedError("Translation cancelled by user.")
                if not done:
                    continue

                for future in done:
                    task_item = pending.pop(future)
                    try:
                        res = future.result()
                    except Exception:
                        if is_run_cancelled():
                            raise InterruptedError("Translation cancelled by user.")
                        raise
                    on_result(task_item, res)

                _refill_window()
        except BaseException:
            wait_on_exit = False
            abort_event.set()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            if wait_on_exit:
                executor.shutdown(wait=True)

    def translate_unique_texts(
        self,
        unique_texts: List[str],
        target_lang: str,
        source_lang: str,
        options: TranslationOptions,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        progress_start: int = _DEFAULT_PROGRESS_START,
        progress_span: int = _DEFAULT_PROGRESS_BATCH_SPAN,
        duplicate_saved: int = 0,
    ) -> Dict[str, str]:
        """
        Shared deterministic cache lookup, concurrent batch translation, and cache persistence.
        Guarantees options, source_lang, mode, and model_id are passed consistently to TranslationCache.
        """
        if not unique_texts:
            return {}

        model_id = self._get_cache_model_id()
        cached_map, uncached_items = self.cache.get_batch(
            texts=unique_texts,
            target_lang=target_lang,
            options=options,
            source_lang=source_lang,
            mode="batch",
            model_id=model_id,
        )

        translation_map: Dict[str, str] = {}
        for idx, trans in cached_map.items():
            translation_map[unique_texts[idx]] = trans

        cache_hits = len(cached_map)
        if not uncached_items:
            return translation_map

        batches = self.pack_batches(uncached_items, text_fn=lambda item: item[1], options=options)
        total_batches = len(batches)
        completed_batches = 0

        def translate_worker(
            batch_items: List[Tuple[int, str]],
            cancel_check: Callable[[], bool],
        ) -> Tuple[List[str], List[str]]:
            if cancel_check():
                raise InterruptedError("Translation cancelled by user.")
            src_batch = [item[1] for item in batch_items]
            translated = self.llm_manager.translate_batch(
                texts=src_batch,
                target_lang=target_lang,
                source_lang=source_lang,
                options=options,
                cancel_check=cancel_check,
            )
            if len(translated) != len(src_batch):
                raise ValueError(
                    f"Batch translation count mismatch: expected {len(src_batch)}, got {len(translated)}."
                )
            return src_batch, translated

        def on_batch_done(_batch: List[Tuple[int, str]], result: Tuple[List[str], List[str]]) -> None:
            nonlocal completed_batches
            src_texts, trans_texts = result
            effective_model_id = self._get_cache_model_id() or model_id
            self.cache.save_batch(
                source_texts=src_texts,
                translated_texts=trans_texts,
                target_lang=target_lang,
                options=options,
                source_lang=source_lang,
                mode="batch",
                model_id=effective_model_id,
            )
            for orig, trans in zip(src_texts, trans_texts):
                translation_map[orig] = trans

            completed_batches += 1
            pct = progress_start + int((completed_batches / total_batches) * progress_span)
            if progress_callback:
                if duplicate_saved > 0:
                    msg = self._t(
                        "progress_batch_dedup",
                        done=completed_batches,
                        total=total_batches,
                        cached=cache_hits,
                        dedup=duplicate_saved,
                    )
                else:
                    msg = self._t(
                        "progress_batch",
                        done=completed_batches,
                        total=total_batches,
                    )
                progress_callback(pct, 100, msg)

        self._run_concurrent_tasks(batches, translate_worker, on_batch_done)
        return translation_map

    def translate_unique_sections(
        self,
        sections: List[str],
        target_lang: str,
        source_lang: str,
        options: TranslationOptions,
        mode: str = "markdown",
        plain_text: bool = False,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        progress_start: int = _DEFAULT_PROGRESS_START,
        progress_span: int = _DEFAULT_PROGRESS_SECTION_SPAN,
        on_cache_checked: Optional[Callable[[int, int], None]] = None,
        progress_formatter: Optional[Callable[[int, int, int], str]] = None,
    ) -> Dict[str, str]:
        """
        Shared cache lookup, deduplicated concurrent section translation, and single-thread
        cache persistence for Markdown and plain-text translators.
        """
        unique_sections = list(dict.fromkeys(s for s in sections if s and s.strip()))
        if not unique_sections:
            return {}

        model_id = self._get_cache_model_id()
        cached_map, uncached_items = self.cache.get_batch(
            texts=unique_sections,
            target_lang=target_lang,
            options=options,
            source_lang=source_lang,
            mode=mode,
            model_id=model_id,
        )

        translation_map: Dict[str, str] = {
            unique_sections[idx]: trans for idx, trans in cached_map.items()
        }
        cache_hits = len(cached_map)
        completed_count = cache_hits
        total_unique = len(unique_sections)

        if on_cache_checked:
            on_cache_checked(cache_hits, total_unique)

        if not uncached_items:
            return translation_map

        def translate_worker(
            item: Tuple[int, str],
            cancel_check: Callable[[], bool],
        ) -> Tuple[str, str]:
            _, section_text = item
            if cancel_check():
                raise InterruptedError("Translation cancelled by user.")
            translated = self.llm_manager.translate_markdown_text(
                markdown_text=section_text,
                target_lang=target_lang,
                options=options,
                source_lang=source_lang,
                cancel_check=cancel_check,
                plain_text=plain_text,
            )
            return section_text, translated

        def on_section_done(_item: Tuple[int, str], result: Tuple[str, str]) -> None:
            nonlocal completed_count
            section_text, translated = result
            effective_model_id = self._get_cache_model_id() or model_id
            self.cache.save_batch(
                source_texts=[section_text],
                translated_texts=[translated],
                target_lang=target_lang,
                options=options,
                source_lang=source_lang,
                mode=mode,
                model_id=effective_model_id,
            )
            translation_map[section_text] = translated
            completed_count += 1
            pct = progress_start + int((completed_count / max(1, total_unique)) * progress_span)
            if progress_callback:
                msg = (
                    progress_formatter(completed_count, total_unique, cache_hits)
                    if progress_formatter
                    else self._t(
                        "progress_section",
                        done=completed_count,
                        total=total_unique,
                        cached=cache_hits,
                    )
                )
                progress_callback(pct, 100, msg)

        self._run_concurrent_tasks(uncached_items, translate_worker, on_section_done)
        return translation_map

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
        **kwargs,
    ) -> str:
        """
        Main translation flow. Translates content while preserving formatting and layout,
        and saves output file. Returns the path of the saved file.
        """
        pass
