"""
Confirm Modal dialog for RakuTrans AI.
Presents a clear, focused confirmation prompt for destructive or irreversible actions.
"""

from typing import Callable, Optional
import customtkinter as ctk

from components.ui_system import BaseModal, CustomButton


class ConfirmModal(BaseModal):
    """
    Standard confirmation dialog with warning icon, description, and explicit action buttons.
    """

    def __init__(
        self,
        parent,
        title: Optional[str] = None,
        message: Optional[str] = None,
        description: str = "",
        confirm_text: Optional[str] = None,
        cancel_text: Optional[str] = None,
        on_confirm: Optional[Callable[[], None]] = None,
        on_cancel: Optional[Callable[[], None]] = None,
        variant: str = "danger",
        icon: str = "⚠️",
        get_translation: Optional[Callable[[str], str]] = None
    ):
        self._confirmed = False
        self._user_confirm_cb = on_confirm
        self._user_cancel_cb = on_cancel
        self.t = get_translation or (lambda k, **kw: k)

        resolved_title = title or self.t("confirm_action_title")
        resolved_msg = message or self.t("confirm_action_msg")
        resolved_confirm = confirm_text or self.t("confirm")
        resolved_cancel = cancel_text or self.t("cancel")

        super().__init__(
            parent=parent,
            title=resolved_title,
            width=460,
            height=240,
            resizable=False,
            on_close=self._handle_cancel,
            on_confirm=self._handle_confirm
        )

        self._setup_content(icon, resolved_msg, description, resolved_confirm, resolved_cancel, variant)

    def _setup_content(
        self,
        icon: str,
        message: str,
        description: str,
        confirm_text: str,
        cancel_text: str,
        variant: str
    ):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=24, pady=20)
        container.grid_columnconfigure(1, weight=1)

        # Header row: Icon & Message
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))

        icon_label = ctk.CTkLabel(
            header_frame,
            text=icon,
            font=ctk.CTkFont(size=32)
        )
        icon_label.pack(side="left", padx=(0, 14), anchor="n")

        text_frame = ctk.CTkFrame(header_frame, fg_color="transparent")
        text_frame.pack(side="left", fill="x", expand=True)

        title_label = ctk.CTkLabel(
            text_frame,
            text=message,
            font=ctk.CTkFont(size=14, weight="bold"),
            anchor="w",
            justify="left",
            wraplength=340
        )
        title_label.pack(fill="x")

        if description:
            desc_label = ctk.CTkLabel(
                text_frame,
                text=description,
                font=ctk.CTkFont(size=12),
                text_color=("gray40", "gray60"),
                anchor="w",
                justify="left",
                wraplength=340
            )
            desc_label.pack(fill="x", pady=(4, 0))

        # Bottom Buttons
        btn_frame = ctk.CTkFrame(container, fg_color="transparent")
        btn_frame.pack(fill="x", side="bottom", pady=(14, 0))

        self.confirm_btn = CustomButton(
            btn_frame,
            text=confirm_text,
            variant=variant,
            size="md",
            command=self._handle_confirm
        )
        self.confirm_btn.pack(side="right", padx=(8, 0))

        self.cancel_btn = CustomButton(
            btn_frame,
            text=cancel_text,
            variant="outline",
            size="md",
            command=self.close_modal
        )
        self.cancel_btn.pack(side="right")
        self.cancel_btn.focus_set()

    def _handle_confirm(self):
        self._confirmed = True
        self.close_modal()
        if self._user_confirm_cb:
            self._user_confirm_cb()

    def _handle_cancel(self):
        if not self._confirmed and self._user_cancel_cb:
            self._user_cancel_cb()

