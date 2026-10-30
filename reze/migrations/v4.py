"""REZE 3.0 schema, migration 4: universal search (FTS5 with a safe fallback)."""

from __future__ import annotations

import sqlite3

from reze.core.migrations import execute_all
from reze.logging_config import logger

STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS search_index (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        ref_id TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '',
        tags TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(kind, ref_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_search_kind ON search_index(kind)",
]

FTS_STATEMENTS = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
        title, body, tags,
        content='search_index',
        content_rowid='id',
        tokenize='unicode61 remove_diacritics 0'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS search_index_ai AFTER INSERT ON search_index BEGIN
        INSERT INTO search_fts(rowid, title, body, tags)
        VALUES (new.id, new.title, new.body, new.tags);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS search_index_ad AFTER DELETE ON search_index BEGIN
        INSERT INTO search_fts(search_fts, rowid, title, body, tags)
        VALUES ('delete', old.id, old.title, old.body, old.tags);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS search_index_au AFTER UPDATE ON search_index BEGIN
        INSERT INTO search_fts(search_fts, rowid, title, body, tags)
        VALUES ('delete', old.id, old.title, old.body, old.tags);
        INSERT INTO search_fts(rowid, title, body, tags)
        VALUES (new.id, new.title, new.body, new.tags);
    END
    """,
]


def apply(conn: sqlite3.Connection) -> None:
    execute_all(conn, STATEMENTS)
    try:
        execute_all(conn, FTS_STATEMENTS)
        conn.execute(
            "INSERT INTO global_settings (key, value) VALUES ('search.fts5', '1') "
            "ON CONFLICT(key) DO UPDATE SET value = '1'"
        )
    except sqlite3.Error as exc:
        # SQLite builds without FTS5 still get a working (slower) LIKE search.
        logger.warning("FTS5 is unavailable in this SQLite build (%s); using LIKE search.", exc)
        conn.execute(
            "INSERT INTO global_settings (key, value) VALUES ('search.fts5', '0') "
            "ON CONFLICT(key) DO UPDATE SET value = '0'"
        )
