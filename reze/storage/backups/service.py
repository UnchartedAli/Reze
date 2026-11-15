"""Safe SQLite backups: online snapshots, optional encryption, verified restore.

REZE 4.0 changes (Milestone 1):

* Backups are encrypted with the Digital Vault key (AES-256-GCM) whenever a
  vault key is configured. Encrypted files start with ``REZEBK1`` followed by a
  12-byte nonce and the ciphertext. Without a configured key, backups stay as
  plain SQLite files, as in REZE 3.0, and the file header makes that visible.
* The encryption key is never written into a backup. It stays in the
  environment (``REZE_VAULT_KEY`` or ``REZE_SECRET_KEY``).
* Restore refuses a backup whose schema is newer than the running code
  supports, because such a database cannot be opened safely.
* Backup identifiers match exactly (numeric id, file name or full path). The
  old substring match could restore an unintended backup.
"""

from __future__ import annotations

import hmac
import os
import secrets
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta
from reze.timeutil import utcnow as _utcnow
from typing import Any, Dict, Iterator, List, Optional

from reze.config import settings
from reze.database import db
from reze.logging_config import logger
from reze.migrations import MIGRATIONS
from reze.storage import encryption
from reze.storage.encryption import VaultDecryptError, VaultLocked

RESTORE_CODE_TTL_MINUTES = 10
ENCRYPTED_MAGIC = b"REZEBK1\n"


class BackupError(Exception):
    """Raised when a backup cannot be created, verified or restored."""


def supported_schema_version() -> int:
    """Highest schema version this REZE build knows how to open."""
    return max((migration.version for migration in MIGRATIONS), default=0)


class BackupService:
    def __init__(self) -> None:
        self.directory = os.path.join(settings.data_dir or "data", "backups")

    # ------------------------------------------------------------------ helpers
    def _ensure_dir(self) -> str:
        os.makedirs(self.directory, exist_ok=True)
        return self.directory

    def _live_path(self) -> str:
        return db.db_path

    @staticmethod
    def _is_encrypted_file(path: str) -> bool:
        with open(path, "rb") as handle:
            return handle.read(len(ENCRYPTED_MAGIC)) == ENCRYPTED_MAGIC

    @staticmethod
    def _seal(plain_path: str, target: str) -> None:
        """Encrypt *plain_path* into *target* atomically (write temp, then rename)."""
        with open(plain_path, "rb") as handle:
            plaintext = handle.read()
        nonce, ciphertext = encryption.encrypt(plaintext)
        del plaintext
        partial = target + ".part"
        with open(partial, "wb") as handle:
            handle.write(ENCRYPTED_MAGIC + nonce + ciphertext)
        os.replace(partial, target)

    @contextmanager
    def _plain_copy(self, path: str) -> Iterator[str]:
        """Yield a readable plain SQLite path for *path*, decrypting if needed.

        Decrypted material lives in a private temporary file that is removed when
        the context exits. It is never placed in the backups directory.
        """
        if not self._is_encrypted_file(path):
            yield path
            return
        with open(path, "rb") as handle:
            blob = handle.read()
        header = len(ENCRYPTED_MAGIC)
        nonce = blob[header : header + encryption.NONCE_BYTES]
        ciphertext = blob[header + encryption.NONCE_BYTES :]
        try:
            plaintext = encryption.decrypt(nonce, ciphertext)
        except VaultLocked as exc:
            raise BackupError(
                "This backup is encrypted. Set REZE_VAULT_KEY to the key it was created with, then try again."
            ) from exc
        except VaultDecryptError as exc:
            raise BackupError(
                "This backup could not be decrypted. The vault key does not match or the file was modified."
            ) from exc
        fd, scratch = tempfile.mkstemp(prefix="reze-plain-", suffix=".db")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(plaintext)
            del plaintext
            yield scratch
        finally:
            try:
                os.remove(scratch)
            except OSError:
                logger.warning("Could not remove temporary decrypted backup %s.", scratch)

    # ------------------------------------------------------------------ create
    def create(self, kind: str = "manual") -> Dict[str, Any]:
        source_path = self._live_path()
        if not os.path.isfile(source_path):
            raise BackupError("The live database file does not exist yet.")
        directory = self._ensure_dir()
        stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
        suffix = secrets.token_hex(2)
        encrypted = encryption.is_configured()
        name = f"reze-{stamp}-{suffix}.db" + (".enc" if encrypted else "")
        target = os.path.join(directory, name)

        # The plain snapshot is written to a private scratch file. It becomes the
        # final file only when no encryption is configured.
        fd, scratch = tempfile.mkstemp(dir=directory, prefix=".snapshot-", suffix=".tmp")
        os.close(fd)
        try:
            try:
                source = sqlite3.connect(source_path, timeout=30)
                destination = sqlite3.connect(scratch)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
                    source.close()
            except sqlite3.Error as exc:
                raise BackupError(f"Could not copy the database: {exc}") from exc
            if encrypted:
                self._seal(scratch, target)
            else:
                os.replace(scratch, target)
        finally:
            if os.path.exists(scratch):
                os.remove(scratch)

        size = os.path.getsize(target)
        detail = f"schema v{db.schema_version}" + (", encrypted" if encrypted else ", plaintext")
        db.execute(
            "INSERT INTO backups (path, size_bytes, kind, status, detail) VALUES (?, ?, ?, 'ok', ?)",
            (target, size, (kind or "manual")[:30], detail),
        )
        logger.info("Backup created at %s (%d bytes, %s).", target, size, "encrypted" if encrypted else "plaintext")
        return {
            "path": target,
            "size": size,
            "kind": kind,
            "name": os.path.basename(target),
            "encrypted": encrypted,
        }

    # -------------------------------------------------------------------- list
    def list(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = db.query("SELECT * FROM backups ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),))
        for row in rows:
            row["exists"] = os.path.isfile(row.get("path", ""))
            if row["exists"]:
                row["size_bytes"] = os.path.getsize(row["path"])
                row["encrypted"] = self._is_encrypted_file(row["path"])
        return rows

    def resolve(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Find one backup by numeric id, exact file name or exact path.

        Partial matches are not accepted: a substring could select an unintended
        backup for restore.
        """
        text = (identifier or "").strip()
        if not text:
            return None
        if text.isdigit():
            row = db.query_one("SELECT * FROM backups WHERE id = ?", (int(text),))
            if row:
                return row
        for row in db.query("SELECT * FROM backups ORDER BY id DESC LIMIT 500"):
            path = row.get("path", "")
            if text == path or text == os.path.basename(path):
                return row
        return None

    # ------------------------------------------------------------------ verify
    def verify(self, path: str) -> Dict[str, Any]:
        if not os.path.isfile(path):
            raise BackupError("The backup file does not exist.")
        encrypted = self._is_encrypted_file(path)
        with self._plain_copy(path) as plain:
            try:
                conn = sqlite3.connect(f"file:{plain}?mode=ro", uri=True)
                try:
                    integrity = conn.execute("PRAGMA integrity_check").fetchone()
                    version = conn.execute("PRAGMA user_version").fetchone()
                    tables = {
                        row[0]
                        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
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
            "encrypted": encrypted,
            "path": path,
            "size": os.path.getsize(path),
        }

    def _check_schema(self, report: Dict[str, Any]) -> None:
        supported = supported_schema_version()
        if report["schema_version"] > supported:
            raise BackupError(
                f"The backup uses schema v{report['schema_version']}, but this REZE build supports up to "
                f"v{supported}. Upgrade REZE before restoring it."
            )

    # ----------------------------------------------------------------- restore
    def prepare_restore(self, identifier: str) -> Dict[str, Any]:
        row = self.resolve(identifier)
        if row is None:
            raise BackupError("Backup not found.")
        report = self.verify(row["path"])
        if not report["ok"]:
            raise BackupError("The backup failed its integrity check.")
        self._check_schema(report)
        code = f"{secrets.randbelow(900000) + 100000}"
        expires = (_utcnow() + timedelta(minutes=RESTORE_CODE_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
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
            if datetime.strptime(expires, "%Y-%m-%d %H:%M:%S") < _utcnow():
                raise BackupError("The confirmation code expired; prepare the restore again.")
        except ValueError as exc:
            raise BackupError("The confirmation state is invalid; prepare the restore again.") from exc

        report = self.verify(stored_path)
        if not report["ok"]:
            raise BackupError("The backup failed its integrity check.")
        self._check_schema(report)
        live_version = db.schema_version

        safety = self.create(kind="pre-restore")
        live = self._live_path()
        try:
            with self._plain_copy(stored_path) as plain:
                source = sqlite3.connect(plain, timeout=30)
                destination = sqlite3.connect(live, timeout=30)
                try:
                    source.backup(destination)
                finally:
                    destination.close()
                    source.close()
        except sqlite3.Error as exc:
            raise BackupError(
                f"Restore failed; the pre-restore backup is at {safety['path']}: {exc}"
            ) from exc

        for key in ("backup.restore_code", "backup.restore_path", "backup.restore_expires"):
            db.delete_setting(key)
        logger.warning("Database restored from %s (safety copy: %s).", stored_path, safety["path"])
        return {
            "path": stored_path,
            "safety": safety["path"],
            "schema_version": report["schema_version"],
            # An older schema is upgraded by the migration runner at the next start.
            "restart_required": report["schema_version"] != live_version,
            "encrypted": report["encrypted"],
        }

    # ------------------------------------------------------------------- prune
    def prune(self, keep: int = 10) -> int:
        rows = db.query("SELECT * FROM backups ORDER BY id DESC")
        removed = 0
        for row in rows[max(0, int(keep)) :]:
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
        return round((_utcnow() - stamp).total_seconds() / 86400, 1)


backup_service = BackupService()

__all__ = ["BackupError", "BackupService", "backup_service", "supported_schema_version"]
