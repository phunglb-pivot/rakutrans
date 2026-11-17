"""
In-page Settings View and Settings Modal for RakuTrans AI.
Enables AI Provider selection, model switching, secure API key configuration,
appearance customization, and links to provider key generation pages.
Supports both seamless in-page transition (no popup) and standalone modal.
All settings changes take effect immediately and persist automatically.
"""

import threading
import time
import webbrowser
from typing import Callable, Optional
import customtkinter as ctk

from config import (
    AppConfig,
    AI_PROVIDERS,
    RATE_LIMIT_PRESETS,
    UI_LANGUAGES,
    APP_VERSION,
    _coerce_float,
    _coerce_int,
    _coerce_optional_float,
)
from model_fetcher import fetch_models_async
from update_checker import UpdateCheckResult, UpdateInfo, check_for_updates_async
from components.ui_system import CustomButton, CustomSegmentedButton
from components.icons import get_icon, get_provider_icon, get_provider_icon_name
from components.update_modal import UpdateModal


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
        show_back_button: bool = False,
        on_update_found: Optional[Callable[[UpdateInfo], None]] = None,
        **kwargs
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self.t = get_translation
        self.on_save = on_save_callback
        self.on_close = on_close_callback
        self.show_back_button = show_back_button
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
        self._adv_save_after_id = None

        self._setup_ui()

    def _get_guide_text(self, provider: str) -> str:
        guide_key = AI_PROVIDERS.get(provider, {}).get("guide_key")
        if guide_key:
            return self.t(guide_key)
        return AI_PROVIDERS.get(provider, {}).get("guide_text", "")

    def _get_theme_display_names(self) -> list[str]:
        return [self.t("theme_dark"), self.t("theme_light"), self.t("theme_system")]

    def _get_current_theme_display(self) -> str:
        mode = self.config.theme_mode.lower()
        if mode == "dark":
            return self.t("theme_dark")
        elif mode == "light":
            return self.t("theme_light")
        return self.t("theme_system")

    def _setup_ui(self):
        # --------------------------------------------------------------------
        # Pinned Header with Title and Back Navigation
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

        self.back_header_btn = CustomButton(
            self.header_frame,
            text=self.t("back"),
            variant="outline",
            size="sm",
            icon_name="arrow_left",
            icon_size=14,
            command=self.on_close
        )
        if self.show_back_button:
            self.back_header_btn.pack(side="right")

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
        current_lang_name = UI_LANGUAGES.get(self.config.ui_language, "English")

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
        # 4. Advanced & Performance Settings (Collapsible)
        # --------------------------------------------------------------------
        self.advanced_group = ctk.CTkFrame(self.container, fg_color="transparent")
        self.advanced_group.pack(fill="x", pady=(0, 12), padx=2)

        self.advanced_toggle_btn = ctk.CTkButton(
            self.advanced_group,
            text=self.t("advanced_toggle_show"),
            command=self._toggle_advanced_section,
            fg_color="transparent",
            hover_color=("#F4F4F5", "#27272A"),
            text_color=("#3F3F46", "#D4D4D8"),
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=30,
        )
        self.advanced_toggle_btn.pack(fill="x", padx=2, pady=(4, 4))

        self.advanced_card = ctk.CTkFrame(
            self.advanced_group,
            fg_color=("#F4F4F5", "#18181B"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            corner_radius=8
        )
        # Collapsed by default; shown on demand via _toggle_advanced_section()

        self.rate_profile_label = ctk.CTkLabel(
            self.advanced_card,
            text=self.t("rate_profile_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.rate_profile_label.pack(anchor="w", padx=12, pady=(10, 4))

        self.rate_profile_var = ctk.StringVar(value=self._get_rate_profile_display())
        self.rate_profile_dropdown = ctk.CTkOptionMenu(
            self.advanced_card,
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
        self.rate_profile_dropdown.pack(fill="x", padx=12, pady=(0, 4))

        self.rate_profile_hint_label = ctk.CTkLabel(
            self.advanced_card,
            text=self.t("rate_profile_hint"),
            font=ctk.CTkFont(size=11),
            text_color=("#71717A", "#A1A1AA"),
            wraplength=500,
            justify="left",
            anchor="w",
        )
        self.rate_profile_hint_label.pack(fill="x", padx=12, pady=(0, 8))

        self.base_url_label = ctk.CTkLabel(
            self.advanced_card,
            text=self.t("base_url_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.base_url_label.pack(anchor="w", padx=12, pady=(2, 4))

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
        self.base_url_entry.pack(fill="x", padx=12, pady=(0, 10))

        adv_grid = ctk.CTkFrame(self.advanced_card, fg_color="transparent")
        adv_grid.pack(fill="x", padx=12, pady=(0, 8))
        adv_grid.grid_columnconfigure(0, weight=1, uniform="adv_cols")
        adv_grid.grid_columnconfigure(1, weight=1, uniform="adv_cols")

        self.temperature_label = ctk.CTkLabel(
            adv_grid,
            text=self.t("temperature_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.temperature_label.grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))

        self.request_timeout_label = ctk.CTkLabel(
            adv_grid,
            text=self.t("request_timeout_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.request_timeout_label.grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 4))

        self.temperature_var = ctk.StringVar(
            value="" if self.config.temperature is None else f"{self.config.temperature:g}"
        )
        self.temperature_entry = ctk.CTkEntry(
            adv_grid,
            textvariable=self.temperature_var,
            placeholder_text=self.t("temperature_placeholder"),
            height=32,
            fg_color=("#FFFFFF", "#09090B"),
            border_color=("#D4D4D8", "#3F3F46"),
        )
        self.temperature_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(0, 8))

        self.request_timeout_var = ctk.StringVar(
            value=f"{self.config.request_timeout:g}"
        )
        self.request_timeout_entry = ctk.CTkEntry(
            adv_grid,
            textvariable=self.request_timeout_var,
            height=32,
            fg_color=("#FFFFFF", "#09090B"),
            border_color=("#D4D4D8", "#3F3F46"),
        )
        self.request_timeout_entry.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        self.batch_size_label = ctk.CTkLabel(
            adv_grid,
            text=self.t("batch_size_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.batch_size_label.grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 4))

        self.max_concurrent_label = ctk.CTkLabel(
            adv_grid,
            text=self.t("max_concurrent_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.max_concurrent_label.grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(0, 4))

        self.batch_size_var = ctk.StringVar(value=str(self.config.batch_size))
        self.batch_size_entry = ctk.CTkEntry(
            adv_grid,
            textvariable=self.batch_size_var,
            height=32,
            fg_color=("#FFFFFF", "#09090B"),
            border_color=("#D4D4D8", "#3F3F46"),
        )
        self.batch_size_entry.grid(row=3, column=0, sticky="ew", padx=(0, 8), pady=(0, 4))

        self.max_concurrent_var = ctk.StringVar(
            value=str(self.config.max_concurrent_requests)
        )
        self.max_concurrent_entry = ctk.CTkEntry(
            adv_grid,
            textvariable=self.max_concurrent_var,
            height=32,
            fg_color=("#FFFFFF", "#09090B"),
            border_color=("#D4D4D8", "#3F3F46"),
        )
        self.max_concurrent_entry.grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(0, 8))

        self.batch_max_chars_var = ctk.StringVar(value=str(self.config.batch_max_chars))
        self.section_max_chars_var = ctk.StringVar(value=str(self.config.section_max_chars))
        self.min_interval_var = ctk.StringVar(value=f"{self.config.min_request_interval:g}")
        self.rate_retries_var = ctk.StringVar(value=str(self.config.max_retries_rate_limit))
        self.rpm_limit_var = ctk.StringVar(value=str(self.config.rpm_limit))
        self.tpm_limit_var = ctk.StringVar(value=str(self.config.tpm_limit))

        extra_adv_pairs = [
            (4, "batch_max_chars_label", self.batch_max_chars_var, "batch_max_chars_entry"),
            (4, "section_max_chars_label", self.section_max_chars_var, "section_max_chars_entry"),
            (6, "min_interval_label", self.min_interval_var, "min_interval_entry"),
            (6, "rate_retries_label", self.rate_retries_var, "rate_retries_entry"),
            (8, "rpm_limit_label", self.rpm_limit_var, "rpm_limit_entry"),
            (8, "tpm_limit_label", self.tpm_limit_var, "tpm_limit_entry"),
        ]
        extra_entries = []
        for idx, (row_base, label_key, str_var, entry_attr) in enumerate(extra_adv_pairs):
            col = idx % 2
            padx = (0, 8) if col == 0 else (8, 0)
            lbl = ctk.CTkLabel(
                adv_grid,
                text=self.t(label_key),
                font=ctk.CTkFont(size=12, weight="bold")
            )
            lbl.grid(row=row_base, column=col, sticky="w", padx=padx, pady=(0, 4))
            setattr(self, label_key, lbl)

            ent = ctk.CTkEntry(
                adv_grid,
                textvariable=str_var,
                height=32,
                fg_color=("#FFFFFF", "#09090B"),
                border_color=("#D4D4D8", "#3F3F46"),
            )
            ent.grid(row=row_base + 1, column=col, sticky="ew", padx=padx, pady=(0, 8))
            setattr(self, entry_attr, ent)
            extra_entries.append(ent)

        for entry_widget in (
            self.base_url_entry,
            self.temperature_entry,
            self.request_timeout_entry,
            self.batch_size_entry,
            self.max_concurrent_entry,
            *extra_entries,
        ):
            entry_widget.bind("<FocusOut>", lambda _e: self._commit_advanced_settings())
            entry_widget.bind("<Return>", lambda _e: self._commit_advanced_settings())

        self.strict_json_var = ctk.BooleanVar(value=bool(self.config.strict_json_mode))
        self.strict_json_cb = ctk.CTkCheckBox(
            self.advanced_card,
            text=self.t("strict_json_mode_label"),
            variable=self.strict_json_var,
            command=self._on_strict_json_toggled,
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
        self.strict_json_cb.pack(anchor="w", padx=12, pady=(2, 10))

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

    def _schedule_model_autofetch(self, delay_ms: int = 150) -> None:
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

    def _get_rate_profile_pairs(self) -> list[tuple[str, str]]:
        return [
            ("safe_free", self.t("rate_profile_safe_free")),
            ("balanced", self.t("rate_profile_balanced")),
            ("fast_paid", self.t("rate_profile_fast_paid")),
            ("custom", self.t("rate_profile_custom")),
        ]

    def _get_rate_profile_display_names(self) -> list[str]:
        return [label for _, label in self._get_rate_profile_pairs()]

    def _get_rate_profile_display(self) -> str:
        code = getattr(self.config, "rate_limit_preset", "") or self.config.detect_rate_limit_preset()
        mapping = dict(self._get_rate_profile_pairs())
        return mapping.get(code, mapping["custom"])

    def _on_rate_profile_changed(self, chosen_label: str) -> None:
        code = "custom"
        for preset_code, label in self._get_rate_profile_pairs():
            if label == chosen_label:
                code = preset_code
                break
        if code in RATE_LIMIT_PRESETS:
            self.config.apply_rate_limit_preset(code)
            self._sync_advanced_vars()
            self.config.save()
            self.on_save(self.config)
        else:
            self.config.rate_limit_preset = "custom"
            self.config.save()

    def _toggle_advanced_section(self) -> None:
        self._advanced_expanded = not self._advanced_expanded
        if self._advanced_expanded:
            self.advanced_card.pack(fill="x", padx=4, pady=(0, 8))
        else:
            self.advanced_card.pack_forget()
        key = "advanced_toggle_hide" if self._advanced_expanded else "advanced_toggle_show"
        self.advanced_toggle_btn.configure(text=self.t(key))

    def _sync_advanced_vars(self) -> None:
        self._suppress_adv_trace = True
        try:
            provider = self.provider_var.get()
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
            if getattr(self, "rate_profile_var", None) is not None:
                self.rate_profile_var.set(self._get_rate_profile_display())
            if getattr(self, "strict_json_var", None) is not None:
                self.strict_json_var.set(bool(self.config.strict_json_mode))
        finally:
            self._suppress_adv_trace = False

    def _on_base_url_changed(self, *_args) -> None:
        if self._suppress_adv_trace or getattr(self, "base_url_var", None) is None:
            return
        provider = self.provider_var.get()
        self.config.base_urls[provider] = self.base_url_var.get().strip()
        self._adv_save_pending = True
        if getattr(self, "_adv_save_after_id", None):
            try:
                self.after_cancel(self._adv_save_after_id)
            except Exception:
                pass
        try:
            self._adv_save_after_id = self.after(300, self._flush_adv_save)
        except Exception:
            self._adv_save_after_id = None

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
        if getattr(self, "temperature_var", None) is not None:
            self.config.temperature = _coerce_optional_float(
                self.temperature_var.get(), 0.0, 2.0
            )
        if getattr(self, "request_timeout_var", None) is not None:
            self.config.request_timeout = _coerce_float(
                self.request_timeout_var.get(), 120.0, 5.0, 600.0
            )
        if getattr(self, "batch_size_var", None) is not None:
            self.config.batch_size = _coerce_int(
                self.batch_size_var.get(), 25, 1, 500
            )
        if getattr(self, "max_concurrent_var", None) is not None:
            self.config.max_concurrent_requests = _coerce_int(
                self.max_concurrent_var.get(), 2, 1, 20
            )
        if getattr(self, "batch_max_chars_var", None) is not None:
            self.config.batch_max_chars = _coerce_int(
                self.batch_max_chars_var.get(), 6000, 200, 100000
            )
        if getattr(self, "section_max_chars_var", None) is not None:
            self.config.section_max_chars = _coerce_int(
                self.section_max_chars_var.get(), 6000, 200, 100000
            )
        if getattr(self, "min_interval_var", None) is not None:
            self.config.min_request_interval = _coerce_float(
                self.min_interval_var.get(), 0.5, 0.0, 60.0
            )
        if getattr(self, "rate_retries_var", None) is not None:
            self.config.max_retries_rate_limit = _coerce_int(
                self.rate_retries_var.get(), 5, 1, 15
            )
        if getattr(self, "rpm_limit_var", None) is not None:
            self.config.rpm_limit = _coerce_int(
                self.rpm_limit_var.get(), 45, 0, 10000
            )
        if getattr(self, "tpm_limit_var", None) is not None:
            self.config.tpm_limit = _coerce_int(
                self.tpm_limit_var.get(), 0, 0, 10000000
            )
        if getattr(self, "strict_json_var", None) is not None:
            self.config.strict_json_mode = bool(self.strict_json_var.get())
        self.config.rate_limit_preset = self.config.detect_rate_limit_preset()
        if normalize_display:
            self._sync_advanced_vars()
        self._adv_save_pending = False
        self.config.save()
        if notify:
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
        if self._adv_save_pending:
            self._adv_save_pending = False
            self.config.save()

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
        self.lang_var.set(UI_LANGUAGES.get(self.config.ui_language, "English"))
        self.theme_var.set(self._get_current_theme_display())
        self.auto_update_var.set(bool(self.config.auto_check_updates))
        self._sync_advanced_vars()
        if not self._has_auto_fetched_on_open:
            self._has_auto_fetched_on_open = True
            self._schedule_model_autofetch(150)

    def refresh_i18n(self, get_translation: Callable[[str], str]):
        """Refreshes localized labels inside SettingsView."""
        self.t = get_translation
        self.title_label.configure(text="  " + self.t("settings_title"))
        self.back_header_btn.set_text(self.t("back"))
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
        self.lang_var.set(UI_LANGUAGES.get(self.config.ui_language, "English"))
        self.theme_label_elem.configure(text=self.t("theme_mode"))
        self.theme_dropdown.configure(values=self._get_theme_display_names())
        self.theme_var.set(self._get_current_theme_display())
        adv_toggle_key = "advanced_toggle_hide" if self._advanced_expanded else "advanced_toggle_show"
        self.advanced_toggle_btn.configure(text=self.t(adv_toggle_key))
        self.base_url_label.configure(text=self.t("base_url_label"))
        self.base_url_entry.configure(placeholder_text=self.t("base_url_placeholder"))
        self.temperature_label.configure(text=self.t("temperature_label"))
        self.temperature_entry.configure(placeholder_text=self.t("temperature_placeholder"))
        self.request_timeout_label.configure(text=self.t("request_timeout_label"))
        self.batch_size_label.configure(text=self.t("batch_size_label"))
        self.max_concurrent_label.configure(text=self.t("max_concurrent_label"))
        self.rate_profile_label.configure(text=self.t("rate_profile_label"))
        self.rate_profile_dropdown.configure(values=self._get_rate_profile_display_names())
        self.rate_profile_var.set(self._get_rate_profile_display())
        self.rate_profile_hint_label.configure(text=self.t("rate_profile_hint"))
        for lbl_key in (
            "batch_max_chars_label",
            "section_max_chars_label",
            "min_interval_label",
            "rate_retries_label",
            "rpm_limit_label",
            "tpm_limit_label",
        ):
            lbl_widget = getattr(self, lbl_key, None)
            if lbl_widget is not None:
                lbl_widget.configure(text=self.t(lbl_key))
        self.strict_json_cb.configure(text=self.t("strict_json_mode_label"))
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
                    text_color="#EF4444"
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
                            text_color="#EF4444"
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
                        text_color="#10B981"
                    )
                else:
                    self._apply_model_options([], self._get_selected_model_value(provider))
                    if is_manual:
                        self.model_hint_label.configure(
                            text=self.t("err_no_models_returned", provider=provider),
                            text_color="#EF4444"
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

        self._schedule_model_autofetch(150)

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
            self._key_save_after_id = self.after(300, self._flush_key_save)
        except Exception:
            self._key_save_after_id = None

    def _open_provider_guide(self):
        provider = self.provider_var.get()
        url = AI_PROVIDERS[provider]["api_url_guide"]
        webbrowser.open_new_tab(url)

    def _on_theme_changed(self, selected_display: str):
        if selected_display == self.t("theme_dark"):
            mode = "dark"
        elif selected_display == self.t("theme_light"):
            mode = "light"
        else:
            mode = "system"
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
                text_color="#EF4444"
            )
            return

        if not selected_model:
            self.test_conn_status.configure(
                text=self.t("err_select_model"),
                text_color="#EF4444"
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
                from llm_manager import create_llm_client

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
                    self.test_conn_status.configure(text=msg, text_color="#10B981")
                else:
                    msg = self.t("test_conn_failed", error=err_msg)
                    self.test_conn_status.configure(text=msg, text_color="#EF4444")

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
                text_color="#10B981"
            )
        elif self._update_status_state == "error":
            self.update_status_label.configure(
                text=self.t("update_check_failed", error=self._update_status_error),
                text_color="#EF4444"
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

        check_for_updates_async(on_done, current_version=APP_VERSION)

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
                if attr not in ("_key_save_after_id", "_adv_save_after_id"):
                    setattr(self, attr, None)
        self._flush_key_save()
        self._flush_adv_save()
        super().destroy()
