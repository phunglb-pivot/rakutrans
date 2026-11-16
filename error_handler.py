"""
Error handling and diagnostics module for RakuTrans AI.
Classifies exceptions into actionable, user-friendly diagnostic information using
authoritative SDK exception types, HTTP status codes, and structured error codes first,
with text-pattern fallback only for unstructured exceptions.
"""

import traceback
from dataclasses import dataclass
from typing import Optional, Any


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


def _iter_chain(exc: Exception, max_depth: int = 6):
    seen = set()
    curr: Optional[BaseException] = exc
    depth = 0
    while curr is not None and id(curr) not in seen and depth < max_depth:
        seen.add(id(curr))
        yield curr
        curr = curr.__cause__ or curr.__context__
        depth += 1


def _extract_structured_diag_signals(exc: Exception):
    status_code: Optional[int] = None
    codes: set[str] = set()
    class_names: set[str] = set()
    is_format_error = False

    for err in _iter_chain(exc):
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

    return status_code, codes, class_names, is_format_error


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
        from i18n import I18nManager
        i18n = I18nManager()

    def t(key: str, **kwargs) -> str:
        return i18n.t(key, **kwargs)

    status_code, codes, class_names, is_format_error = _extract_structured_diag_signals(exc)

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
        or bool(class_names & {"AuthenticationError", "PermissionDeniedError"})
        or bool(codes & {"invalid_api_key", "authentication_error", "permission_error", "unauthenticated", "permission_denied"})
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
        or bool(codes & {"insufficient_quota", "billing_hard_limit_reached", "credit_balance_too_low"})
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
        status_code in (429, 529)
        or bool(class_names & {"RateLimitError", "OverloadedError"})
        or bool(codes & {"resource_exhausted", "rate_limit_exceeded", "rate_limit_error", "overloaded_error"})
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
    if bool(class_names & {"ConnectionError", "TimeoutError", "APIConnectionError", "APITimeoutError", "RequestTimeoutError", "GatewayTimeoutError", "DeadlineExceededError"}):
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
        message=raw_str if len(raw_str) < 180 else raw_str[:180] + "...",
        action_advice=t("err_diag_general_advice"),
        can_retry=True,
        requires_settings=(
            status_code == 404
            or "NotFoundError" in class_names
            or bool(codes & {"not_found", "not_found_error", "model_not_found"})
        ),
        technical_details=f"{raw_str}\n\n{full_trace}"
    )
