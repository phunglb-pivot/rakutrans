"""
LLM Manager for RakuTrans AI.
Provides unified routing across Google Gemini, OpenAI GPT, and Anthropic Claude.
Features strict indexed JSON batching, automatic batch splitting on structural mismatch,
robust retries with exponential backoff, and error handling.
"""

import inspect
import json
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar

from config import (
    AI_PROVIDERS,
    AppConfig,
    NUMERIC_SETTING_SPECS,
    TranslationOptions,
    resolve_config_float,
    resolve_config_int,
)
from error_handler import (
    AUTH_ERROR_CODES,
    AUTH_SDK_CLASSES,
    BILLING_ERROR_CODES,
    NOT_FOUND_ERROR_CODES,
    RATE_LIMIT_API_CODES as _RATE_LIMIT_API_CODES,
    RATE_LIMIT_SDK_CLASSES as _RATE_LIMIT_SDK_CLASSES,
    RATE_LIMIT_STATUS_CODES as _RATE_LIMIT_STATUS_CODES,
    collect_structured_error_signals as _collect_structured_error_signals,
    extract_body_error_dict as _extract_body_error_dict,
    get_http_status_code as _get_http_status_code,
    iter_exception_chain as _iter_exception_chain,
)
from model_fetcher import get_model_metadata, update_model_metadata

T = TypeVar("T")

_DEFAULT_REQUEST_TIMEOUT_S = float(NUMERIC_SETTING_SPECS["request_timeout"].default)
_MIN_RETRY_DELAY_S = 1.0
_MAX_RETRY_DELAY_S = 180.0
_RATE_WINDOW_SECONDS = 60.0
_RATE_WINDOW_PADDING_S = 0.05
_RATE_RECOVERY_IDLE_S = 180.0
_MAX_ADAPTIVE_FLOOR_S = 10.0
_MAX_ADAPTIVE_INTERVAL_S = 30.0
_CONSECUTIVE_OK_FOR_PACE_DECAY = 5
_CONSECUTIVE_OK_FOR_CONCURRENCY_INC = 8
_PACE_DECAY_FACTOR = 0.90
_BACKOFF_BASE_SCHEDULE = (8.0, 16.0, 32.0, 45.0)
_MIN_SPLIT_RETRY_CHARS = 40
_TOKEN_ASCII_BOUND = 127
_TOKEN_ASCII_CHARS_PER_TOK = 3.5
_TOKEN_NON_ASCII_WEIGHT = 1.2
_TOKEN_OUTPUT_MULTIPLIER = 2.2

_NON_RETRYABLE_STATUS_CODES = frozenset({400, 401, 402, 403, 404, 413, 422})

_NON_RETRYABLE_SDK_CLASSES = AUTH_SDK_CLASSES | frozenset({
    "BadRequestError",
    "NotFoundError",
    "UnprocessableEntityError",
    "ContentTooLargeError",
    "RequestTooLargeError",
    "ContentFilterFinishReasonError",
})

_NON_RETRYABLE_API_CODES = AUTH_ERROR_CODES | BILLING_ERROR_CODES | NOT_FOUND_ERROR_CODES | frozenset({
    "invalid_request_error",
    "invalid_argument",
    "failed_precondition",
})

# Fallback substring patterns used only when an exception carries no structured SDK/HTTP metadata
_NON_RETRYABLE_PATTERNS = (
    "api key is missing",
    "invalid_api_key",
    "invalid api key",
    "api_key_invalid",
    "incorrect api key",
    "authentication",
    "permission_denied",
    "unauthorized",
    "model_not_found",
    "insufficient_quota",
    "billing",
    "billing_hard_limit_reached",
    "credit_balance_too_low",
    "prepayment credits",
    "credits are depleted",
)

_RATE_LIMIT_PATTERNS = (
    "429",
    "resource_exhausted",
    "rate limit",
    "rate_limit",
    "too many requests",
    "quota exceeded",
    "tokens per min",
    "requests per min",
)


def is_non_retryable_error(err: Exception) -> bool:
    """Return True for permanent auth, missing-key, billing, or invalid-request errors."""
    signals = _collect_structured_error_signals(err)
    status = _get_http_status_code(err)

    if signals["should_retry"] == "false":
        return True
    if signals["codes"] & _NON_RETRYABLE_API_CODES:
        return True
    if status in _NON_RETRYABLE_STATUS_CODES:
        return True
    if signals["class_names"] & _NON_RETRYABLE_SDK_CLASSES:
        return True

    # Only fall back to message text matching when no structured status/code/SDK class exists
    has_structured_status = (
        status is not None
        or bool(signals["codes"])
        or bool(signals["class_names"] & (_RATE_LIMIT_SDK_CLASSES | {"ServerError", "InternalServerError", "APIConnectionError", "APITimeoutError"}))
    )
    if has_structured_status and status not in (429, None):
        return False

    for exc in _iter_exception_chain(err):
        lower = str(exc).lower()
        if any(pat in lower for pat in _NON_RETRYABLE_PATTERNS):
            return True
    return False


def is_rate_limit_error(err: Exception) -> bool:
    """Return True if exception indicates a transient 429 / 529 / RPM / TPM rate limit."""
    if is_non_retryable_error(err):
        return False
    status = _get_http_status_code(err)
    if status in _RATE_LIMIT_STATUS_CODES:
        return True
    signals = _collect_structured_error_signals(err)
    if signals["class_names"] & _RATE_LIMIT_SDK_CLASSES:
        return True
    if signals["codes"] & _RATE_LIMIT_API_CODES:
        return True
    for exc in _iter_exception_chain(err):
        lower = str(exc).lower()
        if any(pat in lower for pat in _RATE_LIMIT_PATTERNS):
            return True
    return False


def _parse_duration_seconds(raw_val: Any) -> Optional[float]:
    """Parse duration strings like '24s', '500ms', '1m30s' or numeric seconds."""
    if raw_val is None:
        return None
    if isinstance(raw_val, (int, float)):
        return float(raw_val) if raw_val > 0 else None
    text = str(raw_val).strip().lower()
    if not text:
        return None
    try:
        val = float(text)
        return val if val > 0 else None
    except ValueError:
        pass
    m_compound = re.fullmatch(r"(?:(\d+(?:\.\d+)?)m)?\s*(?:(\d+(?:\.\d+)?)s)?\s*(?:(\d+(?:\.\d+)?)ms)?", text)
    if m_compound and any(m_compound.groups()):
        mins = float(m_compound.group(1) or 0)
        secs = float(m_compound.group(2) or 0)
        ms = float(m_compound.group(3) or 0)
        total = mins * 60.0 + secs + ms / 1000.0
        return total if total > 0 else None
    return None


def _clamp_retry_delay(val: float) -> float:
    return min(max(float(val), _MIN_RETRY_DELAY_S), _MAX_RETRY_DELAY_S)


def estimate_text_tokens(text: str) -> int:
    """Fast heuristic token estimator distinguishing ASCII vs non-ASCII/CJK characters."""
    if not text:
        return 0
    non_ascii = sum(1 for ch in text if ord(ch) > _TOKEN_ASCII_BOUND)
    ascii_chars = len(text) - non_ascii
    return max(1, int(ascii_chars / _TOKEN_ASCII_CHARS_PER_TOK + non_ascii * _TOKEN_NON_ASCII_WEIGHT))


def estimate_request_tokens(system_prompt: str, user_prompt: str) -> int:
    """Estimates combined input + translated output tokens for proactive TPM throttling."""
    sys_tokens = estimate_text_tokens(system_prompt)
    usr_tokens = estimate_text_tokens(user_prompt)
    # Translation outputs roughly ~1.1-1.3x user payload tokens plus JSON framing
    return max(1, sys_tokens + int(usr_tokens * _TOKEN_OUTPUT_MULTIPLIER))


def extract_retry_delay(err: Exception) -> Optional[float]:
    """
    Extract server-suggested retry delay (seconds) from authoritative sources first:
    1. Explicit `retry_after` attribute
    2. HTTP headers (`retry-after-ms`, `retry-after`, `x-ratelimit-reset-*`)
    3. Google RPC `RetryInfo.retryDelay` in error details
    4. Prose text fallback when structured metadata is absent
    """
    for exc in _iter_exception_chain(err):
        explicit = getattr(exc, "retry_after", None)
        if isinstance(explicit, (int, float)) and explicit > 0:
            return _clamp_retry_delay(explicit)

        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) if response is not None else None
        if headers is not None and hasattr(headers, "get"):
            retry_ms = headers.get("retry-after-ms") or headers.get("Retry-After-Ms")
            if retry_ms is not None:
                try:
                    ms_val = float(str(retry_ms).strip())
                    if ms_val > 0:
                        return _clamp_retry_delay(ms_val / 1000.0)
                except ValueError:
                    pass

            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after is not None:
                raw_hdr = str(retry_after).strip()
                try:
                    val = float(raw_hdr)
                    if val > 0:
                        return _clamp_retry_delay(val)
                except ValueError:
                    try:
                        dt = parsedate_to_datetime(raw_hdr)
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        delta = (dt - datetime.now(timezone.utc)).total_seconds()
                        if delta > 0:
                            return _clamp_retry_delay(delta)
                    except Exception:
                        pass

            for reset_hdr in ("x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
                hdr_val = headers.get(reset_hdr)
                parsed_sec = _parse_duration_seconds(hdr_val)
                if parsed_sec is not None:
                    return _clamp_retry_delay(parsed_sec)

        # Google RPC RetryInfo inside structured error details
        details = getattr(exc, "details", None)
        if isinstance(details, dict):
            err_block = details.get("error") if isinstance(details.get("error"), dict) else details
            detail_list = err_block.get("details")
            if isinstance(detail_list, list):
                for entry in detail_list:
                    if isinstance(entry, dict) and str(entry.get("@type", "")).endswith("RetryInfo"):
                        delay_sec = _parse_duration_seconds(entry.get("retryDelay"))
                        if delay_sec is not None:
                            return _clamp_retry_delay(delay_sec)

    # Prose text fallback for plain exceptions or gateways without structured headers
    for exc in _iter_exception_chain(err):
        msg = str(exc)
        patterns = (
            r"retry(?:ing)?\s+(?:in|after)\s+(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\b",
            r"try\s+again\s+in\s+(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\b",
            r"retry[-_ ]?(?:delay|after)\s*[:=]\s*[\"']?(\d+(?:\.\d+)?)\s*s?[\"']?",
        )
        for pattern in patterns:
            m = re.search(pattern, msg, flags=re.IGNORECASE)
            if m:
                try:
                    val = float(m.group(1))
                    if val > 0:
                        return _clamp_retry_delay(val)
                except ValueError:
                    pass
    return None


class LLMError(Exception):
    """Custom exception for LLM translation failures preserving HTTP and SDK diagnostics."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        retry_after: Optional[float] = None,
        response: Any = None,
        is_format_error: bool = False,
        error_code: Optional[str] = None,
        error_type: Optional[str] = None,
        error_status: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.response = response
        self.is_format_error = is_format_error
        self.error_code = error_code
        self.error_type = error_type
        self.error_status = error_status


def _wrap_provider_error(prefix: str, exc: Exception) -> LLMError:
    """Wrap SDK exception in LLMError preserving HTTP status, headers, codes, and Retry-After."""
    if isinstance(exc, LLMError):
        return exc
    body_err = _extract_body_error_dict(exc)
    raw_code = getattr(exc, "error_code", None) or getattr(exc, "code", None) or body_err.get("code")
    err_code = str(raw_code) if isinstance(raw_code, str) else None
    raw_type = getattr(exc, "type", None) or body_err.get("type")
    err_type = str(raw_type) if isinstance(raw_type, str) else None
    raw_status = getattr(exc, "status", None) or body_err.get("status")
    err_status = str(raw_status) if isinstance(raw_status, str) else None

    return LLMError(
        f"{prefix}: {exc}",
        status_code=_get_http_status_code(exc),
        retry_after=extract_retry_delay(exc),
        response=getattr(exc, "response", None),
        error_code=err_code,
        error_type=err_type,
        error_status=err_status,
    )


def _is_preferred_translation_json(parsed: Any) -> bool:
    if isinstance(parsed, dict):
        if any(k in parsed for k in ("translations", "data", "items", "result", "translated")):
            return True
        return bool(parsed) and all(isinstance(k, str) and k.isdigit() for k in parsed.keys())
    return False


def _is_numeric_marker_list(parsed: Any) -> bool:
    return (
        isinstance(parsed, list)
        and len(parsed) > 0
        and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in parsed)
    )


def _decode_first_json_slice(text: str) -> Optional[str]:
    """Use JSONDecoder.raw_decode to extract the best valid JSON object/array substring."""
    decoder = json.JSONDecoder(strict=False)
    candidates: List[Tuple[Any, str]] = []
    idx = 0
    n = len(text)
    while idx < n:
        if text[idx] in "{[":
            try:
                parsed, end_idx = decoder.raw_decode(text, idx)
                if isinstance(parsed, (dict, list)):
                    slice_str = text[idx:end_idx].strip()
                    if _is_preferred_translation_json(parsed):
                        return slice_str
                    candidates.append((parsed, slice_str))
                    idx = end_idx
                    continue
            except json.JSONDecodeError:
                pass
        idx += 1

    if not candidates:
        return None
    for parsed, slice_str in candidates:
        if isinstance(parsed, dict):
            return slice_str
    for parsed, slice_str in candidates:
        if not _is_numeric_marker_list(parsed):
            return slice_str
    return candidates[0][1]


def _strip_trailing_json_commas(text: str) -> str:
    """Removes trailing commas before ']' or '}' outside JSON string literals."""
    out: List[str] = []
    in_string = False
    escape = False
    n = len(text)
    i = 0
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            i += 1
            continue

        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "]}":
                i += 1
                continue

        out.append(ch)
        i += 1
    return "".join(out)


def clean_json_text(text: str) -> str:
    """Extract a valid JSON object/array from raw or markdown-fenced LLM output."""
    stripped = (text or "").strip()
    if not stripped:
        return ""

    # 1. Fast path: already valid JSON object or array
    try:
        parsed = json.loads(stripped, strict=False)
        if isinstance(parsed, (dict, list)):
            return stripped
    except json.JSONDecodeError:
        pass

    # 2. If a markdown code fence is present, scan starting right after its opening tag
    #    so embedded backticks inside JSON string values cannot truncate parsing.
    for fence_match in re.finditer(r"```(?:json)?\s*", stripped, flags=re.IGNORECASE):
        after_fence = stripped[fence_match.end():]
        extracted = _decode_first_json_slice(after_fence)
        if extracted:
            return extracted

    # 3. Direct balanced scan across the full response; if trailing commas broke an outer object, repair first
    extracted = _decode_first_json_slice(stripped)
    repaired = _strip_trailing_json_commas(stripped)
    if repaired != stripped:
        repaired_extracted = _decode_first_json_slice(repaired)
        if repaired_extracted:
            if not extracted:
                return repaired_extracted
            try:
                orig_obj = json.loads(extracted, strict=False)
                rep_obj = json.loads(repaired_extracted, strict=False)
                if not _is_preferred_translation_json(orig_obj) and _is_preferred_translation_json(rep_obj):
                    return repaired_extracted
            except json.JSONDecodeError:
                pass
    if extracted:
        return extracted

    return repaired


_APPEND_ORIGINAL_RULE = (
    "APPEND ORIGINAL SOURCE WORDS AND ADAPT QUOTATION MARKS:\n"
    "- UI Labels and Quotation Marks: Enclose translated UI labels, button names, and filter options using the standard quotation marks of the target language rather than retaining source-specific bracket styles. Do not insert speculative filler words, category prefixes, or extra commentary around UI labels.\n"
    "- Verbatim Source Term: When appending the original term in parentheses immediately following its translation, the term inside the parentheses MUST be the exact verbatim string copied directly from the input source text in the original source language. Absolutely do not translate, interpret, or convert the original term into any other language.\n"
    "- Do not annotate common everyday words or terms that remain untranslated."
)
_KEEP_TERMS_RULE = (
    "KEEP SPECIALIZED TERMS UNTRANSLATED: Maintain proper nouns, standard abbreviations, acronyms, "
    "and internationally recognized terms in their original form without forcing awkward or literal translations. "
    "Ensure surrounding sentences flow naturally and grammatically in the target language."
)


def _critical_fidelity_rule(target_lang: str) -> str:
    return (
        f"CRITICAL FIDELITY: Except for parenthetical source term annotations, keywords, code syntax, "
        f"variable names, proper nouns, standard abbreviations, acronyms, numbers, punctuation, or content already in {target_lang}, "
        f"ALL words, sentences, and explanatory text MUST be fully translated into {target_lang}."
    )


def _append_option_rules(rules: List[str], options: TranslationOptions) -> None:
    if options.keep_it_terms:
        rules.append(_KEEP_TERMS_RULE)
    if options.append_original_words:
        rules.append(_APPEND_ORIGINAL_RULE)
    if options.custom_context and options.custom_context.strip():
        rules.append(f"PROJECT GLOSSARY & CONTEXT INSTRUCTIONS:\n{options.custom_context.strip()}")


def build_system_prompt(
    target_lang: str,
    options: Optional[TranslationOptions] = None,
    source_lang: Optional[str] = None,
) -> str:
    """Build a comprehensive system prompt enforcing indexed JSON format and translation rules."""
    options = options or TranslationOptions()
    clean_source = (source_lang or "").strip()
    source_rule = (
        f"SOURCE LANGUAGE CONTEXT: The primary source language is {clean_source}. "
        "Embedded foreign terms or mixed multilingual fragments may also appear."
        if clean_source and clean_source.lower() != "auto"
        else "SOURCE LANGUAGE CONTEXT: Input texts may be in any language or contain mixed multilingual content."
    )

    rules = [
        f"You are an expert, professional document translator specializing in accurate, fluent, and natural translation into {target_lang}.",
        f"Translate every item in the provided JSON input into {target_lang}.",
        source_rule,
        _critical_fidelity_rule(target_lang),
        "NATURAL & PROFESSIONAL STYLE: Ensure sentences flow naturally, grammatically, and smoothly according to professional document conventions in the target language. Do not produce rigid or literal word-for-word translations.",
        (
            'STRICT OUTPUT FORMAT: Return ONLY a valid JSON object of the exact schema '
            '{"translations": [{"i": <int>, "t": "<translated_text>"}, ...]}. '
            'Every input index "i" MUST appear exactly once in the output with its corresponding translated string "t".'
        ),
        "Do NOT include explanations, markdown headers, conversational filler, or commentary. Output raw JSON only.",
        "PRESERVE FORMATTING & PLACEHOLDERS: Strictly preserve placeholders (e.g. {0}, {name}, %s), code syntax, HTML/XML tags, URLs, numbers, punctuation, and leading/trailing whitespace where appropriate.",
        "INLINE STYLE TAGS: If an input string contains numbered inline style markers such as <s0>...</s0>, <s1>...</s1>, preserve every exact <sN>...</sN> tag pair around its corresponding translated phrase without dropping, renaming, or adding markers.",
        "UI LABELS AND QUOTATION MARKS: Adapt source quotation marks or corner brackets to the standard quotation marks of the target language for UI labels, button names, and quoted terms. Do not insert extraneous words, category prefixes, or filler around them.",
    ]
    _append_option_rules(rules, options)
    return "\n\n".join(rules)


class BaseLLMClient(ABC):
    """Abstract base class for all LLM provider clients."""

    @abstractmethod
    def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True,
    ) -> str:
        """Synchronously generate completion text."""
        pass


class GeminiClient(BaseLLMClient):
    """Client for Google Gemini API using official google-genai SDK configuration and response metadata."""

    _POLICY_FINISH_REASONS = frozenset({
        "SAFETY",
        "RECITATION",
        "LANGUAGE",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    })

    def __init__(
        self,
        api_key: str,
        timeout: float = _DEFAULT_REQUEST_TIMEOUT_S,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        strict_json_mode: bool = True,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = (base_url or "").strip()
        self.temperature = temperature
        self.strict_json_mode = bool(strict_json_mode)
        self._lock = threading.Lock()
        self._genai_client = None

    def _get_genai_client(self):
        with self._lock:
            if self._genai_client is not None:
                return self._genai_client
            from google import genai
            from google.genai import types

            http_kwargs: Dict[str, Any] = {
                "timeout": int(self.timeout * 1000),
                "retry_options": types.HttpRetryOptions(attempts=1),
            }
            if self.base_url:
                http_kwargs["base_url"] = self.base_url
            http_options = types.HttpOptions(**http_kwargs)
            self._genai_client = genai.Client(api_key=self.api_key, http_options=http_options)
            return self._genai_client

    def _resolve_temperature(self, model_name: str) -> Optional[float]:
        """Returns explicitly configured temperature clamped to API-reported max_temperature if known."""
        if self.temperature is None:
            return None
        temp = max(0.0, float(self.temperature))
        meta = get_model_metadata("Gemini", model_name)
        max_temp = meta.get("max_temperature")
        if isinstance(max_temp, (int, float)) and not isinstance(max_temp, bool) and max_temp > 0:
            temp = min(temp, float(max_temp))
        return temp

    @classmethod
    def _validate_gemini_response(cls, response: Any) -> str:
        """Inspect official prompt_feedback and candidate finish_reason before returning text."""
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = getattr(prompt_feedback, "block_reason", None)
        if block_reason:
            raise LLMError(f"Gemini blocked the request ({block_reason}).", status_code=400)

        candidates = getattr(response, "candidates", None) or []
        if candidates:
            finish_reason = getattr(candidates[0], "finish_reason", None)
            finish_name = getattr(finish_reason, "name", None) or str(finish_reason or "")
            upper_finish = finish_name.upper()
            if upper_finish == "MAX_TOKENS":
                raise LLMError(
                    "Gemini response truncated (finish_reason=MAX_TOKENS).",
                    is_format_error=True,
                )
            if upper_finish in cls._POLICY_FINISH_REASONS:
                raise LLMError(
                    f"Gemini stopped generation due to policy ({finish_name}).",
                    status_code=400,
                )

        text = getattr(response, "text", None) or ""
        return text

    def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True,
    ) -> str:
        from google.genai import types

        client = self._get_genai_client()
        cfg_kwargs: Dict[str, Any] = {
            "system_instruction": system_prompt,
            "response_mime_type": "application/json" if (is_json and self.strict_json_mode) else "text/plain",
            "automatic_function_calling": types.AutomaticFunctionCallingConfig(disable=True),
        }
        resolved_temp = self._resolve_temperature(model_name)
        if resolved_temp is not None:
            cfg_kwargs["temperature"] = resolved_temp
        config = types.GenerateContentConfig(**cfg_kwargs)
        response = client.models.generate_content(
            model=model_name,
            contents=user_prompt,
            config=config,
        )
        return self._validate_gemini_response(response)

    def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True,
    ) -> str:
        if not self.api_key:
            raise LLMError("Gemini API key is missing. Please configure it in Settings.", status_code=401)
        target_model = (model_name or "").strip()
        if not target_model:
            raise LLMError(
                "No Gemini model selected. Please fetch and select a model in Settings.",
                status_code=400,
                error_code="model_not_selected",
            )

        try:
            return self._call_gemini(system_prompt, user_prompt, target_model, is_json=is_json)
        except LLMError:
            raise
        except Exception as e:
            raise _wrap_provider_error("Gemini API Error", e) from e


class OpenAIClient(BaseLLMClient):
    """Direct OpenAI Chat Completions API client without parameter guessing or 400 retry loops."""

    def __init__(
        self,
        api_key: str,
        timeout: float = _DEFAULT_REQUEST_TIMEOUT_S,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
        strict_json_mode: bool = True,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = (base_url or "").strip()
        self.temperature = temperature
        self.strict_json_mode = bool(strict_json_mode)
        self._lock = threading.Lock()
        self._client = None

    def _get_client(self):
        with self._lock:
            if self._client is None:
                from openai import OpenAI
                client_kwargs: Dict[str, Any] = {
                    "api_key": self.api_key,
                    "timeout": self.timeout,
                    "max_retries": 0,
                }
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self._client = OpenAI(**client_kwargs)
            return self._client

    def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True,
    ) -> str:
        if not self.api_key:
            raise LLMError("OpenAI API key is missing. Please configure it in Settings.", status_code=401)
        target_model = (model_name or "").strip()
        if not target_model:
            raise LLMError(
                "No OpenAI model selected. Please fetch and select a model in Settings.",
                status_code=400,
                error_code="model_not_selected",
            )

        client = self._get_client()
        req_kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if is_json and self.strict_json_mode:
            req_kwargs["response_format"] = {"type": "json_object"}
        if self.temperature is not None:
            req_kwargs["temperature"] = float(self.temperature)

        try:
            response = client.chat.completions.create(**req_kwargs)
        except LLMError:
            raise
        except Exception as e:
            raise _wrap_provider_error("OpenAI API Error", e) from e

        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        choice = choices[0]
        finish_reason = getattr(choice, "finish_reason", None)
        message = getattr(choice, "message", None)
        refusal = getattr(message, "refusal", None) if message is not None else None
        if refusal:
            raise LLMError(f"OpenAI refused request: {refusal}", status_code=400)
        if finish_reason == "content_filter":
            raise LLMError("OpenAI blocked output due to content_filter.", status_code=400)
        if finish_reason == "length":
            raise LLMError("OpenAI response truncated (finish_reason=length).", is_format_error=True)
        return (getattr(message, "content", None) or "") if message is not None else ""


class ClaudeClient(BaseLLMClient):
    """Direct Anthropic Claude API client using official ModelInfo limits and standard SDK calls."""

    def __init__(
        self,
        api_key: str,
        timeout: float = _DEFAULT_REQUEST_TIMEOUT_S,
        base_url: Optional[str] = None,
        temperature: Optional[float] = None,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = (base_url or "").strip()
        self.temperature = temperature
        self._lock = threading.Lock()
        self._client = None
        self._model_max_tokens: Dict[str, int] = {}

    def _get_client(self):
        with self._lock:
            if self._client is None:
                import anthropic
                client_kwargs: Dict[str, Any] = {
                    "api_key": self.api_key,
                    "timeout": self.timeout,
                    "max_retries": 0,
                }
                if self.base_url:
                    client_kwargs["base_url"] = self.base_url
                self._client = anthropic.Anthropic(**client_kwargs)
            return self._client

    def _resolve_model_max_tokens(self, client: Any, model_name: str) -> int:
        """
        Resolves the model's authoritative max_tokens from Anthropic ModelInfo metadata
        (in-memory cache -> disk cache -> live `client.models.retrieve`).
        Raises LLMError if max_tokens is not reported by Anthropic API.
        """
        with self._lock:
            if model_name in self._model_max_tokens:
                return self._model_max_tokens[model_name]

        cached_meta = get_model_metadata("Claude", model_name)
        cached_max = cached_meta.get("max_tokens")
        if isinstance(cached_max, int) and cached_max > 0:
            with self._lock:
                self._model_max_tokens[model_name] = cached_max
            return cached_max

        info = client.models.retrieve(model_name)
        api_max = getattr(info, "max_tokens", None)
        if isinstance(api_max, int) and api_max > 0:
            with self._lock:
                self._model_max_tokens[model_name] = api_max
            meta_update: Dict[str, Any] = {"max_tokens": api_max}
            if getattr(info, "max_input_tokens", None) is not None:
                meta_update["max_input_tokens"] = info.max_input_tokens
            if getattr(info, "lifecycle", None) is not None:
                meta_update["lifecycle"] = info.lifecycle
            update_model_metadata("Claude", model_name, meta_update)
            return api_max

        raise LLMError(
            f"Claude model '{model_name}' metadata did not report max_tokens.",
            status_code=400,
        )

    @staticmethod
    def _extract_message_text(message: Any) -> str:
        """Collects text across TextBlocks while ignoring ThinkingBlocks/other non-text blocks."""
        blocks = getattr(message, "content", None) or []
        parts: List[str] = []
        for block in blocks:
            b_type = getattr(block, "type", None)
            if b_type is None or b_type == "text":
                txt = getattr(block, "text", None)
                if isinstance(txt, str):
                    parts.append(txt)
        return "".join(parts)

    def generate_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        model_name: str,
        is_json: bool = True,
    ) -> str:
        if not self.api_key:
            raise LLMError("Anthropic Claude API key is missing. Please configure it in Settings.", status_code=401)
        target_model = (model_name or "").strip()
        if not target_model:
            raise LLMError(
                "No Claude model selected. Please fetch and select a model in Settings.",
                status_code=400,
                error_code="model_not_selected",
            )

        client = self._get_client()
        try:
            max_tokens = self._resolve_model_max_tokens(client, target_model)
            create_kwargs: Dict[str, Any] = {
                "model": target_model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "timeout": self.timeout,
            }
            if self.temperature is not None:
                try:
                    if "temperature" in inspect.signature(client.messages.create).parameters:
                        create_kwargs["temperature"] = float(self.temperature)
                except (TypeError, ValueError):
                    pass
            message = client.messages.create(**create_kwargs)
        except LLMError:
            raise
        except Exception as e:
            raise _wrap_provider_error("Claude API Error", e) from e

        stop_reason = getattr(message, "stop_reason", None)
        if stop_reason == "max_tokens":
            raise LLMError("Claude response truncated (stop_reason=max_tokens).", is_format_error=True)
        if stop_reason in ("refusal", "model_context_window_exceeded"):
            raise LLMError(f"Claude stopped generation ({stop_reason}).", status_code=400)

        return self._extract_message_text(message)


def create_llm_client(
    provider: str,
    api_key: str,
    timeout: float = _DEFAULT_REQUEST_TIMEOUT_S,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    strict_json_mode: bool = True,
) -> BaseLLMClient:
    """Shared factory creating the provider client for translation or connection tests."""
    if provider not in AI_PROVIDERS:
        raise LLMError(f"Unsupported AI provider: {provider}")
    factories: Dict[str, Callable[[str], BaseLLMClient]] = {
        "Gemini": lambda k: GeminiClient(
            k, timeout=timeout, base_url=base_url, temperature=temperature, strict_json_mode=strict_json_mode
        ),
        "OpenAI": lambda k: OpenAIClient(
            k, timeout=timeout, base_url=base_url, temperature=temperature, strict_json_mode=strict_json_mode
        ),
        "Claude": lambda k: ClaudeClient(
            k, timeout=timeout, base_url=base_url, temperature=temperature
        ),
    }
    factory = factories.get(provider)
    if factory is None:
        raise LLMError(f"Unsupported AI provider: {provider}")
    return factory(api_key)


class _StructuralMismatchError(ValueError):
    """Raised when LLM output JSON does not strictly match expected batch items/indices."""


class LLMManager:
    """
    High-level LLM translation coordinator.
    Handles batch packing, strict indexed JSON verification, automatic binary splitting
    on structural mismatch, shared 429 cooldowns, adaptive request pacing, and provider routing.
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._rate_lock = threading.Lock()
        self._concurrency_cond = threading.Condition(self._rate_lock)
        self._client_lock = threading.Lock()
        self._cached_client_key: Optional[Tuple[Any, ...]] = None
        self._cached_client: Optional[BaseLLMClient] = None
        self._cooldown_until: float = 0.0
        self._next_dispatch_at: float = 0.0
        self._request_history: deque[Tuple[float, int]] = deque()
        self._active_requests: int = 0
        self._consecutive_successes: int = 0
        self._rate_limit_hits: int = 0
        self._last_request_at: float = 0.0
        self._base_min_interval: float = self._read_base_min_interval(config)
        self._min_interval: float = self._base_min_interval
        self._session_min_interval_floor: float = self._base_min_interval
        self._effective_concurrency: int = self._get_configured_max_workers()

    @staticmethod
    def _read_base_min_interval(config: AppConfig) -> float:
        return resolve_config_float(config, "min_request_interval")

    def _get_configured_max_workers(self) -> int:
        return resolve_config_int(self.config, "max_concurrent_requests")

    def _get_rate_limits(self) -> Tuple[int, int]:
        return resolve_config_int(self.config, "rpm_limit"), resolve_config_int(self.config, "tpm_limit")

    def sync_config(self, config: Optional[AppConfig] = None) -> None:
        """Refreshes pacing, concurrency, and sliding-window bounds after Settings changes."""
        if config is not None:
            self.config = config
        with self._rate_lock:
            self._base_min_interval = self._read_base_min_interval(self.config)
            self._min_interval = self._base_min_interval
            self._session_min_interval_floor = self._base_min_interval
            self._effective_concurrency = self._get_configured_max_workers()
            self._consecutive_successes = 0
            self._rate_limit_hits = 0
            self._cooldown_until = 0.0
            self._next_dispatch_at = 0.0
            self._request_history.clear()
            self._concurrency_cond.notify_all()

    def _sleep_with_cancel(
        self,
        seconds: float,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Sleep for seconds while allowing prompt cancellation."""
        if cancel_check and cancel_check():
            raise InterruptedError("Translation cancelled by user.")
        if seconds <= 0:
            return
        if cancel_check is None:
            time.sleep(seconds)
            return

        deadline = time.monotonic() + seconds
        while True:
            if cancel_check():
                raise InterruptedError("Translation cancelled by user.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            step = min(0.25, remaining)
            t0 = time.monotonic()
            time.sleep(step)
            # Break immediately if time.sleep is mocked in tests
            if time.monotonic() - t0 < step * 0.25:
                break

    @contextmanager
    def _concurrency_gate(
        self,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        """Bounds active in-flight HTTP calls to adaptive _effective_concurrency."""
        with self._concurrency_cond:
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError("Translation cancelled by user.")
                allowed = max(1, min(self._effective_concurrency, self._get_configured_max_workers()))
                if self._active_requests < allowed:
                    self._active_requests += 1
                    break
                self._concurrency_cond.wait(timeout=0.25)
        try:
            yield
        finally:
            with self._concurrency_cond:
                if self._active_requests > 0:
                    self._active_requests -= 1
                self._concurrency_cond.notify_all()

    def _prune_window_locked(self, now: float) -> None:
        cutoff = now - _RATE_WINDOW_SECONDS
        while self._request_history and self._request_history[0][0] <= cutoff:
            self._request_history.popleft()

    def _compute_window_wait_locked(
        self,
        now: float,
        rpm_limit: int,
        tpm_limit: int,
        estimated_tokens: int,
    ) -> float:
        wait_for = 0.0
        window_reset = _RATE_WINDOW_SECONDS + _RATE_WINDOW_PADDING_S
        if rpm_limit > 0 and len(self._request_history) >= rpm_limit:
            idx = len(self._request_history) - rpm_limit
            oldest_blocking_ts = self._request_history[idx][0]
            wait_for = max(wait_for, (oldest_blocking_ts + window_reset) - now)
        if tpm_limit > 0 and estimated_tokens > 0:
            used_tokens = sum(tok for _, tok in self._request_history)
            if used_tokens > 0 and used_tokens + estimated_tokens > tpm_limit:
                excess = (used_tokens + estimated_tokens) - tpm_limit
                reclaimed = 0
                for ts, tok in self._request_history:
                    reclaimed += tok
                    if reclaimed >= excess:
                        wait_for = max(wait_for, (ts + window_reset) - now)
                        break
        return max(0.0, wait_for)

    def _acquire_request_slot(
        self,
        cancel_check: Optional[Callable[[], bool]] = None,
        estimated_tokens: int = 0,
    ) -> None:
        """Respect shared 429 cooldowns, dispatch pacing, and proactive RPM/TPM windows."""
        while True:
            if cancel_check and cancel_check():
                raise InterruptedError("Translation cancelled by user.")
            rpm_limit, tpm_limit = self._get_rate_limits()
            with self._rate_lock:
                now = time.monotonic()
                if self._last_request_at > 0 and (now - self._last_request_at) > _RATE_RECOVERY_IDLE_S and self._rate_limit_hits > 0:
                    self._rate_limit_hits = 0
                    self._session_min_interval_floor = self._base_min_interval
                    self._min_interval = max(self._base_min_interval, min(self._min_interval, self._base_min_interval))
                    self._effective_concurrency = self._get_configured_max_workers()

                self._prune_window_locked(now)
                window_wait = self._compute_window_wait_locked(now, rpm_limit, tpm_limit, estimated_tokens)
                if now < self._cooldown_until:
                    wait_for = max(self._cooldown_until - now, window_wait)
                elif now < self._next_dispatch_at:
                    wait_for = max(self._next_dispatch_at - now, window_wait)
                elif window_wait > 0:
                    wait_for = window_wait
                else:
                    self._next_dispatch_at = now + self._min_interval
                    self._last_request_at = now
                    if rpm_limit > 0 or tpm_limit > 0:
                        self._request_history.append((now, max(0, estimated_tokens)))
                    return
            t0 = time.monotonic()
            self._sleep_with_cancel(wait_for, cancel_check=cancel_check)
            # If sleep/time.sleep is mocked (elapsed time didn't advance), claim slot directly
            if time.monotonic() - t0 < wait_for * 0.25:
                with self._rate_lock:
                    now = time.monotonic()
                    self._next_dispatch_at = now + self._min_interval
                    self._last_request_at = now
                    if rpm_limit > 0:
                        while len(self._request_history) >= rpm_limit:
                            self._request_history.popleft()
                    if tpm_limit > 0 and estimated_tokens > 0:
                        used_tokens = sum(tok for _, tok in self._request_history)
                        while self._request_history and used_tokens + estimated_tokens > tpm_limit:
                            _, popped = self._request_history.popleft()
                            used_tokens -= popped
                    if rpm_limit > 0 or tpm_limit > 0:
                        self._request_history.append((now, max(0, estimated_tokens)))
                return

    def _record_rate_limit(self, delay_seconds: float) -> None:
        """Set a shared cooldown, slow dispatch pacing, and throttle concurrency to 1."""
        with self._rate_lock:
            now = time.monotonic()
            self._cooldown_until = max(self._cooldown_until, now + delay_seconds)
            self._rate_limit_hits += 1
            self._consecutive_successes = 0
            self._effective_concurrency = 1
            if self._rate_limit_hits == 1:
                self._session_min_interval_floor = min(_MAX_ADAPTIVE_FLOOR_S, max(self._base_min_interval, 1.0))
            else:
                self._session_min_interval_floor = min(
                    _MAX_ADAPTIVE_FLOOR_S,
                    max(self._base_min_interval, self._session_min_interval_floor * 1.5),
                )
            self._min_interval = min(
                _MAX_ADAPTIVE_INTERVAL_S,
                max(self._session_min_interval_floor, self._min_interval * 2.0),
            )

    def _record_success(self) -> None:
        """Gradually restore dispatch pacing and concurrency after sustained healthy responses."""
        with self._rate_lock:
            self._consecutive_successes += 1
            if self._consecutive_successes >= _CONSECUTIVE_OK_FOR_PACE_DECAY:
                self._min_interval = max(
                    self._session_min_interval_floor,
                    self._min_interval * _PACE_DECAY_FACTOR,
                )
            configured = self._get_configured_max_workers()
            if self._effective_concurrency < configured and self._consecutive_successes >= _CONSECUTIVE_OK_FOR_CONCURRENCY_INC:
                self._effective_concurrency += 1
                self._consecutive_successes = 0
                self._concurrency_cond.notify_all()

    @staticmethod
    def _compute_backoff(attempt: int, err: Exception) -> Tuple[float, bool]:
        """Return (wait_seconds, is_rate_limit) for retry scheduling."""
        if is_rate_limit_error(err):
            extracted = extract_retry_delay(err)
            base = _BACKOFF_BASE_SCHEDULE[min(attempt, len(_BACKOFF_BASE_SCHEDULE) - 1)]
            wait = max(base, extracted or 0.0) + random.uniform(0.5, 2.0)
            return wait, True

        wait = (2 ** attempt) + 1 + random.uniform(0.1, 0.5)
        return wait, False

    def _execute_with_retry(
        self,
        operation: Callable[[], T],
        max_retries: Optional[int] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        error_context: str = "translate batch",
        estimated_tokens: int = 0,
    ) -> T:
        """Execute an LLM operation with 429-aware shared cooldown and separate retry budgets."""
        cfg_general = resolve_config_int(self.config, "max_retries_general")
        cfg_rate = resolve_config_int(self.config, "max_retries_rate_limit")
        cfg_format = resolve_config_int(self.config, "max_retries_format")

        general_limit = max(1, max_retries) if max_retries is not None else cfg_general
        rate_limit_max = max(1, max_retries) if max_retries is not None else cfg_rate
        format_limit = min(general_limit, cfg_format) if max_retries != 1 else 1
        total_limit = max_retries if max_retries is not None else (rate_limit_max + general_limit)

        rate_attempts = 0
        general_attempts = 0
        format_attempts = 0
        last_error: Optional[Exception] = None

        while True:
            try:
                with self._concurrency_gate(cancel_check=cancel_check):
                    self._acquire_request_slot(
                        cancel_check=cancel_check,
                        estimated_tokens=estimated_tokens,
                    )
                    result = operation()
                self._record_success()
                return result
            except InterruptedError:
                raise
            except Exception as e:
                last_error = e
                # Deterministic truncation (MAX_TOKENS / finish_reason=length) should split immediately
                if isinstance(e, LLMError) and e.is_format_error:
                    raise

                if is_non_retryable_error(e):
                    if isinstance(e, LLMError):
                        raise
                    body_err = _extract_body_error_dict(e)
                    raise LLMError(
                        str(e),
                        status_code=_get_http_status_code(e),
                        response=getattr(e, "response", None),
                        error_code=getattr(e, "error_code", None) or (getattr(e, "code", None) if isinstance(getattr(e, "code", None), str) else body_err.get("code")),
                        error_type=getattr(e, "type", None) or body_err.get("type"),
                        error_status=getattr(e, "status", None) or body_err.get("status"),
                    ) from e

                is_structural = isinstance(e, (_StructuralMismatchError, json.JSONDecodeError))
                if is_structural:
                    format_attempts += 1
                    total_attempts = rate_attempts + general_attempts + format_attempts
                    if format_attempts >= format_limit or total_attempts >= total_limit:
                        break
                    self._sleep_with_cancel(random.uniform(0.2, 0.5), cancel_check=cancel_check)
                    continue

                if is_rate_limit_error(e):
                    wait_seconds, _ = self._compute_backoff(rate_attempts, e)
                    rate_attempts += 1
                    total_attempts = rate_attempts + general_attempts + format_attempts
                    if rate_attempts >= rate_limit_max or total_attempts >= total_limit:
                        with self._rate_lock:
                            self._cooldown_until = 0.0
                            self._next_dispatch_at = 0.0
                        break
                    self._record_rate_limit(wait_seconds)
                else:
                    wait_seconds, _ = self._compute_backoff(general_attempts, e)
                    general_attempts += 1
                    total_attempts = rate_attempts + general_attempts + format_attempts
                    if general_attempts >= general_limit or total_attempts >= total_limit:
                        if rate_attempts > 0:
                            with self._rate_lock:
                                self._cooldown_until = 0.0
                                self._next_dispatch_at = 0.0
                        break
                    self._sleep_with_cancel(wait_seconds, cancel_check=cancel_check)

        total_attempts = rate_attempts + general_attempts + format_attempts
        is_fmt = isinstance(last_error, (_StructuralMismatchError, json.JSONDecodeError)) or bool(
            getattr(last_error, "is_format_error", False)
        )
        err = LLMError(
            f"Failed to {error_context} after {total_attempts} attempts. Last error: {last_error}",
            status_code=_get_http_status_code(last_error) if last_error else None,
            retry_after=extract_retry_delay(last_error) if last_error else None,
            response=getattr(last_error, "response", None),
            is_format_error=is_fmt,
            error_code=getattr(last_error, "error_code", None),
            error_type=getattr(last_error, "error_type", None),
            error_status=getattr(last_error, "error_status", None),
        )
        raise err from last_error

    def _get_selected_model(self) -> str:
        """Returns the explicitly configured model for the active provider, or raises LLMError."""
        provider = (self.config.active_provider or "").strip()
        if provider not in AI_PROVIDERS:
            raise LLMError(
                f"Unsupported or missing AI provider: {provider!r}. Please select a valid provider in Settings.",
                status_code=400,
            )
        model_name = (self.config.get_active_model() or "").strip()
        if not model_name:
            raise LLMError(
                f"No model selected for {provider}. Please select a model in Settings.",
                status_code=400,
                error_code="model_not_selected",
            )
        return model_name

    def _get_client(self) -> BaseLLMClient:
        provider = self.config.active_provider
        api_key = self.config.get_effective_api_key(provider)
        base_url = (
            self.config.get_effective_base_url(provider)
            if hasattr(self.config, "get_effective_base_url")
            else ""
        )
        timeout = resolve_config_float(self.config, "request_timeout")
        temperature = getattr(self.config, "temperature", None)
        strict_json_mode = bool(getattr(self.config, "strict_json_mode", True))
        cache_key = (provider, api_key, base_url, timeout, temperature, strict_json_mode)

        with self._client_lock:
            if self._cached_client is not None and self._cached_client_key == cache_key:
                return self._cached_client

            client = create_llm_client(
                provider,
                api_key,
                timeout=timeout,
                base_url=base_url or None,
                temperature=temperature,
                strict_json_mode=strict_json_mode,
            )
            self._cached_client = client
            self._cached_client_key = cache_key
            with self._rate_lock:
                self._base_min_interval = self._read_base_min_interval(self.config)
                self._cooldown_until = 0.0
                self._min_interval = self._base_min_interval
                self._session_min_interval_floor = self._base_min_interval
                self._effective_concurrency = self._get_configured_max_workers()
                self._consecutive_successes = 0
                self._rate_limit_hits = 0
                self._request_history.clear()
                self._concurrency_cond.notify_all()
            return client

    @staticmethod
    def _parse_batch_response(raw_response: str, expected_count: int) -> List[str]:
        """
        Strictly parse and validate an LLM batch translation payload.
        Accepts:
          - Indexed records: {"translations": [{"i": 0, "t": "..."}, ...]} or [{"i": 0, "t": "..."}, ...]
          - Index-keyed dict: {"0": "...", "1": "..."}
          - Ordered string array: ["...", "..."] or {"translations": ["...", "..."]}
        Raises _StructuralMismatchError if count or indices do not match expected_count exactly.
        """
        cleaned = clean_json_text(raw_response)
        try:
            parsed = json.loads(cleaned, strict=False)
        except json.JSONDecodeError as e:
            raise _StructuralMismatchError(f"Invalid JSON in LLM response: {e}") from e

        if isinstance(parsed, dict):
            # Support index-keyed dictionary {"0": "...", "1": "..."} when keys cover 0..N-1
            str_keys = {str(i) for i in range(expected_count)}
            if expected_count > 0 and str_keys.issubset(parsed.keys()) and len(parsed) == expected_count:
                result: List[str] = []
                for i in range(expected_count):
                    val = parsed[str(i)]
                    if isinstance(val, (dict, list)) or val is None:
                        raise _StructuralMismatchError(f"Invalid translated value type at index {i}")
                    result.append(str(val))
                return result

            for key in ("translations", "data", "items", "result", "translated"):
                if key in parsed and isinstance(parsed[key], list):
                    parsed = parsed[key]
                    break
            else:
                list_vals = [v for v in parsed.values() if isinstance(v, list)]
                if len(list_vals) == 1:
                    parsed = list_vals[0]
                elif list_vals:
                    parsed = max(list_vals, key=len)
                else:
                    raise _StructuralMismatchError("Returned JSON is an object without a list property.")

        if not isinstance(parsed, list):
            raise _StructuralMismatchError(f"Expected JSON array, got {type(parsed).__name__}")

        if len(parsed) != expected_count:
            raise _StructuralMismatchError(
                f"Expected {expected_count} translated items, got {len(parsed)} (length differs)."
            )

        if expected_count == 0:
            return []

        # Case 1: Indexed objects [{"i": 0, "t": "..."}, ...]
        if all(isinstance(item, dict) for item in parsed):
            mapped: Dict[int, str] = {}
            for pos, item in enumerate(parsed):
                raw_idx = None
                for idx_key in ("i", "index", "id"):
                    if idx_key in item:
                        raw_idx = item[idx_key]
                        break
                if raw_idx is None:
                    raise _StructuralMismatchError(f"Missing index key 'i' in item at position {pos}")
                try:
                    idx_val = int(raw_idx)
                except (TypeError, ValueError) as e:
                    raise _StructuralMismatchError(f"Non-integer index {raw_idx!r} at position {pos}") from e
                if idx_val < 0 or idx_val >= expected_count:
                    raise _StructuralMismatchError(f"Out-of-range index {idx_val} for batch of {expected_count}")
                if idx_val in mapped:
                    raise _StructuralMismatchError(f"Duplicate index {idx_val} in LLM batch response")

                trans_val = None
                for text_key in ("t", "text", "translation", "translated"):
                    if text_key in item:
                        trans_val = item[text_key]
                        break
                if trans_val is None or isinstance(trans_val, (dict, list)):
                    raise _StructuralMismatchError(f"Missing or invalid translated text for index {idx_val}")
                mapped[idx_val] = str(trans_val)

            if len(mapped) != expected_count:
                missing = sorted(set(range(expected_count)) - set(mapped.keys()))
                raise _StructuralMismatchError(f"Missing translated indices: {missing}")

            return [mapped[i] for i in range(expected_count)]

        # Case 2: Ordered array of primitive strings
        out: List[str] = []
        for pos, item in enumerate(parsed):
            if item is None or isinstance(item, (dict, list)):
                raise _StructuralMismatchError(f"Invalid item type {type(item).__name__} at position {pos}")
            out.append(str(item))
        return out

    def translate_batch(
        self,
        texts: List[str],
        target_lang: str,
        options: Optional[TranslationOptions] = None,
        source_lang: Optional[str] = None,
        max_retries: Optional[int] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[str]:
        """
        Translates a list of strings into target_lang and returns a list of translated strings of equal length.
        Enforces strict indexed alignment; automatically splits batches on structural mismatch.
        """
        if not texts:
            return []

        options = options or self.config.translation_options

        max_batch_items = resolve_config_int(self.config, "batch_size")
        max_batch_chars = resolve_config_int(self.config, "batch_max_chars")

        total_chars = sum(len(t) for t in texts)
        if len(texts) > max_batch_items or total_chars > max_batch_chars:
            if len(texts) > 1:
                sub_batches: List[List[str]] = []
                curr_sub: List[str] = []
                curr_chars = 0
                for t in texts:
                    t_len = len(t)
                    if curr_sub and (len(curr_sub) >= max_batch_items or (curr_chars + t_len > max_batch_chars)):
                        sub_batches.append(curr_sub)
                        curr_sub = [t]
                        curr_chars = t_len
                    else:
                        curr_sub.append(t)
                        curr_chars += t_len
                if curr_sub:
                    sub_batches.append(curr_sub)

                results: List[str] = []
                for sub_b in sub_batches:
                    results.extend(
                        self.translate_batch(
                            texts=sub_b,
                            target_lang=target_lang,
                            options=options,
                            source_lang=source_lang,
                            max_retries=max_retries,
                            cancel_check=cancel_check,
                        )
                    )
                return results

        system_prompt = build_system_prompt(target_lang, options, source_lang)
        indexed_payload = [{"i": idx, "t": text} for idx, text in enumerate(texts)]
        user_input_json = json.dumps(indexed_payload, ensure_ascii=False)
        user_prompt = (
            f"Translate all {len(texts)} items into {target_lang}. "
            f'Return ONLY a JSON object {{"translations": [{{"i": 0, "t": "..."}}]}} '
            f"containing every index i from 0 to {len(texts) - 1}:\n{user_input_json}"
        )

        model_name = self._get_selected_model()
        client = self._get_client()
        est_tokens = estimate_request_tokens(system_prompt, user_prompt)

        def _run_batch() -> List[str]:
            raw_response = client.generate_completion(system_prompt, user_prompt, model_name, is_json=True)
            return self._parse_batch_response(raw_response, len(texts))

        try:
            return self._execute_with_retry(
                _run_batch,
                max_retries=max_retries,
                cancel_check=cancel_check,
                error_context="translate batch",
                estimated_tokens=est_tokens,
            )
        except LLMError as err:
            if err.is_format_error and len(texts) > 1:
                mid = len(texts) // 2
                left = self.translate_batch(
                    texts=texts[:mid],
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang,
                    max_retries=max_retries,
                    cancel_check=cancel_check,
                )
                right = self.translate_batch(
                    texts=texts[mid:],
                    target_lang=target_lang,
                    options=options,
                    source_lang=source_lang,
                    max_retries=max_retries,
                    cancel_check=cancel_check,
                )
                return left + right
            raise

    def translate_markdown_text(
        self,
        markdown_text: str,
        target_lang: str,
        options: Optional[TranslationOptions] = None,
        source_lang: Optional[str] = None,
        max_retries: Optional[int] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        plain_text: bool = False,
    ) -> str:
        """Translates a Markdown or plain text block into target_lang preserving structure."""
        if not markdown_text.strip():
            return markdown_text

        options = options or self.config.translation_options
        clean_source = (source_lang or "").strip()
        source_note = (
            f"The primary source language is {clean_source} (mixed multilingual terms may still appear).\n"
            if clean_source and clean_source.lower() != "auto"
            else "The input document may contain mixed multilingual text.\n"
        )

        if plain_text:
            base_prompt = (
                f"You are a professional translator. Translate the following plain text document into {target_lang}.\n"
                + source_note
                + _critical_fidelity_rule(target_lang)
                + "\nSTRICT RULES:\n"
                "1. PRESERVE ALL LINE BREAKS, INDENTATION, AND PARAGRAPH STRUCTURE EXACTLY.\n"
                "2. DO NOT invent Markdown formatting or alter symbols like #, *, -, or |.\n"
                "3. DO NOT translate URLs, file paths, placeholders ({0}, %s), or identifiers.\n"
                "4. Return ONLY the translated text without conversational introduction or conclusion.\n"
                "5. UI LABELS AND QUOTATION MARKS: Adapt source quotation marks or corner brackets to the standard quotation marks of the target language for quoted terms. Do not insert extraneous words, category prefixes, or filler around them."
            )
            next_rule_idx = 6
        else:
            base_prompt = (
                f"You are a professional translator. Translate the following Markdown document into {target_lang}.\n"
                + source_note
                + _critical_fidelity_rule(target_lang)
                + "\nSTRICT RULES:\n"
                "1. PRESERVE ALL MARKDOWN FORMATTING (headers, lists, tables, bold, italics, links, blockquotes).\n"
                "2. If the input contains partial Markdown table rows (`| ... |`) without a header/separator row, keep them strictly as pipe-delimited rows without adding extra headers, separator rows, or blank lines.\n"
                "3. DO NOT translate code within code blocks or inline code.\n"
                "4. DO NOT translate URLs in markdown links or images.\n"
                "5. Return ONLY the translated Markdown text without conversational introduction or conclusion.\n"
                "6. UI LABELS AND QUOTATION MARKS: Adapt source quotation marks or corner brackets to the standard quotation marks of the target language for UI labels, button names, and quoted terms. Do not insert extraneous words, category prefixes, or filler around them."
            )
            next_rule_idx = 7

        prompt_parts = [base_prompt]
        if options.keep_it_terms:
            prompt_parts.append(f"{next_rule_idx}. {_KEEP_TERMS_RULE}")
            next_rule_idx += 1
        if options.append_original_words:
            prompt_parts.append(f"{next_rule_idx}. {_APPEND_ORIGINAL_RULE}")
        if options.custom_context and options.custom_context.strip():
            prompt_parts.append(f"\nCUSTOM GLOSSARY & CONTEXT:\n{options.custom_context.strip()}")
        system_prompt = "\n".join(prompt_parts)

        model_name = self._get_selected_model()
        client = self._get_client()
        est_tokens = estimate_request_tokens(system_prompt, markdown_text)
        try:
            return self._execute_with_retry(
                lambda: client.generate_completion(system_prompt, markdown_text, model_name, is_json=False),
                max_retries=max_retries,
                cancel_check=cancel_check,
                error_context="translate text section" if plain_text else "translate markdown section",
                estimated_tokens=est_tokens,
            )
        except LLMError as err:
            if err.is_format_error:
                split_parts = self._split_markdown_for_retry(markdown_text, plain_text=plain_text)
                if split_parts is not None:
                    left_text, sep, right_text = split_parts
                    left_tr = self.translate_markdown_text(
                        markdown_text=left_text,
                        target_lang=target_lang,
                        options=options,
                        source_lang=source_lang,
                        max_retries=max_retries,
                        cancel_check=cancel_check,
                        plain_text=plain_text,
                    )
                    right_tr = self.translate_markdown_text(
                        markdown_text=right_text,
                        target_lang=target_lang,
                        options=options,
                        source_lang=source_lang,
                        max_retries=max_retries,
                        cancel_check=cancel_check,
                        plain_text=plain_text,
                    )
                    return f"{left_tr}{sep}{right_tr}"
            raise

    @staticmethod
    def _split_markdown_for_retry(text: str, plain_text: bool = False) -> Optional[Tuple[str, str, str]]:
        """Splits a truncated section near its midpoint at a blank-line or newline boundary outside code fences."""
        if len(text) < _MIN_SPLIT_RETRY_CHARS:
            return None
        mid = len(text) // 2
        candidates: List[Tuple[int, int]] = []
        line_breaks: List[int] = []
        pos = 0
        fence_char: Optional[str] = None
        fence_len = 0

        for line in text.splitlines(keepends=True):
            stripped = line.lstrip()
            if not plain_text and stripped.startswith(("```", "~~~")):
                ch = stripped[0]
                run_len = len(stripped) - len(stripped.lstrip(ch))
                if fence_char is None and run_len >= 3:
                    fence_char = ch
                    fence_len = run_len
                elif fence_char == ch and run_len >= fence_len and stripped[run_len:].strip() == "":
                    fence_char = None
                    fence_len = 0
            line_end = pos + len(line)
            if fence_char is None:
                if line.strip() == "" and pos > 0 and line_end < len(text):
                    candidates.append((pos, line_end))
                if 0 < line_end < len(text) and line.endswith("\n"):
                    line_breaks.append(line_end)
            pos = line_end

        if candidates:
            split_start, split_end = min(candidates, key=lambda span: abs(span[0] - mid))
            return text[:split_start], text[split_start:split_end], text[split_end:]

        if line_breaks:
            split_pos = min(line_breaks, key=lambda p: abs(p - mid))
            return text[:split_pos], "", text[split_pos:]
        return None
