"""
Authentication and Session Security for Reze Web Panel.
Provides PBKDF2/SHA256 password hashing, verification, secure session tokens, and timing-attack resistance.
"""

import hashlib
import hmac
import secrets
import time
from typing import Dict, Optional, Any
from reze.config import settings
from reze.logging_config import logger

ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
FAILED_ATTEMPTS: Dict[str, list] = {}

def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Generate secure salted PBKDF2-HMAC-SHA256 hash."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations=100_000
    ).hex()
    return f"{salt}${hashed}"

def verify_password(password: str, stored_hash: str) -> bool:
    """Safely verify a password against stored salt$hash using constant-time comparison."""
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, expected_hash = stored_hash.split("$", 1)
    test_hash = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations=100_000
    ).hex()
    return hmac.compare_digest(expected_hash, test_hash)

def create_session(username: str) -> str:
    """Create a new authenticated web session token."""
    token = secrets.token_urlsafe(32)
    ACTIVE_SESSIONS[token] = {
        "username": username,
        "created_at": time.time(),
        "last_active": time.time(),
        "csrf_token": secrets.token_hex(16)
    }
    return token

def get_session(token: Optional[str]) -> Optional[Dict[str, Any]]:
    """Retrieve active session and update activity timestamp (timeout: 4 hours)."""
    if not token or token not in ACTIVE_SESSIONS:
        return None
    session = ACTIVE_SESSIONS[token]
    # Check session expiration (14400s = 4h)
    if time.time() - session["last_active"] > 14400:
        del ACTIVE_SESSIONS[token]
        return None
    session["last_active"] = time.time()
    return session

def destroy_session(token: str):
    """Log out session."""
    if token in ACTIVE_SESSIONS:
        del ACTIVE_SESSIONS[token]

def check_rate_limit(ip: str) -> bool:
    """Rate limit login attempts (max 5 failed attempts per 5 minutes)."""
    now = time.time()
    attempts = FAILED_ATTEMPTS.get(ip, [])
    attempts = [t for t in attempts if now - t < 300]
    FAILED_ATTEMPTS[ip] = attempts
    return len(attempts) < 5

def record_failed_login(ip: str):
    attempts = FAILED_ATTEMPTS.get(ip, [])
    attempts.append(time.time())
    FAILED_ATTEMPTS[ip] = attempts
