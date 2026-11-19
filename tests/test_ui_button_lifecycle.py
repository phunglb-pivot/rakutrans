"""
Unit tests for Button Lifecycle & State Management and Design Tokens in RakuTrans AI.
Verifies proper show/hide/disable transitions and minimalist palette consistency across Light and Dark modes.
"""

import unittest

try:
    import tkinter
    import customtkinter as ctk
    HAS_TKINTER = True
    from rakutrans.ui.components.ui_system import (
        BUTTON_SIZES,
        BUTTON_VARIANTS
    )
    from rakutrans.ui.app import RakuTransApp
except (ImportError, ModuleNotFoundError):
    HAS_TKINTER = False


@unittest.skipUnless(HAS_TKINTER, "Tkinter is not available in this Python environment")
class TestUIButtonLifecycle(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from rakutrans.core import config as config_mod
        from rakutrans.llm import model_fetcher
        from rakutrans.llm import translation_cache
        cls._tmp_dir = tempfile.TemporaryDirectory()
        tmp_path = Path(cls._tmp_dir.name)
        cls._patches = [
            patch.object(config_mod, "CONFIG_DIR", tmp_path),
            patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"),
            patch.object(model_fetcher, "CACHE_DIR", tmp_path),
            patch.object(model_fetcher, "MODELS_CACHE_FILE", tmp_path / "models_cache.json"),
            patch.object(translation_cache, "CACHE_DB_PATH", tmp_path / "cache.db"),
        ]
        for p in cls._patches:
            p.start()

        # Initialize app headless without showing window using isolated temp config/cache
        ctk.set_appearance_mode("Dark")
        cls.app = RakuTransApp()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        for p in reversed(getattr(cls, "_patches", [])):
            try:
                p.stop()
            except Exception:
                pass
        if hasattr(cls, "_tmp_dir"):
            cls._tmp_dir.cleanup()

    def test_windows_taskbar_icon_guard(self):
        """On Windows, RakuTransApp must set iconbitmap so CustomTkinter doesn't overwrite it."""
        import platform
        if platform.system() == "Windows":
            self.assertTrue(getattr(self.app, "_iconbitmap_method_called", False))

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

        # Switch back to translate mode restores provider badge with logo icon
        self.app._on_mode_switched(self.app.tab_translate_label)
        self.assertEqual(self.app.current_mode, "translate")
        self.assertEqual(self.app.provider_badge.winfo_manager(), "pack")
        self.assertIsNotNone(self.app.provider_badge.cget("image"))

    def test_shortcut_hint_matches_os_and_mode(self):
        """Verify shortcut hint displays only OS-specific modifier and active mode actions."""
        from unittest.mock import patch

        self.app.config.ui_language = "en"
        self.app._on_settings_changed(self.app.config)

        with patch("rakutrans.ui.app.platform.system", return_value="Darwin"):
            self.app._on_mode_switched(self.app.tab_translate_label)
            mac_tr = self.app.shortcut_hint_label.cget("text")
            self.assertIn("⌘+O", mac_tr)
            self.assertIn("Translate", mac_tr)
            self.assertNotIn("Ctrl", mac_tr)
            self.assertNotIn("Convert", mac_tr)

            self.app._on_mode_switched(self.app.tab_convert_label)
            mac_cv = self.app.shortcut_hint_label.cget("text")
            self.assertIn("⌘+O", mac_cv)
            self.assertIn("Convert", mac_cv)
            self.assertNotIn("Ctrl", mac_cv)
            self.assertNotIn("Translate", mac_cv)

        with patch("rakutrans.ui.app.platform.system", return_value="Windows"):
            self.app._on_mode_switched(self.app.tab_translate_label)
            win_tr = self.app.shortcut_hint_label.cget("text")
            self.assertIn("Ctrl+O", win_tr)
            self.assertIn("Translate", win_tr)
            self.assertNotIn("⌘", win_tr)

            self.app._on_mode_switched(self.app.tab_convert_label)
            win_cv = self.app.shortcut_hint_label.cget("text")
            self.assertIn("Ctrl+O", win_cv)
            self.assertIn("Convert", win_cv)
            self.assertNotIn("⌘", win_cv)

        # Restore translate mode
        self.app._on_mode_switched(self.app.tab_translate_label)

    def test_clear_cache_button_state(self):
        """Verify cache button disabled when empty, enabled when populated."""
        self.app.cache.clear()
        self.app._refresh_cache_display()
        self.assertEqual(self.app.clear_cache_btn.cget("state"), "disabled")

        self.app.cache.save_batch(
            ["hello"], ["xin chào"], target_lang="Vietnamese", source_lang="English"
        )
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
        self.assertEqual(self.app.shortcut_hint_label.cget("text"), self.app._get_shortcut_hint_text())
        self.assertIn("Phím tắt", self.app.shortcut_hint_label.cget("text"))
        self.assertNotIn("⌘/Ctrl", self.app.shortcut_hint_label.cget("text"))
        self.assertEqual(self.app.status_label.cget("text"), self.app.i18n.t("status_ready"))
        self.assertEqual(self.app.subtitle_label.cget("text"), self.app.i18n.t("app_subtitle"))
        self.assertEqual(self.app.tgt_label.cget("text"), self.app.i18n.t("target_lang"))
        self.assertEqual(self.app.save_as_btn.cget("text"), self.app.i18n.t("save_as"))
        self.assertFalse(self.app.save_as_btn.cget("text").startswith("💾 💾"))
        self.assertEqual(self.app.error_btn.cget("text"), self.app.i18n.t("view_error_details"))
        self.assertFalse(self.app.error_btn.cget("text").startswith("⚠️ ⚠️"))
        self.assertEqual(self.app.translate_btn.cget("text"), self.app.i18n.t("start_translation"))
        self.assertEqual(self.app.convert_btn.cget("text"), self.app.i18n.t("convert_button"))
        self.assertIsNotNone(self.app.convert_btn.cget("image"))
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
        self.assertEqual(self.app.open_file_btn.cget("text"), self.app.i18n.t("open_file"))
        self.assertIsNotNone(self.app.open_file_btn.cget("image"))
        self.assertEqual(self.app.translate_btn.cget("text"), self.app.i18n.t("translate_again"))
        self.assertIsNotNone(self.app.translate_btn.cget("image"))
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

    def test_convert_dropzone_filters_unsupported_and_diagnoses_errors(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            json_file = Path(tmpdir) / "locale.json"
            json_file.write_text('{"a": "b"}', encoding="utf-8")
            csv_file = Path(tmpdir) / "table.csv"
            csv_file.write_text("A,B\n1,2\n", encoding="utf-8")

            # Convert DropZone must ignore .json (not in _CONVERSION_REGISTRY)
            self.app.convert_drop_zone.clear()
            self.app.convert_drop_zone.set_file(str(json_file))
            self.assertIsNone(self.app.convert_drop_zone.selected_file)

            # Convert DropZone accepts .csv
            self.app.convert_drop_zone.set_file(str(csv_file))
            self.assertEqual(self.app.convert_drop_zone.selected_file, str(csv_file.resolve()))
            self.app.convert_drop_zone.clear()

        # Conversion failures should create DiagnosticInfo for ErrorModal
        self.app._on_mode_switched(self.app.tab_convert_label)
        self.app._on_conversion_failed("Permission denied", PermissionError("[Errno 13] Permission denied"))
        self.assertEqual(self.app.current_button_state, "error")
        self.assertIsNotNone(self.app.last_diagnostic)
        self.assertEqual(self.app.last_diagnostic.category, "file_lock")

        # Cleanup back to translate mode
        self.app.last_exception = None
        self.app.last_diagnostic = None
        self.app.last_convert_error = None
        self.app._on_mode_switched(self.app.tab_translate_label)
        self.app._update_button_states("idle_no_file")
        self.app._refresh_status_text()

    def test_mode_switch_preserves_completed_and_error_states(self):
        self.app.selected_file = "/fake/doc.docx"
        self.app.last_output_file = "/fake/doc_vi.docx"
        self.app._on_mode_switched(self.app.tab_translate_label)
        self.app._update_button_states("completed")

        # Switch to convert -> idle_no_file
        self.app.selected_convert_file = None
        self.app._on_mode_switched(self.app.tab_convert_label)
        self.assertEqual(self.app.current_button_state, "idle_no_file")

        # Switch back -> translate completed state preserved
        self.app._on_mode_switched(self.app.tab_translate_label)
        self.assertEqual(self.app.current_button_state, "completed")
        self.assertEqual(self.app.open_file_btn.winfo_manager(), "pack")

        # Cleanup
        self.app.selected_file = None
        self.app.last_output_file = None
        self.app._update_button_states("idle_no_file")
        self.app._refresh_status_text()

    def test_shortcuts_locked_while_processing_and_convert_grid_reset(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_file = Path(tmpdir) / "a.pdf"
            pdf_file.write_bytes(b"%PDF-1.4")
            csv_file = Path(tmpdir) / "b.csv"
            csv_file.write_text("A,B\n1,2\n", encoding="utf-8")

            self.app._on_mode_switched(self.app.tab_convert_label)
            self.app._on_convert_file_selected(str(pdf_file))
            self.app._on_convert_file_selected(str(csv_file))

            from rakutrans.parsers.format_converter import get_convert_options
            csv_opts_count = len(get_convert_options(".csv"))
            col_cfg = self.app.target_segmented.grid_columnconfigure(csv_opts_count)
            self.assertEqual(col_cfg["weight"], 0)
            self.assertIn(col_cfg["uniform"], (None, ""))

        # Verify real Tk shortcut bindings are registered for both macOS and Windows/Linux
        self.assertIn("_on_shortcut_open", self.app.bind("<Command-o>"))
        self.assertIn("_on_shortcut_open", self.app.bind("<Control-o>"))
        self.assertIn("_on_shortcut_action", self.app.bind("<Command-Return>"))
        self.assertIn("_on_shortcut_action", self.app.bind("<Control-Return>"))

        # Shortcuts blocked while processing or in settings (avoid focus_force/event_generate which deadlock on headless macOS CI)
        with patch.object(self.app, "_start_translation") as mock_start, \
             patch.object(self.app, "_start_conversion") as mock_convert, \
             patch.object(self.app.drop_zone, "_browse_file") as mock_browse, \
             patch.object(self.app.convert_drop_zone, "_browse_file") as mock_convert_browse:
            self.app.is_translating = True
            self.assertEqual(self.app._on_shortcut_open(), "break")
            self.assertEqual(self.app._on_shortcut_action(), "break")
            self.app.is_translating = False

            prev_screen = self.app.current_screen
            self.app.current_screen = "settings"
            self.assertEqual(self.app._on_shortcut_open(), "break")
            self.assertEqual(self.app._on_shortcut_action(), "break")
            self.app.current_screen = prev_screen

            mock_start.assert_not_called()
            mock_convert.assert_not_called()
            mock_browse.assert_not_called()
            mock_convert_browse.assert_not_called()

        # Cleanup
        self.app.selected_convert_file = None
        self.app.selected_target_format = None
        self.app._on_mode_switched(self.app.tab_translate_label)
        self.app._update_button_states("idle_no_file")
        self.app._refresh_status_text()

    def test_update_banner_lifecycle_and_skip_version(self):
        """Verify update banner shows for new unskipped versions, localizes, and hides when dismissed/skipped."""
        from rakutrans.core.update_checker import UpdateCheckResult, UpdateInfo

        info = UpdateInfo(
            current_version="1.0.0",
            latest_version="1.5.0",
            has_update=True,
            release_url="https://github.com/phunglb-pivot/rakutrans/releases/tag/v1.5.0",
            download_url="https://github.com/phunglb-pivot/rakutrans/releases/download/v1.5.0/RakuTrans-Installer-macOS.dmg",
        )

        # Skipped version must NOT display banner on startup check
        self.app.config.skipped_update_version = "1.5.0"
        self.app._update_banner_dismissed = False
        self.app._handle_startup_update_result(UpdateCheckResult(status="update_available", info=info))
        self.assertEqual(self.app.update_banner.winfo_manager(), "")

        # Unskipped version displays banner and refreshes text on language change
        self.app.config.skipped_update_version = ""
        self.app._handle_startup_update_result(UpdateCheckResult(status="update_available", info=info))
        self.assertEqual(self.app.update_banner.winfo_manager(), "pack")
        self.assertIn("1.5.0", self.app.update_banner_label.cget("text"))

        self.app.config.ui_language = "vi"
        self.app._on_settings_changed(self.app.config)
        self.assertIn("1.5.0", self.app.update_banner_label.cget("text"))
        self.assertEqual(self.app.update_banner_btn.cget("text"), self.app.i18n.t("update_details_btn"))

        # Skipping version persists and dismisses banner
        self.app._on_skip_update_version("1.5.0")
        self.assertEqual(self.app.config.skipped_update_version, "1.5.0")
        self.assertEqual(self.app.update_banner.winfo_manager(), "")

        # Cleanup
        self.app.config.skipped_update_version = ""
        self.app.config.ui_language = "en"
        self.app._available_update_info = None
        self.app._update_banner_dismissed = False
        self.app._on_settings_changed(self.app.config)

    def test_dark_mode_translate_convert_active_and_disabled_clarity(self):
        """In Dark mode, active mode tab and enabled/disabled translate & convert action buttons have unambiguous contrast."""
        from rakutrans.ui.components.ui_system import BUTTON_DISABLED_STYLES, SEGMENTED_BUTTON_TOKENS

        ctk.set_appearance_mode("Dark")

        # 1. Mode segmented tabs: Translate active vs Convert inactive
        self.app.mode_segmented.set(self.app.tab_translate_label)
        self.app._on_mode_switched(self.app.tab_translate_label)
        tr_tab = self.app.mode_segmented._buttons_dict[self.app.tab_translate_label]
        cv_tab = self.app.mode_segmented._buttons_dict[self.app.tab_convert_label]

        self.assertEqual(tr_tab.cget("fg_color"), SEGMENTED_BUTTON_TOKENS["selected_color"])
        self.assertEqual(tr_tab.cget("text_color"), SEGMENTED_BUTTON_TOKENS["selected_text_color"])
        self.assertEqual(cv_tab.cget("fg_color"), SEGMENTED_BUTTON_TOKENS["unselected_color"])
        self.assertEqual(cv_tab.cget("text_color"), SEGMENTED_BUTTON_TOKENS["unselected_text_color"])

        # Switch to Convert Format tab
        self.app.mode_segmented.set(self.app.tab_convert_label)
        self.app._on_mode_switched(self.app.tab_convert_label)
        self.assertEqual(cv_tab.cget("fg_color"), SEGMENTED_BUTTON_TOKENS["selected_color"])
        self.assertEqual(cv_tab.cget("text_color"), SEGMENTED_BUTTON_TOKENS["selected_text_color"])
        self.assertEqual(tr_tab.cget("fg_color"), SEGMENTED_BUTTON_TOKENS["unselected_color"])
        self.assertEqual(tr_tab.cget("text_color"), SEGMENTED_BUTTON_TOKENS["unselected_text_color"])

        # 2. Action buttons: disabled state must use muted surface, ready state restores primary surface
        self.app.selected_convert_file = None
        self.app.selected_target_format = None
        self.app._update_button_states("idle_no_file")
        self.assertEqual(self.app.convert_btn.cget("state"), "disabled")
        self.assertEqual(self.app.convert_btn.cget("fg_color"), BUTTON_DISABLED_STYLES["filled"]["fg_color"])

        self.app.selected_convert_file = "/fake/sample.pdf"
        self.app.selected_target_format = "docx"
        self.app._update_button_states("file_ready")
        self.assertEqual(self.app.convert_btn.cget("state"), "normal")
        self.assertEqual(self.app.convert_btn.cget("fg_color"), BUTTON_VARIANTS["primary"]["fg_color"])

        self.app.mode_segmented.set(self.app.tab_translate_label)
        self.app._on_mode_switched(self.app.tab_translate_label)
        self.app.selected_file = None
        self.app._update_button_states("idle_no_file")
        self.assertEqual(self.app.translate_btn.cget("state"), "disabled")
        self.assertEqual(self.app.translate_btn.cget("fg_color"), BUTTON_DISABLED_STYLES["filled"]["fg_color"])

        self.app.selected_file = "/fake/sample.docx"
        self.app._update_button_states("file_ready")
        self.assertEqual(self.app.translate_btn.cget("state"), "normal")
        self.assertEqual(self.app.translate_btn.cget("fg_color"), BUTTON_VARIANTS["primary"]["fg_color"])

        # Cleanup
        self.app.selected_file = None
        self.app.selected_convert_file = None
        self.app.selected_target_format = None
        self.app._update_button_states("idle_no_file")
        self.app._refresh_status_text()

    def test_start_translation_requires_explicit_model_before_running(self):
        """When API key is set but no model is selected, _start_translation blocks and opens Settings."""
        from unittest.mock import patch

        prev_prov = self.app.config.active_provider
        prev_key = self.app.config.api_keys.get(prev_prov, "")
        prev_model = self.app.config.selected_models.get(prev_prov, "")
        try:
            self.app.current_screen = "main"
            self.app.selected_file = "/fake/sample.docx"
            self.app.config.active_provider = "OpenAI"
            self.app.config.api_keys["OpenAI"] = "sk-test-key"
            self.app.config.selected_models["OpenAI"] = ""
            self.app._on_settings_changed(self.app.config)

            self.assertIn("No model", self.app.provider_badge.cget("text"))

            with patch.object(self.app, "_open_settings") as mock_settings, \
                 patch.object(self.app, "_run_translation_worker") as mock_worker:
                self.app._start_translation()
                mock_worker.assert_not_called()
                mock_settings.assert_called_once()
                self.assertFalse(self.app.is_translating)
                self.assertIn("OpenAI", self.app.status_label.cget("text"))
        finally:
            self.app.config.active_provider = prev_prov
            self.app.config.api_keys[prev_prov] = prev_key
            self.app.config.selected_models[prev_prov] = prev_model
            self.app.selected_file = None
            self.app._on_settings_changed(self.app.config)
            self.app._update_button_states("idle_no_file")
            self.app._refresh_status_text()

    def test_bilingual_checkbox_enabled_only_for_xlsx(self):
        """bilingual_cb stays enabled only for .xlsx (or no file) and disabled for .docx/.pdf/.txt; worker clamps non-.xlsx."""
        from pathlib import Path
        from unittest.mock import patch
        from rakutrans.parsers.translator_registry import TranslatorRegistry

        prev_bilingual = self.app.config.translation_options.bilingual_mode
        try:
            self.app.current_screen = "main"
            self.app._on_file_selected(str(Path(self._tmp_dir.name) / "sheet.xlsx"))
            self.assertEqual(self.app.bilingual_cb.cget("state"), "normal")

            for non_xlsx in ("report.docx", "slides.pptx", "doc.pdf", "notes.txt", "README.md"):
                self.app._on_file_selected(str(Path(self._tmp_dir.name) / non_xlsx))
                self.assertEqual(
                    self.app.bilingual_cb.cget("state"),
                    "disabled",
                    f"Expected bilingual_cb disabled for {non_xlsx}",
                )

            # Worker also strips bilingual_mode=True when translating non-.xlsx
            self.app.config.translation_options.bilingual_mode = True
            seen = {}

            class _FakeDocxTr:
                def process_file(self, **kwargs):
                    seen["bilingual"] = kwargs["options"].bilingual_mode
                    return str(Path(self._tmp_dir.name) / "report_vi.docx") if False else "out.docx"

            fake_docx = Path(self._tmp_dir.name) / "report.docx"
            fake_docx.write_bytes(b"PK")
            cancel_ev = __import__("threading").Event()
            with patch.object(TranslatorRegistry, "create_translator", return_value=_FakeDocxTr()), \
                 patch.object(self.app, "_safe_after"):
                self.app._run_translation_worker(str(fake_docx), "Vietnamese", cancel_ev)
            self.assertFalse(seen["bilingual"])
        finally:
            self.app.config.translation_options.bilingual_mode = prev_bilingual
            self.app._on_file_selected("")

    def test_close_settings_commits_pending_numeric_edits(self):
        """Editing a numeric advanced setting and immediately clicking Done persists without requiring FocusOut."""
        prev_batch = self.app.config.batch_size
        prev_rpm = self.app.config.rpm_limit
        prev_preset = self.app.config.rate_limit_preset
        try:
            self.app._open_settings()
            self.assertEqual(self.app.current_screen, "settings")

            self.app.settings_view.batch_size_var.set("37")
            self.app.settings_view.rpm_limit_var.set("19")
            self.assertTrue(self.app.settings_view._adv_numeric_dirty)

            # Immediately close Settings via Done without FocusOut or Return
            self.app._close_settings()

            self.assertEqual(self.app.current_screen, "main")
            self.assertEqual(self.app.config.batch_size, 37)
            self.assertEqual(self.app.config.rpm_limit, 19)
            self.assertEqual(self.app.config.rate_limit_preset, "custom")
            self.assertEqual(self.app.llm_manager.config.batch_size, 37)
            self.assertEqual(self.app.llm_manager.config.rpm_limit, 19)
        finally:
            self.app.config.batch_size = prev_batch
            self.app.config.rpm_limit = prev_rpm
            self.app.config.rate_limit_preset = prev_preset
            self.app.config.save()
            self.app._on_settings_changed(self.app.config)

    def test_quick_speed_mode_in_translation_options_and_settings_sync(self):
        """Speed & Limit Mode inside Translation Options syncs bidirectionally with Settings, i18n, and processing state."""
        from rakutrans.core.config import DEFAULT_RATE_LIMIT_PRESET, RATE_LIMIT_PRESETS

        prev_preset = self.app.config.rate_limit_preset
        prev_lang = self.app.config.ui_language
        try:
            self.app.current_screen = "main"
            self.app.config.ui_language = "en"
            self.app.config.apply_rate_limit_preset(DEFAULT_RATE_LIMIT_PRESET)
            self.app._on_settings_changed(self.app.config)

            # 1. Lives inside collapsible options_body
            self.assertEqual(self.app.speed_mode_dropdown.master, self.app.options_body)
            self.assertEqual(self.app.speed_mode_var.get(), self.app.i18n.t("rate_profile_balanced"))

            # 2. Switch to Slow & Safe from Translation Options -> applies preset, updates summary & llm_manager
            self.app._on_quick_rate_profile_changed(self.app.i18n.t("rate_profile_safe_free"))
            self.assertEqual(self.app.config.rate_limit_preset, "safe_free")
            self.assertEqual(self.app.config.rpm_limit, RATE_LIMIT_PRESETS["safe_free"]["rpm_limit"])
            self.assertEqual(self.app.config.max_concurrent_requests, RATE_LIMIT_PRESETS["safe_free"]["max_concurrent_requests"])
            self.assertEqual(self.app.llm_manager.config.rpm_limit, RATE_LIMIT_PRESETS["safe_free"]["rpm_limit"])
            self.assertEqual(self.app.speed_mode_var.get(), self.app.i18n.t("rate_profile_safe_free"))
            self.assertIn("12", self.app.speed_mode_summary_label.cget("text"))

            # 3. Opening Settings shows the same preset; switching to Fast in Settings syncs back to Translate options
            self.app._open_settings()
            self.assertEqual(self.app.settings_view.rate_profile_var.get(), self.app.i18n.t("rate_profile_safe_free"))
            self.app.settings_view._on_rate_profile_changed(self.app.i18n.t("rate_profile_fast_paid"))
            self.app._close_settings()
            self.assertEqual(self.app.config.rate_limit_preset, "fast_paid")
            self.assertEqual(self.app.speed_mode_var.get(), self.app.i18n.t("rate_profile_fast_paid"))

            # 4. Selecting Custom from Translation Options opens Settings with Fine-Tuning expanded
            self.app._on_quick_rate_profile_changed(self.app.i18n.t("rate_profile_custom_quick"))
            self.assertEqual(self.app.current_screen, "settings")
            self.assertTrue(self.app.settings_view._advanced_expanded)
            self.assertEqual(self.app.settings_view.rate_profile_var.get(), self.app.i18n.t("rate_profile_custom"))

            # Closing Settings without modifying numbers restores actual preset label on Translate screen
            self.app._close_settings()
            self.assertEqual(self.app.speed_mode_var.get(), self.app.i18n.t("rate_profile_fast_paid"))

            # Selecting Custom and actually editing a number reflects Custom on Translate screen
            self.app._on_quick_rate_profile_changed(self.app.i18n.t("rate_profile_custom_quick"))
            self.app.settings_view.rpm_limit_var.set("25")
            self.app._close_settings()
            self.assertEqual(self.app.config.rate_limit_preset, "custom")
            self.assertEqual(self.app.speed_mode_var.get(), self.app.i18n.t("rate_profile_custom_quick"))
            self.assertIn("25", self.app.speed_mode_summary_label.cget("text"))

            # 5. Language switching updates label, dropdown selection, and summary
            self.app.config.apply_rate_limit_preset("balanced")
            self.app.config.ui_language = "vi"
            self.app._on_settings_changed(self.app.config)
            self.assertEqual(self.app.speed_mode_label.cget("text"), self.app.i18n.t("rate_profile_label"))
            self.assertEqual(self.app.speed_mode_var.get(), self.app.i18n.t("rate_profile_balanced"))

            # 6. Disabled during processing, re-enabled when idle
            self.app._update_button_states("processing")
            self.assertEqual(self.app.speed_mode_dropdown.cget("state"), "disabled")
            self.app._update_button_states("idle_no_file")
            self.assertEqual(self.app.speed_mode_dropdown.cget("state"), "normal")
        finally:
            if self.app.current_screen == "settings":
                self.app._close_settings()
            self.app.config.ui_language = prev_lang
            self.app.config.apply_rate_limit_preset(
                prev_preset if prev_preset in RATE_LIMIT_PRESETS else DEFAULT_RATE_LIMIT_PRESET
            )
            self.app.config.save()
            self.app._on_settings_changed(self.app.config)


if __name__ == "__main__":
    unittest.main()
