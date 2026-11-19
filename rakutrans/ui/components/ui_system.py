"""
UI System & Design Tokens for RakuTrans AI.
Provides unified button variants, standard sizing scales, loading buttons,
and a standardized BaseModal for consistent desktop UX.
"""

import tkinter as tk
from typing import Callable, Optional
import customtkinter as ctk

from rakutrans.ui.components.icons import get_icon, apply_windows_window_icon

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # noqa: F401
    HAS_TKDND = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    HAS_TKDND = False


# -----------------------------------------------------------------------------
# 1. Design Tokens
# -----------------------------------------------------------------------------

COLORS = {
    "text_primary": ("#18181B", "#FAFAFA"),
    "text_muted": ("#71717A", "#A1A1AA"),
    "text_secondary": ("#52525B", "#A1A1AA"),
    "text_body": ("#3F3F46", "#D4D4D8"),
    "surface_card": ("#FFFFFF", "#18181B"),
    "surface_subtle": ("#F4F4F5", "#18181B"),
    "surface_elevated": ("#FFFFFF", "#202023"),
    "surface_hover": ("#F4F4F5", "#27272A"),
    "border": ("#E4E4E7", "#27272A"),
    "border_strong": ("#D4D4D8", "#3F3F46"),
    "border_active": ("#71717A", "#A1A1AA"),
    "danger": ("#DC2626", "#EF4444"),
    "success": ("#16A34A", "#22C55E"),
    "warning": ("#D97706", "#F59E0B"),
    "warning_bg": ("#FEF3C7", "#451A03"),
    "warning_text": ("#B45309", "#FBBF24"),
    "error_bg": ("#FEF2F2", "#2A1818"),
    "error_border": ("#FCA5A5", "#7F1D1D"),
    "error_title": "#EF4444",
    "error_advice_title": ("#B91C1C", "#F87171"),
    "info_bg": ("#EFF6FF", "#172554"),
    "info_border": ("#BFDBFE", "#1D4ED8"),
    "info_text": ("#1E3A8A", "#DBEAFE"),
    "disabled_fg": ("#E4E4E7", "#27272A"),
    "disabled_text": ("#A1A1AA", "#71717A"),
}

UI_LAYOUT = {
    "main_geometry": "860x820",
    "main_minsize": (780, 680),
    "confirm_modal_size": (460, 240),
    "error_modal_size": (580, 540),
    "update_modal_size": (560, 460),
    "lang_trigger_width": 360,
    "lang_trigger_height": 36,
    "lang_panel_height": 240,
    "dropdown_row_height": 32,
}

UI_TIMING = {
    "spinner_interval_ms": 100,
    "grab_retry_delay_ms": 20,
    "debounce_save_ms": 300,
    "autofetch_delay_ms": 150,
    "copy_reset_delay_ms": 2000,
    "cache_refresh_delay_ms": 2500,
    "focus_delay_ms": 50,
    "startup_update_delay_ms": 1500,
}

BUTTON_SIZES = {
    "sm": {
        "height": 28,
        "font_size": 11,
        "corner_radius": 6,
    },
    "md": {
        "height": 34,
        "font_size": 12,
        "corner_radius": 8,
    },
    "lg": {
        "height": 40,
        "font_size": 13,
        "corner_radius": 8,
    }
}

BUTTON_VARIANTS = {
    # Primary actions (Start Translation, Save Settings, Hero Open File)
    "primary": {
        "fg_color": COLORS["text_primary"],
        "hover_color": ("#27272A", "#E4E4E7"),
        "text_color": ("#FFFFFF", "#18181B"),
        "border_width": 0,
        "border_color": None
    },
    # Secondary solid buttons (Browse, Select, Settings, Re-run actions)
    "secondary": {
        "fg_color": COLORS["disabled_fg"],
        "hover_color": COLORS["border_strong"],
        "text_color": COLORS["text_primary"],
        "border_width": 0,
        "border_color": None
    },
    # Outline buttons (Cancel, Close, Open Folder, Save As)
    "outline": {
        "fg_color": "transparent",
        "hover_color": COLORS["surface_hover"],
        "text_color": COLORS["text_primary"],
        "border_width": 1,
        "border_color": COLORS["border_strong"]
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
        "hover_color": COLORS["surface_hover"],
        "text_color": COLORS["text_primary"],
        "border_width": 0,
        "border_color": None
    },
}

# Muted surfaces for disabled CustomButton states so disabled primary
# buttons do not stay bright white in Dark Mode or solid black in Light Mode.
BUTTON_DISABLED_STYLES = {
    "filled": {
        "fg_color": COLORS["disabled_fg"],
        "text_color_disabled": COLORS["disabled_text"],
        "icon_color": COLORS["disabled_text"],
    },
    "loading": {
        "fg_color": COLORS["disabled_fg"],
        "text_color_disabled": COLORS["text_secondary"],
        "icon_color": COLORS["text_secondary"],
    },
    "transparent": {
        "fg_color": "transparent",
        "border_color": COLORS["disabled_fg"],
        "text_color_disabled": COLORS["disabled_text"],
        "icon_color": COLORS["disabled_text"],
    },
}

SEGMENTED_BUTTON_TOKENS = {
    "fg_color": ("#D4D4D8", "#27272A"),
    "selected_color": COLORS["text_primary"],
    "selected_hover_color": ("#27272A", "#E4E4E7"),
    "unselected_color": COLORS["surface_subtle"],
    "unselected_hover_color": COLORS["disabled_fg"],
    "selected_text_color": ("#FFFFFF", "#18181B"),
    "unselected_text_color": COLORS["text_muted"],
    "text_color_disabled": COLORS["disabled_text"],
    "selected_icon_color": "primary",
    "unselected_icon_color": "muted",
}

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


# -----------------------------------------------------------------------------
# 2. CustomButton Component
# -----------------------------------------------------------------------------

class CustomButton(ctk.CTkButton):
    """
    Standardized, high-accessibility button for RakuTrans AI.
    Features:
    - Standardized variants ('primary', 'secondary', 'outline', 'danger', 'ghost')
    - Standardized sizes ('sm', 'md', 'lg')
    - Native hand cursor (cursor='hand2')
    - Built-in loading state with animated spinner
    - Distinct muted visual styling when disabled across Light and Dark modes
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
        self._raw_text = text
        self._icon_name = icon_name
        self._icon_size = icon_size or (14 if size == "sm" else 16)
        self._is_loading = False
        self._spinner_idx = 0
        self._loading_after_id = None
        self._custom_fg_color = kwargs.get("fg_color")
        self._custom_border_color = kwargs.get("border_color")
        self._custom_text_color_disabled = kwargs.get("text_color_disabled")

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
            "text_color_disabled": BUTTON_DISABLED_STYLES["filled"]["text_color_disabled"],
            "command": command
        }

        # Apply variant styles if not explicitly passed
        for key, val in var_cfg.items():
            if key not in kwargs and val is not None:
                btn_kwargs[key] = val

        btn_kwargs.update(kwargs)

        initial_state = btn_kwargs.get("state", "normal")
        if initial_state == "disabled":
            self._inject_state_visuals("disabled", btn_kwargs, respect_existing=False)
        elif icon_name and "image" not in kwargs:
            btn_kwargs["image"] = get_icon(icon_name, color=variant, size=self._icon_size)
            btn_kwargs.setdefault("compound", "left")

        self._current_image = btn_kwargs.get("image")

        super().__init__(master, text=text, **btn_kwargs)

    def _disabled_style_key(self) -> str:
        var_cfg = BUTTON_VARIANTS.get(self.variant, BUTTON_VARIANTS["primary"])
        if self._is_loading:
            return "loading"
        if var_cfg["fg_color"] == "transparent" and self._custom_fg_color in (None, "transparent"):
            return "transparent"
        return "filled"

    def _inject_state_visuals(self, state_val: str, cfg: dict, respect_existing: bool = True):
        var_cfg = BUTTON_VARIANTS.get(self.variant, BUTTON_VARIANTS["primary"])
        if state_val == "disabled":
            dstyle = BUTTON_DISABLED_STYLES[self._disabled_style_key()]
            cfg.setdefault("cursor", "arrow")
            if self._custom_fg_color is None and ("fg_color" not in cfg or not respect_existing):
                cfg["fg_color"] = dstyle["fg_color"]
            if self._custom_text_color_disabled is None and ("text_color_disabled" not in cfg or not respect_existing):
                cfg["text_color_disabled"] = dstyle["text_color_disabled"]
            if var_cfg.get("border_width", 0) > 0 and self._custom_border_color is None:
                if "border_color" in dstyle and ("border_color" not in cfg or not respect_existing):
                    cfg["border_color"] = dstyle["border_color"]
            if self._icon_name and not self._is_loading and ("image" not in cfg or not respect_existing):
                img = get_icon(self._icon_name, color=dstyle["icon_color"], size=self._icon_size)
                self._current_image = img
                cfg["image"] = img
                cfg.setdefault("compound", "left")
        else:
            cfg.setdefault("cursor", "hand2")
            if self._custom_fg_color is None and ("fg_color" not in cfg or not respect_existing):
                cfg["fg_color"] = var_cfg["fg_color"]
            if "hover_color" not in cfg or not respect_existing:
                cfg["hover_color"] = var_cfg["hover_color"]
            if "text_color" not in cfg or not respect_existing:
                cfg["text_color"] = var_cfg["text_color"]
            if var_cfg.get("border_color") is not None and var_cfg.get("border_width", 0) > 0 and self._custom_border_color is None:
                if "border_color" not in cfg or not respect_existing:
                    cfg["border_color"] = var_cfg["border_color"]
            if self._icon_name and not self._is_loading and ("image" not in cfg or not respect_existing):
                img = get_icon(self._icon_name, color=self.variant, size=self._icon_size)
                self._current_image = img
                cfg["image"] = img
                cfg.setdefault("compound", "left")

    def configure(self, require_redraw=False, **kwargs):
        if "state" in kwargs:
            self._inject_state_visuals(kwargs["state"], kwargs, respect_existing=True)
        if "image" in kwargs and not self._is_loading:
            self._current_image = kwargs["image"]
        if "text" in kwargs and not self._is_loading:
            self._raw_text = kwargs["text"]
        return super().configure(require_redraw=require_redraw, **kwargs)

    def set_icon(self, icon_name: Optional[str], icon_size: Optional[int] = None):
        """Update the button's vector icon dynamically."""
        self._icon_name = icon_name
        if icon_size is not None:
            self._icon_size = icon_size
        if icon_name:
            cur_state = getattr(self, "_state", "normal")
            if cur_state == "disabled":
                icon_color = BUTTON_DISABLED_STYLES[self._disabled_style_key()]["icon_color"]
            else:
                icon_color = self.variant
            img = get_icon(icon_name, color=icon_color, size=self._icon_size)
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
            cur_state = getattr(self, "_state", "normal")
            cfg = {"border_width": var_cfg["border_width"]}
            self._inject_state_visuals(cur_state, cfg, respect_existing=False)
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
            self._loading_after_id = None
            return

        spinner = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
        self._spinner_idx += 1
        try:
            self.configure(text=f"{spinner} {self._loading_text}")
            self._loading_after_id = self.after(
                UI_TIMING["spinner_interval_ms"], self._animate_spinner
            )
        except Exception:
            self._loading_after_id = None

    def set_text(self, text: str):
        """Update button text and keep internal raw text in sync."""
        self._raw_text = text
        if not self._is_loading:
            self.configure(text=text)

    def destroy(self):
        self._is_loading = False
        if getattr(self, "_loading_after_id", None):
            try:
                self.after_cancel(self._loading_after_id)
            except Exception:
                pass
            self._loading_after_id = None
        super().destroy()


# -----------------------------------------------------------------------------
# 3. CustomSegmentedButton Component
# -----------------------------------------------------------------------------

class CustomSegmentedButton(ctk.CTkSegmentedButton):
    """
    Segmented control with high-contrast active vs. inactive segment styling
    across Light and Dark modes, including automatic per-segment text and icon
    color synchronization.
    """

    def __init__(
        self,
        master,
        selected_text_color=None,
        unselected_text_color=None,
        icons: Optional[dict] = None,
        **kwargs
    ):
        self._selected_text_color = (
            selected_text_color or SEGMENTED_BUTTON_TOKENS["selected_text_color"]
        )
        self._unselected_text_color = (
            unselected_text_color
            or kwargs.get("text_color")
            or SEGMENTED_BUTTON_TOKENS["unselected_text_color"]
        )
        self._segment_icons: dict = dict(icons or {})

        kwargs.setdefault("fg_color", SEGMENTED_BUTTON_TOKENS["fg_color"])
        kwargs.setdefault("selected_color", SEGMENTED_BUTTON_TOKENS["selected_color"])
        kwargs.setdefault("selected_hover_color", SEGMENTED_BUTTON_TOKENS["selected_hover_color"])
        kwargs.setdefault("unselected_color", SEGMENTED_BUTTON_TOKENS["unselected_color"])
        kwargs.setdefault("unselected_hover_color", SEGMENTED_BUTTON_TOKENS["unselected_hover_color"])
        kwargs.setdefault("text_color", self._unselected_text_color)
        kwargs.setdefault("text_color_disabled", SEGMENTED_BUTTON_TOKENS["text_color_disabled"])

        super().__init__(master, **kwargs)
        self._sync_segment_styles()

    def set_icons(self, icons: dict):
        """Register (icon_name, size) per segment value and refresh active/inactive icon colors."""
        self._segment_icons = dict(icons or {})
        self._sync_segment_styles()

    def _apply_segment_button_style(self, value: str, is_selected: bool):
        btn = self._buttons_dict.get(value)
        if btn is None:
            return
        cfg = {
            "text_color": self._selected_text_color if is_selected else self._unselected_text_color
        }
        if value in self._segment_icons:
            icon_name, icon_size = self._segment_icons[value]
            icon_color = (
                SEGMENTED_BUTTON_TOKENS["selected_icon_color"]
                if is_selected
                else SEGMENTED_BUTTON_TOKENS["unselected_icon_color"]
            )
            cfg["image"] = get_icon(icon_name, color=icon_color, size=icon_size)
            cfg["compound"] = "left"
        btn.configure(**cfg)

    def _sync_segment_styles(self):
        for value in list(self._buttons_dict.keys()):
            self._apply_segment_button_style(value, value == self._current_value)

    def _select_button_by_value(self, value: str):
        super()._select_button_by_value(value)
        self._apply_segment_button_style(value, True)

    def _unselect_button_by_value(self, value: str):
        super()._unselect_button_by_value(value)
        self._apply_segment_button_style(value, False)

    def configure(self, **kwargs):
        if "selected_text_color" in kwargs:
            self._selected_text_color = kwargs.pop("selected_text_color")
        if "unselected_text_color" in kwargs:
            self._unselected_text_color = kwargs.pop("unselected_text_color")
        needs_sync = any(
            k in kwargs for k in ("values", "text_color", "selected_text_color", "unselected_text_color")
        )
        res = super().configure(**kwargs)
        if needs_sync:
            self._sync_segment_styles()
        return res


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
        self._grab_after_id = None
        self.transient(parent)
        try:
            self.grab_set()
        except Exception:
            pass
        try:
            self._grab_after_id = self.after(
                UI_TIMING["grab_retry_delay_ms"], self._ensure_grab
            )
        except Exception:
            self._grab_after_id = None

        # Center relative to parent
        self._center_on_parent(width, height)

        # Standard keyboard shortcuts
        self.bind("<Escape>", self._on_escape_pressed)
        if on_confirm:
            self.bind("<Return>", self._on_return_pressed)

        # Protocol for window close button (X)
        self.protocol("WM_DELETE_WINDOW", self.close_modal)

    def _ensure_grab(self):
        self._grab_after_id = None
        try:
            if self.winfo_exists() and self.winfo_ismapped():
                self.grab_set()
        except Exception:
            pass

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
                # Keep title bar visible on primary monitor while preserving negative multi-monitor coords
                if px >= 0:
                    x = max(20, x)
                if py >= 0:
                    y = max(20, y)
            else:
                sw = self.winfo_screenwidth()
                sh = self.winfo_screenheight()
                x = max(20, (sw - width) // 2)
                y = max(20, (sh - height) // 2)

            self.geometry(f"{width}x{height}{x:+d}{y:+d}")
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

    def destroy(self):
        if getattr(self, "_grab_after_id", None):
            try:
                self.after_cancel(self._grab_after_id)
            except Exception:
                pass
            self._grab_after_id = None
        super().destroy()

