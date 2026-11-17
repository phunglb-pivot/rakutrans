"""
Software Update Modal for RakuTrans AI.
Displays available release details, OS-specific upgrade tips, and direct download actions.
"""

import platform
import webbrowser
from typing import Callable, Optional
import customtkinter as ctk

from components.icons import get_icon
from components.ui_system import BaseModal, COLORS, CustomButton, UI_LAYOUT
from update_checker import UpdateInfo


class UpdateModal(BaseModal):
    """
    Clean modal dialog presenting an available application update and download links.
    """

    def __init__(
        self,
        parent,
        update_info: UpdateInfo,
        on_skip_version: Optional[Callable[[str], None]] = None,
        get_translation: Optional[Callable[..., str]] = None,
    ):
        self.update_info = update_info
        self.on_skip_version = on_skip_version
        self.t = get_translation or (lambda k, **kw: k)

        modal_w, modal_h = UI_LAYOUT["update_modal_size"]
        super().__init__(
            parent=parent,
            title=self.t("update_modal_title"),
            width=modal_w,
            height=modal_h,
            resizable=False,
            on_confirm=self._open_download,
        )

        self._setup_ui()

    def _get_install_tip_key(self) -> str:
        sys_name = platform.system()
        if sys_name == "Windows":
            return "update_install_tip_windows"
        if sys_name == "Darwin":
            return "update_install_tip_macos"
        return "update_install_tip_other"

    def _setup_ui(self):
        container = ctk.CTkFrame(self, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=22, pady=20)

        # 1. Header row
        header_frame = ctk.CTkFrame(container, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 12))

        icon_label = ctk.CTkLabel(
            header_frame,
            text="",
            image=get_icon("download", "info_accent", 32),
        )
        icon_label.pack(side="left", padx=(0, 12))

        title_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_box.pack(side="left", fill="x", expand=True)

        self.heading_label = ctk.CTkLabel(
            title_box,
            text=self.t("update_modal_heading", latest=self.update_info.latest_version),
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        )
        self.heading_label.pack(fill="x")

        self.versions_label = ctk.CTkLabel(
            title_box,
            text=self.t(
                "update_modal_versions",
                current=self.update_info.current_version,
                latest=self.update_info.latest_version,
            ),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_secondary"],
            anchor="w",
        )
        self.versions_label.pack(fill="x", pady=(2, 0))

        # 2. OS-specific upgrade reassurance tip
        tip_box = ctk.CTkFrame(
            container,
            fg_color=COLORS["info_bg"],
            border_width=1,
            border_color=COLORS["info_border"],
            corner_radius=8,
        )
        tip_box.pack(fill="x", pady=(0, 12))

        tip_inner = ctk.CTkFrame(tip_box, fg_color="transparent")
        tip_inner.pack(fill="x", padx=12, pady=10)

        tip_icon = ctk.CTkLabel(
            tip_inner,
            text="",
            image=get_icon("info", "info_accent", 16),
        )
        tip_icon.pack(side="left", padx=(0, 8), anchor="n")

        self.tip_label = ctk.CTkLabel(
            tip_inner,
            text=self.t(self._get_install_tip_key()),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["info_text"],
            wraplength=460,
            justify="left",
            anchor="w",
        )
        self.tip_label.pack(side="left", fill="x", expand=True)

        # 3. Release notes
        notes_label = ctk.CTkLabel(
            container,
            text=self.t("update_release_notes_label"),
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
        )
        notes_label.pack(fill="x", pady=(0, 4))

        notes_text = (self.update_info.release_notes or "").strip()
        if not notes_text:
            notes_text = self.t("update_no_release_notes")

        self.notes_box = ctk.CTkTextbox(
            container,
            font=ctk.CTkFont(size=12),
            fg_color=COLORS["surface_subtle"],
            border_width=1,
            border_color=COLORS["border"],
            text_color=COLORS["text_primary"],
            wrap="word",
        )
        self.notes_box.pack(fill="both", expand=True, pady=(0, 14))
        self.notes_box.insert("1.0", notes_text)
        self.notes_box.configure(state="disabled")

        # 4. Action buttons
        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x")

        self.skip_btn = CustomButton(
            btn_row,
            text=self.t("skip_version_btn"),
            variant="ghost",
            size="md",
            command=self._handle_skip,
        )
        self.skip_btn.pack(side="left")

        self.download_btn = CustomButton(
            btn_row,
            text=self.t("download_update_btn"),
            variant="primary",
            size="md",
            icon_name="download",
            icon_size=15,
            command=self._open_download,
        )
        self.download_btn.pack(side="right", padx=(8, 0))

        if (
            self.update_info.release_url
            and self.update_info.download_url
            and self.update_info.download_url != self.update_info.release_url
        ):
            self.release_page_btn = CustomButton(
                btn_row,
                text=self.t("open_releases_page_btn"),
                variant="outline",
                size="md",
                command=self._open_release_page,
            )
            self.release_page_btn.pack(side="right", padx=(8, 0))

        self.later_btn = CustomButton(
            btn_row,
            text=self.t("later_btn"),
            variant="outline",
            size="md",
            command=self.close_modal,
        )
        self.later_btn.pack(side="right")

    def _open_download(self):
        target_url = self.update_info.download_url or self.update_info.release_url
        if target_url:
            webbrowser.open_new_tab(target_url)
        self.close_modal()

    def _open_release_page(self):
        if self.update_info.release_url:
            webbrowser.open_new_tab(self.update_info.release_url)

    def _handle_skip(self):
        if self.on_skip_version:
            self.on_skip_version(self.update_info.latest_version)
        self.close_modal()
