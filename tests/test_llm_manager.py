"""
Unit tests for LLM Manager prompt construction, JSON cleaning, batching, and 429 rate-limit handling.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from base_translator import BaseTranslator
from config import AppConfig, TranslationOptions
from llm_manager import (
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

        legacy_prompt = build_system_prompt("Japanese", "Vietnamese", opts)
        self.assertIn("Vietnamese", legacy_prompt)
        self.assertIn("KEEP SPECIALIZED TERMS UNTRANSLATED", legacy_prompt)

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

    @patch("llm_manager.time.sleep")
    def test_translate_batch_retries_on_429_and_adapts_pacing(self, mock_sleep):
        config = AppConfig()
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

    @patch("llm_manager.time.sleep")
    def test_non_retryable_error_fails_immediately(self, mock_sleep):
        config = AppConfig()
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

    @patch("llm_manager.time.sleep")
    def test_translate_markdown_text_retries_on_429(self, mock_sleep):
        config = AppConfig()
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
        config = AppConfig()
        manager = LLMManager(config)
        manager._record_rate_limit(10.0)
        sleep_durations = []

        with patch.object(manager, "_sleep_with_cancel", side_effect=lambda s, cancel_check=None: sleep_durations.append(s)):
            manager._acquire_request_slot()

        self.assertEqual(len(sleep_durations), 1)
        self.assertGreater(sleep_durations[0], 9.0)

    def test_cancel_during_retry_raises_interrupted(self):
        config = AppConfig()
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
        config = AppConfig(batch_size=60)
        translator = _DummyTranslator(config, LLMManager(config))
        batches = translator.pack_batches([f"item {i}" for i in range(60)])
        self.assertEqual([len(b) for b in batches], [25, 25, 10])
        self.assertEqual(translator.get_max_workers(10), 2)
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

        config = AppConfig()
        manager = LLMManager(config)
        # Reordered indices from model should map back to exact input positions
        out_of_order = json.dumps({"translations": [{"i": 1, "t": "Thế giới"}, {"i": 0, "t": "Xin chào"}]})
        manager._get_client = lambda: _DummyClient([out_of_order])
        res = manager.translate_batch(["Hello", "World"], target_lang="Vietnamese", source_lang="English")
        self.assertEqual(res, ["Xin chào", "Thế giới"])

    @patch("llm_manager.time.sleep")
    def test_length_mismatch_retries_and_splits_instead_of_padding_source(self, _mock_sleep):
        import json
        config = AppConfig()
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
        from llm_manager import _wrap_provider_error, _get_http_status_code
        sdk_err = Exception("Rate limited")
        sdk_err.status_code = 429
        sdk_err.response = SimpleNamespace(status_code=429, headers={"Retry-After": "17"})
        wrapped = _wrap_provider_error("OpenAI API Error", sdk_err)
        self.assertEqual(_get_http_status_code(wrapped), 429)
        self.assertTrue(is_rate_limit_error(wrapped))
        self.assertEqual(extract_retry_delay(wrapped), 17.0)

    def test_should_translate_text_rules(self):
        from base_translator import should_translate_text
        self.assertTrue(should_translate_text("1,2,3"))
        self.assertFalse(should_translate_text("1,234.56"))
        self.assertFalse(should_translate_text("---"))
        self.assertFalse(should_translate_text("=SUM(A1:A5)"))

    def test_openai_client_structured_param_discovery_and_finish_reasons(self):
        from llm_manager import OpenAIClient

        calls = []

        class _FakeCompletions:
            def create(self, **kwargs):
                calls.append(dict(kwargs))
                if "temperature" in kwargs:
                    err = Exception("Unsupported parameter")
                    err.status_code = 400
                    err.param = "temperature"
                    raise err
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
        oa.generate_completion("sys", "usr", "o4-mini", is_json=True)
        self.assertEqual(len(calls), 3)
        self.assertIn("temperature", calls[0])
        self.assertNotIn("temperature", calls[1])
        self.assertNotIn("temperature", calls[2])

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
        from llm_manager import GeminiClient

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
        import model_fetcher
        from llm_manager import ClaudeClient

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

    def test_structured_headers_retry_info_and_auto_model_resolution(self):
        import httpx2
        from llm_manager import _wrap_provider_error

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

        # 5. Auto-discover live model when config has no model selected yet
        cfg = AppConfig()
        cfg.active_provider = "OpenAI"
        cfg.api_keys["OpenAI"] = "sk-live-key"
        cfg.selected_models["OpenAI"] = ""
        cfg.save = lambda: None
        manager = LLMManager(cfg)

        with patch("llm_manager.fetch_live_models", return_value=["gpt-live-first"]) as mock_fetch, \
             patch("config.load_cached_models", return_value=[]):
            resolved = manager._resolve_active_model()
            self.assertEqual(resolved, "gpt-live-first")
            self.assertEqual(cfg.selected_models["OpenAI"], "gpt-live-first")
            mock_fetch.assert_called_once_with("OpenAI", "sk-live-key")

    def test_real_third_party_sdk_exceptions_and_mock_transport(self):
        import json
        import httpx2
        import openai
        import anthropic
        from google.genai import errors as genai_errors
        from error_handler import diagnose_error
        from llm_manager import OpenAIClient, _wrap_provider_error

        # 1. Real OpenAI BadRequestError with structured param='temperature' (even when message prose omits 'temperature')
        oai_req = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
        calls = []

        def oai_handler(request: httpx2.Request) -> httpx2.Response:
            body = json.loads(request.content.decode())
            calls.append(body)
            if "temperature" in body:
                return httpx2.Response(
                    400,
                    json={"error": {"message": "Parameter rejected", "type": "invalid_request_error", "param": "temperature", "code": "unsupported_parameter"}},
                    request=request,
                )
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
        self.assertEqual(len(calls), 2)
        self.assertIn("temperature", calls[0])
        self.assertNotIn("temperature", calls[1])

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

            cfg_402 = AppConfig()
            mgr_402 = LLMManager(cfg_402)
            dummy_402 = _DummyClient([wrapped_g_402, '["Should not reach"]'])
            mgr_402._get_client = lambda: dummy_402
            with patch("llm_manager.time.sleep") as mock_sleep:
                with self.assertRaises(LLMError):
                    mgr_402.translate_batch(["Hello"], target_lang="Vietnamese")
            self.assertEqual(dummy_402.calls, 1)
            mock_sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
