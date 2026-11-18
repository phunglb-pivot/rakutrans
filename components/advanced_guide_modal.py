"""
Visual Diagram & Settings Guide Modal for RakuTrans AI.
Explains how document splitting, rate-limit pacing, Custom API Server URLs,
and local cache work together using visual flowcards and common recipes.
"""

from typing import Callable, Optional
import customtkinter as ctk

from components.icons import get_icon
from components.ui_system import BaseModal, COLORS, CustomButton, UI_LAYOUT


class AdvancedGuideModal(BaseModal):
    """Modal dialog displaying visual workflow diagrams and practical recipes for Advanced Settings."""

    def __init__(
        self,
        parent,
        get_translation: Optional[Callable[..., str]] = None,
    ):
        self.t = get_translation or (lambda k, **kw: k)

        modal_w, modal_h = UI_LAYOUT["advanced_guide_modal_size"]
        super().__init__(
            parent=parent,
            title=self.t("adv_guide_modal_title"),
            width=modal_w,
            height=modal_h,
            resizable=True,
        )

        self._setup_ui()

    def _add_section_title(self, parent, title_key: str) -> None:
        lbl = ctk.CTkLabel(
            parent,
            text=self.t(title_key),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        lbl.pack(fill="x", pady=(10, 6))

    def _add_flow_arrow(self, parent) -> None:
        arrow = ctk.CTkLabel(
            parent,
            text="↓",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color=COLORS["text_muted"],
            anchor="center",
        )
        arrow.pack(fill="x", pady=2)

    def _add_step_card(
        self,
        parent,
        badge_text: str,
        title_key: str,
        body_key: str,
        accent: str = "neutral",
    ) -> ctk.CTkFrame:
        fg = COLORS["info_bg"] if accent == "info" else COLORS["surface_subtle"]
        border = COLORS["info_border"] if accent == "info" else COLORS["border"]
        title_color = COLORS["info_text"] if accent == "info" else COLORS["text_primary"]

        card = ctk.CTkFrame(
            parent,
            fg_color=fg,
            border_width=1,
            border_color=border,
            corner_radius=8,
        )
        card.pack(fill="x", pady=(0, 2))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(8, 2))

        badge = ctk.CTkLabel(
            header,
            text=badge_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("#E4E4E7", "#27272A") if accent == "neutral" else ("#DBEAFE", "#1E3A8A"),
            text_color=title_color,
            corner_radius=4,
            padx=6,
            pady=2,
        )
        badge.pack(side="left", padx=(0, 8))

        title = ctk.CTkLabel(
            header,
            text=self.t(title_key),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=title_color,
            anchor="w",
        )
        title.pack(side="left", fill="x", expand=True)

        body = ctk.CTkLabel(
            card,
            text=self.t(body_key),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_body"] if accent == "neutral" else COLORS["info_text"],
            wraplength=580,
            justify="left",
            anchor="w",
        )
        body.pack(fill="x", padx=12, pady=(0, 9))
        return card

    def _add_split_branch_card(self, parent) -> None:
        """Step 1 diagram showing how Office/Table vs Markdown/TXT documents split."""
        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["surface_subtle"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        card.pack(fill="x", pady=(0, 2))

        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=12, pady=(8, 6))

        badge = ctk.CTkLabel(
            header,
            text="1",
            font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=("#E4E4E7", "#27272A"),
            text_color=COLORS["text_primary"],
            corner_radius=4,
            padx=6,
            pady=2,
        )
        badge.pack(side="left", padx=(0, 8))

        title = ctk.CTkLabel(
            header,
            text=self.t("adv_guide_step1_title"),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        )
        title.pack(side="left", fill="x", expand=True)

        branches = ctk.CTkFrame(card, fg_color="transparent")
        branches.pack(fill="x", padx=12, pady=(0, 10))
        branches.grid_columnconfigure(0, weight=1, uniform="guide_split")
        branches.grid_columnconfigure(1, weight=1, uniform="guide_split")

        branch_specs = (
            (0, "adv_guide_branch_table_title", "adv_guide_branch_table_body", (0, 6)),
            (1, "adv_guide_branch_text_title", "adv_guide_branch_text_body", (6, 0)),
        )
        for col, t_key, b_key, padx in branch_specs:
            box = ctk.CTkFrame(
                branches,
                fg_color=("#FFFFFF", "#09090B"),
                border_width=1,
                border_color=COLORS["border_strong"],
                corner_radius=6,
            )
            box.grid(row=0, column=col, sticky="nsew", padx=padx)

            ctk.CTkLabel(
                box,
                text=self.t(t_key),
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=COLORS["text_primary"],
                anchor="w",
            ).pack(fill="x", padx=10, pady=(7, 2))

            ctk.CTkLabel(
                box,
                text=self.t(b_key),
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_secondary"],
                wraplength=260,
                justify="left",
                anchor="w",
            ).pack(fill="x", padx=10, pady=(0, 8))

    def _add_recipe_card(self, parent, title_key: str, body_key: str) -> None:
        card = ctk.CTkFrame(
            parent,
            fg_color=COLORS["surface_subtle"],
            border_width=1,
            border_color=COLORS["border"],
            corner_radius=8,
        )
        card.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            card,
            text=self.t(title_key),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_primary"],
            anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 2))

        ctk.CTkLabel(
            card,
            text=self.t(body_key),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_body"],
            wraplength=580,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 8))

    def _setup_ui(self) -> None:
        outer = ctk.CTkFrame(self, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=18, pady=(16, 14))

        # Header
        header_row = ctk.CTkFrame(outer, fg_color="transparent")
        header_row.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(
            header_row,
            text="",
            image=get_icon("info", "info_accent", 24),
        ).pack(side="left", padx=(0, 10))

        title_col = ctk.CTkFrame(header_row, fg_color="transparent")
        title_col.pack(side="left", fill="x", expand=True)

        ctk.CTkLabel(
            title_col,
            text=self.t("adv_guide_heading"),
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            title_col,
            text=self.t("adv_guide_subheading"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_secondary"],
            anchor="w",
        ).pack(fill="x", pady=(1, 0))

        # Scrollable diagram & guide body
        scroll = ctk.CTkScrollableFrame(outer, fg_color="transparent", corner_radius=0)
        scroll.pack(fill="both", expand=True, pady=(4, 10))

        # Section 1: End-to-End Translation Pipeline Diagram
        self._add_section_title(scroll, "adv_guide_pipeline_title")
        self._add_split_branch_card(scroll)
        self._add_flow_arrow(scroll)
        self._add_step_card(scroll, "2", "adv_guide_step2_title", "adv_guide_step2_body")
        self._add_flow_arrow(scroll)
        self._add_step_card(scroll, "3", "adv_guide_step3_title", "adv_guide_step3_body", accent="info")
        self._add_flow_arrow(scroll)
        self._add_step_card(scroll, "4", "adv_guide_step4_title", "adv_guide_step4_body")

        # Section 2: Custom API Server URL Priority Diagram
        self._add_section_title(scroll, "adv_guide_url_title")
        self._add_step_card(scroll, "1 → 2 → 3", "adv_guide_url_flow_title", "adv_guide_url_flow_body", accent="info")

        # Section 3: Practical Recipes
        self._add_section_title(scroll, "adv_guide_recipes_title")
        self._add_recipe_card(scroll, "adv_guide_recipe1_title", "adv_guide_recipe1_body")
        self._add_recipe_card(scroll, "adv_guide_recipe2_title", "adv_guide_recipe2_body")
        self._add_recipe_card(scroll, "adv_guide_recipe3_title", "adv_guide_recipe3_body")

        # Footer button
        btn_row = ctk.CTkFrame(outer, fg_color="transparent")
        btn_row.pack(fill="x")

        self.close_btn = CustomButton(
            btn_row,
            text=self.t("close"),
            variant="primary",
            size="md",
            width=110,
            command=self.close_modal,
        )
        self.close_btn.pack(side="right")
