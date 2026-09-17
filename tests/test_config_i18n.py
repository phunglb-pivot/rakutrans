"""
Unit tests for configuration and i18n localization.
"""

import unittest
from config import AppConfig, TranslationOptions, SUPPORTED_LANGUAGES
from i18n import I18nManager, TRANSLATIONS


class TestConfigAndI18n(unittest.TestCase):
    
    def test_default_config(self):
        config = AppConfig()
        self.assertEqual(config.ui_language, "en")
        self.assertEqual(config.active_provider, "Gemini")
        self.assertTrue(config.translation_options.keep_it_terms)
        self.assertFalse(config.translation_options.append_original_words)
        self.assertEqual(config.target_language, "Vietnamese")
        self.assertIsNone(config.source_language)

    def test_i18n_all_languages(self):
        # Verify that all 3 languages exist in SUPPORTED_LANGUAGES
        self.assertIn("en", SUPPORTED_LANGUAGES)
        self.assertIn("ja", SUPPORTED_LANGUAGES)
        self.assertIn("vi", SUPPORTED_LANGUAGES)

        # Verify key consistency across languages
        en_keys = set(TRANSLATIONS["en"].keys())
        ja_keys = set(TRANSLATIONS["ja"].keys())
        vi_keys = set(TRANSLATIONS["vi"].keys())

        # All languages should have identical translation keys
        self.assertEqual(en_keys, ja_keys, "JA missing keys from EN")
        self.assertEqual(en_keys, vi_keys, "VI missing keys from EN")

        # Test I18nManager lookup
        manager = I18nManager("ja")
        self.assertEqual(manager.t("app_title"), "RakuTrans AI")
        self.assertIn("翻訳", manager.t("start_translation"))
        manager.set_language("vi")
        self.assertIn("dịch", manager.t("start_translation").lower())
        self.assertNotIn("offline", manager.t("convert_subtitle").lower())
        self.assertNotIn("không dùng ai", manager.t("convert_subtitle").lower())

    def test_smart_output_naming(self):
        import tempfile
        from pathlib import Path
        from config import get_smart_output_path, get_target_lang_code

        self.assertEqual(get_target_lang_code("Vietnamese"), "vi")
        self.assertEqual(get_target_lang_code("English"), "en")
        self.assertEqual(get_target_lang_code("Japanese"), "ja")

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


if __name__ == "__main__":
    unittest.main()
