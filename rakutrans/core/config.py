"""
Configuration management for RakuTrans AI.
Handles user settings persistence, default API keys, providers, and localization.
"""

import json
import os
import re
import tempfile
import threading
import uuid
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Dict, Optional, Union

_CONFIG_IO_LOCK = threading.RLock()

APP_NAME = "RakuTrans AI"
APP_VERSION = "1.0.0"
APP_EXECUTABLE_NAME = "RakuTrans"
APP_BUNDLE_ID = "com.rakutrans.app"
APP_USER_MODEL_ID = "RakuTrans.AI.Desktop"
GITHUB_REPO = "phunglb-pivot/rakutrans"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPO}/releases"
LATEST_RELEASE_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

CONFIG_DIR_NAME = ".rakutrans"
LARGE_FILE_SIZE_BYTES = 10 * 1024 * 1024
HIGH_REQUEST_WARNING_THRESHOLD = 250
LARGE_FILE_REQUEST_FALLBACK_THRESHOLD = 100
SAFE_OUTPUT_PATH_MAX_ATTEMPTS = 1000


def get_config_dir() -> Path:
    """Returns the application data/config directory, honoring RAKUTRANS_HOME when set."""
    env_home = (os.getenv("RAKUTRANS_HOME") or "").strip()
    if env_home:
        return Path(env_home).expanduser().resolve()
    return Path.home() / CONFIG_DIR_NAME


CONFIG_DIR = get_config_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"
_INITIAL_CONFIG_DIR = CONFIG_DIR
_INITIAL_CONFIG_FILE = CONFIG_FILE


def _resolve_config_file() -> Path:
    """Resolves config.json honoring both test monkeypatches and runtime RAKUTRANS_HOME."""
    if CONFIG_FILE != _INITIAL_CONFIG_FILE:
        return CONFIG_FILE
    if CONFIG_DIR != _INITIAL_CONFIG_DIR:
        return CONFIG_DIR / "config.json"
    return get_config_dir() / "config.json"

UI_LANGUAGES = {
    "en": "English",
    "ja": "日本語",
    "vi": "Tiếng Việt"
}
DEFAULT_UI_LANGUAGE = "en"
DEFAULT_THEME_MODE = "dark"
THEME_MODES = ("dark", "light", "system")
DEFAULT_ACTIVE_PROVIDER = "Gemini"
DEFAULT_RATE_LIMIT_PRESET = "balanced"
MAX_RECENT_TARGET_LANGUAGES = 3


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
_LANG_BY_CODE = {lang.code.lower(): lang for lang in ALL_LANGUAGES}
_english_info = _LANG_BY_CODE.get("en")
DEFAULT_TARGET_LANGUAGE: str = _english_info.display_name if _english_info else "English (English)"
_DEFAULT_TARGET_CODE: str = _english_info.code.lower() if _english_info else "en"

DEFAULT_RECENT_TARGET_CODES: tuple[str, ...] = ("vi", "en", "ja")
DEFAULT_RECENT_TARGET_LANGUAGES: list[str] = [
    _LANG_BY_CODE[code].display_name
    for code in DEFAULT_RECENT_TARGET_CODES
    if code in _LANG_BY_CODE
][:MAX_RECENT_TARGET_LANGUAGES]

AI_PROVIDERS = {
    "Gemini": {
        "name": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "env_base_url_key": "GEMINI_BASE_URL",
        "icon_name": "provider_gemini",
        "api_url_guide": "https://aistudio.google.com/app/apikey",
        "guide_key": "guide_gemini",
    },
    "OpenAI": {
        "name": "OpenAI (GPT)",
        "env_key": "OPENAI_API_KEY",
        "env_base_url_key": "OPENAI_BASE_URL",
        "icon_name": "provider_openai",
        "api_url_guide": "https://platform.openai.com/api-keys",
        "guide_key": "guide_openai",
    },
    "Claude": {
        "name": "Anthropic Claude",
        "env_key": "ANTHROPIC_API_KEY",
        "env_base_url_key": "ANTHROPIC_BASE_URL",
        "icon_name": "provider_claude",
        "api_url_guide": "https://console.anthropic.com/settings/keys",
        "guide_key": "guide_claude",
    }
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

    # 2. Extract content inside parentheses e.g. "Tiếng Việt (Vietnamese)" or "繁體中文 (Chinese (Traditional))"
    m = re.search(r"\((.+)\)", query)
    if m:
        inner = m.group(1).strip().lower()
        for lang in ALL_LANGUAGES:
            if inner == lang.name.lower() or inner == lang.code.lower():
                return lang.display_name

    return query


def _coerce_int(raw_val: object, default: int, min_val: int, max_val: int) -> int:
    if raw_val is None or isinstance(raw_val, bool):
        return default
    if isinstance(raw_val, str) and not raw_val.strip():
        return default
    try:
        parsed = int(raw_val)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(parsed, max_val))


def _coerce_float(raw_val: object, default: float, min_val: float, max_val: float) -> float:
    if raw_val is None or isinstance(raw_val, bool):
        return default
    if isinstance(raw_val, str) and not raw_val.strip():
        return default
    try:
        parsed = float(raw_val)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:  # NaN guard
        return default
    return max(min_val, min(parsed, max_val))


def _coerce_optional_float(raw_val: object, min_val: float, max_val: float) -> Optional[float]:
    if raw_val is None or isinstance(raw_val, bool):
        return None
    if isinstance(raw_val, str) and not raw_val.strip():
        return None
    try:
        parsed = float(raw_val)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return max(min_val, min(parsed, max_val))


RATE_LIMIT_PRESETS: Dict[str, Dict[str, Union[int, float]]] = {
    "safe_free": {
        "max_concurrent_requests": 1,
        "min_request_interval": 4.0,
        "rpm_limit": 12,
        "tpm_limit": 100000,
        "batch_size": 100,
        "batch_max_chars": 12000,
        "section_max_chars": 12000,
        "max_retries_rate_limit": 8,
    },
    "balanced": {
        "max_concurrent_requests": 2,
        "min_request_interval": 0.5,
        "rpm_limit": 45,
        "tpm_limit": 0,
        "batch_size": 100,
        "batch_max_chars": 12000,
        "section_max_chars": 12000,
        "max_retries_rate_limit": 5,
    },
    "fast_paid": {
        "max_concurrent_requests": 4,
        "min_request_interval": 0.2,
        "rpm_limit": 0,
        "tpm_limit": 0,
        "batch_size": 100,
        "batch_max_chars": 12000,
        "section_max_chars": 12000,
        "max_retries_rate_limit": 5,
    },
}

_PREVIOUS_RATE_LIMIT_PRESETS: Dict[str, Dict[str, Union[int, float]]] = {
    "safe_free": {
        "max_concurrent_requests": 1,
        "min_request_interval": 4.0,
        "rpm_limit": 12,
        "tpm_limit": 100000,
        "batch_size": 50,
        "batch_max_chars": 8000,
        "section_max_chars": 8000,
        "max_retries_rate_limit": 8,
    },
    "balanced": {
        "max_concurrent_requests": 2,
        "min_request_interval": 0.5,
        "rpm_limit": 45,
        "tpm_limit": 0,
        "batch_size": 60,
        "batch_max_chars": 8000,
        "section_max_chars": 8000,
        "max_retries_rate_limit": 5,
    },
}

_LEGACY_RATE_LIMIT_PRESETS: Dict[str, Dict[str, Union[int, float]]] = {
    "safe_free": {
        "max_concurrent_requests": 1,
        "min_request_interval": 4.0,
        "rpm_limit": 12,
        "tpm_limit": 100000,
        "batch_size": 25,
        "batch_max_chars": 8000,
        "section_max_chars": 8000,
        "max_retries_rate_limit": 8,
    },
    "balanced": {
        "max_concurrent_requests": 2,
        "min_request_interval": 0.5,
        "rpm_limit": 45,
        "tpm_limit": 0,
        "batch_size": 25,
        "batch_max_chars": 6000,
        "section_max_chars": 6000,
        "max_retries_rate_limit": 5,
    },
    "fast_paid": {
        "max_concurrent_requests": 4,
        "min_request_interval": 0.2,
        "rpm_limit": 0,
        "tpm_limit": 0,
        "batch_size": 30,
        "batch_max_chars": 10000,
        "section_max_chars": 10000,
        "max_retries_rate_limit": 5,
    },
}

_DEFAULT_PRESET_VALUES = RATE_LIMIT_PRESETS[DEFAULT_RATE_LIMIT_PRESET]


@dataclass(frozen=True)
class NumericSettingSpec:
    """Single source of truth for numeric setting default and clamping bounds."""
    default: Optional[Union[int, float]]
    min_val: Union[int, float]
    max_val: Union[int, float]
    kind: str  # "int" | "float" | "optional_float"


NUMERIC_SETTING_SPECS: Dict[str, NumericSettingSpec] = {
    "temperature": NumericSettingSpec(None, 0.0, 2.0, "optional_float"),
    "request_timeout": NumericSettingSpec(120.0, 5.0, 600.0, "float"),
    "model_fetch_timeout": NumericSettingSpec(30.0, 3.0, 120.0, "float"),
    "batch_size": NumericSettingSpec(int(_DEFAULT_PRESET_VALUES["batch_size"]), 1, 500, "int"),
    "batch_max_chars": NumericSettingSpec(int(_DEFAULT_PRESET_VALUES["batch_max_chars"]), 200, 100000, "int"),
    "section_max_chars": NumericSettingSpec(int(_DEFAULT_PRESET_VALUES["section_max_chars"]), 200, 100000, "int"),
    "max_concurrent_requests": NumericSettingSpec(int(_DEFAULT_PRESET_VALUES["max_concurrent_requests"]), 1, 20, "int"),
    "min_request_interval": NumericSettingSpec(float(_DEFAULT_PRESET_VALUES["min_request_interval"]), 0.0, 60.0, "float"),
    "rpm_limit": NumericSettingSpec(int(_DEFAULT_PRESET_VALUES["rpm_limit"]), 0, 10000, "int"),
    "tpm_limit": NumericSettingSpec(int(_DEFAULT_PRESET_VALUES["tpm_limit"]), 0, 10000000, "int"),
    "max_retries_general": NumericSettingSpec(3, 1, 10, "int"),
    "max_retries_rate_limit": NumericSettingSpec(int(_DEFAULT_PRESET_VALUES["max_retries_rate_limit"]), 1, 15, "int"),
    "max_retries_format": NumericSettingSpec(2, 1, 10, "int"),
}


def coerce_setting_value(name: str, raw_val: object) -> Optional[Union[int, float]]:
    """Coerces and clamps a named numeric setting using NUMERIC_SETTING_SPECS."""
    spec = NUMERIC_SETTING_SPECS[name]
    if spec.kind == "int":
        return _coerce_int(raw_val, int(spec.default), int(spec.min_val), int(spec.max_val))
    if spec.kind == "float":
        return _coerce_float(raw_val, float(spec.default), float(spec.min_val), float(spec.max_val))
    return _coerce_optional_float(raw_val, float(spec.min_val), float(spec.max_val))


def resolve_config_int(config: Optional[object], name: str) -> int:
    """Safely reads and clamps an integer setting from config using NUMERIC_SETTING_SPECS."""
    spec = NUMERIC_SETTING_SPECS[name]
    raw_val = getattr(config, name, spec.default) if config is not None else spec.default
    return _coerce_int(raw_val, int(spec.default), int(spec.min_val), int(spec.max_val))


def resolve_config_float(config: Optional[object], name: str) -> float:
    """Safely reads and clamps a float setting from config using NUMERIC_SETTING_SPECS."""
    spec = NUMERIC_SETTING_SPECS[name]
    raw_val = getattr(config, name, spec.default) if config is not None else spec.default
    return _coerce_float(raw_val, float(spec.default), float(spec.min_val), float(spec.max_val))


@dataclass
class AppConfig:
    """Application configuration and state persistence."""
    ui_language: str = DEFAULT_UI_LANGUAGE
    theme_mode: str = DEFAULT_THEME_MODE
    active_provider: str = DEFAULT_ACTIVE_PROVIDER
    api_keys: Dict[str, str] = field(default_factory=lambda: {
        prov: "" for prov in AI_PROVIDERS
    })
    base_urls: Dict[str, str] = field(default_factory=lambda: {
        prov: "" for prov in AI_PROVIDERS
    })
    selected_models: Dict[str, str] = field(default_factory=lambda: {
        prov: "" for prov in AI_PROVIDERS
    })
    temperature: Optional[float] = None
    strict_json_mode: bool = True
    request_timeout: float = float(NUMERIC_SETTING_SPECS["request_timeout"].default)
    model_fetch_timeout: float = float(NUMERIC_SETTING_SPECS["model_fetch_timeout"].default)
    rate_limit_preset: str = DEFAULT_RATE_LIMIT_PRESET
    batch_size: int = int(NUMERIC_SETTING_SPECS["batch_size"].default)
    batch_max_chars: int = int(NUMERIC_SETTING_SPECS["batch_max_chars"].default)
    section_max_chars: int = int(NUMERIC_SETTING_SPECS["section_max_chars"].default)
    max_concurrent_requests: int = int(NUMERIC_SETTING_SPECS["max_concurrent_requests"].default)
    min_request_interval: float = float(NUMERIC_SETTING_SPECS["min_request_interval"].default)
    rpm_limit: int = int(NUMERIC_SETTING_SPECS["rpm_limit"].default)
    tpm_limit: int = int(NUMERIC_SETTING_SPECS["tpm_limit"].default)
    max_retries_general: int = int(NUMERIC_SETTING_SPECS["max_retries_general"].default)
    max_retries_rate_limit: int = int(NUMERIC_SETTING_SPECS["max_retries_rate_limit"].default)
    max_retries_format: int = int(NUMERIC_SETTING_SPECS["max_retries_format"].default)
    target_language: str = DEFAULT_TARGET_LANGUAGE
    recent_target_languages: list[str] = field(default_factory=lambda: list(DEFAULT_RECENT_TARGET_LANGUAGES))
    source_language: Optional[str] = None
    translation_options: TranslationOptions = field(default_factory=TranslationOptions)
    auto_check_updates: bool = True
    skipped_update_version: str = ""

    def apply_rate_limit_preset(self, preset_name: str) -> None:
        """Applies a named rate-limit & batching preset to this config."""
        preset = RATE_LIMIT_PRESETS.get(preset_name)
        if not preset:
            return
        self.rate_limit_preset = preset_name
        self.max_concurrent_requests = int(preset["max_concurrent_requests"])
        self.min_request_interval = float(preset["min_request_interval"])
        self.rpm_limit = int(preset["rpm_limit"])
        self.tpm_limit = int(preset["tpm_limit"])
        self.batch_size = int(preset["batch_size"])
        self.batch_max_chars = int(preset["batch_max_chars"])
        self.section_max_chars = int(preset["section_max_chars"])
        self.max_retries_rate_limit = int(preset["max_retries_rate_limit"])

    def _matches_preset_values(self, preset: Dict[str, Union[int, float]]) -> bool:
        """Checks whether current rate-limit and batching parameters match a preset map."""
        return (
            int(self.max_concurrent_requests) == int(preset["max_concurrent_requests"])
            and abs(float(self.min_request_interval) - float(preset["min_request_interval"])) < 1e-6
            and int(self.rpm_limit) == int(preset["rpm_limit"])
            and int(self.tpm_limit) == int(preset["tpm_limit"])
            and int(self.batch_size) == int(preset["batch_size"])
            and int(self.batch_max_chars) == int(preset["batch_max_chars"])
            and int(self.section_max_chars) == int(preset["section_max_chars"])
            and int(self.max_retries_rate_limit) == int(preset["max_retries_rate_limit"])
        )

    def detect_rate_limit_preset(self) -> str:
        """Returns matching preset name if settings align with a preset, else 'custom'."""
        for name, preset in RATE_LIMIT_PRESETS.items():
            if self._matches_preset_values(preset):
                return name
        return "custom"

    def record_recent_target_language(self, lang_name: str) -> None:
        """Adds a language to the top of recent_target_languages (MRU)."""
        norm = normalize_language_name(lang_name)
        # Deduplicate while preserving order
        self.recent_target_languages = [l for l in self.recent_target_languages if l != norm]
        self.recent_target_languages.insert(0, norm)
        self.recent_target_languages = self.recent_target_languages[:MAX_RECENT_TARGET_LANGUAGES]

    def get_effective_api_key(self, provider: Optional[str] = None) -> str:
        """Returns the active API key with dynamic fallback to env vars."""
        target_provider = provider or self.active_provider
        user_key = (self.api_keys.get(target_provider) or "").strip()
        if user_key:
            return user_key

        # Fallback to environment variable dynamically so rotations/unsets take effect
        env_var = AI_PROVIDERS.get(target_provider, {}).get("env_key")
        if env_var:
            env_val = os.getenv(env_var)
            if env_val is not None:
                return env_val.strip()

        return ""

    def get_effective_base_url(self, provider: Optional[str] = None) -> str:
        """Returns the configured custom base URL for provider, or falls back to env var."""
        target_provider = provider or self.active_provider
        user_url = (self.base_urls.get(target_provider) or "").strip()
        if user_url:
            return user_url

        env_var = AI_PROVIDERS.get(target_provider, {}).get("env_base_url_key")
        if env_var:
            env_val = os.getenv(env_var)
            if env_val is not None:
                return env_val.strip()

        return ""

    def get_active_model(self) -> str:
        """Returns the explicitly selected model for the active provider, or '' if unset."""
        return (self.selected_models.get(self.active_provider) or "").strip()

    def get_available_models(self, provider: Optional[str] = None) -> list[str]:
        """Returns cached/fresh available models for the given or active provider."""
        from rakutrans.llm.model_fetcher import load_cached_models
        prov = provider or self.active_provider
        return load_cached_models(prov)

    def save(self) -> None:
        """Save settings atomically and thread-safely to disk."""
        tmp_path: Optional[Path] = None
        try:
            with _CONFIG_IO_LOCK:
                cfg_file = _resolve_config_file()
                cfg_file.parent.mkdir(parents=True, exist_ok=True)
                self.rate_limit_preset = self.detect_rate_limit_preset()
                data = {
                    "ui_language": self.ui_language,
                    "theme_mode": self.theme_mode,
                    "active_provider": self.active_provider,
                    "api_keys": {
                        prov: str(self.api_keys.get(prov) or "")
                        for prov in AI_PROVIDERS
                    },
                    "base_urls": {
                        prov: str(self.base_urls.get(prov) or "")
                        for prov in AI_PROVIDERS
                    },
                    "selected_models": {
                        prov: str(self.selected_models.get(prov) or "")
                        for prov in AI_PROVIDERS
                    },
                    "temperature": self.temperature,
                    "strict_json_mode": bool(self.strict_json_mode),
                    "request_timeout": float(self.request_timeout),
                    "model_fetch_timeout": float(self.model_fetch_timeout),
                    "rate_limit_preset": str(self.rate_limit_preset or "custom"),
                    "batch_size": self.batch_size,
                    "batch_max_chars": self.batch_max_chars,
                    "section_max_chars": self.section_max_chars,
                    "max_concurrent_requests": self.max_concurrent_requests,
                    "min_request_interval": float(self.min_request_interval),
                    "rpm_limit": int(self.rpm_limit),
                    "tpm_limit": int(self.tpm_limit),
                    "max_retries_general": self.max_retries_general,
                    "max_retries_rate_limit": self.max_retries_rate_limit,
                    "max_retries_format": self.max_retries_format,
                    "target_language": self.target_language,
                    "recent_target_languages": self.recent_target_languages,
                    "translation_options": asdict(self.translation_options),
                    "auto_check_updates": bool(self.auto_check_updates),
                    "skipped_update_version": str(self.skipped_update_version or "").strip(),
                }
                if self.source_language:
                    data["source_language"] = self.source_language

                fd, tmp_name = tempfile.mkstemp(
                    prefix=".config_",
                    suffix=".tmp",
                    dir=str(cfg_file.parent),
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
                os.replace(str(tmp_path), str(cfg_file))
                tmp_path = None
        except Exception as e:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            print(f"[Warning] Failed to save config: {e}")

    @classmethod
    def load(cls) -> "AppConfig":
        """Load settings from disk or return default config."""
        with _CONFIG_IO_LOCK:
            cfg_file = _resolve_config_file()
            if not cfg_file.exists():
                config = cls()
                config.save()
                return config

            try:
                with open(cfg_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    return cls()

                raw_options = data.get("translation_options", {})
                if not isinstance(raw_options, dict):
                    raw_options = {}
                options = TranslationOptions(
                    keep_it_terms=bool(raw_options.get("keep_it_terms", True)),
                    append_original_words=bool(raw_options.get("append_original_words", False)),
                    custom_context=str(raw_options.get("custom_context", "") or ""),
                    bilingual_mode=bool(raw_options.get("bilingual_mode", False)),
                )

                loaded_models = data.get("selected_models", {})
                if not isinstance(loaded_models, dict):
                    loaded_models = {}
                resolved_models = {
                    prov: str(loaded_models.get(prov) or "").strip()
                    for prov in AI_PROVIDERS
                }

                loaded_keys = data.get("api_keys", {})
                if not isinstance(loaded_keys, dict):
                    loaded_keys = {}
                resolved_keys = {
                    prov: str(loaded_keys.get(prov) or "").strip()
                    for prov in AI_PROVIDERS
                }

                loaded_base_urls = data.get("base_urls", {})
                if not isinstance(loaded_base_urls, dict):
                    loaded_base_urls = {}
                resolved_base_urls = {
                    prov: str(loaded_base_urls.get(prov) or "").strip()
                    for prov in AI_PROVIDERS
                }

                raw_provider = str(data.get("active_provider", DEFAULT_ACTIVE_PROVIDER) or DEFAULT_ACTIVE_PROVIDER)
                active_provider = raw_provider if raw_provider in AI_PROVIDERS else DEFAULT_ACTIVE_PROVIDER

                raw_ui_lang = str(data.get("ui_language", DEFAULT_UI_LANGUAGE) or DEFAULT_UI_LANGUAGE)
                ui_language = raw_ui_lang if raw_ui_lang in UI_LANGUAGES else DEFAULT_UI_LANGUAGE

                raw_theme = str(data.get("theme_mode", DEFAULT_THEME_MODE) or DEFAULT_THEME_MODE).lower()
                theme_mode = raw_theme if raw_theme in THEME_MODES else DEFAULT_THEME_MODE

                temperature = coerce_setting_value("temperature", data.get("temperature"))
                raw_strict_json = data.get("strict_json_mode", True)
                strict_json_mode = raw_strict_json if isinstance(raw_strict_json, bool) else True
                request_timeout = float(coerce_setting_value("request_timeout", data.get("request_timeout")))
                model_fetch_timeout = float(coerce_setting_value("model_fetch_timeout", data.get("model_fetch_timeout")))

                batch_size = int(coerce_setting_value("batch_size", data.get("batch_size")))
                batch_max_chars = int(coerce_setting_value("batch_max_chars", data.get("batch_max_chars")))
                section_max_chars = int(coerce_setting_value("section_max_chars", data.get("section_max_chars")))
                max_concurrent_requests = int(coerce_setting_value("max_concurrent_requests", data.get("max_concurrent_requests")))
                min_request_interval = float(coerce_setting_value("min_request_interval", data.get("min_request_interval")))
                rpm_limit = int(coerce_setting_value("rpm_limit", data.get("rpm_limit")))
                tpm_limit = int(coerce_setting_value("tpm_limit", data.get("tpm_limit")))
                max_retries_general = int(coerce_setting_value("max_retries_general", data.get("max_retries_general")))
                max_retries_rate_limit = int(coerce_setting_value("max_retries_rate_limit", data.get("max_retries_rate_limit")))
                max_retries_format = int(coerce_setting_value("max_retries_format", data.get("max_retries_format")))

                raw_target = data.get("target_language", DEFAULT_TARGET_LANGUAGE)
                normalized_target = normalize_language_name(
                    raw_target if isinstance(raw_target, str) else DEFAULT_TARGET_LANGUAGE
                )

                raw_recents = data.get("recent_target_languages")
                if raw_recents and isinstance(raw_recents, list):
                    recents = []
                    for r in raw_recents:
                        norm = normalize_language_name(str(r))
                        if norm not in recents:
                            recents.append(norm)
                    recents = recents[:MAX_RECENT_TARGET_LANGUAGES]
                else:
                    recents = list(DEFAULT_RECENT_TARGET_LANGUAGES)

                # Ensure the active target language is at the top of recent list
                if normalized_target not in recents:
                    recents.insert(0, normalized_target)
                    recents = recents[:MAX_RECENT_TARGET_LANGUAGES]

                raw_source = data.get("source_language", None)
                source_language = str(raw_source).strip() if isinstance(raw_source, str) and raw_source.strip() else None

                raw_auto_update = data.get("auto_check_updates", True)
                auto_check_updates = raw_auto_update if isinstance(raw_auto_update, bool) else True

                raw_skipped = data.get("skipped_update_version", "")
                skipped_update_version = raw_skipped.strip() if isinstance(raw_skipped, str) else ""

                raw_preset = str(data.get("rate_limit_preset", "") or "").strip()
                valid_presets = set(RATE_LIMIT_PRESETS.keys()) | {"custom"}

                config = cls(
                    ui_language=ui_language,
                    theme_mode=theme_mode,
                    active_provider=active_provider,
                    api_keys=resolved_keys,
                    base_urls=resolved_base_urls,
                    selected_models=resolved_models,
                    temperature=temperature,
                    strict_json_mode=strict_json_mode,
                    request_timeout=request_timeout,
                    model_fetch_timeout=model_fetch_timeout,
                    rate_limit_preset=raw_preset if raw_preset in valid_presets else DEFAULT_RATE_LIMIT_PRESET,
                    batch_size=batch_size,
                    batch_max_chars=batch_max_chars,
                    section_max_chars=section_max_chars,
                    max_concurrent_requests=max_concurrent_requests,
                    min_request_interval=min_request_interval,
                    rpm_limit=rpm_limit,
                    tpm_limit=tpm_limit,
                    max_retries_general=max_retries_general,
                    max_retries_rate_limit=max_retries_rate_limit,
                    max_retries_format=max_retries_format,
                    target_language=normalized_target,
                    recent_target_languages=recents,
                    source_language=source_language,
                    translation_options=options,
                    auto_check_updates=auto_check_updates,
                    skipped_update_version=skipped_update_version,
                )
                # Silently migrate unmodified legacy built-in presets to optimized defaults
                upgrade_candidate = raw_preset if raw_preset in _LEGACY_RATE_LIMIT_PRESETS else (
                    DEFAULT_RATE_LIMIT_PRESET if not raw_preset else ""
                )
                if upgrade_candidate and config.detect_rate_limit_preset() == "custom":
                    legacy_snapshots = (
                        _LEGACY_RATE_LIMIT_PRESETS.get(upgrade_candidate),
                        _PREVIOUS_RATE_LIMIT_PRESETS.get(upgrade_candidate),
                    )
                    if any(snap and config._matches_preset_values(snap) for snap in legacy_snapshots):
                        config.apply_rate_limit_preset(upgrade_candidate)
                config.rate_limit_preset = config.detect_rate_limit_preset()
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
        if counter > SAFE_OUTPUT_PATH_MAX_ATTEMPTS:
            return parent / f"{base_stem} ({uuid.uuid4().hex[:8]}){suffix}"


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
    suffix = (target_format if target_format else src.suffix).strip()
    if suffix and not suffix.startswith("."):
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
