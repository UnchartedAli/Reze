"""Model Council: ask up to three configured models and synthesize one answer.

Honest fallbacks: with a single model it reports a single answer (no fake
consensus); failed members are listed instead of being hidden. Uses the same
credential for all providers, which is a documented limitation.
"""

from __future__ import annotations

from typing import Any, Dict, List

from reze.ai.gateway import ai_gateway
from reze.ai.providers import DEFAULT_MODELS
from reze.config import settings
from reze.features import features

MAX_MEMBERS = 3


class CouncilUnavailable(Exception):
    """Raised when the council cannot run."""


class CouncilService:
    def available(self) -> bool:
        return features.is_enabled("model_council")

    def members(self) -> List[Dict[str, str]]:
        primary_provider = (settings.ai_provider or "").strip().lower()
        primary_model = (settings.ai_model or "").strip() or DEFAULT_MODELS.get(primary_provider, "")
        members = []
        if primary_provider:
            members.append({"provider": primary_provider, "model": primary_model})
        for raw in settings.ai_fallback or []:
            provider, _, model = str(raw).partition(":")
            provider = provider.strip().lower()
            if not provider or provider == primary_provider:
                continue
            members.append({"provider": provider, "model": model.strip() or DEFAULT_MODELS.get(provider, "")})
        return members[:MAX_MEMBERS]

    async def ask(self, prompt: str, max_tokens: int = 500) -> Dict[str, Any]:
        if not self.available():
            raise CouncilUnavailable("The Model Council feature is OFF.")
        text = (prompt or "").strip()
        if not text:
            raise CouncilUnavailable("Ask a question first.")
        if not settings.ai_api_key:
            raise CouncilUnavailable("Set REZE_AI_API_KEY before using the council.")
        members = self.members()
        if not members:
            raise CouncilUnavailable("Configure REZE_AI_PROVIDER and optionally REZE_AI_FALLBACK.")

        answers: List[Dict[str, str]] = []
        errors: List[str] = []
        for member in members:
            try:
                result = await ai_gateway.complete(
                    text, provider=member["provider"], model=member["model"] or None, max_tokens=max_tokens
                )
                answers.append(
                    {
                        "provider": result.provider,
                        "model": result.model,
                        "text": result.text,
                    }
                )
            except Exception as exc:  # noqa: BLE001 - one member cannot sink the council
                errors.append(f"{member['provider']}/{member['model'] or 'default'}: {exc}"[:250])

        if not answers:
            raise CouncilUnavailable("Every council member failed: " + "; ".join(errors))

        if len(answers) == 1:
            synthesis = answers[0]["text"]
            note = "Only one model answered; this is not a consensus."
        else:
            joined = "\n\n".join(
                f"[{item['provider']}/{item['model']}]\n{item['text']}" for item in answers
            )
            synthesis_prompt = (
                "Combine the following independent answers into one concise answer. "
                "Point out genuine disagreements; do not invent agreement.\n\n" + joined
            )
            try:
                result = await ai_gateway.complete(synthesis_prompt, max_tokens=max_tokens)
                synthesis = result.text
                note = f"Synthesized from {len(answers)} models."
            except Exception as exc:  # noqa: BLE001
                synthesis = joined
                note = f"Synthesis failed ({exc}); showing the individual answers."
        return {
            "answers": answers,
            "synthesis": synthesis,
            "note": note,
            "errors": errors,
        }


council_service = CouncilService()

__all__ = ["CouncilService", "CouncilUnavailable", "MAX_MEMBERS", "council_service"]
