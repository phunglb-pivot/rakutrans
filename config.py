"""
Configuration management for RakuTrans AI.
Handles user settings persistence, default API keys, providers, and localization.
"""

import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional, Union

from model_fetcher import SEED_MODELS, load_cached_models

APP_NAME = "RakuTrans AI"
APP_VERSION = "1.0.0"
CONFIG_DIR = Path.home() / ".rakutrans"
CONFIG_FILE = CONFIG_DIR / "config.json"

SUPPORTED_LANGUAGES = {
    "en": "English",
    "ja": "日本語",
    "vi": "Tiếng Việt"
}

AI_PROVIDERS = {
    "Gemini": {
        "name": "Google Gemini",
        "default_model": "gemini-3.6-flash",
        "available_models": SEED_MODELS["Gemini"],
        "env_key": "GEMINI_API_KEY",
        "api_url_guide": "https://aistudio.google.com/app/apikey",
        "guide_text": "Get a free API key from Google AI Studio (aistudio.google.com)."
    },
    "OpenAI": {
        "name": "OpenAI (GPT)",
        "default_model": "gpt-4o-mini",
        "available_models": SEED_MODELS["OpenAI"],
        "env_key": "OPENAI_API_KEY",
        "api_url_guide": "https://platform.openai.com/api-keys",
        "guide_text": "Create an API key in your OpenAI Platform dashboard (platform.openai.com)."
    },
    "Claude": {
        "name": "Anthropic Claude",
        "default_model": "claude-3-7-sonnet-latest",
        "available_models": SEED_MODELS["Claude"],
        "env_key": "ANTHROPIC_API_KEY",
        "api_url_guide": "https://console.anthropic.com/settings/keys",
        "guide_text": "Generate an API key in your Anthropic Console (console.anthropic.com)."
    }
}

def get_provider_models(provider: str) -> list[str]:
    """Returns available models for provider from local cache, falling back to seed models."""
    return load_cached_models(provider)

# Fallback default demo keys or placeholders if user has not provided their own.
# Environment variables will override these.
DEFAULT_FALLBACK_KEYS = {
    "Gemini": os.getenv("GEMINI_API_KEY", ""),
    "OpenAI": os.getenv("OPENAI_API_KEY", ""),
    "Claude": os.getenv("ANTHROPIC_API_KEY", "")
}


@dataclass
class TranslationOptions:
    """Options that modify how translation prompt is formed and documents are exported."""
    keep_it_terms: bool = True
    append_original_words: bool = False
    custom_context: str = ""
    bilingual_mode: bool = False

    @property
    def keep_terms(self) -> bool:
        return self.keep_it_terms

    @keep_terms.setter
    def keep_terms(self, value: bool) -> None:
        self.keep_it_terms = value


@dataclass
class AppConfig:
    """Application configuration and state persistence."""
    ui_language: str = "en"
    theme_mode: str = "dark"
    active_provider: str = "Gemini"
    api_keys: Dict[str, str] = field(default_factory=lambda: {
        "Gemini": DEFAULT_FALLBACK_KEYS["Gemini"],
        "OpenAI": DEFAULT_FALLBACK_KEYS["OpenAI"],
        "Claude": DEFAULT_FALLBACK_KEYS["Claude"]
    })
    selected_models: Dict[str, str] = field(default_factory=lambda: {
        "Gemini": "gemini-3.6-flash",
        "OpenAI": "gpt-4o-mini",
        "Claude": "claude-3-7-sonnet-latest"
    })
    batch_size: int = 60
    target_language: str = "Vietnamese"
    source_language: Optional[str] = None
    translation_options: TranslationOptions = field(default_factory=TranslationOptions)

    def get_effective_api_key(self, provider: Optional[str] = None) -> str:
        """Returns the active API key with fallback to env vars or default fallback."""
        target_provider = provider or self.active_provider
        user_key = self.api_keys.get(target_provider, "").strip()
        if user_key:
            return user_key
        
        # Fallback to environment variable
        env_var = AI_PROVIDERS.get(target_provider, {}).get("env_key")
        if env_var and os.getenv(env_var):
            return os.getenv(env_var, "").strip()
            
        return DEFAULT_FALLBACK_KEYS.get(target_provider, "").strip()

    def get_active_model(self) -> str:
        """Returns current model for the active provider."""
        return self.selected_models.get(
            self.active_provider, 
            AI_PROVIDERS[self.active_provider]["default_model"]
        )

    def get_available_models(self, provider: Optional[str] = None) -> list[str]:
        """Returns cached/fresh available models for the given or active provider."""
        prov = provider or self.active_provider
        return load_cached_models(prov)

    def save(self) -> None:
        """Save settings to disk."""
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                "ui_language": self.ui_language,
                "theme_mode": self.theme_mode,
                "active_provider": self.active_provider,
                "api_keys": self.api_keys,
                "selected_models": self.selected_models,
                "batch_size": self.batch_size,
                "target_language": self.target_language,
                "translation_options": asdict(self.translation_options)
            }
            if self.source_language:
                data["source_language"] = self.source_language
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[Warning] Failed to save config: {e}")

    @classmethod
    def load(cls) -> "AppConfig":
        """Load settings from disk or return default config."""
        if not CONFIG_FILE.exists():
            config = cls()
            config.save()
            return config

        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            raw_options = data.get("translation_options", {})
            options = TranslationOptions(
                keep_it_terms=raw_options.get("keep_it_terms", True),
                append_original_words=raw_options.get("append_original_words", False),
                custom_context=raw_options.get("custom_context", "")
            )

            loaded_models = data.get("selected_models", {})
            gemini_model = loaded_models.get("Gemini", "gemini-3.6-flash")
            # Auto-migrate deprecated/unavailable legacy models
            if gemini_model in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro", "gemini-2.0-flash"]:
                gemini_model = "gemini-3.6-flash"

            openai_model = loaded_models.get("OpenAI", "gpt-4o-mini")
            claude_model = loaded_models.get("Claude", "claude-3-7-sonnet-latest")

            config = cls(
                ui_language=data.get("ui_language", "en"),
                theme_mode=data.get("theme_mode", "dark"),
                active_provider=data.get("active_provider", "Gemini"),
                api_keys={
                    "Gemini": data.get("api_keys", {}).get("Gemini", DEFAULT_FALLBACK_KEYS["Gemini"]),
                    "OpenAI": data.get("api_keys", {}).get("OpenAI", DEFAULT_FALLBACK_KEYS["OpenAI"]),
                    "Claude": data.get("api_keys", {}).get("Claude", DEFAULT_FALLBACK_KEYS["Claude"])
                },
                selected_models={
                    "Gemini": gemini_model,
                    "OpenAI": openai_model,
                    "Claude": claude_model
                },
                batch_size=data.get("batch_size", 60),
                target_language=data.get("target_language", "Vietnamese"),
                source_language=data.get("source_language", None),
                translation_options=options
            )
            return config
        except Exception as e:
            print(f"[Warning] Failed to load config, using defaults: {e}")
            return cls()


# -------------------------------------------------------------------------
# Smart Output Path Helpers
# -------------------------------------------------------------------------

LANGUAGE_CODES: Dict[str, str] = {
    "vietnamese": "vi",
    "tiếng việt": "vi",
    "vi": "vi",
    "english": "en",
    "tiếng anh": "en",
    "en": "en",
    "japanese": "ja",
    "tiếng nhật": "ja",
    "ja": "ja",
}


def get_target_lang_code(lang_str: Optional[str]) -> str:
    """Returns a clean 2-letter ISO language code (e.g. 'vi', 'en', 'ja')."""
    cleaned = (lang_str or "").strip().lower()
    return LANGUAGE_CODES.get(cleaned, cleaned[:2] if len(cleaned) >= 2 else "vi")


def get_unique_output_path(target_path: Path) -> Path:
    """
    If target_path does not exist on disk, return it as-is.
    If target_path already exists, return the next available indexed path:
    'name (1).ext', 'name (2).ext', etc., avoiding nested '(1) (1)'.
    """
    if not target_path.exists():
        return target_path

    parent = target_path.parent
    stem = target_path.stem
    suffix = target_path.suffix

    m = re.match(r"^(.*?)\s*\((\d+)\)$", stem)
    if m:
        base_stem = m.group(1).rstrip()
        counter = int(m.group(2)) + 1
    else:
        base_stem = stem
        counter = 1

    while True:
        candidate = parent / f"{base_stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
        if counter > 1000:
            return candidate


def get_smart_output_path(
    source_path: Union[str, Path],
    target_lang: Optional[str] = None,
    target_format: Optional[str] = None,
    is_bilingual: bool = False,
    custom_output_path: Optional[str] = None
) -> Path:
    """
    Generates an intelligent, clean, non-colliding output path:
    - Translation mode (target_lang specified):
        e.g. report.xlsx -> report_vi.xlsx (or report_vi (1).xlsx if exists)
        e.g. report_en.xlsx -> report_en_vi.xlsx
        e.g. if already ends with _vi: report_vi.xlsx -> report_vi (1).xlsx
        e.g. if bilingual: report_vi_bilingual.xlsx
    - Convert mode (target_lang is None):
        e.g. report.xlsx -> report.md (or report (1).md if exists)
        e.g. report.md -> report.xlsx (or report (1).xlsx if exists)
    """
    if custom_output_path:
        return Path(custom_output_path)

    src = Path(source_path)
    parent = src.parent
    src_stem = src.stem
    suffix = (target_format if target_format else src.suffix)
    if not suffix.startswith("."):
        suffix = f".{suffix}"

    if target_lang:
        lang_code = get_target_lang_code(target_lang)
        # Avoid redundant double tags like report_vi_vi
        if src_stem.endswith(f"_{lang_code}"):
            stem_base = src_stem
        else:
            stem_base = f"{src_stem}_{lang_code}"

        if is_bilingual:
            stem_base = f"{stem_base}_bilingual"
    else:
        # Convert format mode: keep same stem
        stem_base = src_stem

    desired_path = parent / f"{stem_base}{suffix}"
    return get_unique_output_path(desired_path)
