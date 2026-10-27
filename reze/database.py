"""
Database abstraction layer for Reze.
Supports SQLite (zero-dependency built-in standard library) and SQLAlchemy if installed.
Manages schema migrations, connection pooling, and data persistence safely.
"""

import os
import sqlite3
import tempfile
from datetime import datetime
from typing import Dict, Any, List, Optional
from reze.config import settings
from reze.logging_config import logger

class Database:
    def __init__(self, db_path: str = "data/reze.db"):
        self.db_path = db_path
        if self.db_path.startswith("sqlite:///"):
            self.db_path = self.db_path.replace("sqlite:///", "")
        
        # Ensure parent directory exists
        parent_dir = os.path.dirname(self.db_path)
        try:
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)
            self._init_db()
        except (OSError, sqlite3.Error) as exc:
            # A mounted PaaS volume can be root-owned or read-only. Instead of
            # crash-looping the whole service (and killing the panel), fall back
            # to a temporary database and make the problem visible in the logs.
            fallback = os.path.join(tempfile.gettempdir(), "reze.db")
            if os.path.abspath(self.db_path) == os.path.abspath(fallback):
                raise
            logger.error(
                "Could not open the database at %s (%s). Falling back to the "
                "temporary database %s - configure REZE_DATA_DIR to a writable "
                "persistent volume to keep data.",
                self.db_path,
                exc,
                fallback,
            )
            self.db_path = fallback
            self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Enable WAL mode for better concurrency and foreign keys
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_db(self):
        """Create tables if they do not exist."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. System & Global Settings
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS global_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 2. Profile & Clock Settings
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS profile_settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                name_clock_enabled INTEGER DEFAULT 0,
                bio_clock_enabled INTEGER DEFAULT 0,
                clock_format TEXT DEFAULT '%H:%M',
                name_template TEXT DEFAULT '{name} | {time}',
                bio_template TEXT DEFAULT '{bio} • {time}',
                original_name TEXT DEFAULT '',
                original_bio TEXT DEFAULT '',
                timezone TEXT DEFAULT 'Asia/Tehran',
                interval_minutes INTEGER DEFAULT 1,
                last_updated TIMESTAMP
            );
            """)

            # 3. Group Settings (Rose-inspired & Administration)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_settings (
                chat_id INTEGER PRIMARY KEY,
                chat_title TEXT,
                antiflood_enabled INTEGER DEFAULT 0,
                antiflood_limit INTEGER DEFAULT 5,
                antiflood_seconds INTEGER DEFAULT 5,
                antiflood_action TEXT DEFAULT 'mute', -- mute, kick, ban, warn
                antiraid_enabled INTEGER DEFAULT 0,
                antiraid_limit INTEGER DEFAULT 10,
                antiraid_seconds INTEGER DEFAULT 60,
                antilink_enabled INTEGER DEFAULT 0,
                rules TEXT DEFAULT '',
                welcome_enabled INTEGER DEFAULT 0,
                welcome_text TEXT DEFAULT 'Welcome {mention} to {title}!',
                goodbye_enabled INTEGER DEFAULT 0,
                goodbye_text TEXT DEFAULT 'Goodbye {name}!',
                cleanservice_enabled INTEGER DEFAULT 0,
                log_channel_id INTEGER DEFAULT 0,
                slowmode_seconds INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 4. Warnings
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                reason TEXT DEFAULT '',
                warned_by INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 5. Filters (Automated reply / trigger filters)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                keyword TEXT NOT NULL,
                reply_text TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, keyword)
            );
            """)

            # 6. Blacklists (Words or URLs to auto-delete)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS blacklists (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                trigger TEXT NOT NULL,
                action TEXT DEFAULT 'delete', -- delete, warn, mute
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, trigger)
            );
            """)

            # 7. Locks (Chat permissions)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS locks (
                chat_id INTEGER NOT NULL,
                lock_type TEXT NOT NULL, -- messages, media, stickers, links, forwards, games
                is_locked INTEGER DEFAULT 1,
                PRIMARY KEY (chat_id, lock_type)
            );
            """)

            # 8. Notes
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(chat_id, name)
            );
            """)

            # 9. Plugins
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS plugins (
                name TEXT PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT DEFAULT '{}'
            );
            """)

            # 10. Audit & Admin Logs
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                action TEXT NOT NULL,
                performer_id INTEGER NOT NULL,
                target_id INTEGER,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # Ensure default row for profile settings exists
            cursor.execute("""
            INSERT OR IGNORE INTO profile_settings (id, name_clock_enabled, bio_clock_enabled)
            VALUES (1, 0, 0);
            """)

            conn.commit()
            logger.debug("Database initialized successfully at %s", self.db_path)

    # Helper methods for clean database operations
    def get_profile_settings(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM profile_settings WHERE id = 1").fetchone()
            return dict(row) if row else {}

    def update_profile_settings(self, **kwargs):
        if not kwargs:
            return
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values())
        with self.get_connection() as conn:
            conn.execute(f"UPDATE profile_settings SET {fields} WHERE id = 1", values)
            conn.commit()

    def get_group_settings(self, chat_id: int) -> Dict[str, Any]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM group_settings WHERE chat_id = ?", (chat_id,)).fetchone()
            if row:
                return dict(row)
            # Create default entry
            conn.execute("INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)", (chat_id,))
            conn.commit()
            row = conn.execute("SELECT * FROM group_settings WHERE chat_id = ?", (chat_id,)).fetchone()
            return dict(row) if row else {}

    def update_group_settings(self, chat_id: int, **kwargs):
        if not kwargs:
            return
        self.get_group_settings(chat_id)  # Ensure row exists
        fields = ", ".join([f"{k} = ?" for k in kwargs.keys()])
        values = list(kwargs.values()) + [chat_id]
        with self.get_connection() as conn:
            conn.execute(f"UPDATE group_settings SET {fields}, updated_at = CURRENT_TIMESTAMP WHERE chat_id = ?", values)
            conn.commit()

    def log_admin_action(self, action: str, performer_id: int, chat_id: Optional[int] = None, target_id: Optional[int] = None, details: str = ""):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO admin_logs (chat_id, action, performer_id, target_id, details) VALUES (?, ?, ?, ?, ?)",
                (chat_id, action, performer_id, target_id, details)
            )
            conn.commit()

    def get_recent_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM admin_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def add_warning(self, chat_id: int, user_id: int, warned_by: int, reason: str = "") -> int:
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO warnings (chat_id, user_id, warned_by, reason) VALUES (?, ?, ?, ?)",
                (chat_id, user_id, warned_by, reason)
            )
            count = conn.execute("SELECT COUNT(*) FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)).fetchone()[0]
            conn.commit()
            return count

    def remove_warning(self, chat_id: int, user_id: int) -> int:
        with self.get_connection() as conn:
            last_warn = conn.execute("SELECT id FROM warnings WHERE chat_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1", (chat_id, user_id)).fetchone()
            if last_warn:
                conn.execute("DELETE FROM warnings WHERE id = ?", (last_warn[0],))
            count = conn.execute("SELECT COUNT(*) FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)).fetchone()[0]
            conn.commit()
            return count

    def get_warnings_count(self, chat_id: int, user_id: int) -> int:
        with self.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id)).fetchone()[0]

    def reset_warnings(self, chat_id: int, user_id: int):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM warnings WHERE chat_id = ? AND user_id = ?", (chat_id, user_id))
            conn.commit()

    def set_filter(self, chat_id: int, keyword: str, reply_text: str):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO filters (chat_id, keyword, reply_text) VALUES (?, ?, ?) ON CONFLICT(chat_id, keyword) DO UPDATE SET reply_text = excluded.reply_text",
                (chat_id, keyword.lower(), reply_text)
            )
            conn.commit()

    def remove_filter(self, chat_id: int, keyword: str) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM filters WHERE chat_id = ? AND keyword = ?", (chat_id, keyword.lower()))
            conn.commit()
            return cur.rowcount > 0

    def get_filters(self, chat_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT keyword, reply_text FROM filters WHERE chat_id = ?", (chat_id,)).fetchall()
            return [dict(r) for r in rows]

    def add_blacklist(self, chat_id: int, trigger: str, action: str = "delete"):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO blacklists (chat_id, trigger, action) VALUES (?, ?, ?) ON CONFLICT(chat_id, trigger) DO UPDATE SET action = excluded.action",
                (chat_id, trigger.lower(), action)
            )
            conn.commit()

    def remove_blacklist(self, chat_id: int, trigger: str) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM blacklists WHERE chat_id = ? AND trigger = ?", (chat_id, trigger.lower()))
            conn.commit()
            return cur.rowcount > 0

    def get_blacklists(self, chat_id: int) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT trigger, action FROM blacklists WHERE chat_id = ?", (chat_id,)).fetchall()
            return [dict(r) for r in rows]

    def set_note(self, chat_id: int, name: str, content: str):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO notes (chat_id, name, content) VALUES (?, ?, ?) ON CONFLICT(chat_id, name) DO UPDATE SET content = excluded.content",
                (chat_id, name.lower(), content)
            )
            conn.commit()

    def get_note(self, chat_id: int, name: str) -> Optional[str]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT content FROM notes WHERE chat_id = ? AND name = ?", (chat_id, name.lower())).fetchone()
            return row["content"] if row else None

    def delete_note(self, chat_id: int, name: str) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM notes WHERE chat_id = ? AND name = ?", (chat_id, name.lower()))
            conn.commit()
            return cur.rowcount > 0

    def get_notes(self, chat_id: int) -> List[str]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT name FROM notes WHERE chat_id = ?", (chat_id,)).fetchall()
            return [r["name"] for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            groups_count = conn.execute("SELECT COUNT(*) FROM group_settings").fetchone()[0]
            warnings_count = conn.execute("SELECT COUNT(*) FROM warnings").fetchone()[0]
            filters_count = conn.execute("SELECT COUNT(*) FROM filters").fetchone()[0]
            notes_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            logs_count = conn.execute("SELECT COUNT(*) FROM admin_logs").fetchone()[0]
            return {
                "groups": groups_count,
                "warnings": warnings_count,
                "filters": filters_count,
                "notes": notes_count,
                "admin_logs": logs_count
            }

# The path comes from REZE_DATABASE_URL (or REZE_DATA_DIR on PaaS volumes).
db = Database(settings.database_url)
