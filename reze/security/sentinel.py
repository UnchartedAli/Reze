"""Security Sentinel: proactive, local security checks for the owner.

Checks never send data anywhere and never print secrets. Findings are stored so
``.sentinel`` can show what changed since the previous run.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List

from reze.config import settings
from reze.database import db
from reze.logging_config import logger
from reze.storage import encryption


@dataclass
class Finding:
    check: str
    severity: str  # info | warning | critical
    title: str
    detail: str = ""


def _check_panel_password() -> List[Finding]:
    if settings.has_panel_credentials:
        return []
    return [
        Finding(
            "panel_password",
            "critical",
            "The web panel has no password",
            "Set REZE_PANEL_PASSWORD or REZE_PANEL_PASSWORD_HASH.",
        )
    ]


def _check_secret_key() -> List[Finding]:
    if settings.secret_key != encryption.DEFAULT_SECRET:
        return []
    return [
        Finding(
            "secret_key",
            "warning",
            "REZE_SECRET_KEY is the default value",
            "Change it; the default is public and also disables the Digital Vault.",
        )
    ]


def _check_vault_key() -> List[Finding]:
    if encryption.is_configured():
        return []
    return [
        Finding(
            "vault_key",
            "warning",
            "The Digital Vault is locked",
            "Set REZE_VAULT_KEY to a long random value to enable encrypted storage.",
        )
    ]


def _check_backups() -> List[Finding]:
    from reze.storage.backups.service import backup_service

    try:
        age = backup_service.latest_age_days()
    except Exception:  # pragma: no cover
        return []
    if age is None:
        return [
            Finding("backups", "warning", "No database backup yet", "Run .backup create.")
        ]
    if age > max(1, int(settings.retention_days / 30)):
        return [
            Finding(
                "backups",
                "warning",
                "The latest backup is old",
                f"Last backup: {age} days ago. Run .backup create.",
            )
        ]
    return []


def _check_database() -> List[Finding]:
    try:
        with db.get_connection() as conn:
            row = conn.execute("PRAGMA quick_check").fetchone()
            mode = conn.execute("PRAGMA journal_mode").fetchone()
    except sqlite3.Error as exc:
        return [Finding("database", "critical", "Database check failed", str(exc)[:200])]
    findings = []
    if row and row[0] != "ok":
        findings.append(Finding("database", "critical", "Database integrity problem", str(row[0])[:200]))
    if mode and str(mode[0]).lower() != "wal":
        findings.append(Finding("database", "info", "WAL mode is not active", f"journal_mode={mode[0]}"))
    return findings


def _check_session_permissions() -> List[Finding]:
    path = settings.session_path
    if not path or not os.path.isfile(path) or os.name == "nt":
        return []
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        return []
    if mode & 0o077:
        return [
            Finding(
                "session_permissions",
                "critical",
                "The Telegram session file is readable by other users",
                f"{path} has mode {oct(mode)}; run: chmod 600 {path}",
            )
        ]
    return []


def _check_optional_features() -> List[Finding]:
    from reze.features import FEATURES, features

    sensitive = [spec.key for spec in FEATURES if spec.sensitive and features.is_enabled(spec.key)]
    if not sensitive:
        return []
    return [
        Finding(
            "optional_features",
            "info",
            "Sensitive optional features are enabled",
            ", ".join(sensitive),
        )
    ]


def _check_retention() -> List[Finding]:
    cutoff = (datetime.utcnow() - timedelta(days=max(30, int(settings.audit_retention_days)))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    row = db.query_one("SELECT COUNT(*) AS total FROM audit_log WHERE created_at < ?", (cutoff,))
    total = int((row or {}).get("total") or 0)
    if total > 5000:
        return [
            Finding(
                "retention",
                "info",
                "Old audit rows can be pruned",
                f"{total} rows are older than {settings.audit_retention_days} days. Run .maintain prune.",
            )
        ]
    return []


CHECKS = (
    _check_panel_password,
    _check_secret_key,
    _check_vault_key,
    _check_backups,
    _check_database,
    _check_session_permissions,
    _check_optional_features,
    _check_retention,
)


class SentinelService:
    def run(self) -> List[Dict[str, Any]]:
        findings: List[Finding] = []
        for check in CHECKS:
            try:
                findings.extend(check())
            except Exception as exc:  # noqa: BLE001 - one check cannot break the rest
                logger.debug("Sentinel check %s failed: %s", check.__name__, exc)
        try:
            db.execute("DELETE FROM sentinel_findings WHERE resolved = 0")
            for finding in findings:
                db.execute(
                    "INSERT INTO sentinel_findings (check_name, severity, title, detail) "
                    "VALUES (?, ?, ?, ?)",
                    (finding.check, finding.severity, finding.title[:200], finding.detail[:1000]),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not persist sentinel findings: %s", exc)
        return [finding.__dict__ for finding in findings]

    def open(self, limit: int = 20) -> List[Dict[str, Any]]:
        return db.query(
            "SELECT * FROM sentinel_findings WHERE resolved = 0 ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 100)),),
        )

    def resolve(self, finding_id: int) -> bool:
        db.execute(
            "UPDATE sentinel_findings SET resolved = 1, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(finding_id),),
        )
        return True

    def summary(self) -> Dict[str, Any]:
        rows = self.open(limit=100)
        critical = sum(1 for row in rows if row.get("severity") == "critical")
        warning = sum(1 for row in rows if row.get("severity") == "warning")
        return {"total": len(rows), "critical": critical, "warning": warning, "findings": rows}


sentinel_service = SentinelService()

__all__ = ["Finding", "SentinelService", "sentinel_service"]
