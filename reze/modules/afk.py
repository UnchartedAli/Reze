"""
AFK mode: answer private chats once while you are away and keep a log of what you missed.

* Each person gets ONE automatic reply per cooldown (default 6 hours), never twice in a row.
* Bots, groups and channels never get replies; mentions in groups are only logged.
* ``.back`` (or the timer ending) shows a summary: who wrote to you and where you were mentioned.
"""

import asyncio
import json
import re
import sqlite3
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

from reze.logging_config import logger

STATE_KEY = "afk:state"
DEFAULT_TEXT = "I'm away right now{reason}. I'll get back to you when I can."
COOLDOWN_HOURS = 6
MAX_REPLIES_PER_HOUR = 30
SUMMARY_LINES = 10

_SCHEMA = """
CREATE TABLE IF NOT EXISTS afk_missed (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL,
    kind        TEXT,
    chat_id     INTEGER,
    chat_title  TEXT,
    sender_id   INTEGER,
    sender_name TEXT,
    text        TEXT
);
"""
_DURATION_RE = re.compile(r"^(\d{1,4})([mhd])$", re.I)


def parse_duration(token: str) -> Optional[int]:
    """``30m`` / ``2h`` / ``1d`` -> seconds (None when it is not a duration)."""
    match = _DURATION_RE.match(token or "")
    if not match:
        return None
    return int(match.group(1)) * {"m": 60, "h": 3600, "d": 86400}[match.group(2).lower()]


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds >= 86400:
        return f"{seconds // 86400}d {seconds % 86400 // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    return f"{max(1, seconds // 60)}m"


def _name(entity: Any) -> str:
    if entity is None:
        return "Unknown"
    first = getattr(entity, "first_name", None)
    if first is not None or getattr(entity, "last_name", None) is not None:
        value = " ".join(p for p in (first, getattr(entity, "last_name", None)) if p)
    else:
        value = getattr(entity, "title", "") or ""
    user = getattr(entity, "username", None)
    return (f"{value} (@{user})" if user else value) or str(getattr(entity, "id", "Unknown"))


class AfkService:
    def __init__(self, connect=None, get_setting=None, set_setting=None, clock: Callable[[], float] = time.time):
        self._connect, self._get, self._set, self._clock = connect, get_setting, set_setting, clock
        self._state: Optional[Dict[str, Any]] = None
        self._ready = False
        self._replied: Dict[int, float] = {}
        self._recent_replies: Deque[float] = deque(maxlen=MAX_REPLIES_PER_HOUR)
        self.client_provider: Callable[[], Any] = lambda: None
        self.sleep = asyncio.sleep

    # ----------------------------------------------------------------- storage
    def connect(self) -> sqlite3.Connection:
        if self._connect:
            conn = self._connect()
        else:
            from reze.database import db

            conn = db.get_connection()
        if not self._ready:
            conn.executescript(_SCHEMA)
            conn.commit()
            self._ready = True
        return conn

    @property
    def state(self) -> Dict[str, Any]:
        if self._state is None:
            raw = self._get(STATE_KEY, None) if self._get else self._db_get()
            base = {"enabled": False, "since": 0, "until": 0, "reason": "", "text": "", "auto_off": False}
            try:
                base.update(json.loads(raw or "{}"))
            except (ValueError, TypeError):
                logger.warning("AFK: ignoring corrupt stored state.")
            self._state = base
        return self._state

    def _db_get(self):
        from reze.database import db

        return db.get_setting(STATE_KEY)

    def _save(self) -> None:
        raw = json.dumps(self.state)
        if self._set:
            self._set(STATE_KEY, raw)
        else:
            from reze.database import db

            db.set_setting(STATE_KEY, raw)

    # ------------------------------------------------------------------ control
    @property
    def active(self) -> bool:
        return bool(self.state["enabled"])

    def enable(self, reason: str = "", seconds: int = 0) -> None:
        now = self._clock()
        self.state.update(enabled=True, since=now, until=now + seconds if seconds else 0, reason=reason.strip()[:200])
        self._replied.clear()
        with self.connect() as conn:
            conn.execute("DELETE FROM afk_missed")
            conn.commit()
        self._save()

    def set_text(self, text: str) -> None:
        self.state["text"] = text.strip()[:500]
        self._save()

    def set_auto_off(self, value: bool) -> None:
        self.state["auto_off"] = bool(value)
        self._save()

    def disable(self) -> Dict[str, Any]:
        """Turn AFK off and return the summary of what was missed (also clears the log)."""
        summary = self.summary()
        self.state.update(enabled=False, until=0)
        with self.connect() as conn:
            conn.execute("DELETE FROM afk_missed")
            conn.commit()
        self._save()
        return summary

    def reply_text(self) -> str:
        custom = self.state.get("text") or ""
        if custom:
            return custom
        reason = self.state.get("reason") or ""
        return DEFAULT_TEXT.format(reason=f" ({reason})" if reason else "")

    # ------------------------------------------------------------------ summary
    def _log(self, kind: str, chat_id, chat_title, sender_id, sender_name, text: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO afk_missed (ts, kind, chat_id, chat_title, sender_id, sender_name, text) VALUES (?,?,?,?,?,?,?)",
                (self._clock(), kind, chat_id, chat_title, sender_id, sender_name, (text or "")[:300]),
            )
            conn.commit()

    def summary(self) -> Dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM afk_missed ORDER BY id").fetchall()
        people: Dict[Any, Dict[str, Any]] = {}
        mentions: List[Any] = []
        for row in rows:
            if row["kind"] == "private":
                entry = people.setdefault(row["sender_id"], {"name": row["sender_name"], "count": 0, "last": ""})
                entry["count"] += 1
                entry["last"] = row["text"]
            else:
                mentions.append(row)
        since = self.state.get("since") or 0
        return {
            "away_for": human_duration(self._clock() - since) if since else "-",
            "people": sorted(people.values(), key=lambda p: -p["count"]),
            "mentions": mentions,
            "total": len(rows),
        }

    def format_summary(self, summary: Dict[str, Any]) -> str:
        from reze.ui import ascii

        lines = [f"Away for: {summary['away_for']}"]
        people, mentions = summary["people"], summary["mentions"]
        if not people and not mentions:
            lines.append("Nothing was missed.")
        if people:
            lines += ["", f"Private messages ({sum(p['count'] for p in people)}):"]
            for person in people[:SUMMARY_LINES]:
                lines.append(f"- {person['name']}: {person['count']}")
            if len(people) > SUMMARY_LINES:
                lines.append(f"  ... and {len(people) - SUMMARY_LINES} more people")
        if mentions:
            lines += ["", f"Mentions ({len(mentions)}):"]
            for row in mentions[:SUMMARY_LINES]:
                lines.append(f"- {row['chat_title']}: {(row['text'] or '')[:60]}")
            if len(mentions) > SUMMARY_LINES:
                lines.append(f"  ... and {len(mentions) - SUMMARY_LINES} more")
        return ascii.frame("Welcome back", lines)

    # ------------------------------------------------------------------- events
    def _expired(self) -> bool:
        until = self.state.get("until") or 0
        return bool(until) and self._clock() >= until

    async def on_new_message(self, event: Any) -> None:
        if not self.active:
            return
        client = getattr(event, "client", None) or self.client_provider()
        message = event.message

        if self._expired():
            summary = self.disable()
            if client:
                try:
                    await client.send_message("me", self.format_summary(summary), parse_mode=None)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("AFK: could not send the summary: %s", exc)
            return

        if getattr(message, "out", False):
            return  # auto-off is handled by on_outgoing

        text = getattr(message, "raw_text", None) or getattr(message, "message", "") or ""
        sender = None
        try:
            sender = await event.get_sender()
        except Exception:  # noqa: BLE001
            pass
        if getattr(sender, "bot", False):
            return

        if getattr(event, "is_private", False):
            await self._handle_private(event, client, sender, text)
        elif getattr(event, "is_group", False) and getattr(message, "mentioned", False):
            chat = None
            try:
                chat = await event.get_chat()
            except Exception:  # noqa: BLE001
                pass
            self._log("mention", event.chat_id, _name(chat), getattr(event, "sender_id", None), _name(sender), text)

    async def _handle_private(self, event: Any, client: Any, sender: Any, text: str) -> None:
        sender_id = getattr(event, "sender_id", None)
        self._log("private", event.chat_id, "", sender_id, _name(sender), text)

        now = self._clock()
        if now - self._replied.get(sender_id, 0) < COOLDOWN_HOURS * 3600:
            return
        while self._recent_replies and now - self._recent_replies[0] > 3600:
            self._recent_replies.popleft()
        if len(self._recent_replies) >= MAX_REPLIES_PER_HOUR or not client:
            return
        try:
            await client.send_message(event.chat_id, self.reply_text(), parse_mode=None)
        except Exception as exc:  # noqa: BLE001
            logger.warning("AFK: auto-reply failed: %s", exc)
            return
        self._replied[sender_id] = now
        self._recent_replies.append(now)

    async def on_outgoing(self, event: Any) -> None:
        """Optional: stop AFK when you start chatting again (ignores commands and Saved Messages)."""
        if not (self.active and self.state.get("auto_off")):
            return
        message = event.message
        text = getattr(message, "raw_text", "") or ""
        if not getattr(message, "out", False):
            return
        client = getattr(event, "client", None) or self.client_provider()
        try:
            own_id = await client.get_peer_id("me") if client else None
        except Exception:  # noqa: BLE001
            own_id = None
        if event.chat_id == own_id:  # Saved Messages: reports and notes, not "I'm back"
            return
        from reze.command_router import router

        if text.startswith(router.prefix) or not text.strip():
            return
        summary = self.disable()
        if client:
            try:
                await client.send_message("me", self.format_summary(summary), parse_mode=None)
            except Exception:  # noqa: BLE001
                pass


afk_service = AfkService()
