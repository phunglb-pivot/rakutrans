"""
Error diagnosis modal for RakuTrans AI.
Displays actionable troubleshooting guidance, error details, log copying, and quick recovery buttons.
"""

from typing import Callable, Optional
import customtkinter as ctk

from error_handler import DiagnosticInfo
from components.ui_system import BaseModal, CustomButton


CATEGORY_ICONS = {
    "quota": "⏳",
    "auth": "🔑",
    "network": "🌐",
    "file_lock": "🔒",
    "format": "🧩",
    "cancelled": "⏹",
    "general": "⚠️"
}


class ErrorModal(BaseModal):
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
        self.diag = diag
        self.on_retry = on_retry
        self.on_open_settings = on_open_settings
        self.t = get_translation or (lambda k, **kw: k)

        super().__init__(
            parent=parent,
            title=self.t("error_modal_title"),
            width=580,
            height=540,
            resizable=False,
            on_confirm=self._handle_retry if (on_retry and diag.can_retry) else None
        )

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
            text="💡 " + self.t("err_how_to_fix"),
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
            text=self.t("err_technical_details"),
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color="gray"
        ).pack(side="left")

        self.copy_btn = CustomButton(
            log_header,
            text="📋 " + self.t("copy_log"),
            variant="outline",
            size="sm",
            width=90,
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
            retry_btn = CustomButton(
                btn_bar,
                text="⚡ " + self.t("retry_translation"),
                variant="primary",
                size="md",
                command=self._handle_retry
            )
            retry_btn.pack(side="left", padx=(0, 8))

        if self.on_open_settings and self.diag.requires_settings:
            settings_btn = CustomButton(
                btn_bar,
                text="⚙ " + self.t("settings_btn"),
                variant="secondary",
                size="md",
                command=self._handle_settings
            )
            settings_btn.pack(side="left", padx=(0, 8))

        close_btn = CustomButton(
            btn_bar,
            text=self.t("close"),
            variant="outline",
            size="md",
            command=self.close_modal
        )
        close_btn.pack(side="right")

    def _copy_log(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self.diag.technical_details)
            self.copy_btn.configure(text="✓ " + self.t("copied"))
            self.after(2000, lambda: self.copy_btn.configure(text="📋 " + self.t("copy_log")))
        except Exception:
            pass

    def _handle_retry(self):
        self.close_modal()
        if self.on_retry:
            self.on_retry()

    def _handle_settings(self):
        self.close_modal()
        if self.on_open_settings:
            self.on_open_settings()
