"""
Unit tests for UI System primitives: CustomButton, BaseModal, ConfirmModal, ToastManager.
"""

import unittest

try:
    import tkinter
    import customtkinter
    HAS_TKINTER = True
    from components.ui_system import (
        BUTTON_SIZES,
        BUTTON_VARIANTS,
        SPINNER_FRAMES,
        CustomButton,
        BaseModal
    )
    from components.confirm_modal import ConfirmModal
    from components.toast import ToastManager, TOAST_STYLES
except (ImportError, ModuleNotFoundError):
    HAS_TKINTER = False


@unittest.skipUnless(HAS_TKINTER, "Tkinter is not available in this Python environment")
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
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import customtkinter as ctk
        import config as config_mod
        import model_fetcher
        from config import AppConfig
        from components.settings_modal import SettingsView

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch.object(config_mod, "CONFIG_DIR", tmp_path), \
                 patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"), \
                 patch.object(model_fetcher, "CACHE_DIR", tmp_path), \
                 patch.object(model_fetcher, "MODELS_CACHE_FILE", tmp_path / "models_cache.json"):
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

                # 2. Provider selector has thin border, equal column weights/uniform, and provider logo icons
                self.assertEqual(sv.provider_selector.cget("border_width"), 1)
                for prov in ("Gemini", "OpenAI", "Claude"):
                    self.assertIsNotNone(sv.provider_selector._buttons_dict[prov].cget("image"))

                # 3. Direct changes immediately persist to isolated temp config (never user's ~/.rakutrans)
                sv._on_provider_changed("OpenAI")
                self.assertEqual(cfg.active_provider, "OpenAI")
                self.assertTrue(len(save_events) >= 1)

                sv._on_model_changed("gpt-4o")
                self.assertEqual(cfg.selected_models["OpenAI"], "gpt-4o")

                root.destroy()


    def test_vector_icons_and_hidpi_assets(self):
        """Verify crisp vector CTkImage icons and multi-size HiDPI Windows .ico asset."""
        from pathlib import Path
        from PIL import Image
        import customtkinter as ctk
        from components.icons import get_icon

        root = ctk.CTk()
        for name in (
            "globe", "settings", "refresh", "rotate_ccw", "folder", "folder_hero",
            "file_text", "file_excel", "file_word", "file_ppt", "file_pdf",
            "database", "save", "trash", "alert_triangle", "check", "info",
            "close", "plus", "minus", "arrow_left", "download", "zap", "eye", "lock",
            "key", "clock", "stop_circle", "lightbulb", "copy", "format",
            "provider_gemini", "provider_openai", "provider_claude"
        ):
            img = get_icon(name, "secondary", 16)
            self.assertIsInstance(img, ctk.CTkImage)

        from components.icons import get_provider_icon
        for prov in ("Gemini", "OpenAI", "Claude"):
            self.assertIsInstance(get_provider_icon(prov, "muted", 14), ctk.CTkImage)

        ico_path = Path(__file__).resolve().parent.parent / "assets" / "icon.ico"
        self.assertTrue(ico_path.exists())
        with Image.open(ico_path) as ico_img:
            self.assertIn((256, 256), ico_img.ico.sizes())
            self.assertIn((32, 32), ico_img.ico.sizes())
        root.destroy()

    def test_custom_button_text_sync_and_destroy_cancels_spinner(self):
        import customtkinter as ctk

        root = ctk.CTk()
        btn = CustomButton(root, text="Initial")
        btn.pack()
        btn.configure(text="Updated")
        self.assertEqual(btn._raw_text, "Updated")

        btn.start_loading("Working")
        self.assertTrue(btn._is_loading)
        self.assertIsNotNone(btn._loading_after_id)
        btn.destroy()
        self.assertFalse(btn._is_loading)
        self.assertIsNone(btn._loading_after_id)
        root.update()
        root.destroy()

    def test_confirm_modal_enter_on_cancel_closes_instead_of_confirming(self):
        import customtkinter as ctk

        root = ctk.CTk()
        confirmed = []
        modal = ConfirmModal(root, on_confirm=lambda: confirmed.append(True), get_translation=lambda k, **kw: k)
        modal.update()
        modal.cancel_btn.focus_set()
        modal.cancel_btn.event_generate("<Return>")
        root.update()

        self.assertEqual(confirmed, [])
        self.assertTrue(modal._closed)
        root.destroy()

    def test_dropzone_splitlist_directory_guard_and_inspection_race(self):
        import tempfile
        from pathlib import Path
        import customtkinter as ctk
        from components.dnd_zone import DropZone

        root = ctk.CTk()
        invalid_calls = []
        selected = []
        dz = DropZone(
            root,
            on_file_selected=lambda p: selected.append(p),
            get_translation=lambda k, **kw: k,
            on_invalid_file=lambda msg, p: invalid_calls.append((msg, p)),
        )
        dz.pack()

        parsed = dz._parse_drop_paths("{/tmp/dir with spaces/a.docx} {/tmp/b.pdf}")
        self.assertEqual(parsed, ["/tmp/dir with spaces/a.docx", "/tmp/b.pdf"])

        with tempfile.TemporaryDirectory() as tmpdir:
            dz.set_file(tmpdir)
            self.assertIsNone(dz.selected_file)
            self.assertEqual(len(invalid_calls), 1)

            f1 = Path(tmpdir) / "doc.txt"
            f1.write_text("hello", encoding="utf-8")
            dz.set_file(str(f1))
            tok1 = dz._inspect_token
            dz.clear()
            dz._on_inspection_ready(tok1, str(f1.resolve()), ".txt", {"line_count": 1, "word_count": 1, "char_count": 5})
            self.assertEqual(dz.inspector_label.cget("text"), "")

        dz.destroy()
        root.destroy()

    def test_settings_key_debounce_and_provider_race(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import customtkinter as ctk
        import config as config_mod
        import model_fetcher
        from config import AppConfig
        from components.settings_modal import SettingsView

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch.object(config_mod, "CONFIG_DIR", tmp_path), \
                 patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"), \
                 patch.object(model_fetcher, "CACHE_DIR", tmp_path), \
                 patch.object(model_fetcher, "MODELS_CACHE_FILE", tmp_path / "models_cache.json"), \
                 patch("components.settings_modal.fetch_models_async") as mock_fetch:
                cfg = AppConfig()
                root = ctk.CTk()
                sv = SettingsView(
                    root,
                    config=cfg,
                    get_translation=lambda k, **kw: k,
                    on_save_callback=lambda c: None,
                    on_close_callback=lambda: None,
                )
                root.update()
                mock_fetch.assert_not_called()

                sv.refresh_values()
                self.assertFalse(sv._key_save_pending)

                sv.key_var.set("sk-live-123")
                self.assertEqual(cfg.api_keys[cfg.active_provider], "sk-live-123")
                self.assertTrue(sv._key_save_pending)

                old_fetch_id = sv._fetch_request_id
                old_conn_id = sv._test_conn_request_id
                sv.fetch_btn.start_loading("fetching")
                sv._on_provider_changed("OpenAI")
                self.assertGreater(sv._fetch_request_id, old_fetch_id)
                self.assertGreater(sv._test_conn_request_id, old_conn_id)
                self.assertFalse(sv.fetch_btn._is_loading)

                sv.destroy()
                root.destroy()


if __name__ == "__main__":
    unittest.main()

