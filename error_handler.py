"""
Error handling and diagnostics module for RakuTrans AI.
Classifies raw technical exceptions into actionable, user-friendly diagnostic information.
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


def diagnose_error(exc: Exception, i18n: Optional[Any] = None) -> DiagnosticInfo:
    """
    Analyzes an exception and returns a structured DiagnosticInfo with human-readable advice.
    """
    raw_str = str(exc)
    lower_str = raw_str.lower()
    full_trace = traceback.format_exc() if traceback.format_exc().strip() != "NoneType: None" else raw_str

    def t(key: str, default: str, **kwargs) -> str:
        if i18n and hasattr(i18n, "t"):
            val = i18n.t(key, **kwargs)
            if val != key:
                return val
        return default.format(**kwargs)

    # 1. User Cancellation
    if isinstance(exc, InterruptedError) or "cancelled" in lower_str:
        return DiagnosticInfo(
            category="cancelled",
            title=t("err_diag_cancel_title", "Translation Cancelled"),
            message=t("err_diag_cancel_msg", "The translation process was aborted by user."),
            action_advice=t("err_diag_cancel_advice", "You can restart translation whenever you are ready."),
            can_retry=True,
            requires_settings=False,
            technical_details=raw_str
        )

    # 2. File Lock / Permission Denied (Excel open on Windows/Mac)
    if isinstance(exc, PermissionError) or any(k in lower_str for k in ["permission denied", "errno 13", "sharing violation", "used by another process"]):
        return DiagnosticInfo(
            category="file_lock",
            title=t("err_diag_lock_title", "File Locked by Another App"),
            message=t("err_diag_lock_msg", "Cannot write to output file because it is open in Microsoft Excel or another program."),
            action_advice=t("err_diag_lock_advice", "Please close the document in Excel / your viewer and click 'Retry'."),
            can_retry=True,
            requires_settings=False,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 3. Quota / Rate Limit (429)
    if any(k in lower_str for k in ["429", "resource_exhausted", "quota", "rate limit", "rate_limit", "too many requests"]):
        return DiagnosticInfo(
            category="quota",
            title=t("err_diag_quota_title", "API Rate Limit / Quota Exceeded"),
            message=t("err_diag_quota_msg", "The AI provider returned a rate limit (HTTP 429) or free quota exhaustion."),
            action_advice=t("err_diag_quota_advice", "Wait 1-2 minutes and click 'Retry', or switch to another model/provider in Settings."),
            can_retry=True,
            requires_settings=True,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 4. Authentication / Invalid API Key (401, 403)
    if any(k in lower_str for k in ["401", "403", "api_key", "unauthorized", "forbidden", "invalid api key", "api_key_invalid"]):
        return DiagnosticInfo(
            category="auth",
            title=t("err_diag_auth_title", "Invalid or Missing API Key"),
            message=t("err_diag_auth_msg", "Authentication failed with the AI provider. The API key may be invalid or expired."),
            action_advice=t("err_diag_auth_advice", "Click 'Open Settings' to verify or update your API key for the active provider."),
            can_retry=True,
            requires_settings=True,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 5. Network / Connection Timeout
    if any(k in lower_str for k in ["connection", "timeout", "timed out", "network", "socket", "dns", "getaddrinfo"]):
        return DiagnosticInfo(
            category="network",
            title=t("err_diag_network_title", "Network Connection Error"),
            message=t("err_diag_network_msg", "Unable to establish a secure connection to the AI provider server."),
            action_advice=t("err_diag_network_advice", "Check your internet connection, proxy, or VPN, then click 'Retry'."),
            can_retry=True,
            requires_settings=False,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 6. JSON Parse / Output Format Discrepancy
    if any(k in lower_str for k in ["json", "expected json array", "length differs", "discrepancy"]):
        return DiagnosticInfo(
            category="format",
            title=t("err_diag_format_title", "AI Response Parsing Discrepancy"),
            message=t("err_diag_format_msg", "The AI model returned text that did not conform to the expected structured batch array."),
            action_advice=t("err_diag_format_advice", "Click 'Retry' to re-query the model, or choose a stronger model in Settings."),
            can_retry=True,
            requires_settings=True,
            technical_details=f"{raw_str}\n\n{full_trace}"
        )

    # 7. General / Unhandled Error
    return DiagnosticInfo(
        category="general",
        title=t("err_diag_general_title", "Translation Error Occurred"),
        message=raw_str if len(raw_str) < 180 else raw_str[:180] + "...",
        action_advice=t("err_diag_general_advice", "Inspect the technical log below or retry translation."),
        can_retry=True,
        requires_settings=False,
        technical_details=f"{raw_str}\n\n{full_trace}"
    )
