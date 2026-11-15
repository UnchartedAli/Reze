"""REZE 4.0 schema, migration 5: Channel Digest.

Creates tables only. Nothing is enabled by this migration: the config row has
``enabled = 0``, and the global ``channel_digest`` feature is OFF by default.
"""

from __future__ import annotations

import sqlite3

from reze.core.migrations import execute_all

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS digest_config (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        enabled INTEGER NOT NULL DEFAULT 0,
        paused INTEGER NOT NULL DEFAULT 0,
        time_of_day TEXT NOT NULL DEFAULT '21:00',
        timezone TEXT NOT NULL DEFAULT 'UTC',
        schedule TEXT NOT NULL DEFAULT 'daily',
        days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
        max_messages INTEGER NOT NULL DEFAULT 200,
        max_chars INTEGER NOT NULL DEFAULT 12000,
        ai_enabled INTEGER NOT NULL DEFAULT 0,
        language TEXT NOT NULL DEFAULT 'en',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "INSERT OR IGNORE INTO digest_config (id) VALUES (1)",
    """
    CREATE TABLE IF NOT EXISTS digest_channels (
        chat_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        username TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        priority INTEGER NOT NULL DEFAULT 5,
        include_keywords TEXT NOT NULL DEFAULT '',
        exclude_keywords TEXT NOT NULL DEFAULT '',
        last_message_id INTEGER NOT NULL DEFAULT 0,
        last_synced_at TEXT,
        added_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS digest_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        slot_key TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL DEFAULT 'scheduled',
        status TEXT NOT NULL,
        period_start TEXT,
        period_end TEXT,
        channel_count INTEGER NOT NULL DEFAULT 0,
        message_count INTEGER NOT NULL DEFAULT 0,
        important_count INTEGER NOT NULL DEFAULT 0,
        summary_mode TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        chunk_total INTEGER NOT NULL DEFAULT 0,
        delivered_chunks INTEGER NOT NULL DEFAULT 0,
        delivered_ids TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT,
        last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_digest_runs_status ON digest_runs(status)",
]


def apply(conn: sqlite3.Connection) -> None:
    execute_all(conn, STATEMENTS)


__all__ = ["STATEMENTS", "apply"]
