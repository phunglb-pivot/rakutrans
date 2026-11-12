"""
UI System & Design Tokens for RakuTrans AI.
Provides unified button variants, standard sizing scales, loading buttons,
and a standardized BaseModal for consistent desktop UX.
"""

import tkinter as tk
from typing import Callable, Optional
import customtkinter as ctk

from components.icons import get_icon, apply_windows_window_icon


# -----------------------------------------------------------------------------
# 1. Design Tokens
# -----------------------------------------------------------------------------

BUTTON_SIZES = {
    "sm": {
        "height": 28,
        "font_size": 11,
        "corner_radius": 6,
        "padx": 10
    },
    "md": {
        "height": 34,
        "font_size": 12,
        "corner_radius": 8,
        "padx": 14
    },
    "lg": {
        "height": 40,
        "font_size": 13,
        "corner_radius": 8,
        "padx": 16
    }
}

BUTTON_VARIANTS = {
    # Primary actions (Start Translation, Save Settings, Hero Open File)
    "primary": {
        "fg_color": ("#18181B", "#FAFAFA"),
        "hover_color": ("#27272A", "#E4E4E7"),
        "text_color": ("#FFFFFF", "#18181B"),
        "border_width": 0,
        "border_color": None
    },
    # Accent actions (Convert Mode, Highlights)
    "accent": {
        "fg_color": ("#18181B", "#FAFAFA"),
        "hover_color": ("#27272A", "#E4E4E7"),
        "text_color": ("#FFFFFF", "#18181B"),
        "border_width": 0,
        "border_color": None
    },
    # Secondary solid buttons (Browse, Select, Settings, Re-run actions)
    "secondary": {
        "fg_color": ("#E4E4E7", "#27272A"),
        "hover_color": ("#D4D4D8", "#3F3F46"),
        "text_color": ("#18181B", "#FAFAFA"),
        "border_width": 0,
        "border_color": None
    },
    # Outline buttons (Cancel, Close, Open Folder, Save As)
    "outline": {
        "fg_color": "transparent",
        "hover_color": ("#F4F4F5", "#27272A"),
        "text_color": ("#18181B", "#FAFAFA"),
        "border_width": 1,
        "border_color": ("#D4D4D8", "#3F3F46")
    },
    # Danger actions (Cancel Translation, Clear Cache, Delete, Error Details)
    "danger": {
        "fg_color": ("#DC2626", "#DC2626"),
        "hover_color": ("#B91C1C", "#B91C1C"),
        "text_color": "#FFFFFF",
        "border_width": 0,
        "border_color": None
    },
    # Ghost / Link buttons (View Docs, Inline options)
    "ghost": {
        "fg_color": "transparent",
        "hover_color": ("#F4F4F5", "#27272A"),
        "text_color": ("#18181B", "#FAFAFA"),
        "border_width": 0,
        "border_color": None
    },
    # Info / Primary Action variant (Open File)
    "info": {
        "fg_color": ("#18181B", "#FAFAFA"),
        "hover_color": ("#27272A", "#E4E4E7"),
        "text_color": ("#FFFFFF", "#18181B"),
        "border_width": 0,
        "border_color": None
    }
}

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


# -----------------------------------------------------------------------------
# 2. CustomButton Component
# -----------------------------------------------------------------------------

class CustomButton(ctk.CTkButton):
    """
    Standardized, high-accessibility button for RakuTrans AI.
    Features:
    - Standardized variants ('primary', 'accent', 'secondary', 'outline', 'danger', 'ghost', 'info')
    - Standardized sizes ('sm', 'md', 'lg')
    - Native hand cursor (cursor='hand2')
    - Built-in loading state with animated spinner
    """

    def __init__(
        self,
        master,
        text: str = "",
        variant: str = "primary",
        size: str = "md",
        command: Optional[Callable] = None,
        icon_name: Optional[str] = None,
        icon_size: Optional[int] = None,
        **kwargs
    ):
        self.variant = variant
        self.btn_size = size
        self._raw_text = text
        self._icon_name = icon_name
        self._icon_size = icon_size or (14 if size == "sm" else 16)
        self._is_loading = False
        self._spinner_idx = 0
        self._loading_after_id = None
        self._orig_command = command

        size_cfg = BUTTON_SIZES.get(size, BUTTON_SIZES["md"])
        var_cfg = BUTTON_VARIANTS.get(variant, BUTTON_VARIANTS["primary"])

        # Set default dimensions and styling from tokens unless overridden
        font_weight = "bold" if size in ("md", "lg") else "normal"
        default_font = ctk.CTkFont(size=size_cfg["font_size"], weight=font_weight)

        btn_kwargs = {
            "height": size_cfg["height"],
            "corner_radius": size_cfg["corner_radius"],
            "font": default_font,
            "cursor": "hand2",
            "text_color_disabled": ("gray50", "gray50"),
            "command": command
        }

        if icon_name and "image" not in kwargs:
            btn_kwargs["image"] = get_icon(icon_name, color=variant, size=self._icon_size)
            btn_kwargs.setdefault("compound", "left")

        # Apply variant styles if not explicitly passed
        for key, val in var_cfg.items():
            if key not in kwargs and val is not None:
                btn_kwargs[key] = val

        btn_kwargs.update(kwargs)
        self._current_image = btn_kwargs.get("image")
        if btn_kwargs.get("state") == "disabled":
            btn_kwargs["cursor"] = "arrow"

        super().__init__(master, text=text, **btn_kwargs)

    def configure(self, require_redraw=False, **kwargs):
        if "state" in kwargs:
            st = kwargs["state"]
            if st == "disabled":
                kwargs.setdefault("cursor", "arrow")
            elif st == "normal":
                kwargs.setdefault("cursor", "hand2")
        if "image" in kwargs and not self._is_loading:
            self._current_image = kwargs["image"]
        return super().configure(require_redraw=require_redraw, **kwargs)

    def set_icon(self, icon_name: Optional[str], icon_size: Optional[int] = None):
        """Update the button's vector icon dynamically."""
        self._icon_name = icon_name
        if icon_size is not None:
            self._icon_size = icon_size
        if icon_name:
            img = get_icon(icon_name, color=self.variant, size=self._icon_size)
            self._current_image = img
            if not self._is_loading:
                self.configure(image=img, compound="left")
        else:
            self._current_image = None
            if not self._is_loading:
                self.configure(image=None)

    def set_variant(self, variant: str):
        """Dynamically switch variant styling."""
        if variant in BUTTON_VARIANTS:
            self.variant = variant
            var_cfg = BUTTON_VARIANTS[variant]
            cfg = {
                "fg_color": var_cfg["fg_color"],
                "hover_color": var_cfg["hover_color"],
                "text_color": var_cfg["text_color"],
                "border_width": var_cfg["border_width"],
            }
            if var_cfg.get("border_color") is not None and var_cfg.get("border_width", 0) > 0:
                cfg["border_color"] = var_cfg["border_color"]
            if self._icon_name:
                img = get_icon(self._icon_name, color=variant, size=self._icon_size)
                self._current_image = img
                if not self._is_loading:
                    cfg["image"] = img
            self.configure(**cfg)

    def start_loading(self, loading_text: Optional[str] = None):
        """
        Transition button to animated loading state with spinning indicator.
        Disables clicking while loading is active.
        """
        if loading_text is not None:
            self._loading_text = loading_text
        if self._is_loading:
            spinner = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            self.configure(text=f"{spinner} {self._loading_text}")
            return

        self._is_loading = True
        if loading_text is None:
            self._loading_text = self._raw_text
        self.configure(state="disabled", cursor="arrow", image=None)
        self._animate_spinner()

    def stop_loading(self, restore_text: Optional[str] = None):
        """Restore button from loading state back to normal."""
        if restore_text is not None:
            self._raw_text = restore_text

        if not self._is_loading:
            if restore_text is not None:
                self.configure(text=restore_text)
            return

        self._is_loading = False
        if self._loading_after_id:
            try:
                self.after_cancel(self._loading_after_id)
            except Exception:
                pass
            self._loading_after_id = None

        restore_cfg = {
            "text": self._raw_text,
            "state": "normal",
            "cursor": "hand2",
        }
        if self._icon_name:
            self._current_image = get_icon(self._icon_name, color=self.variant, size=self._icon_size)
            restore_cfg["image"] = self._current_image
            restore_cfg["compound"] = "left"
        elif self._current_image is not None:
            restore_cfg["image"] = self._current_image
        self.configure(**restore_cfg)

    def _animate_spinner(self):
        if not self._is_loading or not self.winfo_exists():
            return

        spinner = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
        self._spinner_idx += 1
        self.configure(text=f"{spinner} {self._loading_text}")
        self._loading_after_id = self.after(100, self._animate_spinner)

    def set_text(self, text: str):
        """Update button text and keep internal raw text in sync."""
        self._raw_text = text
        if not self._is_loading:
            self.configure(text=text)


# -----------------------------------------------------------------------------
# 4. BaseModal Component
# -----------------------------------------------------------------------------

class BaseModal(ctk.CTkToplevel):
    """
    Standard modal dialog base class for RakuTrans AI.
    Features:
    - Auto-centers relative to parent window (or screen)
    - Safe focus / grab management
    - Standard Esc key binding to close modal
    - Standard Enter key binding for confirm action
    - Proper grab_release on destruction
    """

    def __init__(
        self,
        parent,
        title: str = "",
        width: int = 560,
        height: int = 500,
        resizable: bool = False,
        on_close: Optional[Callable] = None,
        on_confirm: Optional[Callable] = None
    ):
        super().__init__(parent)
        self.parent = parent
        self._on_close_cb = on_close
        self._on_confirm_cb = on_confirm
        self._closed = False

        self.title(title)
        self.geometry(f"{width}x{height}")
        self.resizable(resizable, resizable)
        apply_windows_window_icon(self)

        # Modality setup
        self.transient(parent)
        try:
            self.grab_set()
        except Exception:
            pass

        # Center relative to parent
        self._center_on_parent(width, height)

        # Standard keyboard shortcuts
        self.bind("<Escape>", self._on_escape_pressed)
        if on_confirm:
            self.bind("<Return>", self._on_return_pressed)

        # Protocol for window close button (X)
        self.protocol("WM_DELETE_WINDOW", self.close_modal)

    def _center_on_parent(self, width: int, height: int):
        """Calculate and apply relative centering coordinates."""
        try:
            self.update_idletasks()
            if self.parent and self.parent.winfo_exists():
                px = self.parent.winfo_rootx()
                py = self.parent.winfo_rooty()
                pw = self.parent.winfo_width()
                ph = self.parent.winfo_height()
                x = px + (pw - width) // 2
                y = py + (ph - height) // 2
            else:
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()
                x = (sw - width) // 2
                y = (sh - height) // 2

            x = max(20, x)
            y = max(20, y)
            self.geometry(f"{width}x{height}+{x}+{y}")
        except Exception:
            pass

    def _on_escape_pressed(self, event=None):
        self.close_modal()
        return "break"

    def _on_return_pressed(self, event=None):
        # Do not fire Enter confirm if current widget is a multiline Textbox
        try:
            focused = self.focus_get()
            if focused and isinstance(focused, (tk.Text, ctk.CTkTextbox)):
                return
        except Exception:
            pass

        if self._on_confirm_cb:
            self._on_confirm_cb()
            return "break"

    def close_modal(self):
        """Gracefully release grab and destroy modal."""
        if self._closed:
            return
        self._closed = True

        if self._on_close_cb:
            try:
                self._on_close_cb()
            except Exception:
                pass

        try:
            self.grab_release()
        except Exception:
            pass

        try:
            self.destroy()
        except Exception:
            pass

