"""
Configuration management for RakuTrans AI.
Handles user settings persistence, default API keys, providers, and localization.
"""

import json
import os
import re
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, Optional, Union

from model_fetcher import SEED_MODELS, load_cached_models

APP_NAME = "RakuTrans AI"
APP_VERSION = "1.0.0"
CONFIG_DIR = Path.home() / ".rakutrans"
CONFIG_FILE = CONFIG_DIR / "config.json"

UI_LANGUAGES = {
    "en": "English",
    "ja": "日本語",
    "vi": "Tiếng Việt"
}
# Backward compatibility alias
SUPPORTED_LANGUAGES = UI_LANGUAGES


@dataclass(frozen=True)
class LanguageInfo:
    """Represents a translation language with code, English name, and native name."""
    code: str
    name: str          # English name e.g. "Vietnamese", "Japanese"
    native_name: str   # Native name e.g. "Tiếng Việt", "日本語"

    @property
    def display_name(self) -> str:
        """Formatted representation combining native and English name."""
        return f"{self.native_name} ({self.name})"


# Comprehensive, unified world languages catalogue, sorted alphabetically by English name
ALL_LANGUAGES: list[LanguageInfo] = sorted([
    LanguageInfo("af", "Afrikaans", "Afrikaans"),
    LanguageInfo("sq", "Albanian", "Shqip"),
    LanguageInfo("ar", "Arabic", "العربية"),
    LanguageInfo("hy", "Armenian", "Հայերեն"),
    LanguageInfo("az", "Azerbaijani", "Azərbaycan"),
    LanguageInfo("eu", "Basque", "Euskara"),
    LanguageInfo("be", "Belarusian", "Беларуская"),
    LanguageInfo("bn", "Bengali", "বাংলা"),
    LanguageInfo("bs", "Bosnian", "Bosanski"),
    LanguageInfo("bg", "Bulgarian", "Български"),
    LanguageInfo("my", "Burmese", "မြန်မာ"),
    LanguageInfo("ca", "Catalan", "Català"),
    LanguageInfo("zh-CN", "Chinese (Simplified)", "简体中文"),
    LanguageInfo("zh-TW", "Chinese (Traditional)", "繁體中文"),
    LanguageInfo("hr", "Croatian", "Hrvatski"),
    LanguageInfo("cs", "Czech", "Čeština"),
    LanguageInfo("da", "Danish", "Dansk"),
    LanguageInfo("nl", "Dutch", "Nederlands"),
    LanguageInfo("en", "English", "English"),
    LanguageInfo("et", "Estonian", "Eesti"),
    LanguageInfo("fi", "Finnish", "Suomi"),
    LanguageInfo("fr", "French", "Français"),
    LanguageInfo("gl", "Galician", "Galego"),
    LanguageInfo("ka", "Georgian", "ქართული"),
    LanguageInfo("de", "German", "Deutsch"),
    LanguageInfo("el", "Greek", "Ελληνικά"),
    LanguageInfo("gu", "Gujarati", "ગુજરાતી"),
    LanguageInfo("he", "Hebrew", "עברית"),
    LanguageInfo("hi", "Hindi", "हिन्दी"),
    LanguageInfo("hu", "Hungarian", "Magyar"),
    LanguageInfo("is", "Icelandic", "Íslenska"),
    LanguageInfo("id", "Indonesian", "Bahasa Indonesia"),
    LanguageInfo("ga", "Irish", "Gaeilge"),
    LanguageInfo("it", "Italian", "Italiano"),
    LanguageInfo("ja", "Japanese", "日本語"),
    LanguageInfo("kn", "Kannada", "ಕನ್ನಡ"),
    LanguageInfo("kk", "Kazakh", "Қазақша"),
    LanguageInfo("km", "Khmer", "ភាសាខ្មែរ"),
    LanguageInfo("ko", "Korean", "한국어"),
    LanguageInfo("lo", "Lao", "ລາວ"),
    LanguageInfo("lv", "Latvian", "Latviešu"),
    LanguageInfo("lt", "Lithuanian", "Lietuvių"),
    LanguageInfo("mk", "Macedonian", "Македонски"),
    LanguageInfo("ms", "Malay", "Bahasa Melayu"),
    LanguageInfo("ml", "Malayalam", "മലയാളം"),
    LanguageInfo("mr", "Marathi", "मराठी"),
    LanguageInfo("mn", "Mongolian", "Монгол"),
    LanguageInfo("ne", "Nepali", "नेपाली"),
    LanguageInfo("no", "Norwegian", "Norsk"),
    LanguageInfo("fa", "Persian", "فارسی"),
    LanguageInfo("pl", "Polish", "Polski"),
    LanguageInfo("pt", "Portuguese", "Português"),
    LanguageInfo("pa", "Punjabi", "ਪੰਜਾਬੀ"),
    LanguageInfo("ro", "Romanian", "Română"),
    LanguageInfo("ru", "Russian", "Русский"),
    LanguageInfo("sr", "Serbian", "Српски"),
    LanguageInfo("sk", "Slovak", "Slovenčina"),
    LanguageInfo("sl", "Slovenian", "Slovenščina"),
    LanguageInfo("es", "Spanish", "Español"),
    LanguageInfo("sw", "Swahili", "Kiswahili"),
    LanguageInfo("sv", "Swedish", "Svenska"),
    LanguageInfo("tl", "Tagalog / Filipino", "Tagalog"),
    LanguageInfo("ta", "Tamil", "தமிழ்"),
    LanguageInfo("te", "Telugu", "తెలుగు"),
    LanguageInfo("th", "Thai", "ไทย"),
    LanguageInfo("tr", "Turkish", "Türkçe"),
    LanguageInfo("uk", "Ukrainian", "Українська"),
    LanguageInfo("ur", "Urdu", "اردو"),
    LanguageInfo("uz", "Uzbek", "Oʻzbekcha"),
    LanguageInfo("vi", "Vietnamese", "Tiếng Việt"),
    LanguageInfo("cy", "Welsh", "Cymraeg"),
], key=lambda lang: lang.name.lower())

def get_all_languages() -> list[LanguageInfo]:
    """Returns the full list of supported translation languages."""
    return list(ALL_LANGUAGES)

# Default target language is dynamically resolved as English from the catalogue
_english_info = next((l for l in ALL_LANGUAGES if l.code.lower() == "en"), None)
DEFAULT_TARGET_LANGUAGE: str = _english_info.display_name if _english_info else "English (English)"
_DEFAULT_TARGET_CODE: str = _english_info.code.lower() if _english_info else "en"

DEFAULT_RECENT_TARGET_LANGUAGES: list[str] = [
    "Tiếng Việt (Vietnamese)",
    "English (English)",
    "日本語 (Japanese)"
]

AI_PROVIDERS = {
    "Gemini": {
        "name": "Google Gemini",
        "default_model": "gemini-3.6-flash",
        "available_models": SEED_MODELS["Gemini"],
        "env_key": "GEMINI_API_KEY",
        "api_url_guide": "https://aistudio.google.com/app/apikey",
        "guide_key": "guide_gemini",
        "guide_text": "Get a free API key from Google AI Studio (aistudio.google.com)."
    },
    "OpenAI": {
        "name": "OpenAI (GPT)",
        "default_model": "gpt-4o-mini",
        "available_models": SEED_MODELS["OpenAI"],
        "env_key": "OPENAI_API_KEY",
        "api_url_guide": "https://platform.openai.com/api-keys",
        "guide_key": "guide_openai",
        "guide_text": "Create an API key in your OpenAI Platform dashboard (platform.openai.com)."
    },
    "Claude": {
        "name": "Anthropic Claude",
        "default_model": "claude-3-7-sonnet-latest",
        "available_models": SEED_MODELS["Claude"],
        "env_key": "ANTHROPIC_API_KEY",
        "api_url_guide": "https://console.anthropic.com/settings/keys",
        "guide_key": "guide_claude",
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


def normalize_language_name(lang_name_or_code: Optional[str]) -> str:
    """
    Normalizes any language string or code (e.g. 'vi', 'Vietnamese', 'Tiếng Việt',
    'Tiếng Việt (Vietnamese)') to its canonical display format: 'Native (English)'.
    If not recognized, returns the stripped input or DEFAULT_TARGET_LANGUAGE.
    """
    if not lang_name_or_code:
        return DEFAULT_TARGET_LANGUAGE

    query = lang_name_or_code.strip()
    query_lower = query.lower()

    # 1. Exact matches against code, name, native_name, or display_name
    for lang in ALL_LANGUAGES:
        if (
            query_lower == lang.display_name.lower()
            or query_lower == lang.code.lower()
            or query_lower == lang.name.lower()
            or query_lower == lang.native_name.lower()
        ):
            return lang.display_name

    # 2. Extract content inside parentheses e.g. "Tiếng Việt (Vietnamese)" or "(English)"
    m = re.search(r"\((.*?)\)", query)
    if m:
        inner = m.group(1).strip().lower()
        for lang in ALL_LANGUAGES:
            if inner == lang.name.lower() or inner == lang.code.lower():
                return lang.display_name

    return query


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
    target_language: str = DEFAULT_TARGET_LANGUAGE
    recent_target_languages: list[str] = field(default_factory=lambda: list(DEFAULT_RECENT_TARGET_LANGUAGES))
    source_language: Optional[str] = None
    translation_options: TranslationOptions = field(default_factory=TranslationOptions)

    def record_recent_target_language(self, lang_name: str) -> None:
        """Adds a language to the top of recent_target_languages (MRU, max 3)."""
        norm = normalize_language_name(lang_name)
        # Deduplicate while preserving order
        self.recent_target_languages = [l for l in self.recent_target_languages if l != norm]
        self.recent_target_languages.insert(0, norm)
        self.recent_target_languages = self.recent_target_languages[:3]

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
                "recent_target_languages": self.recent_target_languages,
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

            raw_target = data.get("target_language", DEFAULT_TARGET_LANGUAGE)
            normalized_target = normalize_language_name(raw_target)

            raw_recents = data.get("recent_target_languages")
            if raw_recents and isinstance(raw_recents, list):
                recents = []
                for r in raw_recents:
                    norm = normalize_language_name(str(r))
                    if norm not in recents:
                        recents.append(norm)
                recents = recents[:3]
            else:
                recents = list(DEFAULT_RECENT_TARGET_LANGUAGES)

            # Ensure the active target language is at the top of recent list
            if normalized_target not in recents:
                recents.insert(0, normalized_target)
                recents = recents[:3]

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
                target_language=normalized_target,
                recent_target_languages=recents,
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

def get_target_lang_code(lang_str: Optional[str]) -> str:
    """
    Returns a clean ISO language code (e.g. 'vi', 'en', 'ja', 'fr', 'ko') dynamically
    derived from ALL_LANGUAGES without hardcoded alias dictionaries or ad-hoc bias.
    """
    if not lang_str:
        return _DEFAULT_TARGET_CODE

    query = lang_str.strip().lower()

    # 1. Match code directly
    for lang in ALL_LANGUAGES:
        if query == lang.code.lower():
            return lang.code.lower()

    # 2. Match display name, English name, or native name
    for lang in ALL_LANGUAGES:
        if (
            query == lang.display_name.lower()
            or query == lang.name.lower()
            or query == lang.native_name.lower()
        ):
            return lang.code.lower()

    # 3. Match inside or outside parentheses e.g. "Tiếng Việt (Vietnamese)"
    m = re.search(r"^(.*?)\s*\((.*?)\)$", query)
    if m:
        outside, inside = m.group(1).strip().lower(), m.group(2).strip().lower()
        for lang in ALL_LANGUAGES:
            if (
                inside == lang.name.lower()
                or inside == lang.code.lower()
                or outside == lang.native_name.lower()
                or outside == lang.name.lower()
            ):
                return lang.code.lower()

    # 4. Clean fallback: alphanumeric slug without hardcoding any specific language
    cleaned = re.sub(r"[^a-zA-Z0-9]", "", query)
    if len(cleaned) >= 2:
        return cleaned[:3].lower()

    return _DEFAULT_TARGET_CODE


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
