"""
Main User Interface for RakuTrans AI.
Built with CustomTkinter and TkinterDnD2.
Features real-time i18n switching, dark/light themes, background threading,
and comprehensive translation progress tracking.
"""

import os
import platform
import subprocess
import threading
from pathlib import Path
from typing import Optional

import customtkinter as ctk
from tkinter import filedialog

from config import AppConfig, SUPPORTED_LANGUAGES, TranslationOptions
from i18n import I18nManager
from llm_manager import LLMManager
from excel_parser import ExcelTranslator
from markdown_parser import MarkdownTranslator
from translation_cache import TranslationCache
from components.dnd_zone import DropZone
from components.settings_modal import SettingsModal
from components.error_modal import ErrorModal
from error_handler import diagnose_error, DiagnosticInfo
from format_converter import convert_translated_output, convert_file_direct, get_convert_options

try:
    from tkinterdnd2 import TkinterDnD
    HAS_TKDND = True
except ImportError:
    HAS_TKDND = False


class RakuTransApp(ctk.CTk):
    """
    Main desktop application window for RakuTrans AI.
    """

    def __init__(self, config: Optional[AppConfig] = None):
        super().__init__()

        # Load config and i18n
        self.config = config or AppConfig.load()
        self.i18n = I18nManager(self.config.ui_language)
        self.llm_manager = LLMManager(self.config)
        self.cache = TranslationCache()

        # Active translators sharing the local translation memory cache
        self.excel_translator = ExcelTranslator(self.config, self.llm_manager, cache=self.cache)
        self.markdown_translator = MarkdownTranslator(self.config, self.llm_manager, cache=self.cache)

        # Runtime states
        self.selected_file: Optional[str] = None
        self.last_output_file: Optional[str] = None
        self.is_translating: bool = False
        self.current_thread: Optional[threading.Thread] = None
        self.last_diagnostic: Optional[DiagnosticInfo] = None

        # Mode: "translate" or "convert"
        self._mode: str = "translate"
        # Whether options card body is expanded
        self._options_expanded: bool = False

        # Window configuration
        self.title(f"{self.i18n.t('app_title')} - {self.i18n.t('app_subtitle')}")
        self.geometry("860x820")
        self.minsize(780, 680)

        # Apply theme
        ctk.set_appearance_mode(self.config.theme_mode)
        ctk.set_default_color_theme("blue")

        # Initialize TkinterDnD if available
        if HAS_TKDND:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
            except Exception as e:
                print(f"[Info] TkinterDnD initialization note: {e}")

        # Load custom logo / window icon if available
        self.logo_image = None
        logo_path = Path(__file__).resolve().parent / "assets" / "logo.png"
        if logo_path.exists():
            try:
                from PIL import Image, ImageTk
                pil_logo = Image.open(logo_path)
                self.logo_image = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(28, 28))
                self._window_icon = ImageTk.PhotoImage(pil_logo)
                self.iconphoto(False, self._window_icon)
            except Exception as e:
                print(f"[Warning] Failed to load logo from {logo_path}: {e}")

        self._setup_ui()

    def _setup_ui(self):
        # Configure layout: Row 0 Header, Row 1 Scrollable Body, Row 2 Sticky Bottom Bar
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(2, weight=0)

        # --------------------------------------------------------------------
        # Top Header Bar
        # --------------------------------------------------------------------
        self.header_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray90", "#1E293B"))
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=0)
        self.header_frame.grid_columnconfigure(1, weight=1)

        # App branding
        brand_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        brand_frame.grid(row=0, column=0, sticky="w", padx=20, pady=12)

        if self.logo_image:
            self.logo_label = ctk.CTkLabel(
                brand_frame,
                text="  " + self.i18n.t("app_title"),
                image=self.logo_image,
                compound="left",
                font=ctk.CTkFont(size=20, weight="bold")
            )
        else:
            self.logo_label = ctk.CTkLabel(
                brand_frame,
                text="🌐 " + self.i18n.t("app_title"),
                font=ctk.CTkFont(size=20, weight="bold")
            )
        self.logo_label.pack(anchor="w")

        self.subtitle_label = ctk.CTkLabel(
            brand_frame,
            text=self.i18n.t("app_subtitle"),
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.subtitle_label.pack(anchor="w")

        # Header Right Controls (Active Model Badge & Settings Button)
        right_header = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        right_header.grid(row=0, column=2, sticky="e", padx=20, pady=12)

        self.provider_badge = ctk.CTkLabel(
            right_header,
            text=f"AI: {self.config.active_provider} ({self.config.get_active_model()})",
            font=ctk.CTkFont(size=11),
            fg_color=("gray80", "#334155"),
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.provider_badge.pack(side="left", padx=(0, 10))

        self.settings_btn = ctk.CTkButton(
            right_header,
            text=f"⚙ {self.i18n.t('settings_btn')}",
            width=100,
            height=32,
            command=self._open_settings,
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.settings_btn.pack(side="left")

        # --------------------------------------------------------------------
        # Main Scrollable Body
        # --------------------------------------------------------------------
        self.body_scroll = ctk.CTkScrollableFrame(self, corner_radius=0)
        self.body_scroll.grid(row=1, column=0, sticky="nsew", padx=20, pady=(15, 5))
        self.body_scroll.grid_columnconfigure(0, weight=1)

        # 0. Mode Switcher (Translate / Convert)
        self._build_mode_switcher()

        # 1. Language Selection Card (translate mode only)
        self._build_language_card()

        # 2. File Drag & Drop Zone
        self._build_dropzone()

        # 3. Translation Options Card (translate mode only, collapsible)
        self._build_options_card()

        # 4. Convert Panel (convert mode only)
        self._build_convert_panel()

        # 5. Sticky Action Bar (Always visible at the bottom)
        self._build_action_bar()

        # 6. Global Keyboard Shortcuts
        self._setup_shortcuts()

        # Apply initial mode visibility
        self._apply_mode_visibility()

    # -------------------------------------------------------------------------
    # Mode Switcher
    # -------------------------------------------------------------------------

    def _build_mode_switcher(self):
        self.mode_switcher_frame = ctk.CTkFrame(self.body_scroll, corner_radius=10)
        self.mode_switcher_frame.pack(fill="x", pady=(0, 15))

        self.mode_var = ctk.StringVar(value=self.i18n.t("mode_translate"))
        self.mode_switcher = ctk.CTkSegmentedButton(
            self.mode_switcher_frame,
            values=[self.i18n.t("mode_translate"), self.i18n.t("mode_convert")],
            variable=self.mode_var,
            command=self._on_mode_changed,
            height=36,
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.mode_switcher.pack(fill="x", padx=12, pady=10)

    def _on_mode_changed(self, _value: str):
        if self.is_translating:
            # Lock mode switcher while an operation is running
            active_text = self.i18n.t("mode_convert") if self._mode == "convert" else self.i18n.t("mode_translate")
            self.mode_var.set(active_text)
            return

        selected = self.mode_var.get()
        if selected == self.i18n.t("mode_convert"):
            self._mode = "convert"
        else:
            self._mode = "translate"
        self._apply_mode_visibility()
        self._sync_action_bar_mode()

    def _apply_mode_visibility(self):
        if self._mode == "convert":
            if self.lang_card.winfo_ismapped():
                self.lang_card.pack_forget()
            if self.options_card.winfo_ismapped():
                self.options_card.pack_forget()
            if not self.convert_panel.winfo_ismapped():
                self.convert_panel.pack(fill="x", pady=(0, 15))
            self.subtitle_label.configure(text=self.i18n.t("convert_subtitle"))
            if self.provider_badge.winfo_ismapped():
                self.provider_badge.pack_forget()
            self.shortcut_hint_label.configure(text=self.i18n.t("shortcut_hint_convert"))
        else:
            if self.convert_panel.winfo_ismapped():
                self.convert_panel.pack_forget()
            if not self.lang_card.winfo_ismapped():
                self.lang_card.pack(fill="x", pady=(0, 15), before=self.drop_zone)
            if not self.options_card.winfo_ismapped():
                self.options_card.pack(fill="x", pady=(0, 15))
            self.subtitle_label.configure(text=self.i18n.t("app_subtitle"))
            if not self.provider_badge.winfo_ismapped():
                self.provider_badge.pack(side="left", padx=(0, 10), before=self.settings_btn)
            self.provider_badge.configure(
                text=f"AI: {self.config.active_provider} ({self.config.get_active_model()})"
            )
            self.shortcut_hint_label.configure(text=self.i18n.t("shortcut_hint"))

        if hasattr(self, "drop_zone"):
            self.drop_zone.set_mode(self._mode)

    def _sync_action_bar_mode(self):
        """Toggle translate_btn / convert_btn in action bar container."""
        if self._mode == "convert":
            self.translate_btn.pack_forget()
            self.convert_btn.pack(fill="both", expand=True)
        else:
            self.convert_btn.pack_forget()
            self.translate_btn.pack(fill="both", expand=True)
        # Also update convert hint label if a file is selected
        self._refresh_convert_hint()

    # -------------------------------------------------------------------------
    # Language Card
    # -------------------------------------------------------------------------

    def _build_language_card(self):
        self.lang_card = ctk.CTkFrame(self.body_scroll, corner_radius=10)
        self.lang_card.pack(fill="x", pady=(0, 15))

        row = ctk.CTkFrame(self.lang_card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=12)

        self.tgt_label = ctk.CTkLabel(
            row, 
            text=self.i18n.t("target_lang"), 
            font=ctk.CTkFont(size=13, weight="bold")
        )
        self.tgt_label.pack(side="left", padx=(0, 12))

        self.tgt_var = ctk.StringVar(value=self.config.target_language)
        self.tgt_menu = ctk.CTkOptionMenu(
            row,
            values=["English", "Japanese", "Vietnamese"],
            variable=self.tgt_var,
            width=220,
            command=lambda v: self._save_lang_choice()
        )
        self.tgt_menu.pack(side="left")

    # -------------------------------------------------------------------------
    # Drop Zone
    # -------------------------------------------------------------------------

    def _build_dropzone(self):
        self.drop_zone = DropZone(
            self.body_scroll,
            on_file_selected=self._on_file_selected,
            get_translation=self.i18n.t
        )
        self.drop_zone.pack(fill="x", pady=(0, 15))

    # -------------------------------------------------------------------------
    # Options Card (collapsible)
    # -------------------------------------------------------------------------

    def _build_options_card(self):
        self.options_card = ctk.CTkFrame(self.body_scroll, corner_radius=10)
        self.options_card.pack(fill="x", pady=(0, 15))

        # Header row with toggle button
        self.options_header = ctk.CTkFrame(self.options_card, fg_color="transparent")
        self.options_header.pack(fill="x", padx=16, pady=12)
        self.options_header.grid_columnconfigure(0, weight=1)

        self.options_title = ctk.CTkLabel(
            self.options_header,
            text=self.i18n.t("options_toggle_show"),
            font=ctk.CTkFont(size=14, weight="bold"),
            cursor="hand2"
        )
        self.options_title.grid(row=0, column=0, sticky="w")
        self.options_title.bind("<Button-1>", lambda e: self._toggle_options())

        self.options_toggle_btn = ctk.CTkButton(
            self.options_header,
            text="＋",
            width=28,
            height=28,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color="transparent",
            text_color=("gray30", "gray70"),
            hover_color=("gray80", "gray30"),
            command=self._toggle_options
        )
        self.options_toggle_btn.grid(row=0, column=1, sticky="e")

        # Collapsible body — hidden by default
        self.options_body = ctk.CTkFrame(self.options_card, fg_color="transparent")
        # Not packed initially (collapsed)

        # Checkbox 1: Keep terms untranslated
        self.keep_it_var = ctk.BooleanVar(value=self.config.translation_options.keep_it_terms)
        self.keep_it_cb = ctk.CTkCheckBox(
            self.options_body,
            text=self.i18n.t("opt_keep_terms"),
            variable=self.keep_it_var,
            font=ctk.CTkFont(size=12),
            command=self._save_options
        )
        self.keep_it_cb.pack(anchor="w", padx=16, pady=(8, 6))

        # Checkbox 2: Append original words in parentheses
        self.append_source_var = ctk.BooleanVar(value=self.config.translation_options.append_original_words)
        self.append_source_cb = ctk.CTkCheckBox(
            self.options_body,
            text=self.i18n.t("opt_append_source"),
            variable=self.append_source_var,
            font=ctk.CTkFont(size=12),
            command=self._save_options
        )
        self.append_source_cb.pack(anchor="w", padx=16, pady=(0, 6))

        # Checkbox 3: Bilingual Mode (Excel)
        self.bilingual_var = ctk.BooleanVar(value=self.config.translation_options.bilingual_mode)
        self.bilingual_cb = ctk.CTkCheckBox(
            self.options_body,
            text=self.i18n.t("opt_bilingual"),
            variable=self.bilingual_var,
            font=ctk.CTkFont(size=12),
            command=self._save_options
        )
        self.bilingual_cb.pack(anchor="w", padx=16, pady=(0, 8))

        # Output Format Selector
        fmt_frame = ctk.CTkFrame(self.options_body, fg_color="transparent")
        fmt_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.fmt_label = ctk.CTkLabel(
            fmt_frame,
            text=self.i18n.t("output_format_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.fmt_label.pack(side="left", padx=(0, 12))

        self._update_format_mappings()
        self.output_format_var = ctk.StringVar(value=self.fmt_display_map["auto"])
        self.fmt_segmented = ctk.CTkSegmentedButton(
            fmt_frame,
            values=[self.fmt_display_map["auto"], self.fmt_display_map["xlsx"], self.fmt_display_map["md"]],
            variable=self.output_format_var,
            height=30
        )
        self.fmt_segmented.pack(side="left", fill="x", expand=True)

        # Custom Context Prompt Label
        self.custom_prompt_label = ctk.CTkLabel(
            self.options_body,
            text=self.i18n.t("custom_prompt_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.custom_prompt_label.pack(anchor="w", padx=16, pady=(4, 4))

        # Custom Context Textbox
        self.custom_prompt_text = ctk.CTkTextbox(self.options_body, height=65, font=ctk.CTkFont(size=12))
        self.custom_prompt_text.pack(fill="x", padx=16, pady=(0, 14))
        if self.config.translation_options.custom_context:
            self.custom_prompt_text.insert("1.0", self.config.translation_options.custom_context)

        self.custom_prompt_text.bind("<KeyRelease>", lambda e: self._save_options())

    def _toggle_options(self):
        self._options_expanded = not self._options_expanded
        if self._options_expanded:
            self.options_header.pack_configure(pady=(12, 0))
            self.options_body.pack(fill="x")
            self.options_toggle_btn.configure(text="－")
            self.options_title.configure(text=self.i18n.t("options_toggle_hide"))
        else:
            self.options_body.pack_forget()
            self.options_header.pack_configure(pady=12)
            self.options_toggle_btn.configure(text="＋")
            self.options_title.configure(text=self.i18n.t("options_toggle_show"))

    # -------------------------------------------------------------------------
    # Convert Panel
    # -------------------------------------------------------------------------

    def _build_convert_panel(self):
        self.convert_panel = ctk.CTkFrame(self.body_scroll, corner_radius=10)
        # Not packed initially — shown only in convert mode

        header_row = ctk.CTkFrame(self.convert_panel, fg_color="transparent")
        header_row.pack(fill="x", padx=16, pady=(12, 8))

        self.convert_panel_title = ctk.CTkLabel(
            header_row,
            text=self.i18n.t("convert_panel_title"),
            font=ctk.CTkFont(size=14, weight="bold")
        )
        self.convert_panel_title.pack(side="left")

        # Conversion hint badge/card — updated based on selected file
        self.convert_hint_label = ctk.CTkLabel(
            self.convert_panel,
            text=self.i18n.t("convert_hint_none"),
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=("gray40", "gray60"),
            fg_color=("gray90", "#1E293B"),
            corner_radius=8,
            padx=14,
            pady=10,
            wraplength=640,
            justify="left"
        )
        self.convert_hint_label.pack(fill="x", padx=16, pady=(0, 14))

    def _refresh_convert_hint(self):
        """Update the convert hint label based on the currently selected file."""
        if not hasattr(self, "convert_hint_label"):
            return
        if not self.selected_file:
            self.convert_hint_label.configure(
                text="📁 " + self.i18n.t("convert_hint_none"),
                text_color=("gray40", "gray60")
            )
            return
        ext = Path(self.selected_file).suffix.lower()
        if ext == ".xlsx":
            self.convert_hint_label.configure(
                text="📊 " + self.i18n.t("convert_hint_xlsx"),
                text_color=("#047857", "#34D399")
            )
        elif ext == ".md":
            self.convert_hint_label.configure(
                text="📝 " + self.i18n.t("convert_hint_md"),
                text_color=("#6D28D9", "#A78BFA")
            )
        else:
            self.convert_hint_label.configure(
                text="⚠️ " + self.i18n.t("convert_hint_none"),
                text_color=("gray40", "gray60")
            )

    # -------------------------------------------------------------------------
    # Action Bar
    # -------------------------------------------------------------------------

    def _build_action_bar(self):
        self.action_bar = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color=("gray92", "#182234"),
            border_width=1,
            border_color=("gray80", "#334155")
        )
        self.action_bar.grid(row=2, column=0, sticky="ew", padx=0, pady=0)
        self.action_bar.grid_columnconfigure(0, weight=1)

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(self.action_bar, height=10)
        self.progress_bar.pack(fill="x", padx=20, pady=(12, 6))
        self.progress_bar.set(0)

        # Status text & shortcut hint row
        self.status_row = ctk.CTkFrame(self.action_bar, fg_color="transparent")
        self.status_row.pack(fill="x", padx=20, pady=(0, 6))
        self.status_row.grid_columnconfigure(0, weight=1)
        self.status_row.grid_columnconfigure(1, weight=0)

        self.status_label = ctk.CTkLabel(
            self.status_row,
            text=self.i18n.t("status_ready"),
            font=ctk.CTkFont(size=12),
            text_color="gray",
            anchor="w",
            justify="left",
            wraplength=560
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

        self.shortcut_hint_label = ctk.CTkLabel(
            self.status_row,
            text=self.i18n.t("shortcut_hint"),
            font=ctk.CTkFont(size=11),
            text_color=("gray50", "gray60")
        )
        self.shortcut_hint_label.grid(row=0, column=1, sticky="e", padx=(10, 0))

        self.status_row.bind("<Configure>", self._update_status_wraplength)

        # Buttons row
        btn_row = ctk.CTkFrame(self.action_bar, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 14))

        # Action button container (hosts translate_btn OR convert_btn)
        self.action_btn_container = ctk.CTkFrame(btn_row, fg_color="transparent")
        self.action_btn_container.pack(side="left", padx=(0, 10), expand=True, fill="x")

        # Translate button (translate mode)
        self.translate_btn = ctk.CTkButton(
            self.action_btn_container,
            text=self.i18n.t("start_translation"),
            command=self._start_translation,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            fg_color="#10B981",
            hover_color="#059669"
        )
        self.translate_btn.pack(fill="both", expand=True)

        # Convert button (convert mode) — hidden by default
        self.convert_btn = ctk.CTkButton(
            self.action_btn_container,
            text=self.i18n.t("start_conversion"),
            command=self._start_conversion,
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            fg_color="#7C3AED",
            hover_color="#6D28D9"
        )
        # Hidden initially

        self.cancel_btn = ctk.CTkButton(
            btn_row,
            text=self.i18n.t("cancel"),
            command=self._cancel_translation,
            font=ctk.CTkFont(size=13),
            height=40,
            width=90,
            fg_color="#EF4444",
            hover_color="#DC2626"
        )
        # Cancel button is hidden by default

        self.open_file_btn = ctk.CTkButton(
            btn_row,
            text="📄 " + self.i18n.t("open_file"),
            command=self._open_output_file,
            font=ctk.CTkFont(size=13, weight="bold"),
            height=40,
            fg_color="#3B8ED0",
            hover_color="#2563EB"
        )
        # Open file button is hidden by default

        self.open_folder_btn = ctk.CTkButton(
            btn_row,
            text=self.i18n.t("open_folder"),
            command=self._open_output_directory,
            font=ctk.CTkFont(size=13),
            height=40,
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80")
        )
        # Open folder button is hidden by default

        self.save_as_btn = ctk.CTkButton(
            btn_row,
            text=self.i18n.t("save_as"),
            command=self._save_output_as,
            font=ctk.CTkFont(size=13),
            height=40,
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80")
        )
        # Save as button is hidden by default

        self.error_btn = ctk.CTkButton(
            btn_row,
            text=self.i18n.t("view_error_details"),
            command=self._show_error_modal,
            font=ctk.CTkFont(size=12, weight="bold"),
            height=40,
            fg_color="#DC2626",
            hover_color="#B91C1C"
        )
        # Error button is hidden by default

    # -------------------------------------------------------------------------
    # Error Modal
    # -------------------------------------------------------------------------

    def _show_error_modal(self):
        if self.last_diagnostic:
            ErrorModal(
                self,
                diag=self.last_diagnostic,
                on_retry=self._start_translation,
                on_open_settings=self._open_settings,
                get_translation=self.i18n.t
            )

    # -------------------------------------------------------------------------
    # Save As
    # -------------------------------------------------------------------------

    def _save_output_as(self):
        if not self.last_output_file or not Path(self.last_output_file).exists():
            return

        src_path = Path(self.last_output_file)
        ext = src_path.suffix.lower()
        filetypes = [
            (f"Document (*{ext})", f"*{ext}"),
            ("All Files", "*.*")
        ]
        chosen = filedialog.asksaveasfilename(
            title="Save Copy As",
            initialdir=str(src_path.parent),
            initialfile=src_path.name,
            filetypes=filetypes
        )
        if chosen:
            import shutil
            shutil.copy2(self.last_output_file, chosen)
            self._set_status(f"Saved copy to: {Path(chosen).name}", text_color="#10B981")

    # -------------------------------------------------------------------------
    # Keyboard Shortcuts
    # -------------------------------------------------------------------------

    def _setup_shortcuts(self):
        """Bind ergonomic keyboard shortcuts for power users."""
        def on_open(event=None):
            self.drop_zone._browse_file()
            return "break"

        def on_action(event=None):
            if self.is_translating:
                return "break"
            if self._mode == "convert":
                self._start_conversion()
            else:
                self._start_translation()
            return "break"

        def on_cancel(event=None):
            if self.is_translating:
                self._cancel_translation()
            return "break"

        def on_settings(event=None):
            self._open_settings()
            return "break"

        # macOS bindings
        self.bind("<Command-o>", on_open)
        self.bind("<Command-Return>", on_action)
        self.bind("<Command-comma>", on_settings)

        # Windows / Linux bindings
        self.bind("<Control-o>", on_open)
        self.bind("<Control-Return>", on_action)
        self.bind("<Control-comma>", on_settings)

        # Universal Escape to cancel
        self.bind("<Escape>", on_cancel)

    # -------------------------------------------------------------------------
    # File Selection
    # -------------------------------------------------------------------------

    def _on_file_selected(self, file_path: str):
        self.selected_file = file_path if file_path else None
        self.open_folder_btn.pack_forget()
        self.open_file_btn.pack_forget()
        self.save_as_btn.pack_forget()
        self.error_btn.pack_forget()
        if self.selected_file:
            self.status_label.configure(
                text=f"{self.i18n.t('status_ready')}: {Path(file_path).name}",
                text_color=("gray20", "gray80")
            )
        else:
            self.status_label.configure(text=self.i18n.t("status_ready"), text_color="gray")
        # Refresh convert hint whenever a file is selected/cleared
        self._refresh_convert_hint()

    # -------------------------------------------------------------------------
    # Language helpers
    # -------------------------------------------------------------------------

    def _save_lang_choice(self):
        self.config.target_language = self.tgt_var.get()
        self.config.save()

    def _save_options(self):
        self.config.translation_options.keep_it_terms = self.keep_it_var.get()
        self.config.translation_options.append_original_words = self.append_source_var.get()
        self.config.translation_options.bilingual_mode = self.bilingual_var.get()
        self.config.translation_options.custom_context = self.custom_prompt_text.get("1.0", "end-1c").strip()
        self.config.save()

    def _update_format_mappings(self):
        self.fmt_display_map = {
            "auto": self.i18n.t("fmt_auto"),
            "xlsx": self.i18n.t("fmt_excel"),
            "md": self.i18n.t("fmt_markdown")
        }
        self.fmt_value_map = {v: k for k, v in self.fmt_display_map.items()}

    # -------------------------------------------------------------------------
    # Settings
    # -------------------------------------------------------------------------

    def _open_settings(self):
        SettingsModal(
            self,
            config=self.config,
            get_translation=self.i18n.t,
            on_save_callback=self._on_settings_saved
        )

    def _on_settings_saved(self, updated_config: AppConfig):
        self.config = updated_config
        self.i18n.set_language(self.config.ui_language)
        self.provider_badge.configure(
            text=f"AI: {self.config.active_provider} ({self.config.get_active_model()})"
        )
        self.refresh_ui_texts()

    def refresh_ui_texts(self):
        """Update all on-screen text when language changes."""
        self.title(f"{self.i18n.t('app_title')} - {self.i18n.t('app_subtitle')}")
        if self.logo_image:
            self.logo_label.configure(text="  " + self.i18n.t("app_title"))
        else:
            self.logo_label.configure(text="🌐 " + self.i18n.t("app_title"))
        self.subtitle_label.configure(text=self.i18n.t("app_subtitle"))
        self.settings_btn.configure(text=f"⚙ {self.i18n.t('settings_btn')}")

        self.tgt_label.configure(text=self.i18n.t("target_lang"))

        self.drop_zone.refresh_i18n()

        # Options card
        if self._options_expanded:
            self.options_title.configure(text=self.i18n.t("options_toggle_hide"))
        else:
            self.options_title.configure(text=self.i18n.t("options_toggle_show"))
        self.keep_it_cb.configure(text=self.i18n.t("opt_keep_terms"))
        self.append_source_cb.configure(text=self.i18n.t("opt_append_source"))
        self.bilingual_cb.configure(text=self.i18n.t("opt_bilingual"))

        old_fmt_key = self.fmt_value_map.get(self.output_format_var.get(), "auto")
        self._update_format_mappings()
        self.fmt_label.configure(text=self.i18n.t("output_format_label"))
        self.fmt_segmented.configure(
            values=[self.fmt_display_map["auto"], self.fmt_display_map["xlsx"], self.fmt_display_map["md"]]
        )
        self.output_format_var.set(self.fmt_display_map.get(old_fmt_key, self.fmt_display_map["auto"]))
        self.custom_prompt_label.configure(text=self.i18n.t("custom_prompt_label"))

        # Mode switcher
        old_mode = self._mode
        self.mode_switcher.configure(
            values=[self.i18n.t("mode_translate"), self.i18n.t("mode_convert")]
        )
        if old_mode == "convert":
            self.mode_var.set(self.i18n.t("mode_convert"))
        else:
            self.mode_var.set(self.i18n.t("mode_translate"))

        # Convert panel
        if hasattr(self, "convert_panel_title"):
            self.convert_panel_title.configure(text=self.i18n.t("convert_panel_title"))
        self._refresh_convert_hint()

        # Action bar
        self.translate_btn.configure(text=self.i18n.t("start_translation"))
        self.convert_btn.configure(text=self.i18n.t("start_conversion"))
        self.cancel_btn.configure(text=self.i18n.t("cancel"))
        self.open_file_btn.configure(text="📄 " + self.i18n.t("open_file"))
        self.open_folder_btn.configure(text=self.i18n.t("open_folder"))
        self.save_as_btn.configure(text=self.i18n.t("save_as"))
        self.error_btn.configure(text=self.i18n.t("view_error_details"))

        # Re-apply mode visibility to update subtitle, provider badge, and shortcuts
        self._apply_mode_visibility()

        if not self.is_translating:
            self.status_label.configure(text=self.i18n.t("status_ready"))

    # -------------------------------------------------------------------------
    # Translation
    # -------------------------------------------------------------------------

    def _start_translation(self):
        # Validation checks
        if not self.selected_file:
            self._set_status(self.i18n.t("err_no_file"), is_error=True)
            return

        tgt_lang = self.tgt_var.get()

        # Check API key
        active_key = self.config.get_effective_api_key()
        if not active_key:
            self._set_status(
                self.i18n.t("err_no_api_key", provider=self.config.active_provider),
                is_error=True
            )
            self._open_settings()
            return

        self._save_options()
        self.is_translating = True
        self.open_folder_btn.pack_forget()
        self.open_file_btn.pack_forget()
        self.save_as_btn.pack_forget()
        self.error_btn.pack_forget()

        # Update UI controls
        self.translate_btn.configure(state="disabled", text=self.i18n.t("translating"))
        self.cancel_btn.pack(side="left", padx=(0, 10))
        self.progress_bar.set(0)
        self._set_status(self.i18n.t("status_loading_file"))

        # Spawn background translation thread
        self.current_thread = threading.Thread(
            target=self._run_translation_worker,
            args=(self.selected_file, tgt_lang),
            daemon=True
        )
        self.current_thread.start()

    def _cancel_translation(self):
        if self.is_translating:
            self.excel_translator.cancel()
            self.markdown_translator.cancel()
            self._set_status("Cancelling translation...", is_error=False)

    def _run_translation_worker(self, file_path: str, tgt_lang: str):
        try:
            path = Path(file_path)
            ext = path.suffix.lower()

            def on_progress(current: int, total: int, msg: str):
                fraction = current / max(1, total)
                self.after(0, lambda: self._update_progress(fraction, msg))

            if ext == ".xlsx":
                output_file = self.excel_translator.process_file(
                    file_path=file_path,
                    target_lang=tgt_lang,
                    options=self.config.translation_options,
                    progress_callback=on_progress
                )
            elif ext == ".md":
                output_file = self.markdown_translator.process_file(
                    file_path=file_path,
                    target_lang=tgt_lang,
                    options=self.config.translation_options,
                    progress_callback=on_progress
                )
            else:
                raise ValueError(self.i18n.t("err_unsupported_file"))

            # Cross-format conversion if requested by user
            chosen_key = self.fmt_value_map.get(self.output_format_var.get(), "auto")
            if chosen_key != "auto":
                final_out = convert_translated_output(output_file, chosen_key)
                if final_out != output_file:
                    output_file = final_out

            self.last_output_file = output_file
            self.after(0, lambda: self._on_translation_completed(output_file))

        except InterruptedError:
            self.after(0, lambda: self._on_translation_cancelled())
        except Exception as e:
            self.after(0, lambda err=e: self._on_translation_failed(str(err), exc=err))

    def _update_progress(self, fraction: float, message: str):
        self.progress_bar.set(fraction)
        self._set_status(message)

    def _on_translation_completed(self, output_path: str):
        self.is_translating = False
        self.progress_bar.set(1.0)
        out_name = Path(output_path).name
        self._set_status(self.i18n.t("status_completed", filename=out_name), text_color="#10B981")

        self.translate_btn.configure(state="normal", text=self.i18n.t("start_translation"))
        self.cancel_btn.pack_forget()
        self.error_btn.pack_forget()
        self.open_file_btn.pack(side="left", padx=(0, 10))
        self.open_folder_btn.pack(side="left", padx=(0, 10))
        self.save_as_btn.pack(side="left", padx=(0, 10))

        # Audio completion cue & native OS notification
        try:
            import sys
            sys.stdout.write('\a')
            sys.stdout.flush()
        except Exception:
            pass

        system_os = platform.system()
        if system_os == "Darwin":
            try:
                subprocess.Popen([
                    "osascript", "-e",
                    f'display notification "{out_name}" with title "RakuTrans AI" subtitle "Translation Completed"'
                ])
            except Exception:
                pass

    def _on_translation_cancelled(self):
        self.is_translating = False
        self.progress_bar.set(0)
        self._set_status("Translation cancelled by user.", text_color="orange")
        self.translate_btn.configure(state="normal", text=self.i18n.t("start_translation"))
        self.cancel_btn.pack_forget()
        self.error_btn.pack_forget()

    def _on_translation_failed(self, error_msg: str, exc: Optional[Exception] = None):
        self.is_translating = False
        self.progress_bar.set(0)
        self.last_diagnostic = diagnose_error(exc if exc else Exception(error_msg), self.i18n)
        short_summary = f"{self.last_diagnostic.title}: {self.last_diagnostic.message}"
        self._set_status(short_summary, is_error=True)
        self.translate_btn.configure(state="normal", text=self.i18n.t("start_translation"))
        self.cancel_btn.pack_forget()
        self.error_btn.pack(side="left", padx=(0, 10))
        self._show_error_modal()

    # -------------------------------------------------------------------------
    # Conversion (no translate)
    # -------------------------------------------------------------------------

    def _start_conversion(self):
        if not self.selected_file:
            self._set_status(self.i18n.t("err_convert_no_file"), is_error=True)
            return

        ext = Path(self.selected_file).suffix.lower()
        options = get_convert_options(ext)
        if not options:
            self._set_status(self.i18n.t("err_convert_same_format"), is_error=True)
            return

        target_fmt = options[0]  # Only one option per source type

        self.is_translating = True  # Reuse flag to block concurrent actions
        self.open_folder_btn.pack_forget()
        self.open_file_btn.pack_forget()
        self.save_as_btn.pack_forget()
        self.error_btn.pack_forget()

        self.convert_btn.configure(state="disabled", text=self.i18n.t("converting"))
        self.progress_bar.set(0)
        self._set_status(self.i18n.t("converting"))

        def worker():
            try:
                self.after(0, lambda: self.progress_bar.set(0.3))
                output_file = convert_file_direct(self.selected_file, target_fmt)
                self.after(0, lambda: self.progress_bar.set(1.0))
                self.last_output_file = output_file
                self.after(0, lambda f=output_file: self._on_conversion_completed(f))
            except Exception as e:
                self.after(0, lambda err=e: self._on_conversion_failed(str(err)))

        threading.Thread(target=worker, daemon=True).start()

    def _on_conversion_completed(self, output_path: str):
        self.is_translating = False
        out_name = Path(output_path).name
        self._set_status(self.i18n.t("status_convert_completed", filename=out_name), text_color="#10B981")
        self.convert_btn.configure(state="normal", text=self.i18n.t("start_conversion"))
        self.cancel_btn.pack_forget()
        self.error_btn.pack_forget()
        self.open_file_btn.pack(side="left", padx=(0, 10))
        self.open_folder_btn.pack(side="left", padx=(0, 10))
        self.save_as_btn.pack(side="left", padx=(0, 10))

        system_os = platform.system()
        if system_os == "Darwin":
            try:
                subprocess.Popen([
                    "osascript", "-e",
                    f'display notification "{out_name}" with title "RakuTrans AI" subtitle "Conversion Completed"'
                ])
            except Exception:
                pass

    def _on_conversion_failed(self, error_msg: str):
        self.is_translating = False
        self.progress_bar.set(0)
        self._set_status(f"Conversion failed: {error_msg}", is_error=True)
        self.convert_btn.configure(state="normal", text=self.i18n.t("start_conversion"))
        self.cancel_btn.pack_forget()

    # -------------------------------------------------------------------------
    # Open File / Folder
    # -------------------------------------------------------------------------

    def _open_output_file(self):
        if not self.last_output_file or not Path(self.last_output_file).exists():
            return

        file_path = str(Path(self.last_output_file).resolve())
        system_os = platform.system()
        try:
            if system_os == "Darwin":
                subprocess.Popen(["open", file_path])
            elif system_os == "Windows":
                os.startfile(file_path)
            else:
                subprocess.Popen(["xdg-open", file_path])
        except Exception as e:
            print(f"[Warning] Failed to open file: {e}")

    def _open_output_directory(self):
        if not self.last_output_file:
            return

        folder = Path(self.last_output_file).parent
        system_os = platform.system()
        try:
            if system_os == "Darwin":
                subprocess.Popen(["open", str(folder)])
            elif system_os == "Windows":
                os.startfile(str(folder))
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception as e:
            print(f"[Warning] Failed to open folder: {e}")

    # -------------------------------------------------------------------------
    # Status helper
    # -------------------------------------------------------------------------

    def _update_status_wraplength(self, event=None):
        """Dynamically adapt status_label wraplength to prevent text overflow on narrow windows."""
        try:
            if event is not None and hasattr(event, "width") and event.width > 50:
                total_w = event.width
            else:
                total_w = self.status_row.winfo_width()

            if total_w > 100:
                hint_w = self.shortcut_hint_label.winfo_reqwidth() if self.shortcut_hint_label.winfo_ismapped() else 0
                available_w = max(180, total_w - hint_w - 24)
                self.status_label.configure(wraplength=available_w)
        except Exception:
            pass

    def _set_status(self, text: str, is_error: bool = False, text_color: Optional[str] = None):
        self._update_status_wraplength()
        if is_error:
            self.status_label.configure(text=text, text_color="#EF4444")
        elif text_color:
            self.status_label.configure(text=text, text_color=text_color)
        else:
            self.status_label.configure(text=text, text_color=("gray20", "gray80"))
