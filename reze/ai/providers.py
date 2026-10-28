"""
Provider adapters for REZE Intelligence.

Each adapter speaks the provider's official HTTP API through the standard
library, so enabling an AI provider never pulls an SDK into the deployment:

``openai``             POST https://api.openai.com/v1/chat/completions
``anthropic``          POST https://api.anthropic.com/v1/messages
``gemini``             POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
``openai_compatible``  POST {base_url}/chat/completions  (self-hosted, Groq, ...)

Capabilities (vision, streaming, tool calling) differ per provider and per
model; the gateway only ever claims what the adapter above declares.
"""

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from reze.exceptions import (
    AIConfigurationError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)

PROVIDER_NAMES = ("openai", "anthropic", "gemini", "openai_compatible")
DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "gemini": "gemini-1.5-flash",
    "openai_compatible": "local-model",
}
DEFAULT_BASE_URLS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "openai_compatible": "",
}
ANTHROPIC_VERSION = "2023-06-01"


@dataclass
class ProviderConfig:
    provider: str
    model: str
    api_key: str
    base_url: str = ""
    timeout: int = 60
    max_output_tokens: int = 900
    temperature: float = 0.7

    @property
    def normalized_provider(self) -> str:
        return (self.provider or "").strip().lower().replace("-", "_")

    @property
    def effective_base_url(self) -> str:
        base = (self.base_url or DEFAULT_BASE_URLS.get(self.normalized_provider, "")).rstrip("/")
        return base

    @property
    def supports_vision(self) -> bool:
        model = (self.model or "").lower()
        provider = self.normalized_provider
        if provider == "gemini":
            return True
        if provider == "anthropic":
            return "claude-3" in model or "claude-4" in model or "sonnet" in model or "opus" in model
        if provider in {"openai", "openai_compatible"}:
            markers = ("gpt-4o", "gpt-4.1", "gpt-4-turbo", "gpt-4-vision", "o3", "o4", "vision", "llava")
            return any(marker in model for marker in markers)
        return False


@dataclass
class ProviderResponse:
    text: str
    model: str
    provider: str
    usage: Dict[str, Any] = field(default_factory=dict)
    raw_metadata: Dict[str, Any] = field(default_factory=dict)


class _HttpResult:
    __slots__ = ("status", "body", "headers")

    def __init__(self, status: int, body: str, headers: Any = None):
        self.status = status
        self.body = body
        self.headers = headers


def http_post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    timeout: int = 60,
) -> Tuple[int, str, Dict[str, str]]:
    """POST JSON using urllib. Kept small so tests can replace it."""
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, body, dict(response.headers or {})
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return exc.code, body, dict(exc.headers or {})
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, TimeoutError) or "timed out" in str(reason).lower():
            raise AITimeoutError(f"The AI provider did not answer within {timeout}s.") from exc
        raise AIProviderError(f"Could not reach the AI provider: {reason}") from exc
    except TimeoutError as exc:
        raise AITimeoutError(f"The AI provider did not answer within {timeout}s.") from exc


def _normalize_error(provider: str, status: int, body: str, retry_after: Optional[str]) -> Exception:
    """Map an HTTP failure to a Reze exception without echoing secrets."""
    detail = ""
    try:
        parsed = json.loads(body or "{}")
        error = parsed.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("type") or "")[:200]
        elif isinstance(error, str):
            detail = error[:200]
    except (json.JSONDecodeError, AttributeError):
        detail = (body or "")[:120]

    if status in (401, 403):
        return AIConfigurationError(
            f"{provider} rejected the credentials. Check the API key and its permissions."
        )
    if status == 404:
        return AIProviderError(
            f"{provider} does not know this model or endpoint. Check REZE_AI_MODEL and REZE_AI_BASE_URL."
        )
    if status == 429:
        suffix = f" Retry after {retry_after}s." if retry_after else ""
        return AIRateLimitError(f"{provider} rate limit or quota reached.{suffix}")
    if status >= 500:
        return AIProviderError(f"{provider} is unavailable right now (HTTP {status}).")
    message = f"{provider} returned HTTP {status}."
    if detail:
        message += f" {detail}"
    return AIProviderError(message)


def _retry_after(headers: Dict[str, str]) -> Optional[str]:
    for key, value in (headers or {}).items():
        if key.lower() == "retry-after":
            return str(value)
    return None


def _extract_openai(body: str) -> ProviderResponse:
    try:
        payload = json.loads(body)
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            text = "".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )
        else:
            text = content or ""
        return ProviderResponse(
            text=text.strip(),
            model=payload.get("model", ""),
            provider="openai",
            usage=payload.get("usage", {}) or {},
            raw_metadata={"finish_reason": choice.get("finish_reason", "")},
        )
    except (json.JSONDecodeError, IndexError, AttributeError) as exc:
        raise AIProviderError("The provider returned an unreadable response.") from exc


def _extract_anthropic(body: str) -> ProviderResponse:
    try:
        payload = json.loads(body)
        blocks = payload.get("content") or []
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type", "text") == "text"
        )
        usage = payload.get("usage", {}) or {}
        return ProviderResponse(
            text=text.strip(),
            model=payload.get("model", ""),
            provider="anthropic",
            usage=usage,
            raw_metadata={"stop_reason": payload.get("stop_reason", "")},
        )
    except (json.JSONDecodeError, AttributeError) as exc:
        raise AIProviderError("The provider returned an unreadable response.") from exc


def _extract_gemini(body: str) -> ProviderResponse:
    try:
        payload = json.loads(body)
        candidates = payload.get("candidates") or []
        if not candidates:
            feedback = payload.get("promptFeedback", {}) or {}
            reason = feedback.get("blockReason", "")
            raise AIProviderError(
                "Gemini returned no candidates"
                + (f" (blocked: {reason})." if reason else ".")
            )
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict))
        usage_meta = payload.get("usageMetadata", {}) or {}
        usage = {
            "prompt_tokens": usage_meta.get("promptTokenCount", 0),
            "completion_tokens": usage_meta.get("candidatesTokenCount", 0),
            "total_tokens": usage_meta.get("totalTokenCount", 0),
        }
        return ProviderResponse(
            text=text.strip(),
            model=payload.get("modelVersion", ""),
            provider="gemini",
            usage=usage,
            raw_metadata={"finish_reason": candidates[0].get("finishReason", "")},
        )
    except (json.JSONDecodeError, IndexError, AttributeError) as exc:
        raise AIProviderError("The provider returned an unreadable response.") from exc


class ProviderAdapter:
    """One provider, one request/response contract."""

    name = "provider"
    supports_vision = False

    def __init__(self, config: ProviderConfig):
        self.config = config
        self.supports_vision = config.supports_vision

    # ------------------------------------------------------------------ requests
    def build_request(
        self,
        prompt: str,
        system: str = "",
        image: Optional[Tuple[bytes, str]] = None,
    ) -> Tuple[str, Dict[str, str], Dict[str, Any]]:
        raise NotImplementedError

    def parse(self, body: str) -> ProviderResponse:
        raise NotImplementedError

    async def complete(
        self,
        prompt: str,
        system: str = "",
        image: Optional[Tuple[bytes, str]] = None,
        http_post=http_post_json,
    ) -> ProviderResponse:
        import asyncio

        url, headers, payload = self.build_request(prompt, system, image)
        started = time.time()
        status, body, response_headers = await asyncio.to_thread(
            http_post, url, headers, payload, self.config.timeout
        )
        if status >= 400:
            raise _normalize_error(
                self.name, status, body, _retry_after(response_headers)
            )
        parsed = self.parse(body)
        parsed.raw_metadata["elapsed"] = round(time.time() - started, 2)
        parsed.raw_metadata["http_status"] = status
        return parsed


class OpenAIAdapter(ProviderAdapter):
    name = "openai"

    def build_request(self, prompt, system="", image=None):
        base = self.config.effective_base_url or DEFAULT_BASE_URLS["openai"]
        if not self.config.api_key:
            raise AIConfigurationError("REZE_AI_API_KEY is not set for the OpenAI provider.")
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        if image:
            import base64

            payload_bytes, mime = image
            data_url = f"data:{mime};base64,{base64.b64encode(payload_bytes).decode('ascii')}"
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            )
        else:
            messages.append({"role": "user", "content": prompt})

        return (
            f"{base}/chat/completions",
            {"Authorization": f"Bearer {self.config.api_key}"},
            {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": self.config.max_output_tokens,
                "temperature": self.config.temperature,
            },
        )

    def parse(self, body: str) -> ProviderResponse:
        return _extract_openai(body)


class OpenAICompatibleAdapter(OpenAIAdapter):
    name = "openai_compatible"

    def build_request(self, prompt, system="", image=None):
        if not self.config.effective_base_url:
            raise AIConfigurationError(
                "REZE_AI_BASE_URL is required for the openai_compatible provider "
                "(for example http://127.0.0.1:8000/v1)."
            )
        return super().build_request(prompt, system, image)


class AnthropicAdapter(ProviderAdapter):
    name = "anthropic"

    def build_request(self, prompt, system="", image=None):
        base = self.config.effective_base_url or DEFAULT_BASE_URLS["anthropic"]
        if not self.config.api_key:
            raise AIConfigurationError("REZE_AI_API_KEY is not set for the Anthropic provider.")
        content: List[Dict[str, Any]] = []
        if image:
            import base64

            payload_bytes, mime = image
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": mime,
                        "data": base64.b64encode(payload_bytes).decode("ascii"),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "max_tokens": self.config.max_output_tokens,
            "temperature": self.config.temperature,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            payload["system"] = system

        return (
            f"{base}/messages",
            {
                "x-api-key": self.config.api_key,
                "anthropic-version": ANTHROPIC_VERSION,
            },
            payload,
        )

    def parse(self, body: str) -> ProviderResponse:
        return _extract_anthropic(body)


class GeminiAdapter(ProviderAdapter):
    name = "gemini"

    def build_request(self, prompt, system="", image=None):
        base = self.config.effective_base_url or DEFAULT_BASE_URLS["gemini"]
        if not self.config.api_key:
            raise AIConfigurationError("REZE_AI_API_KEY is not set for the Gemini provider.")
        parts: List[Dict[str, Any]] = [{"text": prompt}]
        if image:
            import base64

            payload_bytes, mime = image
            parts.append(
                {
                    "inline_data": {
                        "mime_type": mime,
                        "data": base64.b64encode(payload_bytes).decode("ascii"),
                    }
                }
            )
        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "maxOutputTokens": self.config.max_output_tokens,
                "temperature": self.config.temperature,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        return (
            f"{base}/models/{self.config.model}:generateContent?key={self.config.api_key}",
            {},
            payload,
        )

    def parse(self, body: str) -> ProviderResponse:
        return _extract_gemini(body)


ADAPTERS = {
    "openai": OpenAIAdapter,
    "openai_compatible": OpenAICompatibleAdapter,
    "anthropic": AnthropicAdapter,
    "gemini": GeminiAdapter,
}


def build_adapter(config: ProviderConfig) -> ProviderAdapter:
    provider = config.normalized_provider
    adapter = ADAPTERS.get(provider)
    if adapter is None:
        raise AIConfigurationError(
            f"Unsupported AI provider '{config.provider}'. Supported: {', '.join(PROVIDER_NAMES)}."
        )
    return adapter(config)
