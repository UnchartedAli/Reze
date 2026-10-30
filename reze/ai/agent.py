"""AI Agent: turns a natural-language request into a *proposal* only.

The model never executes anything. It returns JSON naming one allowlisted tool
and its arguments; REZE validates it and creates an approval code that the owner
must confirm. If no provider is configured the command says so instead of
pretending an agent exists.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from reze.ai.gateway import ai_gateway
from reze.ai.tools.registry import TOOLS, ToolError, describe_tools, tool_registry
from reze.config import settings
from reze.features import features

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class AgentUnavailable(Exception):
    """Raised when the agent cannot run on this installation."""


SYSTEM_PROMPT = (
    "You are the REZE tool planner. Reply with ONE JSON object and nothing else.\n"
    "Schema: {\"tool\": \"<tool name>\", \"args\": {...}}\n"
    "Use only the tools listed below. Never invent tools, never include prose, "
    "never include secrets. If no tool fits, reply {\"tool\": \"\", \"args\": {}}.\n"
    "Tools:\n{tools}"
)


class AgentService:
    def available(self) -> bool:
        return features.is_enabled("ai_agent")

    def configured(self) -> bool:
        provider = (settings.ai_provider or "").strip()
        return bool(provider and settings.ai_api_key)

    def tool_catalog_prompt(self) -> str:
        lines = []
        for item in describe_tools():
            args = ", ".join(f"{name}:{kind}" for name, kind in item["args"].items()) or "none"
            lines.append(f"- {item['name']} ({args}) - {item['description']}")
        return "\n".join(lines)

    async def propose_from_text(
        self, text: str, chat_id: int = 0, actor: int = 0
    ) -> Dict[str, Any]:
        if not self.available():
            raise AgentUnavailable("The AI Agent feature is OFF.")
        if not self.configured():
            raise AgentUnavailable(
                "No AI provider is configured. Set REZE_AI_PROVIDER, REZE_AI_MODEL and REZE_AI_API_KEY."
            )
        prompt = (text or "").strip()
        if not prompt:
            raise AgentUnavailable("Describe what you want the agent to prepare.")
        if len(prompt) > 2000:
            raise AgentUnavailable("Keep the request under 2000 characters.")
        result = await ai_gateway.complete(
            prompt,
            system=SYSTEM_PROMPT.format(tools=self.tool_catalog_prompt()),
            max_tokens=300,
        )
        parsed = self._parse(result.text)
        tool = str(parsed.get("tool") or "").strip()
        args = parsed.get("args") or {}
        if not tool:
            raise ToolError("The model did not propose a tool for this request.")
        if tool not in TOOLS:
            raise ToolError(f"The model proposed an unknown tool '{tool}'.")
        proposal = tool_registry.propose(tool, args, chat_id=chat_id, actor=actor)
        proposal["provider"] = f"{result.provider}/{result.model}"
        return proposal

    async def propose_direct(
        self, tool: str, args: Dict[str, Any], chat_id: int = 0, actor: int = 0
    ) -> Dict[str, Any]:
        if not self.available():
            raise AgentUnavailable("The AI Agent feature is OFF.")
        if tool not in TOOLS:
            raise ToolError(f"Unknown tool '{tool}'. Use .agent tools.")
        return tool_registry.propose(tool, args or {}, chat_id=chat_id, actor=actor)

    @staticmethod
    def _parse(text: str) -> Dict[str, Any]:
        body = (text or "").strip()
        if body.startswith("```"):
            body = body.strip("`")
            body = body.split("\n", 1)[1] if "\n" in body else body
        match = _JSON_RE.search(body)
        if not match:
            raise ToolError("The model did not return a tool JSON object.")
        try:
            data = json.loads(match.group(0))
        except ValueError as exc:
            raise ToolError("The model returned invalid JSON; nothing was executed.") from exc
        if not isinstance(data, dict):
            raise ToolError("The model returned JSON that is not an object.")
        return data


agent_service = AgentService()

__all__ = ["AgentService", "AgentUnavailable", "agent_service"]
