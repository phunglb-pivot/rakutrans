"""
Unit tests for MarkdownTranslator chunking and structure preservation.
"""

import tempfile
import unittest
from pathlib import Path

from rakutrans.core.config import AppConfig
from rakutrans.parsers.markdown_parser import MarkdownTranslator


class MockLLMManager:
    def __init__(self):
        self.call_count = 0

    def translate_markdown_text(self, markdown_text, *args, **kwargs):
        self.call_count += 1
        target_lang = kwargs.get("target_lang")
        if args:
            if len(args) >= 2 and isinstance(args[1], str):
                target_lang = args[1]
            elif len(args) >= 1 and isinstance(args[0], str):
                target_lang = args[0]
        tgt = target_lang or "target"
        return f"[Translated in {tgt}]\n" + markdown_text


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
        from rakutrans.llm.translation_cache import TranslationCache
        config = AppConfig()
        mock_llm = MockLLMManager()
        translator = MarkdownTranslator(config, mock_llm, cache=TranslationCache(db_path=Path(self.temp_dir.name) / "md_cache.db"))

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
        from rakutrans.llm.translation_cache import TranslationCache
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

    def test_chunking_preserves_code_blocks_and_large_tables(self):
        config = AppConfig()
        from rakutrans.llm.translation_cache import TranslationCache
        translator = MarkdownTranslator(
            config,
            MockLLMManager(),
            cache=TranslationCache(db_path=Path(self.temp_dir.name) / "md_chunk_init.db"),
        )

        # Fenced code block containing blank lines must not be split across chunks
        code_md = (
            "# Title\n\n"
            + ("Intro paragraph.\n\n" * 80)
            + "```python\ndef f1():\n    return 1\n\ndef f2():\n    return 2\n```\n\n"
            + "Tail paragraph."
        )
        chunks = [c for c, _ in translator._split_into_chunk_specs(code_md, max_chars=800)]
        fence_chunks = [c for c in chunks if "```python" in c]
        self.assertEqual(len(fence_chunks), 1)
        self.assertIn("def f2():", fence_chunks[0])
        self.assertIn("\n```", fence_chunks[0])

        # Oversized table splits at row boundaries and reassembles without '\n\n' gaps
        rows = ["| Col1 | Col2 |", "| --- | --- |"] + [f"| R{i} | {'x' * 120} |" for i in range(40)]
        table_md = "# Data\n\n" + "\n".join(rows) + "\n"
        big_md_path = Path(self.temp_dir.name) / "big_table.md"
        big_md_path.write_text(table_md, encoding="utf-8")

        class _PassthroughMock:
            def translate_markdown_text(self, markdown_text, *args, **kwargs):
                return markdown_text

        tr_pass = MarkdownTranslator(
            config,
            _PassthroughMock(),
            cache=TranslationCache(db_path=Path(self.temp_dir.name) / "md_chunk_cache.db"),
        )
        out_path = tr_pass.process_file(file_path=str(big_md_path), target_lang="Vietnamese")
        out_text = Path(out_path).read_text(encoding="utf-8")
        self.assertEqual(out_text, table_md)

    def test_markdown_requires_explicit_model_and_caches_per_model(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from rakutrans.core import config as config_mod
        from rakutrans.llm import model_fetcher
        from rakutrans.llm.llm_manager import LLMError, LLMManager
        from rakutrans.llm.translation_cache import TranslationCache

        tmp_path = Path(self.temp_dir.name)
        with patch.object(config_mod, "CONFIG_DIR", tmp_path), \
             patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"), \
             patch.object(model_fetcher, "CACHE_DIR", tmp_path), \
             patch.object(model_fetcher, "MODELS_CACHE_FILE", tmp_path / "models_cache.json"):
            cfg = AppConfig()
            cfg.active_provider = "OpenAI"
            cfg.api_keys["OpenAI"] = "sk-test"
            cfg.selected_models["OpenAI"] = ""
            mgr = LLMManager(cfg)
            calls = {"count": 0}

            def _complete(sys_p, usr_p, model_name, is_json=False):
                calls["count"] += 1
                return f"[VI]\n{usr_p}"

            mgr._get_client = lambda: SimpleNamespace(generate_completion=_complete)
            cache = TranslationCache(db_path=tmp_path / "md_first_run.db")
            tr = MarkdownTranslator(cfg, mgr, cache=cache)

            with self.assertRaises(LLMError):
                tr.process_file(file_path=str(self.test_md_path), target_lang="Vietnamese")
            self.assertEqual(calls["count"], 0)

            cfg.selected_models["OpenAI"] = "gpt-live-1"
            tr.process_file(file_path=str(self.test_md_path), target_lang="Vietnamese")
            first_calls = calls["count"]
            self.assertGreater(first_calls, 0)
            tr.process_file(file_path=str(self.test_md_path), target_lang="Vietnamese")
            self.assertEqual(calls["count"], first_calls)

    def test_inline_backticks_leading_blanks_and_code_only_chunk_skipped(self):
        from rakutrans.llm.translation_cache import TranslationCache

        md_doc = (
            "\n\n"
            "```inline_var``` is described here.\n\n"
            + ("Paragraph filler.\n\n" * 40)
            + "```python\ndef only_code():\n    return 42\n```\n\n"
            + "Closing prose line.\n"
        )
        md_path = Path(self.temp_dir.name) / "edge_fence.md"
        md_path.write_text(md_doc, encoding="utf-8")

        seen_chunks = []

        class _SpyMD:
            def translate_markdown_text(self, markdown_text, *args, **kwargs):
                seen_chunks.append(markdown_text)
                return f"[TR]\n{markdown_text}"

        tr = MarkdownTranslator(
            AppConfig(),
            _SpyMD(),
            cache=TranslationCache(db_path=Path(self.temp_dir.name) / "md_edge.db"),
        )
        specs = tr._split_into_chunk_specs(md_doc, max_chars=400)
        self.assertTrue(specs[0][1].startswith("\n\n"))

        out_path = tr.process_file(file_path=str(md_path), target_lang="Vietnamese")
        out_text = Path(out_path).read_text(encoding="utf-8")
        self.assertIn("[TR]\n", out_text)
        self.assertIn("Closing prose line.", out_text)
        self.assertFalse(any(c.strip().startswith("```python") and "only_code" in c and "Paragraph" not in c and "Closing" not in c for c in seen_chunks))
        self.assertIn("def only_code():", out_text)

    def test_large_code_fence_isolated_even_in_short_doc_and_long_prose_line_splits(self):
        from rakutrans.llm.translation_cache import TranslationCache

        large_code = "```python\n" + "\n".join(f"def helper_{i}(x):\n    return x + {i}" for i in range(15)) + "\n```"
        short_doc_with_big_code = f"# Intro\n\nPlease review the snippet below.\n\n{large_code}\n\nConclusion text.\n"
        md_path = Path(self.temp_dir.name) / "isolated_code.md"
        md_path.write_text(short_doc_with_big_code, encoding="utf-8")

        seen_chunks = []

        class _SpyLLM:
            def translate_markdown_text(self, markdown_text, *args, **kwargs):
                seen_chunks.append(markdown_text)
                return f"[VI] {markdown_text}"

        tr = MarkdownTranslator(
            AppConfig(section_max_chars=6000),
            _SpyLLM(),
            cache=TranslationCache(db_path=Path(self.temp_dir.name) / "md_iso.db"),
        )
        out_path = tr.process_file(file_path=str(md_path), target_lang="Vietnamese")
        out_text = Path(out_path).read_text(encoding="utf-8")

        # Large code fence must NOT be sent to LLM at all, prose around it is coalesced into 1 call, and code is preserved verbatim
        self.assertEqual(len(seen_chunks), 1)
        self.assertTrue(all("def helper_0" not in c for c in seen_chunks))
        self.assertIn("<<<RAKUTRANS_CODE_0>>>", seen_chunks[0])
        self.assertIn(large_code, out_text)
        self.assertIn("[VI] # Intro", out_text)
        self.assertIn("Conclusion text.", out_text)

        # Single unwrapped prose line > max_chars splits cleanly along whitespace
        long_line_md = "word " * 300
        line_specs = tr._split_into_chunk_specs(long_line_md, max_chars=400)
        self.assertGreater(len(line_specs), 1)
        self.assertTrue(all(len(c) <= 400 for c, _ in line_specs))
        self.assertEqual("".join(c + s for c, s in line_specs), long_line_md)

    def test_interleaved_code_blocks_coalesced_and_cached(self):
        from rakutrans.llm.translation_cache import TranslationCache

        blocks = []
        code_blocks = []
        for i in range(10):
            code = "```python\n" + "\n".join(f"def fn_{i}_{j}(v):\n    return v + {j}" for j in range(10)) + "\n```"
            code_blocks.append(code)
            blocks.append(f"## Section {i}\n\nExplanation for step {i}.\n\n{code}")
        blocks.append("Final summary line.")
        doc_text = "\n\n".join(blocks) + "\n"

        md_path = Path(self.temp_dir.name) / "many_code_blocks.md"
        md_path.write_text(doc_text, encoding="utf-8")

        seen_chunks = []

        class _LinePrefixSpy:
            def translate_markdown_text(self, markdown_text, *args, **kwargs):
                seen_chunks.append(markdown_text)
                out_lines = []
                for ln in markdown_text.splitlines(keepends=True):
                    stripped = ln.strip()
                    if stripped.startswith("<<<") and stripped.endswith(">>>"):
                        # Simulate occasional accidental inline backtick wrapping by LLM
                        out_lines.append(f"`{stripped}`" + ln[len(ln.rstrip("\r\n")):])
                    elif stripped:
                        out_lines.append(f"[VI] {ln}")
                    else:
                        out_lines.append(ln)
                return "".join(out_lines)

        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "md_interleaved.db")
        tr = MarkdownTranslator(AppConfig(section_max_chars=8000), _LinePrefixSpy(), cache=cache)

        out_path = tr.process_file(file_path=str(md_path), target_lang="Vietnamese")
        out_text = Path(out_path).read_text(encoding="utf-8")

        # 10 interleaved code blocks + 11 prose sections fit into 1 single API call
        self.assertEqual(len(seen_chunks), 1)
        for i, code in enumerate(code_blocks):
            self.assertNotIn(f"fn_{i}_0", seen_chunks[0])
            self.assertIn(code, out_text)
            self.assertIn(f"[VI] ## Section {i}", out_text)
        self.assertIn("[VI] Final summary line.", out_text)

        # Second run hits cache 100% with 0 additional calls
        calls_before = len(seen_chunks)
        tr.process_file(file_path=str(md_path), target_lang="Vietnamese")
        self.assertEqual(len(seen_chunks), calls_before)

    def test_placeholder_corruption_falls_back_cleanly_without_poisoning_cache(self):
        from rakutrans.llm.translation_cache import TranslationCache

        code1 = "```python\n" + "\n".join(f"val_{i} = {i} * 2" for i in range(15)) + "\n```"
        doc_text = f"# First\n\nAlpha paragraph.\n\n{code1}\n\nBeta paragraph.\n"
        md_path = Path(self.temp_dir.name) / "fallback_code.md"
        md_path.write_text(doc_text, encoding="utf-8")

        seen_chunks = []

        class _BadPlaceholderLLM:
            def translate_markdown_text(self, markdown_text, *args, **kwargs):
                seen_chunks.append(markdown_text)
                if "<<<RAKUTRANS_CODE_" in markdown_text:
                    # Simulate model accidentally dropping the placeholder token
                    return markdown_text.replace("<<<RAKUTRANS_CODE_0>>>", "")
                return "\n".join(f"[VI] {ln}" if ln.strip() else ln for ln in markdown_text.splitlines())

        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "md_fallback.db")
        tr = MarkdownTranslator(AppConfig(section_max_chars=8000), _BadPlaceholderLLM(), cache=cache)

        out_path = tr.process_file(file_path=str(md_path), target_lang="Vietnamese")
        out_text = Path(out_path).read_text(encoding="utf-8")

        # 1 failed masked attempt + 2 clean unmasked sub-chunk fallback calls
        self.assertEqual(len(seen_chunks), 3)
        self.assertIn(code1, out_text)
        self.assertIn("[VI] # First", out_text)
        self.assertIn("[VI] Beta paragraph.", out_text)

        # Corrupted masked entry was NOT saved to cache; valid fallback sub-chunks WERE cached
        calls_before = len(seen_chunks)
        out_path_2 = tr.process_file(file_path=str(md_path), target_lang="Vietnamese")
        out_text_2 = Path(out_path_2).read_text(encoding="utf-8")
        self.assertIn(code1, out_text_2)
        self.assertEqual(len(seen_chunks), calls_before + 1)

    def test_placeholder_prefix_avoids_collision_with_source_text(self):
        from rakutrans.llm.translation_cache import TranslationCache

        code1 = "```python\n" + "\n".join(f"row_{i} = {i}" for i in range(15)) + "\n```"
        doc_text = (
            "Literal token <<<RAKUTRANS_CODE_0>>> in prose.\n\n"
            f"{code1}\n\n"
            "Trailing line.\n"
        )
        md_path = Path(self.temp_dir.name) / "collision_code.md"
        md_path.write_text(doc_text, encoding="utf-8")

        seen_chunks = []

        class _PassthroughSpy:
            def translate_markdown_text(self, markdown_text, *args, **kwargs):
                seen_chunks.append(markdown_text)
                return markdown_text.replace("Trailing line.", "[VI] Trailing line.")

        cache = TranslationCache(db_path=Path(self.temp_dir.name) / "md_collision.db")
        tr = MarkdownTranslator(AppConfig(section_max_chars=8000), _PassthroughSpy(), cache=cache)

        out_path = tr.process_file(file_path=str(md_path), target_lang="Vietnamese")
        out_text = Path(out_path).read_text(encoding="utf-8")

        self.assertEqual(len(seen_chunks), 1)
        self.assertIn("<<<XRAKUTRANS_CODE_0>>>", seen_chunks[0])
        self.assertIn("Literal token <<<RAKUTRANS_CODE_0>>> in prose.", out_text)
        self.assertIn(code1, out_text)
        self.assertIn("[VI] Trailing line.", out_text)


if __name__ == "__main__":
    unittest.main()

