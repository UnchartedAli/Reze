"""Reze -> Watchdog: signed events to the Watchdog worker's /reze/event route.

Signature: HMAC-SHA256 (hex) of "<unix timestamp>.<raw body>" with the bridge secret.
The worker accepts an event for five minutes and each signature once. Nothing here logs the
secret or the event text. Without a stored bridge secret, no event is sent.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from reze import consent
from reze.digest.text import unsupported_tokens
from reze.logging_config import logger
from reze.storage import secret_store

DEFAULT_URL = "https://amo.alimmazza043.workers.dev"
EVENT_PATH = "/reze/event"
BRIDGE_SECRET = "watchdog_bridge"
ENV_SECRET = "REZE_WATCHDOG_BRIDGE_SECRET"
MIN_SECRET_LENGTH = 32
TEXT_MAX = 500
TIMEOUT_SECONDS = 10


class WatchdogError(RuntimeError):
    """The Watchdog URL or secret is unusable. The message is safe to show the owner."""


def url() -> str:
    value = os.environ.get("REZE_WATCHDOG_URL", "").strip() or DEFAULT_URL
    value = value.rstrip("/")
    local = value.startswith(("http://127.0.0.1", "http://localhost"))  # for tests only
    if not (value.startswith("https://") or local):
        raise WatchdogError("REZE_WATCHDOG_URL must use https.")
    return value


def bridge_secret() -> Optional[str]:
    secret_store.import_from_env(BRIDGE_SECRET, ENV_SECRET)
    try:
        value = secret_store.read(BRIDGE_SECRET)
    except secret_store.SecretStoreError:
        return None
    if value and len(value) >= MIN_SECRET_LENGTH:
        return value
    return None


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + body, hashlib.sha256).hexdigest()


def _clean(text: str) -> str:
    return " ".join(str(text).split())[:TEXT_MAX]


def build_request(secret: str, kind: str, text: str, now: Optional[float] = None) -> Tuple[bytes, Dict[str, str]]:
    timestamp = int(now if now is not None else time.time())
    body = json.dumps({"kind": kind, "text": _clean(text)}, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Reze-Timestamp": str(timestamp),
        "X-Reze-Signature": sign(secret, timestamp, body),
    }
    return body, headers


def send_event_blocking(kind: str, text: str) -> bool:
    """Send one event. Returns True when the worker accepted it. Never raises."""
    try:
        target = url() + EVENT_PATH
    except WatchdogError as exc:
        logger.warning("Watchdog: %s", exc)
        return False
    secret = bridge_secret()
    if not secret:
        return False
    body, headers = build_request(secret, kind, text)
    request = urllib.request.Request(target, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError) as exc:
        logger.warning("Watchdog event not delivered (%s).", type(exc).__name__)
        return False


async def send_event(kind: str, text: str) -> bool:
    return await asyncio.to_thread(send_event_blocking, kind, text)


def forget() -> None:
    secret_store.forget(BRIDGE_SECRET)


__all__ = ["BRIDGE_SECRET", "MAX_POSTS", "summarize_posts", "verify_summary", "WatchdogError", "build_request", "bridge_secret", "forget", "send_event", "send_event_blocking", "sign", "url"]


# ---- Summaries of channel posts (only with consent) ------------------------------------------------
MAX_POSTS = 40
MAX_POST_CHARS = 1500
MAX_BODY_CHARS = 65536
SUMMARY_TIMEOUT = 40

_FRIENDLY = {
    "ai_not_configured": "The Watchdog bot has no AI key set yet.",
    "ai_failed": "The Watchdog bot could not get an answer from its AI. Try again later.",
    "ai_empty": "The AI answered with nothing. Try again with fewer posts.",
    "too_many_posts": f"Send at most {MAX_POSTS} posts at a time.",
    "bad_json": "The Watchdog bot did not accept the request.",
    "no_posts": "There are no posts to summarize.",
}


def verify_summary(summary: str, sources: List[str]) -> tuple:
    """Drop every line that has a number or link the posts do not contain. Returns (text, removed)."""
    kept: List[str] = []
    removed = 0
    for line in summary.splitlines():
        if line.strip() and unsupported_tokens(line, sources):
            removed += 1
            continue
        kept.append(line)
    return "\n".join(kept).strip(), removed


def _post_summary(secret: str, body: bytes) -> Dict[str, Any]:
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "X-Reze-Timestamp": str(timestamp),
        "X-Reze-Signature": sign(secret, timestamp, body),
    }
    request = urllib.request.Request(url() + "/reze/summarize", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=SUMMARY_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            error = json.loads(exc.read().decode("utf-8")).get("error", "")
        except (ValueError, AttributeError):
            error = ""
        raise WatchdogError(_FRIENDLY.get(error, "The Watchdog bot did not answer as expected.")) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise WatchdogError("The Watchdog bot is not reachable right now.") from exc


async def summarize_posts(posts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Send the owner's chosen posts to Watchdog for one summary. Needs consent. Nothing is stored."""
    consent.require("watchdog.channel_posts")
    secret = bridge_secret()
    if not secret:
        raise WatchdogError("Set the Watchdog bridge secret first (REZE_WATCHDOG_BRIDGE_SECRET).")
    if not posts:
        raise WatchdogError("There are no posts to summarize.")
    if len(posts) > MAX_POSTS:
        raise WatchdogError(f"Send at most {MAX_POSTS} posts at a time.")
    clean = [
        {
            "channel": str(post.get("channel", ""))[:100],
            "date": str(post.get("date", ""))[:20],
            "text": str(post.get("text", ""))[:MAX_POST_CHARS],
        }
        for post in posts
    ]
    body = json.dumps({"posts": clean}, ensure_ascii=False).encode("utf-8")
    if len(body) > MAX_BODY_CHARS:
        raise WatchdogError("These posts are too large to send at once. Ask for fewer.")
    try:
        result = await asyncio.to_thread(_post_summary, secret, body)
    except WatchdogError as exc:
        logger.warning("Watchdog summary request failed (%s).", type(exc).__name__)
        raise
    if not result.get("ok"):
        raise WatchdogError(_FRIENDLY.get(str(result.get("error", "")), "The Watchdog bot did not answer as expected."))
    summary, removed = verify_summary(str(result.get("summary", "")), [item["text"] for item in clean])
    if not summary:
        raise WatchdogError("Every line of the summary had a number or link that the posts do not contain, so nothing was kept.")
    return {"summary": summary, "removed": removed, "posts": len(clean)}
