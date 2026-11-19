"""
Unit tests for LLM Manager prompt construction, JSON cleaning, batching, and 429 rate-limit handling.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from rakutrans.parsers.base_translator import BaseTranslator
from rakutrans.core.config import AppConfig, TranslationOptions
from rakutrans.llm.llm_manager import (
    LLMError,
    LLMManager,
    build_system_prompt,
    clean_json_text,
    extract_retry_delay,
    is_non_retryable_error,
    is_rate_limit_error,
)


class _DummyClient:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def generate_completion(self, system_prompt, user_prompt, model_name, is_json=True):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _DummyTranslator(BaseTranslator):
    @classmethod
    def inspect_file(cls, file_path: str):
        return {}

    def process_file(self, file_path: str, *args, **kwargs) -> str:
        return file_path


def _configured_config(provider: str = "Gemini", model: str = "gemini-test", api_key: str = "test-key") -> AppConfig:
    cfg = AppConfig()
    cfg.active_provider = provider
    cfg.api_keys[provider] = api_key
    cfg.selected_models[provider] = model
    return cfg


class TestLLMManager(unittest.TestCase):

    def test_build_system_prompt_options(self):
        opts = TranslationOptions(
            keep_it_terms=True,
            append_original_words=True,
            custom_context="Rule: preserve sku codes",
        )
        prompt = build_system_prompt("Vietnamese", opts)
        self.assertIn("Vietnamese", prompt)
        self.assertIn("KEEP SPECIALIZED TERMS UNTRANSLATED", prompt)
        self.assertIn("APPEND ORIGINAL SOURCE WORDS", prompt)
        self.assertIn("Rule: preserve sku codes", prompt)

        source_prompt = build_system_prompt("Vietnamese", opts, source_lang="Japanese")
        self.assertIn("Vietnamese", source_prompt)
        self.assertIn("Japanese", source_prompt)
        self.assertIn("KEEP SPECIALIZED TERMS UNTRANSLATED", source_prompt)

    def test_clean_json_text(self):
        raw = '["Xin chào", "Tạm biệt"]'
        self.assertEqual(clean_json_text(raw), raw)

        fenced = '```json\n["Xin chào", "Tạm biệt"]\n```'
        self.assertEqual(clean_json_text(fenced), raw)

        messy = 'Here is the translated result:\n```\n["A", "B"]\n```\nHope that helps!'
        self.assertEqual(clean_json_text(messy), '["A", "B"]')

        bare_messy = 'Output: ["Alpha", "Beta"] done.'
        self.assertEqual(clean_json_text(bare_messy), '["Alpha", "Beta"]')

    def test_rate_limit_and_retry_delay_detection(self):
        gemini_429 = Exception("429 RESOURCE_EXHAUSTED: Quota exceeded. Please retry in 24.5s.")
        self.assertTrue(is_rate_limit_error(gemini_429))
        self.assertFalse(is_non_retryable_error(gemini_429))
        self.assertEqual(extract_retry_delay(gemini_429), 24.5)

        header_err = Exception("Too many requests")
        header_err.response = SimpleNamespace(status_code=429, headers={"Retry-After": "18"})
        self.assertTrue(is_rate_limit_error(header_err))
        self.assertEqual(extract_retry_delay(header_err), 18.0)

        billing_err = Exception("429 You exceeded your current quota, please check your plan and billing details (insufficient_quota).")
        self.assertTrue(is_non_retryable_error(billing_err))
        self.assertFalse(is_rate_limit_error(billing_err))

        auth_err = Exception("401 invalid_api_key provided")
        self.assertTrue(is_non_retryable_error(auth_err))
        self.assertFalse(is_rate_limit_error(auth_err))

    @patch("rakutrans.llm.llm_manager.time.sleep")
    def test_translate_batch_retries_on_429_and_adapts_pacing(self, mock_sleep):
        config = _configured_config()
        manager = LLMManager(config)
        dummy_client = _DummyClient([
            Exception("429 RESOURCE_EXHAUSTED. Please retry in 12s"),
            Exception("429 Too Many Requests"),
            '["Xin chào", "Thế giới"]',
        ])
        manager._get_client = lambda: dummy_client

        result = manager.translate_batch(["Hello", "World"], target_lang="Vietnamese")
        self.assertEqual(result, ["Xin chào", "Thế giới"])
        self.assertEqual(dummy_client.calls, 3)
        self.assertGreaterEqual(mock_sleep.call_count, 2)
        self.assertGreater(manager._min_interval, 0.35)

    @patch("rakutrans.llm.llm_manager.time.sleep")
    def test_non_retryable_error_fails_immediately(self, mock_sleep):
        config = _configured_config()
        manager = LLMManager(config)
        dummy_client = _DummyClient([
            Exception("401 invalid_api_key"),
            '["Should not reach"]',
        ])
        manager._get_client = lambda: dummy_client

        with self.assertRaises(LLMError):
            manager.translate_batch(["Hello"], target_lang="Vietnamese")

        self.assertEqual(dummy_client.calls, 1)
        mock_sleep.assert_not_called()

    @patch("rakutrans.llm.llm_manager.time.sleep")
    def test_translate_markdown_text_retries_on_429(self, mock_sleep):
        config = _configured_config()
        manager = LLMManager(config)
        dummy_client = _DummyClient([
            Exception("429 rate_limit reached, try again in 5s"),
            "# Xin chào",
        ])
        manager._get_client = lambda: dummy_client

        result = manager.translate_markdown_text("# Hello", target_lang="Vietnamese")
        self.assertEqual(result, "# Xin chào")
        self.assertEqual(dummy_client.calls, 2)
        self.assertGreaterEqual(mock_sleep.call_count, 1)

    def test_shared_cooldown_pauses_subsequent_slot(self):
        config = _configured_config()
        manager = LLMManager(config)
        manager._record_rate_limit(10.0)
        sleep_durations = []

        with patch.object(manager, "_sleep_with_cancel", side_effect=lambda s, cancel_check=None: sleep_durations.append(s)):
            manager._acquire_request_slot()

        self.assertEqual(len(sleep_durations), 1)
        self.assertGreater(sleep_durations[0], 9.0)

    def test_cancel_during_retry_raises_interrupted(self):
        config = _configured_config()
        manager = LLMManager(config)
        cancelled = {"flag": False}

        def _failing_then_cancelled():
            cancelled["flag"] = True
            raise Exception("429 RESOURCE_EXHAUSTED")

        dummy_client = SimpleNamespace(generate_completion=lambda *a, **kw: _failing_then_cancelled())
        manager._get_client = lambda: dummy_client

        with self.assertRaises(InterruptedError):
            manager.translate_batch(
                ["Hello"],
                target_lang="Vietnamese",
                cancel_check=lambda: cancelled["flag"],
            )

    def test_base_translator_batch_and_worker_bounds(self):
        from rakutrans.parsers.base_translator import estimate_batch_item_chars

        default_cfg = AppConfig()
        self.assertEqual(default_cfg.batch_size, 100)
        default_tr = _DummyTranslator(default_cfg, LLMManager(default_cfg))
        self.assertEqual(
            [len(b) for b in default_tr.pack_batches([f"item {i}" for i in range(230)])],
            [100, 100, 30],
        )
        # Short 25-char items pack cleanly into 5 batches for 500 items instead of 20
        short_items = [f"Label item number {i:04d} ok" for i in range(500)]
        self.assertEqual(len(default_tr.pack_batches(short_items)), 5)

        # Inline tags add realistic overhead (10 chars per tag token) without excessive splitting
        tagged = "<s0>Alpha</s0><s1>Beta</s1>"
        self.assertEqual(estimate_batch_item_chars(tagged), len(tagged) + 40)

        # Explicit batch_size > 100 is honored directly without silent 100-item cap
        cfg_large = AppConfig(batch_size=140, batch_max_chars=16000, max_concurrent_requests=12)
        translator = _DummyTranslator(cfg_large, LLMManager(cfg_large))
        batches = translator.pack_batches([f"item {i}" for i in range(140)])
        self.assertEqual([len(b) for b in batches], [140])
        self.assertEqual(translator.get_max_workers(20), 12)
        self.assertEqual(translator.get_max_workers(1), 1)

    def test_clean_json_text_preserves_embedded_backticks_and_brackets(self):
        payload = '{"translations": [{"i": 0, "t": "Code: ```\\n[a, b]\\n```"}]}'
        fenced = f"Here is the output [batch 1]:\n```json\n{payload}\n```\nDone."
        cleaned = clean_json_text(fenced)
        import json
        parsed = json.loads(cleaned)
        self.assertEqual(parsed["translations"][0]["t"], "Code: ```\n[a, b]\n```")

    def test_indexed_response_and_source_lang_prompt(self):
        import json
        prompt = build_system_prompt("Vietnamese", TranslationOptions(), source_lang="Japanese")
        self.assertIn("Japanese", prompt)

        config = _configured_config()
        manager = LLMManager(config)
        # Reordered indices from model should map back to exact input positions
        out_of_order = json.dumps({"translations": [{"i": 1, "t": "Thế giới"}, {"i": 0, "t": "Xin chào"}]})
        manager._get_client = lambda: _DummyClient([out_of_order])
        res = manager.translate_batch(["Hello", "World"], target_lang="Vietnamese", source_lang="English")
        self.assertEqual(res, ["Xin chào", "Thế giới"])

    @patch("rakutrans.llm.llm_manager.time.sleep")
    def test_length_mismatch_retries_and_splits_instead_of_padding_source(self, _mock_sleep):
        import json
        config = _configured_config()
        manager = LLMManager(config)

        class _SplittingClient:
            def __init__(self):
                self.calls = 0

            def generate_completion(self, system_prompt, user_prompt, model_name, is_json=True):
                self.calls += 1
                items = json.loads(user_prompt.split(":\n", 1)[1])
                if len(items) > 1:
                    # Simulate stubbornly dropping last item on multi-item batches
                    return json.dumps([f"TR:{it['t']}" for it in items[:-1]])
                return json.dumps({"translations": [{"i": 0, "t": f"TR:{items[0]['t']}"}]})

        client = _SplittingClient()
        manager._get_client = lambda: client
        res = manager.translate_batch(["One", "Two", "Three"], target_lang="Vietnamese", max_retries=1)
        self.assertEqual(res, ["TR:One", "TR:Two", "TR:Three"])

    def test_llm_error_preserves_http_status_and_retry_after(self):
        from rakutrans.llm.llm_manager import _wrap_provider_error, _get_http_status_code
        sdk_err = Exception("Rate limited")
        sdk_err.status_code = 429
        sdk_err.response = SimpleNamespace(status_code=429, headers={"Retry-After": "17"})
        wrapped = _wrap_provider_error("OpenAI API Error", sdk_err)
        self.assertEqual(_get_http_status_code(wrapped), 429)
        self.assertTrue(is_rate_limit_error(wrapped))
        self.assertEqual(extract_retry_delay(wrapped), 17.0)

    def test_should_translate_text_rules(self):
        from rakutrans.parsers.base_translator import should_translate_text
        self.assertTrue(should_translate_text("1,2,3"))
        self.assertFalse(should_translate_text("1,234.56"))
        self.assertFalse(should_translate_text("---"))
        self.assertFalse(should_translate_text("=SUM(A1:A5)"))

    def test_openai_client_direct_sdk_call_and_finish_reasons(self):
        from rakutrans.llm.llm_manager import OpenAIClient

        calls = []

        class _FakeCompletions:
            def create(self, **kwargs):
                calls.append(dict(kwargs))
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            finish_reason="stop",
                            message=SimpleNamespace(content='{"translations": []}', refusal=None),
                        )
                    ]
                )

        oa = OpenAIClient("test-key")
        oa._get_client = lambda: SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
        oa.generate_completion("sys", "usr", "o4-mini", is_json=True)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "o4-mini")
        self.assertEqual(calls[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("temperature", calls[0])

        # HTTP 400 must be reported directly without catching to strip params and retry
        err_calls = []

        class _RejectingCompletions:
            def create(self, **kwargs):
                err_calls.append(dict(kwargs))
                err = Exception("Unsupported parameter")
                err.status_code = 400
                err.param = "response_format"
                raise err

        oa._get_client = lambda: SimpleNamespace(chat=SimpleNamespace(completions=_RejectingCompletions()))
        with self.assertRaises(LLMError) as bad_ctx:
            oa.generate_completion("sys", "usr", "o1-mini", is_json=True)
        self.assertEqual(bad_ctx.exception.status_code, 400)
        self.assertEqual(len(err_calls), 1)

        # Length truncation triggers format error so batch translator can split
        trunc_completions = SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        finish_reason="length",
                        message=SimpleNamespace(content='{"translations": [{"i": 0', refusal=None),
                    )
                ]
            )
        )
        oa._get_client = lambda: SimpleNamespace(chat=SimpleNamespace(completions=trunc_completions))
        with self.assertRaises(LLMError) as ctx:
            oa.generate_completion("sys", "usr", "o4-mini", is_json=True)
        self.assertTrue(ctx.exception.is_format_error)

    def test_gemini_client_does_not_scrape_error_prose_and_checks_finish_reason(self):
        from rakutrans.llm.llm_manager import GeminiClient

        cfg = AppConfig()
        cfg.selected_models["Gemini"] = "gemini-selected-by-user"
        gm = GeminiClient("test-key")

        def _deprecated_err(sys_p, usr_p, model_name, is_json=True):
            err = Exception("Please update your code to use models/gemini-other")
            err.code = 404
            raise err

        gm._call_gemini = _deprecated_err
        with self.assertRaises(LLMError) as ctx:
            gm.generate_completion("sys", "usr", "gemini-selected-by-user")
        self.assertEqual(ctx.exception.status_code, 404)
        # User's selected model must NOT be silently overwritten from error message prose
        self.assertEqual(cfg.selected_models["Gemini"], "gemini-selected-by-user")

        # MAX_TOKENS candidate finish_reason raises format error
        fake_response = SimpleNamespace(
            prompt_feedback=None,
            candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="MAX_TOKENS"))],
            text="",
        )
        with self.assertRaises(LLMError) as fmt_ctx:
            gm._validate_gemini_response(fake_response)
        self.assertTrue(fmt_ctx.exception.is_format_error)

    def test_claude_client_uses_model_info_max_tokens_and_real_sdk_signature(self):
        import inspect
        import json
        import tempfile
        from pathlib import Path
        import anthropic
        import httpx2
        from rakutrans.llm import model_fetcher
        from rakutrans.llm.llm_manager import ClaudeClient

        captured_requests = []

        def mock_handler(request: httpx2.Request) -> httpx2.Response:
            captured_requests.append((request.method, request.url.path, json.loads(request.content.decode()) if request.content else None))
            if request.url.path.startswith("/v1/models/"):
                return httpx2.Response(
                    200,
                    json={
                        "id": "claude-live-model",
                        "type": "model",
                        "display_name": "Claude Live Model",
                        "created_at": "2026-01-01T00:00:00Z",
                        "lifecycle": "active",
                        "max_tokens": 16384,
                        "max_input_tokens": 200000,
                    },
                )
            if request.url.path == "/v1/messages":
                return httpx2.Response(
                    200,
                    json={
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-live-model",
                        "stop_reason": "end_turn",
                        "stop_sequence": None,
                        "usage": {"input_tokens": 5, "output_tokens": 2},
                        "content": [
                            {"type": "thinking", "thinking": "internal thoughts", "signature": "sig"},
                            {"type": "text", "text": "Pong"},
                        ],
                    },
                )
            return httpx2.Response(404, json={"error": {"type": "not_found_error", "message": "not found"}})

        real_create_params = set(inspect.signature(anthropic.resources.Messages.create).parameters.keys())
        real_sdk_client = anthropic.Anthropic(
            api_key="sk-ant-test",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(mock_handler)),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(model_fetcher, "MODELS_CACHE_FILE", Path(tmpdir) / "models_cache.json"), \
                 patch.object(model_fetcher, "CACHE_DIR", Path(tmpdir)):
                cc = ClaudeClient("sk-ant-test")
                cc._get_client = lambda: real_sdk_client
                res = cc.generate_completion("sys", "usr", "claude-live-model", is_json=False)
                self.assertEqual(res, "Pong")

                msg_payloads = [body for method, path, body in captured_requests if path == "/v1/messages"]
                self.assertEqual(len(msg_payloads), 1)
                self.assertEqual(msg_payloads[0]["max_tokens"], 16384)
                if "temperature" not in real_create_params:
                    self.assertNotIn("temperature", msg_payloads[0])

    def test_structured_headers_retry_info_and_explicit_model_required(self):
        import tempfile
        from pathlib import Path
        import httpx2
        from rakutrans.llm import model_fetcher
        from rakutrans.llm.llm_manager import _wrap_provider_error

        # 1. retry-after-ms header takes precedence
        req = httpx2.Request("POST", "https://api.example.com")
        resp = httpx2.Response(429, headers={"retry-after-ms": "3500", "Retry-After": "10"}, request=req)
        err = Exception("rate limited")
        err.status_code = 429
        err.response = resp
        self.assertEqual(extract_retry_delay(err), 3.5)

        # 2. Google RPC RetryInfo inside error details
        g_err = Exception("quota exhausted")
        g_err.code = 429
        g_err.status = "RESOURCE_EXHAUSTED"
        g_err.details = {
            "error": {
                "details": [
                    {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "22.5s"}
                ]
            }
        }
        self.assertTrue(is_rate_limit_error(g_err))
        self.assertEqual(extract_retry_delay(g_err), 22.5)

        # 3. x-should-retry: false marks error non-retryable even with 429
        no_retry_resp = httpx2.Response(429, headers={"x-should-retry": "false"}, request=req)
        no_retry_err = Exception("do not retry")
        no_retry_err.status_code = 429
        no_retry_err.response = no_retry_resp
        self.assertTrue(is_non_retryable_error(no_retry_err))

        # 4. Insufficient quota structured code is non-retryable
        quota_err = Exception("billing limit reached")
        quota_err.status_code = 429
        quota_err.code = "insufficient_quota"
        wrapped_quota = _wrap_provider_error("OpenAI API Error", quota_err)
        self.assertTrue(is_non_retryable_error(wrapped_quota))
        self.assertFalse(is_rate_limit_error(wrapped_quota))

        # 5. Missing model must fail explicitly without auto-fetching or picking cached[0]
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch.object(model_fetcher, "CACHE_DIR", tmp_path), \
                 patch.object(model_fetcher, "MODELS_CACHE_FILE", tmp_path / "models_cache.json"):
                model_fetcher.save_cached_models("OpenAI", ["gpt-cached-first"])
                cfg = AppConfig()
                cfg.active_provider = "OpenAI"
                cfg.api_keys["OpenAI"] = "sk-live-key"
                cfg.selected_models["OpenAI"] = ""
                self.assertEqual(cfg.get_active_model(), "")

                manager = LLMManager(cfg)
                with self.assertRaises(LLMError) as missing_ctx:
                    manager.translate_batch(["Hello"], target_lang="Vietnamese")
                self.assertEqual(missing_ctx.exception.error_code, "model_not_selected")
                self.assertEqual(cfg.selected_models["OpenAI"], "")

    def test_real_third_party_sdk_exceptions_and_mock_transport(self):
        import json
        import httpx2
        import openai
        import anthropic
        from google.genai import errors as genai_errors
        from rakutrans.core.error_handler import diagnose_error
        from rakutrans.llm.llm_manager import OpenAIClient, _wrap_provider_error

        # 1. Real OpenAI direct SDK call works cleanly and 400 propagates immediately without retry-stripping
        oai_req = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
        calls = []

        def oai_handler(request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content.decode())
            calls.append(body)
            return httpx2.Response(
                200,
                json={
                    "id": "chatcmpl_1",
                    "object": "chat.completion",
                    "created": 1750000000,
                    "model": body["model"],
                    "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ok"}}],
                },
                request=request,
            )

        real_oai = openai.OpenAI(
            api_key="sk-test",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(oai_handler)),
        )
        oa = OpenAIClient("sk-test")
        oa._get_client = lambda: real_oai
        self.assertEqual(oa.generate_completion("sys", "usr", "reasoning-model", is_json=False), "ok")
        self.assertEqual(len(calls), 1)
        self.assertNotIn("temperature", calls[0])

        bad_calls = []

        def oai_400_handler(request: httpx2.Request) -> httpx2.Response:
            bad_calls.append(json.loads(request.content.decode()))
            return httpx2.Response(
                400,
                json={"error": {"message": "Parameter rejected", "type": "invalid_request_error", "param": "response_format", "code": "unsupported_parameter"}},
                request=request,
            )

        oa._get_client = lambda: openai.OpenAI(
            api_key="sk-test",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(oai_400_handler)),
        )
        with self.assertRaises(LLMError) as bad_ctx:
            oa.generate_completion("sys", "usr", "legacy-model", is_json=True)
        self.assertEqual(bad_ctx.exception.status_code, 400)
        self.assertEqual(len(bad_calls), 1)

        # 2. Real OpenAI RateLimitError with insufficient_quota -> non-retryable & diagnosed as quota
        quota_resp = httpx2.Response(
            429,
            json={"error": {"message": "Exceeded budget", "type": "insufficient_quota", "code": "insufficient_quota"}},
            request=oai_req,
        )
        oai_quota = openai.RateLimitError("Error code: 429", response=quota_resp, body=quota_resp.json()["error"])
        wrapped_oai_quota = _wrap_provider_error("OpenAI API Error", oai_quota)
        self.assertTrue(is_non_retryable_error(wrapped_oai_quota))
        self.assertEqual(diagnose_error(wrapped_oai_quota).category, "quota")

        # 3. Real Anthropic OverloadedError (529) -> retryable rate/capacity limit with Retry-After
        ant_req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        ant_resp = httpx2.Response(
            529,
            headers={"retry-after": "7"},
            json={"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
            request=ant_req,
        )
        ant_overloaded = anthropic.OverloadedError("Overloaded", response=ant_resp, body=ant_resp.json())
        wrapped_ant = _wrap_provider_error("Claude API Error", ant_overloaded)
        self.assertTrue(is_rate_limit_error(wrapped_ant))
        self.assertEqual(extract_retry_delay(wrapped_ant), 7.0)

        # 4. Real Google GenAI ClientError with RetryInfo
        g_req = httpx2.Request("POST", "https://generativelanguage.googleapis.com/v1beta/models/m:generateContent")
        g_resp = httpx2.Response(
            429,
            json={"error": {"code": 429, "message": "Busy", "status": "RESOURCE_EXHAUSTED", "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "19s"}]}},
            request=g_req,
        )
        try:
            genai_errors.APIError.raise_for_response(g_resp)
        except genai_errors.APIError as g_err:
            wrapped_g = _wrap_provider_error("Gemini API Error", g_err)
            self.assertTrue(is_rate_limit_error(wrapped_g))
            self.assertEqual(extract_retry_delay(wrapped_g), 19.0)
            self.assertEqual(diagnose_error(wrapped_g).category, "quota")

        # 5. Real Google GenAI 402 RESOURCE_EXHAUSTED (prepayment credits depleted) -> non-retryable & fails immediately
        g_402_resp = httpx2.Response(
            402,
            json={"error": {"code": 402, "message": "Your prepayment credits are depleted.", "status": "RESOURCE_EXHAUSTED"}},
            request=g_req,
        )
        try:
            genai_errors.APIError.raise_for_response(g_402_resp)
        except genai_errors.APIError as g_402_err:
            wrapped_g_402 = _wrap_provider_error("Gemini API Error", g_402_err)
            self.assertTrue(is_non_retryable_error(wrapped_g_402))
            self.assertFalse(is_rate_limit_error(wrapped_g_402))
            billing_diag = diagnose_error(wrapped_g_402)
            self.assertEqual(billing_diag.category, "quota")
            self.assertIn("402", billing_diag.message)

            cfg_402 = _configured_config()
            mgr_402 = LLMManager(cfg_402)
            dummy_402 = _DummyClient([wrapped_g_402, '["Should not reach"]'])
            mgr_402._get_client = lambda: dummy_402
            with patch("rakutrans.llm.llm_manager.time.sleep") as mock_sleep:
                with self.assertRaises(LLMError):
                    mgr_402.translate_batch(["Hello"], target_lang="Vietnamese")
            self.assertEqual(dummy_402.calls, 1)
            mock_sleep.assert_not_called()

    def test_first_run_cache_model_id_matches_subsequent_runs(self):
        import json
        import tempfile
        from pathlib import Path
        from rakutrans.core import config as config_mod
        from rakutrans.llm import model_fetcher
        from rakutrans.llm.translation_cache import TranslationCache

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            with patch.object(config_mod, "CONFIG_DIR", tmp_path), \
                 patch.object(config_mod, "CONFIG_FILE", tmp_path / "config.json"), \
                 patch.object(model_fetcher, "CACHE_DIR", tmp_path), \
                 patch.object(model_fetcher, "MODELS_CACHE_FILE", tmp_path / "models_cache.json"):
                cfg = _configured_config("OpenAI", "gpt-live-first", "sk-test-key")

                mgr = LLMManager(cfg)
                client_calls = {"count": 0}

                def _fake_complete(sys_p, usr_p, model_name, is_json=True):
                    client_calls["count"] += 1
                    items = json.loads(usr_p.split(":\n", 1)[1])
                    return json.dumps({"translations": [{"i": it["i"], "t": f"VI:{it['t']}"} for it in items]})

                mgr._get_client = lambda: SimpleNamespace(generate_completion=_fake_complete)
                cache = TranslationCache(db_path=tmp_path / "cache.db")
                translator = _DummyTranslator(cfg, mgr, cache=cache)

                res1 = translator.translate_unique_texts(
                    ["Hello", "World"],
                    target_lang="Vietnamese",
                    source_lang="English",
                    options=TranslationOptions(),
                )
                self.assertEqual(res1, {"Hello": "VI:Hello", "World": "VI:World"})
                self.assertEqual(client_calls["count"], 1)

                # Second run must hit cache 100% with matching OpenAI:gpt-live-first key
                res2 = translator.translate_unique_texts(
                    ["Hello", "World"],
                    target_lang="Vietnamese",
                    source_lang="English",
                    options=TranslationOptions(),
                )
                self.assertEqual(res2, {"Hello": "VI:Hello", "World": "VI:World"})
                self.assertEqual(client_calls["count"], 1)

    def test_cancel_returns_promptly_without_waiting_for_slow_worker(self):
        import tempfile
        import threading
        import time
        from pathlib import Path
        from rakutrans.llm.translation_cache import TranslationCache

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = AppConfig(batch_size=5, max_concurrent_requests=2)
            mgr = LLMManager(cfg)
            cache = TranslationCache(db_path=Path(tmpdir) / "cancel_cache.db")
            translator = _DummyTranslator(cfg, mgr, cache=cache)

            started = threading.Event()
            release_slow = threading.Event()

            def _slow_translate_batch(texts, **kwargs):
                cancel_check = kwargs.get("cancel_check")
                if texts[0] == "item 0":
                    started.set()
                    release_slow.wait(timeout=3.0)
                else:
                    started.wait(timeout=1.0)
                    translator.cancel()
                    if cancel_check and cancel_check():
                        raise InterruptedError("cancelled")
                return [f"T:{t}" for t in texts]

            mgr.translate_batch = _slow_translate_batch

            t0 = time.monotonic()
            with self.assertRaises(InterruptedError):
                translator.translate_unique_texts(
                    [f"item {i}" for i in range(10)],
                    target_lang="Vietnamese",
                    source_lang="English",
                    options=TranslationOptions(),
                )
            elapsed = time.monotonic() - t0
            self.assertLess(elapsed, 1.0)
            release_slow.set()

    def test_format_error_splits_immediately_without_wasted_retries(self):
        import json
        cfg = _configured_config()
        manager = LLMManager(cfg)
        calls = []

        class _TruncatingClient:
            def generate_completion(self, sys_p, usr_p, model_name, is_json=True):
                items = json.loads(usr_p.split(":\n", 1)[1])
                calls.append(len(items))
                if len(items) > 1:
                    raise LLMError("Truncated", is_format_error=True)
                return json.dumps({"translations": [{"i": 0, "t": f"OK:{items[0]['t']}"}]})

        manager._get_client = lambda: _TruncatingClient()
        manager._min_interval = 0.0
        with patch("rakutrans.llm.llm_manager.time.sleep") as mock_sleep:
            res = manager.translate_batch(["A", "B"], target_lang="Vietnamese")
        self.assertEqual(res, ["OK:A", "OK:B"])
        self.assertEqual(calls, [2, 1, 1])
        mock_sleep.assert_not_called()

    @patch("rakutrans.llm.llm_manager.time.sleep")
    def test_separate_retry_budgets_and_no_cooldown_leak_on_failure(self, _mock_sleep):
        cfg = _configured_config()
        manager = LLMManager(cfg)
        dummy_client = _DummyClient([
            Exception("429 RESOURCE_EXHAUSTED"),
            Exception("429 Too Many Requests"),
            Exception("500 Internal Server Error"),
            '["Thành công"]',
        ])
        manager._get_client = lambda: dummy_client
        res = manager.translate_batch(["Success"], target_lang="Vietnamese")
        self.assertEqual(res, ["Thành công"])
        self.assertEqual(dummy_client.calls, 4)

        # Exhausting rate-limit retries must not leave a multi-second cooldown stuck for next run
        manager2 = LLMManager(cfg)
        failing_client = _DummyClient([Exception("429 Too Many Requests")] * 5)
        manager2._get_client = lambda: failing_client
        with self.assertRaises(LLMError):
            manager2.translate_batch(["Fail"], target_lang="Vietnamese")
        self.assertLessEqual(manager2._cooldown_until, 0.0)

    def test_acquire_request_slot_rechecks_extended_cooldown(self):
        import threading
        import time

        cfg = AppConfig()
        manager = LLMManager(cfg)
        manager._record_rate_limit(0.08)
        finished_at = []

        def _waiter():
            manager._acquire_request_slot()
            finished_at.append(time.monotonic())

        t_start = time.monotonic()
        t = threading.Thread(target=_waiter)
        t.start()
        time.sleep(0.03)
        manager._record_rate_limit(0.20)
        t.join(timeout=2.0)

        self.assertEqual(len(finished_at), 1)
        self.assertGreaterEqual(finished_at[0] - t_start, 0.18)

    def test_clean_json_text_skips_numeric_markers_and_preserves_string_commas(self):
        import json

        marked = '[1] {"translations": [{"i": 0, "t": "Xin chào"}]}'
        parsed_marked = json.loads(clean_json_text(marked))
        self.assertEqual(parsed_marked["translations"][0]["t"], "Xin chào")

        str_list_marked = '[1] ["Xin chào"]'
        self.assertEqual(json.loads(clean_json_text(str_list_marked)), ["Xin chào"])

        comma_in_str = '{"translations": [{"i": 0, "t": "keep , } intact"}],}'
        parsed_comma = json.loads(clean_json_text(comma_in_str))
        self.assertEqual(parsed_comma["translations"][0]["t"], "keep , } intact")

    def test_gemini_client_llm_error_no_cause_cycle_and_markdown_split_on_truncation(self):
        from rakutrans.llm.llm_manager import GeminiClient

        gm = GeminiClient("test-key")
        gm._call_gemini = lambda *a, **kw: (_ for _ in ()).throw(
            LLMError("Gemini response truncated (finish_reason=MAX_TOKENS).", is_format_error=True)
        )
        with self.assertRaises(LLMError) as ctx:
            gm.generate_completion("sys", "usr", "gemini-2.5-flash")
        self.assertIsNot(ctx.exception.__cause__, ctx.exception)

        cfg = _configured_config()
        mgr = LLMManager(cfg)

        def _split_md_complete(sys_p, usr_p, model_name, is_json=False):
            if "Part Two" in usr_p and "Part One" in usr_p:
                raise LLMError("Truncated", is_format_error=True)
            return f"VI:{usr_p}"

        mgr._get_client = lambda: SimpleNamespace(generate_completion=_split_md_complete)
        out = mgr.translate_markdown_text(
            "Part One is long enough to split safely.\n\nPart Two is also long enough.",
            target_lang="Vietnamese",
        )
        self.assertEqual(out, "VI:Part One is long enough to split safely.\n\nVI:Part Two is also long enough.")

    def test_claude_client_requires_api_max_tokens_and_no_streaming_fallback(self):
        import tempfile
        from pathlib import Path
        from rakutrans.llm import model_fetcher
        from rakutrans.llm.llm_manager import ClaudeClient

        stream_called = {"flag": False}

        class _FakeStreamCtx:
            def __enter__(self):
                stream_called["flag"] = True
                return self

            def __exit__(self, *args):
                return False

            def get_final_message(self):
                return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="Streamed")])

        fake_messages = SimpleNamespace(
            create=lambda **kw: (_ for _ in ()).throw(ValueError("Streaming is required for operations that may take longer than 10 minutes")),
            stream=lambda **kw: _FakeStreamCtx(),
        )
        cc = ClaudeClient("sk-ant-test")
        cc._model_max_tokens["claude-test"] = 64000
        cc._get_client = lambda: SimpleNamespace(messages=fake_messages)

        with self.assertRaises(LLMError) as err_ctx:
            cc.generate_completion("sys", "usr", "claude-test", is_json=False)
        self.assertIn("Streaming is required", str(err_ctx.exception))
        self.assertFalse(stream_called["flag"])

        # Missing max_tokens in ModelInfo must raise LLMError instead of falling back to hardcoded 4096
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(model_fetcher, "MODELS_CACHE_FILE", Path(tmpdir) / "models_cache.json"), \
                 patch.object(model_fetcher, "CACHE_DIR", Path(tmpdir)):
                cc2 = ClaudeClient("sk-ant-test")
                cc2._get_client = lambda: SimpleNamespace(
                    models=SimpleNamespace(retrieve=lambda m: SimpleNamespace(id=m, max_tokens=None)),
                    messages=SimpleNamespace(create=lambda **kw: None),
                )
                with self.assertRaises(LLMError) as mt_ctx:
                    cc2.generate_completion("sys", "usr", "claude-no-limit", is_json=False)
                self.assertIn("max_tokens", str(mt_ctx.exception))

    def test_gemini_temperature_and_strict_json_mode_configurable(self):
        from rakutrans.llm.llm_manager import GeminiClient

        captured_configs = []

        class _FakeModels:
            def generate_content(self, model, contents, config):
                captured_configs.append((model, config))
                return SimpleNamespace(text='{"translations": [{"i": 0, "t": "Xin chao"}]}', candidates=[])

        fake_client = SimpleNamespace(models=_FakeModels())

        # Default temperature=None leaves temperature unset cleanly; strict_json_mode=True sets JSON mime type
        gm_default = GeminiClient("test-key")
        gm_default._get_client = lambda: fake_client
        gm_default._call_gemini("sys", "usr", "gemini-2.5-flash", is_json=True)
        cfg1 = captured_configs[-1][1]
        self.assertIsNone(getattr(cfg1, "temperature", None))
        self.assertEqual(getattr(cfg1, "response_mime_type", None), "application/json")

        # Explicit temperature & strict_json_mode=False
        gm_custom = GeminiClient("test-key", temperature=0.65, strict_json_mode=False)
        gm_custom._get_client = lambda: fake_client
        gm_custom._call_gemini("sys", "usr", "gemini-2.5-flash", is_json=True)
        cfg2 = captured_configs[-1][1]
        self.assertAlmostEqual(cfg2.temperature, 0.65)
        self.assertIsNone(getattr(cfg2, "response_mime_type", None))

    def test_llm_manager_config_cache_key_invalidation_and_custom_params(self):
        cfg = _configured_config()
        cfg.active_provider = "OpenAI"
        cfg.api_keys["OpenAI"] = "sk-test"
        cfg.selected_models["OpenAI"] = "gpt-4o"
        cfg.base_urls["OpenAI"] = "https://gateway.one/v1"
        cfg.temperature = 0.3
        cfg.strict_json_mode = False
        cfg.request_timeout = 45.0

        mgr = LLMManager(cfg)
        c1 = mgr._get_client()
        self.assertEqual(c1.base_url, "https://gateway.one/v1")
        self.assertAlmostEqual(c1.temperature, 0.3)
        self.assertFalse(c1.strict_json_mode)
        self.assertAlmostEqual(c1.timeout, 45.0)
        self.assertIs(mgr._get_client(), c1)

        # Updating base_url / temperature / strict_json_mode / timeout must invalidate cached client
        cfg.base_urls["OpenAI"] = "https://gateway.two/v1"
        cfg.temperature = None
        cfg.strict_json_mode = True
        cfg.request_timeout = 90.0
        c2 = mgr._get_client()
        self.assertIsNot(c2, c1)
        self.assertEqual(c2.base_url, "https://gateway.two/v1")
        self.assertIsNone(c2.temperature)
        self.assertTrue(c2.strict_json_mode)
        self.assertAlmostEqual(c2.timeout, 90.0)

    def test_proactive_rpm_and_tpm_sliding_window_pacing(self):
        cfg = _configured_config()
        cfg.min_request_interval = 0.0
        cfg.rpm_limit = 2
        cfg.tpm_limit = 0
        mgr = LLMManager(cfg)

        clock = {"now": 100.0}
        sleeps = []

        def fake_monotonic():
            return clock["now"]

        def fake_sleep(sec):
            sleeps.append(sec)
            clock["now"] += sec

        with patch("rakutrans.llm.llm_manager.time.monotonic", side_effect=fake_monotonic), \
             patch("rakutrans.llm.llm_manager.time.sleep", side_effect=fake_sleep):
            mgr._acquire_request_slot(estimated_tokens=50)
            clock["now"] += 1.0
            mgr._acquire_request_slot(estimated_tokens=50)
            self.assertEqual(sleeps, [])

            # 3rd request within 60s window must wait until 1st slot expires (100.0 + 60.05 - 101.0 = 59.05s)
            mgr._acquire_request_slot(estimated_tokens=50)
            self.assertTrue(len(sleeps) >= 1)
            self.assertGreaterEqual(clock["now"], 160.0)

        # TPM window check
        cfg_tpm = _configured_config()
        cfg_tpm.min_request_interval = 0.0
        cfg_tpm.rpm_limit = 0
        cfg_tpm.tpm_limit = 1000
        mgr_tpm = LLMManager(cfg_tpm)
        clock["now"] = 200.0
        sleeps.clear()

        with patch("rakutrans.llm.llm_manager.time.monotonic", side_effect=fake_monotonic), \
             patch("rakutrans.llm.llm_manager.time.sleep", side_effect=fake_sleep):
            mgr_tpm._acquire_request_slot(estimated_tokens=700)
            clock["now"] += 1.0
            # Next request of 500 tokens exceeds 1000 TPM -> waits until first entry expires
            mgr_tpm._acquire_request_slot(estimated_tokens=500)
            self.assertTrue(len(sleeps) >= 1)
            self.assertGreaterEqual(clock["now"], 260.0)

    def test_adaptive_concurrency_and_anti_sawtooth_recovery(self):
        cfg = _configured_config()
        cfg.max_concurrent_requests = 4
        cfg.min_request_interval = 0.25
        cfg.rpm_limit = 0
        mgr = LLMManager(cfg)
        self.assertEqual(mgr._effective_concurrency, 4)

        mgr._record_rate_limit(10.0)
        self.assertEqual(mgr._effective_concurrency, 1)
        self.assertGreaterEqual(mgr._session_min_interval_floor, 1.0)
        self.assertGreaterEqual(mgr._min_interval, 1.0)

        # Few successes (< 5) must NOT prematurely collapse pacing back down
        for _ in range(4):
            mgr._record_success()
        self.assertEqual(mgr._effective_concurrency, 1)
        self.assertGreaterEqual(mgr._min_interval, 1.0)

        # 8 consecutive successes step concurrency up +1 without dropping below session floor
        for _ in range(4):
            mgr._record_success()
        self.assertEqual(mgr._effective_concurrency, 2)
        self.assertGreaterEqual(mgr._min_interval, mgr._session_min_interval_floor)

        # Changing settings via sync_config restores configured ceiling
        cfg.max_concurrent_requests = 3
        cfg.min_request_interval = 0.4
        mgr.sync_config(cfg)
        self.assertEqual(mgr._effective_concurrency, 3)
        self.assertAlmostEqual(mgr._min_interval, 0.4)

    def test_sliding_window_task_submission_and_large_workload_cache_resume(self):
        import json
        import tempfile
        import threading
        from pathlib import Path
        from rakutrans.llm.translation_cache import TranslationCache

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = _configured_config()
            cfg.batch_size = 20
            cfg.batch_max_chars = 6000
            cfg.max_concurrent_requests = 2
            cfg.min_request_interval = 0.0
            cfg.rpm_limit = 0

            mgr = LLMManager(cfg)
            cache = TranslationCache(db_path=Path(tmpdir) / "large_cache.db")
            translator = _DummyTranslator(cfg, mgr, cache=cache)

            # 2400 unique items -> 120 batches (> max_workers * 2 = 4 in-flight window)
            items = [f"Segment number {i} for large file simulation" for i in range(2400)]

            lock = threading.Lock()
            state = {"in_flight": 0, "max_in_flight": 0, "calls": 0, "fail_on_call": 50}

            def fake_complete(sys_p, usr_p, model_name, is_json=True):
                with lock:
                    state["calls"] += 1
                    call_num = state["calls"]
                    state["in_flight"] += 1
                    state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
                try:
                    if state["fail_on_call"] and call_num >= state["fail_on_call"]:
                        err = Exception("429 Too Many Requests")
                        err.status_code = 429
                        raise err
                    payload = json.loads(usr_p.split(":\n", 1)[1])
                    return json.dumps({"translations": [{"i": it["i"], "t": f"VI:{it['t']}"} for it in payload]})
                finally:
                    with lock:
                        state["in_flight"] -= 1

            mgr._get_client = lambda: SimpleNamespace(generate_completion=fake_complete)

            with patch("rakutrans.llm.llm_manager.time.sleep"):
                with self.assertRaises(LLMError):
                    translator.translate_unique_texts(
                        items,
                        target_lang="Vietnamese",
                        source_lang="English",
                        options=TranslationOptions(),
                    )

            # Window bounded active concurrency and many completed batches persisted to SQLite cache
            self.assertLessEqual(state["max_in_flight"], 2)
            cached_after_abort = cache.count()
            self.assertGreater(cached_after_abort, 40)

            # Resume without failures (keep sleep patched since elevated post-429 pacing floor applies)
            state["fail_on_call"] = 0
            calls_before_resume = state["calls"]
            with patch("rakutrans.llm.llm_manager.time.sleep"):
                resumed = translator.translate_unique_texts(
                    items,
                    target_lang="Vietnamese",
                    source_lang="English",
                    options=TranslationOptions(),
                )
            calls_during_resume = state["calls"] - calls_before_resume
            self.assertEqual(len(resumed), 2400)
            self.assertEqual(resumed[items[0]], f"VI:{items[0]}")
            self.assertEqual(calls_during_resume, 120 - (cached_after_abort // 20))

    def test_single_oversized_batch_item_splits_on_format_error_plain_and_inline_tags(self):
        import json
        from rakutrans.parsers.base_translator import compute_effective_batch_char_limit, estimate_translation_requests

        cfg = _configured_config()
        mgr = LLMManager(cfg)
        mgr._min_interval = 0.0

        # 1. Plain single item > _MIN_SPLIT_RETRY_CHARS splits at sentence/line boundary on MAX_TOKENS
        def _complete_plain(sys_p, usr_p, model_name, is_json=True):
            items = json.loads(usr_p.split(":\n", 1)[1])
            text_val = items[0]["t"]
            if len(text_val) > 95:
                raise LLMError("Response truncated (MAX_TOKENS)", is_format_error=True)
            return json.dumps({"translations": [{"i": 0, "t": f"VI[{text_val.strip()}]"}]})

        mgr._get_client = lambda: SimpleNamespace(generate_completion=_complete_plain)
        long_single = (
            "First sentence is quite long so that the combined single cell exceeds ninety chars. "
            "Second sentence is also long enough to stand on its own."
        )
        res_plain = mgr.translate_batch([long_single], target_lang="Vietnamese")
        self.assertEqual(
            res_plain,
            [
                "VI[First sentence is quite long so that the combined single cell exceeds ninety chars.] "
                "VI[Second sentence is also long enough to stand on its own.]"
            ],
        )

        # 2. Inline-tagged single item (<s0>...</s0><s1>...</s1>...) splits across tag boundaries and re-shifts indices
        def _complete_tagged(sys_p, usr_p, model_name, is_json=True):
            items = json.loads(usr_p.split(":\n", 1)[1])
            text_val = items[0]["t"]
            if "<s2>" in text_val:
                raise LLMError("Truncated inline tags", is_format_error=True)
            # Translate each <sK>...</sK> segment preserving local indices
            import re
            translated_val = re.sub(
                r"<s(\d+)>(.*?)</s\1>",
                lambda m: f"<s{m.group(1)}>VI:{m.group(2)}</s{m.group(1)}>",
                text_val,
            )
            return json.dumps({"translations": [{"i": 0, "t": translated_val}]})

        mgr._get_client = lambda: SimpleNamespace(generate_completion=_complete_tagged)
        tagged_single = "<s0>Alpha</s0><s1>Beta</s1><s2>Gamma</s2><s3>Delta</s3>"
        res_tagged = mgr.translate_batch([tagged_single], target_lang="Vietnamese")
        self.assertEqual(
            res_tagged,
            ["<s0>VI:Alpha</s0><s1>VI:Beta</s1><s2>VI:Gamma</s2><s3>VI:Delta</s3>"],
        )

        # 3. Effective batch char budget adapts when append_original_words is enabled and stays aligned with LLMManager
        cfg_budget = AppConfig(batch_size=60, batch_max_chars=1000)
        base_limit = compute_effective_batch_char_limit(cfg_budget, TranslationOptions(append_original_words=False))
        expanded_limit = compute_effective_batch_char_limit(cfg_budget, TranslationOptions(append_original_words=True))
        self.assertEqual(base_limit, 1000)
        self.assertEqual(expanded_limit, 750)
        mgr_budget = LLMManager(cfg_budget)
        self.assertEqual(mgr_budget._resolve_effective_batch_char_limit(TranslationOptions(append_original_words=True)), 750)

        # 4. Markdown system prompt includes placeholder preservation rule only when placeholders are present
        seen_sys = []
        mgr_md = LLMManager(_configured_config())
        mgr_md._min_interval = 0.0
        mgr_md._get_client = lambda: SimpleNamespace(
            generate_completion=lambda s, u, m, is_json=False: (seen_sys.append(s) or u)
        )
        mgr_md.translate_markdown_text("Hello world", target_lang="Vietnamese", plain_text=False)
        mgr_md.translate_markdown_text("Hello\n\n<<<RAKUTRANS_CODE_0>>>\n\nWorld", target_lang="Vietnamese", plain_text=False)
        self.assertNotIn("PRESERVE PLACEHOLDER TOKENS", seen_sys[0])
        self.assertIn("PRESERVE PLACEHOLDER TOKENS", seen_sys[1])

        # 5. Request estimation uses unique_char_count and translatable_char_count accurately
        excel_info = {"type": "excel", "unique_texts": 10, "char_count": 50000, "unique_char_count": 3000}
        self.assertEqual(estimate_translation_requests(excel_info, cfg_budget), 3)
        md_info = {"type": "markdown", "char_count": 20000, "translatable_char_count": 1500}
        cfg_md = AppConfig(section_max_chars=1000)
        self.assertEqual(estimate_translation_requests(md_info, cfg_md), 2)


if __name__ == "__main__":
    unittest.main()
