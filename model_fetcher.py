"""
Dynamic Model Fetcher & Local Cache for RakuTrans AI.
Fetches up-to-date AI models from providers (Google Gemini, OpenAI, Claude),
applies smart text-generation filtering, and caches models locally to ensure
instant, reliable UI startup without blocking the interface.
"""

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import List, Dict, Optional, Callable

CACHE_DIR = Path.home() / ".rakutrans"
MODELS_CACHE_FILE = CACHE_DIR / "models_cache.json"

# Minimal seed models used when offline or on a fresh installation before fetching
SEED_MODELS: Dict[str, List[str]] = {
    "Gemini": [
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
        "gemini-flash-latest",
        "gemini-pro-latest"
    ],
    "OpenAI": [
        "gpt-4o-mini",
        "gpt-4o",
        "chatgpt-4o-latest",
        "o3-mini",
        "o1"
    ],
    "Claude": [
        "claude-3-7-sonnet-latest",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-latest"
    ]
}

# Exclusion keywords for non-text / non-chat models
EXCLUDED_KEYWORDS = [
    "embedding", "embed", "aqa", "lyria", "whisper", "tts", "dall-e",
    "imagen", "image", "image-generation", "veo", "robotics", "realtime",
    "audio", "moderation", "davinci", "babbage", "curie", "search",
    "customtools"
]


def _is_valid_text_model(model_name: str, provider: str) -> bool:
    """Filter out non-text/specialized models that are unsuitable for document translation."""
    lower = model_name.lower()
    
    # Exclude embeddings, audio, image models
    for kw in EXCLUDED_KEYWORDS:
        if kw in lower:
            return False

    if provider == "Gemini":
        # Keep gemini models with text generation capabilities
        if not lower.startswith("gemini"):
            return False
        # Prefer flash, pro, latest, lite models
        return any(k in lower for k in ["flash", "pro", "latest", "lite"])

    elif provider == "OpenAI":
        # Keep GPT-4, GPT-3.5, o1, o3, chatgpt
        return any(lower.startswith(prefix) for prefix in ["gpt-4", "gpt-3.5", "o1", "o3", "chatgpt"])

    elif provider == "Claude":
        return lower.startswith("claude")

    return True


def _sort_models(models: List[str], provider: str) -> List[str]:
    """Sort models so the most cost-effective and modern translation models appear on top."""
    def sort_key(name: str):
        lower = name.lower()
        if provider == "Gemini":
            # Priority:
            # 0: gemini-flash-latest / 3.8 / 3.7 / 3.6 flash
            # 1: other flash / lite models
            # 2: gemini-pro-latest / pro models
            # 3: others
            if "flash-latest" in lower:
                return (0, 0, name)
            elif "flash" in lower:
                # Extract number if any to sort descending (e.g. 3.8 > 3.7 > 3.6)
                nums = re.findall(r"(\d+(?:\.\d+)?)", lower)
                ver = float(nums[0]) if nums else 0.0
                return (0, -ver, name)
            elif "pro" in lower:
                nums = re.findall(r"(\d+(?:\.\d+)?)", lower)
                ver = float(nums[0]) if nums else 0.0
                return (1, -ver, name)
            return (2, 0, name)
        elif provider == "OpenAI":
            # Priority: mini / 4o first, then o3, then o1
            priority = 3
            if "mini" in lower:
                priority = 0
            elif "gpt-4o" in lower:
                priority = 1
            elif "o3" in lower:
                priority = 2
            return (priority, 0, name)
        elif provider == "Claude":
            # Priority: 3-7, then 3-5, then sonnet, then haiku
            prio = 5
            if "3-7" in lower:
                prio = 0
            elif "3-5" in lower:
                prio = 1
            return (prio, 0, name)
        return (0, 0, name)

    return sorted(list(dict.fromkeys(models)), key=sort_key)


def load_cached_models(provider: str) -> List[str]:
    """Load model list from local disk cache, falling back to seed models if not found."""
    if not MODELS_CACHE_FILE.exists():
        return SEED_MODELS.get(provider, [])

    try:
        with open(MODELS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            prov_data = data.get(provider)
            if prov_data and isinstance(prov_data, dict):
                models = prov_data.get("models", [])
                if models:
                    return models
            elif isinstance(prov_data, list) and prov_data:
                return prov_data
    except Exception as e:
        print(f"[ModelFetcher] Warning: failed to read cache: {e}")

    return SEED_MODELS.get(provider, [])


def save_cached_models(provider: str, models: List[str]) -> None:
    """Save fetched models for a provider to local disk cache."""
    if not models:
        return
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        data = {}
        if MODELS_CACHE_FILE.exists():
            try:
                with open(MODELS_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {}

        data[provider] = {
            "updated_at": time.time(),
            "models": models
        }

        with open(MODELS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[ModelFetcher] Warning: failed to write cache: {e}")


def fetch_live_models(provider: str, api_key: str) -> List[str]:
    """
    Directly queries the provider's API to retrieve live available models.
    Filters out non-text models and sorts them intelligently.
    """
    key = api_key.strip()
    if not key:
        return load_cached_models(provider)

    models: List[str] = []

    if provider == "Gemini":
        try:
            # Try Google GenAI SDK (google-genai 2.x)
            from google import genai
            client = genai.Client(api_key=key)
            raw_list = list(client.models.list())
            for m in raw_list:
                name = m.name or ""
                if name.startswith("models/"):
                    name = name[len("models/"):]
                
                # Check supported actions if available
                actions = (
                    getattr(m, "supported_actions", None) or 
                    getattr(m, "supported_generation_methods", None) or 
                    []
                )
                if actions and "generateContent" not in actions:
                    continue
                
                if _is_valid_text_model(name, "Gemini"):
                    models.append(name)
        except Exception as e:
            # Try legacy google.generativeai if google-genai had issues
            try:
                import warnings
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", category=FutureWarning)
                    import google.generativeai as genai_legacy
                genai_legacy.configure(api_key=key)
                for m in genai_legacy.list_models():
                    name = m.name or ""
                    if name.startswith("models/"):
                        name = name[len("models/"):]
                    methods = getattr(m, "supported_generation_methods", [])
                    if "generateContent" in methods and _is_valid_text_model(name, "Gemini"):
                        models.append(name)
            except Exception as legacy_err:
                raise RuntimeError(f"Gemini Model Fetch failed: {e}; Legacy fallback: {legacy_err}")

    elif provider == "OpenAI":
        try:
            from openai import OpenAI
            client = OpenAI(api_key=key)
            raw_list = client.models.list()
            for m in raw_list.data:
                name = m.id
                if _is_valid_text_model(name, "OpenAI"):
                    models.append(name)
        except Exception as e:
            raise RuntimeError(f"OpenAI Model Fetch failed: {e}")

    elif provider == "Claude":
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=key)
            # Anthropic models.list() API
            if hasattr(client, "models") and hasattr(client.models, "list"):
                raw_list = client.models.list()
                for m in raw_list.data:
                    name = m.id
                    if _is_valid_text_model(name, "Claude"):
                        models.append(name)
            if not models:
                models = SEED_MODELS["Claude"]
        except Exception as e:
            # Fallback to seed models if models.list() is not supported on key
            models = SEED_MODELS["Claude"]

    # Filter & sort
    filtered_models = [m for m in models if _is_valid_text_model(m, provider)]
    sorted_models = _sort_models(filtered_models, provider)

    if sorted_models:
        save_cached_models(provider, sorted_models)
        return sorted_models

    return load_cached_models(provider)


def fetch_models_async(
    provider: str,
    api_key: str,
    callback: Optional[Callable[[List[str], Optional[str]], None]] = None
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
