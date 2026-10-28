"""AI gateway tests: adapters, error mapping, retries, fallback and limits."""

import json
import unittest
from unittest.mock import patch

import support

from reze.ai.gateway import AIGateway
from reze.ai.providers import (
    AnthropicAdapter,
    GeminiAdapter,
    OpenAIAdapter,
    ProviderConfig,
    build_adapter,
)
from reze.config import settings
from reze.exceptions import (
    AIConfigurationError,
    AIError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)


def openai_body(text="Hello"):
    return (
        200,
        json.dumps(
            {
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            }
        ),
        {},
    )


class AdapterTests(unittest.TestCase):
    def test_openai_request_shape(self):
        adapter = OpenAIAdapter(ProviderConfig("openai", "gpt-4o-mini", "sk-test"))
        url, headers, payload = adapter.build_request("Summarize this", system="Be brief")
        self.assertTrue(url.endswith("/chat/completions"))
        self.assertEqual(headers["Authorization"], "Bearer sk-test")
        self.assertEqual(payload["model"], "gpt-4o-mini")
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["content"], "Summarize this")

    def test_openai_requires_key(self):
        adapter = OpenAIAdapter(ProviderConfig("openai", "gpt-4o-mini", ""))
        with self.assertRaises(AIConfigurationError):
            adapter.build_request("hi")

    def test_anthropic_request_shape(self):
        adapter = AnthropicAdapter(ProviderConfig("anthropic", "claude-3-5-sonnet-latest", "key"))
        url, headers, payload = adapter.build_request("Hello", system="System")
        self.assertTrue(url.endswith("/messages"))
        self.assertEqual(headers["x-api-key"], "key")
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(payload["system"], "System")
        self.assertEqual(payload["messages"][0]["content"][0]["text"], "Hello")

    def test_gemini_request_shape(self):
        adapter = GeminiAdapter(ProviderConfig("gemini", "gemini-1.5-flash", "key"))
        url, headers, payload = adapter.build_request("Hello")
        self.assertIn("models/gemini-1.5-flash:generateContent", url)
        self.assertEqual(payload["contents"][0]["parts"][0]["text"], "Hello")

    def test_openai_compatible_requires_base_url(self):
        adapter = build_adapter(ProviderConfig("openai_compatible", "local", "key"))
        with self.assertRaises(AIConfigurationError):
            adapter.build_request("hi")

    def test_unknown_provider(self):
        with self.assertRaises(AIConfigurationError):
            build_adapter(ProviderConfig("mystery", "model", "key"))

    def test_vision_capability_detection(self):
        self.assertTrue(ProviderConfig("openai", "gpt-4o", "k").supports_vision)
        self.assertFalse(ProviderConfig("openai", "gpt-3.5-turbo", "k").supports_vision)
        self.assertTrue(ProviderConfig("gemini", "gemini-1.5-flash", "k").supports_vision)

    def test_image_payload_for_openai(self):
        adapter = OpenAIAdapter(ProviderConfig("openai", "gpt-4o", "key"))
        _url, _headers, payload = adapter.build_request("describe", image=(b"abc", "image/jpeg"))
        content = payload["messages"][-1]["content"]
        self.assertEqual(content[0]["type"], "text")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_openai_parsing(self):
        adapter = OpenAIAdapter(ProviderConfig("openai", "gpt-4o-mini", "key"))
        parsed = adapter.parse(openai_body("Hi there")[1])
        self.assertEqual(parsed.text, "Hi there")
        self.assertEqual(parsed.usage["total_tokens"], 15)

    def test_anthropic_parsing(self):
        adapter = AnthropicAdapter(ProviderConfig("anthropic", "claude-3", "key"))
        body = json.dumps(
            {
                "model": "claude-3",
                "content": [{"type": "text", "text": "Answer"}],
                "usage": {"input_tokens": 3, "output_tokens": 4},
            }
        )
        parsed = adapter.parse(body)
        self.assertEqual(parsed.text, "Answer")
        self.assertEqual(parsed.usage["output_tokens"], 4)

    def test_gemini_parsing_blocked(self):
        adapter = GeminiAdapter(ProviderConfig("gemini", "gemini-1.5-flash", "key"))
        with self.assertRaises(AIProviderError):
            adapter.parse(json.dumps({"candidates": [], "promptFeedback": {"blockReason": "SAFETY"}}))


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.patches = [
            patch.object(settings, "ai_provider", "openai"),
            patch.object(settings, "ai_model", "gpt-4o-mini"),
            patch.object(settings, "ai_api_key", "sk-test"),
            patch.object(settings, "ai_base_url", ""),
            patch.object(settings, "ai_fallback", []),
            patch.object(settings, "ai_max_input_chars", 5000),
            patch.object(settings, "ai_timeout_seconds", 10),
        ]
        for active in self.patches:
            active.start()
        self.gateway = AIGateway()

    def tearDown(self):
        for active in self.patches:
            active.stop()

    def test_status_never_leaks_the_key(self):
        status = self.gateway.status()
        self.assertTrue(status["configured"])
        self.assertNotIn("sk-test", json.dumps(status))

    def test_successful_completion(self):
        calls = []

        def fake_post(url, headers, payload, timeout):
            calls.append(payload)
            return openai_body("Summary text")

        result = support.run(self.gateway.complete("Summarize", http_post=fake_post))
        self.assertEqual(result.text, "Summary text")
        self.assertEqual(result.provider, "openai")
        self.assertEqual(result.usage["total_tokens"], 15)
        self.assertIn("openai/", result.metadata_line())
        self.assertEqual(len(calls), 1)

    def test_missing_credentials(self):
        with patch.object(settings, "ai_api_key", ""):
            with self.assertRaises(AIConfigurationError):
                support.run(self.gateway.complete("hi", http_post=lambda *a: openai_body()))

    def test_prompt_limit(self):
        with patch.object(settings, "ai_max_input_chars", 10):
            with self.assertRaises(AIError) as context:
                support.run(self.gateway.complete("x" * 50, http_post=lambda *a: openai_body()))
        self.assertIn("limit", str(context.exception))

    def test_http_error_mapping(self):
        cases = {
            401: AIConfigurationError,
            404: AIProviderError,
            429: AIRateLimitError,
            500: AIProviderError,
        }
        for status, expected in cases.items():
            def fake_post(url, headers, payload, timeout, status=status):
                return status, json.dumps({"error": {"message": "failure"}}), {}

            async def run_case(fake_post=fake_post, expected=expected):
                with patch("reze.ai.gateway.asyncio.sleep", new=_no_sleep()):
                    with self.assertRaises(expected):
                        await self.gateway.complete("hi", http_post=fake_post)

            support.run(run_case())

    def test_timeout_is_retried_then_raised(self):
        attempts = []

        def fake_post(url, headers, payload, timeout):
            attempts.append(1)
            raise AITimeoutError("timed out")

        async def scenario():
            with patch("reze.ai.gateway.asyncio.sleep", new=_no_sleep()):
                with self.assertRaises(AITimeoutError):
                    await self.gateway.complete("hi", http_post=fake_post)

        support.run(scenario())
        self.assertEqual(len(attempts), 3)

    def test_rate_limit_retry_then_success(self):
        attempts = []

        def fake_post(url, headers, payload, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                return 429, json.dumps({"error": {"message": "slow down"}}), {"Retry-After": "1"}
            return openai_body("Second attempt")

        async def scenario():
            with patch("reze.ai.gateway.asyncio.sleep", new=_no_sleep()):
                return await self.gateway.complete("hi", http_post=fake_post)

        result = support.run(scenario())
        self.assertEqual(result.text, "Second attempt")
        self.assertEqual(len(attempts), 2)

    def test_fallback_is_reported(self):
        with patch.object(settings, "ai_fallback", ["openai_compatible:local-model"]), patch.object(
            settings, "ai_base_url", "http://127.0.0.1:9/v1"
        ):
            calls = []

            def fake_post(url, headers, payload, timeout):
                calls.append(url)
                if len(calls) <= 2:  # primary attempt + its single 5xx retry
                    return 500, json.dumps({"error": {"message": "down"}}), {}
                return openai_body("Fallback answer")

            async def scenario():
                with patch("reze.ai.gateway.asyncio.sleep", new=_no_sleep()):
                    return await self.gateway.complete("hi", http_post=fake_post)

            result = support.run(scenario())
            self.assertTrue(result.fallback_used)
            self.assertIn("fallback", result.metadata_line())
            self.assertEqual(len(calls), 3)

    def test_vision_requires_capable_model(self):
        with patch.object(settings, "ai_model", "gpt-3.5-turbo"):
            with self.assertRaises(AIError):
                support.run(
                    self.gateway.complete(
                        "describe", image=(b"abc", "image/jpeg"), http_post=lambda *a: openai_body()
                    )
                )

    def test_empty_response_is_an_error(self):
        def fake_post(url, headers, payload, timeout):
            return 200, json.dumps({"choices": [{"message": {"content": ""}}]}), {}

        async def scenario():
            with self.assertRaises(AIProviderError):
                await self.gateway.complete("hi", http_post=fake_post)

        support.run(scenario())


def _no_sleep():
    async def sleeper(*_args, **_kwargs):
        return None

    return sleeper


if __name__ == "__main__":
    unittest.main()
