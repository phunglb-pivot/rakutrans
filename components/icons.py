"""
Cross-platform vector-rendered icon system for RakuTrans AI.
Generates crisp 4x-supersampled anti-aliased icons via Pillow and wraps them
in CustomTkinter CTkImage objects with automatic Light/Dark mode color adaptation.
Replaces OS-dependent Unicode emojis that render poorly on Windows Tkinter.
"""

from functools import lru_cache
import math
from pathlib import Path
import platform
from typing import Optional, Tuple, Union

import customtkinter as ctk
from PIL import Image, ImageDraw


ColorPair = Union[str, Tuple[str, str]]

# Standardized icon color tokens matching BUTTON_VARIANTS & Tailwind Zinc palette
ICON_COLORS = {
    "primary": ("#FFFFFF", "#18181B"),
    "accent": ("#FFFFFF", "#18181B"),
    "info": ("#FFFFFF", "#18181B"),
    "secondary": ("#18181B", "#FAFAFA"),
    "outline": ("#18181B", "#FAFAFA"),
    "ghost": ("#18181B", "#FAFAFA"),
    "danger": ("#FFFFFF", "#FFFFFF"),
    "default": ("#18181B", "#FAFAFA"),
    "muted": ("#71717A", "#A1A1AA"),
    "success_accent": ("#059669", "#34D399"),
    "info_accent": ("#2563EB", "#60A5FA"),
    "warning_accent": ("#D97706", "#FBBF24"),
    "danger_accent": ("#DC2626", "#F87171"),
}

_SUPERSAMPLE = 4


def _hex_to_rgba(color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    c = color.strip().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        return (24, 24, 27, alpha)
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), alpha)


def _resolve_colors(color: ColorPair) -> Tuple[str, str]:
    if isinstance(color, tuple) and len(color) == 2:
        return color[0], color[1]
    if isinstance(color, str):
        if color in ICON_COLORS:
            return ICON_COLORS[color]
        return color, color
    return ICON_COLORS["default"]


def _s(v: float, scale: float) -> float:
    return v * scale


def _draw_thick_line(draw: ImageDraw.ImageDraw, pts, color, width: int):
    if len(pts) < 2:
        return
    draw.line(pts, fill=color, width=width, joint="curve")
    r = max(1.0, width / 2.0)
    for x, y in (pts[0], pts[-1]):
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def _draw_arc_with_caps(
    draw: ImageDraw.ImageDraw,
    bbox,
    start: float,
    end: float,
    color,
    width: int,
    cx: float,
    cy: float,
    radius: float,
):
    draw.arc(bbox, start=start, end=end, fill=color, width=width)
    r_cap = max(1.0, width / 2.0)
    for deg in (start, end):
        rad = math.radians(deg)
        px = cx + radius * math.cos(rad)
        py = cy + radius * math.sin(rad)
        draw.ellipse((px - r_cap, py - r_cap, px + r_cap, py + r_cap), fill=color)


def _render_vector_icon(name: str, color_hex: str, px_size: int) -> Image.Image:
    """Renders a 24x24 viewBox Lucide-style vector icon at 4x resolution and downsamples cleanly."""
    canvas_size = px_size * _SUPERSAMPLE
    scale = canvas_size / 24.0
    sw = max(2, round(1.9 * scale))  # stroke width
    sw_thin = max(2, round(1.55 * scale))

    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    col = _hex_to_rgba(color_hex)

    def p(x: float, y: float) -> Tuple[float, float]:
        return (x * scale, y * scale)

    def rect(x1, y1, x2, y2):
        return (x1 * scale, y1 * scale, x2 * scale, y2 * scale)

    if name == "globe":
        draw.ellipse(rect(2.5, 2.5, 21.5, 21.5), outline=col, width=sw)
        draw.ellipse(rect(8.2, 2.5, 15.8, 21.5), outline=col, width=sw_thin)
        _draw_thick_line(draw, [p(3.0, 12.0), p(21.0, 12.0)], col, sw_thin)
        _draw_thick_line(draw, [p(4.6, 7.6), p(19.4, 7.6)], col, max(1, round(1.3 * scale)))
        _draw_thick_line(draw, [p(4.6, 16.4), p(19.4, 16.4)], col, max(1, round(1.3 * scale)))

    elif name == "settings":
        # Gear outer teeth + inner circle
        cx, cy = 12.0, 12.0
        r_outer = 9.4
        r_inner = 7.0
        pts = []
        teeth = 8
        for i in range(teeth * 4):
            ang = (i * 2.0 * math.pi) / (teeth * 4)
            phase = i % 4
            r = r_outer if phase in (0, 1) else r_inner
            pts.append((cx * scale + r * scale * math.cos(ang), cy * scale + r * scale * math.sin(ang)))
        pts.append(pts[0])
        draw.line(pts, fill=col, width=sw_thin, joint="curve")
        draw.ellipse(rect(8.8, 8.8, 15.2, 15.2), outline=col, width=sw)

    elif name in ("refresh", "convert"):
        cx, cy, rad = 12.0, 12.0, 8.2
        bb = rect(cx - rad, cy - rad, cx + rad, cy + rad)
        _draw_arc_with_caps(draw, bb, -155, -20, col, sw, cx * scale, cy * scale, rad * scale)
        _draw_arc_with_caps(draw, bb, 25, 160, col, sw, cx * scale, cy * scale, rad * scale)
        # Top-right arrowhead
        _draw_thick_line(draw, [p(16.6, 4.6), p(19.9, 8.8), p(15.3, 9.2)], col, sw)
        # Bottom-left arrowhead
        _draw_thick_line(draw, [p(7.4, 19.4), p(4.1, 15.2), p(8.7, 14.8)], col, sw)

    elif name == "rotate_ccw":
        cx, cy, rad = 12.0, 12.0, 8.2
        bb = rect(cx - rad, cy - rad, cx + rad, cy + rad)
        _draw_arc_with_caps(draw, bb, -125, 195, col, sw, cx * scale, cy * scale, rad * scale)
        _draw_thick_line(draw, [p(3.6, 5.0), p(4.3, 9.6), p(9.0, 8.9)], col, sw)

    elif name == "folder":
        pts = [
            p(3.0, 5.6),
            p(9.6, 5.6),
            p(11.6, 8.0),
            p(20.6, 8.0),
            p(21.0, 8.4),
            p(21.0, 18.4),
            p(20.6, 18.8),
            p(3.4, 18.8),
            p(3.0, 18.4),
            p(3.0, 5.6),
        ]
        draw.line(pts, fill=col, width=sw, joint="curve")

    elif name == "folder_hero":
        # Soft modern dual-tone folder for DropZone idle state
        fill_back = _hex_to_rgba("#94A3B8" if color_hex.upper() in ("#18181B", "#000000") else "#64748B", 230)
        fill_front = _hex_to_rgba("#CBD5E1" if color_hex.upper() in ("#18181B", "#000000") else "#94A3B8", 245)
        paper_col = _hex_to_rgba("#FFFFFF", 240)
        # Back flap
        draw.rounded_rectangle(rect(2.5, 4.2, 11.2, 10.5), radius=1.8 * scale, fill=fill_back)
        draw.rounded_rectangle(rect(2.5, 6.5, 21.5, 19.2), radius=2.2 * scale, fill=fill_back)
        # Document sheet peeking out
        draw.rounded_rectangle(rect(4.6, 7.6, 19.4, 14.0), radius=1.2 * scale, fill=paper_col)
        # Front folder body
        draw.rounded_rectangle(rect(2.5, 9.6, 21.5, 19.8), radius=2.2 * scale, fill=fill_front)

    elif name in ("file_text", "file_generic"):
        # Clean page with folded corner
        pts = [
            p(5.2, 2.8), p(14.5, 2.8), p(19.2, 7.5), p(19.2, 20.8),
            p(18.6, 21.4), p(5.2, 21.4), p(4.6, 20.8), p(4.6, 3.4), p(5.2, 2.8)
        ]
        draw.line(pts, fill=col, width=sw, joint="curve")
        _draw_thick_line(draw, [p(14.4, 3.0), p(14.4, 7.6), p(19.0, 7.6)], col, sw_thin)
        _draw_thick_line(draw, [p(8.2, 11.0), p(15.6, 11.0)], col, sw_thin)
        _draw_thick_line(draw, [p(8.2, 14.3), p(15.6, 14.3)], col, sw_thin)
        _draw_thick_line(draw, [p(8.2, 17.6), p(13.0, 17.6)], col, sw_thin)

    elif name in ("file_excel", "file_word", "file_ppt", "file_pdf", "file_md", "file_json"):
        palette = {
            "file_excel": "#16A34A",
            "file_word": "#2563EB",
            "file_ppt": "#EA580C",
            "file_pdf": "#DC2626",
            "file_md": "#6366F1",
            "file_json": "#D97706",
        }
        accent = _hex_to_rgba(palette[name], 255)
        soft_bg = _hex_to_rgba(palette[name], 34)
        poly_fill = [p(4.6, 2.8), p(14.6, 2.8), p(19.4, 7.6), p(19.4, 21.2), p(4.6, 21.2)]
        draw.polygon(poly_fill, fill=soft_bg)
        pts = [
            p(5.0, 2.8), p(14.6, 2.8), p(19.4, 7.6), p(19.4, 20.8),
            p(18.8, 21.4), p(5.0, 21.4), p(4.4, 20.8), p(4.4, 3.4), p(5.0, 2.8)
        ]
        draw.line(pts, fill=accent, width=sw, joint="curve")
        _draw_thick_line(draw, [p(14.5, 3.0), p(14.5, 7.6), p(19.2, 7.6)], accent, sw_thin)
        if name == "file_excel":
            draw.rounded_rectangle(rect(7.2, 10.2, 16.8, 18.2), radius=0.9 * scale, outline=accent, width=sw_thin)
            _draw_thick_line(draw, [p(7.4, 14.2), p(16.6, 14.2)], accent, sw_thin)
            _draw_thick_line(draw, [p(12.0, 10.4), p(12.0, 18.0)], accent, sw_thin)
        elif name == "file_ppt":
            draw.rounded_rectangle(rect(7.2, 10.4, 16.8, 16.8), radius=0.9 * scale, outline=accent, width=sw_thin)
            _draw_thick_line(draw, [p(12.0, 16.8), p(12.0, 19.0)], accent, sw_thin)
            _draw_thick_line(draw, [p(9.5, 19.0), p(14.5, 19.0)], accent, sw_thin)
        elif name == "file_json":
            # Curly braces { }
            _draw_thick_line(draw, [p(10.2, 10.2), p(8.6, 10.8), p(8.6, 13.4), p(7.4, 14.2), p(8.6, 15.0), p(8.6, 17.6), p(10.2, 18.2)], accent, sw_thin)
            _draw_thick_line(draw, [p(13.8, 10.2), p(15.4, 10.8), p(15.4, 13.4), p(16.6, 14.2), p(15.4, 15.0), p(15.4, 17.6), p(13.8, 18.2)], accent, sw_thin)
        else:
            _draw_thick_line(draw, [p(7.8, 10.8), p(16.2, 10.8)], accent, sw_thin)
            _draw_thick_line(draw, [p(7.8, 14.2), p(16.2, 14.2)], accent, sw_thin)
            _draw_thick_line(draw, [p(7.8, 17.6), p(13.2, 17.6)], accent, sw_thin)

    elif name in ("database", "save"):
        # Clean floppy / storage icon
        draw.rounded_rectangle(rect(3.5, 3.5, 20.5, 20.5), radius=2.2 * scale, outline=col, width=sw)
        draw.rounded_rectangle(rect(7.2, 3.6, 15.2, 8.8), radius=0.8 * scale, outline=col, width=sw_thin)
        draw.rounded_rectangle(rect(6.8, 13.4, 17.2, 20.4), radius=1.0 * scale, outline=col, width=sw_thin)

    elif name == "trash":
        _draw_thick_line(draw, [p(3.8, 6.4), p(20.2, 6.4)], col, sw)
        _draw_thick_line(draw, [p(8.8, 6.2), p(8.8, 3.8), p(15.2, 3.8), p(15.2, 6.2)], col, sw_thin)
        draw.rounded_rectangle(rect(5.8, 6.4, 18.2, 20.4), radius=1.8 * scale, outline=col, width=sw)
        _draw_thick_line(draw, [p(10.0, 10.2), p(10.0, 16.8)], col, sw_thin)
        _draw_thick_line(draw, [p(14.0, 10.2), p(14.0, 16.8)], col, sw_thin)

    elif name == "alert_triangle":
        pts = [p(12.0, 3.2), p(21.4, 19.6), p(2.6, 19.6), p(12.0, 3.2)]
        draw.line(pts, fill=col, width=sw, joint="curve")
        _draw_thick_line(draw, [p(12.0, 9.2), p(12.0, 13.8)], col, sw)
        r_dot = 1.15 * scale
        cx, cy = p(12.0, 16.8)
        draw.ellipse((cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot), fill=col)

    elif name == "check":
        _draw_thick_line(draw, [p(4.5, 12.6), p(9.6, 17.6), p(19.6, 6.8)], col, sw)

    elif name == "info":
        draw.ellipse(rect(2.8, 2.8, 21.2, 21.2), outline=col, width=sw)
        _draw_thick_line(draw, [p(12.0, 11.2), p(12.0, 16.8)], col, sw)
        r_dot = 1.15 * scale
        cx, cy = p(12.0, 7.8)
        draw.ellipse((cx - r_dot, cy - r_dot, cx + r_dot, cy + r_dot), fill=col)

    elif name == "close":
        _draw_thick_line(draw, [p(5.8, 5.8), p(18.2, 18.2)], col, sw)
        _draw_thick_line(draw, [p(18.2, 5.8), p(5.8, 18.2)], col, sw)

    elif name == "plus":
        _draw_thick_line(draw, [p(12.0, 5.0), p(12.0, 19.0)], col, sw)
        _draw_thick_line(draw, [p(5.0, 12.0), p(19.0, 12.0)], col, sw)

    elif name == "minus":
        _draw_thick_line(draw, [p(5.0, 12.0), p(19.0, 12.0)], col, sw)

    elif name == "arrow_left":
        _draw_thick_line(draw, [p(19.0, 12.0), p(5.0, 12.0)], col, sw)
        _draw_thick_line(draw, [p(11.2, 5.8), p(5.0, 12.0), p(11.2, 18.2)], col, sw)

    elif name == "zap":
        pts = [p(13.2, 2.5), p(4.5, 13.6), p(11.6, 13.6), p(10.6, 21.5), p(19.5, 10.4), p(12.4, 10.4), p(13.2, 2.5)]
        draw.line(pts, fill=col, width=sw, joint="curve")

    elif name == "eye":
        # Top and bottom eye curves
        cx, cy = 12.0, 12.0
        top_pts = []
        bot_pts = []
        for i in range(21):
            t = i / 20.0
            x = 2.6 + t * 18.8
            arch = math.sin(t * math.pi) * 5.6
            top_pts.append(p(x, cy - arch))
            bot_pts.append(p(x, cy + arch))
        draw.line(top_pts, fill=col, width=sw, joint="curve")
        draw.line(bot_pts, fill=col, width=sw, joint="curve")
        draw.ellipse(rect(9.0, 9.0, 15.0, 15.0), outline=col, width=sw)

    elif name == "lock":
        draw.rounded_rectangle(rect(4.5, 10.5, 19.5, 20.8), radius=2.2 * scale, outline=col, width=sw)
        _draw_arc_with_caps(draw, rect(7.5, 3.6, 16.5, 13.4), 180, 360, col, sw, 12.0 * scale, 8.5 * scale, 4.5 * scale)
        _draw_thick_line(draw, [p(7.5, 8.5), p(7.5, 10.5)], col, sw)
        _draw_thick_line(draw, [p(16.5, 8.5), p(16.5, 10.5)], col, sw)

    elif name == "key":
        draw.ellipse(rect(3.0, 10.5, 11.2, 18.7), outline=col, width=sw)
        _draw_thick_line(draw, [p(10.2, 12.0), p(20.4, 3.8)], col, sw)
        _draw_thick_line(draw, [p(17.8, 5.9), p(20.4, 8.4)], col, sw)
        _draw_thick_line(draw, [p(15.2, 8.0), p(17.5, 10.2)], col, sw)

    elif name in ("clock", "quota"):
        draw.ellipse(rect(2.8, 2.8, 21.2, 21.2), outline=col, width=sw)
        _draw_thick_line(draw, [p(12.0, 6.8), p(12.0, 12.2), p(15.8, 14.2)], col, sw)

    elif name == "stop_circle":
        draw.ellipse(rect(2.8, 2.8, 21.2, 21.2), outline=col, width=sw)
        draw.rounded_rectangle(rect(9.0, 9.0, 15.0, 15.0), radius=0.9 * scale, fill=col)

    elif name == "lightbulb":
        _draw_arc_with_caps(draw, rect(5.8, 2.8, 18.2, 15.2), 140, 400, col, sw, 12.0 * scale, 9.0 * scale, 6.2 * scale)
        _draw_thick_line(draw, [p(8.8, 14.4), p(9.2, 17.2), p(14.8, 17.2), p(15.2, 14.4)], col, sw_thin)
        _draw_thick_line(draw, [p(9.6, 20.2), p(14.4, 20.2)], col, sw)

    elif name == "copy":
        draw.rounded_rectangle(rect(8.5, 8.5, 20.2, 20.2), radius=2.0 * scale, outline=col, width=sw)
        _draw_thick_line(draw, [p(5.2, 15.5), p(4.2, 15.5), p(4.2, 4.2), p(15.5, 4.2), p(15.5, 5.5)], col, sw)

    elif name == "search":
        draw.ellipse(rect(3.5, 3.5, 16.5, 16.5), outline=col, width=sw)
        _draw_thick_line(draw, [p(14.8, 14.8), p(20.4, 20.4)], col, sw)

    elif name == "format":
        # Code / blocks icon for format errors
        _draw_thick_line(draw, [p(8.5, 7.0), p(3.5, 12.0), p(8.5, 17.0)], col, sw)
        _draw_thick_line(draw, [p(15.5, 7.0), p(20.5, 12.0), p(15.5, 17.0)], col, sw)
        _draw_thick_line(draw, [p(13.5, 5.0), p(10.5, 19.0)], col, sw_thin)

    else:
        draw.ellipse(rect(5.0, 5.0, 19.0, 19.0), outline=col, width=sw)

    return img.resize((px_size, px_size), Image.Resampling.LANCZOS)


@lru_cache(maxsize=256)
def _cached_pil_pair(name: str, light_hex: str, dark_hex: str, size: int) -> Tuple[Image.Image, Image.Image]:
    # Render at 2x target display size so HiDPI / Retina displays stay ultra-sharp
    render_px = max(16, size * 2)
    light_img = _render_vector_icon(name, light_hex, render_px)
    dark_img = light_img if dark_hex == light_hex else _render_vector_icon(name, dark_hex, render_px)
    return light_img, dark_img


def get_icon(name: str, color: ColorPair = "default", size: int = 16) -> ctk.CTkImage:
    """
    Returns a cached CTkImage vector icon with automatic Light/Dark mode support.
    `color` can be a preset name in ICON_COLORS (e.g. 'primary', 'secondary', 'muted')
    or a hex string / (light_hex, dark_hex) tuple.
    """
    light_hex, dark_hex = _resolve_colors(color)
    light_img, dark_img = _cached_pil_pair(name, light_hex, dark_hex, size)
    return ctk.CTkImage(light_image=light_img, dark_image=dark_img, size=(size, size))


# -----------------------------------------------------------------------------
# Windows Taskbar & Window Icon Helpers
# -----------------------------------------------------------------------------

_APP_USER_MODEL_ID = "RakuTrans.AI.Desktop"


def init_windows_app_id():
    """
    Sets a dedicated Windows AppUserModelID before any Tk window is created so the
    Windows Taskbar displays RakuTrans's own icon instead of grouping under python.exe.
    """
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
    except Exception:
        pass


def get_assets_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "assets"


def apply_windows_window_icon(window, ico_path: Optional[Path] = None):
    """
    Applies the multi-size .ico file to a CTk / CTkToplevel window on Windows and marks
    CustomTkinter's internal `_iconbitmap_method_called` flag so CustomTkinter will not
    overwrite the icon after 200ms with `CustomTkinter_icon_Windows.ico`.
    """
    if platform.system() != "Windows":
        return

    target_ico = ico_path or (get_assets_dir() / "icon.ico")
    if not target_ico.exists():
        return

    try:
        window.iconbitmap(default=str(target_ico))
    except Exception:
        try:
            window.iconbitmap(str(target_ico))
        except Exception:
            pass

    # Also push high-res ICON_BIG / ICON_SMALL via Win32 WM_SETICON for crisp Taskbar & Alt-Tab
    def _set_win32_icons():
        try:
            if not window.winfo_exists():
                return
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(window.winfo_id()) or window.winfo_id()
            if not hwnd:
                return
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1

            hicon_big = user32.LoadImageW(None, str(target_ico), IMAGE_ICON, 256, 256, LR_LOADFROMFILE)
            if not hicon_big:
                hicon_big = user32.LoadImageW(None, str(target_ico), IMAGE_ICON, 48, 48, LR_LOADFROMFILE)
            hicon_small = user32.LoadImageW(None, str(target_ico), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)

            if hicon_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
            if hicon_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        except Exception:
            pass

    try:
        window.after(50, _set_win32_icons)
    except Exception:
        pass
