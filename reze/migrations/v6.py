"""REZE 4.0 schema, migration 6: Style Assistant.

Creates tables only. The feature is OFF, and auto-reply is OFF per default.
Only the owner's own outgoing text is ever stored in ``style_samples``.
"""

from __future__ import annotations

import sqlite3

from reze.core.migrations import execute_all

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS style_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        msg_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        learned_at TEXT NOT NULL,
        UNIQUE (chat_id, msg_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS style_profile (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        profile TEXT NOT NULL DEFAULT '{}',
        sample_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT
    )
    """,
    "INSERT OR IGNORE INTO style_profile (id) VALUES (1)",
    """
    CREATE TABLE IF NOT EXISTS style_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        auto_enabled INTEGER NOT NULL DEFAULT 0,
        quiet_start TEXT NOT NULL DEFAULT '',
        quiet_end TEXT NOT NULL DEFAULT '',
        timezone TEXT NOT NULL DEFAULT 'UTC',
        cooldown_hours INTEGER NOT NULL DEFAULT 6,
        hourly_cap INTEGER NOT NULL DEFAULT 10,
        owner_active_minutes INTEGER NOT NULL DEFAULT 30,
        language TEXT NOT NULL DEFAULT 'en'
    )
    """,
    "INSERT OR IGNORE INTO style_settings (id) VALUES (1)",
    """
    CREATE TABLE IF NOT EXISTS style_auto_chats (
        chat_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        last_reply_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS style_auto_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        sent_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS style_drafts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        reply_to_id INTEGER,
        draft TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    )
    """,
]


def apply(conn: sqlite3.Connection) -> None:
    execute_all(conn, STATEMENTS)


__all__ = ["STATEMENTS", "apply"]
