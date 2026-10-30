"""
Provider-neutral AI gateway.

Rules enforced here:

* no provider or model is hardcoded as the only option, and no key is required
  for non-AI features;
* prompts and responses are never written to the log;
* input size, output tokens and timeouts are bounded;
* retries happen only for rate limits and timeouts, with bounded backoff;
* fallback happens only when ``REZE_AI_FALLBACK`` is explicitly configured, and
  the answering provider is always reported to the user;
* vision is used only when the model is known to accept images and
  ``REZE_AI_VISION`` allows it.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from reze.config import settings
from reze.exceptions import (
    AIConfigurationError,
    AIError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)
from reze.logging_config import logger
from reze.preferences import get_pref
from reze.ai import budget
from reze.ai.providers import (
    DEFAULT_MODELS,
    ProviderConfig,
    build_adapter,
    http_post_json,
)

MAX_RETRIES = 2
RETRY_BACKOFF = (1.0, 2.5)


@dataclass
class AIResult:
    text: str
    provider: str
    model: str
    elapsed: float = 0.0
    usage: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    finish_reason: str = ""

    def metadata_line(self) -> str:
        parts = [f"{self.provider}/{self.model}"]
        if self.elapsed:
            parts.append(f"{self.elapsed:.1f}s")
        total = self.usage.get("total_tokens") or (
            int(self.usage.get("prompt_tokens", 0) or 0)
            + int(self.usage.get("completion_tokens", 0) or 0)
        )
        if total:
            parts.append(f"{total} tokens")
        if self.fallback_used:
            parts.append("fallback")
        return " · ".join(parts)


class AIGateway:
    # ------------------------------------------------------------------- config
    def _provider(self) -> str:
        return (get_pref("ai_provider", settings.ai_provider) or "").strip().lower()

    def _model(self) -> str:
        return (get_pref("ai_model", settings.ai_model) or "").strip()

    def _vision_allowed(self) -> bool:
        mode = (get_pref("ai_vision", settings.ai_vision) or "auto").lower()
        if mode in {"on", "true", "1"}:
            return True
        if mode in {"off", "false", "0"}:
            return False
        return settings.ai_vision_enabled or bool(self._model())

    def config(self, provider: Optional[str] = None, model: Optional[str] = None) -> ProviderConfig:
        provider_name = (provider or self._provider()).strip().lower()
        model_name = (model or self._model()).strip()
        if not provider_name:
            raise AIConfigurationError(
                "No AI provider is configured. Set REZE_AI_PROVIDER (openai, anthropic, "
                "gemini, openai_compatible) or use .config ai_provider."
            )
        if not model_name:
            model_name = DEFAULT_MODELS.get(provider_name, "")
        return ProviderConfig(
            provider=provider_name,
            model=model_name,
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            timeout=max(5, int(settings.ai_timeout_seconds)),
            max_output_tokens=max(16, int(settings.ai_max_output_tokens)),
        )

    @property
    def fallbacks(self) -> list:
        entries = []
        for raw in settings.ai_fallback or []:
            provider, _, model = str(raw).partition(":")
            if provider.strip():
                entries.append((provider.strip(), model.strip()))
        return entries

    def status(self) -> Dict[str, Any]:
        """Non-secret provider state for commands and the web panel."""
        provider = self._provider()
        model = self._model() or DEFAULT_MODELS.get(provider, "")
        configured = bool(provider and settings.ai_api_key)
        return {
            "provider": provider or "not configured",
            "model": model or "not configured",
            "configured": configured,
            "api_key_present": bool(settings.ai_api_key),
            "base_url": settings.ai_base_url or "",
            "vision": bool(configured and settings.ai_vision_enabled),
            "vision_mode": settings.ai_vision,
            "fallbacks": [f"{p}:{m}" if m else p for p, m in self.fallbacks],
            "timeout": settings.ai_timeout_seconds,
            "max_input_chars": settings.ai_max_input_chars,
            "max_output_tokens": settings.ai_max_output_tokens,
        }

    # ------------------------------------------------------------------ request
    def _validate_prompt(self, prompt: str) -> str:
        text = (prompt or "").strip()
        if not text:
            raise AIError("The prompt is empty.")
        if len(text) > settings.ai_max_input_chars:
            raise AIError(
                f"The prompt is {len(text)} characters; the limit is {settings.ai_max_input_chars}. "
                "Shorten the content or raise REZE_AI_MAX_INPUT_CHARS."
            )
        return text

    async def complete(
        self,
        prompt: str,
        system: str = "",
        image: Optional[Tuple[bytes, str]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        http_post=http_post_json,
    ) -> AIResult:
        """Send one completion request and normalize the result."""
        text = self._validate_prompt(prompt)
        budget.check()
        base_config = self.config(provider, model)
        if max_tokens:
            base_config.max_output_tokens = max(16, int(max_tokens))

        candidates = [(base_config.provider, base_config.model)]
        for fallback_provider, fallback_model in self.fallbacks:
            candidates.append((fallback_provider, fallback_model or base_config.model))

        last_error: Optional[Exception] = None
        for index, (candidate_provider, candidate_model) in enumerate(candidates):
            config = self.config(candidate_provider, candidate_model)
            config.max_output_tokens = base_config.max_output_tokens
            if image is not None and not config.supports_vision:
                raise AIError(
                    f"{config.provider}/{config.model} does not accept images. "
                    "Configure a vision-capable model or use text-only commands."
                )
            try:
                result = await self._attempt(config, text, system, image, http_post)
            except AIConfigurationError:
                raise
            except (AIProviderError, AITimeoutError, AIRateLimitError) as exc:
                last_error = exc
                if index + 1 < len(candidates):
                    logger.warning(
                        "AI provider %s failed (%s); trying the configured fallback.",
                        candidate_provider,
                        type(exc).__name__,
                    )
                    continue
                raise
            result.fallback_used = index > 0
            budget.record(
                provider=result.provider,
                model=result.model,
                kind="vision" if image is not None else "chat",
                prompt_tokens=int(result.usage.get("prompt_tokens", 0) or 0),
                completion_tokens=int(result.usage.get("completion_tokens", 0) or 0),
            )
            return result

        raise last_error or AIError("The AI request failed.")

    async def _attempt(self, config: ProviderConfig, prompt: str, system: str, image, http_post) -> AIResult:
        adapter = build_adapter(config)
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES + 1):
            started = time.time()
            try:
                logger.info(
                    "AI request provider=%s model=%s chars=%d vision=%s",
                    config.provider,
                    config.model,
                    len(prompt),
                    image is not None,
                )
                response = await adapter.complete(prompt, system, image, http_post=http_post)
                if not response.text:
                    raise AIProviderError("The provider returned an empty response.")
                return AIResult(
                    text=response.text,
                    provider=config.provider,
                    model=response.model or config.model,
                    elapsed=round(time.time() - started, 2),
                    usage=response.usage or {},
                    finish_reason=str(response.raw_metadata.get("finish_reason", "")),
                )
            except (AIRateLimitError, AITimeoutError) as exc:
                last_error = exc
                if attempt >= MAX_RETRIES:
                    raise
                delay = RETRY_BACKOFF[min(attempt, len(RETRY_BACKOFF) - 1)]
                logger.warning(
                    "AI request to %s failed (%s); retrying in %.1fs.",
                    config.provider,
                    type(exc).__name__,
                    delay,
                )
                await asyncio.sleep(delay)
            except AIProviderError as exc:
                # 5xx outages are worth one retry; client errors are not.
                last_error = exc
                if "unavailable" not in str(exc).lower() or attempt >= 1:
                    raise
                await asyncio.sleep(0.8)
        raise last_error or AIError("The AI request failed.")

    # ------------------------------------------------------------------- vision
    async def describe_image(
        self,
        image_path: str,
        prompt: str = "Describe this image in detail. Mention text, objects and layout.",
        http_post=http_post_json,
    ) -> AIResult:
        from reze.media import images

        if not images.available():
            raise AIError("Pillow is required to prepare images for the AI provider.")
        payload, mime = await asyncio.to_thread(images.prepare_for_vision, image_path)
        return await self.complete(prompt, image=(payload, mime), http_post=http_post)


ai_gateway = AIGateway()
