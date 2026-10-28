"""
Authentication, sessions and CSRF protection for the Reze panel.

* passwords: PBKDF2-HMAC-SHA256 with a per-password salt, constant-time compare
* sessions: random tokens, expiry, CSRF token bound to the session, in-memory
  (a restart signs everyone out, which is the safe default)
* login rate limiting per client address
"""

import hashlib
import hmac
import secrets
import time
from typing import Any, Dict, Optional

from reze.config import settings
from reze.logging_config import logger

ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
FAILED_ATTEMPTS: Dict[str, list] = {}

PBKDF2_ITERATIONS = 120_000
MAX_FAILED_ATTEMPTS = 5
FAILED_WINDOW_SECONDS = 300


def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Generate a salted PBKDF2-HMAC-SHA256 hash in ``salt$hash`` form."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=PBKDF2_ITERATIONS,
    ).hex()
    return f"{salt}${hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification of ``salt$hash``."""
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, expected_hash = stored_hash.split("$", 1)
    try:
        test_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations=PBKDF2_ITERATIONS,
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected_hash, test_hash)


def create_session(username: str) -> str:
    """Create an authenticated session and return its cookie token."""
    token = secrets.token_urlsafe(32)
    now = time.time()
    ACTIVE_SESSIONS[token] = {
        "username": username,
        "created_at": now,
        "last_active": now,
        "csrf_token": secrets.token_hex(16),
    }
    return token


def get_session(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return the live session for *token*, or ``None`` when absent/expired."""
    if not token or token not in ACTIVE_SESSIONS:
        return None
    session = ACTIVE_SESSIONS[token]
    ttl = max(300, int(settings.session_ttl_seconds))
    if time.time() - session["last_active"] > ttl:
        del ACTIVE_SESSIONS[token]
        return None
    session["last_active"] = time.time()
    return session


def destroy_session(token: str) -> None:
    ACTIVE_SESSIONS.pop(token, None)


def validate_csrf(session: Optional[Dict[str, Any]], token: str) -> bool:
    """Verify a CSRF token against the one bound to the session."""
    if not session or not token:
        return False
    expected = session.get("csrf_token", "")
    return bool(expected) and hmac.compare_digest(str(token), str(expected))


def csrf_token_for(session: Optional[Dict[str, Any]]) -> str:
    return session.get("csrf_token", "") if session else ""


def check_rate_limit(ip: str) -> bool:
    """True when the client may attempt another login."""
    now = time.time()
    attempts = [stamp for stamp in FAILED_ATTEMPTS.get(ip, []) if now - stamp < FAILED_WINDOW_SECONDS]
    FAILED_ATTEMPTS[ip] = attempts
    return len(attempts) < MAX_FAILED_ATTEMPTS


def record_failed_login(ip: str) -> None:
    attempts = FAILED_ATTEMPTS.get(ip, [])
    attempts.append(time.time())
    FAILED_ATTEMPTS[ip] = attempts
    if len(FAILED_ATTEMPTS) > 5000:  # keep the map bounded
        cutoff = time.time() - FAILED_WINDOW_SECONDS
        for key in [k for k, v in FAILED_ATTEMPTS.items() if not v or v[-1] < cutoff]:
            FAILED_ATTEMPTS.pop(key, None)
    logger.warning("Failed panel login attempt from %s", ip)


def reset_rate_limit(ip: str) -> None:
    FAILED_ATTEMPTS.pop(ip, None)
