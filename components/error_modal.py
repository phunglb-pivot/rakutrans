"""
Error diagnosis modal for RakuTrans AI.
Displays actionable troubleshooting guidance, error details, log copying, and quick recovery buttons.
"""

from typing import Callable, Optional
import customtkinter as ctk

from error_handler import DiagnosticInfo


CATEGORY_ICONS = {
    "quota": "⏳",
    "auth": "🔑",
    "network": "🌐",
    "file_lock": "🔒",
    "format": "🧩",
    "cancelled": "⏹",
    "general": "⚠️"
}


class ErrorModal(ctk.CTkToplevel):
    """
    User-friendly modal dialog showing error diagnosis and resolution actions.
    """

    def __init__(
        self,
        parent,
        diag: DiagnosticInfo,
        on_retry: Optional[Callable[[], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
        get_translation: Optional[Callable[[str], str]] = None
    ):
        super().__init__(parent)
        self.diag = diag
        self.on_retry = on_retry
        self.on_open_settings = on_open_settings
        self.t = get_translation or (lambda k, **kw: k)

        self.title(self.t("error_modal_title", default="Error Details & Diagnosis"))
        self.geometry("580x520")
        self.minsize(500, 420)

        self.transient(parent)
        self.grab_set()

        self._setup_ui()

    def _setup_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=20)
        container.grid_columnconfigure(0, weight=1)

        # 1. Header with Icon & Title
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 12))

        icon = CATEGORY_ICONS.get(self.diag.category, "⚠️")
        icon_label = ctk.CTkLabel(header_frame, text=icon, font=ctk.CTkFont(size=32))
        icon_label.pack(side="left", padx=(0, 12))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)

        title_label = ctk.CTkLabel(
            title_box,
            text=self.diag.title,
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#EF4444",
            anchor="w"
        )
        title_label.pack(fill="x")

        subtitle_label = ctk.CTkLabel(
            title_box,
            text=self.diag.message,
            font=ctk.CTkFont(size=12),
            text_color=("gray30", "gray70"),
            wraplength=460,
            justify="left",
            anchor="w"
        )
        subtitle_label.pack(fill="x", pady=(2, 0))

        # 2. Action Advice Box
        advice_box = ctk.CTkFrame(
            container,
            fg_color=("#FEF2F2", "#2A1818"),
            border_width=1,
            border_color=("#FCA5A5", "#7F1D1D"),
            corner_radius=8
        )
        advice_box.pack(fill="x", pady=(0, 12), padx=2)

        advice_title = ctk.CTkLabel(
            advice_box,
            text="💡 " + self.t("err_how_to_fix", default="Recommended Action:"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=("#B91C1C", "#F87171")
        )
        advice_title.pack(anchor="w", padx=12, pady=(10, 2))

        advice_body = ctk.CTkLabel(
            advice_box,
            text=self.diag.action_advice,
            font=ctk.CTkFont(size=12),
            wraplength=480,
            justify="left"
        )
        advice_body.pack(anchor="w", padx=12, pady=(0, 10))

        # 3. Technical Log Section
        log_header = ctk.CTkFrame(container, fg_color="transparent")
        log_header.pack(fill="x", pady=(0, 4))

        ctk.CTkLabel(
            log_header,
            text=self.t("err_technical_details", default="Technical Error Log:"),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray"
        ).pack(side="left")

        self.copy_btn = ctk.CTkButton(
            log_header,
            text="📋 " + self.t("copy_log", default="Copy Log"),
            width=85,
            height=24,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            border_width=1,
            text_color=("gray30", "gray70"),
            command=self._copy_log
        )
        self.copy_btn.pack(side="right")

        self.log_textbox = ctk.CTkTextbox(
            container,
            height=130,
            font=ctk.CTkFont(family="Courier", size=10)
        )
        self.log_textbox.pack(fill="both", expand=True, pady=(0, 14))
        self.log_textbox.insert("1.0", self.diag.technical_details)
        self.log_textbox.configure(state="disabled")

        # 4. Action Buttons Bar
        btn_bar = ctk.CTkFrame(container, fg_color="transparent")
        btn_bar.pack(fill="x")

        if self.on_retry and self.diag.can_retry:
            retry_btn = ctk.CTkButton(
                btn_bar,
                text="⚡ " + self.t("retry_translation", default="Retry"),
                command=self._handle_retry,
                font=ctk.CTkFont(size=12, weight="bold"),
                fg_color="#10B981",
                hover_color="#059669",
                height=34
            )
            retry_btn.pack(side="left", padx=(0, 8))

        if self.on_open_settings and self.diag.requires_settings:
            settings_btn = ctk.CTkButton(
                btn_bar,
                text="⚙ " + self.t("settings_btn", default="Settings"),
                command=self._handle_settings,
                font=ctk.CTkFont(size=12),
                height=34
            )
            settings_btn.pack(side="left", padx=(0, 8))

        close_btn = ctk.CTkButton(
            btn_bar,
            text=self.t("close", default="Close"),
            command=self.destroy,
            font=ctk.CTkFont(size=12),
            fg_color="transparent",
            border_width=1,
            text_color=("gray20", "gray80"),
            height=34
        )
        close_btn.pack(side="right")

    def _copy_log(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.diag.technical_details)
            self.copy_btn.configure(text="✓ " + self.t("copied", default="Copied!"))
            self.after(2000, lambda: self.copy_btn.configure(text="📋 " + self.t("copy_log", default="Copy Log")))
        except Exception:
            pass

    def _handle_retry(self):
        self.destroy()
        if self.on_retry:
            self.on_retry()

    def _handle_settings(self):
        self.destroy()
        if self.on_open_settings:
            self.on_open_settings()
