"""
In-page Settings View and Settings Modal for RakuTrans AI.
Enables AI Provider selection, model switching, secure API key configuration,
appearance customization, and links to provider key generation pages.
Supports both seamless in-page transition (no popup) and standalone modal.
All settings changes take effect immediately and persist automatically.
"""

import math
import threading
import time
import webbrowser
from typing import Callable, Optional
import customtkinter as ctk

from rakutrans.core.config import (
    AI_PROVIDERS,
    APP_VERSION,
    AppConfig,
    DEFAULT_RATE_LIMIT_PRESET,
    DEFAULT_UI_LANGUAGE,
    NUMERIC_SETTING_SPECS,
    RATE_LIMIT_PRESETS,
    THEME_MODES,
    UI_LANGUAGES,
    coerce_setting_value,
)
from rakutrans.llm.model_fetcher import fetch_models_async
from rakutrans.core.update_checker import UpdateCheckResult, UpdateInfo, check_for_updates_async
from rakutrans.ui.components.ui_system import COLORS, CustomButton, CustomSegmentedButton, UI_TIMING
from rakutrans.ui.components.icons import get_icon, get_provider_icon_name
from rakutrans.ui.components.update_modal import UpdateModal

_ADV_NUMERIC_BINDINGS = (
    ("temperature_var", "temperature"),
    ("request_timeout_var", "request_timeout"),
    ("batch_size_var", "batch_size"),
    ("max_concurrent_var", "max_concurrent_requests"),
    ("batch_max_chars_var", "batch_max_chars"),
    ("section_max_chars_var", "section_max_chars"),
    ("min_interval_var", "min_request_interval"),
    ("rate_retries_var", "max_retries_rate_limit"),
    ("rpm_limit_var", "rpm_limit"),
    ("tpm_limit_var", "tpm_limit"),
)

_ADV_FIELD_LABEL_KEYS = {
    "temperature": "temperature_label",
    "request_timeout": "request_timeout_label",
    "batch_size": "batch_size_label",
    "max_concurrent_requests": "max_concurrent_label",
    "batch_max_chars": "batch_max_chars_label",
    "section_max_chars": "section_max_chars_label",
    "min_request_interval": "min_interval_label",
    "max_retries_rate_limit": "rate_retries_label",
    "rpm_limit": "rpm_limit_label",
    "tpm_limit": "tpm_limit_label",
}


class SettingsView(ctk.CTkFrame):
    """
    In-page Settings View for RakuTrans AI.
    Replaces popup dialogs by transitioning smoothly on the main window directly below the header.
    Settings changes take effect directly in real-time.
    """

    def __init__(
        self,
        master,
        config: AppConfig,
        get_translation: Callable[[str], str],
        on_save_callback: Callable[[AppConfig], None],
        on_close_callback: Callable[[], None],
        on_update_found: Optional[Callable[[UpdateInfo], None]] = None,
        **kwargs
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self.t = get_translation
        self.on_save = on_save_callback
        self.on_close = on_close_callback
        self.on_update_found = on_update_found
        self._show_key = False
        self.key_var: Optional[ctk.StringVar] = None
        self.model_var: Optional[ctk.StringVar] = None
        self._suppress_key_trace = False
        self._key_save_pending = False
        self._key_save_after_id = None
        self._fetch_after_id = None
        self._fetch_request_id = 0
        self._test_conn_request_id = 0
        self._update_check_request_id = 0
        self._latest_update_info: Optional[UpdateInfo] = None
        self._update_status_state: Optional[str] = None
        self._update_status_error: str = ""
        self._has_auto_fetched_on_open = False
        self._advanced_expanded = False
        self._suppress_adv_trace = False
        self._adv_save_pending = False
        self._adv_numeric_dirty = False
        self._adv_save_after_id = None
        self._manual_custom_mode = False
        self._adv_status_state: Optional[str] = None
        self._adv_status_details: str = ""

        self._setup_ui()

    def _get_guide_text(self, provider: str) -> str:
        guide_key = AI_PROVIDERS.get(provider, {}).get("guide_key", "")
        return self.t(guide_key) if guide_key else ""

    def _get_theme_display_names(self) -> list[str]:
        return [self.t(f"theme_{mode}") for mode in THEME_MODES]

    def _get_current_theme_display(self) -> str:
        mode = (self.config.theme_mode or "").lower()
        resolved = mode if mode in THEME_MODES else THEME_MODES[-1]
        return self.t(f"theme_{resolved}")

    def _setup_ui(self):
        # --------------------------------------------------------------------
        # Pinned Header with Title
        # --------------------------------------------------------------------
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(fill="x", padx=20, pady=(14, 8))

        self.title_label = ctk.CTkLabel(
            self.header_frame,
            text="  " + self.t("settings_title"),
            image=get_icon("settings", "default", 18),
            compound="left",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        self.title_label.pack(side="left")

        # --------------------------------------------------------------------
        # Middle Scrollable Content Container (takes full height)
        # --------------------------------------------------------------------
        self.container = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=20, pady=(4, 8))

        # --------------------------------------------------------------------
        # 1. AI Provider Selection
        # --------------------------------------------------------------------
        self.provider_group = ctk.CTkFrame(self.container, fg_color="transparent")
        self.provider_group.pack(fill="x", pady=(0, 15), padx=2)

        self.active_prov_label = ctk.CTkLabel(
            self.provider_group,
            text=self.t("active_provider"),
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.active_prov_label.pack(anchor="w", padx=4, pady=(12, 6))

        self.provider_var = ctk.StringVar(value=self.config.active_provider)
        providers_list = list(AI_PROVIDERS.keys())
        self.provider_selector = CustomSegmentedButton(
            self.provider_group,
            values=providers_list,
            variable=self.provider_var,
            command=self._on_provider_changed,
            height=35,
            border_width=1,
        )
        for i in range(len(providers_list)):
            self.provider_selector.grid_columnconfigure(i, weight=1, uniform="prov_tabs")
        self._apply_provider_icons()
        self.provider_selector.pack(fill="x", padx=4, pady=(0, 12))

        # --------------------------------------------------------------------
        # 2. Model Selection
        # --------------------------------------------------------------------
        self.model_group = ctk.CTkFrame(self.container, fg_color="transparent")
        self.model_group.pack(fill="x", pady=(0, 15), padx=2)

        self.model_label_elem = ctk.CTkLabel(
            self.model_group,
            text=self.t("model_label"),
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.model_label_elem.pack(anchor="w", padx=4, pady=(12, 6))

        current_prov = self.config.active_provider
        available_models = self.config.get_available_models(current_prov)
        active_model = self.config.get_active_model()
        self.model_var = ctk.StringVar(value=active_model)

        model_row = ctk.CTkFrame(self.model_group, fg_color="transparent")
        model_row.pack(fill="x", padx=4, pady=(0, 4))

        self.model_combo = ctk.CTkOptionMenu(
            model_row,
            values=[],
            variable=self.model_var,
            command=self._on_model_changed,
            height=34,
            dynamic_resizing=False,
            fg_color=("#FFFFFF", "#18181B"),
            button_color=("#E4E4E7", "#27272A"),
            button_hover_color=("#D4D4D8", "#3F3F46"),
            text_color=("#18181B", "#FAFAFA"),
            dropdown_fg_color=("#FFFFFF", "#18181B"),
            dropdown_hover_color=("#F4F4F5", "#27272A"),
            dropdown_text_color=("#18181B", "#FAFAFA")
        )
        self._apply_model_options(available_models, active_model)
        self.model_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.fetch_btn = CustomButton(
            model_row,
            text=self.t("fetch_models"),
            variant="secondary",
            size="md",
            width=128,
            icon_name="refresh",
            icon_size=15,
            command=self._fetch_live_models
        )
        self.fetch_btn.pack(side="right")

        self.model_hint_label = ctk.CTkLabel(
            self.model_group,
            text=self.t("model_hint"),
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=520,
            justify="left"
        )
        self.model_hint_label.pack(anchor="w", padx=4, pady=(0, 12))

        # --------------------------------------------------------------------
        # 3. API Key & Provider Guide
        # --------------------------------------------------------------------
        self.key_group = ctk.CTkFrame(self.container, fg_color="transparent")
        self.key_group.pack(fill="x", pady=(0, 15), padx=2)

        self.api_key_label_elem = ctk.CTkLabel(
            self.key_group,
            text=self.t("api_key_label"),
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.api_key_label_elem.pack(anchor="w", padx=4, pady=(12, 4))

        entry_frame = ctk.CTkFrame(self.key_group, fg_color="transparent")
        entry_frame.pack(fill="x", padx=4, pady=(0, 8))

        self.key_var = ctk.StringVar(value=self.config.api_keys.get(current_prov, ""))
        self.key_var.trace_add("write", self._on_key_changed)

        self.key_entry = ctk.CTkEntry(
            entry_frame,
            textvariable=self.key_var,
            placeholder_text=self.t("api_key_placeholder"),
            show="*",
            height=34,
            fg_color=("#FFFFFF", "#18181B"),
            border_color=("#E4E4E7", "#27272A"),
            text_color=("#18181B", "#FAFAFA")
        )
        self.key_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.key_entry.bind("<FocusOut>", self._on_key_focus_out)

        self.toggle_btn = CustomButton(
            entry_frame,
            text="",
            variant="outline",
            size="md",
            width=40,
            icon_name="eye",
            icon_size=16,
            command=self._toggle_key_visibility
        )
        self.toggle_btn.pack(side="right")

        test_row = ctk.CTkFrame(self.key_group, fg_color="transparent")
        test_row.pack(fill="x", padx=4, pady=(0, 10))

        self.test_conn_btn = CustomButton(
            test_row,
            text=self.t("test_connection"),
            variant="secondary",
            size="md",
            width=155,
            icon_name="zap",
            icon_size=15,
            command=self._test_api_connection
        )
        self.test_conn_btn.pack(side="left")

        self.test_conn_status = ctk.CTkLabel(
            test_row,
            text="",
            font=ctk.CTkFont(size=11),
            anchor="w",
            wraplength=400,
            justify="left"
        )
        self.test_conn_status.pack(side="left", padx=(10, 0), fill="x", expand=True)

        self.guide_box = ctk.CTkFrame(
            self.key_group,
            fg_color=("#F4F4F5", "#18181B"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            corner_radius=8
        )
        self.guide_box.pack(fill="x", padx=4, pady=(4, 15))

        self.guide_text_label = ctk.CTkLabel(
            self.guide_box,
            text=self._get_guide_text(current_prov),
            font=ctk.CTkFont(size=12),
            wraplength=480,
            justify="left"
        )
        self.guide_text_label.pack(anchor="w", padx=12, pady=(8, 4))

        self.guide_link_btn = CustomButton(
            self.guide_box,
            text=self.t("open_api_guide"),
            variant="ghost",
            size="sm",
            command=self._open_provider_guide
        )
        self.guide_link_btn.pack(anchor="w", padx=12, pady=(0, 8))

        # --------------------------------------------------------------------
        # 4. Appearance & Preferences
        # --------------------------------------------------------------------
        pref_group = ctk.CTkFrame(self.container, fg_color="transparent")
        pref_group.pack(fill="x", pady=(0, 15), padx=2)

        self.pref_label_elem = ctk.CTkLabel(
            pref_group,
            text=self.t("preferences_title"),
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.pref_label_elem.pack(anchor="w", padx=4, pady=(12, 6))

        pref_grid = ctk.CTkFrame(pref_group, fg_color="transparent")
        pref_grid.pack(fill="x", padx=4, pady=(0, 15))
        pref_grid.grid_columnconfigure((0, 1), weight=1)

        self.ui_lang_label_elem = ctk.CTkLabel(
            pref_grid,
            text=self.t("ui_language"),
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.ui_lang_label_elem.grid(row=0, column=0, sticky="w", pady=(0, 4))

        lang_codes = list(UI_LANGUAGES.keys())
        lang_names = [UI_LANGUAGES[c] for c in lang_codes]
        current_lang_name = UI_LANGUAGES.get(
            self.config.ui_language, UI_LANGUAGES[DEFAULT_UI_LANGUAGE]
        )

        self.lang_var = ctk.StringVar(value=current_lang_name)
        self.lang_dropdown = ctk.CTkOptionMenu(
            pref_grid,
            values=lang_names,
            variable=self.lang_var,
            command=self._on_language_changed,
            height=32,
            fg_color=("#FFFFFF", "#18181B"),
            button_color=("#E4E4E7", "#27272A"),
            button_hover_color=("#D4D4D8", "#3F3F46"),
            text_color=("#18181B", "#FAFAFA"),
            dropdown_fg_color=("#FFFFFF", "#18181B"),
            dropdown_hover_color=("#F4F4F5", "#27272A"),
            dropdown_text_color=("#18181B", "#FAFAFA")
        )
        self.lang_dropdown.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        self.theme_label_elem = ctk.CTkLabel(
            pref_grid,
            text=self.t("theme_mode"),
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.theme_label_elem.grid(row=0, column=1, sticky="w", pady=(0, 4))

        self.theme_var = ctk.StringVar(value=self._get_current_theme_display())
        self.theme_dropdown = ctk.CTkOptionMenu(
            pref_grid,
            values=self._get_theme_display_names(),
            variable=self.theme_var,
            command=self._on_theme_changed,
            height=32,
            fg_color=("#FFFFFF", "#18181B"),
            button_color=("#E4E4E7", "#27272A"),
            button_hover_color=("#D4D4D8", "#3F3F46"),
            text_color=("#18181B", "#FAFAFA"),
            dropdown_fg_color=("#FFFFFF", "#18181B"),
            dropdown_hover_color=("#F4F4F5", "#27272A"),
            dropdown_text_color=("#18181B", "#FAFAFA")
        )
        self.theme_dropdown.grid(row=1, column=1, sticky="ew", padx=(8, 0))

        # --------------------------------------------------------------------
        # 5. Translation Speed & Rate-Limit Mode (Always visible)
        # --------------------------------------------------------------------
        self.speed_group = ctk.CTkFrame(self.container, fg_color="transparent")
        self.speed_group.pack(fill="x", pady=(0, 8), padx=2)

        self.speed_section_label = ctk.CTkLabel(
            self.speed_group,
            text=self.t("speed_section_title"),
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
        )
        self.speed_section_label.pack(anchor="w", padx=4, pady=(8, 6))

        self.speed_card = ctk.CTkFrame(
            self.speed_group,
            fg_color=("#F4F4F5", "#18181B"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            corner_radius=8,
        )
        self.speed_card.pack(fill="x", padx=4, pady=(0, 4))

        self.rate_profile_label = ctk.CTkLabel(
            self.speed_card,
            text=self.t("rate_profile_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.rate_profile_label.pack(anchor="w", padx=14, pady=(10, 4))

        self.rate_profile_var = ctk.StringVar(value=self._get_rate_profile_display())
        self.rate_profile_dropdown = ctk.CTkOptionMenu(
            self.speed_card,
            values=self._get_rate_profile_display_names(),
            variable=self.rate_profile_var,
            command=self._on_rate_profile_changed,
            height=32,
            fg_color=("#FFFFFF", "#09090B"),
            button_color=("#E4E4E7", "#27272A"),
            button_hover_color=("#D4D4D8", "#3F3F46"),
            text_color=("#18181B", "#FAFAFA"),
            dropdown_fg_color=("#FFFFFF", "#18181B"),
            dropdown_hover_color=("#F4F4F5", "#27272A"),
            dropdown_text_color=("#18181B", "#FAFAFA")
        )
        self.rate_profile_dropdown.pack(fill="x", padx=14, pady=(0, 6))

        self.rate_profile_summary_label = ctk.CTkLabel(
            self.speed_card,
            text=self._get_rate_profile_summary_text(),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_body"],
            wraplength=600,
            justify="left",
            anchor="w",
        )
        self.rate_profile_summary_label.pack(fill="x", padx=14, pady=(0, 2))

        self.rate_profile_hint_label = ctk.CTkLabel(
            self.speed_card,
            text=self.t("rate_profile_hint"),
            font=ctk.CTkFont(size=11),
            text_color=("#71717A", "#A1A1AA"),
            wraplength=600,
            justify="left",
            anchor="w",
        )
        self.rate_profile_hint_label.pack(fill="x", padx=14, pady=(0, 10))

        # --------------------------------------------------------------------
        # 6. Fine-Tuning & Custom Server (Collapsible)
        # --------------------------------------------------------------------
        self.advanced_group = ctk.CTkFrame(self.container, fg_color="transparent")
        self.advanced_group.pack(fill="x", pady=(0, 12), padx=2)

        adv_header_row = ctk.CTkFrame(self.advanced_group, fg_color="transparent")
        adv_header_row.pack(fill="x", padx=2, pady=(2, 4))

        self.advanced_toggle_btn = ctk.CTkButton(
            adv_header_row,
            text=self.t("advanced_toggle_show"),
            command=self._toggle_advanced_section,
            fg_color="transparent",
            hover_color=("#F4F4F5", "#27272A"),
            text_color=("#3F3F46", "#D4D4D8"),
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=30,
        )
        self.advanced_toggle_btn.pack(side="left", fill="x", expand=True)

        self.advanced_card = ctk.CTkFrame(
            self.advanced_group,
            fg_color=("#F4F4F5", "#18181B"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            corner_radius=8
        )
        # Collapsed by default; shown on demand via _toggle_advanced_section()

        adv_top_row = ctk.CTkFrame(self.advanced_card, fg_color="transparent")
        adv_top_row.pack(fill="x", padx=14, pady=(12, 6))

        self.advanced_intro_label = ctk.CTkLabel(
            adv_top_row,
            text=self.t("advanced_intro_note"),
            font=ctk.CTkFont(size=11),
            text_color=("#71717A", "#A1A1AA"),
            wraplength=460,
            justify="left",
            anchor="w",
        )
        self.advanced_intro_label.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.reset_adv_btn = CustomButton(
            adv_top_row,
            text=self.t("adv_reset_defaults_btn"),
            variant="outline",
            size="sm",
            icon_name="rotate_ccw",
            icon_size=13,
            command=self._reset_advanced_defaults,
        )
        self.reset_adv_btn.pack(side="right")

        self.adv_status_slot = ctk.CTkFrame(self.advanced_card, fg_color="transparent", height=0)
        self.adv_status_slot.pack(fill="x", padx=14, pady=(0, 4))
        self.adv_status_label = ctk.CTkLabel(
            self.adv_status_slot,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["success"],
            wraplength=580,
            justify="left",
            anchor="w",
        )

        self.temperature_var = ctk.StringVar(
            value="" if self.config.temperature is None else f"{self.config.temperature:g}"
        )
        self.request_timeout_var = ctk.StringVar(
            value=f"{self.config.request_timeout:g}"
        )
        self.batch_size_var = ctk.StringVar(value=str(self.config.batch_size))
        self.max_concurrent_var = ctk.StringVar(
            value=str(self.config.max_concurrent_requests)
        )
        self.batch_max_chars_var = ctk.StringVar(value=str(self.config.batch_max_chars))
        self.section_max_chars_var = ctk.StringVar(value=str(self.config.section_max_chars))
        self.min_interval_var = ctk.StringVar(value=f"{self.config.min_request_interval:g}")
        self.rate_retries_var = ctk.StringVar(value=str(self.config.max_retries_rate_limit))
        self.rpm_limit_var = ctk.StringVar(value=str(self.config.rpm_limit))
        self.tpm_limit_var = ctk.StringVar(value=str(self.config.tpm_limit))
        for var_attr, _cfg_field in _ADV_NUMERIC_BINDINGS:
            tk_var = getattr(self, var_attr)
            tk_var.trace_add("write", self._on_adv_numeric_var_changed)

        # --- Sub-group 1: AI Connection & Output ---
        self._add_adv_section_header(self.advanced_card, "adv_group_connection")

        self.base_url_label = ctk.CTkLabel(
            self.advanced_card,
            text=self._get_base_url_label_text(current_prov),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        self.base_url_label.pack(anchor="w", padx=14, pady=(4, 2))

        self.base_url_hint = ctk.CTkLabel(
            self.advanced_card,
            text=self.t("base_url_hint"),
            font=ctk.CTkFont(size=11),
            text_color=("#71717A", "#A1A1AA"),
            wraplength=600,
            justify="left",
            anchor="w",
        )
        self.base_url_hint.pack(fill="x", padx=14, pady=(0, 4))

        self.base_url_var = ctk.StringVar(
            value=self.config.base_urls.get(current_prov, "")
        )
        self.base_url_var.trace_add("write", self._on_base_url_changed)
        self.base_url_entry = ctk.CTkEntry(
            self.advanced_card,
            textvariable=self.base_url_var,
            placeholder_text=self.t("base_url_placeholder"),
            height=32,
            fg_color=("#FFFFFF", "#09090B"),
            border_color=("#D4D4D8", "#3F3F46"),
        )
        self.base_url_entry.pack(fill="x", padx=14, pady=(0, 10))
        self.base_url_entry.bind("<FocusOut>", lambda _e: self._commit_advanced_settings())
        self.base_url_entry.bind("<Return>", lambda _e: self._commit_advanced_settings())

        self._add_adv_setting_row(
            self.advanced_card,
            "temperature_label",
            "temperature_hint",
            self.temperature_var,
            "temperature_entry",
            placeholder_key="temperature_placeholder",
        )
        self._add_adv_setting_row(
            self.advanced_card,
            "request_timeout_label",
            "request_timeout_hint",
            self.request_timeout_var,
            "request_timeout_entry",
        )

        self.strict_json_var = ctk.BooleanVar(value=bool(self.config.strict_json_mode))
        self.strict_json_cb = ctk.CTkCheckBox(
            self.advanced_card,
            text=self.t("strict_json_mode_label"),
            variable=self.strict_json_var,
            command=self._on_strict_json_toggled,
            font=ctk.CTkFont(size=12, weight="bold"),
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            border_width=2,
            fg_color=("#18181B", "#FAFAFA"),
            hover_color=("#27272A", "#E4E4E7"),
            checkmark_color=("#FFFFFF", "#18181B"),
            border_color=("#D4D4D8", "#52525B")
        )
        self.strict_json_cb.pack(anchor="w", padx=14, pady=(4, 2))

        self.strict_json_mode_hint = ctk.CTkLabel(
            self.advanced_card,
            text=self.t("strict_json_mode_hint"),
            font=ctk.CTkFont(size=11),
            text_color=("#71717A", "#A1A1AA"),
            wraplength=580,
            justify="left",
            anchor="w",
        )
        self.strict_json_mode_hint.pack(fill="x", padx=(40, 14), pady=(0, 10))

        # --- Sub-group 2: How Documents Are Split ---
        self._add_adv_section_header(self.advanced_card, "adv_group_batching")

        for label_key, hint_key, str_var, entry_attr in (
            ("batch_size_label", "batch_size_hint", self.batch_size_var, "batch_size_entry"),
            ("batch_max_chars_label", "batch_max_chars_hint", self.batch_max_chars_var, "batch_max_chars_entry"),
            ("section_max_chars_label", "section_max_chars_hint", self.section_max_chars_var, "section_max_chars_entry"),
        ):
            self._add_adv_setting_row(
                self.advanced_card, label_key, hint_key, str_var, entry_attr
            )

        # --- Sub-group 3: Speed & Rate-Limit Protection ---
        self._add_adv_section_header(self.advanced_card, "adv_group_ratelimit")

        for label_key, hint_key, str_var, entry_attr in (
            ("max_concurrent_label", "max_concurrent_hint", self.max_concurrent_var, "max_concurrent_entry"),
            ("min_interval_label", "min_interval_hint", self.min_interval_var, "min_interval_entry"),
            ("rate_retries_label", "rate_retries_hint", self.rate_retries_var, "rate_retries_entry"),
            ("rpm_limit_label", "rpm_limit_hint", self.rpm_limit_var, "rpm_limit_entry"),
            ("tpm_limit_label", "tpm_limit_hint", self.tpm_limit_var, "tpm_limit_entry"),
        ):
            self._add_adv_setting_row(
                self.advanced_card, label_key, hint_key, str_var, entry_attr
            )

        # Bottom breathing space inside advanced card
        ctk.CTkFrame(self.advanced_card, height=4, fg_color="transparent").pack(fill="x")

        # --------------------------------------------------------------------
        # 5. Application Version & Updates
        # --------------------------------------------------------------------
        self.updates_group = ctk.CTkFrame(self.container, fg_color="transparent")
        self.updates_group.pack(fill="x", pady=(0, 15), padx=2)

        self.updates_title_label = ctk.CTkLabel(
            self.updates_group,
            text=self.t("updates_section_title"),
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.updates_title_label.pack(anchor="w", padx=4, pady=(8, 6))

        updates_card = ctk.CTkFrame(
            self.updates_group,
            fg_color=("#F4F4F5", "#18181B"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            corner_radius=8
        )
        updates_card.pack(fill="x", padx=4, pady=(0, 8))

        updates_top_row = ctk.CTkFrame(updates_card, fg_color="transparent")
        updates_top_row.pack(fill="x", padx=12, pady=(10, 6))

        self.version_label = ctk.CTkLabel(
            updates_top_row,
            text=self.t("current_version_label", version=APP_VERSION),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w"
        )
        self.version_label.pack(side="left")

        self.check_updates_btn = CustomButton(
            updates_top_row,
            text=self.t("check_updates_btn"),
            variant="secondary",
            size="sm",
            width=150,
            icon_name="refresh",
            icon_size=14,
            command=self._check_for_updates
        )
        self.check_updates_btn.pack(side="right")

        self.download_update_btn = CustomButton(
            updates_top_row,
            text=self.t("update_details_btn"),
            variant="primary",
            size="sm",
            icon_name="download",
            icon_size=14,
            command=self._open_update_modal
        )
        # Shown only when an update is available

        self.update_status_label = ctk.CTkLabel(
            updates_card,
            text="",
            font=ctk.CTkFont(size=11),
            text_color="gray",
            wraplength=500,
            justify="left",
            anchor="w"
        )
        self.update_status_label.pack(fill="x", padx=12, pady=(0, 8))

        self.auto_update_var = ctk.BooleanVar(value=self.config.auto_check_updates)
        self.auto_update_cb = ctk.CTkCheckBox(
            updates_card,
            text=self.t("auto_check_updates_label"),
            variable=self.auto_update_var,
            command=self._on_auto_update_toggled,
            font=ctk.CTkFont(size=12),
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            border_width=2,
            fg_color=("#18181B", "#FAFAFA"),
            hover_color=("#27272A", "#E4E4E7"),
            checkmark_color=("#FFFFFF", "#18181B"),
            border_color=("#D4D4D8", "#52525B")
        )
        self.auto_update_cb.pack(anchor="w", padx=12, pady=(0, 10))

    def _schedule_model_autofetch(
        self, delay_ms: int = UI_TIMING["autofetch_delay_ms"]
    ) -> None:
        if getattr(self, "_fetch_after_id", None):
            try:
                self.after_cancel(self._fetch_after_id)
            except Exception:
                pass
            self._fetch_after_id = None
        try:
            self._fetch_after_id = self.after(delay_ms, self._run_scheduled_autofetch)
        except Exception:
            self._fetch_after_id = None

    def _run_scheduled_autofetch(self) -> None:
        self._fetch_after_id = None
        try:
            if self.winfo_exists():
                self._fetch_live_models(is_manual=False)
        except Exception:
            pass

    def _apply_provider_icons(self) -> None:
        """Attaches crisp provider logo icons alongside provider names in the selector."""
        try:
            self.provider_selector.set_icons({
                prov: (get_provider_icon_name(prov), 15)
                for prov in AI_PROVIDERS
            })
        except Exception:
            pass

    def _model_placeholder_text(self) -> str:
        return self.t("select_model_placeholder")

    def _get_selected_model_value(self, provider: Optional[str] = None) -> str:
        prov = provider or self.provider_var.get()
        return (self.config.selected_models.get(prov) or "").strip()

    def _apply_model_options(self, models: list[str], selected: str) -> None:
        """Synchronizes model dropdown values and enabled state without auto-picking models."""
        clean_selected = (selected or "").strip()
        if models:
            display_values = list(models)
            if clean_selected and clean_selected not in display_values:
                display_values.insert(0, clean_selected)
            state = "normal"
        elif clean_selected:
            display_values = [clean_selected]
            state = "normal"
        else:
            display_values = []
            state = "disabled"
        self.model_combo.configure(values=display_values, state=state)
        self.model_combo.set(clean_selected if clean_selected else self._model_placeholder_text())

    def _set_key_var_silently(self, value: str) -> None:
        self._suppress_key_trace = True
        try:
            if self.key_var is not None:
                self.key_var.set(value)
        finally:
            self._suppress_key_trace = False

    def _get_base_url_label_text(self, provider: Optional[str] = None) -> str:
        prov = provider or (
            self.provider_var.get()
            if getattr(self, "provider_var", None) is not None
            else self.config.active_provider
        )
        return self.t("base_url_label_provider", provider=prov)

    def _get_rate_profile_pairs(self) -> list[tuple[str, str]]:
        return [
            (code, self.t(f"rate_profile_{code}"))
            for code in (*RATE_LIMIT_PRESETS.keys(), "custom")
        ]

    def _get_rate_profile_display_names(self) -> list[str]:
        return [label for _, label in self._get_rate_profile_pairs()]

    def _get_rate_profile_display(self) -> str:
        mapping = dict(self._get_rate_profile_pairs())
        if getattr(self, "_manual_custom_mode", False):
            return mapping["custom"]
        code = getattr(self.config, "rate_limit_preset", "") or self.config.detect_rate_limit_preset()
        return mapping.get(code, mapping["custom"])

    def _get_rate_profile_summary_text(self) -> str:
        rpm_val = int(self.config.rpm_limit)
        rpm_part = (
            self.t("rate_summary_unlimited")
            if rpm_val <= 0
            else self.t("rate_summary_rpm", rpm=rpm_val)
        )
        return self.t(
            "rate_summary_format",
            parallel=int(self.config.max_concurrent_requests),
            interval=f"{float(self.config.min_request_interval):g}",
            rpm_part=rpm_part,
            chars=f"{int(self.config.batch_max_chars):,}",
        )

    def _update_rate_profile_summary(self) -> None:
        if getattr(self, "rate_profile_summary_label", None) is not None:
            self.rate_profile_summary_label.configure(
                text=self._get_rate_profile_summary_text()
            )
        if getattr(self, "rate_profile_var", None) is not None:
            self.rate_profile_var.set(self._get_rate_profile_display())

    def _render_adv_status(self) -> None:
        if getattr(self, "adv_status_label", None) is None:
            return
        if self._adv_status_state == "reset":
            self.adv_status_label.configure(
                text=self.t("adv_reset_defaults_done"),
                text_color=COLORS["success"],
            )
            if not self.adv_status_label.winfo_manager():
                self.adv_status_label.pack(fill="x", pady=(0, 4))
        elif self._adv_status_state == "adjusted" and self._adv_status_details:
            self.adv_status_label.configure(
                text=self.t("adv_adjusted_notice", details=self._adv_status_details),
                text_color=COLORS["warning_text"],
            )
            if not self.adv_status_label.winfo_manager():
                self.adv_status_label.pack(fill="x", pady=(0, 4))
        else:
            if self.adv_status_label.winfo_manager():
                self.adv_status_label.pack_forget()
            self.adv_status_label.configure(text="")

    def _set_adv_status(self, state: Optional[str], details: str = "") -> None:
        self._adv_status_state = state
        self._adv_status_details = details
        self._render_adv_status()

    def _on_rate_profile_changed(self, chosen_label: str) -> None:
        code = "custom"
        for preset_code, label in self._get_rate_profile_pairs():
            if label == chosen_label:
                code = preset_code
                break
        if code in RATE_LIMIT_PRESETS:
            self._manual_custom_mode = False
            self._adv_numeric_dirty = False
            self._set_adv_status(None)
            self.config.apply_rate_limit_preset(code)
            self._sync_advanced_vars()
            self.config.save()
            self.on_save(self.config)
        else:
            self._manual_custom_mode = True
            self.config.rate_limit_preset = "custom"
            self._set_advanced_expanded(True)
            self._update_rate_profile_summary()
            self.config.save()

    def _set_advanced_expanded(self, expanded: bool) -> None:
        if self._advanced_expanded == expanded:
            return
        self._advanced_expanded = expanded
        if self._advanced_expanded:
            self.advanced_card.pack(fill="x", padx=4, pady=(0, 8))
        else:
            self.advanced_card.pack_forget()
        key = "advanced_toggle_hide" if self._advanced_expanded else "advanced_toggle_show"
        self.advanced_toggle_btn.configure(text=self.t(key))

    def _add_adv_section_header(self, parent, title_key: str) -> None:
        """Adds a subtle divider and group title inside the advanced settings card."""
        divider = ctk.CTkFrame(parent, height=1, fg_color=("#E4E4E7", "#27272A"))
        divider.pack(fill="x", padx=14, pady=(4, 10))
        lbl = ctk.CTkLabel(
            parent,
            text=self.t(title_key),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#18181B", "#FAFAFA"),
            anchor="w",
        )
        lbl.pack(anchor="w", padx=14, pady=(0, 6))
        setattr(self, title_key, lbl)

    def _add_adv_setting_row(
        self,
        parent,
        label_key: str,
        hint_key: str,
        str_var: ctk.StringVar,
        entry_attr: str,
        placeholder_key: Optional[str] = None,
    ) -> ctk.CTkEntry:
        """Adds a horizontal setting row with title + plain-language hint on the left and numeric input on the right."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(0, 10))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=0)

        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.grid(row=0, column=0, sticky="ew", padx=(0, 14))

        lbl = ctk.CTkLabel(
            text_col,
            text=self.t(label_key),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        lbl.pack(anchor="w")
        setattr(self, label_key, lbl)

        hint = ctk.CTkLabel(
            text_col,
            text=self.t(hint_key),
            font=ctk.CTkFont(size=11),
            text_color=("#71717A", "#A1A1AA"),
            wraplength=460,
            justify="left",
            anchor="w",
        )
        hint.pack(fill="x", anchor="w", pady=(1, 0))
        setattr(self, hint_key, hint)

        entry_kwargs = {
            "textvariable": str_var,
            "width": 130,
            "height": 32,
            "justify": "right",
            "fg_color": ("#FFFFFF", "#09090B"),
            "border_color": ("#D4D4D8", "#3F3F46"),
        }
        if placeholder_key:
            entry_kwargs["placeholder_text"] = self.t(placeholder_key)
        ent = ctk.CTkEntry(row, **entry_kwargs)
        ent.grid(row=0, column=1, sticky="e")
        ent.bind("<FocusOut>", lambda _e: self._commit_advanced_settings())
        ent.bind("<Return>", lambda _e: self._commit_advanced_settings())
        setattr(self, entry_attr, ent)
        return ent

    def _toggle_advanced_section(self) -> None:
        self._set_advanced_expanded(not self._advanced_expanded)

    def _sync_advanced_vars(self) -> None:
        self._suppress_adv_trace = True
        try:
            provider = self.provider_var.get()
            if getattr(self, "base_url_label", None) is not None:
                self.base_url_label.configure(text=self._get_base_url_label_text(provider))
            if getattr(self, "base_url_var", None) is not None:
                self.base_url_var.set(self.config.base_urls.get(provider, ""))
            if getattr(self, "temperature_var", None) is not None:
                temp_str = "" if self.config.temperature is None else f"{self.config.temperature:g}"
                self.temperature_var.set(temp_str)
            if getattr(self, "request_timeout_var", None) is not None:
                self.request_timeout_var.set(f"{self.config.request_timeout:g}")
            if getattr(self, "batch_size_var", None) is not None:
                self.batch_size_var.set(str(self.config.batch_size))
            if getattr(self, "max_concurrent_var", None) is not None:
                self.max_concurrent_var.set(str(self.config.max_concurrent_requests))
            if getattr(self, "batch_max_chars_var", None) is not None:
                self.batch_max_chars_var.set(str(self.config.batch_max_chars))
            if getattr(self, "section_max_chars_var", None) is not None:
                self.section_max_chars_var.set(str(self.config.section_max_chars))
            if getattr(self, "min_interval_var", None) is not None:
                self.min_interval_var.set(f"{self.config.min_request_interval:g}")
            if getattr(self, "rate_retries_var", None) is not None:
                self.rate_retries_var.set(str(self.config.max_retries_rate_limit))
            if getattr(self, "rpm_limit_var", None) is not None:
                self.rpm_limit_var.set(str(self.config.rpm_limit))
            if getattr(self, "tpm_limit_var", None) is not None:
                self.tpm_limit_var.set(str(self.config.tpm_limit))
            if getattr(self, "strict_json_var", None) is not None:
                self.strict_json_var.set(bool(self.config.strict_json_mode))
            self._update_rate_profile_summary()
        finally:
            self._suppress_adv_trace = False

    def _parse_adv_numeric_value(self, cfg_field: str, raw_val: object) -> tuple[object, bool]:
        """Parses an advanced numeric field and reports whether clamping or fallback was needed."""
        spec = NUMERIC_SETTING_SPECS[cfg_field]
        trimmed = str(raw_val or "").strip() if raw_val is not None else ""
        if spec.kind == "optional_float":
            if not trimmed:
                return None, False
            try:
                parsed = float(trimmed)
            except (TypeError, ValueError):
                return None, True
            if math.isnan(parsed) or math.isinf(parsed):
                return None, True
            clamped = max(float(spec.min_val), min(parsed, float(spec.max_val)))
            return clamped, abs(clamped - parsed) > 1e-9

        if spec.kind == "int":
            if not trimmed:
                return int(spec.default), True
            try:
                parsed = int(trimmed)
            except (TypeError, ValueError):
                return int(spec.default), True
            clamped = max(int(spec.min_val), min(parsed, int(spec.max_val)))
            return clamped, clamped != parsed

        if not trimmed:
            return float(spec.default), True
        try:
            parsed = float(trimmed)
        except (TypeError, ValueError):
            return float(spec.default), True
        if math.isnan(parsed) or math.isinf(parsed):
            return float(spec.default), True
        clamped = max(float(spec.min_val), min(parsed, float(spec.max_val)))
        return clamped, abs(clamped - parsed) > 1e-9

    def _apply_numeric_vars_to_config(self) -> list[str]:
        """Applies numeric StringVars to self.config and returns descriptions of adjusted fields."""
        adjusted: list[str] = []
        for var_attr, cfg_field in _ADV_NUMERIC_BINDINGS:
            tk_var = getattr(self, var_attr, None)
            if tk_var is None:
                continue
            parsed_val, was_adjusted = self._parse_adv_numeric_value(cfg_field, tk_var.get())
            setattr(self.config, cfg_field, parsed_val)
            if was_adjusted:
                spec = NUMERIC_SETTING_SPECS[cfg_field]
                label_key = _ADV_FIELD_LABEL_KEYS.get(cfg_field, cfg_field)
                display_val = (
                    self.t("temperature_placeholder")
                    if parsed_val is None
                    else (f"{parsed_val:g}" if isinstance(parsed_val, float) else str(parsed_val))
                )
                adjusted.append(f"{self.t(label_key)} → {display_val} ({spec.min_val:g}–{spec.max_val:g})")
        return adjusted

    def _schedule_adv_save(self) -> None:
        if getattr(self, "_adv_save_after_id", None):
            try:
                self.after_cancel(self._adv_save_after_id)
            except Exception:
                pass
        try:
            self._adv_save_after_id = self.after(
                UI_TIMING["debounce_save_ms"], self._flush_adv_save
            )
        except Exception:
            self._adv_save_after_id = None

    def _on_adv_numeric_var_changed(self, *_args) -> None:
        if self._suppress_adv_trace:
            return
        self._adv_numeric_dirty = True
        self._schedule_adv_save()

    def _on_base_url_changed(self, *_args) -> None:
        if self._suppress_adv_trace or getattr(self, "base_url_var", None) is None:
            return
        provider = self.provider_var.get()
        self.config.base_urls[provider] = self.base_url_var.get().strip()
        self._adv_save_pending = True
        self._schedule_adv_save()

    def _commit_advanced_settings(
        self, normalize_display: bool = True, notify: bool = True
    ) -> None:
        if getattr(self, "_adv_save_after_id", None):
            try:
                self.after_cancel(self._adv_save_after_id)
            except Exception:
                pass
            self._adv_save_after_id = None
        provider = self.provider_var.get()
        if getattr(self, "base_url_var", None) is not None:
            self.config.base_urls[provider] = self.base_url_var.get().strip()
        adjusted = self._apply_numeric_vars_to_config()
        if getattr(self, "strict_json_var", None) is not None:
            self.config.strict_json_mode = bool(self.strict_json_var.get())
        detected = self.config.detect_rate_limit_preset()
        self.config.rate_limit_preset = detected
        if detected == "custom":
            self._manual_custom_mode = False
        self._adv_save_pending = False
        self._adv_numeric_dirty = False
        if normalize_display:
            self._sync_advanced_vars()
            if adjusted:
                self._set_adv_status("adjusted", "; ".join(adjusted))
            else:
                self._set_adv_status(None)
        else:
            self._update_rate_profile_summary()
        self.config.save()
        if notify:
            self.on_save(self.config)

    def _reset_advanced_defaults(self) -> None:
        if getattr(self, "_adv_save_after_id", None):
            try:
                self.after_cancel(self._adv_save_after_id)
            except Exception:
                pass
            self._adv_save_after_id = None
        self._manual_custom_mode = False
        self._adv_numeric_dirty = False
        self._adv_save_pending = False
        self.config.apply_rate_limit_preset(DEFAULT_RATE_LIMIT_PRESET)
        self.config.temperature = coerce_setting_value("temperature", None)
        self.config.request_timeout = float(NUMERIC_SETTING_SPECS["request_timeout"].default)
        self.config.strict_json_mode = True
        self._sync_advanced_vars()
        self._set_adv_status("reset")
        self.config.save()
        self.on_save(self.config)

    def _on_strict_json_toggled(self) -> None:
        self._commit_advanced_settings(normalize_display=False, notify=True)

    def _flush_adv_save(self) -> None:
        if getattr(self, "_adv_save_after_id", None):
            try:
                self.after_cancel(self._adv_save_after_id)
            except Exception:
                pass
            self._adv_save_after_id = None
        if self._adv_numeric_dirty:
            parsed_updates: dict[str, object] = {}
            all_clean = True
            for var_attr, cfg_field in _ADV_NUMERIC_BINDINGS:
                tk_var = getattr(self, var_attr, None)
                if tk_var is None:
                    continue
                raw_text = tk_var.get().strip()
                if raw_text.endswith(".") or raw_text in ("-", "+"):
                    all_clean = False
                    break
                val, was_adjusted = self._parse_adv_numeric_value(cfg_field, raw_text)
                if was_adjusted:
                    all_clean = False
                    break
                parsed_updates[cfg_field] = val
            if all_clean:
                for cfg_field, val in parsed_updates.items():
                    setattr(self.config, cfg_field, val)
                self._adv_numeric_dirty = False
                self._adv_save_pending = False
                detected = self.config.detect_rate_limit_preset()
                self.config.rate_limit_preset = detected
                if detected == "custom":
                    self._manual_custom_mode = False
                self._update_rate_profile_summary()
                self.config.save()
                self.on_save(self.config)
                return
        if self._adv_save_pending:
            self._adv_save_pending = False
            self.config.save()
            self.on_save(self.config)

    def commit_pending_changes(self) -> None:
        """Commits any in-progress API key or advanced numeric/URL edits before leaving Settings."""
        had_key_pending = self._key_save_pending
        if had_key_pending:
            self._flush_key_save()
            self.on_save(self.config)
        if self._adv_save_pending or self._adv_numeric_dirty:
            self._commit_advanced_settings(normalize_display=True, notify=True)

    def _flush_key_save(self) -> None:
        if getattr(self, "_key_save_after_id", None):
            try:
                self.after_cancel(self._key_save_after_id)
            except Exception:
                pass
            self._key_save_after_id = None
        if self._key_save_pending:
            self._key_save_pending = False
            self.config.save()

    def refresh_values(self):
        """Synchronizes UI fields with latest config when switching into settings view."""
        current_prov = self.config.active_provider
        self.provider_var.set(current_prov)
        for i in range(len(list(AI_PROVIDERS.keys()))):
            self.provider_selector.grid_columnconfigure(i, weight=1, uniform="prov_tabs")
        self._apply_provider_icons()
        models = self.config.get_available_models(current_prov)
        self._apply_model_options(models, self.config.get_active_model())
        self._set_key_var_silently(self.config.api_keys.get(current_prov, ""))
        self.guide_text_label.configure(text=self._get_guide_text(current_prov))
        self.lang_var.set(UI_LANGUAGES.get(self.config.ui_language, UI_LANGUAGES[DEFAULT_UI_LANGUAGE]))
        self.theme_var.set(self._get_current_theme_display())
        self.auto_update_var.set(bool(self.config.auto_check_updates))
        self._manual_custom_mode = False
        self._adv_numeric_dirty = False
        self._set_adv_status(None)
        self._sync_advanced_vars()
        if not self._has_auto_fetched_on_open:
            self._has_auto_fetched_on_open = True
            self._schedule_model_autofetch(UI_TIMING["autofetch_delay_ms"])

    def refresh_i18n(self, get_translation: Callable[[str], str]):
        """Refreshes localized labels inside SettingsView."""
        self.t = get_translation
        self.title_label.configure(text="  " + self.t("settings_title"))
        self.active_prov_label.configure(text=self.t("active_provider"))
        self.model_label_elem.configure(text=self.t("model_label"))
        current_prov = self.provider_var.get()
        self._apply_model_options(
            self.config.get_available_models(current_prov),
            self._get_selected_model_value(current_prov),
        )
        self.fetch_btn.set_text(self.t("fetch_models"))
        self.model_hint_label.configure(text=self.t("model_hint"))
        self.api_key_label_elem.configure(text=self.t("api_key_label"))
        self.key_entry.configure(placeholder_text=self.t("api_key_placeholder"))
        self.test_conn_btn.set_text(self.t("test_connection"))
        self.guide_link_btn.configure(text=self.t("open_api_guide"))
        self.guide_text_label.configure(text=self._get_guide_text(self.provider_var.get()))
        self.pref_label_elem.configure(text=self.t("preferences_title"))
        self.ui_lang_label_elem.configure(text=self.t("ui_language"))
        self.lang_var.set(UI_LANGUAGES.get(self.config.ui_language, UI_LANGUAGES[DEFAULT_UI_LANGUAGE]))
        self.theme_label_elem.configure(text=self.t("theme_mode"))
        self.theme_dropdown.configure(values=self._get_theme_display_names())
        self.theme_var.set(self._get_current_theme_display())
        self.speed_section_label.configure(text=self.t("speed_section_title"))
        adv_toggle_key = "advanced_toggle_hide" if self._advanced_expanded else "advanced_toggle_show"
        self.advanced_toggle_btn.configure(text=self.t(adv_toggle_key))
        self.advanced_intro_label.configure(text=self.t("advanced_intro_note"))
        self.reset_adv_btn.set_text(self.t("adv_reset_defaults_btn"))
        self.base_url_entry.configure(placeholder_text=self.t("base_url_placeholder"))
        self.temperature_entry.configure(placeholder_text=self.t("temperature_placeholder"))
        self.rate_profile_label.configure(text=self.t("rate_profile_label"))
        self.rate_profile_dropdown.configure(values=self._get_rate_profile_display_names())
        self.rate_profile_var.set(self._get_rate_profile_display())
        self.rate_profile_summary_label.configure(text=self._get_rate_profile_summary_text())
        self.rate_profile_hint_label.configure(text=self.t("rate_profile_hint"))
        self.base_url_label.configure(text=self._get_base_url_label_text(current_prov))
        for text_key in (
            "adv_group_connection",
            "adv_group_batching",
            "adv_group_ratelimit",
            "base_url_hint",
            "temperature_label",
            "temperature_hint",
            "request_timeout_label",
            "request_timeout_hint",
            "strict_json_mode_hint",
            "batch_size_label",
            "batch_size_hint",
            "batch_max_chars_label",
            "batch_max_chars_hint",
            "section_max_chars_label",
            "section_max_chars_hint",
            "max_concurrent_label",
            "max_concurrent_hint",
            "min_interval_label",
            "min_interval_hint",
            "rate_retries_label",
            "rate_retries_hint",
            "rpm_limit_label",
            "rpm_limit_hint",
            "tpm_limit_label",
            "tpm_limit_hint",
        ):
            widget = getattr(self, text_key, None)
            if widget is not None:
                widget.configure(text=self.t(text_key))
        self.strict_json_cb.configure(text=self.t("strict_json_mode_label"))
        self._render_adv_status()
        self.updates_title_label.configure(text=self.t("updates_section_title"))
        self.version_label.configure(text=self.t("current_version_label", version=APP_VERSION))
        self.check_updates_btn.set_text(self.t("check_updates_btn"))
        self.download_update_btn.set_text(self.t("update_details_btn"))
        self.auto_update_cb.configure(text=self.t("auto_check_updates_label"))
        self._render_update_status()
        for i in range(len(list(AI_PROVIDERS.keys()))):
            self.provider_selector.grid_columnconfigure(i, weight=1, uniform="prov_tabs")
        self._apply_provider_icons()

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        self.key_entry.configure(show="" if self._show_key else "*")
        self.toggle_btn.set_icon("lock" if self._show_key else "eye", 16)

    def _fetch_live_models(self, is_manual: bool = True):
        provider = self.provider_var.get()
        key = self.key_var.get().strip() or self.config.get_effective_api_key(provider)
        if not key:
            if is_manual:
                self.model_hint_label.configure(
                    text=self.t("err_enter_api_key_models"),
                    text_color=COLORS["error_title"]
                )
            return

        if is_manual:
            self.fetch_btn.start_loading(self.t("fetching_models"))
            self.model_hint_label.configure(
                text=self.t("fetching_models"),
                text_color="#3B8ED0"
            )

        self._fetch_request_id += 1
        req_id = self._fetch_request_id

        def on_done(models, error_msg):
            def update_ui():
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return

                if req_id != self._fetch_request_id or self.provider_var.get() != provider:
                    return

                if is_manual:
                    self.fetch_btn.stop_loading(self.t("fetch_models"))

                if error_msg:
                    selected = self._get_selected_model_value(provider)
                    if models:
                        self._apply_model_options(models, selected)
                    if is_manual or not models:
                        self.model_hint_label.configure(
                            text=error_msg,
                            text_color=COLORS["error_title"]
                        )
                    else:
                        self.model_hint_label.configure(
                            text=self.t("model_hint"),
                            text_color="gray"
                        )
                elif models:
                    selected = self._get_selected_model_value(provider)
                    self._apply_model_options(models, selected)
                    msg_key = "models_fetched_success" if selected else "models_fetched_select"
                    msg = self.t(msg_key, count=len(models), provider=provider)
                    self.model_hint_label.configure(
                        text=msg,
                        text_color=COLORS["success"]
                    )
                else:
                    self._apply_model_options([], self._get_selected_model_value(provider))
                    if is_manual:
                        self.model_hint_label.configure(
                            text=self.t("err_no_models_returned", provider=provider),
                            text_color=COLORS["error_title"]
                        )
                    else:
                        self.model_hint_label.configure(
                            text=self.t("model_hint"),
                            text_color="gray"
                        )

            self.after(0, update_ui)

        base_url = (
            self.base_url_var.get().strip()
            if getattr(self, "base_url_var", None) is not None
            else ""
        ) or self.config.get_effective_base_url(provider)
        fetch_models_async(
            provider,
            key,
            on_done,
            base_url=base_url or None,
            timeout=float(self.config.model_fetch_timeout),
        )

    def _on_key_focus_out(self, _event=None):
        self._flush_key_save()
        self.on_save(self.config)
        provider = self.provider_var.get()
        key = self.key_var.get().strip() if self.key_var else ""
        if key and not self.config.get_available_models(provider):
            self._fetch_live_models(is_manual=False)

    def _on_provider_changed(self, new_provider: str):
        if self.key_var is None or self.model_var is None:
            return
        self._flush_key_save()
        if self._adv_save_pending or self._adv_numeric_dirty:
            self._commit_advanced_settings(normalize_display=False, notify=False)
        self._fetch_request_id += 1
        self._test_conn_request_id += 1
        self.fetch_btn.stop_loading(self.t("fetch_models"))
        self.test_conn_btn.stop_loading(self.t("test_connection"))
        self.test_conn_status.configure(text="")

        old_prov = self.config.active_provider
        self.config.api_keys[old_prov] = self.key_var.get().strip()
        if getattr(self, "base_url_var", None) is not None:
            self.config.base_urls[old_prov] = self.base_url_var.get().strip()

        self.config.active_provider = new_provider
        self.provider_var.set(new_provider)
        available_models = self.config.get_available_models(new_provider)
        saved_model = self._get_selected_model_value(new_provider)
        self._apply_model_options(available_models, saved_model)

        self._set_key_var_silently(self.config.api_keys.get(new_provider, ""))
        self._sync_advanced_vars()
        self.guide_text_label.configure(text=self._get_guide_text(new_provider))
        self.model_hint_label.configure(text=self.t("model_hint"), text_color="gray")

        # Save directly and notify parent
        self.config.save()
        self.on_save(self.config)

        self._schedule_model_autofetch(UI_TIMING["autofetch_delay_ms"])

    def _on_model_changed(self, new_model: str):
        clean_model = (new_model or "").strip()
        if not clean_model or clean_model == self._model_placeholder_text():
            return
        provider = self.provider_var.get()
        self.config.selected_models[provider] = clean_model
        self.config.save()
        self.on_save(self.config)

    def _on_key_changed(self, *args):
        if self._suppress_key_trace or self.key_var is None:
            return
        provider = self.provider_var.get()
        new_key = self.key_var.get().strip()
        self.config.api_keys[provider] = new_key
        self._key_save_pending = True
        if getattr(self, "_key_save_after_id", None):
            try:
                self.after_cancel(self._key_save_after_id)
            except Exception:
                pass
        try:
            self._key_save_after_id = self.after(
                UI_TIMING["debounce_save_ms"], self._flush_key_save
            )
        except Exception:
            self._key_save_after_id = None

    def _open_provider_guide(self):
        provider = self.provider_var.get()
        url = AI_PROVIDERS[provider]["api_url_guide"]
        webbrowser.open_new_tab(url)

    def _on_theme_changed(self, selected_display: str):
        display_to_mode = {self.t(f"theme_{m}"): m for m in THEME_MODES}
        mode = display_to_mode.get(selected_display, THEME_MODES[-1])
        self.config.theme_mode = mode
        self.config.save()
        ctk.set_appearance_mode(mode)
        self.on_save(self.config)

    def _on_language_changed(self, selected_name: str):
        for code, name in UI_LANGUAGES.items():
            if name == selected_name:
                self.config.ui_language = code
                self.config.save()
                self.on_save(self.config)
                break

    def _test_api_connection(self):
        provider = self.provider_var.get()
        key = self.key_var.get().strip() or self.config.get_effective_api_key(provider)
        selected_model = self._get_selected_model_value(provider)

        if not key:
            self.test_conn_status.configure(
                text=self.t("err_enter_api_key"),
                text_color=COLORS["error_title"]
            )
            return

        if not selected_model:
            self.test_conn_status.configure(
                text=self.t("err_select_model"),
                text_color=COLORS["error_title"]
            )
            return

        self._commit_advanced_settings(normalize_display=True, notify=False)
        base_url = self.config.get_effective_base_url(provider) or None
        timeout = float(self.config.request_timeout)
        temperature = self.config.temperature
        strict_json_mode = bool(self.config.strict_json_mode)

        self.test_conn_btn.start_loading(self.t("testing_connection"))
        self.test_conn_status.configure(
            text=self.t("testing_connection"),
            text_color="#3B8ED0"
        )
        self._test_conn_request_id += 1
        req_id = self._test_conn_request_id

        def worker():
            t0 = time.time()
            success = False
            err_msg = ""
            try:
                from rakutrans.llm.llm_manager import create_llm_client

                client = create_llm_client(
                    provider,
                    key,
                    timeout=timeout,
                    base_url=base_url,
                    temperature=temperature,
                    strict_json_mode=strict_json_mode,
                )
                res = client.generate_completion(
                    system_prompt="You are a ping test assistant. Reply with one word.",
                    user_prompt="Ping",
                    model_name=selected_model,
                    is_json=False
                )
                success = bool(res and res.strip())
            except Exception as e:
                err_msg = str(e)

            elapsed_ms = int((time.time() - t0) * 1000)

            def update_ui():
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return
                if req_id != self._test_conn_request_id or self.provider_var.get() != provider:
                    return
                self.test_conn_btn.stop_loading(self.t("test_connection"))
                if success:
                    msg = self.t("test_conn_success", model=selected_model, ms=elapsed_ms)
                    self.test_conn_status.configure(text=msg, text_color=COLORS["success"])
                else:
                    msg = self.t("test_conn_failed", error=err_msg)
                    self.test_conn_status.configure(text=msg, text_color=COLORS["error_title"])

            self.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _on_auto_update_toggled(self):
        self.config.auto_check_updates = bool(self.auto_update_var.get())
        self.config.save()
        self.on_save(self.config)

    def _render_update_status(self):
        if self._update_status_state == "checking":
            self.update_status_label.configure(
                text=self.t("checking_updates"),
                text_color="#3B8ED0"
            )
        elif self._update_status_state == "update_available" and self._latest_update_info:
            self.update_status_label.configure(
                text=self.t("update_available_short", version=self._latest_update_info.latest_version),
                text_color="#3B8ED0"
            )
        elif self._update_status_state == "up_to_date":
            self.update_status_label.configure(
                text=self.t("update_up_to_date", version=APP_VERSION),
                text_color=COLORS["success"]
            )
        elif self._update_status_state == "error":
            self.update_status_label.configure(
                text=self.t("update_check_failed", error=self._update_status_error),
                text_color=COLORS["error_title"]
            )

    def _check_for_updates(self):
        self._update_check_request_id += 1
        req_id = self._update_check_request_id
        self._update_status_state = "checking"
        self._update_status_error = ""
        self.check_updates_btn.start_loading(self.t("checking_updates"))
        self.download_update_btn.pack_forget()
        self._render_update_status()

        def on_done(result: UpdateCheckResult):
            def update_ui():
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return
                if req_id != self._update_check_request_id:
                    return
                self.check_updates_btn.stop_loading(self.t("check_updates_btn"))
                if result.status == "update_available" and result.info:
                    self._latest_update_info = result.info
                    self._update_status_state = "update_available"
                    self.download_update_btn.pack(side="right", padx=(0, 8))
                    self._render_update_status()
                    if self.on_update_found:
                        self.on_update_found(result.info)
                elif result.status == "up_to_date":
                    self._latest_update_info = result.info
                    self._update_status_state = "up_to_date"
                    self.download_update_btn.pack_forget()
                    self._render_update_status()
                else:
                    self._update_status_state = "error"
                    self._update_status_error = result.error_message
                    self.download_update_btn.pack_forget()
                    self._render_update_status()

            self.after(0, update_ui)

        check_for_updates_async(
            on_done,
            current_version=APP_VERSION,
            ui_language=self.config.ui_language,
        )

    def _open_update_modal(self):
        if not self._latest_update_info:
            return
        UpdateModal(
            self.winfo_toplevel(),
            update_info=self._latest_update_info,
            on_skip_version=self._on_skip_version,
            get_translation=self.t,
        )

    def _on_skip_version(self, version: str):
        self.config.skipped_update_version = version
        self.config.save()
        self.on_save(self.config)

    def destroy(self):
        self._fetch_request_id += 1
        self._test_conn_request_id += 1
        self._update_check_request_id += 1
        for attr in ("_fetch_after_id", "_key_save_after_id", "_adv_save_after_id"):
            after_id = getattr(self, attr, None)
            if after_id:
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
                if attr != "_key_save_after_id":
                    setattr(self, attr, None)
        self._flush_key_save()
        if self._adv_numeric_dirty or self._adv_save_pending:
            provider = self.provider_var.get()
            if getattr(self, "base_url_var", None) is not None:
                self.config.base_urls[provider] = self.base_url_var.get().strip()
            if self._adv_numeric_dirty:
                self._apply_numeric_vars_to_config()
            self.config.rate_limit_preset = self.config.detect_rate_limit_preset()
            self._adv_numeric_dirty = False
            self._adv_save_pending = False
            self.config.save()
        super().destroy()
