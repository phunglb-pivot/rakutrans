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

from config import AppConfig, AI_PROVIDERS, UI_LANGUAGES
from model_fetcher import fetch_models_async
from components.ui_system import CustomButton
from components.icons import get_icon


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
        **kwargs
    ):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.config = config
        self.t = get_translation
        self.on_save = on_save_callback
        self.on_close = on_close_callback
        self.show_back_button = show_back_button
        self._show_key = False
        self.key_var: Optional[ctk.StringVar] = None
        self.model_var: Optional[ctk.StringVar] = None

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
        self.provider_selector = ctk.CTkSegmentedButton(
            self.provider_group,
            values=providers_list,
            variable=self.provider_var,
            command=self._on_provider_changed,
            height=35,
            border_width=1,
            selected_color=("#D4D4D8", "#3F3F46"),
            selected_hover_color=("#C4C4C8", "#52525B"),
            unselected_color=("#F4F4F5", "#18181B"),
            unselected_hover_color=("#E4E4E7", "#27272A"),
            text_color=("#18181B", "#FAFAFA")
        )
        for i in range(len(providers_list)):
            self.provider_selector.grid_columnconfigure(i, weight=1, uniform="prov_tabs")
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
        self.model_var = ctk.StringVar(value=self.config.get_active_model())

        model_row = ctk.CTkFrame(self.model_group, fg_color="transparent")
        model_row.pack(fill="x", padx=4, pady=(0, 4))

        self.model_combo = ctk.CTkOptionMenu(
            model_row,
            values=available_models,
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
        self.key_entry.bind("<FocusOut>", lambda e: self.on_save(self.config))

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

        # Auto-fetch latest models in background if key is present
        self.after(250, lambda: self._fetch_live_models(is_manual=False))

    def refresh_values(self):
        """Synchronizes UI fields with latest config when switching into settings view."""
        current_prov = self.config.active_provider
        self.provider_var.set(current_prov)
        for i in range(len(list(AI_PROVIDERS.keys()))):
            self.provider_selector.grid_columnconfigure(i, weight=1, uniform="prov_tabs")
        models = self.config.get_available_models(current_prov)
        self.model_combo.configure(values=models)
        self.model_var.set(self.config.get_active_model())
        self.key_var.set(self.config.api_keys.get(current_prov, ""))
        self.guide_text_label.configure(text=self._get_guide_text(current_prov))
        self.lang_var.set(UI_LANGUAGES.get(self.config.ui_language, "English"))
        self.theme_var.set(self._get_current_theme_display())

    def refresh_i18n(self, get_translation: Callable[[str], str]):
        """Refreshes localized labels inside SettingsView."""
        self.t = get_translation
        self.title_label.configure(text="  " + self.t("settings_title"))
        self.back_header_btn.configure(text=self.t("back"))
        self.active_prov_label.configure(text=self.t("active_provider"))
        self.model_label_elem.configure(text=self.t("model_label"))
        self.fetch_btn.configure(text=self.t("fetch_models"))
        self.model_hint_label.configure(text=self.t("model_hint"))
        self.api_key_label_elem.configure(text=self.t("api_key_label"))
        self.key_entry.configure(placeholder_text=self.t("api_key_placeholder"))
        self.test_conn_btn.configure(text=self.t("test_connection"))
        self.guide_link_btn.configure(text=self.t("open_api_guide"))
        self.guide_text_label.configure(text=self._get_guide_text(self.provider_var.get()))
        self.pref_label_elem.configure(text=self.t("preferences_title"))
        self.ui_lang_label_elem.configure(text=self.t("ui_language"))
        self.lang_var.set(UI_LANGUAGES.get(self.config.ui_language, "English"))
        self.theme_label_elem.configure(text=self.t("theme_mode"))
        self.theme_dropdown.configure(values=self._get_theme_display_names())
        self.theme_var.set(self._get_current_theme_display())
        for i in range(len(list(AI_PROVIDERS.keys()))):
            self.provider_selector.grid_columnconfigure(i, weight=1, uniform="prov_tabs")

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

        def on_done(models, error_msg):
            def update_ui():
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return

                if is_manual:
                    self.fetch_btn.stop_loading(self.t("fetch_models"))

                if self.provider_var.get() != provider:
                    return

                if models:
                    self.model_combo.configure(values=models)
                    if self.model_var.get() not in models:
                        self.model_var.set(models[0])
                        self.config.selected_models[provider] = models[0]
                        self.config.save()
                        self.on_save(self.config)
                    msg = self.t("models_fetched_success", count=len(models), provider=provider)
                    self.model_hint_label.configure(
                        text=msg,
                        text_color="#10B981"
                    )
                elif error_msg and is_manual:
                    self.model_hint_label.configure(
                        text=error_msg,
                        text_color="#EF4444"
                    )
                elif not is_manual:
                    self.model_hint_label.configure(
                        text=self.t("model_hint"),
                        text_color="gray"
                    )

            self.after(0, update_ui)

        fetch_models_async(provider, key, on_done)

    def _on_provider_changed(self, new_provider: str):
        if self.key_var is None or self.model_var is None:
            return
        old_prov = self.config.active_provider
        self.config.api_keys[old_prov] = self.key_var.get().strip()
        self.config.selected_models[old_prov] = self.model_var.get().strip()

        self.config.active_provider = new_provider
        self.provider_var.set(new_provider)
        available_models = self.config.get_available_models(new_provider)
        self.model_combo.configure(values=available_models)

        saved_model = self.config.selected_models.get(
            new_provider,
            AI_PROVIDERS[new_provider]["default_model"]
        )
        if available_models and saved_model not in available_models:
            saved_model = available_models[0]
        self.model_var.set(saved_model)
        self.config.selected_models[new_provider] = saved_model

        self.key_var.set(self.config.api_keys.get(new_provider, ""))
        self.guide_text_label.configure(text=self._get_guide_text(new_provider))
        self.model_hint_label.configure(text=self.t("model_hint"), text_color="gray")

        # Save directly and notify parent
        self.config.save()
        self.on_save(self.config)

        self.after(150, lambda: self._fetch_live_models(is_manual=False))

    def _on_model_changed(self, new_model: str):
        provider = self.provider_var.get()
        self.config.selected_models[provider] = new_model
        self.config.save()
        self.on_save(self.config)

    def _on_key_changed(self, *args):
        if self.key_var is None:
            return
        provider = self.provider_var.get()
        new_key = self.key_var.get().strip()
        self.config.api_keys[provider] = new_key
        self.config.save()

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
        model = self.model_var.get().strip() or AI_PROVIDERS[provider]["default_model"]

        if not key:
            self.test_conn_status.configure(
                text=self.t("err_enter_api_key"),
                text_color="#EF4444"
            )
            return

        self.test_conn_btn.start_loading(self.t("testing_connection"))
        self.test_conn_status.configure(
            text=self.t("testing_connection"),
            text_color="#3B8ED0"
        )

        def worker():
            t0 = time.time()
            success = False
            err_msg = ""
            try:
                if provider == "Gemini":
                    from llm_manager import GeminiClient
                    client = GeminiClient(key)
                    res = client.generate_completion(
                        system_prompt="You are a ping test assistant. Reply with one word.",
                        user_prompt="Ping",
                        model_name=model,
                        is_json=False
                    )
                    success = bool(res and res.strip())
                elif provider == "OpenAI":
                    from llm_manager import OpenAIClient
                    client = OpenAIClient(key)
                    res = client.generate_completion(
                        system_prompt="You are a ping test assistant. Reply with one word.",
                        user_prompt="Ping",
                        model_name=model,
                        is_json=False
                    )
                    success = bool(res and res.strip())
                elif provider == "Claude":
                    from llm_manager import ClaudeClient
                    client = ClaudeClient(key)
                    res = client.generate_completion(
                        system_prompt="You are a ping test assistant. Reply with one word.",
                        user_prompt="Ping",
                        model_name=model,
                        is_json=False
                    )
                    success = bool(res and res.strip())
            except Exception as e:
                err_msg = str(e)

            elapsed_ms = int((time.time() - t0) * 1000)

            def update_ui():
                self.test_conn_btn.stop_loading(self.t("test_connection"))
                if success:
                    msg = self.t("test_conn_success", model=model, ms=elapsed_ms)
                    self.test_conn_status.configure(text=msg, text_color="#10B981")
                else:
                    msg = self.t("test_conn_failed", error=err_msg)
                    self.test_conn_status.configure(text=msg, text_color="#EF4444")

            self.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()
