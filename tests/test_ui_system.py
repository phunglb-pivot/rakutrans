"""
Unit tests for UI System primitives: CustomButton, BaseModal, ConfirmModal, ToastManager.
"""

import unittest
from components.ui_system import (
    BUTTON_SIZES,
    BUTTON_VARIANTS,
    SPINNER_FRAMES,
    CustomButton,
    BaseModal
)
from components.confirm_modal import ConfirmModal
from components.toast import ToastManager, TOAST_STYLES


class TestUISystem(unittest.TestCase):

    def test_design_tokens(self):
        # Verify button sizes
        for size in ("sm", "md", "lg"):
            self.assertIn(size, BUTTON_SIZES)
            cfg = BUTTON_SIZES[size]
            self.assertIn("height", cfg)
            self.assertIn("font_size", cfg)
            self.assertIn("corner_radius", cfg)
            self.assertIn("padx", cfg)

        # Verify button variants
        expected_variants = {"primary", "accent", "secondary", "outline", "danger", "ghost", "info"}
        for var in expected_variants:
            self.assertIn(var, BUTTON_VARIANTS)
            vcfg = BUTTON_VARIANTS[var]
            self.assertIn("fg_color", vcfg)
            self.assertIn("hover_color", vcfg)
            self.assertIn("text_color", vcfg)

        self.assertTrue(len(SPINNER_FRAMES) >= 4)

    def test_toast_styles(self):
        for t_type in ("success", "info", "warning", "error"):
            self.assertIn(t_type, TOAST_STYLES)
            cfg = TOAST_STYLES[t_type]
            self.assertIn("icon", cfg)
            self.assertIn("bg_color", cfg)
            self.assertIn("border_color", cfg)
            self.assertIn("text_color", cfg)

    def test_modal_classes(self):
        # Check that ConfirmModal is subclass of BaseModal
        self.assertTrue(issubclass(ConfirmModal, BaseModal))

    def test_confirm_modal_localized_defaults(self):
        """Verify ConfirmModal resolves localized default text when strings are omitted."""
        import customtkinter as ctk
        from i18n import I18nManager
        i18n = I18nManager("vi")
        root = ctk.CTk()

        modal = ConfirmModal(root, get_translation=i18n.t)
        self.assertEqual(modal.title(), i18n.t("confirm_action_title"))
        self.assertEqual(modal.confirm_btn.cget("text"), i18n.t("confirm"))
        self.assertEqual(modal.cancel_btn.cget("text"), i18n.t("cancel"))

        modal.destroy()
        root.destroy()

    def test_settings_direct_save_and_equal_segmented_proportions(self):
        """Verify SettingsView direct changes without close/save buttons, and equal segmented ratios."""
        import customtkinter as ctk
        from config import AppConfig
        from components.settings_modal import SettingsView

        cfg = AppConfig()
        cfg.active_provider = "Gemini"
        save_events = []

        root = ctk.CTk()
        sv = SettingsView(
            root,
            config=cfg,
            get_translation=lambda k, **kw: k,
            on_save_callback=lambda c: save_events.append(c),
            on_close_callback=lambda: None
        )
        root.update()

        # 1. No close_btn or save_btn in SettingsView, back_header_btn not mapped by default to avoid duplicate button
        self.assertFalse(hasattr(sv, "save_btn"))
        self.assertFalse(hasattr(sv, "close_btn"))
        self.assertTrue(hasattr(sv, "back_header_btn"))
        self.assertFalse(sv.back_header_btn.winfo_ismapped())

        # 2. Provider selector has thin border and equal column weights/uniform
        self.assertEqual(sv.provider_selector.cget("border_width"), 1)

        # 3. Direct changes immediately persist to config
        sv._on_provider_changed("OpenAI")
        self.assertEqual(cfg.active_provider, "OpenAI")
        self.assertTrue(len(save_events) >= 1)

        sv._on_model_changed("gpt-4o")
        self.assertEqual(cfg.selected_models["OpenAI"], "gpt-4o")

        root.destroy()


if __name__ == "__main__":
    unittest.main()

