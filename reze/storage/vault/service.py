"""Digital Vault: encrypted secrets and small files, owner-only."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.logging_config import logger
from reze.search import universal
from reze.storage import encryption
from reze.storage.encryption import VaultDecryptError, VaultLocked

MAX_SECRET_BYTES = 64 * 1024
MAX_FILE_BYTES = 10 * 1024 * 1024


class VaultService:
    @property
    def configured(self) -> bool:
        return encryption.is_configured()

    def set_secret(self, name: str, value: str) -> int:
        extra = (value or "").encode("utf-8")
        if len(extra) > MAX_SECRET_BYTES:
            raise ValueError("Vault secrets are limited to 64 KB; use a file entry instead.")
        return self._store(name, "secret", extra, filename="", mime="text/plain")

    def put_file(self, name: str, path: str, mime: str = "") -> int:
        if not os.path.isfile(path):
            raise ValueError(f"No file at {path}.")
        size = os.path.getsize(path)
        if size > MAX_FILE_BYTES:
            raise ValueError("Vault files are limited to 10 MB.")
        with open(path, "rb") as handle:
            payload = handle.read()
        return self._store(name, "file", payload, filename=os.path.basename(path), mime=mime)

    def _store(self, name: str, kind: str, payload: bytes, filename: str, mime: str) -> int:
        cleaned = " ".join((name or "").split())
        if not cleaned:
            raise ValueError("A Vault entry needs a name.")
        cleaned = cleaned[:120]
        nonce, ciphertext = encryption.encrypt(payload)
        # Names are unique case-insensitively, so "Token" and "token" address
        # the same entry instead of silently creating a duplicate.
        existing = self.get_meta(cleaned)
        if existing:
            db.execute(
                "UPDATE vault_entries SET name = ?, kind = ?, filename = ?, mime = ?, size = ?, "
                "nonce = ?, ciphertext = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (cleaned, kind, filename[:200], mime[:100], len(payload), nonce, ciphertext, existing["id"]),
            )
        else:
            db.execute(
                "INSERT INTO vault_entries (name, kind, filename, mime, size, nonce, ciphertext) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cleaned, kind, filename[:200], mime[:100], len(payload), nonce, ciphertext),
            )
        row = self.get_meta(cleaned)
        if row:
            # Only the name is indexed; the encrypted payload never is.
            universal.index("vault", row["id"], row["name"], f"{row['kind']} {row['filename']}", "vault")
        logger.info("Vault entry '%s' stored (%s, %d bytes).", cleaned, kind, len(payload))
        return int(row["id"]) if row else 0

    def get_meta(self, name: str) -> Optional[Dict[str, Any]]:
        row = db.query_one(
            "SELECT id, name, kind, filename, mime, size, created_at, updated_at, accessed_at, "
            "access_count FROM vault_entries WHERE lower(name) = lower(?)",
            ((name or "").strip(),),
        )
        return row

    def get_secret(self, name: str) -> str:
        payload = self._read(name)
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            raise VaultDecryptError("This entry is a file, not a text secret.")

    def get_file_bytes(self, name: str) -> bytes:
        return self._read(name)

    def export(self, name: str, path: str) -> str:
        payload = self._read(name)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def _read(self, name: str) -> bytes:
        cleaned = (name or "").strip()
        row = db.query_one("SELECT * FROM vault_entries WHERE lower(name) = lower(?)", (cleaned,))
        if row is None:
            raise KeyError(cleaned)
        payload = encryption.decrypt(row["nonce"], row["ciphertext"])
        db.execute(
            "UPDATE vault_entries SET accessed_at = CURRENT_TIMESTAMP, access_count = access_count + 1 "
            "WHERE id = ?",
            (row["id"],),
        )
        return payload

    def list(self, limit: int = 50) -> List[Dict[str, Any]]:
        return db.query(
            "SELECT id, name, kind, filename, mime, size, created_at, updated_at, accessed_at, "
            "access_count FROM vault_entries ORDER BY name LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )

    def delete(self, name: str) -> bool:
        row = self.get_meta(name)
        if row is None:
            return False
        db.execute("DELETE FROM vault_entries WHERE id = ?", (row["id"],))
        universal.unindex("vault", row["id"])
        return True

    def status(self) -> Dict[str, Any]:
        row = db.query_one("SELECT COUNT(*) AS total, COALESCE(SUM(size), 0) AS bytes FROM vault_entries")
        return {
            "configured": self.configured,
            "fingerprint": encryption.fingerprint(),
            "entries": int((row or {}).get("total") or 0),
            "bytes": int((row or {}).get("bytes") or 0),
        }


vault_service = VaultService()

__all__ = ["VaultDecryptError", "VaultLocked", "VaultService", "vault_service"]
