"""
Error handling and diagnostics module for RakuTrans AI.
Classifies exceptions into actionable, user-friendly diagnostic information using
authoritative SDK exception types, HTTP status codes, and structured error codes first,
with text-pattern fallback only for unstructured exceptions.
"""

import traceback
from dataclasses import dataclass
from typing import Optional, Any, Dict, Set

_GENERAL_MSG_MAX_CHARS = 180
_EXCEPTION_CHAIN_MAX_DEPTH = 6

AUTH_ERROR_CODES = frozenset({
    "invalid_api_key",
    "authentication_error",
    "permission_error",
    "unauthenticated",
    "permission_denied",
})
BILLING_ERROR_CODES = frozenset({
    "insufficient_quota",
    "billing_hard_limit_reached",
    "credit_balance_too_low",
})
RATE_LIMIT_STATUS_CODES = frozenset({429, 529})
RATE_LIMIT_API_CODES = frozenset({
    "resource_exhausted",
    "rate_limit_exceeded",
    "rate_limit_error",
    "overloaded_error",
})
NOT_FOUND_ERROR_CODES = frozenset({
    "not_found",
    "not_found_error",
    "model_not_found",
    "model_not_selected",
})
AUTH_SDK_CLASSES = frozenset({"AuthenticationError", "PermissionDeniedError"})
RATE_LIMIT_SDK_CLASSES = frozenset({"RateLimitError", "OverloadedError"})
NETWORK_SDK_CLASSES = frozenset({
    "ConnectionError",
    "TimeoutError",
    "APIConnectionError",
    "APITimeoutError",
    "RequestTimeoutError",
    "GatewayTimeoutError",
    "DeadlineExceededError",
})

_SDK_CLASS_HTTP_STATUS = {
    "AuthenticationError": 401,
    "PermissionDeniedError": 403,
    "NotFoundError": 404,
    "BadRequestError": 400,
    "UnprocessableEntityError": 422,
    "RateLimitError": 429,
    "OverloadedError": 529,
}


@dataclass
class DiagnosticInfo:
    """Structured information about an error with actionable recovery suggestions."""
    category: str  # 'quota', 'auth', 'network', 'file_lock', 'format', 'cancelled', 'general'
    title: str
    message: str
    action_advice: str
    can_retry: bool = True
    requires_settings: bool = False
    technical_details: str = ""


def iter_exception_chain(exc: BaseException, max_depth: int = _EXCEPTION_CHAIN_MAX_DEPTH):
    """Yield exception and its cause/context chain without infinite loops."""
    seen: Set[int] = set()
    curr: Optional[BaseException] = exc
    depth = 0
    while curr is not None and id(curr) not in seen and depth < max_depth:
        seen.add(id(curr))
        yield curr
        curr = curr.__cause__ or curr.__context__
        depth += 1


def extract_body_error_dict(exc: BaseException) -> Dict[str, Any]:
    """Extract structured error metadata dict from OpenAI/Anthropic/Google SDK payloads."""
    for attr in ("body", "details"):
        payload = getattr(exc, attr, None)
        if isinstance(payload, dict):
            nested = payload.get("error")
            if isinstance(nested, dict):
                return nested
            return payload
    return {}


def get_http_status_code(err: BaseException) -> Optional[int]:
    """Extract numeric HTTP status code from SDK exceptions, responses, or class names."""
    for exc in iter_exception_chain(err):
        for attr in ("status_code", "code"):
            val = getattr(exc, attr, None)
            if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                return val
        response = getattr(exc, "response", None)
        if response is not None:
            val = getattr(response, "status_code", None)
            if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                return val
        cls_names = {cls.__name__ for cls in type(exc).__mro__}
        for cls_name, code in _SDK_CLASS_HTTP_STATUS.items():
            if cls_name in cls_names:
                return code
    return None


def collect_structured_error_signals(exc: BaseException) -> Dict[str, Any]:
    """Collect authoritative API error metadata (status_code, codes, class_names, headers, format flag)."""
    status_code: Optional[int] = None
    codes: Set[str] = set()
    class_names: Set[str] = set()
    is_format_error = False
    should_retry_header: Optional[str] = None

    for err in iter_exception_chain(exc):
        class_names.update(cls.__name__ for cls in type(err).__mro__)
        if getattr(err, "is_format_error", False):
            is_format_error = True
        if status_code is None:
            for attr in ("status_code", "code"):
                val = getattr(err, attr, None)
                if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                    status_code = val
                    break
            if status_code is None:
                resp = getattr(err, "response", None)
                val = getattr(resp, "status_code", None) if resp is not None else None
                if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                    status_code = val
        for attr in ("error_code", "error_type", "error_status", "type", "status"):
            val = getattr(err, attr, None)
            if isinstance(val, str) and val.strip():
                codes.add(val.strip().lower())
        raw_code = getattr(err, "code", None)
        if isinstance(raw_code, str) and raw_code.strip():
            codes.add(raw_code.strip().lower())

        body_err = extract_body_error_dict(err)
        for key in ("code", "type", "status", "error_code"):
            val = body_err.get(key)
            if isinstance(val, str) and val.strip():
                codes.add(val.strip().lower())

        response = getattr(err, "response", None)
        headers = getattr(response, "headers", None) if response is not None else None
        if headers is not None and hasattr(headers, "get") and should_retry_header is None:
            hdr = headers.get("x-should-retry") or headers.get("X-Should-Retry")
            if isinstance(hdr, str) and hdr.strip():
                should_retry_header = hdr.strip().lower()

    return {
        "status_code": status_code,
        "codes": codes,
        "class_names": class_names,
        "is_format_error": is_format_error,
        "should_retry": should_retry_header,
    }


def diagnose_error(exc: Exception, i18n: Optional[Any] = None) -> DiagnosticInfo:
    """
    Analyzes an exception and returns a structured DiagnosticInfo with human-readable advice.
    """
    raw_str = str(exc) or type(exc).__name__
    lower_str = raw_str.lower()
    active_trace = traceback.format_exc()
    if active_trace.strip() != "NoneType: None":
        full_trace = active_trace
    elif getattr(exc, "__traceback__", None) is not None:
        full_trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    else:
        full_trace = raw_str

    if i18n is None or not hasattr(i18n, "t"):
        from rakutrans.core.i18n import I18nManager
        i18n = I18nManager()

    def t(key: str, **kwargs) -> str:
        return i18n.t(key, **kwargs)

    signals = collect_structured_error_signals(exc)
    status_code = signals["status_code"]
    codes = signals["codes"]
    class_names = signals["class_names"]
    is_format_error = signals["is_format_error"]

    # 1. User Cancellation (do not misclassify server/HTTP errors whose prose mentions "cancelled")
    is_user_cancel = (
        isinstance(exc, InterruptedError)
        or "InterruptedError" in class_names
        or (
            status_code is None
            and not codes
            and any(p in lower_str for p in ("cancelled by user", "canceled by user", "translation cancelled", "translation was cancelled", "conversion cancelled"))
        )
    )
    if is_user_cancel:
        return DiagnosticInfo(
            category="cancelled",
            title=t("err_diag_cancel_title"),
            message=t("err_diag_cancel_msg"),
            action_advice=t("err_diag_cancel_advice"),
            can_retry=True,
            requires_settings=False,
            technical_details=raw_str
        )

    # 2. File Lock / Permission Denied (Excel open on Windows/Mac)
    if isinstance(exc, PermissionError) or "PermissionError" in class_names or any(
        k in lower_str for k in ["permission denied", "errno 13", "sharing violation", "used by another process"]
    ):
        return DiagnosticInfo(
            category="file_lock",
            title=t("err_diag_lock_title"),
            message=t("err_diag_lock_msg"),
            action_advice=t("err_diag_lock_advice"),
            can_retry=True,
            requires_settings=False,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 3. Authentication / Invalid API Key (401, 403 or SDK auth classes/codes)
    if (
        status_code in (401, 403)
        or bool(class_names & AUTH_SDK_CLASSES)
        or bool(codes & AUTH_ERROR_CODES)
    ):
        return DiagnosticInfo(
            category="auth",
            title=t("err_diag_auth_title"),
            message=t("err_diag_auth_msg"),
            action_advice=t("err_diag_auth_advice"),
            can_retry=True,
            requires_settings=True,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 4a. Billing / Credits Depleted (HTTP 402 or non-retryable billing/quota codes)
    if (
        status_code == 402
        or bool(codes & BILLING_ERROR_CODES)
    ):
        return DiagnosticInfo(
            category="quota",
            title=t("err_diag_billing_title"),
            message=t("err_diag_billing_msg"),
            action_advice=t("err_diag_billing_advice"),
            can_retry=True,
            requires_settings=True,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 4b. Quota / Rate Limit (429, 529 or SDK RateLimit/Overloaded classes/codes)
    if (
        status_code in RATE_LIMIT_STATUS_CODES
        or bool(class_names & RATE_LIMIT_SDK_CLASSES)
        or bool(codes & RATE_LIMIT_API_CODES)
    ):
        return DiagnosticInfo(
            category="quota",
            title=t("err_diag_quota_title"),
            message=t("err_diag_quota_msg"),
            action_advice=t("err_diag_quota_advice"),
            can_retry=True,
            requires_settings=True,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 5. Network / Connection Timeout (SDK network/timeout classes or stdlib errors)
    if bool(class_names & NETWORK_SDK_CLASSES):
        return DiagnosticInfo(
            category="network",
            title=t("err_diag_network_title"),
            message=t("err_diag_network_msg"),
            action_advice=t("err_diag_network_advice"),
            can_retry=True,
            requires_settings=False,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 6. Structured Output / Format Discrepancy
    if is_format_error or "JSONDecodeError" in class_names:
        return DiagnosticInfo(
            category="format",
            title=t("err_diag_format_title"),
            message=t("err_diag_format_msg"),
            action_advice=t("err_diag_format_advice"),
            can_retry=True,
            requires_settings=True,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # Text-pattern fallback only when structured SDK/HTTP metadata was not decisive
    if status_code is None and not codes:
        if any(
            k in lower_str
            for k in [
                "prepayment credits",
                "credits are depleted",
                "credit_balance_too_low",
                "billing_hard_limit_reached",
                "insufficient_quota",
                "credit balance",
                "billing",
            ]
        ):
            return DiagnosticInfo(
                category="quota",
                title=t("err_diag_billing_title"),
                message=t("err_diag_billing_msg"),
                action_advice=t("err_diag_billing_advice"),
                can_retry=True,
                requires_settings=True,
                technical_details=f"{raw_str}\n\n{full_trace}"
            )

        if any(k in lower_str for k in ["429", "resource_exhausted", "quota", "rate limit", "rate_limit", "too many requests"]):
            return DiagnosticInfo(
                category="quota",
                title=t("err_diag_quota_title"),
                message=t("err_diag_quota_msg"),
                action_advice=t("err_diag_quota_advice"),
                can_retry=True,
                requires_settings=True,
                technical_details=f"{raw_str}\n\n{full_trace}"
            )

        if any(k in lower_str for k in ["401", "403", "api_key", "unauthorized", "forbidden", "invalid api key", "api_key_invalid"]):
            return DiagnosticInfo(
                category="auth",
                title=t("err_diag_auth_title"),
                message=t("err_diag_auth_msg"),
                action_advice=t("err_diag_auth_advice"),
                can_retry=True,
                requires_settings=True,
                technical_details=f"{raw_str}\n\n{full_trace}"
            )

        if any(k in lower_str for k in ["connection", "timeout", "timed out", "network", "socket", "dns", "getaddrinfo"]):
            return DiagnosticInfo(
                category="network",
                title=t("err_diag_network_title"),
                message=t("err_diag_network_msg"),
                action_advice=t("err_diag_network_advice"),
                can_retry=True,
                requires_settings=False,
                technical_details=f"{raw_str}\n\n{full_trace}"
            )

        if any(k in lower_str for k in ["json", "expected json array", "length differs", "discrepancy"]):
            return DiagnosticInfo(
                category="format",
                title=t("err_diag_format_title"),
                message=t("err_diag_format_msg"),
                action_advice=t("err_diag_format_advice"),
                can_retry=True,
                requires_settings=True,
                technical_details=f"{raw_str}\n\n{full_trace}"
            )

    # 7. General / Unhandled Error
    return DiagnosticInfo(
        category="general",
        title=t("err_diag_general_title"),
        message=raw_str if len(raw_str) < _GENERAL_MSG_MAX_CHARS else raw_str[:_GENERAL_MSG_MAX_CHARS] + "...",
        action_advice=t("err_diag_general_advice"),
        can_retry=True,
        requires_settings=(
            status_code == 404
            or "NotFoundError" in class_names
            or bool(codes & NOT_FOUND_ERROR_CODES)
        ),
        technical_details=f"{raw_str}\n\n{full_trace}"
    )
