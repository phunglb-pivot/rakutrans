"""
Unit tests for model_fetcher.py
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import model_fetcher
from model_fetcher import (
    _is_valid_text_model,
    _sort_models,
    load_cached_models,
    save_cached_models,
    fetch_live_models,
    SEED_MODELS
)


class TestModelFetcher(unittest.TestCase):

    def test_filter_gemini_models(self):
        # Valid text models
        self.assertTrue(_is_valid_text_model("gemini-3.6-flash", "Gemini"))
        self.assertTrue(_is_valid_text_model("gemini-flash-latest", "Gemini"))
        self.assertTrue(_is_valid_text_model("gemini-pro-latest", "Gemini"))
        self.assertTrue(_is_valid_text_model("gemini-2.0-flash-lite", "Gemini"))

        # Non-text or specialized models to exclude
        self.assertFalse(_is_valid_text_model("text-embedding-004", "Gemini"))
        self.assertFalse(_is_valid_text_model("imagen-3.0-generate-002", "Gemini"))
        self.assertFalse(_is_valid_text_model("lyria-3-clip-preview", "Gemini"))
        self.assertFalse(_is_valid_text_model("aqa", "Gemini"))

    def test_filter_openai_models(self):
        # Valid models
        self.assertTrue(_is_valid_text_model("gpt-4o", "OpenAI"))
        self.assertTrue(_is_valid_text_model("gpt-4o-mini", "OpenAI"))
        self.assertTrue(_is_valid_text_model("o3-mini", "OpenAI"))
        self.assertTrue(_is_valid_text_model("o1", "OpenAI"))
        self.assertTrue(_is_valid_text_model("chatgpt-4o-latest", "OpenAI"))

        # Excluded models
        self.assertFalse(_is_valid_text_model("dall-e-3", "OpenAI"))
        self.assertFalse(_is_valid_text_model("whisper-1", "OpenAI"))
        self.assertFalse(_is_valid_text_model("tts-1", "OpenAI"))
        self.assertFalse(_is_valid_text_model("text-embedding-3-small", "OpenAI"))
        self.assertFalse(_is_valid_text_model("davinci-002", "OpenAI"))

    def test_filter_claude_models(self):
        self.assertTrue(_is_valid_text_model("claude-3-7-sonnet-latest", "Claude"))
        self.assertTrue(_is_valid_text_model("claude-3-5-haiku-latest", "Claude"))
        self.assertFalse(_is_valid_text_model("random-model", "Claude"))

    def test_sort_models(self):
        gemini_raw = ["gemini-pro-latest", "gemini-3.6-flash", "gemini-3.7-pro", "gemini-flash-latest"]
        sorted_gemini = _sort_models(gemini_raw, "Gemini")
        # Flash models should be prioritized before non-flash
        flash_indices = [i for i, m in enumerate(sorted_gemini) if "flash" in m]
        non_flash_indices = [i for i, m in enumerate(sorted_gemini) if "flash" not in m]
        self.assertTrue(max(flash_indices) < min(non_flash_indices))

    def test_cache_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache_file = Path(tmpdir) / "test_models_cache.json"
            with patch.object(model_fetcher, "MODELS_CACHE_FILE", test_cache_file), \
                 patch.object(model_fetcher, "CACHE_DIR", Path(tmpdir)):
                
                # Initially loads seed models
                seeds = load_cached_models("Gemini")
                self.assertEqual(seeds, SEED_MODELS["Gemini"])

                # Save custom models
                custom = ["gemini-custom-flash", "gemini-custom-pro"]
                save_cached_models("Gemini", custom)

                # Now loads cached models
                loaded = load_cached_models("Gemini")
                self.assertEqual(loaded, custom)

    def test_empty_api_key_fallback(self):
        # When key is empty, fetch_live_models returns cached or seed models without error
        res = fetch_live_models("Gemini", "")
        self.assertIsInstance(res, list)
        self.assertTrue(len(res) > 0)


if __name__ == "__main__":
    unittest.main()
