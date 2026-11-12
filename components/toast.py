"""
Toast Notification Component for RakuTrans AI.
Displays smooth, non-intrusive floating feedback cards inside the application window.
"""

from typing import Optional
import customtkinter as ctk

TOAST_STYLES = {
    "success": {
        "icon": "✓",
        "bg_color": ("#ECFDF5", "#064E3B"),
        "border_color": ("#A7F3D0", "#059669"),
        "text_color": ("#065F46", "#ECFDF5"),
        "icon_color": ("#059669", "#34D399")
    },
    "info": {
        "icon": "ℹ",
        "bg_color": ("#EFF6FF", "#1E3A8A"),
        "border_color": ("#BFDBFE", "#3B82F6"),
        "text_color": ("#1E40AF", "#EFF6FF"),
        "icon_color": ("#2563EB", "#60A5FA")
    },
    "warning": {
        "icon": "⚠️",
        "bg_color": ("#FFFBEB", "#78350F"),
        "border_color": ("#FDE68A", "#D97706"),
        "text_color": ("#92400E", "#FEF3C7"),
        "icon_color": ("#D97706", "#FBBF24")
    },
    "error": {
        "icon": "✕",
        "bg_color": ("#FEF2F2", "#7F1D1D"),
        "border_color": ("#FECACA", "#DC2626"),
        "text_color": ("#991B1B", "#FEE2E2"),
        "icon_color": ("#DC2626", "#F87171")
    }
}


class ToastManager:
    """
    Manages displaying floating in-app notifications.
    Positions toast at the top-right of the window with auto-dismiss.
    """

    _active_toast: Optional[ctk.CTkFrame] = None
    _dismiss_after_id = None

    @classmethod
    def show(
        cls,
        parent: ctk.CTk,
        message: str,
        toast_type: str = "success",
        duration_ms: int = 2800
    ):
        """Display a toast notification."""
        # Dismiss any current toast first
        cls.dismiss()

        if not parent or not parent.winfo_exists():
            return

        style = TOAST_STYLES.get(toast_type, TOAST_STYLES["info"])

        toast = ctk.CTkFrame(
            parent,
            fg_color=style["bg_color"],
            border_width=1,
            border_color=style["border_color"],
            corner_radius=10
        )
        cls._active_toast = toast

        content = ctk.CTkFrame(toast, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=14, pady=8)

        icon_lbl = ctk.CTkLabel(
            content,
            text=style["icon"],
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=style["icon_color"]
        )
        icon_lbl.pack(side="left", padx=(0, 8))

        msg_lbl = ctk.CTkLabel(
            content,
            text=message,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=style["text_color"],
            wraplength=380,
            justify="left"
        )
        msg_lbl.pack(side="left")

        # Allow clicking toast to dismiss early
        def _on_click(e=None):
            cls.dismiss()

        toast.bind("<Button-1>", _on_click)
        content.bind("<Button-1>", _on_click)
        icon_lbl.bind("<Button-1>", _on_click)
        msg_lbl.bind("<Button-1>", _on_click)

        # Place at top-right
        toast.place(relx=0.96, rely=0.08, anchor="ne")
        toast.lift()

        # Auto dismiss
        cls._dismiss_after_id = parent.after(duration_ms, cls.dismiss)

    @classmethod
    def dismiss(cls):
        """Immediately remove active toast if present."""
        if cls._dismiss_after_id and cls._active_toast:
            try:
                cls._active_toast.after_cancel(cls._dismiss_after_id)
            except Exception:
                pass
            cls._dismiss_after_id = None

        if cls._active_toast:
            try:
                if cls._active_toast.winfo_exists():
                    cls._active_toast.destroy()
            except Exception:
                pass
            cls._active_toast = None

