"""
Dynamic Model Fetcher & Local Cache for RakuTrans AI.
Queries third-party provider APIs (Google Gemini, OpenAI, Anthropic Claude) directly
using their official SDK endpoints and metadata, and caches both model lists and
provider-reported model capabilities/limits locally without hardcoded model guesses.
"""

from datetime import datetime, timezone
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rakutrans.core.config import AI_PROVIDERS, NUMERIC_SETTING_SPECS, get_config_dir

CACHE_DIR = get_config_dir()
MODELS_CACHE_FILE = CACHE_DIR / "models_cache.json"
_INITIAL_CACHE_DIR = CACHE_DIR
_INITIAL_MODELS_CACHE_FILE = MODELS_CACHE_FILE
_CACHE_LOCK = threading.RLock()
_DEFAULT_MODEL_FETCH_TIMEOUT_S = float(NUMERIC_SETTING_SPECS["model_fetch_timeout"].default)


def _resolve_models_cache_file() -> Path:
    """Resolves models_cache.json honoring both test monkeypatches and runtime RAKUTRANS_HOME."""
    if MODELS_CACHE_FILE != _INITIAL_MODELS_CACHE_FILE:
        return MODELS_CACHE_FILE
    if CACHE_DIR != _INITIAL_CACHE_DIR:
        return CACHE_DIR / "models_cache.json"
    return get_config_dir() / "models_cache.json"


def _to_timestamp(value: Any) -> float:
    """Converts numeric timestamps, datetimes, or ISO-8601 strings to Unix epoch seconds."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return 0.0
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            return 0.0
    return 0.0


def _is_past_date(date_str: Optional[str]) -> bool:
    """Returns True if an API-provided ISO date/timestamp is strictly in the past."""
    if not date_str or not isinstance(date_str, str):
        return False
    ts = _to_timestamp(date_str)
    if ts <= 0:
        return False
    return ts < time.time()


def _read_cache_data() -> Dict[str, Any]:
    """Reads the local models cache JSON safely under lock."""
    with _CACHE_LOCK:
        cache_file = _resolve_models_cache_file()
        if not cache_file.exists():
            return {}
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[ModelFetcher] Warning: failed to read cache: {e}")
            return {}


def _write_cache_data(data: Dict[str, Any]) -> None:
    """Persists the models cache JSON atomically and thread-safely."""
    tmp_path: Optional[Path] = None
    try:
        with _CACHE_LOCK:
            cache_file = _resolve_models_cache_file()
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                prefix=".models_cache_",
                suffix=".tmp",
                dir=str(cache_file.parent),
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(str(tmp_path), str(cache_file))
            tmp_path = None
    except Exception as e:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        print(f"[ModelFetcher] Warning: failed to write cache: {e}")


def _extract_provider_models(data: Dict[str, Any], provider: str) -> List[str]:
    prov_data = data.get(provider)
    if isinstance(prov_data, dict):
        models = prov_data.get("models", [])
        if isinstance(models, list):
            return [str(m) for m in models if str(m).strip()]
    elif isinstance(prov_data, list):
        return [str(m) for m in prov_data if str(m).strip()]
    return []


def load_cached_models(provider: str) -> List[str]:
    """Loads previously fetched live models for provider from local disk cache."""
    data = _read_cache_data()
    return _extract_provider_models(data, provider)


def load_cached_model_metadata(provider: str) -> Dict[str, Dict[str, Any]]:
    """Loads provider-reported model metadata dict keyed by model ID."""
    data = _read_cache_data()
    prov_data = data.get(provider)
    if isinstance(prov_data, dict):
        meta = prov_data.get("models_meta", {})
        if isinstance(meta, dict):
            return dict(meta)
    return {}


def get_model_metadata(provider: str, model_name: str) -> Dict[str, Any]:
    """Returns cached API metadata for a specific model if available."""
    if not model_name:
        return {}
    entry = load_cached_model_metadata(provider).get(model_name, {})
    return dict(entry) if isinstance(entry, dict) else {}


def save_cached_models(
    provider: str,
    models: List[str],
    models_meta: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Saves live fetched models and optional API metadata for a provider to disk cache."""
    if not models:
        return
    with _CACHE_LOCK:
        data = _read_cache_data()
        existing = data.get(provider) if isinstance(data.get(provider), dict) else {}
        entry: Dict[str, Any] = {
            "updated_at": time.time(),
            "models": list(dict.fromkeys(models)),
        }
        if models_meta is not None:
            entry["models_meta"] = models_meta
        elif isinstance(existing.get("models_meta"), dict):
            entry["models_meta"] = existing["models_meta"]

        data[provider] = entry
        _write_cache_data(data)


def update_model_metadata(provider: str, model_name: str, meta: Dict[str, Any]) -> None:
    """Merges official API metadata for a single model into the local disk cache."""
    if not model_name or not meta:
        return
    with _CACHE_LOCK:
        data = _read_cache_data()
        prov_entry = data.get(provider)
        if not isinstance(prov_entry, dict):
            prov_entry = {"updated_at": time.time(), "models": [], "models_meta": {}}
        models_meta = prov_entry.setdefault("models_meta", {})
        if not isinstance(models_meta, dict):
            models_meta = {}
            prov_entry["models_meta"] = models_meta
        current = models_meta.get(model_name, {})
        if not isinstance(current, dict):
            current = {}
        current = dict(current)
        current.update(meta)
        models_meta[model_name] = current
        data[provider] = prov_entry
        _write_cache_data(data)


def _strip_gemini_prefix(name: str) -> str:
    if name.startswith("models/"):
        return name[len("models/"):]
    return name


def _extract_gemini_model_meta(model_obj: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for attr in (
        "display_name",
        "version",
        "input_token_limit",
        "output_token_limit",
        "temperature",
        "max_temperature",
        "thinking",
    ):
        val = getattr(model_obj, attr, None)
        if val is not None:
            meta[attr] = val
    actions = (
        getattr(model_obj, "supported_actions", None)
        or getattr(model_obj, "supported_generation_methods", None)
    )
    if actions is not None:
        meta["supported_actions"] = list(actions)
    return meta


def _build_gemini_client(
    api_key: str,
    timeout_s: float = _DEFAULT_MODEL_FETCH_TIMEOUT_S,
    base_url: Optional[str] = None,
):
    """Instantiates google.genai.Client with explicit timeout and single-attempt HTTP retry options."""
    from google import genai
    from google.genai import types

    http_kwargs: Dict[str, Any] = {
        "timeout": int(timeout_s * 1000),
        "retry_options": types.HttpRetryOptions(attempts=1),
    }
    clean_url = (base_url or "").strip()
    if clean_url:
        http_kwargs["base_url"] = clean_url
    http_options = types.HttpOptions(**http_kwargs)
    return genai.Client(api_key=api_key, http_options=http_options)


def _fetch_gemini_models(
    api_key: str,
    timeout_s: float = _DEFAULT_MODEL_FETCH_TIMEOUT_S,
    base_url: Optional[str] = None,
) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    models: List[str] = []
    meta_map: Dict[str, Dict[str, Any]] = {}

    client = _build_gemini_client(api_key, timeout_s=timeout_s, base_url=base_url)
    for m in client.models.list():
        name = _strip_gemini_prefix(getattr(m, "name", "") or "")
        if not name:
            continue
        actions = getattr(m, "supported_actions", None) or []
        if "generateContent" not in actions:
            continue
        models.append(name)
        meta_map[name] = _extract_gemini_model_meta(m)

    deduped = list(dict.fromkeys(models))
    return deduped, meta_map


def _fetch_openai_models(
    api_key: str,
    timeout_s: float = _DEFAULT_MODEL_FETCH_TIMEOUT_S,
    base_url: Optional[str] = None,
) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    from openai import OpenAI

    client_kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "timeout": timeout_s,
        "max_retries": 0,
    }
    clean_url = (base_url or "").strip()
    if clean_url:
        client_kwargs["base_url"] = clean_url
    client = OpenAI(**client_kwargs)
    entries: List[Tuple[float, int, str, Dict[str, Any]]] = []

    for idx, m in enumerate(client.models.list()):
        model_id = (getattr(m, "id", "") or "").strip()
        if not model_id:
            continue
        shutdown_date = getattr(m, "shutdown_date", None)
        if _is_past_date(shutdown_date):
            continue
        created_ts = _to_timestamp(getattr(m, "created", None))
        meta: Dict[str, Any] = {}
        if getattr(m, "created", None) is not None:
            meta["created"] = m.created
        if getattr(m, "owned_by", None) is not None:
            meta["owned_by"] = m.owned_by
        if shutdown_date is not None:
            meta["shutdown_date"] = shutdown_date
        entries.append((created_ts, idx, model_id, meta))

    # Sort strictly by API-reported creation timestamp descending, preserving API order on ties
    entries.sort(key=lambda item: (-item[0], item[1]))

    models: List[str] = []
    meta_map: Dict[str, Dict[str, Any]] = {}
    for _, _, model_id, meta in entries:
        if model_id not in meta_map:
            models.append(model_id)
            meta_map[model_id] = meta
    return models, meta_map


def _extract_claude_model_meta(model_info: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for attr in ("display_name", "lifecycle", "line", "max_input_tokens", "max_tokens", "type"):
        val = getattr(model_info, attr, None)
        if val is not None:
            meta[attr] = val
    created_at = getattr(model_info, "created_at", None)
    if created_at is not None:
        meta["created_at"] = (
            created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
        )
    caps = getattr(model_info, "capabilities", None)
    if caps is not None:
        cap_summary: Dict[str, bool] = {}
        for cap_name in ("structured_outputs", "batch", "thinking", "citations"):
            cap_obj = getattr(caps, cap_name, None)
            supported = getattr(cap_obj, "supported", None)
            if isinstance(supported, bool):
                cap_summary[cap_name] = supported
        if cap_summary:
            meta["capabilities"] = cap_summary
    return meta


def _fetch_claude_models(
    api_key: str,
    timeout_s: float = _DEFAULT_MODEL_FETCH_TIMEOUT_S,
    base_url: Optional[str] = None,
) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    import anthropic

    client_kwargs: Dict[str, Any] = {
        "api_key": api_key,
        "timeout": timeout_s,
        "max_retries": 0,
    }
    clean_url = (base_url or "").strip()
    if clean_url:
        client_kwargs["base_url"] = clean_url
    client = anthropic.Anthropic(**client_kwargs)
    entries: List[Tuple[int, float, int, str, Dict[str, Any]]] = []

    for idx, m in enumerate(client.models.list()):
        model_id = (getattr(m, "id", "") or "").strip()
        if not model_id:
            continue
        model_type = getattr(m, "type", None)
        if model_type is not None and model_type != "model":
            continue
        lifecycle = getattr(m, "lifecycle", None)
        if lifecycle == "retired":
            continue
        retires_at = getattr(m, "retires_at", None)
        if isinstance(retires_at, datetime) and _to_timestamp(retires_at) < time.time():
            continue

        lifecycle_rank = 1 if lifecycle == "deprecated" else 0
        created_ts = _to_timestamp(getattr(m, "created_at", None))
        meta = _extract_claude_model_meta(m)
        entries.append((lifecycle_rank, created_ts, idx, model_id, meta))

    # Active models before deprecated, newest created_at first
    entries.sort(key=lambda item: (item[0], -item[1], item[2]))

    models: List[str] = []
    meta_map: Dict[str, Dict[str, Any]] = {}
    for _, _, _, model_id, meta in entries:
        if model_id not in meta_map:
            models.append(model_id)
            meta_map[model_id] = meta
    return models, meta_map


_PROVIDER_FETCHERS: Dict[str, Callable[..., Tuple[List[str], Dict[str, Dict[str, Any]]]]] = {
    "Gemini": _fetch_gemini_models,
    "OpenAI": _fetch_openai_models,
    "Claude": _fetch_claude_models,
}


def fetch_live_models(
    provider: str,
    api_key: str,
    base_url: Optional[str] = None,
    timeout: float = _DEFAULT_MODEL_FETCH_TIMEOUT_S,
) -> List[str]:
    """
    Directly queries the provider's official Models API to retrieve available models
    and persists both model IDs and official model metadata to local disk cache.
    """
    if provider not in AI_PROVIDERS:
        raise ValueError(f"Unsupported AI provider: {provider}")
    fetcher = _PROVIDER_FETCHERS.get(provider)
    if fetcher is None:
        raise ValueError(f"Unsupported AI provider: {provider}")

    key = (api_key or "").strip()
    if not key:
        return []

    models, meta_map = fetcher(key, timeout_s=timeout, base_url=base_url)
    if models:
        save_cached_models(provider, models, models_meta=meta_map)
    return models


def fetch_models_async(
    provider: str,
    api_key: str,
    callback: Optional[Callable[[List[str], Optional[str]], None]] = None,
    base_url: Optional[str] = None,
    timeout: float = _DEFAULT_MODEL_FETCH_TIMEOUT_S,
) -> threading.Thread:
    """
    Spawns a daemon thread to fetch live models asynchronously.
    Executes callback(models, error_message) upon completion.
    """
    def _worker():
        try:
            models = fetch_live_models(provider, api_key, base_url=base_url, timeout=timeout)
            if callback:
                callback(models, None)
        except Exception as e:
            fallback = load_cached_models(provider)
            if callback:
                callback(fallback, str(e))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread
