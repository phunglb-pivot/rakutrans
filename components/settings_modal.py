"""
Settings modal for RakuTrans AI.
Enables AI Provider selection, model switching, secure API key configuration,
appearance customization, and links to provider key generation pages.
"""

import threading
import time
import webbrowser
from typing import Callable
import customtkinter as ctk

from config import AppConfig, AI_PROVIDERS, SUPPORTED_LANGUAGES
from translation_cache import TranslationCache
from model_fetcher import fetch_models_async, load_cached_models


class SettingsModal(ctk.CTkToplevel):
    """
    Settings dialog modal.
    """

    def __init__(
        self,
        parent,
        config: AppConfig,
        get_translation: Callable[[str], str],
        on_save_callback: Callable[[AppConfig], None]
    ):
        super().__init__(parent)
        self.config = config
        self.t = get_translation
        self.on_save = on_save_callback

        self.title(self.t("settings_title"))
        self.geometry("620x680")
        self.resizable(False, False)

        # Make modal window stay on top
        self.transient(parent)
        self.grab_set()

        self._show_key = False
        # Pre-initialize widget vars to prevent AttributeError if provider
        # segmented button fires its command before _setup_ui completes.
        self.key_var = None
        self.model_var = None
        self._setup_ui()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Main scrollable container
        container = ctk.CTkScrollableFrame(self, corner_radius=0)
        container.pack(fill="both", expand=True, padx=20, pady=20)

        # Title
        title_label = ctk.CTkLabel(
            container,
            text=self.t("settings_title"),
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.pack(anchor="w", pady=(0, 15))

        # --------------------------------------------------------------------
        # 1. AI Provider Selection
        # --------------------------------------------------------------------
        provider_group = ctk.CTkFrame(container)
        provider_group.pack(fill="x", pady=(0, 15), padx=2)

        ctk.CTkLabel(
            provider_group,
            text=self.t("active_provider"),
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(12, 6))

        self.provider_var = ctk.StringVar(value=self.config.active_provider)
        self.provider_selector = ctk.CTkSegmentedButton(
            provider_group,
            values=list(AI_PROVIDERS.keys()),
            variable=self.provider_var,
            command=self._on_provider_changed,
            height=35
        )
        self.provider_selector.pack(fill="x", padx=15, pady=(0, 12))

        # --------------------------------------------------------------------
        # 2. Model Selection (Flexible ComboBox + Live Model Fetching)
        # --------------------------------------------------------------------
        model_group = ctk.CTkFrame(container)
        model_group.pack(fill="x", pady=(0, 15), padx=2)

        ctk.CTkLabel(
            model_group,
            text=self.t("model_label"),
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(12, 6))

        current_prov = self.config.active_provider
        available_models = self.config.get_available_models(current_prov)
        self.model_var = ctk.StringVar(value=self.config.get_active_model())

        model_row = ctk.CTkFrame(model_group, fg_color="transparent")
        model_row.pack(fill="x", padx=15, pady=(0, 4))

        self.model_combo = ctk.CTkOptionMenu(
            model_row,
            values=available_models,
            variable=self.model_var,
            height=34,
            dynamic_resizing=False
        )
        self.model_combo.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.fetch_btn = ctk.CTkButton(
            model_row,
            text="🔄 " + self.t("fetch_models"),
            width=115,
            height=34,
            font=ctk.CTkFont(size=12),
            command=self._fetch_live_models
        )
        self.fetch_btn.pack(side="right")

        self.model_hint_label = ctk.CTkLabel(
            model_group,
            text=self.t("model_hint"),
            font=ctk.CTkFont(size=11),
            text_color="gray"
        )
        self.model_hint_label.pack(anchor="w", padx=15, pady=(0, 12))

        # --------------------------------------------------------------------
        # 3. API Key & Provider Guide
        # --------------------------------------------------------------------
        key_group = ctk.CTkFrame(container)
        key_group.pack(fill="x", pady=(0, 15), padx=2)

        ctk.CTkLabel(
            key_group,
            text=self.t("api_key_label"),
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(12, 4))

        # Entry row with show/hide button
        entry_frame = ctk.CTkFrame(key_group, fg_color="transparent")
        entry_frame.pack(fill="x", padx=15, pady=(0, 8))

        self.key_var = ctk.StringVar(value=self.config.api_keys.get(current_prov, ""))
        self.key_entry = ctk.CTkEntry(
            entry_frame,
            textvariable=self.key_var,
            placeholder_text=self.t("api_key_placeholder"),
            show="*",
            height=34
        )
        self.key_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.toggle_btn = ctk.CTkButton(
            entry_frame,
            text="👁",
            width=40,
            height=34,
            command=self._toggle_key_visibility
        )
        self.toggle_btn.pack(side="right")

        # Test Connection button & status row
        test_row = ctk.CTkFrame(key_group, fg_color="transparent")
        test_row.pack(fill="x", padx=15, pady=(0, 10))

        self.test_conn_btn = ctk.CTkButton(
            test_row,
            text="⚡ " + self.t("test_connection"),
            width=135,
            height=30,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._test_api_connection
        )
        self.test_conn_btn.pack(side="left")

        self.test_conn_status = ctk.CTkLabel(
            test_row,
            text="",
            font=ctk.CTkFont(size=11),
            anchor="w"
        )
        self.test_conn_status.pack(side="left", padx=(10, 0), fill="x", expand=True)

        # Provider guide box
        self.guide_box = ctk.CTkFrame(key_group, fg_color=("gray90", "gray20"), corner_radius=8)
        self.guide_box.pack(fill="x", padx=15, pady=(4, 15))

        self.guide_text_label = ctk.CTkLabel(
            self.guide_box,
            text=AI_PROVIDERS[current_prov]["guide_text"],
            font=ctk.CTkFont(size=12),
            wraplength=480,
            justify="left"
        )
        self.guide_text_label.pack(anchor="w", padx=12, pady=(8, 4))

        self.guide_link_btn = ctk.CTkButton(
            self.guide_box,
            text=self.t("open_api_guide"),
            command=self._open_provider_guide,
            height=26,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            text_color="#3B8ED0"
        )
        self.guide_link_btn.pack(anchor="w", padx=12, pady=(0, 8))

        # --------------------------------------------------------------------
        # 3.5. Translation Memory Cache
        # --------------------------------------------------------------------
        self.cache = TranslationCache()
        cache_group = ctk.CTkFrame(container)
        cache_group.pack(fill="x", pady=(0, 15), padx=2)

        ctk.CTkLabel(
            cache_group,
            text=self.t("cache_section_title"),
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=15, pady=(12, 4))

        cache_row = ctk.CTkFrame(cache_group, fg_color="transparent")
        cache_row.pack(fill="x", padx=15, pady=(0, 12))

        self.cache_stats_label = ctk.CTkLabel(
            cache_row,
            text=self.t("cache_stats", count=self.cache.count()),
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70")
        )
        self.cache_stats_label.pack(side="left")

        self.clear_cache_btn = ctk.CTkButton(
            cache_row,
            text=self.t("clear_cache"),
            width=100,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80"),
            command=self._on_clear_cache
        )
        self.clear_cache_btn.pack(side="right")

        # --------------------------------------------------------------------
        # 4. App Preferences (Language & Theme)
        # --------------------------------------------------------------------
        pref_group = ctk.CTkFrame(container)
        pref_group.pack(fill="x", pady=(0, 20), padx=2)

        pref_grid = ctk.CTkFrame(pref_group, fg_color="transparent")
        pref_grid.pack(fill="x", padx=15, pady=12)
        pref_grid.grid_columnconfigure((0, 1), weight=1)

        # Language dropdown
        ctk.CTkLabel(
            pref_grid,
            text=self.t("ui_language"),
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=0, sticky="w", pady=(0, 4))

        lang_codes = list(SUPPORTED_LANGUAGES.keys())
        lang_names = [SUPPORTED_LANGUAGES[c] for c in lang_codes]
        current_lang_name = SUPPORTED_LANGUAGES.get(self.config.ui_language, "English")
        
        self.lang_var = ctk.StringVar(value=current_lang_name)
        self.lang_dropdown = ctk.CTkOptionMenu(
            pref_grid,
            values=lang_names,
            variable=self.lang_var,
            command=self._on_language_changed,
            height=32
        )
        self.lang_dropdown.grid(row=1, column=0, sticky="ew", padx=(0, 8))

        # Theme dropdown
        ctk.CTkLabel(
            pref_grid,
            text=self.t("theme_mode"),
            font=ctk.CTkFont(size=13, weight="bold")
        ).grid(row=0, column=1, sticky="w", pady=(0, 4))

        self.theme_var = ctk.StringVar(value=self.config.theme_mode.capitalize())
        self.theme_dropdown = ctk.CTkOptionMenu(
            pref_grid,
            values=["Dark", "Light", "System"],
            variable=self.theme_var,
            command=self._on_theme_changed,
            height=32
        )
        self.theme_dropdown.grid(row=1, column=1, sticky="ew", padx=(8, 0))

        # --------------------------------------------------------------------
        # 5. Bottom Action Buttons
        # --------------------------------------------------------------------
        actions_frame = ctk.CTkFrame(container, fg_color="transparent")
        actions_frame.pack(fill="x", pady=(10, 0))

        save_btn = ctk.CTkButton(
            actions_frame,
            text=self.t("save_settings"),
            command=self._save_and_close,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=38
        )
        save_btn.pack(side="right", padx=(8, 0))

        cancel_btn = ctk.CTkButton(
            actions_frame,
            text=self.t("close_settings"),
            command=self.destroy,
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80"),
            height=38
        )
        cancel_btn.pack(side="right")

        # Auto-fetch latest models in background if key is present
        self.after(250, lambda: self._fetch_live_models(is_manual=False))

    def _toggle_key_visibility(self):
        self._show_key = not self._show_key
        self.key_entry.configure(show="" if self._show_key else "*")
        self.toggle_btn.configure(text="🔒" if self._show_key else "👁")

    def _fetch_live_models(self, is_manual: bool = True):
        provider = self.provider_var.get()
        key = self.key_var.get().strip() or self.config.get_effective_api_key(provider)
        if not key:
            if is_manual:
                self.model_hint_label.configure(
                    text="⚠️ Please enter an API key first to fetch live models.",
                    text_color="#EF4444"
                )
            return

        if is_manual:
            self.fetch_btn.configure(state="disabled", text=self.t("fetching_models"))
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
                    self.fetch_btn.configure(state="normal", text="🔄 " + self.t("fetch_models"))

                if self.provider_var.get() != provider:
                    return

                if models:
                    self.model_combo.configure(values=models)
                    if self.model_var.get() not in models:
                        self.model_var.set(models[0])
                    msg = self.t("models_fetched_success", count=len(models), provider=provider)
                    self.model_hint_label.configure(
                        text=msg,
                        text_color="#10B981"
                    )
                elif error_msg and is_manual:
                    self.model_hint_label.configure(
                        text=f"⚠️ {error_msg[:70]}...",
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
        # Guard: called before _setup_ui finishes (CTkSegmentedButton fires early)
        if self.key_var is None or self.model_var is None:
            return
        # Save previous key to dictionary in memory
        old_prov = self.config.active_provider
        self.config.api_keys[old_prov] = self.key_var.get().strip()
        self.config.selected_models[old_prov] = self.model_var.get().strip()

        # Update controls
        self.config.active_provider = new_provider
        available_models = self.config.get_available_models(new_provider)
        self.model_combo.configure(values=available_models)
        
        saved_model = self.config.selected_models.get(
            new_provider, 
            AI_PROVIDERS[new_provider]["default_model"]
        )
        if available_models and saved_model not in available_models:
            saved_model = available_models[0]
        self.model_var.set(saved_model)

        self.key_var.set(self.config.api_keys.get(new_provider, ""))
        self.guide_text_label.configure(text=AI_PROVIDERS[new_provider]["guide_text"])
        self.model_hint_label.configure(text=self.t("model_hint"), text_color="gray")

        # Automatically fetch models for the newly selected provider in background
        self.after(150, lambda: self._fetch_live_models(is_manual=False))

    def _open_provider_guide(self):
        provider = self.provider_var.get()
        url = AI_PROVIDERS[provider]["api_url_guide"]
        webbrowser.open_new_tab(url)

    def _on_theme_changed(self, new_theme: str):
        ctk.set_appearance_mode(new_theme.lower())

    def _on_language_changed(self, selected_name: str):
        # Find matching code
        for code, name in SUPPORTED_LANGUAGES.items():
            if name == selected_name:
                self.config.ui_language = code
                break

    def _test_api_connection(self):
        provider = self.provider_var.get()
        key = self.key_var.get().strip() or self.config.get_effective_api_key(provider)
        model = self.model_var.get().strip() or AI_PROVIDERS[provider]["default_model"]

        if not key:
            self.test_conn_status.configure(
                text="⚠️ Please enter an API key first.",
                text_color="#EF4444"
            )
            return

        self.test_conn_btn.configure(state="disabled", text=self.t("testing_connection"))
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
                self.test_conn_btn.configure(state="normal", text="⚡ " + self.t("test_connection"))
                if success:
                    msg = self.t("test_conn_success", model=model, ms=elapsed_ms)
                    self.test_conn_status.configure(text=msg, text_color="#10B981")
                else:
                    msg = self.t("test_conn_failed", error=err_msg[:60])
                    self.test_conn_status.configure(text=msg, text_color="#EF4444")

            self.after(0, update_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _on_clear_cache(self):
        self.cache.clear()
        self.cache_stats_label.configure(text=self.t("cache_cleared"), text_color="#10B981")

    def _save_and_close(self):
        current_prov = self.provider_var.get()
        self.config.active_provider = current_prov
        self.config.api_keys[current_prov] = self.key_var.get().strip()
        self.config.selected_models[current_prov] = self.model_var.get().strip()
        self.config.theme_mode = self.theme_var.get().lower()

        for code, name in SUPPORTED_LANGUAGES.items():
            if name == self.lang_var.get():
                self.config.ui_language = code
                break

        self.config.save()
        self.on_save(self.config)
        self.destroy()
