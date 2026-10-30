"""Strictly allowlisted AI tools with approval gates and an audit trail.

Nothing here executes model output directly. A tool call must:

1. exist in :data:`TOOLS` (no dynamic import, no eval);
2. pass an exact argument-schema check (unknown fields rejected);
3. have its optional feature enabled;
4. be proposed first and approved by the owner with a short code;
5. stay within the daily AI budget.

Every proposal, denial and execution is written to ``ai_tool_audit``.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, List, Optional

from reze.ai import budget
from reze.config import settings
from reze.database import db
from reze.features import features
from reze.logging_config import logger
from reze.permissions import PermissionManager

APPROVAL_TTL_MINUTES = 15


class ToolError(Exception):
    """Raised for an invalid, disabled or unknown tool call."""


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: Dict[str, type]
    handler: Callable[[Dict[str, Any]], Awaitable[str]]
    feature: Optional[str] = None
    requires_approval: bool = True
    max_calls_per_day: int = 20


async def _memory_save(args: Dict[str, Any]) -> str:
    from reze.personal.memory import memory_service

    memory_id = memory_service.save(args["content"], source="ai_tool", tags=args.get("tags", ""))
    return f"Saved memory #{memory_id}."


async def _memory_search(args: Dict[str, Any]) -> str:
    from reze.personal.memory import memory_service

    rows = memory_service.search(args["query"], limit=int(args.get("limit", 5)))
    if not rows:
        return "No memories matched."
    return "\n".join(f"#{row['id']} {row['content'][:140]}" for row in rows)


async def _task_add(args: Dict[str, Any]) -> str:
    from reze.personal.projects import project_service

    task_id = project_service.add_task(
        args["title"], project=args.get("project", ""), priority=int(args.get("priority", 3))
    )
    return f"Added task #{task_id}."


async def _timeline_add(args: Dict[str, Any]) -> str:
    from reze.personal.timeline import timeline_service

    event_id = timeline_service.append("ai", args["title"], args.get("body", ""), source="ai_tool")
    return f"Added timeline event #{event_id}."


async def _feature_list(args: Dict[str, Any]) -> str:
    rows = features.snapshot()
    enabled = [row["key"] for row in rows if row["enabled"]]
    return "Enabled: " + (", ".join(enabled) if enabled else "none (all optional features are OFF)")


async def _budget_status(args: Dict[str, Any]) -> str:
    snapshot = budget.snapshot()
    return f"AI calls today: {snapshot['used']}/{snapshot['limit']}."


TOOLS: Dict[str, Tool] = {
    tool.name: tool
    for tool in (
        Tool(
            "memory.save",
            "Save a durable memory for later recall.",
            {"content": str, "tags": str},
            _memory_save,
            feature="memory",
            max_calls_per_day=10,
        ),
        Tool(
            "memory.search",
            "Search saved memories.",
            {"query": str, "limit": int},
            _memory_search,
            feature="memory",
            max_calls_per_day=20,
        ),
        Tool(
            "task.add",
            "Add a local task.",
            {"title": str, "project": str, "priority": int},
            _task_add,
            feature="projects",
            max_calls_per_day=10,
        ),
        Tool(
            "timeline.add",
            "Append an event to the timeline.",
            {"title": str, "body": str},
            _timeline_add,
            feature="timeline",
            max_calls_per_day=10,
        ),
        Tool(
            "features.list",
            "List optional feature states.",
            {},
            _feature_list,
            feature=None,
            max_calls_per_day=20,
        ),
        Tool(
            "budget.status",
            "Show today's AI usage.",
            {},
            _budget_status,
            feature=None,
            max_calls_per_day=20,
        ),
    )
}

_ARG_LIMITS = {str: 4000, int: 1_000_000}


def describe_tools() -> List[Dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "args": {name: kind.__name__ for name, kind in tool.args.items()},
            "feature": tool.feature or "-",
            "enabled": (tools_enabled(tool.name)),
        }
        for tool in TOOLS.values()
    ]


def tools_enabled(name: str) -> bool:
    tool = TOOLS.get(name)
    if tool is None:
        return False
    return not tool.feature or features.is_enabled(tool.feature)


def validate_args(tool: Tool, args: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolError("Tool arguments must be a JSON object.")
    unknown = set(args) - set(tool.args)
    if unknown:
        raise ToolError(f"Unknown argument(s): {', '.join(sorted(unknown))}")
    cleaned: Dict[str, Any] = {}
    for name, expected in tool.args.items():
        if name not in args:
            continue
        value = args[name]
        if expected is int:
            try:
                value = int(value)
            except (TypeError, ValueError) as exc:
                raise ToolError(f"'{name}' must be an integer.") from exc
        elif expected is str:
            if not isinstance(value, str):
                raise ToolError(f"'{name}' must be a string.")
            value = value.strip()[: _ARG_LIMITS[str]]
        cleaned[name] = value
    required = {
        "memory.save": ("content",),
        "memory.search": ("query",),
        "task.add": ("title",),
        "timeline.add": ("title",),
    }.get(tool.name, ())
    missing = [name for name in required if not str(cleaned.get(name) or "").strip()]
    if missing:
        raise ToolError(f"Missing required argument(s): {', '.join(missing)}")
    return cleaned


class ToolRegistry:
    def _audit(
        self,
        request_id: str,
        tool: str,
        args: Dict[str, Any],
        status: str,
        actor: int = 0,
        approval_id: Optional[int] = None,
        result: str = "",
        error: str = "",
    ) -> None:
        try:
            db.execute(
                "INSERT INTO ai_tool_audit (request_id, tool, args, status, actor, approval_id, result, error) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request_id[:64],
                    tool[:60],
                    json.dumps(args, ensure_ascii=False)[:4000],
                    status[:20],
                    int(actor or 0),
                    approval_id,
                    result[:2000],
                    error[:1000],
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool audit write failed: %s", exc)

    def propose(self, tool_name: str, args: Dict[str, Any], chat_id: int = 0, actor: int = 0) -> Dict[str, Any]:
        if not PermissionManager.is_owner(int(actor or 0)):
            raise ToolError("Only the owner can propose tool calls.")
        if not features.is_enabled("ai_agent"):
            raise ToolError("The AI Agent feature is OFF.")
        tool = TOOLS.get(tool_name)
        if tool is None:
            raise ToolError(f"Unknown tool '{tool_name}'. Use .agent tools.")
        if tool.feature and not features.is_enabled(tool.feature):
            raise ToolError(f"Tool '{tool_name}' needs the '{tool.feature}' feature enabled.")
        cleaned = validate_args(tool, args or {})
        if self._daily_count(tool_name) >= tool.max_calls_per_day:
            raise ToolError(f"Tool '{tool_name}' reached its daily limit.")

        code = f"{secrets.randbelow(900000) + 100000}"
        expires = (datetime.utcnow() + timedelta(minutes=APPROVAL_TTL_MINUTES)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        approval_id = db.execute(
            "INSERT INTO ai_approvals (code, tool, args, chat_id, user_id, expires_at, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (
                code,
                tool.name,
                json.dumps(cleaned, ensure_ascii=False)[:4000],
                int(chat_id or 0),
                int(actor or 0),
                expires,
            ),
        )
        request_id = secrets.token_hex(6)
        self._audit(request_id, tool.name, cleaned, "proposed", actor, approval_id)
        return {
            "approval_id": approval_id,
            "code": code,
            "tool": tool.name,
            "args": cleaned,
            "expires": expires,
            "request_id": request_id,
        }

    def _daily_count(self, tool_name: str) -> int:
        row = db.query_one(
            "SELECT COUNT(*) AS total FROM ai_tool_audit WHERE tool = ? AND status = 'executed' "
            "AND date(created_at) = date('now')",
            (tool_name,),
        )
        return int((row or {}).get("total") or 0)

    def get_approval(self, code: str) -> Optional[Dict[str, Any]]:
        return db.query_one(
            "SELECT * FROM ai_approvals WHERE code = ? AND status = 'pending'", (str(code).strip(),)
        )

    def pending(self, limit: int = 10) -> List[Dict[str, Any]]:
        return db.query(
            "SELECT id, code, tool, args, created_at, expires_at FROM ai_approvals "
            "WHERE status = 'pending' ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 50)),),
        )

    async def approve(self, code: str, actor: int = 0) -> Dict[str, Any]:
        if not PermissionManager.is_owner(int(actor or 0)):
            raise ToolError("Only the owner can approve tool calls.")
        row = self.get_approval(code)
        if row is None:
            raise ToolError("No pending approval with that code.")
        if self._expired(row.get("expires_at")):
            db.execute("UPDATE ai_approvals SET status = 'expired' WHERE id = ?", (row["id"],))
            raise ToolError("This approval expired; propose the tool again.")
        tool = TOOLS.get(row["tool"])
        if tool is None:
            raise ToolError("The tool no longer exists.")
        if tool.feature and not features.is_enabled(tool.feature):
            raise ToolError(f"Tool '{tool.name}' needs the '{tool.feature}' feature enabled.")
        budget.check()
        try:
            args = json.loads(row.get("args") or "{}")
            cleaned = validate_args(tool, args)
            result = await tool.handler(cleaned)
        except Exception as exc:  # noqa: BLE001
            db.execute(
                "UPDATE ai_approvals SET status = 'failed', result = ? WHERE id = ?",
                (str(exc)[:1000], row["id"]),
            )
            self._audit("approval", tool.name, {}, "failed", actor, row["id"], error=str(exc))
            raise ToolError(f"The tool failed: {exc}") from exc
        db.execute(
            "UPDATE ai_approvals SET status = 'approved', result = ? WHERE id = ?",
            (str(result)[:2000], row["id"]),
        )
        self._audit("approval", tool.name, cleaned, "executed", actor, row["id"], result=str(result))
        budget.record(kind="tool", calls=1, provider="tools", model=tool.name)
        return {"tool": tool.name, "result": result, "approval_id": row["id"]}

    def deny(self, code: str, actor: int = 0) -> bool:
        if not PermissionManager.is_owner(int(actor or 0)):
            raise ToolError("Only the owner can deny tool calls.")
        row = self.get_approval(code)
        if row is None:
            return False
        db.execute("UPDATE ai_approvals SET status = 'denied' WHERE id = ?", (row["id"],))
        self._audit("approval", row["tool"], {}, "denied", actor, row["id"])
        return True

    def cancel(self, code: str, actor: int = 0) -> bool:
        return self.deny(code, actor)

    def history(self, limit: int = 20) -> List[Dict[str, Any]]:
        return db.query("SELECT * FROM ai_tool_audit ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),))

    @staticmethod
    def _expired(value: Any) -> bool:
        try:
            return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S") < datetime.utcnow()
        except (ValueError, TypeError):
            return True


tool_registry = ToolRegistry()

__all__ = [
    "APPROVAL_TTL_MINUTES",
    "TOOLS",
    "Tool",
    "ToolError",
    "ToolRegistry",
    "describe_tools",
    "tool_registry",
    "tools_enabled",
    "validate_args",
]
