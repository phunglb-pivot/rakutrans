"""
Unit tests for data format parsers: CsvTranslator, JsonTranslator, and TextTranslator.
"""

import json
import tempfile
import unittest
from pathlib import Path

from config import AppConfig
from data_parser import CsvTranslator, JsonTranslator, TextTranslator
from translation_cache import TranslationCache


class MockLLMManager:
    def __init__(self):
        self.call_count = 0

    def translate_batch(self, texts, target_lang="Vietnamese", *args, **kwargs):
        self.call_count += 1
        return [f"[{target_lang}] {t}" for t in texts]

    def translate_markdown_text(self, markdown_text, target_lang="Vietnamese", *args, **kwargs):
        self.call_count += 1
        return f"[{target_lang}] {markdown_text}"


class TestDataParsers(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # CSV / TSV Tests
    # -------------------------------------------------------------------------

    def test_csv_translation(self):
        csv_file = self.dir_path / "products.csv"
        csv_content = (
            "ID,Product Name,Category,Price\n"
            "1,Wireless Mouse,Electronics,25.99\n"
            "2,Mechanical Keyboard,Electronics,89.50\n"
        )
        csv_file.write_text(csv_content, encoding="utf-8")

        info = CsvTranslator.inspect_file(str(csv_file))
        self.assertEqual(info["type"], "csv")
        self.assertEqual(info["rows"], 3)
        self.assertEqual(info["columns"], 4)
        self.assertGreater(info["translatable_cells"], 0)

        config = AppConfig()
        mock_llm = MockLLMManager()
        translator = CsvTranslator(config, mock_llm)

        out_path = translator.process_file(str(csv_file), target_lang="Vietnamese")
        self.assertTrue(Path(out_path).exists())
        self.assertEqual(Path(out_path).name, "products_vi.csv")

        content = Path(out_path).read_text(encoding="utf-8-sig")
        self.assertIn("[Vietnamese] Product Name", content)
        self.assertIn("[Vietnamese] Wireless Mouse", content)
        # Verify numbers are preserved untouched
        self.assertIn("25.99", content)
        self.assertIn("89.50", content)

    def test_tsv_translation(self):
        tsv_file = self.dir_path / "data.tsv"
        tsv_content = "Name\tRole\nAlice\tEngineer\nBob\tDesigner\n"
        tsv_file.write_text(tsv_content, encoding="utf-8")

        config = AppConfig()
        mock_llm = MockLLMManager()
        translator = CsvTranslator(config, mock_llm)

        out_path = translator.process_file(str(tsv_file), target_lang="Vietnamese")
        self.assertEqual(Path(out_path).name, "data_vi.tsv")
        content = Path(out_path).read_text(encoding="utf-8-sig")
        self.assertIn("[Vietnamese] Engineer", content)
        self.assertIn("\t", content)

    # -------------------------------------------------------------------------
    # JSON Localization Tests
    # -------------------------------------------------------------------------

    def test_json_translation_preserves_keys_and_tokens(self):
        json_file = self.dir_path / "en.json"
        json_data = {
            "app_title": "Storefront",
            "version": 2.5,
            "is_active": True,
            "messages": {
                "welcome": "Welcome back, {user}!",
                "items_count": "You have %d items in your cart."
            },
            "tags": ["Electronics", "Computers"]
        }
        json_file.write_text(json.dumps(json_data, indent=2), encoding="utf-8")

        info = JsonTranslator.inspect_file(str(json_file))
        self.assertEqual(info["type"], "json")
        self.assertEqual(info["total_keys"], 7)
        self.assertGreater(info["translatable_strings"], 0)

        config = AppConfig()
        mock_llm = MockLLMManager()
        translator = JsonTranslator(config, mock_llm)

        out_path = translator.process_file(str(json_file), target_lang="Vietnamese")
        self.assertEqual(Path(out_path).name, "en_vi.json")

        with open(out_path, "r", encoding="utf-8") as f:
            res_data = json.load(f)

        # Keys MUST NOT be translated
        self.assertIn("app_title", res_data)
        self.assertIn("messages", res_data)
        self.assertIn("welcome", res_data["messages"])
        # Non-string values MUST be intact
        self.assertEqual(res_data["version"], 2.5)
        self.assertIs(res_data["is_active"], True)
        # Strings are translated
        self.assertEqual(res_data["app_title"], "[Vietnamese] Storefront")
        self.assertIn("[Vietnamese] Welcome back, {user}!", res_data["messages"]["welcome"])
        self.assertEqual(res_data["tags"][0], "[Vietnamese] Electronics")

    # -------------------------------------------------------------------------
    # Plain Text Tests
    # -------------------------------------------------------------------------

    def test_text_translation(self):
        txt_file = self.dir_path / "notes.txt"
        txt_content = "First paragraph of instructions.\n\nSecond paragraph with details."
        txt_file.write_text(txt_content, encoding="utf-8")

        info = TextTranslator.inspect_file(str(txt_file))
        self.assertEqual(info["type"], "txt")
        self.assertEqual(info["line_count"], 3)
        self.assertGreater(info["word_count"], 0)

        config = AppConfig()
        mock_llm = MockLLMManager()
        translator = TextTranslator(config, mock_llm)

        out_path = translator.process_file(str(txt_file), target_lang="Vietnamese")
        self.assertEqual(Path(out_path).name, "notes_vi.txt")

        content = Path(out_path).read_text(encoding="utf-8")
        self.assertIn("[Vietnamese] First paragraph of instructions.", content)
        self.assertIn("Second paragraph with details.", content)


if __name__ == "__main__":
    unittest.main()
