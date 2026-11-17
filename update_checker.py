"""
Update Checker for RakuTrans AI.
Checks GitHub Releases for newer application versions without blocking the UI
and resolves platform-appropriate download URLs (.dmg on macOS, .exe on Windows).
"""

from dataclasses import dataclass
import json
import platform
import re
import ssl
import threading
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from config import (
    APP_EXECUTABLE_NAME,
    APP_VERSION,
    DEFAULT_UI_LANGUAGE,
    LATEST_RELEASE_API_URL,
    RELEASES_PAGE_URL,
)

DEFAULT_UPDATE_CHECK_TIMEOUT_S = 6.0


def _t_update_err(ui_language: Optional[str], key: str, **kwargs: Any) -> str:
    from i18n import I18nManager

    return I18nManager(ui_language or DEFAULT_UI_LANGUAGE).t(key, **kwargs)


@dataclass(frozen=True)
class UpdateInfo:
    """Metadata describing an application release check result."""
    current_version: str
    latest_version: str
    has_update: bool
    release_url: str
    download_url: str
    asset_name: str = ""
    release_notes: str = ""
    published_at: str = ""


@dataclass(frozen=True)
class UpdateCheckResult:
    """Result returned by synchronous or asynchronous update checks."""
    status: str  # "update_available" | "up_to_date" | "error"
    info: Optional[UpdateInfo] = None
    error_message: str = ""


def normalize_version_str(version_str: str) -> str:
    """Strips whitespace and a leading 'v' prefix from a semantic version string."""
    raw = (version_str or "").strip()
    if raw.lower().startswith("v"):
        raw = raw[1:].strip()
    return raw


def parse_version(version_str: str) -> Tuple[Tuple[int, ...], Tuple[Tuple[int, Any], ...]]:
    """
    Parses semantic version strings (e.g. 'v1.2.3', '1.2.3-beta.1') into a comparable tuple:
    (numeric_core_tuple, prerelease_tuple).
    """
    cleaned = normalize_version_str(version_str)
    if not cleaned:
        return (0,), ()

    # Drop build metadata (+...)
    cleaned = cleaned.split("+", 1)[0].strip()

    if "-" in cleaned:
        core_part, pre_part = cleaned.split("-", 1)
    else:
        core_part, pre_part = cleaned, ""

    core_nums: List[int] = []
    for segment in core_part.split("."):
        m = re.match(r"^(\d+)", segment.strip())
        if m:
            core_nums.append(int(m.group(1)))
        else:
            core_nums.append(0)
    if not core_nums:
        core_nums = [0]

    pre_items: List[Tuple[int, Any]] = []
    if pre_part.strip():
        for token in re.split(r"[.\-_]+", pre_part.strip()):
            if not token:
                continue
            if token.isdigit():
                pre_items.append((0, int(token)))
            else:
                pre_items.append((1, token.lower()))

    return tuple(core_nums), tuple(pre_items)


def is_newer_version(latest: str, current: str) -> bool:
    """Returns True if `latest` represents a strictly newer version than `current`."""
    latest_core, latest_pre = parse_version(latest)
    current_core, current_pre = parse_version(current)

    max_len = max(len(latest_core), len(current_core))
    l_pad = latest_core + (0,) * (max_len - len(latest_core))
    c_pad = current_core + (0,) * (max_len - len(current_core))

    if l_pad != c_pad:
        return l_pad > c_pad

    # Equal numeric core: stable release > prerelease
    if not latest_pre and current_pre:
        return True
    if latest_pre and not current_pre:
        return False
    return latest_pre > current_pre


def _is_safe_https_url(url: Any) -> bool:
    return isinstance(url, str) and url.strip().lower().startswith("https://")


def pick_platform_asset(
    assets: Optional[List[Dict[str, Any]]],
    system_name: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Selects the best installer download URL and asset name for the current OS.
    Returns (download_url, asset_name) or ("", "") if none match.
    """
    if not assets or not isinstance(assets, list):
        return "", ""

    sys_name = (system_name or platform.system()).lower()
    valid_assets: List[Tuple[str, str]] = []
    for item in assets:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if name and _is_safe_https_url(url):
            valid_assets.append((name, url))

    if not valid_assets:
        return "", ""

    def _find_best(predicates: List[Callable[[str], bool]]) -> Tuple[str, str]:
        for pred in predicates:
            for name, url in valid_assets:
                if pred(name.lower()):
                    return url, name
        return "", ""

    if sys_name == "darwin":
        return _find_best([
            lambda n: n.endswith(".dmg") and ("mac" in n or "darwin" in n or "osx" in n),
            lambda n: n.endswith(".dmg"),
            lambda n: n.endswith(".pkg"),
            lambda n: n.endswith(".zip") and ("mac" in n or "darwin" in n),
        ])

    if sys_name == "windows":
        return _find_best([
            lambda n: n.endswith(".exe") and ("installer" in n or "setup" in n or "win" in n),
            lambda n: n.endswith(".exe"),
            lambda n: n.endswith(".msi"),
            lambda n: n.endswith(".zip") and "win" in n,
        ])

    # Linux / other platforms
    return _find_best([
        lambda n: n.endswith(".appimage"),
        lambda n: n.endswith(".deb"),
        lambda n: n.endswith(".tar.gz"),
        lambda n: n.endswith(".zip"),
    ])


def _build_ssl_context() -> ssl.SSLContext:
    """Uses certifi's CA bundle when available so frozen PyInstaller macOS apps verify TLS cleanly."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def check_for_updates(
    current_version: str = APP_VERSION,
    api_url: str = LATEST_RELEASE_API_URL,
    releases_url: str = RELEASES_PAGE_URL,
    timeout: float = DEFAULT_UPDATE_CHECK_TIMEOUT_S,
    system_name: Optional[str] = None,
    opener: Optional[Callable[..., Any]] = None,
    ui_language: Optional[str] = None,
) -> UpdateCheckResult:
    """
    Synchronously queries GitHub Releases API for the latest release and compares
    it with `current_version`.
    """
    norm_current = normalize_version_str(current_version) or "0.0.0"

    req = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_EXECUTABLE_NAME}/{norm_current}",
        },
        method="GET",
    )

    try:
        if opener is not None:
            resp_ctx = opener(req, timeout=timeout)
        else:
            ssl_ctx = _build_ssl_context()
            resp_ctx = urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx)

        with resp_ctx as resp:
            raw_bytes = resp.read()
        payload = json.loads(raw_bytes.decode("utf-8"))
        if not isinstance(payload, dict):
            return UpdateCheckResult(
                status="error",
                error_message=_t_update_err(ui_language, "update_err_invalid_metadata"),
            )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            # No published release exists yet on the repository
            return UpdateCheckResult(
                status="up_to_date",
                info=UpdateInfo(
                    current_version=norm_current,
                    latest_version=norm_current,
                    has_update=False,
                    release_url=releases_url,
                    download_url=releases_url,
                ),
            )
        if e.code in (403, 429):
            return UpdateCheckResult(
                status="error",
                error_message=_t_update_err(ui_language, "update_err_rate_limit", code=e.code),
            )
        return UpdateCheckResult(
            status="error",
            error_message=_t_update_err(ui_language, "update_err_http", code=e.code, reason=e.reason),
        )
    except Exception as e:
        return UpdateCheckResult(status="error", error_message=str(e))

    if payload.get("draft"):
        return UpdateCheckResult(
            status="up_to_date",
            info=UpdateInfo(
                current_version=norm_current,
                latest_version=norm_current,
                has_update=False,
                release_url=releases_url,
                download_url=releases_url,
            ),
        )

    raw_tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    latest_ver = normalize_version_str(raw_tag)
    if not latest_ver:
        return UpdateCheckResult(
            status="error",
            error_message=_t_update_err(ui_language, "update_err_missing_tag"),
        )

    html_url = str(payload.get("html_url") or "").strip()
    if not _is_safe_https_url(html_url):
        html_url = releases_url

    asset_url, asset_name = pick_platform_asset(payload.get("assets"), system_name=system_name)
    download_url = asset_url or html_url
    release_notes = str(payload.get("body") or "").strip()
    published_at = str(payload.get("published_at") or "").strip()

    has_update = is_newer_version(latest_ver, norm_current)
    info = UpdateInfo(
        current_version=norm_current,
        latest_version=latest_ver,
        has_update=has_update,
        release_url=html_url,
        download_url=download_url,
        asset_name=asset_name,
        release_notes=release_notes,
        published_at=published_at,
    )
    return UpdateCheckResult(
        status="update_available" if has_update else "up_to_date",
        info=info,
    )


def check_for_updates_async(
    callback: Callable[[UpdateCheckResult], None],
    current_version: str = APP_VERSION,
    api_url: str = LATEST_RELEASE_API_URL,
    releases_url: str = RELEASES_PAGE_URL,
    timeout: float = DEFAULT_UPDATE_CHECK_TIMEOUT_S,
    system_name: Optional[str] = None,
    ui_language: Optional[str] = None,
) -> threading.Thread:
    """Runs `check_for_updates` in a daemon thread and invokes `callback(result)`."""
    def _worker():
        try:
            res = check_for_updates(
                current_version=current_version,
                api_url=api_url,
                releases_url=releases_url,
                timeout=timeout,
                system_name=system_name,
                ui_language=ui_language,
            )
        except Exception as e:
            res = UpdateCheckResult(status="error", error_message=str(e))
        callback(res)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return t
