"""Web panel logic for Channel Digest. Testable without HTTP.

Every control calls a real store or service function. Anything that needs a live
Telegram connection (adding a channel, sending now) is either refused with a clear
message or handed to the running digest loop as a request.
"""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import quote

from reze.digest import schedule as sched
from reze.digest import store
from reze.digest.service import digest_service
from reze.features import features
from reze.timeutil import utcnow

CHANNEL_FIELDS = ("priority", "include_keywords", "exclude_keywords")


def _value(form: Dict[str, List[str]], key: str, limit: int = 300) -> str:
    return (form.get(key, [""])[0] or "").strip()[:limit]


def build_state(query: Dict[str, List[str]], language: str = "en", message: str = "", error: str = "") -> Dict[str, Any]:
    search = _value(query, "q", 80).lower()
    snap = digest_service.snapshot(utcnow())
    channels = [
        row
        for row in store.list_channels()
        if not search
        or search in (row.get("title") or "").lower()
        or search in (row.get("username") or "").lower()
    ]
    return {
        "feature_on": features.is_enabled("channel_digest"),
        "config": snap["config"],
        "next_slot": snap["next_slot"],
        "last_run": snap["last_run"],
        "pending": snap["pending"],
        "channels": channels,
        "search": search,
        "channel_total": len(store.list_channels()),
        "runs": store.list_runs(limit=15),
        "message": message,
        "error": error,
    }


def save_settings(form: Dict[str, List[str]]) -> None:
    """Validate and save the schedule and summary settings. Raises ValueError with a readable message."""
    sched.load_timezone(_value(form, "timezone", 64) or "UTC")
    store.set_timezone(_value(form, "timezone", 64) or "UTC")
    store.set_time(_value(form, "time_of_day", 5) or "21:00")
    store.set_schedule(_value(form, "schedule", 10) or "daily", _value(form, "days", 40))
    store.set_limits(
        max_messages=int(_value(form, "max_messages", 5) or 200),
        max_chars=int(_value(form, "max_chars", 6) or 12000),
    )
    store.set_language(_value(form, "language", 2).lower() or "en")


def toggle(name: str, value: str) -> None:
    if name not in store.CONFIG_TOGGLES:
        raise ValueError("Unknown switch.")
    store.set_toggle(name, value == "on")


def update_channel(form: Dict[str, List[str]]) -> None:
    chat_id = _value(form, "chat_id", 20)
    if not chat_id.lstrip("-").isdigit():
        raise ValueError("Invalid channel.")
    if store.get_channel(int(chat_id)) is None:
        raise ValueError("That channel is no longer selected.")
    priority = int(_value(form, "priority", 3) or 5)
    store.update_channel(
        int(chat_id),
        priority=priority,
        enabled=bool(form.get("enabled")),
        include_keywords=_value(form, "include_keywords", 300).replace(" ", ""),
        exclude_keywords=_value(form, "exclude_keywords", 300).replace(" ", ""),
    )


def remove_channel(form: Dict[str, List[str]]) -> None:
    chat_id = _value(form, "chat_id", 20)
    if not chat_id.lstrip("-").isdigit():
        raise ValueError("Invalid channel.")
    store.remove_channel(int(chat_id))


def request_run() -> None:
    if not store.get_config()["enabled"]:
        raise ValueError("Turn the digest on first.")
    store.request_run()


def clear_history(confirm: str) -> int:
    if (confirm or "").strip().lower() != "yes":
        raise ValueError("Tick the confirmation box to delete digest history.")
    return store.clear_history()


def redirect_url(message: str = "", error: str = "") -> str:
    if error:
        return "/digest?err=" + quote(error[:200])
    return "/digest?msg=" + quote(message[:200])


__all__ = ["build_state", "clear_history", "redirect_url", "remove_channel", "request_run", "save_settings", "toggle", "update_channel"]
