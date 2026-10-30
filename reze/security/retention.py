"""Retention policies: bounded local history with previewable pruning."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict

from reze.config import settings
from reze.database import db
from reze.logging_config import logger


def _cutoff(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")


def policies() -> Dict[str, int]:
    return {
        "audit_log_days": int(settings.audit_retention_days),
        "maintenance_days": int(settings.retention_days),
        "workflow_runs_days": 90,
        "inbox_read_days": int(settings.retention_days),
        "sentinel_resolved_days": 90,
    }


def preview() -> Dict[str, int]:
    limits = policies()
    counts: Dict[str, int] = {}
    checks = {
        "audit_log": ("SELECT COUNT(*) AS total FROM audit_log WHERE created_at < ?", _cutoff(limits["audit_log_days"])),
        "maintenance_runs": (
            "SELECT COUNT(*) AS total FROM maintenance_runs WHERE created_at < ?",
            _cutoff(limits["maintenance_days"]),
        ),
        "workflow_runs": (
            "SELECT COUNT(*) AS total FROM workflow_runs WHERE status IN ('done','failed','cancelled') "
            "AND finished_at != '' AND finished_at < ?",
            _cutoff(limits["workflow_runs_days"]),
        ),
        "inbox_read": (
            "SELECT COUNT(*) AS total FROM inbox_items WHERE status = 'read' AND created_at < ?",
            _cutoff(limits["inbox_read_days"]),
        ),
        "sentinel_resolved": (
            "SELECT COUNT(*) AS total FROM sentinel_findings WHERE resolved = 1 AND resolved_at != '' "
            "AND resolved_at < ?",
            _cutoff(limits["sentinel_resolved_days"]),
        ),
    }
    for name, (sql, cutoff) in checks.items():
        try:
            row = db.query_one(sql, (cutoff,))
            counts[name] = int((row or {}).get("total") or 0)
        except Exception:  # noqa: BLE001 - table missing on an old install
            counts[name] = 0
    return counts


def apply() -> Dict[str, int]:
    limits = policies()
    removed: Dict[str, int] = {}
    statements = {
        "audit_log": ("DELETE FROM audit_log WHERE created_at < ?", _cutoff(limits["audit_log_days"])),
        "maintenance_runs": (
            "DELETE FROM maintenance_runs WHERE created_at < ?",
            _cutoff(limits["maintenance_days"]),
        ),
        "workflow_runs": (
            "DELETE FROM workflow_runs WHERE status IN ('done','failed','cancelled') "
            "AND finished_at != '' AND finished_at < ?",
            _cutoff(limits["workflow_runs_days"]),
        ),
        "inbox_read": (
            "DELETE FROM inbox_items WHERE status = 'read' AND created_at < ?",
            _cutoff(limits["inbox_read_days"]),
        ),
        "sentinel_resolved": (
            "DELETE FROM sentinel_findings WHERE resolved = 1 AND resolved_at != '' AND resolved_at < ?",
            _cutoff(limits["sentinel_resolved_days"]),
        ),
    }
    for name, (sql, cutoff) in statements.items():
        try:
            removed[name] = int(db.execute(sql, (cutoff,)) or 0)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Retention skip for %s: %s", name, exc)
            removed[name] = 0
    return removed


__all__ = ["apply", "policies", "preview"]
