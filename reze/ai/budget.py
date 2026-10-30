"""Daily AI usage budget shared by chat, tools, council and voice."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from reze.config import settings
from reze.database import db


class BudgetExceeded(Exception):
    """Raised when the configured daily call budget is exhausted."""


def _day() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def used_today() -> int:
    row = db.query_one("SELECT COALESCE(SUM(calls), 0) AS total FROM ai_usage WHERE day = ?", (_day(),))
    return int((row or {}).get("total") or 0)


def remaining() -> int:
    return max(0, int(settings.ai_daily_budget_calls) - used_today())


def check(cost: int = 1) -> None:
    if remaining() < max(1, int(cost)):
        raise BudgetExceeded(
            f"The daily AI budget ({settings.ai_daily_budget_calls} calls) is exhausted. "
            "Raise REZE_AI_DAILY_BUDGET_CALLS or try again tomorrow (UTC)."
        )


def record(
    provider: str = "",
    model: str = "",
    kind: str = "chat",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    calls: int = 1,
) -> None:
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    try:
        db.execute(
            "INSERT INTO ai_usage (day, provider, model, kind, calls, prompt_tokens, completion_tokens, total_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(day, provider, model, kind) DO UPDATE SET calls = calls + excluded.calls, "
            "prompt_tokens = prompt_tokens + excluded.prompt_tokens, "
            "completion_tokens = completion_tokens + excluded.completion_tokens, "
            "total_tokens = total_tokens + excluded.total_tokens",
            (
                _day(),
                (provider or "")[:40],
                (model or "")[:80],
                (kind or "chat")[:20],
                max(0, int(calls)),
                max(0, int(prompt_tokens or 0)),
                max(0, int(completion_tokens or 0)),
                max(0, total),
            ),
        )
    except Exception:  # noqa: BLE001 - accounting must never break a request
        pass


def snapshot() -> Dict[str, Any]:
    rows = db.query("SELECT * FROM ai_usage WHERE day = ? ORDER BY calls DESC", (_day(),))
    return {
        "day": _day(),
        "used": used_today(),
        "limit": int(settings.ai_daily_budget_calls),
        "remaining": remaining(),
        "by_model": rows,
    }


__all__ = ["BudgetExceeded", "check", "record", "remaining", "snapshot", "used_today"]
