"""
Unit tests for TranslationCache (SQLite Translation Memory).
"""

import tempfile
import unittest
from pathlib import Path

from config import TranslationOptions
from translation_cache import TranslationCache


class TestTranslationCache(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_cache.db"
        self.cache = TranslationCache(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cache_miss_and_hit(self):
        texts = ["Apple", "Banana", "Cherry"]
        opts = TranslationOptions(keep_it_terms=True, append_original_words=False)

        # 1. Initial lookup -> 100% cache miss
        cached_map, uncached = self.cache.get_batch(texts, "English", "Vietnamese", opts)
        self.assertEqual(len(cached_map), 0)
        self.assertEqual(len(uncached), 3)

        # 2. Save translations
        translated = ["Quả táo", "Quả chuối", "Quả anh đào"]
        self.cache.save_batch(texts, translated, "English", "Vietnamese", opts)

        # 3. Subsequent lookup -> 100% cache hit
        cached_map, uncached = self.cache.get_batch(texts, "English", "Vietnamese", opts)
        self.assertEqual(len(cached_map), 3)
        self.assertEqual(len(uncached), 0)
        self.assertEqual(cached_map[0], "Quả táo")
        self.assertEqual(cached_map[1], "Quả chuối")
        self.assertEqual(cached_map[2], "Quả anh đào")

    def test_partial_cache_hit(self):
        opts = TranslationOptions()
        self.cache.save_batch(["Hello"], ["Xin chào"], "English", "Vietnamese", opts)

        cached_map, uncached = self.cache.get_batch(
            ["Hello", "Goodbye"], "English", "Vietnamese", opts
        )
        self.assertEqual(len(cached_map), 1)
        self.assertEqual(cached_map[0], "Xin chào")
        self.assertEqual(len(uncached), 1)
        self.assertEqual(uncached[0], (1, "Goodbye"))

    def test_options_hash_isolation(self):
        texts = ["Server"]
        opts1 = TranslationOptions(append_original_words=False)
        opts2 = TranslationOptions(append_original_words=True)

        self.cache.save_batch(texts, ["Máy chủ"], "English", "Vietnamese", opts1)

        # Lookup with opts1 -> Hit
        hit, _ = self.cache.get_batch(texts, "English", "Vietnamese", opts1)
        self.assertEqual(len(hit), 1)

        # Lookup with opts2 -> Miss (different translation output expected)
        miss, _ = self.cache.get_batch(texts, "English", "Vietnamese", opts2)
        self.assertEqual(len(miss), 0)

    def test_count_and_clear(self):
        opts = TranslationOptions()
        self.assertEqual(self.cache.count(), 0)

        self.cache.save_batch(["A", "B", "C"], ["1", "2", "3"], "EN", "VI", opts)
        self.assertEqual(self.cache.count(), 3)

        self.cache.clear()
        self.assertEqual(self.cache.count(), 0)


if __name__ == "__main__":
    unittest.main()
