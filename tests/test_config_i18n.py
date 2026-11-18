"""
Unit tests for configuration and i18n localization.
"""

import unittest
from config import AppConfig, UI_LANGUAGES, DEFAULT_TARGET_LANGUAGE, normalize_language_name
from i18n import I18nManager, TRANSLATIONS


class TestConfigAndI18n(unittest.TestCase):
    
    def test_default_config(self):
        config = AppConfig()
        self.assertEqual(config.ui_language, "en")
        self.assertEqual(config.active_provider, "Gemini")
        self.assertTrue(config.translation_options.keep_it_terms)
        self.assertFalse(config.translation_options.append_original_words)
        self.assertEqual(config.target_language, DEFAULT_TARGET_LANGUAGE)
        self.assertEqual(config.target_language, "English (English)")
        self.assertEqual(len(config.recent_target_languages), 3)
        self.assertIsNone(config.source_language)

    def test_recent_target_languages_logic(self):
        config = AppConfig()
        self.assertEqual(len(config.recent_target_languages), 3)

        # Recording a language moves it to the top
        config.record_recent_target_language("Japanese")
        self.assertEqual(config.recent_target_languages[0], "日本語 (Japanese)")
        self.assertEqual(len(config.recent_target_languages), 3)

        # Recording a new language (Korean) drops the oldest one
        config.record_recent_target_language("ko")
        self.assertEqual(config.recent_target_languages[0], "한국어 (Korean)")
        self.assertEqual(config.recent_target_languages[1], "日本語 (Japanese)")
        self.assertEqual(len(config.recent_target_languages), 3)

        # Re-recording Japanese moves it back to index 0 without duplicates
        config.record_recent_target_language("ja")
        self.assertEqual(config.recent_target_languages[0], "日本語 (Japanese)")
        self.assertEqual(config.recent_target_languages[1], "한국어 (Korean)")
        self.assertEqual(len(config.recent_target_languages), 3)

    def test_languages_alphabetical_order(self):
        from config import get_all_languages
        langs = get_all_languages()
        names = [l.name.lower() for l in langs]
        self.assertEqual(names, sorted(names))
        self.assertEqual(DEFAULT_TARGET_LANGUAGE, "English (English)")

    def test_i18n_all_languages(self):
        # Verify that all 3 languages exist in UI_LANGUAGES
        self.assertIn("en", UI_LANGUAGES)
        self.assertIn("ja", UI_LANGUAGES)
        self.assertIn("vi", UI_LANGUAGES)

        # Test language normalization
        self.assertEqual(normalize_language_name("Vietnamese"), "Tiếng Việt (Vietnamese)")
        self.assertEqual(normalize_language_name("vi"), "Tiếng Việt (Vietnamese)")
        self.assertEqual(normalize_language_name("English"), "English (English)")
        self.assertEqual(normalize_language_name("ja"), "日本語 (Japanese)")

        # Verify key consistency across languages
        en_keys = set(TRANSLATIONS["en"].keys())
        ja_keys = set(TRANSLATIONS["ja"].keys())
        vi_keys = set(TRANSLATIONS["vi"].keys())

        # All languages should have identical translation keys
        self.assertEqual(en_keys, ja_keys, "JA missing keys from EN")
        self.assertEqual(en_keys, vi_keys, "VI missing keys from EN")

        # Verify specific comprehensive i18n keys exist
        required_keys = [
            "preferences_title", "guide_gemini", "guide_openai", "guide_claude",
            "err_enter_api_key", "err_enter_api_key_models", "search_lang_placeholder",
            "no_matching_language", "recent_languages", "all_languages", "dialog_select_file", "filetype_supported",
            "filetype_pdf", "filetype_office", "filetype_spreadsheets", "filetype_text",
            "filetype_json", "filetype_all", "file_info_path", "file_info_size",
            "badge_plain_text", "dialog_save_copy", "status_saved_copy", "filetype_doc_ext",
            "status_cancelling", "status_cancelled", "notification_completed",
            "notification_convert_completed", "confirm_action_title", "confirm_action_msg",
            "confirm", "done"
        ]
        for rk in required_keys:
            self.assertIn(rk, en_keys)
            self.assertIn(rk, ja_keys)
            self.assertIn(rk, vi_keys)

        # Test I18nManager lookup
        manager = I18nManager("ja")
        self.assertEqual(manager.t("app_title"), "RakuTrans AI")
        self.assertIn("翻訳", manager.t("start_translation"))
        manager.set_language("vi")
        self.assertIn("dịch", manager.t("start_translation").lower())

    def test_smart_output_naming(self):
        import tempfile
        from pathlib import Path
        from config import get_smart_output_path, get_target_lang_code

        self.assertEqual(get_target_lang_code("Vietnamese"), "vi")
        self.assertEqual(get_target_lang_code("Tiếng Việt (Vietnamese)"), "vi")
        self.assertEqual(get_target_lang_code("English"), "en")
        self.assertEqual(get_target_lang_code("Japanese"), "ja")
        self.assertEqual(get_target_lang_code("Français (French)"), "fr")
        self.assertEqual(get_target_lang_code("한국어 (Korean)"), "ko")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # 1. report.xlsx -> report_vi.xlsx, report_vi (1).xlsx, report_vi (2).xlsx
            f1 = tmp_path / "report.xlsx"
            f1.touch()

            out1 = get_smart_output_path(f1, target_lang="Vietnamese")
            self.assertEqual(out1.name, "report_vi.xlsx")
            out1.touch()

            out2 = get_smart_output_path(f1, target_lang="Vietnamese")
            self.assertEqual(out2.name, "report_vi (1).xlsx")
            out2.touch()

            out3 = get_smart_output_path(f1, target_lang="Vietnamese")
            self.assertEqual(out3.name, "report_vi (2).xlsx")

            # 2. report_en.xlsx -> report_en_vi.xlsx
            f_en = tmp_path / "report_en.xlsx"
            f_en.touch()
            out_en_vi = get_smart_output_path(f_en, target_lang="Vietnamese")
            self.assertEqual(out_en_vi.name, "report_en_vi.xlsx")

            # 3. report_vi.xlsx translated to vi again -> report_vi (no report_vi_vi)
            f_fresh_vi = tmp_path / "fresh_vi.xlsx"
            f_fresh_vi.touch()
            out_fresh = get_smart_output_path(f_fresh_vi, target_lang="Vietnamese")
            self.assertEqual(out_fresh.name, "fresh_vi (1).xlsx")

            # 4. Convert format: report.xlsx -> report.md, report (1).md
            c1 = get_smart_output_path(f1, target_format=".md")
            self.assertEqual(c1.name, "report.md")
            c1.touch()

            c2 = get_smart_output_path(f1, target_format=".md")
            self.assertEqual(c2.name, "report (1).md")

            # 5. Convert format: report.md -> report.xlsx -> report (1).xlsx (since report.xlsx exists)
            c3 = get_smart_output_path(c1, target_format=".xlsx")
            self.assertEqual(c3.name, "report (1).xlsx")

            # 6. Bilingual mode
            f_bilingual = tmp_path / "sales.xlsx"
            b_out = get_smart_output_path(f_bilingual, target_lang="Vietnamese", is_bilingual=True)
            self.assertEqual(b_out.name, "sales_vi_bilingual.xlsx")

    def test_bilingual_mode_roundtrip_persistence(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import config as config_mod
        from config import TranslationOptions

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = Path(tmpdir)
            cfg_file = cfg_dir / "config.json"
            with patch.object(config_mod, "CONFIG_DIR", cfg_dir), patch.object(config_mod, "CONFIG_FILE", cfg_file):
                cfg = AppConfig(translation_options=TranslationOptions(bilingual_mode=True, custom_context="glossary"))
                cfg.save()
                loaded = AppConfig.load()
                self.assertTrue(loaded.translation_options.bilingual_mode)
                self.assertEqual(loaded.translation_options.custom_context, "glossary")

    def test_user_selected_model_not_overwritten_and_cli_flags(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import config as config_mod
        from main import build_cli_parser

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = Path(tmpdir)
            cfg_file = cfg_dir / "config.json"
            with patch.object(config_mod, "CONFIG_DIR", cfg_dir), patch.object(config_mod, "CONFIG_FILE", cfg_file):
                fresh = AppConfig.load()
                self.assertEqual(fresh.active_provider, "Gemini")

                cfg = AppConfig()
                cfg.selected_models["Gemini"] = "gemini-2.5-flash"
                cfg.save()
                loaded = AppConfig.load()
                self.assertEqual(loaded.selected_models["Gemini"], "gemini-2.5-flash")

        parser = build_cli_parser()
        args = parser.parse_args([
            "--cli", "-f", "doc.xlsx", "--no-keep-terms", "--bilingual", "-o", "custom_out.xlsx"
        ])
        self.assertFalse(args.keep_it)
        self.assertTrue(args.bilingual)
        self.assertEqual(args.output_path, "custom_out.xlsx")

    def test_env_api_keys_not_frozen_and_atomic_resilient_load(self):
        import json
        import os
        import tempfile
        import threading
        from pathlib import Path
        from unittest.mock import patch
        import config as config_mod
        from config import get_smart_output_path

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = Path(tmpdir)
            cfg_file = cfg_dir / "config.json"
            with patch.object(config_mod, "CONFIG_DIR", cfg_dir), patch.object(config_mod, "CONFIG_FILE", cfg_file):
                with patch.dict(os.environ, {"GEMINI_API_KEY": "env-secret-1"}):
                    loaded = AppConfig.load()
                    self.assertEqual(loaded.get_effective_api_key("Gemini"), "env-secret-1")
                    raw_saved = json.loads(cfg_file.read_text(encoding="utf-8"))
                    self.assertEqual(raw_saved["api_keys"]["Gemini"], "")

                # Unsetting env var takes effect immediately because key was not frozen
                with patch.dict(os.environ, {}, clear=False):
                    os.environ.pop("GEMINI_API_KEY", None)
                    self.assertEqual(loaded.get_effective_api_key("Gemini"), "")

                # Malformed types in config.json must not crash load() or drop valid fields
                cfg_file.write_text(
                    json.dumps({
                        "ui_language": "invalid",
                        "theme_mode": "neon",
                        "active_provider": "OpenAI",
                        "api_keys": {"OpenAI": None, "Gemini": "k1"},
                        "batch_size": "not-an-int",
                        "max_concurrent_requests": "bad",
                        "translation_options": "bad-type",
                        "auto_check_updates": "invalid-bool",
                        "skipped_update_version": 123,
                    }),
                    encoding="utf-8",
                )
                recovered = AppConfig.load()
                self.assertEqual(recovered.active_provider, "OpenAI")
                self.assertEqual(recovered.ui_language, "en")
                self.assertEqual(recovered.theme_mode, "dark")
                self.assertEqual(recovered.batch_size, 100)
                self.assertEqual(recovered.max_concurrent_requests, 2)
                self.assertTrue(recovered.auto_check_updates)
                self.assertEqual(recovered.skipped_update_version, "")
                self.assertEqual(recovered.get_effective_api_key("Gemini"), "k1")
                self.assertEqual(recovered.get_effective_api_key("OpenAI"), "")

                recovered.auto_check_updates = False
                recovered.skipped_update_version = "1.2.0"
                recovered.save()
                reloaded_upd = AppConfig.load()
                self.assertFalse(reloaded_upd.auto_check_updates)
                self.assertEqual(reloaded_upd.skipped_update_version, "1.2.0")

                # Concurrent saves + loads never produce truncated JSON
                errors = []

                def _writer(idx: int):
                    try:
                        c = AppConfig(batch_size=10 + idx)
                        for _ in range(10):
                            c.save()
                            AppConfig.load()
                    except Exception as exc:
                        errors.append(exc)

                threads = [threading.Thread(target=_writer, args=(i,)) for i in range(4)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                self.assertEqual(errors, [])

        self.assertEqual(normalize_language_name("繁體中文 (Chinese (Traditional))"), "繁體中文 (Chinese (Traditional))")
        out_extless = get_smart_output_path("README", target_lang="Vietnamese")
        self.assertEqual(out_extless.name, "README_vi")

    def test_cli_convert_requires_file_and_i18n_tsv(self):
        import io
        import sys
        from unittest.mock import patch
        import main as main_mod

        for lang in ("en", "ja", "vi"):
            i18n = I18nManager(lang)
            self.assertIn(".tsv", i18n.t("drag_drop_title"))
            self.assertIn("*.tsv", i18n.t("filetype_supported"))
            self.assertIn(".tsv", i18n.t("err_unsupported_file"))

        self.assertNotIn("英語", TRANSLATIONS["ja"]["opt_keep_terms"])

        buf = io.StringIO()
        with patch.object(sys, "argv", ["main.py", "--convert", "docx"]), \
             patch("sys.stdout", buf), \
             patch.object(main_mod.AppConfig, "load", return_value=AppConfig(ui_language="en")), \
             patch.object(main_mod, "launch_gui") as mock_gui:
            with self.assertRaises(SystemExit) as cm:
                main_mod.main()
            self.assertEqual(cm.exception.code, 1)
            mock_gui.assert_not_called()
            self.assertIn("--convert requires --file", buf.getvalue())

    def test_explicit_provider_and_model_required_without_magic_guessing(self):
        import io
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import config as config_mod
        import model_fetcher
        import main as main_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch.object(config_mod, "CONFIG_DIR", tmp_path), \
                 patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"), \
                 patch.object(model_fetcher, "CACHE_DIR", tmp_path), \
                 patch.object(model_fetcher, "MODELS_CACHE_FILE", tmp_path / "models_cache.json"):
                model_fetcher.save_cached_models("Gemini", ["gemini-cached-0"])
                cfg = AppConfig()
                cfg.active_provider = "Gemini"
                cfg.api_keys["Gemini"] = "k-gem"
                cfg.selected_models["Gemini"] = ""
                cfg.save()

                # Cached models must NOT be silently picked as active model
                self.assertEqual(cfg.get_active_model(), "")

                sample_txt = tmp_path / "sample.txt"
                sample_txt.write_text("Hello", encoding="utf-8")

                # 1. CLI --model without --provider must fail explicitly
                buf_no_prov = io.StringIO()
                with patch("sys.stdout", buf_no_prov):
                    with self.assertRaises(SystemExit) as cm1:
                        main_mod.run_cli_translation(str(sample_txt), model="gpt-4o")
                self.assertEqual(cm1.exception.code, 1)
                self.assertIn("--model requires --provider", buf_no_prov.getvalue())

                # 2. CLI without selected model must fail explicitly
                buf_no_model = io.StringIO()
                with patch("sys.stdout", buf_no_model):
                    with self.assertRaises(SystemExit) as cm2:
                        main_mod.run_cli_translation(str(sample_txt), provider="Gemini")
                self.assertEqual(cm2.exception.code, 1)
                self.assertIn("No model selected for provider 'Gemini'", buf_no_model.getvalue())

                # 3. CLI with explicit --provider and --model runs cleanly without mutating config.json
                from translator_registry import TranslatorRegistry
                captured = {}

                class _FakeTr:
                    def process_file(self, **kwargs):
                        captured["provider"] = cfg_seen["obj"].active_provider
                        captured["model"] = cfg_seen["obj"].get_active_model()
                        return str(tmp_path / "sample_vi.txt")

                cfg_seen = {}

                def _fake_create(path, cfg_obj, llm_mgr):
                    cfg_seen["obj"] = cfg_obj
                    return _FakeTr()

                buf_ok = io.StringIO()
                with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env-cli"}), \
                     patch("sys.stdout", buf_ok), \
                     patch.object(TranslatorRegistry, "create_translator", side_effect=_fake_create):
                    main_mod.run_cli_translation(str(sample_txt), provider="OpenAI", model="gpt-4o")
                self.assertEqual(captured, {"provider": "OpenAI", "model": "gpt-4o"})
                self.assertEqual(AppConfig.load().active_provider, "Gemini")
                self.assertEqual(AppConfig.load().selected_models["OpenAI"], "")

                # 4. CLI --bilingual on non-xlsx file must warn and clamp bilingual_mode to False
                bilingual_seen = {}

                class _FakeNonExcelTr:
                    def process_file(self, **kwargs):
                        bilingual_seen["mode"] = kwargs["options"].bilingual_mode
                        return str(tmp_path / "sample_vi.txt")

                buf_bi = io.StringIO()
                with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env-cli"}), \
                     patch("sys.stdout", buf_bi), \
                     patch.object(
                         TranslatorRegistry,
                         "create_translator",
                         side_effect=lambda *a, **kw: _FakeNonExcelTr(),
                     ):
                    main_mod.run_cli_translation(
                        str(sample_txt), provider="OpenAI", model="gpt-4o", bilingual=True
                    )
                self.assertFalse(bilingual_seen["mode"])
                self.assertIn(".xlsx", buf_bi.getvalue())

    def test_rakutrans_home_override_and_advanced_config_persistence(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import config as config_mod
        import model_fetcher
        from translation_cache import TranslationCache

        with tempfile.TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "custom_rakutrans_home"
            with patch.dict(os.environ, {"RAKUTRANS_HOME": str(home_dir)}, clear=False):
                self.assertEqual(config_mod.get_config_dir(), home_dir.resolve())

                cfg = AppConfig(
                    base_urls={"OpenAI": "https://proxy.example/v1", "Gemini": "", "Claude": ""},
                    temperature=0.45,
                    strict_json_mode=False,
                    request_timeout=75.0,
                    model_fetch_timeout=18.0,
                    batch_size=40,
                    batch_max_chars=5200,
                    section_max_chars=4800,
                    max_concurrent_requests=12,
                    min_request_interval=0.15,
                    max_retries_general=4,
                    max_retries_rate_limit=7,
                    max_retries_format=3,
                )
                cfg.save()
                self.assertTrue((home_dir / "config.json").is_file())

                loaded = AppConfig.load()
                self.assertEqual(loaded.base_urls["OpenAI"], "https://proxy.example/v1")
                self.assertAlmostEqual(loaded.temperature, 0.45)
                self.assertFalse(loaded.strict_json_mode)
                self.assertAlmostEqual(loaded.request_timeout, 75.0)
                self.assertAlmostEqual(loaded.model_fetch_timeout, 18.0)
                self.assertEqual(loaded.batch_size, 40)
                self.assertEqual(loaded.batch_max_chars, 5200)
                self.assertEqual(loaded.section_max_chars, 4800)
                self.assertEqual(loaded.max_concurrent_requests, 12)
                self.assertAlmostEqual(loaded.min_request_interval, 0.15)
                self.assertEqual(loaded.max_retries_general, 4)
                self.assertEqual(loaded.max_retries_rate_limit, 7)
                self.assertEqual(loaded.max_retries_format, 3)

                # Config base_url wins over env var; blank falls back to env var
                with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://env.example/v1", "GEMINI_BASE_URL": "https://gem.env"}, clear=False):
                    self.assertEqual(loaded.get_effective_base_url("OpenAI"), "https://proxy.example/v1")
                    self.assertEqual(loaded.get_effective_base_url("Gemini"), "https://gem.env")

                model_fetcher.save_cached_models("Gemini", ["gemini-2.5-flash"])
                self.assertTrue((home_dir / "models_cache.json").is_file())
                self.assertEqual(model_fetcher.load_cached_models("Gemini"), ["gemini-2.5-flash"])

                tc = TranslationCache()
                self.assertEqual(tc.db_path, home_dir.resolve() / "cache.db")

    def test_rate_limit_presets_rpm_tpm_and_cache_resume_i18n(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import config as config_mod
        from config import RATE_LIMIT_PRESETS

        cfg = AppConfig()
        self.assertEqual(cfg.rate_limit_preset, "balanced")
        self.assertEqual(cfg.rpm_limit, 45)
        self.assertEqual(cfg.batch_size, 100)
        self.assertEqual(cfg.batch_max_chars, 12000)
        self.assertEqual(cfg.section_max_chars, 12000)

        cfg.apply_rate_limit_preset("safe_free")
        self.assertEqual(cfg.rate_limit_preset, "safe_free")
        self.assertEqual(cfg.max_concurrent_requests, RATE_LIMIT_PRESETS["safe_free"]["max_concurrent_requests"])
        self.assertEqual(cfg.rpm_limit, 12)
        self.assertEqual(cfg.tpm_limit, 100000)
        self.assertEqual(cfg.batch_size, 100)
        self.assertEqual(cfg.batch_max_chars, 12000)
        self.assertEqual(cfg.section_max_chars, 12000)
        self.assertEqual(cfg.detect_rate_limit_preset(), "safe_free")

        cfg.rpm_limit = 33
        self.assertEqual(cfg.detect_rate_limit_preset(), "custom")

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_dir = Path(tmpdir)
            cfg_file = cfg_dir / "config.json"
            with patch.object(config_mod, "CONFIG_DIR", cfg_dir), patch.object(config_mod, "CONFIG_FILE", cfg_file):
                cfg.save()
                reloaded = AppConfig.load()
                self.assertEqual(reloaded.rpm_limit, 33)
                self.assertEqual(reloaded.tpm_limit, 100000)
                self.assertEqual(reloaded.rate_limit_preset, "custom")

                # Unmodified legacy preset config auto-upgrades on load
                import json
                from config import _LEGACY_RATE_LIMIT_PRESETS, _PREVIOUS_RATE_LIMIT_PRESETS
                legacy_balanced = dict(_LEGACY_RATE_LIMIT_PRESETS["balanced"])
                legacy_balanced["rate_limit_preset"] = "balanced"
                cfg_file.write_text(json.dumps(legacy_balanced), encoding="utf-8")
                upgraded = AppConfig.load()
                self.assertEqual(upgraded.rate_limit_preset, "balanced")
                self.assertEqual(upgraded.batch_size, RATE_LIMIT_PRESETS["balanced"]["batch_size"])
                self.assertEqual(upgraded.batch_max_chars, RATE_LIMIT_PRESETS["balanced"]["batch_max_chars"])
                self.assertEqual(upgraded.section_max_chars, RATE_LIMIT_PRESETS["balanced"]["section_max_chars"])

                prev_safe_free = dict(_PREVIOUS_RATE_LIMIT_PRESETS["safe_free"])
                prev_safe_free["rate_limit_preset"] = "safe_free"
                cfg_file.write_text(json.dumps(prev_safe_free), encoding="utf-8")
                upgraded_free = AppConfig.load()
                self.assertEqual(upgraded_free.rate_limit_preset, "safe_free")
                self.assertEqual(upgraded_free.batch_size, RATE_LIMIT_PRESETS["safe_free"]["batch_size"])
                self.assertEqual(upgraded_free.batch_max_chars, RATE_LIMIT_PRESETS["safe_free"]["batch_max_chars"])
                self.assertEqual(upgraded_free.section_max_chars, RATE_LIMIT_PRESETS["safe_free"]["section_max_chars"])

                # User-customized config with old batch_size=25 must NOT be overwritten
                custom_legacy = dict(_LEGACY_RATE_LIMIT_PRESETS["balanced"])
                custom_legacy["batch_max_chars"] = 4500
                custom_legacy["rate_limit_preset"] = "custom"
                cfg_file.write_text(json.dumps(custom_legacy), encoding="utf-8")
                preserved = AppConfig.load()
                self.assertEqual(preserved.batch_size, 25)
                self.assertEqual(preserved.batch_max_chars, 4500)
                self.assertEqual(preserved.rate_limit_preset, "custom")

        for lang in ("en", "ja", "vi"):
            advice = I18nManager(lang).t("err_diag_quota_advice").lower()
            self.assertTrue(
                ("cache" in advice) or ("キャッシュ" in advice),
                f"Expected cache resume hint in {lang} err_diag_quota_advice: {advice}",
            )


if __name__ == "__main__":
    unittest.main()
