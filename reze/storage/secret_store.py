"""Secrets at rest: encrypted with REZE_VAULT_KEY (AES-256-GCM).

Writing needs REZE_VAULT_KEY. Without it nothing is stored, so a secret is never kept in plain text.
A secret can be imported once from an environment variable. After the import the variable can be
removed, and the value is read from the encrypted store.
"""

from __future__ import annotations

import base64
import os
from typing import Optional

from reze.config import settings
from reze.database import db
from reze.storage import encryption
from reze.storage.encryption import VaultDecryptError, VaultLocked

PREFIX = "v1:"
NONCE_BYTES = encryption.NONCE_BYTES


class SecretStoreError(RuntimeError):
    """A secret cannot be stored or opened. The message is safe to show the owner."""


def _key(name: str) -> str:
    return "secret." + name


def _require_vault_key() -> None:
    if not settings.vault_key:
        raise SecretStoreError("Set REZE_VAULT_KEY first. Secrets are never stored in plain text.")


def store(name: str, value: str) -> None:
    _require_vault_key()
    cleaned = (value or "").strip()
    if not cleaned:
        raise SecretStoreError("The secret is empty.")
    nonce, ciphertext = encryption.encrypt(cleaned.encode("utf-8"))
    db.set_setting(_key(name), PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii"))


def read(name: str) -> Optional[str]:
    raw = db.get_setting(_key(name), None)
    if not raw:
        return None
    if not raw.startswith(PREFIX):
        raise SecretStoreError("The stored secret has an unknown format.")
    _require_vault_key()
    try:
        blob = base64.b64decode(raw[len(PREFIX):], validate=True)
    except ValueError as exc:
        raise SecretStoreError("The stored secret is damaged.") from exc
    try:
        plain = encryption.decrypt(blob[:NONCE_BYTES], blob[NONCE_BYTES:])
    except (VaultLocked, VaultDecryptError) as exc:
        raise SecretStoreError("The stored secret cannot be opened with the current REZE_VAULT_KEY.") from exc
    return plain.decode("utf-8")


def is_stored(name: str) -> bool:
    return db.get_setting(_key(name), None) is not None


def forget(name: str) -> None:
    db.delete_setting(_key(name))


def import_from_env(name: str, env_var: str) -> bool:
    """Move a secret from the environment into the encrypted store, once. Returns True when it moved.

    Without a vault key nothing moves, and the environment variable keeps working as before.
    """
    value = os.environ.get(env_var, "").strip()
    if not value or is_stored(name) or not settings.vault_key:
        return False
    store(name, value)
    return True


__all__ = ["SecretStoreError", "forget", "import_from_env", "is_stored", "read", "store"]
