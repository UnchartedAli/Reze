"""Insight Engine: local statistics about the owner's week (no AI required)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from reze.database import db
from reze.personal.crm import crm_service
from reze.personal.decisions import decision_service
from reze.personal.expenses import expense_service
from reze.personal.focus import focus_service
from reze.personal.life_graph import life_graph
from reze.personal.memory import memory_service
from reze.personal.projects import project_service
from reze.personal.timeline import timeline_service
from reze.personal.writing import writing_service


def _cutoff(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")


def snapshot(days: int = 7) -> Dict[str, Any]:
    cutoff = _cutoff(days)
    counts = {}
    queries = {
        "memories": ("SELECT COUNT(*) AS total FROM memories WHERE created_at >= ?", (cutoff,)),
        "decisions": ("SELECT COUNT(*) AS total FROM decisions WHERE created_at >= ?", (cutoff,)),
        "tasks_done": (
            "SELECT COUNT(*) AS total FROM tasks WHERE status = 'done' AND completed_at >= ?",
            (cutoff,),
        ),
        "timeline": ("SELECT COUNT(*) AS total FROM timeline_events WHERE created_at >= ?", (cutoff,)),
        "interactions": (
            "SELECT COUNT(*) AS total FROM crm_interactions WHERE created_at >= ?",
            (cutoff,),
        ),
    }
    for name, (sql, params) in queries.items():
        row = db.query_one(sql, params)
        counts[name] = int((row or {}).get("total") or 0)

    focus = focus_service.stats(days=days)
    expenses = expense_service.summary()
    return {
        "days": days,
        "counts": counts,
        "focus": focus,
        "expenses": expenses,
        "tasks": project_service.summary(),
        "contacts": crm_service.count(),
        "decisions_total": decision_service.count(),
        "memories_total": memory_service.count(),
        "writing_samples": writing_service.count(),
        "graph": life_graph.count(),
        "timeline_total": timeline_service.count(),
        "search_total": int(
            (db.query_one("SELECT COUNT(*) AS total FROM search_index") or {}).get("total") or 0
        ),
    }


def narrative(data: Dict[str, Any]) -> List[str]:
    """Turn the snapshot into short, factual lines (no invented metrics)."""
    counts = data.get("counts") or {}
    focus = data.get("focus") or {}
    tasks = data.get("tasks") or {}
    expenses = data.get("expenses") or {}
    lines = [
        f"Period: last {data.get('days', 7)} days",
        f"Memories saved: {counts.get('memories', 0)} (total {data.get('memories_total', 0)})",
        f"Decisions logged: {counts.get('decisions', 0)} (total {data.get('decisions_total', 0)})",
        f"Tasks completed: {counts.get('tasks_done', 0)} · open now: {tasks.get('open', 0)}"
        f" · overdue: {tasks.get('overdue', 0)}",
        f"Focus: {focus.get('minutes', 0)} min in {focus.get('completed', 0)} completed sessions"
        f" ({focus.get('completion_rate', 0)}% completion)",
        f"CRM interactions: {counts.get('interactions', 0)} · contacts: {data.get('contacts', 0)}",
        f"Timeline events: {counts.get('timeline', 0)} · indexed records: {data.get('search_total', 0)}",
    ]
    totals = expenses.get("totals") or {}
    if totals:
        formatted = ", ".join(f"{value:g} {currency}" for currency, value in totals.items())
        lines.append(f"Expenses this month: {formatted}")
    if not any(counts.values()) and not focus.get("sessions"):
        lines.append("Not enough activity yet for trends — this is normal on a fresh install.")
    return lines


__all__ = ["narrative", "snapshot"]
