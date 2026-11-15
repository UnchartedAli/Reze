"""Persistence for the Style Assistant. All SQL for the feature lives here."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from reze.database import db
from reze.digest import schedule as sched
from reze.storage import text_at_rest as tar

MAX_SAMPLES = 500
SETTINGS_FIELDS = (
    "auto_enabled",
    "quiet_start",
    "quiet_end",
    "timezone",
    "cooldown_hours",
    "hourly_cap",
    "owner_active_minutes",
    "language",
)


def _ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")


# -------------------------------------------------------------- samples
def add_samples(chat_id: int, items: Sequence[Tuple[int, str]], now: datetime) -> int:
    """Store owner messages. Duplicates are ignored. Returns how many were new."""
    inserted = 0
    with db.connection() as conn:
        for msg_id, text in items:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO style_samples (chat_id, msg_id, text, learned_at) VALUES (?, ?, ?, ?)",
                (int(chat_id), int(msg_id), tar.seal(text), _ts(now)),
            )
            inserted += cursor.rowcount
        conn.execute(
            "DELETE FROM style_samples WHERE id NOT IN "
            "(SELECT id FROM style_samples ORDER BY id DESC LIMIT ?)",
            (MAX_SAMPLES,),
        )
    return inserted


def sample_texts(limit: int = MAX_SAMPLES) -> List[str]:
    rows = db.query("SELECT text FROM style_samples ORDER BY id ASC LIMIT ?", (int(limit),))
    return [tar.open_text(row["text"]) for row in rows]


def sample_count() -> int:
    row = db.query_one("SELECT COUNT(*) AS n FROM style_samples")
    return int(row["n"]) if row else 0


# -------------------------------------------------------------- profile
def get_profile() -> Dict[str, Any]:
    row = db.query_one("SELECT profile FROM style_profile WHERE id = 1")
    try:
        profile = json.loads(row["profile"]) if row else {}
    except (TypeError, ValueError):
        profile = {}
    return profile if profile.get("count") is not None else {"count": 0}


def save_profile(profile: Dict[str, Any], now: datetime) -> None:
    with db.connection() as conn:
        conn.execute(
            "UPDATE style_profile SET profile = ?, sample_count = ?, updated_at = ? WHERE id = 1",
            (json.dumps(profile, ensure_ascii=False), int(profile.get("count", 0)), _ts(now)),
        )


# ------------------------------------------------------------- settings
def get_settings() -> Dict[str, Any]:
    row = dict(db.query_one("SELECT * FROM style_settings WHERE id = 1") or {})
    row["auto_enabled"] = bool(row.get("auto_enabled"))
    return row


def set_setting(name: str, value: Any) -> None:
    if name not in SETTINGS_FIELDS:
        raise ValueError(f"Unknown setting: {name}")
    with db.connection() as conn:
        conn.execute(f"UPDATE style_settings SET {name} = ? WHERE id = 1", (value,))


def set_quiet(start: str, end: str, timezone_name: str) -> None:
    start_h, start_m = sched.parse_time_of_day(start)
    end_h, end_m = sched.parse_time_of_day(end)
    zone = sched.load_timezone(timezone_name)
    with db.connection() as conn:
        conn.execute(
            "UPDATE style_settings SET quiet_start = ?, quiet_end = ?, timezone = ? WHERE id = 1",
            (sched.format_time(start_h, start_m), sched.format_time(end_h, end_m), zone.key),
        )


def clear_quiet() -> None:
    with db.connection() as conn:
        conn.execute("UPDATE style_settings SET quiet_start = '', quiet_end = '' WHERE id = 1")


# ---------------------------------------------------------- allow list
def allow_chat(chat_id: int, title: str) -> None:
    with db.connection() as conn:
        conn.execute(
            "INSERT INTO style_auto_chats (chat_id, title) VALUES (?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET title = excluded.title",
            (int(chat_id), title or ""),
        )


def block_chat(chat_id: int) -> bool:
    with db.connection() as conn:
        return conn.execute("DELETE FROM style_auto_chats WHERE chat_id = ?", (int(chat_id),)).rowcount == 1


def allowed_chat(chat_id: int) -> Optional[Dict[str, Any]]:
    row = db.query_one("SELECT * FROM style_auto_chats WHERE chat_id = ?", (int(chat_id),))
    return dict(row) if row else None


def list_allowed() -> List[Dict[str, Any]]:
    return db.query("SELECT * FROM style_auto_chats ORDER BY lower(title)")


def last_reply_at(chat_id: int) -> Optional[datetime]:
    row = db.query_one("SELECT last_reply_at FROM style_auto_chats WHERE chat_id = ?", (int(chat_id),))
    return _parse(row["last_reply_at"]) if row else None


def record_auto_reply(chat_id: int, now: datetime) -> None:
    with db.connection() as conn:
        conn.execute("UPDATE style_auto_chats SET last_reply_at = ? WHERE chat_id = ?", (_ts(now), int(chat_id)))
        conn.execute("INSERT INTO style_auto_log (chat_id, sent_at) VALUES (?, ?)", (int(chat_id), _ts(now)))
        conn.execute("DELETE FROM style_auto_log WHERE sent_at < ?", (_ts(now - timedelta(hours=24)),))


def replies_since(since: datetime) -> int:
    row = db.query_one("SELECT COUNT(*) AS n FROM style_auto_log WHERE sent_at >= ?", (_ts(since),))
    return int(row["n"]) if row else 0


# -------------------------------------------------------------- drafts
def create_draft(chat_id: int, reply_to_id: Optional[int], draft: str, now: datetime) -> int:
    with db.connection() as conn:
        cursor = conn.execute(
            "INSERT INTO style_drafts (chat_id, reply_to_id, draft, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (int(chat_id), int(reply_to_id) if reply_to_id else None, tar.seal(draft), _ts(now)),
        )
        return int(cursor.lastrowid)


def get_draft(draft_id: int) -> Optional[Dict[str, Any]]:
    row = db.query_one("SELECT * FROM style_drafts WHERE id = ?", (int(draft_id),))
    if not row:
        return None
    data = dict(row)
    data["draft"] = tar.open_text(data["draft"])
    return data


def set_draft_status(draft_id: int, status: str) -> None:
    with db.connection() as conn:
        conn.execute("UPDATE style_drafts SET status = ? WHERE id = ?", (status, int(draft_id)))


# -------------------------------------------------------------- forget
def forget() -> Dict[str, int]:
    """Delete everything learned: samples, profile, drafts, auto-reply log and allow list. Auto-reply is turned off."""
    with db.connection() as conn:
        samples = conn.execute("DELETE FROM style_samples").rowcount
        drafts = conn.execute("DELETE FROM style_drafts").rowcount
        logs = conn.execute("DELETE FROM style_auto_log").rowcount
        allowed = conn.execute("DELETE FROM style_auto_chats").rowcount
        conn.execute("UPDATE style_profile SET profile = '{}', sample_count = 0, updated_at = NULL WHERE id = 1")
        conn.execute("UPDATE style_settings SET auto_enabled = 0 WHERE id = 1")
    return {"samples": samples, "drafts": drafts, "auto_log": logs, "allowed_chats": allowed}


__all__ = [
    "MAX_SAMPLES",
    "add_samples",
    "allow_chat",
    "allowed_chat",
    "block_chat",
    "clear_quiet",
    "create_draft",
    "forget",
    "get_draft",
    "get_profile",
    "get_settings",
    "last_reply_at",
    "list_allowed",
    "record_auto_reply",
    "replies_since",
    "sample_count",
    "sample_texts",
    "save_profile",
    "set_draft_status",
    "set_quiet",
    "set_setting",
]
