"""Safe SQLite backups with verification and explicit restore confirmation."""

from __future__ import annotations

import hmac
import os
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from reze.config import settings
from reze.database import db
from reze.logging_config import logger

RESTORE_CODE_TTL_MINUTES = 10


class BackupError(Exception):
    """Raised when a backup cannot be created, verified or restored."""


class BackupService:
    def __init__(self) -> None:
        self.directory = os.path.join(settings.data_dir or "data", "backups")

    # ------------------------------------------------------------------ helpers
    def _ensure_dir(self) -> str:
        os.makedirs(self.directory, exist_ok=True)
        return self.directory

    def _live_path(self) -> str:
        return db.db_path

    # ------------------------------------------------------------------ create
    def create(self, kind: str = "manual") -> Dict[str, Any]:
        source_path = self._live_path()
        if not os.path.isfile(source_path):
            raise BackupError("The live database file does not exist yet.")
        directory = self._ensure_dir()
        stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        suffix = secrets.token_hex(2)
        target = os.path.join(directory, f"reze-{stamp}-{suffix}.db")
        try:
            source = sqlite3.connect(source_path, timeout=30)
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
        except sqlite3.Error as exc:
            raise BackupError(f"Could not copy the database: {exc}") from exc
        size = os.path.getsize(target)
        db.execute(
            "INSERT INTO backups (path, size_bytes, kind, status, detail) VALUES (?, ?, ?, 'ok', ?)",
            (target, size, (kind or "manual")[:30], f"schema v{db.schema_version}"),
        )
        logger.info("Backup created at %s (%d bytes).", target, size)
        return {"path": target, "size": size, "kind": kind, "name": os.path.basename(target)}

    # -------------------------------------------------------------------- list
    def list(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = db.query("SELECT * FROM backups ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),))
        for row in rows:
            row["exists"] = os.path.isfile(row.get("path", ""))
            if row["exists"]:
                row["size_bytes"] = os.path.getsize(row["path"])
        return rows

    def resolve(self, identifier: str) -> Optional[Dict[str, Any]]:
        text = (identifier or "").strip()
        if not text:
            return None
        if text.isdigit():
            row = db.query_one("SELECT * FROM backups WHERE id = ?", (int(text),))
            if row:
                return row
        return db.query_one(
            "SELECT * FROM backups WHERE path LIKE ? ORDER BY id DESC LIMIT 1",
            (f"%{text}%",),
        )

    # ------------------------------------------------------------------ verify
    def verify(self, path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            raise BackupError("The backup file does not exist.")
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                integrity = conn.execute("PRAGMA integrity_check").fetchone()
                version = conn.execute("PRAGMA user_version").fetchone()
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            finally:
                conn.close()
        except sqlite3.Error as exc:
            raise BackupError(f"The backup is not a readable SQLite file: {exc}") from exc
        ok = bool(integrity and integrity[0] == "ok")
        return {
            "ok": ok,
            "integrity": integrity[0] if integrity else "unknown",
            "schema_version": int(version[0]) if version else 0,
            "core_tables": sorted({"global_settings", "profile_settings"} & tables),
            "path": path,
            "size": os.path.getsize(path),
        }

    # ----------------------------------------------------------------- restore
    def prepare_restore(self, identifier: str) -> Dict[str, Any]:
        row = self.resolve(identifier)
        if row is None:
            raise BackupError("Backup not found.")
        report = self.verify(row["path"])
        if not report["ok"]:
            raise BackupError("The backup failed its integrity check.")
        code = f"{secrets.randbelow(900000) + 100000}"
        expires = (datetime.utcnow() + timedelta(minutes=RESTORE_CODE_TTL_MINUTES)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        db.set_setting("backup.restore_code", code)
        db.set_setting("backup.restore_path", row["path"])
        db.set_setting("backup.restore_expires", expires)
        return {"code": code, "expires": expires, "path": row["path"], "report": report}

    def restore(self, code: str) -> Dict[str, Any]:
        stored_code = db.get_setting("backup.restore_code", "") or ""
        stored_path = db.get_setting("backup.restore_path", "") or ""
        expires = db.get_setting("backup.restore_expires", "") or ""
        if not stored_code or not stored_path:
            raise BackupError("No restore was prepared. Run .backup restore <id> first.")
        if not hmac.compare_digest(str(code).strip(), stored_code):
            raise BackupError("The confirmation code does not match.")
        try:
            if datetime.strptime(expires, "%Y-%m-%d %H:%M:%S") < datetime.utcnow():
                raise BackupError("The confirmation code expired; prepare the restore again.")
        except ValueError as exc:
            raise BackupError("The confirmation state is invalid; prepare the restore again.") from exc

        report = self.verify(stored_path)
        if not report["ok"]:
            raise BackupError("The backup failed its integrity check.")

        safety = self.create(kind="pre-restore")
        live = self._live_path()
        try:
            source = sqlite3.connect(stored_path, timeout=30)
            destination = sqlite3.connect(live, timeout=30)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
        except sqlite3.Error as exc:
            raise BackupError(f"Restore failed; the pre-restore backup is at {safety['path']}: {exc}") from exc

        for key in ("backup.restore_code", "backup.restore_path", "backup.restore_expires"):
            db.delete_setting(key)
        logger.warning("Database restored from %s (safety copy: %s).", stored_path, safety["path"])
        return {"path": stored_path, "safety": safety["path"], "schema_version": report["schema_version"]}

    # ------------------------------------------------------------------- prune
    def prune(self, keep: int = 10) -> int:
        rows = db.query("SELECT * FROM backups ORDER BY id DESC")
        removed = 0
        for row in rows[max(0, int(keep)):]:
            path = row.get("path", "")
            try:
                if path and os.path.isfile(path):
                    os.remove(path)
                db.execute("DELETE FROM backups WHERE id = ?", (row["id"],))
                removed += 1
            except OSError as exc:
                logger.warning("Could not remove old backup %s: %s", path, exc)
        return removed

    def latest_age_days(self) -> Optional[float]:
        rows = self.list(limit=1)
        if not rows:
            return None
        try:
            stamp = datetime.strptime(str(rows[0]["created_at"])[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None
        return round((datetime.utcnow() - stamp).total_seconds() / 86400, 1)


backup_service = BackupService()

__all__ = ["BackupError", "BackupService", "backup_service"]
