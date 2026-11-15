"""Persistence for Channel Digest. All SQL for the feature lives in this module.

Timestamps are stored as naive UTC strings, as elsewhere in REZE.
Writes that must succeed together run in one ``db.connection()`` transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.digest import schedule as sched
from reze.storage import text_at_rest as tar
from reze.digest.text import LABELS  # noqa: F401  - re-exported for callers that need labels

CONFIG_TOGGLES = ("enabled", "paused", "ai_enabled")
LANGUAGES = ("en", "fa")
MAX_MESSAGES_RANGE = (1, 500)
MAX_CHARS_RANGE = (500, 20000)
PRIORITY_RANGE = (1, 10)
CHANNEL_FIELDS = ("enabled", "priority", "include_keywords", "exclude_keywords")


def _ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _as_bool(row: Dict[str, Any], *keys: str) -> Dict[str, Any]:
    for key in keys:
        if key in row and row[key] is not None:
            row[key] = bool(row[key])
    return row


# ------------------------------------------------------------------ config
def get_config() -> Dict[str, Any]:
    row = db.query_one("SELECT * FROM digest_config WHERE id = 1")
    if row is None:
        raise RuntimeError("Channel Digest tables are missing. Run the migrations.")
    return _as_bool(row, *CONFIG_TOGGLES)


def _update_config(values: Dict[str, Any], now: Optional[datetime] = None) -> None:
    from reze.timeutil import utcnow

    stamp = _ts(now or utcnow())
    assignments = ", ".join(f"{key} = ?" for key in values)
    with db.connection() as conn:
        conn.execute(
            f"UPDATE digest_config SET {assignments}, updated_at = ? WHERE id = 1",
            (*values.values(), stamp),
        )


def set_toggle(name: str, value: bool) -> None:
    if name not in CONFIG_TOGGLES:
        raise ValueError(f"Unknown switch: {name}")
    _update_config({name: 1 if value else 0})


def set_time(text: str) -> str:
    hour, minute = sched.parse_time_of_day(text)
    value = sched.format_time(hour, minute)
    _update_config({"time_of_day": value})
    return value


def set_timezone(name: str) -> str:
    zone = sched.load_timezone(name)
    _update_config({"timezone": zone.key})
    return zone.key


def set_schedule(schedule: str, days_text: str = "") -> Dict[str, str]:
    kind, days = sched.parse_schedule(schedule, days_text)
    _update_config({"schedule": kind, "days": days})
    return {"schedule": kind, "days": days}


def set_limits(max_messages: Optional[int] = None, max_chars: Optional[int] = None) -> Dict[str, int]:
    changes: Dict[str, Any] = {}
    if max_messages is not None:
        low, high = MAX_MESSAGES_RANGE
        if not low <= int(max_messages) <= high:
            raise ValueError(f"Messages per digest must be between {low} and {high}.")
        changes["max_messages"] = int(max_messages)
    if max_chars is not None:
        low, high = MAX_CHARS_RANGE
        if not low <= int(max_chars) <= high:
            raise ValueError(f"Digest length must be between {low} and {high} characters.")
        changes["max_chars"] = int(max_chars)
    if changes:
        _update_config(changes)
    return {key: changes[key] for key in changes}


def set_language(code: str) -> str:
    value = (code or "").strip().lower()
    if value not in LANGUAGES:
        raise ValueError("Language must be en or fa.")
    _update_config({"language": value})
    return value


# ---------------------------------------------------------------- channels
def list_channels() -> List[Dict[str, Any]]:
    rows = db.query("SELECT * FROM digest_channels ORDER BY priority ASC, lower(title) ASC")
    return [_as_bool(row, "enabled") for row in rows]


def enabled_channels() -> List[Dict[str, Any]]:
    rows = db.query(
        "SELECT * FROM digest_channels WHERE enabled = 1 ORDER BY priority ASC, chat_id ASC"
    )
    return rows


def get_channel(chat_id: int) -> Optional[Dict[str, Any]]:
    row = db.query_one("SELECT * FROM digest_channels WHERE chat_id = ?", (int(chat_id),))
    return _as_bool(row, "enabled") if row else None


def add_channel(chat_id: int, title: str, username: str, last_message_id: int, now: datetime) -> bool:
    with db.connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO digest_channels "
            "(chat_id, title, username, last_message_id, added_at) VALUES (?, ?, ?, ?, ?)",
            (int(chat_id), title or "", username or "", int(last_message_id), _ts(now)),
        )
        return cursor.rowcount == 1


def remove_channel(chat_id: int) -> bool:
    with db.connection() as conn:
        cursor = conn.execute("DELETE FROM digest_channels WHERE chat_id = ?", (int(chat_id),))
        return cursor.rowcount == 1


def update_channel(chat_id: int, **changes: Any) -> bool:
    unknown = set(changes) - set(CHANNEL_FIELDS)
    if unknown:
        raise ValueError(f"Unknown channel setting: {', '.join(sorted(unknown))}")
    values: Dict[str, Any] = {}
    for key, value in changes.items():
        if key == "priority":
            low, high = PRIORITY_RANGE
            if not low <= int(value) <= high:
                raise ValueError(f"Priority must be between {low} (highest) and {high} (lowest).")
            values[key] = int(value)
        elif key == "enabled":
            values[key] = 1 if value else 0
        else:
            values[key] = str(value or "").strip()[:300]
    if not values:
        return False
    assignments = ", ".join(f"{key} = ?" for key in values)
    with db.connection() as conn:
        cursor = conn.execute(
            f"UPDATE digest_channels SET {assignments} WHERE chat_id = ?",
            (*values.values(), int(chat_id)),
        )
        return cursor.rowcount == 1


# -------------------------------------------------------------------- runs
def run_exists(slot_key: str) -> bool:
    return db.query_one("SELECT 1 AS found FROM digest_runs WHERE slot_key = ?", (slot_key,)) is not None


def create_run(slot_key: str, kind: str, now: datetime) -> Optional[int]:
    """Create a 'collecting' run. Returns None when the slot already has a run (no duplicates)."""
    with db.connection() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO digest_runs (slot_key, kind, status, created_at) VALUES (?, ?, 'collecting', ?)",
            (slot_key, kind, _ts(now)),
        )
        return int(cursor.lastrowid) if cursor.rowcount == 1 else None


def get_run(run_id: int) -> Optional[Dict[str, Any]]:
    row = db.query_one("SELECT * FROM digest_runs WHERE id = ?", (int(run_id),))
    if row is None:
        return None
    data = dict(row)
    data["body"] = tar.open_text(data["body"])
    return data


def list_runs(limit: int = 10) -> List[Dict[str, Any]]:
    """Run history without message bodies."""
    return db.query(
        "SELECT id, slot_key, kind, status, period_start, period_end, channel_count, message_count, "
        "important_count, summary_mode, attempts, last_error, created_at, finished_at "
        "FROM digest_runs ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 100)),),
    )


def commit_collection(
    run_id: int,
    *,
    body: str,
    chunk_total: int,
    mode: str,
    period_start: Optional[datetime],
    period_end: Optional[datetime],
    channel_count: int,
    message_count: int,
    important_count: int,
    checkpoints: Dict[int, int],
    now: datetime,
) -> None:
    """Store the digest body and advance checkpoints in ONE transaction."""
    with db.connection() as conn:
        conn.execute(
            "UPDATE digest_runs SET status = 'pending_send', body = ?, chunk_total = ?, summary_mode = ?, "
            "period_start = ?, period_end = ?, channel_count = ?, message_count = ?, important_count = ?, "
            "next_attempt_at = NULL WHERE id = ?",
            (
                tar.seal(body),
                int(chunk_total),
                mode,
                _ts(period_start) if period_start else None,
                _ts(period_end) if period_end else None,
                int(channel_count),
                int(message_count),
                int(important_count),
                int(run_id),
            ),
        )
        for chat_id, last_message_id in checkpoints.items():
            conn.execute(
                "UPDATE digest_channels SET last_message_id = ?, last_synced_at = ? WHERE chat_id = ?",
                (int(last_message_id), _ts(now), int(chat_id)),
            )


def finish_empty(run_id: int, checkpoints: Dict[int, int], now: datetime) -> None:
    """A run with no new posts: nothing is sent, but checkpoints still move forward."""
    with db.connection() as conn:
        conn.execute(
            "UPDATE digest_runs SET status = 'empty', body = '', finished_at = ? WHERE id = ?",
            (_ts(now), int(run_id)),
        )
        for chat_id, last_message_id in checkpoints.items():
            conn.execute(
                "UPDATE digest_channels SET last_message_id = ?, last_synced_at = ? WHERE chat_id = ?",
                (int(last_message_id), _ts(now), int(chat_id)),
            )


def finish_run(run_id: int, status: str, error: str, now: datetime) -> None:
    with db.connection() as conn:
        conn.execute(
            "UPDATE digest_runs SET status = ?, body = '', last_error = ?, finished_at = ? WHERE id = ?",
            (status, error[:200], _ts(now), int(run_id)),
        )


def mark_chunk_sent(run_id: int, delivered_chunks: int, message_id: int) -> None:
    with db.connection() as conn:
        conn.execute(
            "UPDATE digest_runs SET delivered_chunks = ?, "
            "delivered_ids = CASE WHEN delivered_ids = '' THEN ? ELSE delivered_ids || ',' || ? END "
            "WHERE id = ?",
            (int(delivered_chunks), str(int(message_id)), str(int(message_id)), int(run_id)),
        )


def schedule_retry(run_id: int, attempts: int, next_attempt_at: datetime, error: str, now: datetime) -> None:
    with db.connection() as conn:
        conn.execute(
            "UPDATE digest_runs SET attempts = ?, next_attempt_at = ?, last_error = ? WHERE id = ?",
            (int(attempts), _ts(next_attempt_at), error[:200], int(run_id)),
        )


def mark_sent(run_id: int, now: datetime) -> None:
    """Delivery finished: the stored body is removed (no message content is kept)."""
    with db.connection() as conn:
        conn.execute(
            "UPDATE digest_runs SET status = 'sent', body = '', last_error = '', next_attempt_at = NULL, "
            "finished_at = ? WHERE id = ?",
            (_ts(now), int(run_id)),
        )


def pending_run_ids(now: datetime) -> List[int]:
    rows = db.query(
        "SELECT id FROM digest_runs WHERE status = 'pending_send' "
        "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) ORDER BY id",
        (_ts(now),),
    )
    return [int(row["id"]) for row in rows]


def pending_count() -> int:
    row = db.query_one("SELECT COUNT(*) AS n FROM digest_runs WHERE status = 'pending_send'")
    return int(row["n"]) if row else 0


def delete_interrupted_runs() -> int:
    """Remove runs that were still 'collecting' at shutdown. They stored nothing, so the slot reruns."""
    with db.connection() as conn:
        cursor = conn.execute("DELETE FROM digest_runs WHERE status = 'collecting'")
        return cursor.rowcount


def clear_history() -> int:
    """Delete run history and any stored digest bodies. Channel checkpoints are kept."""
    with db.connection() as conn:
        cursor = conn.execute("DELETE FROM digest_runs")
        return cursor.rowcount


__all__ = [
    "add_channel",
    "clear_history",
    "commit_collection",
    "create_run",
    "delete_interrupted_runs",
    "enabled_channels",
    "finish_empty",
    "finish_run",
    "get_channel",
    "get_config",
    "get_run",
    "list_channels",
    "list_runs",
    "mark_chunk_sent",
    "mark_sent",
    "pending_count",
    "pending_run_ids",
    "remove_channel",
    "run_exists",
    "schedule_retry",
    "set_language",
    "set_limits",
    "set_schedule",
    "set_time",
    "set_timezone",
    "set_toggle",
    "update_channel",
]


# ---------------------------------------------------------- run requests
RUN_REQUEST_KEY = "digest.run_requested"


def request_run() -> None:
    """Ask the digest loop to send one digest on its next pass (used by the web panel)."""
    db.set_setting(RUN_REQUEST_KEY, "1")


def take_run_request() -> bool:
    """Return True once per request and clear it."""
    if db.get_setting(RUN_REQUEST_KEY, "") == "1":
        db.delete_setting(RUN_REQUEST_KEY)
        return True
    return False
