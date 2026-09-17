"""
Unit tests for MarkdownTranslator chunking and structure preservation.
"""

import tempfile
import unittest
from pathlib import Path

from config import AppConfig, TranslationOptions
from markdown_parser import MarkdownTranslator


class MockLLMManager:
    def __init__(self):
        self.call_count = 0

    def translate_markdown_text(self, markdown_text, *args, **kwargs):
        self.call_count += 1
        target_lang = kwargs.get("target_lang", "Vietnamese")
        if args:
            if len(args) >= 2 and isinstance(args[1], str):
                target_lang = args[1]
            elif len(args) >= 1 and isinstance(args[0], str):
                target_lang = args[0]
        return f"[Translated in {target_lang}]\n" + markdown_text


class TestMarkdownTranslator(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.test_md_path = Path(self.temp_dir.name) / "sample_doc.md"

        sample_content = """# Architecture Overview

This is an introductory paragraph explaining the service design.

## API Endpoints

```python
def get_user(user_id: int):
    return {"id": user_id, "name": "Alice"}
```

For more info, visit [Documentation](https://api.example.com).
"""
        with open(self.test_md_path, "w", encoding="utf-8") as f:
            f.write(sample_content)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_markdown_translation_flow(self):
        config = AppConfig()
        mock_llm = MockLLMManager()
        translator = MarkdownTranslator(config, mock_llm)

        out_path = translator.process_file(
            file_path=str(self.test_md_path),
            target_lang="Vietnamese"
        )

        self.assertTrue(Path(out_path).exists())
        self.assertEqual(Path(out_path).name, "sample_doc_vi.md")

        # Second translation run should increment: sample_doc_vi (1).md
        out_path_2 = translator.process_file(
            file_path=str(self.test_md_path),
            target_lang="Vietnamese"
        )
        self.assertEqual(Path(out_path_2).name, "sample_doc_vi (1).md")

        with open(out_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("[Translated in Vietnamese]", content)
        self.assertIn("def get_user(user_id: int):", content)
        self.assertIn("https://api.example.com", content)

    def test_markdown_caching(self):
        from translation_cache import TranslationCache
        cache_db = Path(self.temp_dir.name) / "test_cache.db"
        cache = TranslationCache(db_path=cache_db)

        config = AppConfig()
        mock_llm = MockLLMManager()
        translator = MarkdownTranslator(config, mock_llm, cache=cache)

        # 1st run: cache is empty, calls LLM
        translator.process_file(
            file_path=str(self.test_md_path),
            target_lang="Vietnamese"
        )
        first_calls = mock_llm.call_count
        self.assertGreater(first_calls, 0)

        # 2nd run: should hit cache 100%, call_count must NOT increase
        translator.process_file(
            file_path=str(self.test_md_path),
            target_lang="Vietnamese"
        )
        self.assertEqual(mock_llm.call_count, first_calls)

    def test_inspect_file(self):
        info = MarkdownTranslator.inspect_file(str(self.test_md_path))
        self.assertEqual(info["type"], "markdown")
        self.assertGreater(info["word_count"], 0)
        self.assertGreater(info["char_count"], 0)
        self.assertGreater(info["line_count"], 0)
        self.assertGreater(info["section_count"], 0)


if __name__ == "__main__":
    unittest.main()

