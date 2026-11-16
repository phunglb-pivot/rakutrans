"""
Dynamic Model Fetcher & Local Cache for RakuTrans AI.
Queries third-party provider APIs (Google Gemini, OpenAI, Anthropic Claude) directly
using their official SDK endpoints and metadata, and caches both model lists and
provider-reported model capabilities/limits locally without hardcoded model guesses.
"""

from datetime import datetime, timezone
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

CACHE_DIR = Path.home() / ".rakutrans"
MODELS_CACHE_FILE = CACHE_DIR / "models_cache.json"

SUPPORTED_PROVIDERS = ("Gemini", "OpenAI", "Claude")


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
    """Reads the local models cache JSON safely."""
    if not MODELS_CACHE_FILE.exists():
        return {}
    try:
        with open(MODELS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[ModelFetcher] Warning: failed to read cache: {e}")
        return {}


def _write_cache_data(data: Dict[str, Any]) -> None:
    """Persists the models cache JSON safely."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(MODELS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ModelFetcher] Warning: failed to write cache: {e}")


def load_cached_models(provider: str) -> List[str]:
    """Loads previously fetched live models for provider from local disk cache."""
    data = _read_cache_data()
    prov_data = data.get(provider)
    if isinstance(prov_data, dict):
        models = prov_data.get("models", [])
        if isinstance(models, list):
            return [str(m) for m in models if str(m).strip()]
    elif isinstance(prov_data, list):
        return [str(m) for m in prov_data if str(m).strip()]
    return []


def load_cached_model_metadata(provider: str) -> Dict[str, Dict[str, Any]]:
    """Loads provider-reported model metadata dict keyed by model ID."""
    data = _read_cache_data()
    prov_data = data.get(provider)
    if isinstance(prov_data, dict):
        meta = prov_data.get("models_meta", {})
        if isinstance(meta, dict):
            return meta
    return {}


def get_model_metadata(provider: str, model_name: str) -> Dict[str, Any]:
    """Returns cached API metadata for a specific model if available."""
    if not model_name:
        return {}
    return dict(load_cached_model_metadata(provider).get(model_name, {}))


def save_cached_models(
    provider: str,
    models: List[str],
    models_meta: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """Saves live fetched models and optional API metadata for a provider to disk cache."""
    if not models:
        return
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
    data = _read_cache_data()
    prov_entry = data.get(provider)
    if not isinstance(prov_entry, dict):
        prov_entry = {"updated_at": time.time(), "models": [], "models_meta": {}}
    models_meta = prov_entry.setdefault("models_meta", {})
    current = models_meta.get(model_name, {})
    if not isinstance(current, dict):
        current = {}
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


def _build_gemini_client(api_key: str, timeout_s: float = 30.0):
    """Instantiates google.genai.Client with explicit timeout and single-attempt HTTP retry options."""
    from google import genai
    from google.genai import types

    http_options = None
    if hasattr(types, "HttpOptions"):
        try:
            kwargs: Dict[str, Any] = {"timeout": int(timeout_s * 1000)}
            if hasattr(types, "HttpRetryOptions"):
                kwargs["retry_options"] = types.HttpRetryOptions(attempts=1)
            http_options = types.HttpOptions(**kwargs)
        except Exception:
            http_options = None

    return (
        genai.Client(api_key=api_key, http_options=http_options)
        if http_options is not None
        else genai.Client(api_key=api_key)
    )


def _fetch_gemini_models(api_key: str) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    models: List[str] = []
    meta_map: Dict[str, Dict[str, Any]] = {}

    try:
        client = _build_gemini_client(api_key, timeout_s=30.0)
    except ImportError:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=FutureWarning)
            import google.generativeai as genai_legacy
        genai_legacy.configure(api_key=api_key)
        for m in genai_legacy.list_models():
            name = _strip_gemini_prefix(getattr(m, "name", "") or "")
            if not name:
                continue
            methods = getattr(m, "supported_generation_methods", None) or []
            if "generateContent" not in methods:
                continue
            models.append(name)
            meta_map[name] = _extract_gemini_model_meta(m)
        deduped = list(dict.fromkeys(models))
        return deduped, meta_map

    for m in client.models.list():
        name = _strip_gemini_prefix(getattr(m, "name", "") or "")
        if not name:
            continue
        actions = (
            getattr(m, "supported_actions", None)
            or getattr(m, "supported_generation_methods", None)
            or []
        )
        if "generateContent" not in actions:
            continue
        models.append(name)
        meta_map[name] = _extract_gemini_model_meta(m)

    deduped = list(dict.fromkeys(models))
    return deduped, meta_map


def _fetch_openai_models(api_key: str) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, timeout=30.0, max_retries=0)
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


def _fetch_claude_models(api_key: str) -> Tuple[List[str], Dict[str, Dict[str, Any]]]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key, timeout=30.0, max_retries=0)
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


def fetch_live_models(provider: str, api_key: str) -> List[str]:
    """
    Directly queries the provider's official Models API to retrieve available models
    and persists both model IDs and official model metadata to local disk cache.
    """
    key = (api_key or "").strip()
    if not key:
        return load_cached_models(provider)

    if provider == "Gemini":
        models, meta_map = _fetch_gemini_models(key)
    elif provider == "OpenAI":
        models, meta_map = _fetch_openai_models(key)
    elif provider == "Claude":
        models, meta_map = _fetch_claude_models(key)
    else:
        raise ValueError(f"Unsupported AI provider: {provider}")

    if models:
        save_cached_models(provider, models, models_meta=meta_map)
        return models

    return load_cached_models(provider)


def check_model_exists_live(provider: str, api_key: str, model_name: str) -> bool:
    """
    Queries the provider's official single-model endpoint to confirm whether
    model_name belongs to that provider (without name-prefix guessing).
    """
    key = (api_key or "").strip()
    target = (model_name or "").strip()
    if not key or not target:
        return False

    try:
        if provider == "Gemini":
            client = _build_gemini_client(key, timeout_s=15.0)
            info = client.models.get(model=target)
            actions = getattr(info, "supported_actions", None) or []
            if "generateContent" not in actions:
                return False
            update_model_metadata("Gemini", target, _extract_gemini_model_meta(info))
            return True
        elif provider == "OpenAI":
            from openai import OpenAI
            client = OpenAI(api_key=key, timeout=15.0, max_retries=0)
            info = client.models.retrieve(target)
            meta: Dict[str, Any] = {}
            if getattr(info, "created", None) is not None:
                meta["created"] = info.created
            if getattr(info, "owned_by", None) is not None:
                meta["owned_by"] = info.owned_by
            if meta:
                update_model_metadata("OpenAI", target, meta)
            return True
        elif provider == "Claude":
            import anthropic
            client = anthropic.Anthropic(api_key=key, timeout=15.0, max_retries=0)
            info = client.models.retrieve(target)
            if getattr(info, "lifecycle", None) == "retired":
                return False
            update_model_metadata("Claude", target, _extract_claude_model_meta(info))
            return True
    except Exception:
        return False
    return False


def resolve_provider_for_model(
    model_name: str,
    api_keys: Optional[Dict[str, str]] = None,
    fallback: Optional[str] = None,
) -> Optional[str]:
    """
    Deterministically resolves which provider owns model_name by checking cached live
    models first, then querying configured providers' live APIs if keys are supplied.
    Never guesses ownership from model-name prefixes.
    """
    target = (model_name or "").strip()
    if not target:
        return fallback

    cached_matches = [
        prov for prov in SUPPORTED_PROVIDERS if target in load_cached_models(prov)
    ]
    if len(cached_matches) == 1:
        return cached_matches[0]
    if cached_matches:
        return fallback if fallback in cached_matches else cached_matches[0]

    if api_keys:
        live_matches: List[str] = []
        for prov in SUPPORTED_PROVIDERS:
            key = (api_keys.get(prov) or "").strip()
            if key and check_model_exists_live(prov, key, target):
                live_matches.append(prov)
        if len(live_matches) == 1:
            return live_matches[0]
        if live_matches:
            return fallback if fallback in live_matches else live_matches[0]

    return fallback


def fetch_models_async(
    provider: str,
    api_key: str,
    callback: Optional[Callable[[List[str], Optional[str]], None]] = None,
) -> threading.Thread:
    """
    Spawns a daemon thread to fetch live models asynchronously.
    Executes callback(models, error_message) upon completion.
    """
    def _worker():
        try:
            models = fetch_live_models(provider, api_key)
            if callback:
                callback(models, None)
        except Exception as e:
            fallback = load_cached_models(provider)
            if callback:
                callback(fallback, str(e))

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    return thread
