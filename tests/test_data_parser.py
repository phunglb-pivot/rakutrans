"""
Unit tests for data format parsers: CsvTranslator, JsonTranslator, and TextTranslator.
"""

import json
import tempfile
import unittest
from pathlib import Path

from config import AppConfig
from data_parser import CsvTranslator, JsonTranslator, TextTranslator


class MockLLMManager:
    def __init__(self):
        self.call_count = 0

    def translate_batch(self, texts, target_lang=None, *args, **kwargs):
        self.call_count += 1
        tgt = target_lang or "target"
        return [f"[{tgt}] {t}" for t in texts]

    def translate_markdown_text(self, markdown_text, target_lang=None, *args, **kwargs):
        self.call_count += 1
        tgt = target_lang or "target"
        return f"[{tgt}] {markdown_text}"


class TestDataParsers(unittest.TestCase):

    def setUp(self):
        from translation_cache import TranslationCache
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.cache = TranslationCache(db_path=self.dir_path / "test_data_cache.db")

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
        translator = CsvTranslator(config, mock_llm, cache=self.cache)

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
        translator = CsvTranslator(config, mock_llm, cache=self.cache)

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
        translator = JsonTranslator(config, mock_llm, cache=self.cache)

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
        translator = TextTranslator(config, mock_llm, cache=self.cache)

        out_path = translator.process_file(str(txt_file), target_lang="Vietnamese")
        self.assertEqual(Path(out_path).name, "notes_vi.txt")

        content = Path(out_path).read_text(encoding="utf-8")
        self.assertIn("[Vietnamese] First paragraph of instructions.", content)
        self.assertIn("Second paragraph with details.", content)

    def test_text_passes_plain_text_flag_and_isolates_cache_options(self):
        from config import TranslationOptions
        from translation_cache import TranslationCache

        seen_plain_flags = []

        class _SpyLLM(MockLLMManager):
            def translate_markdown_text(self, markdown_text, target_lang=None, *args, **kwargs):
                seen_plain_flags.append(kwargs.get("plain_text"))
                return super().translate_markdown_text(markdown_text, target_lang=target_lang, *args, **kwargs)

        txt_file = self.dir_path / "plain.txt"
        txt_file.write_text("# Not a heading\n\nPlain body line.", encoding="utf-8")

        cache = TranslationCache(db_path=self.dir_path / "data_cache.db")
        spy = _SpyLLM()
        t1 = TextTranslator(AppConfig(translation_options=TranslationOptions(custom_context="A")), spy, cache=cache)
        t1.process_file(str(txt_file), target_lang="Vietnamese")
        self.assertEqual(seen_plain_flags, [True])
        calls_1 = spy.call_count

        # Different context option must NOT hit cache from context A
        t2 = TextTranslator(AppConfig(translation_options=TranslationOptions(custom_context="B")), spy, cache=cache)
        t2.process_file(str(txt_file), target_lang="Vietnamese")
        self.assertGreater(spy.call_count, calls_1)

    def test_text_requires_explicit_model_and_caches_per_model(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import config as config_mod
        import model_fetcher
        from llm_manager import LLMError, LLMManager
        from translation_cache import TranslationCache

        txt_file = self.dir_path / "first_run.txt"
        txt_file.write_text("Hello world.", encoding="utf-8")

        with patch.object(config_mod, "CONFIG_DIR", self.dir_path), \
             patch.object(config_mod, "CONFIG_FILE", self.dir_path / "config.json"), \
             patch.object(model_fetcher, "CACHE_DIR", self.dir_path), \
             patch.object(model_fetcher, "MODELS_CACHE_FILE", self.dir_path / "models_cache.json"):
            cfg = AppConfig()
            cfg.active_provider = "OpenAI"
            cfg.api_keys["OpenAI"] = "sk-test"
            cfg.selected_models["OpenAI"] = ""
            mgr = LLMManager(cfg)
            calls = {"count": 0}

            def _complete(sys_p, usr_p, model_name, is_json=False):
                calls["count"] += 1
                return f"VI:{usr_p}"

            mgr._get_client = lambda: SimpleNamespace(generate_completion=_complete)
            cache = TranslationCache(db_path=self.dir_path / "txt_first_run.db")
            tr = TextTranslator(cfg, mgr, cache=cache)

            # Empty selected model must fail explicitly instead of auto-fetching/picking models[0]
            with self.assertRaises(LLMError):
                tr.process_file(str(txt_file), target_lang="Vietnamese")
            self.assertEqual(calls["count"], 0)

            cfg.selected_models["OpenAI"] = "gpt-live-1"
            tr.process_file(str(txt_file), target_lang="Vietnamese")
            self.assertEqual(calls["count"], 1)
            tr.process_file(str(txt_file), target_lang="Vietnamese")
            self.assertEqual(calls["count"], 1)

    def test_single_row_semicolon_csv_deep_json_and_long_line_txt_split(self):
        # 1. Single-row semicolon CSV detection
        one_row_csv = self.dir_path / "one_row.csv"
        one_row_csv.write_text("Name;City;Role\n", encoding="utf-8")
        info = CsvTranslator.inspect_file(str(one_row_csv))
        self.assertEqual(info["delimiter"], ";")
        self.assertEqual(info["columns"], 3)

        # 2. Deeply nested JSON (>1200 levels) must not raise RecursionError
        deep_json = self.dir_path / "deep.json"
        nested: dict = {"leaf": "Hello deep world"}
        for _ in range(1200):
            nested = {"child": nested}
        deep_json.write_text(json.dumps(nested), encoding="utf-8")
        j_info = JsonTranslator.inspect_file(str(deep_json))
        self.assertEqual(j_info["translatable_strings"], 1)
        j_tr = JsonTranslator(AppConfig(), MockLLMManager(), cache=self.cache)
        out_json = j_tr.process_file(str(deep_json), target_lang="Vietnamese")
        self.assertIn("[Vietnamese] Hello deep world", Path(out_json).read_text(encoding="utf-8"))

        # 3. Single line > max_chars splits safely and reconstructs identically
        long_line = "word " * 1000
        chunks = TextTranslator._split_text_chunks(long_line, max_chars=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 500 for c, _ in chunks))
        self.assertEqual("".join(c + sep for c, sep in chunks), long_line)


if __name__ == "__main__":
    unittest.main()
