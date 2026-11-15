"""Web panel logic for the Style Assistant. Testable without HTTP.

Only actions that need no live Telegram connection are offered in the panel:
learning, adding chats to the allow list and sending drafts need Telegram and
stay in the commands. Every control here calls real store functions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from urllib.parse import quote

from reze.digest import schedule as sched
from reze.features import features
from reze.style import profile as prof
from reze.style import store
from reze.storage import text_at_rest as tar
from reze.timeutil import utcnow

MAX_TEXT = 300


def build_state(language: str = "en", message: str = "", error: str = "") -> Dict[str, Any]:
    settings = store.get_settings()
    now = utcnow()
    pending = store.db.query(
        "SELECT id, chat_id, reply_to_id, draft, created_at FROM style_drafts "
        "WHERE status = 'pending' ORDER BY id DESC LIMIT 20"
    )
    for draft in pending:
        draft["draft"] = tar.open_text(draft["draft"])
    return {
        "feature_on": features.is_enabled("style_assistant"),
        "settings": settings,
        "samples": store.sample_count(),
        "profile_lines": prof.describe(store.get_profile(), language),
        "allowed": store.list_allowed(),
        "drafts": pending,
        "replies_24h": store.replies_since(now - timedelta(hours=24)),
        "message": message,
        "error": error,
    }


def _text(form: Dict[str, List[str]], key: str, limit: int = MAX_TEXT) -> str:
    return (form.get(key, [""])[0] or "").strip()[:limit]


def save_settings(form: Dict[str, List[str]]) -> None:
    """Validate and save the settings form. Raises ValueError with a readable message."""
    start, end = _text(form, "quiet_start", 5), _text(form, "quiet_end", 5)
    zone = _text(form, "timezone", 64) or "UTC"
    if bool(start) != bool(end):
        raise ValueError("Set both quiet hour times, or clear both.")
    if start and end:
        store.set_quiet(start, end, zone)
    else:
        store.clear_quiet()
        store.set_setting("timezone", sched.load_timezone(zone).key)

    cooldown = int(_text(form, "cooldown_hours", 4) or 6)
    cap = int(_text(form, "hourly_cap", 4) or 10)
    active = int(_text(form, "owner_active_minutes", 5) or 30)
    if not 1 <= cooldown <= 168:
        raise ValueError("Cooldown must be between 1 and 168 hours.")
    if not 1 <= cap <= 100:
        raise ValueError("Hourly cap must be between 1 and 100.")
    if not 0 <= active <= 1440:
        raise ValueError("Owner-active window must be between 0 and 1440 minutes.")
    language = _text(form, "language", 2).lower() or "en"
    if language not in ("en", "fa"):
        raise ValueError("Language must be en or fa.")
    store.set_setting("cooldown_hours", cooldown)
    store.set_setting("hourly_cap", cap)
    store.set_setting("owner_active_minutes", active)
    store.set_setting("language", language)


def set_auto(action: str) -> None:
    if action not in ("on", "off"):
        raise ValueError("Unknown action.")
    store.set_setting("auto_enabled", 1 if action == "on" else 0)


def block_chat(raw_chat_id: str) -> None:
    value = (raw_chat_id or "").strip()
    if not value.lstrip("-").isdigit():
        raise ValueError("Invalid chat.")
    store.block_chat(int(value))


def forget(confirm: str) -> Dict[str, int]:
    if (confirm or "").strip().lower() != "yes":
        raise ValueError("Tick the confirmation box to delete everything learned.")
    return store.forget()


def redirect_url(message: str = "", error: str = "") -> str:
    if error:
        return "/style?err=" + quote(error[:200])
    return "/style?msg=" + quote(message[:200])


__all__ = ["block_chat", "build_state", "forget", "redirect_url", "save_settings", "set_auto"]
