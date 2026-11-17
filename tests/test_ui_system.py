"""
Unit tests for UI System primitives: CustomButton, BaseModal, ConfirmModal.
"""

import unittest

try:
    import tkinter
    import customtkinter
    HAS_TKINTER = True
    from components.ui_system import (
        BUTTON_SIZES,
        BUTTON_VARIANTS,
        BUTTON_DISABLED_STYLES,
        SEGMENTED_BUTTON_TOKENS,
        SPINNER_FRAMES,
        CustomButton,
        CustomSegmentedButton,
        BaseModal
    )
    from components.confirm_modal import ConfirmModal
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

        # Verify button variants
        expected_variants = {"primary", "secondary", "outline", "danger", "ghost"}
        for var in expected_variants:
            self.assertIn(var, BUTTON_VARIANTS)
            vcfg = BUTTON_VARIANTS[var]
            self.assertIn("fg_color", vcfg)
            self.assertIn("hover_color", vcfg)
            self.assertIn("text_color", vcfg)

        self.assertTrue(len(SPINNER_FRAMES) >= 4)

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

                # 1. No redundant save/close/back buttons in SettingsView header (main header owns navigation)
                self.assertFalse(hasattr(sv, "save_btn"))
                self.assertFalse(hasattr(sv, "close_btn"))
                self.assertFalse(hasattr(sv, "back_header_btn"))

                # 2. Provider selector has thin border, equal column weights/uniform, and provider logo icons
                self.assertEqual(sv.provider_selector.cget("border_width"), 1)
                for prov in ("Gemini", "OpenAI", "Claude"):
                    self.assertIsNotNone(sv.provider_selector._buttons_dict[prov].cget("image"))

                # 3. Direct changes immediately persist to isolated temp config (never user's ~/.rakutrans)
                model_fetcher.save_cached_models("OpenAI", ["gpt-4o-mini", "gpt-4o"])
                sv._on_provider_changed("OpenAI")
                self.assertEqual(cfg.active_provider, "OpenAI")
                # Must NOT auto-select models[0] when switching provider
                self.assertEqual(cfg.selected_models["OpenAI"], "")
                self.assertEqual(cfg.get_active_model(), "")
                self.assertTrue(len(save_events) >= 1)

                # Test connection without selected model must fail early without fetching models[0]
                sv.key_var.set("sk-test-key")
                with patch("llm_manager.create_llm_client") as mock_client:
                    sv._test_api_connection()
                    mock_client.assert_not_called()
                    self.assertEqual(sv.test_conn_status.cget("text"), "err_select_model")

                sv._on_model_changed("gpt-4o")
                self.assertEqual(cfg.selected_models["OpenAI"], "gpt-4o")

                # Background / manual fetch completion must NOT overwrite user's choice or auto-pick models[0]
                cfg.selected_models["OpenAI"] = ""
                sv._apply_model_options(["gpt-4o-mini", "gpt-4o"], "")
                with patch(
                    "components.settings_modal.fetch_models_async",
                    side_effect=lambda p, k, cb, **_kw: cb(["gpt-4o-mini", "gpt-4o"], None),
                ):
                    sv._fetch_live_models(is_manual=True)
                    root.update()
                self.assertEqual(cfg.selected_models["OpenAI"], "")
                self.assertEqual(sv.model_combo.cget("values"), ["gpt-4o-mini", "gpt-4o"])

                # Advanced section starts collapsed and persists base_url, temperature, batch/concurrency, strict JSON
                self.assertFalse(sv._advanced_expanded)
                sv._toggle_advanced_section()
                self.assertTrue(sv._advanced_expanded)
                sv.base_url_var.set("https://custom.openai.local/v1")
                sv.temperature_var.set("0.4")
                sv.batch_size_var.set("40")
                sv.max_concurrent_var.set("8")
                sv.request_timeout_var.set("90")
                sv.strict_json_var.set(False)
                sv._commit_advanced_settings()

                self.assertEqual(cfg.base_urls["OpenAI"], "https://custom.openai.local/v1")
                self.assertAlmostEqual(cfg.temperature, 0.4)
                self.assertEqual(cfg.batch_size, 40)
                self.assertEqual(cfg.max_concurrent_requests, 8)
                self.assertAlmostEqual(cfg.request_timeout, 90.0)
                self.assertFalse(cfg.strict_json_mode)

                # Per-provider base_url switches cleanly and fetch_models_async receives base_url & timeout
                with patch("components.settings_modal.fetch_models_async") as mock_fetch_adv:
                    sv._fetch_live_models(is_manual=True)
                    mock_fetch_adv.assert_called_once()
                    self.assertEqual(
                        mock_fetch_adv.call_args.kwargs.get("base_url"),
                        "https://custom.openai.local/v1",
                    )
                    self.assertAlmostEqual(
                        mock_fetch_adv.call_args.kwargs.get("timeout"),
                        cfg.model_fetch_timeout,
                    )

                sv._on_provider_changed("Gemini")
                self.assertEqual(sv.base_url_var.get(), "")
                sv._on_provider_changed("OpenAI")
                self.assertEqual(sv.base_url_var.get(), "https://custom.openai.local/v1")

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

    def test_dropzone_workload_warning_and_settings_rate_profile(self):
        import tempfile
        from pathlib import Path
        import customtkinter as ctk
        from config import AppConfig
        from components.dnd_zone import DropZone
        from components.settings_modal import SettingsView

        root = ctk.CTk()
        cfg = AppConfig()

        with tempfile.TemporaryDirectory() as tmpdir:
            f_txt = Path(tmpdir) / "huge.txt"
            f_txt.write_text("line\n" * 100, encoding="utf-8")

            dz = DropZone(
                root,
                on_file_selected=lambda _p: None,
                get_translation=lambda k, **kw: f"{k}:{kw}" if kw else k,
                config_provider=lambda: cfg,
            )
            dz.pack()
            dz.set_file(str(f_txt))
            tok = dz._inspect_token
            # Simulate high char count yielding > HIGH_REQUEST_WARNING_THRESHOLD requests
            dz._on_inspection_ready(
                tok,
                str(f_txt.resolve()),
                ".txt",
                {"type": "txt", "line_count": 50000, "word_count": 200000, "char_count": 2400000},
            )
            self.assertIn("large_file_badge_warning", dz.workload_warning_label.cget("text"))

            dz.clear()
            self.assertEqual(dz.workload_warning_label.cget("text"), "")
            dz.destroy()

        saved_cfgs = []
        sv = SettingsView(
            root,
            config=cfg,
            get_translation=lambda k, **kw: k,
            on_save_callback=lambda c: saved_cfgs.append(c),
            on_close_callback=lambda: None,
        )
        sv._on_rate_profile_changed("rate_profile_safe_free")
        self.assertEqual(cfg.rate_limit_preset, "safe_free")
        self.assertEqual(cfg.rpm_limit, 12)
        self.assertEqual(cfg.max_concurrent_requests, 1)
        self.assertEqual(sv.rpm_limit_var.get(), "12")

        sv.rpm_limit_var.set("25")
        sv.batch_max_chars_var.set("7500")
        sv._commit_advanced_settings()
        self.assertEqual(cfg.rpm_limit, 25)
        self.assertEqual(cfg.batch_max_chars, 7500)
        self.assertEqual(cfg.rate_limit_preset, "custom")

        sv.destroy()
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

    def test_custom_button_disabled_and_segmented_active_contrast(self):
        """Verify disabled primary CustomButton uses muted surface and CustomSegmentedButton syncs active/inactive styles."""
        import customtkinter as ctk

        ctk.set_appearance_mode("Dark")
        root = ctk.CTk()

        btn = CustomButton(root, text="Translate", variant="primary", icon_name="refresh", state="disabled")
        self.assertEqual(btn.cget("fg_color"), BUTTON_DISABLED_STYLES["filled"]["fg_color"])
        self.assertEqual(btn.cget("text_color_disabled"), BUTTON_DISABLED_STYLES["filled"]["text_color_disabled"])

        btn.configure(state="normal")
        self.assertEqual(btn.cget("fg_color"), BUTTON_VARIANTS["primary"]["fg_color"])
        self.assertEqual(btn.cget("text_color"), BUTTON_VARIANTS["primary"]["text_color"])

        seg = CustomSegmentedButton(
            root,
            values=["Translate", "Convert"],
            icons={"Translate": ("globe", 16), "Convert": ("refresh", 16)},
        )
        seg.set("Translate")
        tr_btn = seg._buttons_dict["Translate"]
        cv_btn = seg._buttons_dict["Convert"]
        self.assertEqual(tr_btn.cget("fg_color"), SEGMENTED_BUTTON_TOKENS["selected_color"])
        self.assertEqual(tr_btn.cget("text_color"), SEGMENTED_BUTTON_TOKENS["selected_text_color"])
        self.assertEqual(cv_btn.cget("fg_color"), SEGMENTED_BUTTON_TOKENS["unselected_color"])
        self.assertEqual(cv_btn.cget("text_color"), SEGMENTED_BUTTON_TOKENS["unselected_text_color"])
        tr_img_selected = tr_btn.cget("image")

        seg.set("Convert")
        self.assertEqual(cv_btn.cget("fg_color"), SEGMENTED_BUTTON_TOKENS["selected_color"])
        self.assertEqual(cv_btn.cget("text_color"), SEGMENTED_BUTTON_TOKENS["selected_text_color"])
        self.assertEqual(tr_btn.cget("fg_color"), SEGMENTED_BUTTON_TOKENS["unselected_color"])
        self.assertEqual(tr_btn.cget("text_color"), SEGMENTED_BUTTON_TOKENS["unselected_text_color"])
        self.assertNotEqual(tr_btn.cget("image"), tr_img_selected)

        root.destroy()


if __name__ == "__main__":
    unittest.main()

