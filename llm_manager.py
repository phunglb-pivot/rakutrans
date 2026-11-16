"""
LLM Manager for RakuTrans AI.
Provides unified routing across Google Gemini, OpenAI GPT, and Anthropic Claude.
Features strict indexed JSON batching, automatic batch splitting on structural mismatch,
robust retries with exponential backoff, and error handling.
"""

import json
import random
import re
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import inspect
import json
import random
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeVar

from config import AI_PROVIDERS, AppConfig, TranslationOptions
from model_fetcher import fetch_live_models, get_model_metadata, update_model_metadata

T = TypeVar("T")

_NON_RETRYABLE_STATUS_CODES = frozenset({400, 401, 402, 403, 404, 413, 422})
_RATE_LIMIT_STATUS_CODES = frozenset({429, 529})

_NON_RETRYABLE_SDK_CLASSES = frozenset({
    "AuthenticationError",
    "PermissionDeniedError",
    "BadRequestError",
    "NotFoundError",
    "UnprocessableEntityError",
    "ContentTooLargeError",
    "RequestTooLargeError",
    "ContentFilterFinishReasonError",
})

_RATE_LIMIT_SDK_CLASSES = frozenset({
    "RateLimitError",
    "OverloadedError",
})

_NON_RETRYABLE_API_CODES = frozenset({
    "insufficient_quota",
    "billing_hard_limit_reached",
    "credit_balance_too_low",
    "invalid_api_key",
    "authentication_error",
    "permission_error",
    "not_found_error",
    "invalid_request_error",
    "model_not_found",
    "unauthenticated",
    "permission_denied",
    "invalid_argument",
    "not_found",
    "failed_precondition",
})

_RATE_LIMIT_API_CODES = frozenset({
    "resource_exhausted",
    "rate_limit_exceeded",
    "rate_limit_error",
    "overloaded_error",
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


def _iter_exception_chain(err: Exception, max_depth: int = 6):
    """Yield exception and its cause/context chain without infinite loops."""
    seen = set()
    curr: Optional[BaseException] = err
    depth = 0
    while curr is not None and id(curr) not in seen and depth < max_depth:
        seen.add(id(curr))
        yield curr
        curr = curr.__cause__ or curr.__context__
        depth += 1


def _get_exception_class_names(err: BaseException) -> Set[str]:
    return {cls.__name__ for cls in type(err).__mro__}


def _extract_body_error_dict(exc: BaseException) -> Dict[str, Any]:
    """Extract structured error metadata dict from OpenAI/Anthropic/Google SDK payloads."""
    for attr in ("body", "details"):
        payload = getattr(exc, attr, None)
        if isinstance(payload, dict):
            nested = payload.get("error")
            if isinstance(nested, dict):
                return nested
            return payload
    return {}


def _get_http_status_code(err: Exception) -> Optional[int]:
    """Extract numeric HTTP status code from SDK exceptions, responses, or class names."""
    for exc in _iter_exception_chain(err):
        for attr in ("status_code", "code"):
            val = getattr(exc, attr, None)
            if isinstance(val, int) and val > 0:
                return val
        response = getattr(exc, "response", None)
        if response is not None:
            val = getattr(response, "status_code", None)
            if isinstance(val, int) and val > 0:
                return val
        cls_names = _get_exception_class_names(exc)
        if "AuthenticationError" in cls_names:
            return 401
        if "PermissionDeniedError" in cls_names:
            return 403
        if "NotFoundError" in cls_names:
            return 404
        if "BadRequestError" in cls_names:
            return 400
        if "UnprocessableEntityError" in cls_names:
            return 422
        if "RateLimitError" in cls_names:
            return 429
        if "OverloadedError" in cls_names:
            return 529
    return None


def _collect_structured_error_signals(err: Exception) -> Dict[str, Any]:
    """Collect authoritative API error metadata (codes, types, statuses, params, headers)."""
    codes: Set[str] = set()
    params: Set[str] = set()
    class_names: Set[str] = set()
    should_retry_header: Optional[str] = None

    for exc in _iter_exception_chain(err):
        class_names.update(_get_exception_class_names(exc))

        for attr in ("error_code", "error_type", "error_status", "type", "status"):
            val = getattr(exc, attr, None)
            if isinstance(val, str) and val.strip():
                codes.add(val.strip().lower())

        raw_code = getattr(exc, "code", None)
        if isinstance(raw_code, str) and raw_code.strip():
            codes.add(raw_code.strip().lower())

        param = getattr(exc, "param", None) or getattr(exc, "error_param", None)
        if isinstance(param, str) and param.strip():
            params.add(param.strip().lower())

        body_err = _extract_body_error_dict(exc)
        for key in ("code", "type", "status", "error_code"):
            val = body_err.get(key)
            if isinstance(val, str) and val.strip():
                codes.add(val.strip().lower())
        body_param = body_err.get("param")
        if isinstance(body_param, str) and body_param.strip():
            params.add(body_param.strip().lower())

        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) if response is not None else None
        if headers is not None and hasattr(headers, "get") and should_retry_header is None:
            hdr = headers.get("x-should-retry") or headers.get("X-Should-Retry")
            if isinstance(hdr, str) and hdr.strip():
                should_retry_header = hdr.strip().lower()

    return {
        "codes": codes,
        "params": params,
        "class_names": class_names,
        "should_retry": should_retry_header,
    }


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
    return min(max(float(val), 1.0), 90.0)


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
        error_param: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after
        self.response = response
        self.is_format_error = is_format_error
        self.error_code = error_code
        self.error_type = error_type
        self.error_status = error_status
        self.error_param = error_param


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
    raw_param = getattr(exc, "param", None) or body_err.get("param")
    err_param = str(raw_param) if isinstance(raw_param, str) else None

    wrapped = LLMError(
        f"{prefix}: {exc}",
        status_code=_get_http_status_code(exc),
        retry_after=extract_retry_delay(exc),
        response=getattr(exc, "response", None),
        error_code=err_code,
        error_type=err_type,
        error_status=err_status,
        error_param=err_param,
    )
    return wrapped


def _decode_first_json_slice(text: str) -> Optional[str]:
    """Use JSONDecoder.raw_decode to extract the first valid JSON object/array substring."""
    decoder = json.JSONDecoder(strict=False)
    for idx, ch in enumerate(text):
        if ch in "{[":
            try:
                parsed, end_idx = decoder.raw_decode(text, idx)
                if isinstance(parsed, (dict, list)):
                    return text[idx:end_idx].strip()
            except json.JSONDecodeError:
                continue
    return None


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

    # 3. Direct balanced scan across the full response
    extracted = _decode_first_json_slice(stripped)
    if extracted:
        return extracted

    # 4. Last-resort repair for trailing commas before ']' or '}' outside/at boundaries
    repaired = re.sub(r",\s*([\]}])", r"\1", stripped)
    extracted = _decode_first_json_slice(repaired)
    if extracted:
        return extracted

    return repaired


def build_system_prompt(
    target_lang: str,
    options: Optional[TranslationOptions] = None,
    source_lang: Optional[str] = None,
    *args,
    **kwargs,
) -> str:
    """Build a comprehensive system prompt enforcing indexed JSON format and translation rules."""
    # Support legacy signature: build_system_prompt(source_lang, target_lang, options)
    if isinstance(options, str):
        legacy_source = target_lang
        legacy_target = options
        legacy_opts = (
            source_lang
            if isinstance(source_lang, TranslationOptions)
            else (args[0] if args else kwargs.get("options", TranslationOptions()))
        )
        target_lang = legacy_target
        source_lang = legacy_source
        options = legacy_opts

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
        f"CRITICAL FIDELITY: Except for parenthetical source term annotations, keywords, code syntax, variable names, proper nouns, standard abbreviations, acronyms, numbers, punctuation, or content already in {target_lang}, ALL words, sentences, and explanatory text MUST be fully translated into {target_lang}.",
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

    if options.keep_it_terms:
        rules.append(
            "KEEP SPECIALIZED TERMS UNTRANSLATED: Maintain proper nouns, standard abbreviations, acronyms, "
            "and internationally recognized terms in their original form without forcing awkward or literal translations. "
            "Ensure surrounding sentences flow naturally and grammatically in the target language."
        )

    if options.append_original_words:
        rules.append(
            "APPEND ORIGINAL SOURCE WORDS AND ADAPT QUOTATION MARKS:\n"
            "- UI Labels and Quotation Marks: Enclose translated UI labels, button names, and filter options using the standard quotation marks of the target language rather than retaining source-specific bracket styles. Do not insert speculative filler words, category prefixes, or extra commentary around UI labels.\n"
            "- Verbatim Source Term: When appending the original term in parentheses immediately following its translation, the term inside the parentheses MUST be the exact verbatim string copied directly from the input source text in the original source language. Absolutely do not translate, interpret, or convert the original term into any other language.\n"
            "- Do not annotate common everyday words or terms that remain untranslated."
        )

    if options.custom_context and options.custom_context.strip():
        rules.append(f"PROJECT GLOSSARY & CONTEXT INSTRUCTIONS:\n{options.custom_context.strip()}")

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

    def __init__(self, api_key: str, timeout: float = 120.0):
        self.api_key = api_key
        self.timeout = timeout
        self._lock = threading.Lock()
        self._genai_client = None

    def _get_genai_client(self):
        with self._lock:
            if self._genai_client is not None:
                return self._genai_client
            from google import genai
            from google.genai import types

            http_options = None
            if hasattr(types, "HttpOptions"):
                try:
                    kwargs: Dict[str, Any] = {"timeout": int(self.timeout * 1000)}
                    if hasattr(types, "HttpRetryOptions"):
                        kwargs["retry_options"] = types.HttpRetryOptions(attempts=1)
                    http_options = types.HttpOptions(**kwargs)
                except Exception:
                    http_options = None

            if http_options is not None:
                try:
                    self._genai_client = genai.Client(api_key=self.api_key, http_options=http_options)
                    return self._genai_client
                except TypeError:
                    pass

            self._genai_client = genai.Client(api_key=self.api_key)
            return self._genai_client

    @staticmethod
    def _validate_gemini_response(response: Any) -> str:
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
            if "MAX_TOKENS" in upper_finish:
                raise LLMError(
                    "Gemini response truncated (finish_reason=MAX_TOKENS).",
                    is_format_error=True,
                )
            if any(flag in upper_finish for flag in ("SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED", "SPII")):
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
        try:
            from google.genai import types
        except ImportError:
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", category=FutureWarning)
                import google.generativeai as genai_legacy
            genai_legacy.configure(api_key=self.api_key)
            generation_config: Dict[str, Any] = {"temperature": 0.2}
            if is_json:
                generation_config["response_mime_type"] = "application/json"
            model = genai_legacy.GenerativeModel(
                model_name=model_name,
                system_instruction=system_prompt,
                generation_config=generation_config,
            )
            response = model.generate_content(user_prompt)
            return self._validate_gemini_response(response)

        client = self._get_genai_client()
        afc_config = None
        if hasattr(types, "AutomaticFunctionCallingConfig"):
            afc_config = types.AutomaticFunctionCallingConfig(disable=True)

        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            response_mime_type="application/json" if is_json else "text/plain",
            temperature=0.2,
            automatic_function_calling=afc_config,
        )
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
            raise LLMError("No Gemini model selected. Please fetch and select a model in Settings.", status_code=400)

        try:
            return self._call_gemini(system_prompt, user_prompt, target_model, is_json=is_json)
        except Exception as e:
            raise _wrap_provider_error("Gemini API Error", e) from e


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI API using structured error parameter reporting and finish_reason checks."""

    def __init__(self, api_key: str, timeout: float = 120.0):
        self.api_key = api_key
        self.timeout = timeout
        self._lock = threading.Lock()
        self._client = None
        self._unsupported_params: Dict[str, Set[str]] = {}

    def _get_client(self):
        with self._lock:
            if self._client is None:
                from openai import OpenAI
                self._client = OpenAI(api_key=self.api_key, timeout=self.timeout, max_retries=0)
            return self._client

    @staticmethod
    def _rejected_param_from_error(err: Exception, active_kwargs: Dict[str, Any]) -> Optional[str]:
        """Extract exact rejected parameter name from OpenAI structured error.param metadata."""
        signals = _collect_structured_error_signals(err)
        for candidate in ("temperature", "response_format"):
            if candidate in signals["params"] and candidate in active_kwargs:
                return candidate
        # Fallback only when gateway/mock omits structured `param`
        if not signals["params"]:
            lower = str(err).lower()
            for candidate in ("temperature", "response_format"):
                if candidate in lower and candidate in active_kwargs:
                    return candidate
        return None

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
            raise LLMError("No OpenAI model selected. Please fetch and select a model in Settings.", status_code=400)

        client = self._get_client()
        unsupported = self._unsupported_params.get(target_model, set())

        req_kwargs: Dict[str, Any] = {
            "model": target_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if "temperature" not in unsupported:
            req_kwargs["temperature"] = 0.2
        if is_json and "response_format" not in unsupported:
            req_kwargs["response_format"] = {"type": "json_object"}

        for _ in range(3):
            try:
                response = client.chat.completions.create(**req_kwargs)
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
            except LLMError:
                raise
            except Exception as e:
                status = _get_http_status_code(e)
                if status == 400:
                    rejected = self._rejected_param_from_error(e, req_kwargs)
                    if rejected:
                        req_kwargs.pop(rejected, None)
                        self._unsupported_params.setdefault(target_model, set()).add(rejected)
                        continue
                raise _wrap_provider_error("OpenAI API Error", e) from e

        raise LLMError("OpenAI API Error: failed after adjusting request parameters.")


class ClaudeClient(BaseLLMClient):
    """Client for Anthropic Claude API using official ModelInfo limits and SDK signature checks."""

    def __init__(self, api_key: str, timeout: float = 120.0):
        self.api_key = api_key
        self.timeout = timeout
        self._lock = threading.Lock()
        self._client = None
        self._model_max_tokens: Dict[str, int] = {}

    def _get_client(self):
        with self._lock:
            if self._client is None:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.api_key, timeout=self.timeout, max_retries=0)
            return self._client

    def _resolve_model_max_tokens(self, client: Any, model_name: str) -> int:
        """
        Resolves the model's authoritative max_tokens from Anthropic ModelInfo metadata
        (in-memory cache -> disk cache -> live `client.models.retrieve`).
        """
        if model_name in self._model_max_tokens:
            return self._model_max_tokens[model_name]

        cached_meta = get_model_metadata("Claude", model_name)
        cached_max = cached_meta.get("max_tokens")
        if isinstance(cached_max, int) and cached_max > 0:
            self._model_max_tokens[model_name] = cached_max
            return cached_max

        models_api = getattr(client, "models", None)
        retrieve_fn = getattr(models_api, "retrieve", None) if models_api is not None else None
        if callable(retrieve_fn):
            info = retrieve_fn(model_name)
            api_max = getattr(info, "max_tokens", None)
            if isinstance(api_max, int) and api_max > 0:
                self._model_max_tokens[model_name] = api_max
                meta_update: Dict[str, Any] = {"max_tokens": api_max}
                if getattr(info, "max_input_tokens", None) is not None:
                    meta_update["max_input_tokens"] = info.max_input_tokens
                if getattr(info, "lifecycle", None) is not None:
                    meta_update["lifecycle"] = info.lifecycle
                update_model_metadata("Claude", model_name, meta_update)
                return api_max

        # Minimal fallback only when a non-standard/mock client omits ModelInfo.max_tokens
        return 4096

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
            raise LLMError("No Claude model selected. Please fetch and select a model in Settings.", status_code=400)

        client = self._get_client()
        try:
            max_tokens = self._resolve_model_max_tokens(client, target_model)
            create_fn = client.messages.create
            req_kwargs: Dict[str, Any] = {
                "model": target_model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }
            try:
                sig_params = inspect.signature(create_fn).parameters
                if "temperature" in sig_params:
                    req_kwargs["temperature"] = 0.2
                if "timeout" in sig_params:
                    req_kwargs["timeout"] = self.timeout
            except (TypeError, ValueError):
                pass

            message = create_fn(**req_kwargs)
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


def create_llm_client(provider: str, api_key: str, timeout: float = 120.0) -> BaseLLMClient:
    """Shared factory creating the provider client for translation or connection tests."""
    factories: Dict[str, Callable[[str], BaseLLMClient]] = {
        "Gemini": lambda k: GeminiClient(k, timeout=timeout),
        "OpenAI": lambda k: OpenAIClient(k, timeout=timeout),
        "Claude": lambda k: ClaudeClient(k, timeout=timeout),
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
        self._client_lock = threading.Lock()
        self._model_resolve_lock = threading.Lock()
        self._cached_client_key: Optional[Tuple[str, str]] = None
        self._cached_client: Optional[BaseLLMClient] = None
        self._cooldown_until: float = 0.0
        self._next_dispatch_at: float = 0.0
        self._min_interval: float = 0.35

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

    def _acquire_request_slot(
        self,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """Respect shared 429 cooldowns and stagger request dispatches across threads."""
        if cancel_check and cancel_check():
            raise InterruptedError("Translation cancelled by user.")
        with self._rate_lock:
            now = time.monotonic()
            slot_time = max(now, self._cooldown_until, self._next_dispatch_at)
            self._next_dispatch_at = slot_time + self._min_interval
            wait_for = slot_time - now
        if wait_for > 0:
            self._sleep_with_cancel(wait_for, cancel_check=cancel_check)

    def _record_rate_limit(self, delay_seconds: float) -> None:
        """Set a shared cooldown across worker threads and slow dispatch pacing."""
        with self._rate_lock:
            now = time.monotonic()
            self._cooldown_until = max(self._cooldown_until, now + delay_seconds)
            self._min_interval = min(4.0, max(1.0, self._min_interval * 2.0))

    def _record_success(self) -> None:
        """Gradually restore dispatch pacing after successful API responses."""
        with self._rate_lock:
            self._min_interval = max(0.35, self._min_interval * 0.85)

    @staticmethod
    def _compute_backoff(attempt: int, err: Exception) -> Tuple[float, bool]:
        """Return (wait_seconds, is_rate_limit) for retry scheduling."""
        if is_rate_limit_error(err):
            extracted = extract_retry_delay(err)
            schedule = (8.0, 16.0, 32.0, 45.0)
            base = schedule[min(attempt, len(schedule) - 1)]
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
    ) -> T:
        """Execute an LLM operation with 429-aware shared cooldown and exponential backoff."""
        general_limit = max_retries if max_retries is not None else 3
        rate_limit_max = max_retries if max_retries is not None else 5
        attempt = 0
        last_error: Optional[Exception] = None

        while True:
            self._acquire_request_slot(cancel_check=cancel_check)
            try:
                result = operation()
                self._record_success()
                return result
            except InterruptedError:
                raise
            except Exception as e:
                last_error = e
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
                        error_param=getattr(e, "param", None) or body_err.get("param"),
                    ) from e

                wait_seconds, rate_limited = self._compute_backoff(attempt, e)
                limit = rate_limit_max if rate_limited else general_limit

                if rate_limited:
                    self._record_rate_limit(wait_seconds)

                attempt += 1
                if attempt >= limit:
                    break

                if not rate_limited:
                    self._sleep_with_cancel(wait_seconds, cancel_check=cancel_check)

        is_fmt = isinstance(last_error, (_StructuralMismatchError, json.JSONDecodeError)) or bool(
            getattr(last_error, "is_format_error", False)
        )
        err = LLMError(
            f"Failed to {error_context} after {attempt} attempts. Last error: {last_error}",
            status_code=_get_http_status_code(last_error) if last_error else None,
            retry_after=extract_retry_delay(last_error) if last_error else None,
            is_format_error=is_fmt,
            error_code=getattr(last_error, "error_code", None),
            error_type=getattr(last_error, "error_type", None),
            error_status=getattr(last_error, "error_status", None),
            error_param=getattr(last_error, "error_param", None),
        )
        raise err from last_error

    def _resolve_active_model(self) -> str:
        """
        Returns the configured model or, if none has been selected/cached yet
        and an API key is configured, discovers live models from the provider API.
        """
        model_name = (self.config.get_active_model() or "").strip()
        if model_name:
            return model_name

        provider = self.config.active_provider
        api_key = (self.config.get_effective_api_key(provider) or "").strip()
        if not api_key:
            return ""

        with self._model_resolve_lock:
            model_name = (self.config.get_active_model() or "").strip()
            if model_name:
                return model_name
            try:
                live_models = fetch_live_models(provider, api_key)
            except Exception as e:
                raise _wrap_provider_error(f"{provider} Model Fetch Error", e) from e
            if not live_models:
                raise LLMError(
                    f"No usable models returned by {provider} API. Please check your account or select a model in Settings.",
                    status_code=404,
                )
            chosen = live_models[0]
            self.config.selected_models[provider] = chosen
            if hasattr(self.config, "save"):
                self.config.save()
            return chosen

    def _get_client(self) -> BaseLLMClient:
        provider = self.config.active_provider
        api_key = self.config.get_effective_api_key(provider)
        cache_key = (provider, api_key)

        with self._client_lock:
            if self._cached_client is not None and self._cached_client_key == cache_key:
                return self._cached_client

            client = create_llm_client(provider, api_key)
            self._cached_client = client
            self._cached_client_key = cache_key
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
        *args,
        **kwargs,
    ) -> List[str]:
        """
        Translates a list of strings into target_lang and returns a list of translated strings of equal length.
        Enforces strict indexed alignment; automatically splits batches on structural mismatch.
        """
        if not texts:
            return []

        # Support legacy signature: translate_batch(texts, source_lang, target_lang, options)
        if isinstance(options, str):
            legacy_source = target_lang
            legacy_target = options
            legacy_opts = (
                source_lang
                if isinstance(source_lang, TranslationOptions)
                else (args[0] if args else kwargs.get("options", None))
            )
            target_lang = legacy_target
            source_lang = legacy_source
            options = legacy_opts

        options = options or self.config.translation_options

        MAX_SAFE_BATCH_ITEMS = 25
        MAX_SAFE_BATCH_CHARS = 3500

        total_chars = sum(len(t) for t in texts)
        if len(texts) > MAX_SAFE_BATCH_ITEMS or total_chars > MAX_SAFE_BATCH_CHARS:
            if len(texts) > 1:
                sub_batches: List[List[str]] = []
                curr_sub: List[str] = []
                curr_chars = 0
                for t in texts:
                    t_len = len(t)
                    if curr_sub and (len(curr_sub) >= MAX_SAFE_BATCH_ITEMS or (curr_chars + t_len > MAX_SAFE_BATCH_CHARS)):
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

        client = self._get_client()
        model_name = self._resolve_active_model()

        def _run_batch() -> List[str]:
            raw_response = client.generate_completion(system_prompt, user_prompt, model_name, is_json=True)
            return self._parse_batch_response(raw_response, len(texts))

        try:
            return self._execute_with_retry(
                _run_batch,
                max_retries=max_retries,
                cancel_check=cancel_check,
                error_context="translate batch",
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
        *args,
        **kwargs,
    ) -> str:
        """Translates a Markdown or plain text block into target_lang preserving structure."""
        # Support legacy signature: translate_markdown_text(markdown_text, source_lang, target_lang, options)
        if isinstance(options, str):
            legacy_source = target_lang
            legacy_target = options
            legacy_opts = (
                source_lang
                if isinstance(source_lang, TranslationOptions)
                else (args[0] if args else kwargs.get("options", None))
            )
            target_lang = legacy_target
            source_lang = legacy_source
            options = legacy_opts

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
            system_prompt = (
                f"You are a professional translator. Translate the following plain text document into {target_lang}.\n"
                + source_note
                + f"CRITICAL: Except for parenthetical source term annotations, keywords, code syntax, variable names, proper nouns, standard abbreviations, acronyms, numbers, punctuation, or content already in {target_lang}, ALL other words, sentences, and explanatory text MUST be fully translated into {target_lang}.\n"
                "STRICT RULES:\n"
                "1. PRESERVE ALL LINE BREAKS, INDENTATION, AND PARAGRAPH STRUCTURE EXACTLY.\n"
                "2. DO NOT invent Markdown formatting or alter symbols like #, *, -, or |.\n"
                "3. DO NOT translate URLs, file paths, placeholders ({0}, %s), or identifiers.\n"
                "4. Return ONLY the translated text without conversational introduction or conclusion.\n"
                "5. UI LABELS AND QUOTATION MARKS: Adapt source quotation marks or corner brackets to the standard quotation marks of the target language for quoted terms. Do not insert extraneous words, category prefixes, or filler around them."
            )
        else:
            system_prompt = (
                f"You are a professional translator. Translate the following Markdown document into {target_lang}.\n"
                + source_note
                + f"CRITICAL: Except for parenthetical source term annotations, keywords, code syntax, variable names, proper nouns, standard abbreviations, acronyms, numbers, punctuation, or content already in {target_lang}, ALL other words, sentences, and explanatory text MUST be fully translated into {target_lang}.\n"
                "STRICT RULES:\n"
                "1. PRESERVE ALL MARKDOWN FORMATTING (headers, lists, tables, bold, italics, links, blockquotes).\n"
                "2. If the input contains partial Markdown table rows (`| ... |`) without a header/separator row, keep them strictly as pipe-delimited rows without adding extra headers, separator rows, or blank lines.\n"
                "3. DO NOT translate code within code blocks or inline code.\n"
                "4. DO NOT translate URLs in markdown links or images.\n"
                "5. Return ONLY the translated Markdown text without conversational introduction or conclusion.\n"
                "6. UI LABELS AND QUOTATION MARKS: Adapt source quotation marks or corner brackets to the standard quotation marks of the target language for UI labels, button names, and quoted terms. Do not insert extraneous words, category prefixes, or filler around them."
            )

        if options.keep_it_terms:
            system_prompt += (
                "\n7. Keep proper nouns, standard abbreviations, acronyms, and international terms in their original form."
            )

        if options.append_original_words:
            system_prompt += (
                "\n8. APPEND ORIGINAL SOURCE WORDS: When appending the original term in parentheses immediately following its translation, "
                "the term inside the parentheses MUST be the exact verbatim string copied directly from the input source document in its original source language. "
                "Never translate, alter, or convert this original term into English or any other language. "
                "Enclose the translated UI labels in standard quotation marks of the target language rather than retaining source-specific bracket styles. "
                "Do not add unprompted commentary, category prefixes, or filler words around UI labels."
            )

        if options.custom_context and options.custom_context.strip():
            system_prompt += f"\n\nCUSTOM GLOSSARY & CONTEXT:\n{options.custom_context.strip()}"

        client = self._get_client()
        model_name = self._resolve_active_model()
        return self._execute_with_retry(
            lambda: client.generate_completion(system_prompt, markdown_text, model_name, is_json=False),
            max_retries=max_retries,
            cancel_check=cancel_check,
            error_context="translate text section" if plain_text else "translate markdown section",
        )
