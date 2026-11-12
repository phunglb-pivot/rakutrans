"""
Searchable Language Selector component for RakuTrans AI.
Provides a modern in-page searchable dropdown selector for choosing target languages
with real-time filtering, clean neutral colors, and zero secondary windows.
"""

import unicodedata
import time
from typing import Callable, List, Optional
import customtkinter as ctk

from config import LanguageInfo, get_all_languages, DEFAULT_TARGET_LANGUAGE, normalize_language_name
from components.icons import get_icon


def _strip_accents(text: str) -> str:
    """Removes diacritics/accents for robust search matching (e.g. 'tiếng việt' -> 'tieng viet')."""
    nfkd_form = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd_form if unicodedata.category(c) != "Mn")


class SearchableLanguageSelect(ctk.CTkFrame):
    """
    Modern in-page searchable dropdown for target language selection.
    Eliminates popup windows (no CTkToplevel) while floating over page content
    without taking up layout space or shifting adjacent elements.
    Features real-time fuzzy filtering, click-outside auto dismiss, and clean minimalist styling.
    """

    def __init__(
        self,
        master,
        current_language: Optional[str] = None,
        on_change: Optional[Callable[[str], None]] = None,
        width: int = 340,
        height: int = 36,
        get_translation: Optional[Callable[[str], str]] = None,
        on_open: Optional[Callable[[], Optional[int]]] = None,
        on_close: Optional[Callable[[], None]] = None,
        recent_languages: Optional[List[str]] = None,
        **kwargs
    ):
        super().__init__(master, fg_color="transparent", width=width, **kwargs)
        self.t = get_translation or (lambda k, **kw: k)
        self.languages: List[LanguageInfo] = get_all_languages()
        self.on_change = on_change
        self.on_open = on_open
        self.on_close = on_close
        self.selected_display = normalize_language_name(current_language or DEFAULT_TARGET_LANGUAGE)
        
        # Initialize recent languages (max 3)
        raw_recents = recent_languages if recent_languages is not None else [self.selected_display]
        seen_recents: List[str] = []
        for r in raw_recents:
            norm = normalize_language_name(r)
            if norm not in seen_recents:
                seen_recents.append(norm)
        if self.selected_display not in seen_recents:
            seen_recents.insert(0, self.selected_display)
        self.recent_languages: List[str] = seen_recents[:3]

        self.is_open = False
        self._panel_width = width
        self._panel_height = 240
        self._buttons: List[ctk.CTkButton] = []
        self._just_toggled_time: float = 0.0

        self.grid_columnconfigure(0, weight=1)

        # Trigger button (displays current language and toggle chevron)
        self.trigger_btn = ctk.CTkButton(
            self,
            text=self.selected_display,
            width=width,
            height=height,
            fg_color=("white", "#202023"),
            text_color=("#18181B", "#FAFAFA"),
            hover_color=("#F4F4F5", "#27272A"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            corner_radius=8,
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
            cursor="hand2",
            command=None  # Click handled centrally by _on_window_click to avoid double toggling
        )
        self.trigger_btn.pack(fill="x")
        self.trigger_btn.bind("<Configure>", lambda e: self._update_chevron(), add="+")
        self.after(20, self._update_chevron)

        # Collapsible Floating Dropdown Panel
        # Attached to the toplevel window so it floats as an overlay without pushing layout
        # or requiring a separate OS window (CTkToplevel).
        self._top_root = self.winfo_toplevel()
        self.panel = ctk.CTkFrame(
            self,
            width=width,
            height=self._panel_height,
            fg_color=("white", "#18181B"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            corner_radius=8
        )
        self.panel.pack_propagate(False)

        # Search Entry Header
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", self._on_search)

        self.search_entry = ctk.CTkEntry(
            self.panel,
            textvariable=self.search_var,
            placeholder_text=self.t("search_lang_placeholder"),
            height=34,
            corner_radius=6,
            fg_color=("#F4F4F5", "#202023"),
            border_width=1,
            border_color=("#E4E4E7", "#27272A"),
            text_color=("#18181B", "#FAFAFA"),
            placeholder_text_color=("#A1A1AA", "#71717A"),
            font=ctk.CTkFont(size=12)
        )
        self.search_entry.pack(fill="x", padx=8, pady=(8, 6))

        self.search_entry.bind("<Escape>", lambda e: self.close())
        self.search_entry.bind("<Return>", self._on_enter_pressed)
        self.search_entry.bind("<Down>", self._focus_first_result)
        self.search_entry.bind("<FocusIn>", lambda e: self._scroll_to_top())

        # Scrollable languages list
        self.scroll_list = ctk.CTkScrollableFrame(
            self.panel,
            fg_color="transparent",
            corner_radius=0
        )
        self.scroll_list.pack(fill="both", expand=True, padx=4, pady=(0, 6))

        # Register event handlers for click-outside, scroll, and window resize dismissal
        self._setup_event_listeners()

    def _setup_event_listeners(self):
        """Binds window-level click, scroll, and resize handlers for seamless auto-dismiss."""
        try:
            self._top_root.bind_all("<ButtonPress-1>", self._on_window_click, add="+")
            self._top_root.bind("<Configure>", self._on_window_configure, add="+")
            self._top_root.bind_all("<MouseWheel>", self._on_window_scroll, add="+")
            self._top_root.bind_all("<Button-4>", self._on_window_scroll, add="+")
            self._top_root.bind_all("<Button-5>", self._on_window_scroll, add="+")
        except Exception:
            pass

    def _is_descendant(self, widget, target) -> bool:
        """Checks whether widget is target or a subwidget belonging to target."""
        if not widget or not target:
            return False
        try:
            w_str = str(widget)
            t_str = str(target)
            return w_str == t_str or w_str.startswith(t_str + ".") or w_str.startswith(t_str + "!")
        except Exception:
            return False

    def _is_inside(self, widget, x_root: int, y_root: int) -> bool:
        """Checks if global screen coordinates (x_root, y_root) fall inside the given widget."""
        if not widget or not widget.winfo_exists() or not widget.winfo_ismapped():
            return False
        try:
            wx = widget.winfo_rootx()
            wy = widget.winfo_rooty()
            ww = widget.winfo_width()
            wh = widget.winfo_height()
            return (wx <= x_root <= wx + ww) and (wy <= y_root <= wy + wh)
        except Exception:
            return False

    def _on_window_click(self, event):
        """Closes dropdown when user clicks outside the panel (including on the trigger button/input)."""
        if not self.winfo_exists():
            return

        is_on_panel = self._is_descendant(event.widget, self.panel)
        is_on_trigger = self._is_descendant(event.widget, self.trigger_btn) or (
            not is_on_panel and self._is_inside(self.trigger_btn, event.x_root, event.y_root)
        )

        if is_on_panel:
            return  # Clicking inside search input, list, scrollbar keeps it open
        if is_on_trigger:
            self.toggle()
        elif self.is_open:
            self.close()

    def _on_window_configure(self, event):
        """Closes dropdown if top-level window resizes or repositions."""
        if not self.winfo_exists() or not self.is_open:
            return
        if event.widget == self._top_root:
            self.close()

    def _on_window_scroll(self, event):
        """Closes dropdown when scrolling outside the dropdown panel."""
        if not self.winfo_exists() or not self.is_open:
            return
        if self._is_descendant(event.widget, self.panel) or self._is_inside(self.panel, event.x_root, event.y_root):
            return
        self.close()

    def _scroll_to_top(self):
        """Scrolls the language scrollable frame back to the top."""
        try:
            if hasattr(self.scroll_list, "_parent_canvas"):
                self.scroll_list._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass

    @property
    def arrow_label(self):
        """Backward-compatibility shim for external references to arrow_label."""
        class _Dummy:
            def configure(self, *a, **kw): pass
            def cget(self, *a, **kw): return "▾"
        return _Dummy()

    def _update_chevron(self):
        """Draws or updates a clean vector chevron directly on the button canvas with zero background."""
        if not hasattr(self, "trigger_btn") or not self.trigger_btn.winfo_exists():
            return
        try:
            canvas = self.trigger_btn._canvas
            w = self.trigger_btn.winfo_width()
            h = self.trigger_btn.winfo_height()
            if w <= 1 or h <= 1:
                w = self._panel_width
                h = 36
            x = w - 20
            y = h / 2
            color = "#A1A1AA" if ctk.get_appearance_mode() == "Dark" else "#71717A"

            import tkinter
            if self.is_open:
                # Up chevron: ⌃
                coords = (x - 4, y + 2, x, y - 2, x + 4, y + 2)
            else:
                # Down chevron: ⌄
                coords = (x - 4, y - 2, x, y + 2, x + 4, y - 2)

            if not canvas.find_withtag("dropdown_chevron"):
                canvas.create_line(
                    *coords,
                    width=1.5,
                    fill=color,
                    capstyle=tkinter.ROUND,
                    joinstyle=tkinter.ROUND,
                    tags="dropdown_chevron"
                )
            else:
                canvas.coords("dropdown_chevron", *coords)
                canvas.itemconfig("dropdown_chevron", fill=color)
            canvas.tag_raise("dropdown_chevron")
        except Exception:
            pass

    def toggle(self):
        """Toggles the in-page dropdown panel visibility."""
        if self.is_open:
            self.close()
        else:
            self.open()

    def open(self):
        """Expands the dropdown list as a floating overlay above other content."""
        if self.is_open:
            return

        # Expand inline (inside layout) instead of floating: native child widgets of
        # other cards (e.g. the drop zone) can bleed through a toplevel-level overlay.
        # on_open may hide sibling content and return the pixel height to match, so
        # opening/closing swaps two equally sized regions without layout jumps.
        panel_height = self._panel_height
        if self.on_open:
            try:
                matched = self.on_open()
                if matched:
                    panel_height = max(matched, 160)
            except Exception:
                pass
        self.panel.configure(width=self._panel_width, height=panel_height)
        self.panel.pack(fill="x", pady=(4, 0))

        self.is_open = True
        self._update_chevron()
        self.search_var.set("")
        self._render_items()
        self._scroll_to_top()
        self.after(50, lambda: self.search_entry.focus_set() if self.winfo_exists() else None)

    def close(self):
        """Collapses and hides the floating dropdown panel."""
        if not self.is_open:
            return
        if hasattr(self, "panel") and self.panel.winfo_exists():
            self.panel.pack_forget()
        self.is_open = False
        self._update_chevron()
        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass
        try:
            # Force repaint of the area previously covered by the overlay
            self._top_root.update_idletasks()
        except Exception:
            pass

    def set_recent_languages(self, langs: List[str]):
        """Sets the list of recent languages (max 3)."""
        seen: List[str] = []
        for l in langs:
            norm = normalize_language_name(l)
            if norm not in seen:
                seen.append(norm)
        self.recent_languages = seen[:3]
        if self.is_open:
            self._render_items()

    def _render_items(self):
        """Populates scrollable list with matching languages."""
        for widget in self.scroll_list.winfo_children():
            widget.destroy()

        self._buttons.clear()
        query = _strip_accents(self.search_var.get().lower().strip())
        matching_count = 0

        # When not searching and recent languages exist, show Recent section first
        if not query and self.recent_languages:
            recent_lbl = ctk.CTkLabel(
                self.scroll_list,
                text=f"  {self.t('recent_languages')}",
                image=get_icon("clock", "muted", 12),
                compound="left",
                anchor="w",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#71717A", "#A1A1AA")
            )
            recent_lbl.pack(fill="x", padx=8, pady=(4, 2))

            for r_lang in self.recent_languages:
                is_selected = (r_lang == self.selected_display)
                prefix = "✓  " if is_selected else "    "

                btn = ctk.CTkButton(
                    self.scroll_list,
                    text=f"{prefix}{r_lang}",
                    anchor="w",
                    height=28,
                    corner_radius=6,
                    fg_color=("#F4F4F5", "#27272A") if is_selected else "transparent",
                    text_color=("#18181B", "#FAFAFA"),
                    hover_color=("#E4E4E7", "#3F3F46") if is_selected else ("#F4F4F5", "#27272A"),
                    font=ctk.CTkFont(size=12, weight="bold" if is_selected else "normal"),
                    cursor="hand2",
                    command=lambda d=r_lang: self._choose(d)
                )
                btn.pack(fill="x", pady=1)
                self._buttons.append(btn)
                matching_count += 1

            all_lbl = ctk.CTkLabel(
                self.scroll_list,
                text=f"  {self.t('all_languages')}",
                image=get_icon("globe", "muted", 12),
                compound="left",
                anchor="w",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=("#71717A", "#A1A1AA")
            )
            all_lbl.pack(fill="x", padx=8, pady=(8, 2))

        for lang in self.languages:
            raw_search_string = f"{lang.name} {lang.native_name} {lang.code} {lang.display_name}".lower()
            if not query or query in _strip_accents(raw_search_string):
                matching_count += 1
                is_selected = (lang.display_name == self.selected_display)
                prefix = "✓  " if is_selected else "    "

                btn = ctk.CTkButton(
                    self.scroll_list,
                    text=f"{prefix}{lang.display_name}",
                    anchor="w",
                    height=28,
                    corner_radius=6,
                    fg_color=("#F4F4F5", "#27272A") if is_selected else "transparent",
                    text_color=("#18181B", "#FAFAFA"),
                    hover_color=("#E4E4E7", "#3F3F46") if is_selected else ("#F4F4F5", "#27272A"),
                    font=ctk.CTkFont(size=12, weight="bold" if is_selected else "normal"),
                    cursor="hand2",
                    command=lambda d=lang.display_name: self._choose(d)
                )
                btn.pack(fill="x", pady=1)
                self._buttons.append(btn)

        if matching_count == 0:
            no_result = ctk.CTkLabel(
                self.scroll_list,
                text=self.t("no_matching_language"),
                text_color="gray",
                font=ctk.CTkFont(size=12)
            )
            no_result.pack(pady=15)

    def _on_search(self, *args):
        self._render_items()
        self._scroll_to_top()

    def _choose(self, display_name: str):
        self.selected_display = normalize_language_name(display_name)
        if self.selected_display in self.recent_languages:
            self.recent_languages.remove(self.selected_display)
        self.recent_languages.insert(0, self.selected_display)
        self.recent_languages = self.recent_languages[:3]

        self.trigger_btn.configure(text=self.selected_display)
        self._update_chevron()
        self.close()
        if self.on_change:
            self.on_change(self.selected_display)

    def _on_enter_pressed(self, event=None):
        if self._buttons:
            # First item in filtered results
            first_btn = self._buttons[0]
            txt = first_btn.cget("text").lstrip("✓ ").strip()
            self._choose(txt)

    def _focus_first_result(self, event=None):
        if self._buttons:
            self._buttons[0].focus_set()

    def get(self) -> str:
        """Returns currently selected display language name (e.g. 'Tiếng Việt (Vietnamese)')."""
        return self.selected_display

    def set(self, lang_name: str):
        """Sets selected language and updates button label."""
        self.selected_display = normalize_language_name(lang_name)
        if self.selected_display in self.recent_languages:
            self.recent_languages.remove(self.selected_display)
        self.recent_languages.insert(0, self.selected_display)
        self.recent_languages = self.recent_languages[:3]
        self.trigger_btn.configure(text=self.selected_display)
        self._update_chevron()

    def refresh_i18n(self, get_translation: Optional[Callable[[str], str]] = None):
        """Updates localized placeholder and messages when UI language changes."""
        if get_translation:
            self.t = get_translation
        self.search_entry.configure(placeholder_text=self.t("search_lang_placeholder"))
        if self.is_open:
            self._render_items()

    def destroy(self):
        """Cleanly destroys the floating panel and the trigger widget."""
        if hasattr(self, "panel") and self.panel.winfo_exists():
            try:
                self.panel.destroy()
            except Exception:
                pass
        super().destroy()
