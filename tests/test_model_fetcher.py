"""
Unit tests for model_fetcher.py (API-driven model discovery, caching, and provider resolution).
"""

from datetime import datetime, timezone
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import model_fetcher
from model_fetcher import (
    fetch_live_models,
    get_model_metadata,
    load_cached_models,
    resolve_provider_for_model,
    save_cached_models,
)


class _FakeGeminiPager:
    def __init__(self, items):
        self._items = items

    def __iter__(self):
        return iter(self._items)


class _FakePagedList:
    """Simulates OpenAI/Anthropic SyncPage where __iter__ spans multiple pages beyond .data."""
    def __init__(self, pages):
        self._pages = pages
        self.data = pages[0] if pages else []

    def __iter__(self):
        for page in self._pages:
            for item in page:
                yield item


class TestModelFetcher(unittest.TestCase):

    def test_empty_cache_returns_empty_list_without_hardcoded_seeds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache_file = Path(tmpdir) / "models_cache.json"
            with patch.object(model_fetcher, "MODELS_CACHE_FILE", test_cache_file), \
                 patch.object(model_fetcher, "CACHE_DIR", Path(tmpdir)):
                self.assertEqual(load_cached_models("Gemini"), [])
                self.assertEqual(load_cached_models("OpenAI"), [])
                self.assertEqual(load_cached_models("Claude"), [])
                self.assertEqual(fetch_live_models("Gemini", ""), [])

                custom = ["gemini-live-1", "gemma-3-27b-it"]
                meta = {"gemini-live-1": {"output_token_limit": 65536}}
                save_cached_models("Gemini", custom, models_meta=meta)

                self.assertEqual(load_cached_models("Gemini"), custom)
                self.assertEqual(get_model_metadata("Gemini", "gemini-live-1")["output_token_limit"], 65536)

    def test_gemini_uses_supported_actions_without_name_prefix_guessing(self):
        fake_models = [
            SimpleNamespace(name="models/gemini-2.5-flash", supported_actions=["generateContent", "countTokens"], version="001", output_token_limit=65536),
            SimpleNamespace(name="models/gemma-3-27b-it", supported_actions=["generateContent"], version="001", output_token_limit=8192),
            SimpleNamespace(name="models/text-embedding-004", supported_actions=["embedContent"], version="001"),
            SimpleNamespace(name="models/imagen-3.0-generate-002", supported_actions=["predict"], version="001"),
        ]
        fake_client = SimpleNamespace(models=SimpleNamespace(list=lambda: _FakeGeminiPager(fake_models)))

        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache_file = Path(tmpdir) / "models_cache.json"
            with patch.object(model_fetcher, "MODELS_CACHE_FILE", test_cache_file), \
                 patch.object(model_fetcher, "CACHE_DIR", Path(tmpdir)), \
                 patch.object(model_fetcher, "_build_gemini_client", return_value=fake_client):
                res = fetch_live_models("Gemini", "test-key")
                self.assertEqual(res, ["gemini-2.5-flash", "gemma-3-27b-it"])
                self.assertEqual(
                    get_model_metadata("Gemini", "gemma-3-27b-it")["supported_actions"],
                    ["generateContent"],
                )

    def test_gemini_api_error_does_not_mask_with_legacy_fallback(self):
        fake_client = SimpleNamespace(
            models=SimpleNamespace(list=lambda: (_ for _ in ()).throw(RuntimeError("401 API_KEY_INVALID")))
        )
        with patch.object(model_fetcher, "_build_gemini_client", return_value=fake_client):
            with self.assertRaises(RuntimeError) as ctx:
                fetch_live_models("Gemini", "bad-key")
            self.assertIn("401 API_KEY_INVALID", str(ctx.exception))

    def test_openai_auto_paginates_and_sorts_by_created_timestamp(self):
        page1 = [
            SimpleNamespace(id="older-model", created=1700000000, owned_by="openai", shutdown_date=None),
            SimpleNamespace(id="expired-model", created=1710000000, owned_by="openai", shutdown_date="2020-01-01"),
        ]
        page2 = [
            SimpleNamespace(id="ft:custom-org:model", created=1750000000, owned_by="org-123", shutdown_date=None),
            SimpleNamespace(id="codex-mini-latest", created=1760000000, owned_by="openai", shutdown_date="2099-01-01"),
        ]
        fake_client = SimpleNamespace(models=SimpleNamespace(list=lambda: _FakePagedList([page1, page2])))

        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache_file = Path(tmpdir) / "models_cache.json"
            with patch.object(model_fetcher, "MODELS_CACHE_FILE", test_cache_file), \
                 patch.object(model_fetcher, "CACHE_DIR", Path(tmpdir)), \
                 patch("openai.OpenAI", return_value=fake_client):
                res = fetch_live_models("OpenAI", "sk-test")
                self.assertEqual(res, ["codex-mini-latest", "ft:custom-org:model", "older-model"])
                self.assertEqual(get_model_metadata("OpenAI", "ft:custom-org:model")["owned_by"], "org-123")

    def test_claude_auto_paginates_sorts_by_lifecycle_and_created_at_and_propagates_errors(self):
        t_old = datetime(2024, 10, 1, tzinfo=timezone.utc)
        t_mid = datetime(2025, 2, 1, tzinfo=timezone.utc)
        t_new = datetime(2026, 5, 1, tzinfo=timezone.utc)

        page1 = [
            SimpleNamespace(id="claude-retired", type="model", lifecycle="retired", created_at=t_new, max_tokens=8192),
            SimpleNamespace(id="claude-deprecated", type="model", lifecycle="deprecated", created_at=t_new, max_tokens=8192),
        ]
        page2 = [
            SimpleNamespace(id="claude-older-active", type="model", lifecycle="active", created_at=t_old, max_tokens=4096),
            SimpleNamespace(
                id="claude-newest-active",
                type="model",
                lifecycle="active",
                created_at=t_mid,
                max_tokens=64000,
                max_input_tokens=200000,
                line="sonnet",
                capabilities=SimpleNamespace(structured_outputs=SimpleNamespace(supported=True)),
            ),
        ]
        fake_client = SimpleNamespace(models=SimpleNamespace(list=lambda: _FakePagedList([page1, page2])))

        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache_file = Path(tmpdir) / "models_cache.json"
            with patch.object(model_fetcher, "MODELS_CACHE_FILE", test_cache_file), \
                 patch.object(model_fetcher, "CACHE_DIR", Path(tmpdir)), \
                 patch("anthropic.Anthropic", return_value=fake_client):
                res = fetch_live_models("Claude", "sk-ant-test")
                self.assertEqual(res, ["claude-newest-active", "claude-older-active", "claude-deprecated"])
                meta = get_model_metadata("Claude", "claude-newest-active")
                self.assertEqual(meta["max_tokens"], 64000)
                self.assertEqual(meta["line"], "sonnet")
                self.assertTrue(meta["capabilities"]["structured_outputs"])

        # Errors from Anthropic must propagate instead of silently returning hardcoded models
        failing_client = SimpleNamespace(
            models=SimpleNamespace(list=lambda: (_ for _ in ()).throw(RuntimeError("401 Unauthorized")))
        )
        with patch("anthropic.Anthropic", return_value=failing_client):
            with self.assertRaises(RuntimeError):
                fetch_live_models("Claude", "bad-key")

    def test_resolve_provider_uses_cache_and_live_lookup_without_prefix_guessing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache_file = Path(tmpdir) / "models_cache.json"
            with patch.object(model_fetcher, "MODELS_CACHE_FILE", test_cache_file), \
                 patch.object(model_fetcher, "CACHE_DIR", Path(tmpdir)):
                save_cached_models("Gemini", ["gemma-3-27b-it"])
                save_cached_models("Claude", ["mythos-preview"])

                self.assertEqual(resolve_provider_for_model("gemma-3-27b-it"), "Gemini")
                self.assertEqual(resolve_provider_for_model("mythos-preview"), "Claude")

                # When uncached, queries live API rather than guessing from prefixes
                with patch.object(
                    model_fetcher,
                    "check_model_exists_live",
                    side_effect=lambda prov, key, m: prov == "OpenAI" and m == "custom-proxy-model",
                ):
                    self.assertEqual(
                        resolve_provider_for_model(
                            "custom-proxy-model",
                            api_keys={"Gemini": "k1", "OpenAI": "k2"},
                            fallback="Gemini",
                        ),
                        "OpenAI",
                    )

                # Unknown model without API match returns fallback instead of prefix guessing
                self.assertEqual(
                    resolve_provider_for_model("gpt-unknown-uncached", fallback="Claude"),
                    "Claude",
                )


if __name__ == "__main__":
    unittest.main()
