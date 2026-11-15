"""Message text at rest: encrypted with the Digital Vault key when one is configured.

Only ``REZE_VAULT_KEY`` turns this on. The secret-key fallback is not used, because
changing ``REZE_SECRET_KEY`` would then make stored messages unreadable without any warning.

Stored form: ``REZE-ENC-v1:`` followed by base64 of (12-byte nonce + ciphertext).
Rows written without a key stay plain text, and they remain readable after a key is added.
A sealed value that cannot be opened (wrong or missing key) reads as a clear placeholder.
"""

from __future__ import annotations

import base64
from typing import Any, Optional

from reze.config import settings
from reze.storage import encryption
from reze.storage.encryption import VaultDecryptError, VaultLocked

PREFIX = "REZE-ENC-v1:"
PLACEHOLDER = "[encrypted text: the vault key does not match or is not set]"


def enabled() -> bool:
    return bool(settings.vault_key) and encryption.is_configured()


def is_sealed(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def seal(text: Optional[str]) -> Optional[str]:
    if text is None or not enabled():
        return text
    nonce, ciphertext = encryption.encrypt(text.encode("utf-8"))
    return PREFIX + base64.b64encode(nonce + ciphertext).decode("ascii")


def _open_strict(value: str) -> Optional[str]:
    """Plain text of a sealed value, or None when it cannot be opened with the current key."""
    try:
        raw = base64.b64decode(value[len(PREFIX):], validate=True)
        plain = encryption.decrypt(raw[: encryption.NONCE_BYTES], raw[encryption.NONCE_BYTES :])
    except (ValueError, VaultLocked, VaultDecryptError):
        return None
    return plain.decode("utf-8", errors="replace")


def reseal(value: Any) -> Any:
    """Store a value that may already be sealed, without ever losing it.

    A plain value is sealed. A sealed value is opened and sealed again. If it cannot be opened
    with the current key, it is returned exactly as stored, so the original ciphertext survives.
    """
    if value is None:
        return None
    if not is_sealed(value):
        return seal(str(value))
    plain = _open_strict(value)
    if plain is None:
        return value
    return seal(plain)


def open_text(value: Any) -> str:
    if value is None:
        return ""
    if not is_sealed(value):
        return str(value)
    try:
        raw = base64.b64decode(value[len(PREFIX):], validate=True)
        plain = encryption.decrypt(raw[: encryption.NONCE_BYTES], raw[encryption.NONCE_BYTES :])
    except (ValueError, VaultLocked, VaultDecryptError):
        return PLACEHOLDER
    return plain.decode("utf-8", errors="replace")


__all__ = ["PLACEHOLDER", "PREFIX", "enabled", "is_sealed", "open_text", "reseal", "seal"]
