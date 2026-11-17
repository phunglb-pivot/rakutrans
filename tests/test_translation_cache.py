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
        cached_map, uncached = self.cache.get_batch(
            texts, target_lang="Vietnamese", options=opts, source_lang="English"
        )
        self.assertEqual(len(cached_map), 0)
        self.assertEqual(len(uncached), 3)

        # 2. Save translations
        translated = ["Quả táo", "Quả chuối", "Quả anh đào"]
        self.cache.save_batch(
            texts, translated, target_lang="Vietnamese", options=opts, source_lang="English"
        )

        # 3. Subsequent lookup -> 100% cache hit
        cached_map, uncached = self.cache.get_batch(
            texts, target_lang="Vietnamese", options=opts, source_lang="English"
        )
        self.assertEqual(len(cached_map), 3)
        self.assertEqual(len(uncached), 0)
        self.assertEqual(cached_map[0], "Quả táo")
        self.assertEqual(cached_map[1], "Quả chuối")
        self.assertEqual(cached_map[2], "Quả anh đào")

    def test_partial_cache_hit(self):
        opts = TranslationOptions()
        self.cache.save_batch(
            ["Hello"], ["Xin chào"], target_lang="Vietnamese", options=opts, source_lang="English"
        )

        cached_map, uncached = self.cache.get_batch(
            ["Hello", "Goodbye"], target_lang="Vietnamese", options=opts, source_lang="English"
        )
        self.assertEqual(len(cached_map), 1)
        self.assertEqual(cached_map[0], "Xin chào")
        self.assertEqual(len(uncached), 1)
        self.assertEqual(uncached[0], (1, "Goodbye"))

    def test_options_hash_isolation(self):
        texts = ["Server"]
        opts1 = TranslationOptions(append_original_words=False)
        opts2 = TranslationOptions(append_original_words=True)

        self.cache.save_batch(
            texts, ["Máy chủ"], target_lang="Vietnamese", options=opts1, source_lang="English"
        )

        # Lookup with opts1 -> Hit
        hit, _ = self.cache.get_batch(
            texts, target_lang="Vietnamese", options=opts1, source_lang="English"
        )
        self.assertEqual(len(hit), 1)

        # Lookup with opts2 -> Miss (different translation output expected)
        miss, _ = self.cache.get_batch(
            texts, target_lang="Vietnamese", options=opts2, source_lang="English"
        )
        self.assertEqual(len(miss), 0)

    def test_count_and_clear(self):
        opts = TranslationOptions()
        self.assertEqual(self.cache.count(), 0)

        self.cache.save_batch(
            ["A", "B", "C"], ["1", "2", "3"], target_lang="VI", options=opts, source_lang="EN"
        )
        self.assertEqual(self.cache.count(), 3)

        self.cache.clear()
        self.assertEqual(self.cache.count(), 0)

    def test_language_normalization_and_mode_model_isolation(self):
        opts = TranslationOptions()
        self.cache.save_batch(
            ["Hello"], ["Xin chào"], target_lang="vi", options=opts, source_lang="en", mode="batch", model_id="Gemini:m1"
        )
        # Alias target_lang/source_lang hits same entry
        hit, _ = self.cache.get_batch(
            ["Hello"], target_lang="Tiếng Việt (Vietnamese)", options=opts, source_lang="English", mode="batch", model_id="Gemini:m1"
        )
        self.assertEqual(hit, {0: "Xin chào"})

        # Different mode or model misses cleanly
        miss_mode, _ = self.cache.get_batch(
            ["Hello"], target_lang="Vietnamese", options=opts, source_lang="English", mode="markdown", model_id="Gemini:m1"
        )
        self.assertEqual(miss_mode, {})

        miss_model, _ = self.cache.get_batch(
            ["Hello"], target_lang="Vietnamese", options=opts, source_lang="English", mode="batch", model_id="OpenAI:gpt-4o"
        )
        self.assertEqual(miss_model, {})

    def test_large_batch_chunked_lookup(self):
        opts = TranslationOptions()
        src = [f"term_{i}" for i in range(950)]
        tgt = [f"dich_{i}" for i in range(950)]
        self.cache.save_batch(src, tgt, target_lang="Vietnamese", options=opts)
        hit, miss = self.cache.get_batch(src + ["term_new"], target_lang="vi", options=opts)
        self.assertEqual(len(hit), 950)
        self.assertEqual(miss, [(950, "term_new")])

    def test_concurrent_wal_saves_and_reads(self):
        import threading

        opts = TranslationOptions()
        errors = []

        def _worker(tid: int):
            try:
                for j in range(5):
                    key = f"src_{tid}_{j}"
                    val = f"tgt_{tid}_{j}"
                    self.cache.save_batch([key], [val], target_lang="Vietnamese", options=opts)
                    hit, _ = self.cache.get_batch([key], target_lang="Vietnamese", options=opts)
                    if hit.get(0) != val:
                        raise AssertionError(f"Expected {val}, got {hit}")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(self.cache.count(), 30)


if __name__ == "__main__":
    unittest.main()
