"""
Unit tests for Button Lifecycle & State Management and Design Tokens in RakuTrans AI.
Verifies proper show/hide/disable transitions and minimalist palette consistency across Light and Dark modes.
"""

import unittest
import customtkinter as ctk

from components.ui_system import (
    BUTTON_SIZES,
    BUTTON_VARIANTS
)
from ui import RakuTransApp


class TestUIButtonLifecycle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Initialize app headless without showing window
        ctk.set_appearance_mode("Dark")
        cls.app = RakuTransApp()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass

    def test_design_token_sizes_and_proportions(self):
        """Verify button height follows 8px grid (lg=40px, md=34px, sm=28px)."""
        self.assertEqual(BUTTON_SIZES["lg"]["height"], 40)
        self.assertEqual(BUTTON_SIZES["md"]["height"], 34)
        self.assertEqual(BUTTON_SIZES["sm"]["height"], 28)
        self.assertEqual(BUTTON_SIZES["lg"]["corner_radius"], 8)

    def test_design_token_unified_palette(self):
        """Verify unified minimalist monochrome palette."""
        primary = BUTTON_VARIANTS["primary"]
        self.assertEqual(primary["fg_color"], ("#18181B", "#FAFAFA"))
        self.assertEqual(primary["hover_color"], ("#27272A", "#E4E4E7"))

        secondary = BUTTON_VARIANTS["secondary"]
        self.assertEqual(secondary["fg_color"], ("#E4E4E7", "#27272A"))

        outline = BUTTON_VARIANTS["outline"]
        self.assertEqual(outline["border_color"], ("#D4D4D8", "#3F3F46"))

        danger = BUTTON_VARIANTS["danger"]
        self.assertEqual(danger["fg_color"], ("#DC2626", "#DC2626"))

    def test_state_idle_no_file(self):
        """When no file is selected, action button is disabled and result buttons are hidden."""
        self.app.selected_file = None
        self.app.current_mode = "translate"
        self.app._update_button_states("idle_no_file")

        # Translate button should be packed and disabled
        self.assertEqual(self.app.translate_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.translate_btn.cget("state"), "disabled")

        # Result and cancel buttons should NOT be packed
        self.assertEqual(self.app.cancel_btn.winfo_manager(), "")
        self.assertEqual(self.app.open_file_btn.winfo_manager(), "")
        self.assertEqual(self.app.open_folder_btn.winfo_manager(), "")
        self.assertEqual(self.app.save_as_btn.winfo_manager(), "")
        self.assertEqual(self.app.error_btn.winfo_manager(), "")

    def test_state_file_ready(self):
        """When a valid file is selected, action button is enabled and prominent."""
        self.app.selected_file = "/fake/sample.docx"
        self.app.current_mode = "translate"
        self.app._update_button_states("file_ready")

        self.assertEqual(self.app.translate_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.translate_btn.cget("state"), "normal")
        self.assertEqual(self.app.translate_btn.variant, "primary")

        # Result buttons must remain hidden
        self.assertEqual(self.app.cancel_btn.winfo_manager(), "")
        self.assertEqual(self.app.open_file_btn.winfo_manager(), "")
        self.assertEqual(self.app.open_folder_btn.winfo_manager(), "")
        self.assertEqual(self.app.save_as_btn.winfo_manager(), "")
        self.assertEqual(self.app.error_btn.winfo_manager(), "")

    def test_state_processing(self):
        """While translating, action button is loading/disabled and cancel button is shown."""
        self.app.current_mode = "translate"
        self.app._update_button_states("processing")

        self.assertEqual(self.app.translate_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.translate_btn.cget("state"), "disabled")
        self.assertEqual(self.app.cancel_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.cancel_btn.cget("state"), "normal")

        # Results still hidden
        self.assertEqual(self.app.open_file_btn.winfo_manager(), "")
        self.assertEqual(self.app.open_folder_btn.winfo_manager(), "")

    def test_state_completed(self):
        """On success, open_file is hero primary, folder/save are outline, re-run is secondary."""
        self.app.current_mode = "translate"
        self.app._update_button_states("completed")

        # Hero button
        self.assertEqual(self.app.open_file_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.open_file_btn.variant, "primary")

        # Companion buttons
        self.assertEqual(self.app.open_folder_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.open_folder_btn.variant, "outline")
        self.assertEqual(self.app.save_as_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.save_as_btn.variant, "outline")

        # Re-run button
        self.assertEqual(self.app.translate_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.translate_btn.variant, "secondary")
        self.assertEqual(self.app.translate_btn.cget("state"), "normal")

        # Cancel & error hidden
        self.assertEqual(self.app.cancel_btn.winfo_manager(), "")
        self.assertEqual(self.app.error_btn.winfo_manager(), "")

    def test_state_error(self):
        """On failure, retry button is primary and error details button is shown."""
        self.app.current_mode = "translate"
        self.app._update_button_states("error")

        self.assertEqual(self.app.translate_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.translate_btn.cget("state"), "normal")
        self.assertEqual(self.app.error_btn.winfo_manager(), "pack")

        # Results and cancel hidden
        self.assertEqual(self.app.open_file_btn.winfo_manager(), "")
        self.assertEqual(self.app.cancel_btn.winfo_manager(), "")

    def test_convert_mode_lifecycle(self):
        """Verify lifecycle in Format Converter mode."""
        self.app._on_mode_switched(self.app.tab_convert_label)
        self.assertEqual(self.app.current_mode, "convert")
        self.assertEqual(self.app.provider_badge.winfo_manager(), "")

        self.app.selected_convert_file = None
        self.app._update_button_states("idle_no_file")

        # Convert button is visible and disabled, translate button hidden
        self.assertEqual(self.app.convert_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.convert_btn.cget("state"), "disabled")
        self.assertEqual(self.app.translate_btn.winfo_manager(), "")

        # Ready state with file and target format
        self.app.selected_convert_file = "/fake/test.pdf"
        self.app.selected_target_format = "docx"
        self.app._update_button_states("file_ready")
        self.assertEqual(self.app.convert_btn.cget("state"), "normal")

        # Completed state
        self.app._update_button_states("completed")
        self.assertEqual(self.app.open_file_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.convert_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.convert_btn.variant, "secondary")

        # Switch back to translate mode restores provider badge
        self.app._on_mode_switched(self.app.tab_translate_label)
        self.assertEqual(self.app.current_mode, "translate")
        self.assertEqual(self.app.provider_badge.winfo_manager(), "pack")

    def test_clear_cache_button_state(self):
        """Verify cache button disabled when empty, enabled when populated."""
        self.app.cache.clear()
        self.app._refresh_cache_display()
        self.assertEqual(self.app.clear_cache_btn.cget("state"), "disabled")

        self.app.cache.set("hello", "xin chào", "English", "Vietnamese")
        self.app._refresh_cache_display()
        self.assertEqual(self.app.clear_cache_btn.cget("state"), "normal")

        # Cleanup
        self.app.cache.clear()

    def test_language_switch_updates_all_texts_and_preserves_state(self):
        """Verify changing UI language updates all on-screen texts, fixes double icons, and preserves states."""
        # 1. Switch to Vietnamese
        self.app.config.ui_language = "vi"
        self.app._on_settings_changed(self.app.config)

        self.assertEqual(self.app.i18n.current_lang, "vi")
        self.assertEqual(self.app.shortcut_hint_label.cget("text"), self.app.i18n.t("shortcut_hint"))
        self.assertIn("Phím tắt", self.app.shortcut_hint_label.cget("text"))
        self.assertEqual(self.app.status_label.cget("text"), self.app.i18n.t("status_ready"))
        self.assertEqual(self.app.subtitle_label.cget("text"), self.app.i18n.t("app_subtitle"))
        self.assertEqual(self.app.tgt_label.cget("text"), self.app.i18n.t("target_lang"))
        self.assertEqual(self.app.save_as_btn.cget("text"), self.app.i18n.t("save_as"))
        self.assertFalse(self.app.save_as_btn.cget("text").startswith("💾 💾"))
        self.assertEqual(self.app.error_btn.cget("text"), self.app.i18n.t("view_error_details"))
        self.assertFalse(self.app.error_btn.cget("text").startswith("⚠️ ⚠️"))
        self.assertEqual(self.app.translate_btn.cget("text"), self.app.i18n.t("start_translation"))
        self.assertEqual(self.app.convert_btn.cget("text"), "🔄 " + self.app.i18n.t("convert_button"))
        self.assertEqual(self.app.settings_view.key_entry.cget("placeholder_text"), self.app.i18n.t("api_key_placeholder"))
        self.assertEqual(self.app.settings_view.lang_var.get(), "Tiếng Việt")

        # 2. Completed state preservation
        self.app.selected_file = "/fake/sample.docx"
        self.app.last_output_file = "/fake/sample_vi.docx"
        self.app.current_mode = "translate"
        self.app._update_button_states("completed")
        self.assertEqual(self.app.current_button_state, "completed")

        # Switch to Japanese while completed
        self.app.config.ui_language = "ja"
        self.app._on_settings_changed(self.app.config)

        self.assertEqual(self.app.current_button_state, "completed")
        self.assertEqual(self.app.open_file_btn.winfo_manager(), "pack")
        self.assertEqual(self.app.open_file_btn.cget("text"), "📄 " + self.app.i18n.t("open_file"))
        self.assertEqual(self.app.translate_btn.cget("text"), "↻ " + self.app.i18n.t("translate_again"))
        self.assertEqual(
            self.app.status_label.cget("text"),
            self.app.i18n.t("status_completed", filename="sample_vi.docx")
        )

        # 3. Error state & re-diagnosis preservation
        self.app._on_translation_failed("429 Rate limit quota exceeded", Exception("429 resource exhausted"))
        self.assertEqual(self.app.current_button_state, "error")

        # Switch back to English while in error state
        self.app.config.ui_language = "en"
        self.app._on_settings_changed(self.app.config)

        self.assertEqual(self.app.current_button_state, "error")
        self.assertEqual(self.app.last_diagnostic.title, self.app.i18n.t("err_diag_quota_title"))
        self.assertIn("API Rate Limit", self.app.last_diagnostic.title)
        self.assertEqual(
            self.app.status_label.cget("text"),
            f"{self.app.last_diagnostic.title}: {self.app.last_diagnostic.message}"
        )

        # 4. Processing state updates
        self.app._update_button_states("processing")
        self.assertIn(self.app.i18n.t("translating"), self.app.translate_btn.cget("text"))
        self.app.config.ui_language = "vi"
        self.app._on_settings_changed(self.app.config)
        self.assertIn(self.app.i18n.t("translating"), self.app.translate_btn.cget("text"))
        self.app.translate_btn.stop_loading()

        # Cleanup
        self.app.last_exception = None
        self.app.last_diagnostic = None
        self.app.selected_file = None
        self.app._update_button_states("idle_no_file")
        self.app._refresh_status_text()


if __name__ == "__main__":
    unittest.main()
