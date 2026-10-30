"""Authenticated encryption for the Digital Vault.

AES-256-GCM with a key derived from ``REZE_VAULT_KEY`` (preferred) or a
non-default ``REZE_SECRET_KEY``. Ciphertext and nonce are stored as BLOBs; the
key itself is never written to the database, logged or returned by any command.
"""

from __future__ import annotations

import hashlib
import os
from typing import Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from reze.config import settings
from reze.logging_config import logger

SALT = b"reze-vault-v1"
DEFAULT_SECRET = "reze-super-secret-key-change-me-in-production"
NONCE_BYTES = 12


class VaultLocked(Exception):
    """Raised when no usable vault key is configured."""


class VaultDecryptError(Exception):
    """Raised when ciphertext cannot be authenticated (wrong key or tampering)."""


def secret_material() -> Optional[str]:
    """The configured key material, or ``None`` when only the default exists."""
    if settings.vault_key.strip():
        return settings.vault_key.strip()
    if settings.secret_key.strip() and settings.secret_key != DEFAULT_SECRET:
        return settings.secret_key.strip()
    return None


def is_configured() -> bool:
    return secret_material() is not None


def _key() -> bytes:
    material = secret_material()
    if material is None:
        raise VaultLocked(
            "Set REZE_VAULT_KEY (or a non-default REZE_SECRET_KEY) to use the Digital Vault."
        )
    kdf = Scrypt(salt=SALT, length=32, n=2**14, r=8, p=1)
    return kdf.derive(material.encode("utf-8"))


def encrypt(plaintext: bytes) -> Tuple[bytes, bytes]:
    """Return ``(nonce, ciphertext)`` for *plaintext*."""
    if plaintext is None:
        plaintext = b""
    nonce = os.urandom(NONCE_BYTES)
    ciphertext = AESGCM(_key()).encrypt(nonce, bytes(plaintext), None)
    return nonce, ciphertext


def decrypt(nonce: bytes, ciphertext: bytes) -> bytes:
    try:
        return AESGCM(_key()).decrypt(bytes(nonce), bytes(ciphertext), None)
    except InvalidTag as exc:
        logger.warning("Vault decryption failed (wrong key or modified data).")
        raise VaultDecryptError("The Vault entry could not be decrypted with the current key.") from exc


def fingerprint() -> str:
    """Short, non-reversible key fingerprint for diagnostics (never the key)."""
    material = secret_material()
    if not material:
        return "unconfigured"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:8]


__all__ = [
    "DEFAULT_SECRET",
    "VaultDecryptError",
    "VaultLocked",
    "decrypt",
    "encrypt",
    "fingerprint",
    "is_configured",
    "secret_material",
]
