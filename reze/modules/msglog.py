"""
Message Guard: keep a short-lived local copy of messages in the chats you watch
and, when one is deleted (or edited), send the saved copy to Saved Messages.

How it works
------------
* ``on_new_message`` stores text + metadata in SQLite and downloads small media
  files into ``<data_dir>/msglog/`` right away (a deleted message can no longer
  be downloaded afterwards).
* ``on_deleted`` / ``on_edited`` look the message up and deliver a report (and the
  saved media) to the configured destination (``me`` = Saved Messages).
* Everything older than ``retention_hours`` is purged automatically.

Telegram quirk handled here: delete events of private chats and basic groups
carry no chat id, and their message ids are unique per account. Channels and
supergroups report a chat id and have per-chat ids. Messages are therefore keyed
by ``(scope, message_id)`` where scope is the channel id or ``0``.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from reze.logging_config import logger

CONFIG_KEY = "msglog:config"

DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "dest": "me",             # "me" (Saved Messages) or a numeric chat id
    "chats": [],              # explicitly watched chat ids
    "private": False,         # watch every private chat
    "groups": False,          # watch every group / supergroup
    "edits": True,            # also report edited messages
    "media": True,            # cache media so deleted files can be re-sent
    "archive": True,          # keep a PERMANENT local copy of deleted messages and timed media
    "ttl": True,              # save self-destructing (timed / view-once) media right away
    "own": False,             # also log messages sent by the owner
    "retention_hours": 48,
    "max_media_mb": 25,
}

ARCHIVE_MAX_MB = 2048   # stop archiving *media files* beyond this (metadata keeps being saved)
MAX_REPORTS_PER_EVENT = 15
DOWNLOAD_WAIT_SECONDS = 8

_SCHEMA = """
CREATE TABLE IF NOT EXISTS msglog (
    scope       INTEGER NOT NULL,
    msg_id      INTEGER NOT NULL,
    chat_id     INTEGER,
    chat_title  TEXT,
    chat_kind   TEXT,
    sender_id   INTEGER,
    sender_name TEXT,
    text        TEXT,
    media_kind  TEXT,
    media_path  TEXT,
    sent_at     REAL,
    stored_at   REAL,
    PRIMARY KEY (scope, msg_id)
);
CREATE INDEX IF NOT EXISTS idx_msglog_stored ON msglog (stored_at);

CREATE TABLE IF NOT EXISTS msglog_archive (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT,
    chat_id     INTEGER,
    chat_title  TEXT,
    chat_kind   TEXT,
    sender_id   INTEGER,
    sender_name TEXT,
    text        TEXT,
    media_kind  TEXT,
    media_path  TEXT,
    sent_at     REAL,
    saved_at    REAL
);
"""


def media_kind(message: Any) -> Optional[str]:
    """Return a short label for the media of *message* (or ``None``)."""
    if not getattr(message, "media", None):
        return None
    for attr, label in (
        ("sticker", "sticker"),
        ("gif", "gif"),
        ("video_note", "video note"),
        ("voice", "voice"),
        ("audio", "audio"),
        ("video", "video"),
        ("photo", "photo"),
    ):
        if getattr(message, attr, None):
            return label
    for attr, label in (("poll", "poll"), ("geo", "location"), ("contact", "contact")):
        if getattr(message, attr, None):
            return label
    if getattr(message, "document", None) or getattr(message, "file", None):
        return "file"
    return None


VIEW_ONCE = 0x7FFFFFFF


def timed_media_seconds(message: Any) -> int:
    """Self-destruct timer of the message's media in seconds (0 = normal media)."""
    value = getattr(getattr(message, "media", None), "ttl_seconds", None)
    try:
        return int(value) if value else 0
    except (TypeError, ValueError):
        return 0


def describe_ttl(seconds: int) -> str:
    return "view once" if seconds >= VIEW_ONCE else f"{seconds}s timer"


_DOWNLOADABLE = {"sticker", "gif", "video note", "voice", "audio", "video", "photo", "file"}


def _display_name(entity: Any) -> str:
    if entity is None:
        return "Unknown"
    first = getattr(entity, "first_name", None)
    if first is not None or getattr(entity, "last_name", None) is not None:
        name = " ".join(p for p in (first, getattr(entity, "last_name", None)) if p).strip()
    else:
        name = getattr(entity, "title", "") or ""
    username = getattr(entity, "username", None)
    if username:
        name = f"{name} (@{username})".strip()
    return name or str(getattr(entity, "id", "Unknown"))


class MessageLogger:
    def __init__(
        self,
        connect: Optional[Callable[[], sqlite3.Connection]] = None,
        get_setting: Optional[Callable[[str, Optional[str]], Optional[str]]] = None,
        set_setting: Optional[Callable[[str, str], None]] = None,
        cache_dir: Optional[str] = None,
        clock: Callable[[], float] = time.time,
    ):
        self._connect = connect
        self._get_setting = get_setting
        self._set_setting = set_setting
        self._cache_dir = cache_dir
        self._clock = clock
        self._cfg: Optional[Dict[str, Any]] = None
        self._ready = False
        self._pending: Dict[tuple, "asyncio.Task"] = {}
        self._purge_task: Optional["asyncio.Task"] = None
        self.client_provider: Callable[[], Any] = lambda: None
        self.stats = {"stored": 0, "deleted": 0, "edited": 0, "timed": 0}

    # ------------------------------------------------------------ plumbing
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
    def cache_dir(self) -> str:
        if not self._cache_dir:
            from reze.config import settings

            self._cache_dir = os.path.join(settings.data_dir, "msglog")
        os.makedirs(self._cache_dir, exist_ok=True)
        return self._cache_dir

    def _read_setting(self) -> Optional[str]:
        if self._get_setting:
            return self._get_setting(CONFIG_KEY, None)
        from reze.database import db

        return db.get_setting(CONFIG_KEY)

    def _write_setting(self, value: str) -> None:
        if self._set_setting:
            self._set_setting(CONFIG_KEY, value)
            return
        from reze.database import db

        db.set_setting(CONFIG_KEY, value)

    # -------------------------------------------------------------- config
    @property
    def config(self) -> Dict[str, Any]:
        if self._cfg is None:
            cfg = dict(DEFAULT_CONFIG)
            try:
                stored = json.loads(self._read_setting() or "{}")
                if isinstance(stored, dict):
                    cfg.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG})
            except (ValueError, TypeError):
                logger.warning("Message Guard: ignoring a corrupt stored configuration.")
            cfg["chats"] = [int(c) for c in cfg.get("chats", [])]
            self._cfg = cfg
        return self._cfg

    def update(self, **changes: Any) -> Dict[str, Any]:
        cfg = self.config
        for key, value in changes.items():
            if key not in DEFAULT_CONFIG:
                raise KeyError(key)
            cfg[key] = value
        self._write_setting(json.dumps(cfg))
        return cfg

    def add_chat(self, chat_id: int) -> bool:
        chats = list(self.config["chats"])
        if chat_id in chats:
            return False
        chats.append(int(chat_id))
        self.update(chats=chats)
        return True

    def remove_chat(self, chat_id: int) -> bool:
        chats = list(self.config["chats"])
        if chat_id not in chats:
            return False
        chats.remove(chat_id)
        self.update(chats=chats)
        return True

    def is_watched(self, chat_id: Optional[int], *, private: bool, group: bool) -> bool:
        cfg = self.config
        if not cfg["enabled"] or chat_id is None:
            return False
        if chat_id in cfg["chats"]:
            return True
        if private and cfg["private"]:
            return True
        return bool(group and cfg["groups"])

    # --------------------------------------------------------------- store
    def _row(self, scope: int, msg_id: int) -> Optional[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                "SELECT * FROM msglog WHERE scope = ? AND msg_id = ?", (scope, msg_id)
            ).fetchone()

    def count(self) -> int:
        with self.connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM msglog").fetchone()[0]

    def purge_expired(self) -> int:
        """Delete cached (not yet reported) copies past retention. The archive is never touched."""
        if float(self.config["retention_hours"]) <= 0:
            return 0  # "forever"
        cutoff = self._clock() - float(self.config["retention_hours"]) * 3600
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT scope, msg_id, media_path FROM msglog WHERE stored_at < ?", (cutoff,)
            ).fetchall()
            conn.execute("DELETE FROM msglog WHERE stored_at < ?", (cutoff,))
            conn.commit()
        for row in rows:
            self._remove_file(row["media_path"])
        return len(rows)

    def clear(self) -> int:
        with self.connect() as conn:
            rows = conn.execute("SELECT media_path FROM msglog").fetchall()
            conn.execute("DELETE FROM msglog")
            conn.commit()
        for row in rows:
            self._remove_file(row["media_path"])
        return len(rows)

    @staticmethod
    def _remove_file(path: Optional[str]) -> None:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    # ------------------------------------------------------------- archive
    @property
    def archive_dir(self) -> str:
        path = os.path.join(self.cache_dir, "archive")
        os.makedirs(path, exist_ok=True)
        return path

    def archive_stats(self):
        """``(items, megabytes_on_disk)`` of the permanent archive."""
        with self.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM msglog_archive").fetchone()[0]
        total = 0
        if os.path.isdir(os.path.join(self.cache_dir, "archive")):
            for entry in os.scandir(self.archive_dir):
                if entry.is_file():
                    total += entry.stat().st_size
        return count, total / (1024 * 1024)

    def _archive(self, row: Any, kind: str, ref: str) -> None:
        """Keep a permanent copy (metadata + media file) of something that was delivered."""
        def pick(key):
            try:
                return row[key]
            except (KeyError, IndexError):
                return None

        media_path = pick("media_path")
        kept = None
        if media_path and os.path.isfile(media_path):
            if self.archive_stats()[1] < ARCHIVE_MAX_MB:
                name = f"{int(self._clock())}_{kind}_{ref}{os.path.splitext(media_path)[1]}"
                kept = os.path.join(self.archive_dir, name)
                try:
                    shutil.move(media_path, kept)
                except OSError as exc:
                    logger.warning("Message Guard: could not archive %s: %s", media_path, exc)
                    kept = None
            else:
                logger.warning("Message Guard: archive is over %d MB; media not kept.", ARCHIVE_MAX_MB)
            self._remove_file(media_path)  # no-op when it was moved
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO msglog_archive (kind, chat_id, chat_title, chat_kind, sender_id, sender_name, "
                "text, media_kind, media_path, sent_at, saved_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (kind, pick("chat_id"), pick("chat_title"), pick("chat_kind"), pick("sender_id"),
                 pick("sender_name"), pick("text"), pick("media_kind"), kept, pick("sent_at"), self._clock()),
            )
            conn.commit()

    def clear_archive(self) -> int:
        with self.connect() as conn:
            rows = conn.execute("SELECT media_path FROM msglog_archive").fetchall()
            conn.execute("DELETE FROM msglog_archive")
            conn.commit()
        for row in rows:
            self._remove_file(row["media_path"])
        return len(rows)

    # ------------------------------------------------------------- capture
    async def on_new_message(self, event: Any) -> None:
        cfg = self.config
        if not cfg["enabled"]:
            return
        message = event.message
        if getattr(message, "out", False) and not cfg["own"]:
            return
        if getattr(message, "action", None):  # service messages
            return

        chat_id = event.chat_id
        is_channel = bool(getattr(event, "is_channel", False))
        is_private = bool(getattr(event, "is_private", False))
        is_group = bool(getattr(event, "is_group", False))
        if not self.is_watched(chat_id, private=is_private, group=is_group):
            return

        text = getattr(message, "raw_text", None) or getattr(message, "message", "") or ""
        kind = media_kind(message)
        if not text and not kind:
            return

        ttl = timed_media_seconds(message)
        if ttl and cfg["ttl"]:
            await self._save_timed_media(event, message, kind or "media", ttl, text)
            return

        scope = chat_id if is_channel else 0
        sender = chat = None
        try:
            sender = await event.get_sender()
        except Exception:  # noqa: BLE001 - best effort metadata
            pass
        try:
            chat = await event.get_chat()
        except Exception:  # noqa: BLE001
            pass

        sent = getattr(message, "date", None)
        sent_ts = sent.timestamp() if hasattr(sent, "timestamp") else self._clock()
        chat_kind = "private" if is_private else ("group" if is_group else "channel")
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO msglog (scope, msg_id, chat_id, chat_title, chat_kind, "
                "sender_id, sender_name, text, media_kind, media_path, sent_at, stored_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    scope, message.id, chat_id, _display_name(chat), chat_kind,
                    getattr(event, "sender_id", None), _display_name(sender), text,
                    kind, sent_ts, self._clock(),
                ),
            )
            conn.commit()
        self.stats["stored"] += 1

        if cfg["media"] and kind in _DOWNLOADABLE:
            size = getattr(getattr(message, "file", None), "size", 0) or 0
            if size <= int(cfg["max_media_mb"]) * 1024 * 1024:
                key = (scope, message.id)
                self._pending[key] = asyncio.ensure_future(self._download(message, key))

    async def _download(self, message: Any, key: tuple) -> None:
        scope, msg_id = key
        try:
            target = os.path.join(self.cache_dir, f"{scope}_{msg_id}")
            path = await message.download_media(file=target)
            if path:
                with self.connect() as conn:
                    conn.execute(
                        "UPDATE msglog SET media_path = ? WHERE scope = ? AND msg_id = ?",
                        (str(path), scope, msg_id),
                    )
                    conn.commit()
        except Exception as exc:  # noqa: BLE001 - media is optional
            logger.debug("Message Guard: could not cache media %s: %s", key, exc)
        finally:
            self._pending.pop(key, None)

    async def _save_timed_media(self, event: Any, message: Any, kind: str, ttl: int, text: str) -> None:
        """
        Copy a self-destructing photo/video/voice to the destination immediately.

        The copy is sent right away (not on deletion): such media disappears from the
        chat as soon as it is opened, and nothing is stored in the local database.
        """
        client = getattr(event, "client", None) or self.client_provider()
        if not client:
            return
        sender = chat = None
        try:
            sender = await event.get_sender()
        except Exception:  # noqa: BLE001
            pass
        try:
            chat = await event.get_chat()
        except Exception:  # noqa: BLE001
            pass

        sent = getattr(message, "date", None)
        row = {
            "sender_id": getattr(event, "sender_id", None), "sender_name": _display_name(sender),
            "chat_title": _display_name(chat), "text": text, "media_kind": f"{kind} ({describe_ttl(ttl)})",
            "sent_at": sent.timestamp() if hasattr(sent, "timestamp") else self._clock(),
            "chat_kind": "private" if getattr(event, "is_private", False) else "group",
            "chat_id": getattr(event, "chat_id", None),
        }

        path = None
        size = getattr(getattr(message, "file", None), "size", 0) or 0
        if size <= int(self.config["max_media_mb"]) * 1024 * 1024:
            try:
                target = os.path.join(self.cache_dir, f"ttl_{getattr(message, 'id', 0)}_{int(self._clock())}")
                path = await message.download_media(file=target)
            except Exception as exc:  # noqa: BLE001 - Telegram may refuse to serve this media
                logger.debug("Message Guard: timed media download failed: %s", exc)
        try:
            if path and os.path.isfile(path):
                report = self.format_report(row, "Self-destructing media")
                caption = report if len(report) <= 1000 else report[:990] + "..."
                try:
                    await client.send_file(self.destination(), path, caption=caption, parse_mode=None)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Message Guard: could not send timed media: %s", exc)
                    return
                self.stats["timed"] += 1
            else:
                row["text"] = "Media could not be downloaded." + (f"\n{text}" if text else "")
                await self._send_text(client, self.format_report(row, "Self-destructing media"))
        finally:
            if self.config["archive"] and (path and os.path.isfile(path)):
                row["media_path"] = path
                self._archive(row, "timed", f"{getattr(message, 'id', 0)}")
            else:
                self._remove_file(path)

    # -------------------------------------------------------------- events
    async def _wait_download(self, key: tuple) -> None:
        task = self._pending.get(key)
        if task:
            try:
                await asyncio.wait_for(asyncio.shield(task), DOWNLOAD_WAIT_SECONDS)
            except Exception:  # noqa: BLE001
                pass

    async def on_deleted(self, event: Any) -> None:
        if not self.config["enabled"]:
            return
        scope = getattr(event, "chat_id", None) or 0
        ids = list(getattr(event, "deleted_ids", []) or [])
        client = getattr(event, "client", None) or self.client_provider()
        if not client:
            return

        sent_reports = 0
        found = 0
        for msg_id in ids:
            await self._wait_download((scope, msg_id))
            row = self._row(scope, msg_id)
            if row is None:
                continue
            found += 1
            if sent_reports < MAX_REPORTS_PER_EVENT:
                await self._deliver(client, row, "Deleted message")
                sent_reports += 1
                if sent_reports < len(ids):
                    await asyncio.sleep(0.4)  # stay clear of flood limits
            with self.connect() as conn:
                conn.execute("DELETE FROM msglog WHERE scope = ? AND msg_id = ?", (scope, msg_id))
                conn.commit()
            if self.config["archive"]:
                self._archive(row, "deleted", f"{scope}_{msg_id}")
            else:
                self._remove_file(row["media_path"])
            self.stats["deleted"] += 1

        if found > sent_reports:
            await self._send_text(
                client,
                f"+ {found - sent_reports} more deleted messages were not shown"
                + (" (saved in the local archive)." if self.config["archive"] else "."),
            )

    async def on_edited(self, event: Any) -> None:
        cfg = self.config
        if not cfg["enabled"] or not cfg["edits"]:
            return
        message = event.message
        if getattr(message, "out", False) and not cfg["own"]:
            return
        is_channel = bool(getattr(event, "is_channel", False))
        scope = event.chat_id if is_channel else 0
        row = self._row(scope, message.id)
        if row is None:
            return
        new_text = getattr(message, "raw_text", None) or getattr(message, "message", "") or ""
        if new_text == (row["text"] or ""):
            return  # reaction / media-only change
        client = getattr(event, "client", None) or self.client_provider()
        if not client:
            return
        await self._deliver(client, row, "Edited message", new_text=new_text, with_media=False)
        with self.connect() as conn:
            conn.execute(
                "UPDATE msglog SET text = ? WHERE scope = ? AND msg_id = ?",
                (new_text, scope, message.id),
            )
            conn.commit()
        self.stats["edited"] += 1

    # ------------------------------------------------------------- reports
    @staticmethod
    def _stamp(ts: Optional[float]) -> str:
        if not ts:
            return "-"
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def format_report(self, row: Any, title: str, new_text: Optional[str] = None) -> str:
        from reze.ui import ascii

        who = row["sender_name"] or "Unknown"
        if row["sender_id"]:
            who = f"{who} [{row['sender_id']}]"
        lines = [
            f"From : {who}",
            f"Chat : {row['chat_title'] or '-'} ({row['chat_kind'] or '?'})",
            f"Sent : {self._stamp(row['sent_at'])}",
            f"Seen : {self._stamp(self._clock())}",
        ]
        if row["media_kind"]:
            lines.append(f"Media: {row['media_kind']}")
        body = (row["text"] or "").strip()
        limit = 2500
        if new_text is not None:
            lines.append("")
            lines.append("Before:")
            lines.append(body[:limit] or "(empty)")
            lines.append("After:")
            lines.append(new_text.strip()[:limit] or "(empty)")
        elif body:
            lines.append("")
            lines.append(body[: limit * 2 if limit else 0])
        return ascii.frame(title, lines)

    def destination(self) -> Any:
        dest = self.config["dest"]
        if isinstance(dest, str) and dest.lstrip("-").isdigit():
            return int(dest)
        return dest or "me"

    async def _send_text(self, client: Any, text: str) -> None:
        try:
            await client.send_message(self.destination(), text, parse_mode=None)
        except Exception as exc:  # noqa: BLE001
            logger.error("Message Guard: could not deliver a report: %s", exc)

    async def _deliver(
        self, client: Any, row: Any, title: str,
        new_text: Optional[str] = None, with_media: bool = True,
    ) -> None:
        report = self.format_report(row, title, new_text)
        path = row["media_path"]
        if with_media and path and os.path.isfile(path):
            try:
                caption = report if len(report) <= 1000 else report[:990] + "..."
                await client.send_file(self.destination(), path, caption=caption, parse_mode=None)
                if len(report) > 1000:
                    await self._send_text(client, report)
                return
            except Exception as exc:  # noqa: BLE001
                logger.error("Message Guard: could not re-send media: %s", exc)
        await self._send_text(client, report)

    # ----------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._purge_task is None or self._purge_task.done():
            self._purge_task = asyncio.ensure_future(self._purge_loop())

    def stop(self) -> None:
        if self._purge_task:
            self._purge_task.cancel()
            self._purge_task = None

    async def _purge_loop(self) -> None:
        while True:
            try:
                removed = self.purge_expired()
                if removed:
                    logger.info("Message Guard: purged %d expired messages.", removed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Message Guard purge failed: %s", exc)
            await asyncio.sleep(3600)


message_logger = MessageLogger()
