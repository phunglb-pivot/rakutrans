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
from PIL import Image, ImageTk

from config import AppConfig
from i18n import I18nManager
from llm_manager import LLMManager
from excel_parser import ExcelTranslator
from markdown_parser import MarkdownTranslator
from translator_registry import TranslatorRegistry
from base_translator import BaseTranslator
from translation_cache import TranslationCache
from format_converter import convert_file_direct, get_convert_options
from components.dnd_zone import DropZone
from components.settings_modal import SettingsView
from components.error_modal import ErrorModal
from components.searchable_select import SearchableLanguageSelect
from components.ui_system import CustomButton
from components.confirm_modal import ConfirmModal
from components.icons import get_icon, init_windows_app_id, apply_windows_window_icon
from error_handler import diagnose_error, DiagnosticInfo

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
        init_windows_app_id()
        super().__init__()
        self.withdraw()  # Hide window while loading assets and constructing layout

        # Load config and i18n
        self.config = config or AppConfig.load()
        self.i18n = I18nManager(self.config.ui_language)
        self.llm_manager = LLMManager(self.config)
        self.cache = TranslationCache()

        # Active translators sharing the local translation memory cache
        self.excel_translator = ExcelTranslator(self.config, self.llm_manager, cache=self.cache)
        self.markdown_translator = MarkdownTranslator(self.config, self.llm_manager, cache=self.cache)
        self.current_translator: Optional[BaseTranslator] = None

        # Runtime states
        self.selected_file: Optional[str] = None
        self.last_output_file: Optional[str] = None
        self.is_translating: bool = False
        self.current_thread: Optional[threading.Thread] = None
        self.last_diagnostic: Optional[DiagnosticInfo] = None
        self.last_exception: Optional[Exception] = None
        self.last_convert_error: Optional[str] = None
        self.current_button_state: str = "idle_no_file"

        # Screen state ("main" vs in-page "settings")
        self.current_screen: str = "main"

        # Format Converter mode states
        self.current_mode: str = "translate"  # "translate" or "convert"
        self.selected_convert_file: Optional[str] = None
        self.selected_target_format: Optional[str] = None
        self.last_convert_output_file: Optional[str] = None
        self.is_converting: bool = False

        # Whether options card body is expanded
        self._options_expanded: bool = False

        # Window configuration
        self.title("")
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

        # Load custom logo / window icon and sync OS Dock / Taskbar icon immediately
        self.logo_image = None
        base_assets = Path(__file__).resolve().parent / "assets"
        logo_path = base_assets / "logo.png"
        icns_path = base_assets / "icon.icns"
        ico_path = base_assets / "icon.ico"

        if platform.system() == "Windows":
            apply_windows_window_icon(self, ico_path)

        if logo_path.exists():
            try:
                pil_logo = Image.open(logo_path)
                self.logo_image = ctk.CTkImage(light_image=pil_logo, dark_image=pil_logo, size=(28, 28))
                if platform.system() != "Darwin":
                    self._window_icon = ImageTk.PhotoImage(pil_logo)
                    self.iconphoto(True, self._window_icon)
            except Exception as e:
                print(f"[Warning] Failed to load logo from {logo_path}: {e}")

        # Synchronize macOS Dock icon immediately via Cocoa runtime
        if platform.system() == "Darwin":
            try:
                import ctypes
                import ctypes.util
                objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
                appkit = ctypes.cdll.LoadLibrary(ctypes.util.find_library("AppKit"))

                objc.objc_getClass.restype = ctypes.c_void_p
                objc.objc_getClass.argtypes = [ctypes.c_char_p]
                objc.sel_registerName.restype = ctypes.c_void_p
                objc.sel_registerName.argtypes = [ctypes.c_char_p]

                NSApp_cls = objc.objc_getClass(b"NSApplication")
                sel_shared = objc.sel_registerName(b"sharedApplication")
                objc.objc_msgSend.restype = ctypes.c_void_p
                objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                ns_app = objc.objc_msgSend(NSApp_cls, sel_shared)

                target_icon = icns_path if icns_path.exists() else logo_path
                if target_icon.exists():
                    NSString_cls = objc.objc_getClass(b"NSString")
                    sel_strWithUtf8 = objc.sel_registerName(b"stringWithUTF8String:")
                    objc.objc_msgSend.restype = ctypes.c_void_p
                    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p]
                    ns_path = objc.objc_msgSend(NSString_cls, sel_strWithUtf8, str(target_icon).encode("utf-8"))

                    NSImage_cls = objc.objc_getClass(b"NSImage")
                    sel_alloc = objc.sel_registerName(b"alloc")
                    sel_initWithFile = objc.sel_registerName(b"initWithContentsOfFile:")
                    objc.objc_msgSend.restype = ctypes.c_void_p
                    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
                    alloc_img = objc.objc_msgSend(NSImage_cls, sel_alloc)

                    objc.objc_msgSend.restype = ctypes.c_void_p
                    objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                    ns_img = objc.objc_msgSend(alloc_img, sel_initWithFile, ns_path)

                    if ns_img:
                        sel_setIcon = objc.sel_registerName(b"setApplicationIconImage:")
                        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
                        objc.objc_msgSend(ns_app, sel_setIcon, ns_img)
            except Exception as e:
                print(f"[Warning] Failed to synchronize macOS Dock icon: {e}")

        self._setup_ui()
        self.update_idletasks()
        # Reset CustomTkinter's early-withdraw flag before mainloop() on Windows;
        # otherwise CTk.mainloop() calls _windows_set_titlebar_color() which
        # withdraws the window and skips deiconify() when the flag is True.
        if hasattr(self, "_withdraw_called_before_window_exists"):
            self._withdraw_called_before_window_exists = False
        self.deiconify()
        self.update()
        self.lift()

    def _setup_ui(self):
        # Configure layout: Row 0 Header, Row 1 Nav Tabs, Row 2 Scrollable Body, Row 3 Sticky Bottom Bar
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=0)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)

        # --------------------------------------------------------------------
        # Top Header Bar
        # --------------------------------------------------------------------
        self.header_frame = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color="transparent"
        )
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
                text="  " + self.i18n.t("app_title"),
                image=get_icon("globe", "default", 22),
                compound="left",
                font=ctk.CTkFont(size=20, weight="bold")
            )
        self.logo_label.pack(anchor="w")

        self.subtitle_label = ctk.CTkLabel(
            brand_frame,
            text=self.i18n.t("app_subtitle"),
            font=ctk.CTkFont(size=12),
            text_color=("#71717A", "#A1A1AA")
        )
        self.subtitle_label.pack(anchor="w")

        # Header Right Controls (Active Model Badge & Settings Button)
        right_header = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        right_header.grid(row=0, column=2, sticky="e", padx=20, pady=12)

        self.provider_badge = ctk.CTkLabel(
            right_header,
            text=f"AI: {self.config.active_provider} ({self.config.get_active_model()})",
            font=ctk.CTkFont(size=11),
            fg_color=("#F4F4F5", "#27272A"),
            text_color=("#71717A", "#A1A1AA"),
            corner_radius=6,
            padx=10,
            pady=4
        )
        self.provider_badge.pack(side="left", padx=(0, 10))

        self.settings_btn = CustomButton(
            right_header,
            text=self.i18n.t("settings_btn"),
            variant="secondary",
            size="md",
            width=106,
            icon_name="settings",
            icon_size=15,
            command=self._open_settings
        )
        self.settings_btn.pack(side="left")

        # --------------------------------------------------------------------
        # Navigation Bar: Translate vs Format Converter (Parallel Features)
        # --------------------------------------------------------------------
        self.nav_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.nav_frame.grid(row=1, column=0, sticky="ew", padx=20, pady=(12, 0))
        self.nav_frame.grid_columnconfigure(0, weight=1)

        self.tab_translate_label = self.i18n.t("tab_translate")
        self.tab_convert_label = self.i18n.t("tab_convert")

        self.mode_segmented = ctk.CTkSegmentedButton(
            self.nav_frame,
            values=[self.tab_translate_label, self.tab_convert_label],
            command=self._on_mode_switched,
            height=36,
            border_width=1,
            font=ctk.CTkFont(size=13, weight="bold"),
            selected_color=("#D4D4D8", "#3F3F46"),
            selected_hover_color=("#C4C4C8", "#52525B"),
            unselected_color=("#F4F4F5", "#18181B"),
            unselected_hover_color=("#E4E4E7", "#27272A"),
            text_color=("#18181B", "#FAFAFA")
        )
        self.mode_segmented.grid_columnconfigure(0, weight=1, uniform="mode_tabs")
        self.mode_segmented.grid_columnconfigure(1, weight=1, uniform="mode_tabs")
        self.mode_segmented.set(self.tab_translate_label)
        self._apply_mode_tab_icons()
        self.mode_segmented.pack(fill="x")

        # --------------------------------------------------------------------
        # Main Scrollable Body
        # --------------------------------------------------------------------
        self.body_scroll = ctk.CTkScrollableFrame(self, corner_radius=0, fg_color="transparent")
        self.body_scroll.grid(row=2, column=0, sticky="nsew", padx=20, pady=(12, 5))
        self.body_scroll.grid_columnconfigure(0, weight=1)
        self._enable_autohide_scrollbar(self.body_scroll)

        # Feature Container 1: Translation View
        self.translate_container = ctk.CTkFrame(self.body_scroll, fg_color="transparent")
        self.translate_container.pack(fill="both", expand=True)

        # 1. Language Selection Card
        self._build_language_card(self.translate_container)

        # 2. File Drag & Drop Zone (Translation)
        self._build_dropzone(self.translate_container)

        # 3. Translation Options Card (collapsible)
        self._build_options_card(self.translate_container)

        # Feature Container 2: Format Converter View (Hidden by default)
        self.convert_container = ctk.CTkFrame(self.body_scroll, fg_color="transparent")

        # 1. File Drag & Drop Zone (Conversion)
        self._build_convert_dropzone(self.convert_container)

        # 2. Convert Options & Target Format Card
        self._build_convert_options_card(self.convert_container)

        # --------------------------------------------------------------------
        # Sticky Action Bar (Row 3, always visible at bottom)
        # --------------------------------------------------------------------
        self._build_action_bar()

        # --------------------------------------------------------------------
        # In-Page Settings View (Row 1-3, hidden by default, replaces main workspace)
        # --------------------------------------------------------------------
        self.settings_view = SettingsView(
            self,
            config=self.config,
            get_translation=self.i18n.t,
            on_save_callback=self._on_settings_changed,
            on_close_callback=self._close_settings
        )

        # Global Keyboard Shortcuts
        self._setup_shortcuts()

    def _enable_autohide_scrollbar(self, scrollable_frame: ctk.CTkScrollableFrame):
        """Dynamically hides the scrollbar when content fits inside the window without scrolling."""
        orig_set = scrollable_frame._scrollbar.set
        canvas = scrollable_frame._parent_canvas
        scrollbar = scrollable_frame._scrollbar
        border_spacing = scrollable_frame._apply_widget_scaling(
            scrollable_frame._parent_frame.cget("corner_radius") + scrollable_frame._parent_frame.cget("border_width")
        )
        border_padding = (0, scrollable_frame._border_width + 1)

        def autohide_set(start_value: float, end_value: float):
            orig_set(start_value, end_value)
            try:
                start = float(start_value)
                end = float(end_value)
                if start <= 0.0 and end >= 1.0:
                    if scrollbar.winfo_ismapped():
                        scrollbar.grid_remove()
                else:
                    if not scrollbar.winfo_ismapped():
                        scrollbar.grid(row=1, column=1, sticky="nsew", padx=border_padding, pady=border_spacing)
            except Exception:
                pass

        canvas.configure(yscrollcommand=autohide_set)
        self.after(50, lambda: autohide_set(*canvas.yview()))

    # -------------------------------------------------------------------------
    # Language Card
    # -------------------------------------------------------------------------

    def _build_language_card(self, parent=None):
        target_parent = parent or self.body_scroll
        self.lang_card = ctk.CTkFrame(
            target_parent,
            fg_color="transparent"
        )
        self.lang_card.pack(fill="x", pady=(0, 12))

        row = ctk.CTkFrame(self.lang_card, fg_color="transparent")
        row.pack(fill="x", padx=0, pady=0)

        self.tgt_label = ctk.CTkLabel(
            row, 
            text=self.i18n.t("target_lang"), 
            font=ctk.CTkFont(size=13, weight="bold")
        )
        # Pin to top (aligned with the 36px trigger) so it stays put when the list expands
        self.tgt_label.pack(side="left", padx=(0, 14), pady=(8, 0), anchor="n")

        self.tgt_var = ctk.StringVar(value=self.config.target_language)
        self.tgt_select = SearchableLanguageSelect(
            row,
            current_language=self.config.target_language,
            on_change=lambda v: self._save_lang_choice(),
            width=360,
            height=36,
            get_translation=self.i18n.t,
            on_open=self._hide_dropzone_for_lang,
            on_close=self._show_dropzone_after_lang,
            recent_languages=self.config.recent_target_languages
        )
        self.tgt_select.pack(side="left", fill="x", expand=True)

    def _hide_dropzone_for_lang(self) -> int:
        """Hides the drop zone while the language list is open; returns height for the list to match."""
        self.update_idletasks()
        # drop zone height + its bottom padding (15) - the list's top padding (4)
        height = self.drop_zone.winfo_height() + 11
        self.drop_zone.pack_forget()
        return height

    def _show_dropzone_after_lang(self):
        if not self.drop_zone.winfo_manager():
            self.drop_zone.pack(fill="x", pady=(0, 15), before=self.options_card)

    # -------------------------------------------------------------------------
    # Drop Zone
    # -------------------------------------------------------------------------

    def _build_dropzone(self, parent=None):
        target_parent = parent or self.body_scroll
        self.drop_zone = DropZone(
            target_parent,
            on_file_selected=self._on_file_selected,
            get_translation=self.i18n.t
        )
        self.drop_zone.pack(fill="x", pady=(0, 15))

    # -------------------------------------------------------------------------
    # Options Card (collapsible)
    # -------------------------------------------------------------------------

    def _build_options_card(self, parent=None):
        target_parent = parent or self.body_scroll
        self.options_card = ctk.CTkFrame(
            target_parent,
            fg_color="transparent"
        )
        self.options_card.pack(fill="x", pady=(0, 15))

        # Header row with toggle button
        self.options_header = ctk.CTkFrame(self.options_card, fg_color="transparent")
        self.options_header.pack(fill="x", padx=0, pady=(4, 6))
        self.options_header.grid_columnconfigure(0, weight=1)

        self.options_title = ctk.CTkLabel(
            self.options_header,
            text=self.i18n.t("options_toggle_show"),
            font=ctk.CTkFont(size=13, weight="bold"),
            cursor="hand2"
        )
        self.options_title.grid(row=0, column=0, sticky="w")
        self.options_title.bind("<Button-1>", lambda e: self._toggle_options())

        self.options_toggle_btn = CustomButton(
            self.options_header,
            text="",
            variant="ghost",
            size="sm",
            width=28,
            icon_name="plus",
            icon_size=14,
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
            fg_color=("#18181B", "#FAFAFA"),
            hover_color=("#27272A", "#E4E4E7"),
            checkmark_color=("#FAFAFA", "#18181B"),
            command=self._save_options
        )
        self.keep_it_cb.pack(anchor="w", padx=2, pady=(8, 6))

        # Checkbox 2: Append original words in parentheses
        self.append_source_var = ctk.BooleanVar(value=self.config.translation_options.append_original_words)
        self.append_source_cb = ctk.CTkCheckBox(
            self.options_body,
            text=self.i18n.t("opt_append_source"),
            variable=self.append_source_var,
            font=ctk.CTkFont(size=12),
            fg_color=("#18181B", "#FAFAFA"),
            hover_color=("#27272A", "#E4E4E7"),
            checkmark_color=("#FAFAFA", "#18181B"),
            command=self._save_options
        )
        self.append_source_cb.pack(anchor="w", padx=2, pady=(0, 6))

        # Checkbox 3: Bilingual Mode (Excel)
        self.bilingual_var = ctk.BooleanVar(value=self.config.translation_options.bilingual_mode)
        self.bilingual_cb = ctk.CTkCheckBox(
            self.options_body,
            text=self.i18n.t("opt_bilingual"),
            variable=self.bilingual_var,
            font=ctk.CTkFont(size=12),
            fg_color=("#18181B", "#FAFAFA"),
            hover_color=("#27272A", "#E4E4E7"),
            checkmark_color=("#FAFAFA", "#18181B"),
            command=self._save_options
        )
        self.bilingual_cb.pack(anchor="w", padx=2, pady=(0, 8))

        # Custom Context Prompt Label
        self.custom_prompt_label = ctk.CTkLabel(
            self.options_body,
            text=self.i18n.t("custom_prompt_label"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.custom_prompt_label.pack(anchor="w", padx=2, pady=(4, 4))

        # Custom Context Textbox
        self.custom_prompt_text = ctk.CTkTextbox(
            self.options_body,
            height=65,
            font=ctk.CTkFont(size=12),
            fg_color=("#FFFFFF", "#18181B"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            text_color=("#18181B", "#FAFAFA")
        )
        self.custom_prompt_text.pack(fill="x", padx=2, pady=(0, 14))
        if self.config.translation_options.custom_context:
            self.custom_prompt_text.insert("1.0", self.config.translation_options.custom_context)

        self.custom_prompt_text.bind("<KeyRelease>", lambda e: self._save_options())

    # -------------------------------------------------------------------------
    # Format Converter UI Components
    # -------------------------------------------------------------------------

    def _build_convert_dropzone(self, parent):
        self.convert_drop_zone = DropZone(
            parent,
            on_file_selected=self._on_convert_file_selected,
            get_translation=self.i18n.t
        )
        self.convert_drop_zone.pack(fill="x", pady=(0, 15))

    def _build_convert_options_card(self, parent):
        self.convert_options_card = ctk.CTkFrame(
            parent,
            fg_color="transparent"
        )
        # Not packed initially until file is selected

        # Top row: Left = "Select Target Format", Right = description of target format
        self.convert_target_row = ctk.CTkFrame(self.convert_options_card, fg_color="transparent")
        self.convert_target_row.pack(fill="x", padx=0, pady=(4, 8))

        self.convert_target_label = ctk.CTkLabel(
            self.convert_target_row,
            text=self.i18n.t("convert_select_target"),
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.convert_target_label.pack(side="left")

        self.convert_desc_label = ctk.CTkLabel(
            self.convert_target_row,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("#71717A", "#A1A1AA")
        )
        self.convert_desc_label.pack(side="right")

        self.target_segmented = ctk.CTkSegmentedButton(
            self.convert_options_card,
            values=["--"],
            command=self._on_target_format_changed,
            height=34,
            border_width=1,
            font=ctk.CTkFont(size=12, weight="bold"),
            selected_color=("#D4D4D8", "#3F3F46"),
            selected_hover_color=("#C4C4C8", "#52525B"),
            unselected_color=("#F4F4F5", "#18181B"),
            unselected_hover_color=("#E4E4E7", "#27272A"),
            text_color=("#18181B", "#FAFAFA")
        )
        self.target_segmented.pack(fill="x", pady=(0, 8))

    # -------------------------------------------------------------------------
    # Mode Switching
    # -------------------------------------------------------------------------

    def _apply_mode_tab_icons(self):
        """Attach crisp vector icons to the Translate / Convert segmented tabs."""
        try:
            btns = getattr(self.mode_segmented, "_buttons_dict", {})
            if self.tab_translate_label in btns:
                btns[self.tab_translate_label].configure(
                    image=get_icon("globe", "secondary", 16),
                    compound="left"
                )
            if self.tab_convert_label in btns:
                btns[self.tab_convert_label].configure(
                    image=get_icon("refresh", "secondary", 16),
                    compound="left"
                )
        except Exception:
            pass

    def _on_mode_switched(self, selected_mode_label: str):
        if self.i18n.t("tab_convert") in selected_mode_label:
            self.current_mode = "convert"
            self.translate_container.pack_forget()
            self.convert_container.pack(fill="both", expand=True)
            self.cache_bar.pack_forget()
            if hasattr(self, "provider_badge"):
                self.provider_badge.pack_forget()
        else:
            self.current_mode = "translate"
            self.convert_container.pack_forget()
            self.translate_container.pack(fill="both", expand=True)
            self.cache_bar.pack(fill="x", padx=20, pady=(0, 8), before=self.btn_row)
            if hasattr(self, "provider_badge") and not self.provider_badge.winfo_ismapped():
                self.provider_badge.pack(side="left", padx=(0, 10), before=self.settings_btn)

        active_file = self.selected_convert_file if self.current_mode == "convert" else self.selected_file
        self._update_button_states("file_ready" if active_file else "idle_no_file")
        self._refresh_status_text()

    def _toggle_options(self):
        self._options_expanded = not self._options_expanded
        if self._options_expanded:
            self.options_header.pack_configure(pady=(12, 0))
            self.options_body.pack(fill="x")
            self.options_toggle_btn.set_icon("minus", 14)
            self.options_title.configure(text=self.i18n.t("options_toggle_hide"))
        else:
            self.options_body.pack_forget()
            self.options_header.pack_configure(pady=12)
            self.options_toggle_btn.set_icon("plus", 14)
            self.options_title.configure(text=self.i18n.t("options_toggle_show"))

    # -------------------------------------------------------------------------
    # Action Bar & Button Lifecycle
    # -------------------------------------------------------------------------

    def _build_action_bar(self):
        self.action_bar = ctk.CTkFrame(
            self,
            corner_radius=0,
            fg_color="transparent"
        )
        self.action_bar.grid(row=3, column=0, sticky="ew", padx=0, pady=0)
        self.action_bar.grid_columnconfigure(0, weight=1)

        self.action_sep = ctk.CTkFrame(self.action_bar, height=1, fg_color=("#E4E4E7", "#27272A"))
        self.action_sep.pack(fill="x", side="top", pady=(0, 10))

        # Progress bar
        self.progress_bar = ctk.CTkProgressBar(
            self.action_bar,
            height=6,
            corner_radius=3,
            progress_color=("#18181B", "#FAFAFA"),
            fg_color=("#E4E4E7", "#27272A")
        )
        self.progress_bar.pack(fill="x", padx=20, pady=(0, 8))
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
            text_color=("#71717A", "#A1A1AA"),
            anchor="w",
            justify="left",
            wraplength=560
        )
        self.status_label.grid(row=0, column=0, sticky="ew")

        self.shortcut_hint_label = ctk.CTkLabel(
            self.status_row,
            text=self.i18n.t("shortcut_hint"),
            font=ctk.CTkFont(size=11),
            text_color=("#A1A1AA", "#71717A")
        )
        self.shortcut_hint_label.grid(row=0, column=1, sticky="e", padx=(10, 0))

        self.status_row.bind("<Configure>", self._update_status_wraplength)

        # Cache memory & Clear Cache row (prominently above the Translate button)
        self.cache_bar = ctk.CTkFrame(self.action_bar, fg_color="transparent")
        self.cache_bar.pack(fill="x", padx=20, pady=(0, 8))
        self.cache_bar.grid_columnconfigure(0, weight=1)
        self.cache_bar.grid_columnconfigure(1, weight=0)

        self.cache_stats_label = ctk.CTkLabel(
            self.cache_bar,
            text="  " + self.i18n.t("cache_stats", count=self.cache.count()),
            image=get_icon("database", "muted", 14),
            compound="left",
            font=ctk.CTkFont(size=11),
            text_color=("#71717A", "#A1A1AA")
        )
        self.cache_stats_label.grid(row=0, column=0, sticky="w")

        self.clear_cache_btn = CustomButton(
            self.cache_bar,
            text=self.i18n.t("clear_cache"),
            variant="outline",
            size="sm",
            width=116,
            icon_name="trash",
            icon_size=14,
            command=self._on_clear_cache_main
        )
        self.clear_cache_btn.grid(row=0, column=1, sticky="e")

        # Buttons row
        self.btn_row = ctk.CTkFrame(self.action_bar, fg_color="transparent")
        self.btn_row.pack(fill="x", padx=20, pady=(0, 14))

        # Translate button
        self.translate_btn = CustomButton(
            self.btn_row,
            text=self.i18n.t("start_translation"),
            command=self._start_translation,
            variant="primary",
            size="lg"
        )

        # Convert button (active in Format Converter mode)
        self.convert_btn = CustomButton(
            self.btn_row,
            text=self.i18n.t("convert_button"),
            command=self._start_conversion,
            variant="primary",
            size="lg",
            icon_name="refresh",
            icon_size=16
        )

        # Cancel button
        self.cancel_btn = CustomButton(
            self.btn_row,
            text=self.i18n.t("cancel"),
            command=self._cancel_translation,
            variant="danger",
            size="lg",
            width=100
        )

        # Open file button (Hero primary action on completion)
        self.open_file_btn = CustomButton(
            self.btn_row,
            text=self.i18n.t("open_file"),
            command=self._open_output_file,
            variant="primary",
            size="lg",
            icon_name="file_text",
            icon_size=16
        )

        # Open folder button
        self.open_folder_btn = CustomButton(
            self.btn_row,
            text=self.i18n.t("open_folder"),
            command=self._open_output_directory,
            variant="outline",
            size="lg",
            width=128,
            icon_name="folder",
            icon_size=16
        )

        # Save as button
        self.save_as_btn = CustomButton(
            self.btn_row,
            text=self.i18n.t("save_as"),
            command=self._save_output_as,
            variant="outline",
            size="lg",
            width=110,
            icon_name="save",
            icon_size=16
        )

        # Error button
        self.error_btn = CustomButton(
            self.btn_row,
            text=self.i18n.t("view_error_details"),
            command=self._show_error_modal,
            variant="danger",
            size="lg",
            width=170,
            icon_name="alert_triangle",
            icon_size=16
        )

        # Apply initial button states
        self._update_button_states("idle_no_file")

    def _update_button_states(self, state: Optional[str] = None):
        """
        Centralized button lifecycle and visibility manager.
        Handles all application states:
        - 'idle_no_file': No file selected (Action button disabled, result buttons hidden)
        - 'file_ready': File selected (Action button enabled and prominent, result buttons hidden)
        - 'processing': Operation in progress (Action button loading/disabled, cancel shown)
        - 'completed': Operation succeeded (Open file is primary, folder/save are outline, re-run is secondary)
        - 'error': Operation failed (Retry button primary, view error details shown)
        - 'cancelled': Operation cancelled (Returns to file ready)
        """
        if state is not None:
            self.current_button_state = state
        else:
            state = getattr(self, "current_button_state", None)
            if state is None or state in ("idle_no_file", "file_ready"):
                if self.is_translating or self.is_converting:
                    state = "processing"
                else:
                    active_file = self.selected_convert_file if self.current_mode == "convert" else self.selected_file
                    state = "file_ready" if active_file else "idle_no_file"
                self.current_button_state = state

        # 1. Update cache clear button state
        if hasattr(self, "clear_cache_btn") and hasattr(self, "cache"):
            has_cache = self.cache.count() > 0
            self.clear_cache_btn.configure(state="normal" if has_cache else "disabled")

        # 2. Reset packing in btn_row
        for widget in [
            self.translate_btn, self.convert_btn, self.cancel_btn,
            self.open_file_btn, self.open_folder_btn, self.save_as_btn, self.error_btn
        ]:
            if hasattr(widget, "pack_forget"):
                widget.pack_forget()

        # 3. Configure button visibility and hierarchy based on state
        if state == "idle_no_file":
            if self.current_mode == "convert":
                self.convert_btn.set_icon("refresh", 16)
                self.convert_btn.stop_loading(self.i18n.t("convert_button"))
                self.convert_btn.set_variant("primary")
                self.convert_btn.configure(state="disabled")
                self.convert_btn.pack(side="left", fill="x", expand=True)
            else:
                self.translate_btn.set_icon(None)
                self.translate_btn.stop_loading(self.i18n.t("start_translation"))
                self.translate_btn.set_variant("primary")
                self.translate_btn.configure(state="disabled")
                self.translate_btn.pack(side="left", fill="x", expand=True)

            if hasattr(self, "mode_segmented"):
                self.mode_segmented.configure(state="normal")
            if hasattr(self, "drop_zone"):
                self.drop_zone.browse_btn.configure(state="normal")
                self.drop_zone.clear_btn.configure(state="normal")
            if hasattr(self, "convert_drop_zone"):
                self.convert_drop_zone.browse_btn.configure(state="normal")
                self.convert_drop_zone.clear_btn.configure(state="normal")

        elif state == "file_ready":
            if self.current_mode == "convert":
                is_ready = bool(self.selected_convert_file and self.selected_target_format)
                self.convert_btn.set_icon("refresh", 16)
                self.convert_btn.stop_loading(self.i18n.t("convert_button"))
                self.convert_btn.set_variant("primary")
                self.convert_btn.configure(state="normal" if is_ready else "disabled")
                self.convert_btn.pack(side="left", fill="x", expand=True)
            else:
                self.translate_btn.set_icon(None)
                self.translate_btn.stop_loading(self.i18n.t("start_translation"))
                self.translate_btn.set_variant("primary")
                self.translate_btn.configure(state="normal")
                self.translate_btn.pack(side="left", fill="x", expand=True)

            if hasattr(self, "mode_segmented"):
                self.mode_segmented.configure(state="normal")
            if hasattr(self, "drop_zone"):
                self.drop_zone.browse_btn.configure(state="normal")
                self.drop_zone.clear_btn.configure(state="normal")
            if hasattr(self, "convert_drop_zone"):
                self.convert_drop_zone.browse_btn.configure(state="normal")
                self.convert_drop_zone.clear_btn.configure(state="normal")

        elif state == "processing":
            if self.current_mode == "convert":
                loading_text = self.i18n.t("converting_progress", target=(self.selected_target_format or "").upper())
                self.convert_btn.start_loading(loading_text)
                self.convert_btn.pack(side="left", fill="x", expand=True)
            else:
                self.translate_btn.start_loading(self.i18n.t("translating"))
                self.translate_btn.pack(side="left", fill="x", expand=True, padx=(0, 10))
                self.cancel_btn.configure(state="normal")
                self.cancel_btn.pack(side="left")

            if hasattr(self, "mode_segmented"):
                self.mode_segmented.configure(state="disabled")
            if hasattr(self, "drop_zone"):
                self.drop_zone.browse_btn.configure(state="disabled")
                self.drop_zone.clear_btn.configure(state="disabled")
            if hasattr(self, "convert_drop_zone"):
                self.convert_drop_zone.browse_btn.configure(state="disabled")
                self.convert_drop_zone.clear_btn.configure(state="disabled")

        elif state == "completed":
            if hasattr(self, "mode_segmented"):
                self.mode_segmented.configure(state="normal")
            if hasattr(self, "drop_zone"):
                self.drop_zone.browse_btn.configure(state="normal")
                self.drop_zone.clear_btn.configure(state="normal")
            if hasattr(self, "convert_drop_zone"):
                self.convert_drop_zone.browse_btn.configure(state="normal")
                self.convert_drop_zone.clear_btn.configure(state="normal")

            # Hero Action: Open File
            self.open_file_btn.set_variant("primary")
            self.open_file_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

            # Secondary Action: Open Folder
            self.open_folder_btn.set_variant("outline")
            self.open_folder_btn.pack(side="left", padx=(0, 8))

            # Secondary Action: Save As
            self.save_as_btn.set_variant("outline")
            self.save_as_btn.pack(side="left", padx=(0, 8))

            # Re-run Action
            if self.current_mode == "convert":
                self.convert_btn.set_icon("rotate_ccw", 15)
                self.convert_btn.stop_loading()
                self.convert_btn.set_variant("secondary")
                self.convert_btn.set_text(self.i18n.t("convert_again"))
                self.convert_btn.configure(state="normal")
                self.convert_btn.pack(side="left")
            else:
                self.translate_btn.set_icon("rotate_ccw", 15)
                self.translate_btn.stop_loading()
                self.translate_btn.set_variant("secondary")
                self.translate_btn.set_text(self.i18n.t("translate_again"))
                self.translate_btn.configure(state="normal")
                self.translate_btn.pack(side="left")

        elif state == "error":
            if hasattr(self, "mode_segmented"):
                self.mode_segmented.configure(state="normal")
            if hasattr(self, "drop_zone"):
                self.drop_zone.browse_btn.configure(state="normal")
                self.drop_zone.clear_btn.configure(state="normal")
            if hasattr(self, "convert_drop_zone"):
                self.convert_drop_zone.browse_btn.configure(state="normal")
                self.convert_drop_zone.clear_btn.configure(state="normal")

            if self.current_mode == "convert":
                self.convert_btn.set_icon("refresh", 16)
                self.convert_btn.stop_loading(self.i18n.t("convert_button"))
                self.convert_btn.set_variant("primary")
                self.convert_btn.configure(state="normal")
                self.convert_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))
            else:
                self.translate_btn.set_icon(None)
                self.translate_btn.stop_loading(self.i18n.t("retry_translation"))
                self.translate_btn.set_variant("primary")
                self.translate_btn.configure(state="normal")
                self.translate_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

            self.error_btn.pack(side="left")

        elif state == "cancelled":
            if hasattr(self, "mode_segmented"):
                self.mode_segmented.configure(state="normal")
            if hasattr(self, "drop_zone"):
                self.drop_zone.browse_btn.configure(state="normal")
                self.drop_zone.clear_btn.configure(state="normal")
            if hasattr(self, "convert_drop_zone"):
                self.convert_drop_zone.browse_btn.configure(state="normal")
                self.convert_drop_zone.clear_btn.configure(state="normal")

            self.translate_btn.set_icon(None)
            self.translate_btn.stop_loading(self.i18n.t("start_translation"))
            self.translate_btn.set_variant("primary")
            self.translate_btn.configure(state="normal")
            self.translate_btn.pack(side="left", fill="x", expand=True)

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
        active_file = self._get_active_output_file()
        if not active_file or not Path(active_file).exists():
            return

        src_path = Path(active_file)
        ext = src_path.suffix.lower()
        filetypes = [
            (self.i18n.t("filetype_doc_ext", ext=ext), f"*{ext}"),
            (self.i18n.t("filetype_all"), "*.*")
        ]
        chosen = filedialog.asksaveasfilename(
            title=self.i18n.t("dialog_save_copy"),
            initialdir=str(src_path.parent),
            initialfile=src_path.name,
            filetypes=filetypes
        )
        if chosen:
            import shutil
            shutil.copy2(active_file, chosen)
            self._set_status(self.i18n.t("status_saved_copy", filename=Path(chosen).name), text_color="#10B981")

    # -------------------------------------------------------------------------
    # Keyboard Shortcuts
    # -------------------------------------------------------------------------

    def _setup_shortcuts(self):
        """Bind ergonomic keyboard shortcuts for power users."""
        def on_open(event=None):
            if self.current_mode == "convert":
                self.convert_drop_zone._browse_file()
            else:
                self.drop_zone._browse_file()
            return "break"

        def on_action(event=None):
            if self.current_mode == "convert":
                if not self.is_converting:
                    self._start_conversion()
            else:
                if not self.is_translating:
                    self._start_translation()
            return "break"

        def on_escape(event=None):
            if self.current_screen == "settings":
                self._close_settings()
                return "break"
            if hasattr(self, "tgt_select") and getattr(self.tgt_select, "is_open", False):
                self.tgt_select.close()
                return "break"
            return None

        def on_settings(event=None):
            if self.current_screen == "settings":
                self._close_settings()
            else:
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

        # Escape closes settings or overlay panels
        self.bind("<Escape>", on_escape)

    # -------------------------------------------------------------------------
    # File Selection
    # -------------------------------------------------------------------------

    def _on_file_selected(self, file_path: str):
        self.selected_file = file_path if file_path else None
        if self.selected_file:
            self.status_label.configure(
                text=f"{self.i18n.t('status_ready')}: {Path(file_path).name}",
                text_color=("#18181B", "#FAFAFA")
            )
            ext = Path(file_path).suffix.lower().lstrip(".")
            if hasattr(self, "bilingual_cb"):
                self.bilingual_cb.configure(state="normal" if ext == "xlsx" else "disabled")
            self._update_button_states("file_ready")
        else:
            self.status_label.configure(text=self.i18n.t("status_ready"), text_color=("#71717A", "#A1A1AA"))
            if hasattr(self, "bilingual_cb"):
                self.bilingual_cb.configure(state="normal")
            self._update_button_states("idle_no_file")

    def _on_convert_file_selected(self, file_path: str):
        self.selected_convert_file = file_path if file_path else None

        if not self.selected_convert_file:
            self.convert_options_card.pack_forget()
            self.target_segmented.configure(values=["--"])
            self.target_segmented.set("--")
            self.selected_target_format = None
            self.convert_desc_label.configure(text="", text_color=("#71717A", "#A1A1AA"))
            self.status_label.configure(text=self.i18n.t("status_ready"), text_color=("#71717A", "#A1A1AA"))
            self._update_button_states("idle_no_file")
            return

        p = Path(self.selected_convert_file)
        ext = p.suffix.lower()

        # Get available target conversion formats
        options = get_convert_options(ext)
        if options:
            display_opts = [opt.upper() for opt in options]
            self.target_segmented.configure(values=display_opts)
            for idx in range(len(display_opts)):
                self.target_segmented.grid_columnconfigure(idx, weight=1, uniform="target_fmts")
            self.target_segmented.set(display_opts[0])
            self.selected_target_format = options[0]
            desc_key = f"convert_desc_{options[0]}"
            self.convert_desc_label.configure(text=self.i18n.t(desc_key), text_color=("#71717A", "#A1A1AA"))
            self._update_button_states("file_ready")
        else:
            self.target_segmented.configure(values=["--"])
            self.target_segmented.set("--")
            self.selected_target_format = None
            self.convert_desc_label.configure(text=self.i18n.t("convert_no_options"), text_color=("#DC2626", "#EF4444"))
            self._update_button_states("idle_no_file")

        # Show options card now that file is selected
        if not self.convert_options_card.winfo_ismapped():
            self.convert_options_card.pack(fill="x", pady=(0, 15))

        self.status_label.configure(
            text=f"{self.i18n.t('status_ready')}: {p.name}",
            text_color=("#18181B", "#FAFAFA")
        )

    def _on_target_format_changed(self, selected_display_fmt: str):
        tgt_fmt = selected_display_fmt.lower().lstrip(".")
        self.selected_target_format = tgt_fmt if tgt_fmt != "--" else None
        if self.selected_target_format:
            desc_key = f"convert_desc_{tgt_fmt}"
            desc = self.i18n.t(desc_key)
            self.convert_desc_label.configure(text=desc, text_color=("#71717A", "#A1A1AA"))
            self._update_button_states("file_ready")
        else:
            self._update_button_states("idle_no_file")

    # -------------------------------------------------------------------------
    # Language helpers
    # -------------------------------------------------------------------------

    def _save_lang_choice(self):
        val = self.tgt_select.get() if hasattr(self, "tgt_select") else self.tgt_var.get()
        self.config.target_language = val
        self.config.record_recent_target_language(val)
        if hasattr(self, "tgt_select"):
            self.tgt_select.set_recent_languages(self.config.recent_target_languages)
        self.tgt_var.set(val)
        self.config.save()

    def _on_clear_cache_main(self):
        count = self.cache.count()
        def do_clear():
            self.cache.clear()
            if hasattr(self, "cache_stats_label"):
                self.cache_stats_label.configure(
                    text="  " + self.i18n.t("cache_cleared"),
                    image=get_icon("check", "success_accent", 14),
                    compound="left",
                    text_color="#10B981"
                )
            self.after(2500, self._refresh_cache_display)

        ConfirmModal(
            parent=self,
            title=self.i18n.t("clear_cache"),
            message=self.i18n.t("confirm_clear_cache"),
            description=self.i18n.t("confirm_clear_cache_desc", count=count),
            confirm_text=self.i18n.t("clear_cache"),
            cancel_text=self.i18n.t("cancel"),
            on_confirm=do_clear,
            variant="danger",
            icon="trash",
            confirm_icon="trash",
            get_translation=self.i18n.t
        )

    def _refresh_cache_display(self):
        if hasattr(self, "cache_stats_label") and hasattr(self, "cache"):
            count = self.cache.count()
            self.cache_stats_label.configure(
                text="  " + self.i18n.t("cache_stats", count=count),
                image=get_icon("database", "muted", 14),
                compound="left",
                text_color=("#64748B", "#94A3B8")
            )
            if hasattr(self, "clear_cache_btn"):
                self.clear_cache_btn.configure(state="normal" if count > 0 else "disabled")

    def _save_options(self):
        self.config.translation_options.keep_it_terms = self.keep_it_var.get()
        self.config.translation_options.append_original_words = self.append_source_var.get()
        self.config.translation_options.bilingual_mode = self.bilingual_var.get()
        self.config.translation_options.custom_context = self.custom_prompt_text.get("1.0", "end-1c").strip()
        self.config.save()

    # -------------------------------------------------------------------------
    # Settings (In-Page View Transition)
    # -------------------------------------------------------------------------

    def _open_settings(self):
        """Switches to the in-page settings view below the header, hiding translate and convert."""
        if self.current_screen == "settings":
            self._close_settings()
            return

        self.current_screen = "settings"

        # Hide navigation tabs, scrollable body (translate/convert), and bottom action bar
        self.nav_frame.grid_remove()
        self.body_scroll.grid_remove()
        self.action_bar.grid_remove()

        # Update settings controls with current config and show below header
        self.settings_view.refresh_values()
        self.settings_view.grid(row=1, column=0, rowspan=3, sticky="nsew", padx=0, pady=0)

        # Update header button
        self.settings_btn.configure(text=self.i18n.t("done"))
        self.settings_btn.set_icon("check", 15)
        self.settings_btn.set_variant("primary")

    def _close_settings(self):
        """Returns to the main document translation and conversion workspace."""
        if self.current_screen != "settings":
            return

        self.current_screen = "main"

        # Hide settings view and restore main workspace
        self.settings_view.grid_remove()
        self.nav_frame.grid()
        self.body_scroll.grid()
        self.action_bar.grid()

        # Update header button
        self.settings_btn.configure(text=self.i18n.t("settings_btn"))
        self.settings_btn.set_icon("settings", 15)
        self.settings_btn.set_variant("secondary")

    def _on_settings_changed(self, updated_config: AppConfig):
        self.config = updated_config
        self.i18n.set_language(self.config.ui_language)
        self.provider_badge.configure(
            text=f"AI: {self.config.active_provider} ({self.config.get_active_model()})"
        )
        self.refresh_ui_texts()

    def refresh_ui_texts(self):
        """Update all on-screen text when language changes."""
        self.title("")
        if self.logo_image:
            self.logo_label.configure(text="  " + self.i18n.t("app_title"))
        else:
            self.logo_label.configure(text="  " + self.i18n.t("app_title"), image=get_icon("globe", "default", 22), compound="left")
        self.subtitle_label.configure(text=self.i18n.t("app_subtitle"))

        if self.current_screen == "settings":
            self.settings_btn.configure(text=self.i18n.t("done"))
            self.settings_btn.set_icon("check", 15)
            self.settings_btn.set_variant("primary")
        else:
            self.settings_btn.configure(text=self.i18n.t("settings_btn"))
            self.settings_btn.set_icon("settings", 15)
            self.settings_btn.set_variant("secondary")

        if hasattr(self, "settings_view"):
            self.settings_view.refresh_i18n(self.i18n.t)

        # Provider badge visibility according to active mode
        if hasattr(self, "provider_badge"):
            if self.current_mode == "convert":
                self.provider_badge.pack_forget()
            elif not self.provider_badge.winfo_ismapped():
                self.provider_badge.pack(side="left", padx=(0, 10), before=self.settings_btn)

        self.tgt_label.configure(text=self.i18n.t("target_lang"))
        if hasattr(self, "tgt_select"):
            self.tgt_select.refresh_i18n(self.i18n.t)

        self.drop_zone.refresh_i18n()

        # Options card
        if self._options_expanded:
            self.options_title.configure(text=self.i18n.t("options_toggle_hide"))
        else:
            self.options_title.configure(text=self.i18n.t("options_toggle_show"))
        self.keep_it_cb.configure(text=self.i18n.t("opt_keep_terms"))
        self.append_source_cb.configure(text=self.i18n.t("opt_append_source"))
        self.bilingual_cb.configure(text=self.i18n.t("opt_bilingual"))

        self.custom_prompt_label.configure(text=self.i18n.t("custom_prompt_label"))

        # Mode selector tabs
        self.tab_translate_label = self.i18n.t("tab_translate")
        self.tab_convert_label = self.i18n.t("tab_convert")
        if hasattr(self, "mode_segmented"):
            self.mode_segmented.configure(values=[self.tab_translate_label, self.tab_convert_label])
            self.mode_segmented.grid_columnconfigure(0, weight=1, uniform="mode_tabs")
            self.mode_segmented.grid_columnconfigure(1, weight=1, uniform="mode_tabs")
            self.mode_segmented.set(
                self.tab_convert_label if self.current_mode == "convert" else self.tab_translate_label
            )
            self._apply_mode_tab_icons()

        if hasattr(self, "convert_drop_zone"):
            self.convert_drop_zone.refresh_i18n()
        if hasattr(self, "convert_target_label"):
            self.convert_target_label.configure(text=self.i18n.t("convert_select_target"))
        if hasattr(self, "convert_btn"):
            self.convert_btn.set_text(self.i18n.t("convert_button"))
        if hasattr(self, "translate_btn"):
            self.translate_btn.set_text(self.i18n.t("start_translation"))
        if hasattr(self, "convert_desc_label"):
            if self.selected_target_format:
                desc_key = f"convert_desc_{self.selected_target_format}"
                self.convert_desc_label.configure(text=self.i18n.t(desc_key), text_color=("#71717A", "#A1A1AA"))
            elif self.selected_convert_file:
                self.convert_desc_label.configure(text=self.i18n.t("convert_no_options"), text_color=("#DC2626", "#EF4444"))
            else:
                self.convert_desc_label.configure(text="")

        # Action bar
        self.cancel_btn.configure(text=self.i18n.t("cancel"))
        self.open_file_btn.configure(text=self.i18n.t("open_file"))
        self.open_folder_btn.configure(text=self.i18n.t("open_folder"))
        self.save_as_btn.configure(text=self.i18n.t("save_as"))
        self.error_btn.configure(text=self.i18n.t("view_error_details"))
        if hasattr(self, "shortcut_hint_label"):
            self.shortcut_hint_label.configure(text=self.i18n.t("shortcut_hint"))

        self._refresh_cache_display()
        if hasattr(self, "clear_cache_btn"):
            self.clear_cache_btn.configure(text=self.i18n.t("clear_cache"))

        # Re-diagnose previous error with new language if exists
        if getattr(self, "last_exception", None):
            self.last_diagnostic = diagnose_error(self.last_exception, self.i18n)

        self._update_button_states()
        self._refresh_status_text()

    def _refresh_status_text(self):
        """Refreshes status label text according to current state and language."""
        if not hasattr(self, "status_label"):
            return

        state = getattr(self, "current_button_state", "idle_no_file")
        if state == "idle_no_file":
            self._set_status(self.i18n.t("status_ready"), text_color=("#71717A", "#A1A1AA"))
        elif state == "file_ready":
            active_file = self.selected_convert_file if self.current_mode == "convert" else self.selected_file
            if active_file:
                self._set_status(f"{self.i18n.t('status_ready')}: {Path(active_file).name}", text_color=("#18181B", "#FAFAFA"))
            else:
                self._set_status(self.i18n.t("status_ready"), text_color=("#71717A", "#A1A1AA"))
        elif state == "completed":
            out_file = self._get_active_output_file()
            out_name = Path(out_file).name if out_file else ""
            if self.current_mode == "convert":
                self._set_status(self.i18n.t("convert_success", filename=out_name), text_color=("#16A34A", "#22C55E"))
            else:
                self._set_status(self.i18n.t("status_completed", filename=out_name), text_color=("#16A34A", "#22C55E"))
        elif state == "error":
            if self.current_mode == "convert" and getattr(self, "last_convert_error", None):
                self._set_status(self.i18n.t("convert_error", error=self.last_convert_error), is_error=True)
            elif getattr(self, "last_diagnostic", None):
                short_summary = f"{self.last_diagnostic.title}: {self.last_diagnostic.message}"
                self._set_status(short_summary, is_error=True)
        elif state == "cancelled":
            self._set_status(self.i18n.t("status_cancelled"), text_color=("#D97706", "#F59E0B"))
        elif state == "processing":
            if self.current_mode == "convert":
                tgt = (self.selected_target_format or "").upper()
                self._set_status(self.i18n.t("converting_progress", target=tgt))
            else:
                self._set_status(self.i18n.t("status_loading_file"))

    # -------------------------------------------------------------------------
    # Translation
    # -------------------------------------------------------------------------

    def _start_translation(self):
        # Validation checks
        if not self.selected_file:
            self._set_status(self.i18n.t("err_no_file"), is_error=True)
            return

        tgt_lang = self.tgt_select.get() if hasattr(self, "tgt_select") else self.tgt_var.get()

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
        self.last_exception = None
        self.last_diagnostic = None
        self.is_translating = True
        self._update_button_states("processing")
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
            if self.current_translator:
                self.current_translator.cancel()
            self.excel_translator.cancel()
            self.markdown_translator.cancel()
            self._set_status(self.i18n.t("status_cancelling"), is_error=False)

    def _run_translation_worker(self, file_path: str, tgt_lang: str):
        try:
            path = Path(file_path)
            if not TranslatorRegistry.is_supported(path):
                raise ValueError(self.i18n.t("err_unsupported_file"))

            def on_progress(current: int, total: int, msg: str):
                fraction = current / max(1, total)
                self.after(0, lambda: self._update_progress(fraction, msg))

            translator = TranslatorRegistry.create_translator(
                file_path_or_ext=path,
                config=self.config,
                llm_manager=self.llm_manager,
                cache=self.cache
            )
            self.current_translator = translator

            output_file = translator.process_file(
                file_path=file_path,
                target_lang=tgt_lang,
                options=self.config.translation_options,
                progress_callback=on_progress
            )

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
        self._set_status(self.i18n.t("status_completed", filename=out_name), text_color=("#16A34A", "#22C55E"))
        self._refresh_cache_display()
        self._update_button_states("completed")

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
                    f'display notification "{out_name}" with title "RakuTrans AI" subtitle "{self.i18n.t("notification_completed")}"'
                ])
            except Exception:
                pass

    def _on_translation_cancelled(self):
        self.is_translating = False
        self.progress_bar.set(0)
        self._set_status(self.i18n.t("status_cancelled"), text_color=("#D97706", "#F59E0B"))
        self._update_button_states("cancelled")

    def _on_translation_failed(self, error_msg: str, exc: Optional[Exception] = None):
        self.is_translating = False
        self.progress_bar.set(0)
        self.last_exception = exc if exc else Exception(error_msg)
        self.last_diagnostic = diagnose_error(self.last_exception, self.i18n)
        short_summary = f"{self.last_diagnostic.title}: {self.last_diagnostic.message}"
        self._set_status(short_summary, is_error=True)
        self._update_button_states("error")
        self._show_error_modal()

    # -------------------------------------------------------------------------
    # Format Conversion Execution
    # -------------------------------------------------------------------------

    def _start_conversion(self):
        if not self.selected_convert_file:
            self._set_status(self.i18n.t("convert_no_file"), is_error=True)
            return

        if not self.selected_target_format:
            self._set_status(self.i18n.t("convert_no_options"), is_error=True)
            return

        self.last_convert_error = None
        self.is_converting = True
        self._update_button_states("processing")
        self.progress_bar.set(0.2)
        loading_text = self.i18n.t("converting_progress", target=self.selected_target_format.upper())
        self._set_status(loading_text)

        # Spawn background conversion thread
        threading.Thread(
            target=self._run_conversion_worker,
            args=(self.selected_convert_file, self.selected_target_format),
            daemon=True
        ).start()

    def _run_conversion_worker(self, file_path: str, target_fmt: str):
        try:
            self.after(0, lambda: self.progress_bar.set(0.5))
            out_file = convert_file_direct(file_path, target_fmt)
            self.last_convert_output_file = out_file
            self.after(0, lambda: self._on_conversion_completed(out_file))
        except Exception as e:
            self.after(0, lambda err=e: self._on_conversion_failed(str(err), exc=err))

    def _on_conversion_completed(self, output_path: str):
        self.is_converting = False
        self.progress_bar.set(1.0)
        out_name = Path(output_path).name
        msg = self.i18n.t("convert_success", filename=out_name)
        self._set_status(msg, text_color=("#16A34A", "#22C55E"))
        self._update_button_states("completed")

        # Audio completion cue & notification
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
                    f'display notification "{out_name}" with title "RakuTrans AI" subtitle "{self.i18n.t("notification_convert_completed")}"'
                ])
            except Exception:
                pass

    def _on_conversion_failed(self, error_msg: str, exc: Optional[Exception] = None):
        self.is_converting = False
        self.progress_bar.set(0)
        self.last_convert_error = error_msg
        msg = self.i18n.t("convert_error", error=error_msg)
        self._set_status(msg, is_error=True)
        self._update_button_states("error")

    # -------------------------------------------------------------------------
    # Open File / Folder
    # -------------------------------------------------------------------------

    def _get_active_output_file(self) -> Optional[str]:
        if self.current_mode == "convert":
            return self.last_convert_output_file
        return self.last_output_file

    def _open_output_file(self):
        active_file = self._get_active_output_file()
        if not active_file or not Path(active_file).exists():
            return

        file_path = str(Path(active_file).resolve())
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
        active_file = self._get_active_output_file()
        if not active_file:
            return

        folder = Path(active_file).parent
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
            self.status_label.configure(text=text, text_color=("#DC2626", "#EF4444"))
        elif text_color:
            self.status_label.configure(text=text, text_color=text_color)
        else:
            self.status_label.configure(text=text, text_color=("#18181B", "#FAFAFA"))
