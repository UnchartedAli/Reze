"""
Database abstraction layer for Reze.
Supports SQLite (zero-dependency built-in standard library) and SQLAlchemy if installed.
Manages schema migrations, connection pooling, and data persistence safely.
"""

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence
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

    @contextmanager
    def connection(self):
        """Context manager that commits, rolls back and always closes."""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Run one statement and return ``lastrowid`` (or ``rowcount``)."""
        with self.connection() as conn:
            cursor = conn.execute(sql, params)
            return int(cursor.lastrowid or cursor.rowcount or 0)

    def query(self, sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

    @property
    def schema_version(self) -> int:
        """Current ``PRAGMA user_version`` (migration level)."""
        try:
            with self.get_connection() as conn:
                row = conn.execute("PRAGMA user_version").fetchone()
                return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0

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

            # 11. Personal archive (saves, links, message references)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS archive (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL DEFAULT 'note',
                title TEXT DEFAULT '',
                content TEXT DEFAULT '',
                url TEXT DEFAULT '',
                chat_id INTEGER,
                message_id INTEGER,
                tags TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 12. Personal notes (owner-scoped, distinct from per-chat notes)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS personal_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)

            # 13. Reminders and scheduled personal actions
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                due_at TIMESTAMP NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fired_at TIMESTAMP
            );
            """)

            # 14. Automation rules (trigger -> condition -> action)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS automations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 0,
                trigger_type TEXT NOT NULL,
                trigger_config TEXT NOT NULL DEFAULT '{}',
                conditions TEXT NOT NULL DEFAULT '[]',
                actions TEXT NOT NULL DEFAULT '[]',
                cooldown_seconds INTEGER NOT NULL DEFAULT 60,
                created_by INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_run TIMESTAMP,
                run_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT DEFAULT ''
            );
            """)

            # 15. Bounded task history for the web panel
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS task_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                command TEXT DEFAULT '',
                status TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                finished_at TIMESTAMP,
                duration_seconds REAL DEFAULT 0,
                error TEXT DEFAULT ''
            );
            """)

            # Ensure default row for profile settings exists
            cursor.execute("""
            INSERT OR IGNORE INTO profile_settings (id, name_clock_enabled, bio_clock_enabled)
            VALUES (1, 0, 0);
            """)

            conn.commit()

            # Versioned, incremental migrations (REZE 3). The baseline above is
            # the REZE 2 schema; migrations only ever add to it.
            from reze.core.migrations import run_migrations
            from reze.migrations import MIGRATIONS

            applied = run_migrations(conn, MIGRATIONS)
            if applied:
                logger.info("Applied database migrations: %s", ", ".join(str(v) for v in applied))
            logger.debug(
                "Database initialized successfully at %s (schema v%d)",
                self.db_path,
                self.schema_version,
            )

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

    # ------------------------------------------------------------------ Settings
    def get_setting(self, key: str, default: Optional[str] = None) -> Optional[str]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT value FROM global_settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default

    def set_setting(self, key: str, value: str):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO global_settings (key, value, updated_at) "
                "VALUES (?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
                "updated_at = CURRENT_TIMESTAMP",
                (key, str(value)),
            )
            conn.commit()

    def delete_setting(self, key: str) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM global_settings WHERE key = ?", (key,))
            conn.commit()
            return cur.rowcount > 0

    def all_settings(self) -> Dict[str, str]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT key, value FROM global_settings").fetchall()
            return {r["key"]: r["value"] for r in rows}

    # ------------------------------------------------------------------- Archive
    def add_archive(
        self,
        kind: str,
        title: str = "",
        content: str = "",
        url: str = "",
        chat_id: Optional[int] = None,
        message_id: Optional[int] = None,
        tags: str = "",
    ) -> int:
        with self.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO archive (kind, title, content, url, chat_id, message_id, tags) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, title, content, url, chat_id, message_id, tags),
            )
            conn.commit()
            return int(cur.lastrowid)

    def search_archive(
        self, query: str, limit: int = 20, kind: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Case-insensitive LIKE search across title, content, url and tags."""
        limit = max(1, min(int(limit), 100))
        needle = f"%{query.lower()}%"
        sql = (
            "SELECT * FROM archive WHERE (lower(title) LIKE ? OR lower(content) LIKE ? "
            "OR lower(url) LIKE ? OR lower(tags) LIKE ?)"
        )
        params: List[Any] = [needle, needle, needle, needle]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def list_archive(self, limit: int = 50, kind: Optional[str] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        sql = "SELECT * FROM archive"
        params: List[Any] = []
        if kind:
            sql += " WHERE kind = ?"
            params.append(kind)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def delete_archive(self, entry_id: int) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM archive WHERE id = ?", (entry_id,))
            conn.commit()
            return cur.rowcount > 0

    def archive_count(self) -> int:
        with self.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM archive").fetchone()[0]

    # ------------------------------------------------------------ Personal notes
    def set_personal_note(self, name: str, content: str):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO personal_notes (name, content) VALUES (?, ?) "
                "ON CONFLICT(name) DO UPDATE SET content = excluded.content, "
                "updated_at = CURRENT_TIMESTAMP",
                (name.lower(), content),
            )
            conn.commit()

    def get_personal_note(self, name: str) -> Optional[str]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT content FROM personal_notes WHERE name = ?", (name.lower(),)
            ).fetchone()
            return row["content"] if row else None

    def list_personal_notes(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT name, content, updated_at FROM personal_notes "
                "ORDER BY updated_at DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_personal_note(self, name: str) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute(
                "DELETE FROM personal_notes WHERE name = ?", (name.lower(),)
            )
            conn.commit()
            return cur.rowcount > 0

    # ----------------------------------------------------------------- Reminders
    def add_reminder(self, chat_id: int, user_id: int, text: str, due_at: datetime) -> int:
        stamp = due_at.strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO reminders (chat_id, user_id, text, due_at) VALUES (?, ?, ?, ?)",
                (chat_id, user_id, text, stamp),
            )
            conn.commit()
            return int(cur.lastrowid)

    def due_reminders(self, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        stamp = (now or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? "
                "ORDER BY due_at ASC",
                (stamp,),
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_reminder_fired(self, reminder_id: int) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute(
                "UPDATE reminders SET status = 'fired', fired_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND status = 'pending'",
                (reminder_id,),
            )
            conn.commit()
            return cur.rowcount > 0

    def cancel_reminder(self, reminder_id: int, user_id: Optional[int] = None) -> bool:
        sql = "UPDATE reminders SET status = 'cancelled' WHERE id = ? AND status = 'pending'"
        params: List[Any] = [reminder_id]
        if user_id is not None:
            sql += " AND user_id = ?"
            params.append(user_id)
        with self.get_connection() as conn:
            cur = conn.execute(sql, params)
            conn.commit()
            return cur.rowcount > 0

    def list_reminders(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM reminders"
        params: List[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY due_at ASC LIMIT ?"
        params.append(max(1, min(int(limit), 200)))
        with self.get_connection() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    # ---------------------------------------------------------------- Automation
    def create_automation(
        self,
        name: str,
        trigger_type: str,
        trigger_config: str,
        conditions: str,
        actions: str,
        cooldown_seconds: int = 60,
        created_by: int = 0,
        enabled: bool = False,
    ) -> int:
        with self.get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO automations (name, enabled, trigger_type, trigger_config, "
                "conditions, actions, cooldown_seconds, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    name,
                    1 if enabled else 0,
                    trigger_type,
                    trigger_config,
                    conditions,
                    actions,
                    int(cooldown_seconds),
                    created_by,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def get_automation(self, name: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM automations WHERE name = ?", (name.lower(),)
            ).fetchone()
            return dict(row) if row else None

    def list_automations(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM automations ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def set_automation_enabled(self, name: str, enabled: bool) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute(
                "UPDATE automations SET enabled = ? WHERE name = ?",
                (1 if enabled else 0, name.lower()),
            )
            conn.commit()
            return cur.rowcount > 0

    def delete_automation(self, name: str) -> bool:
        with self.get_connection() as conn:
            cur = conn.execute("DELETE FROM automations WHERE name = ?", (name.lower(),))
            conn.commit()
            return cur.rowcount > 0

    def record_automation_run(self, name: str, error: str = "") -> None:
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE automations SET last_run = CURRENT_TIMESTAMP, "
                "run_count = run_count + 1, last_error = ? WHERE name = ?",
                (error[:500], name.lower()),
            )
            conn.commit()

    # ----------------------------------------------------------------- Plugins
    def set_plugin_enabled(self, name: str, enabled: bool, metadata: str = "") -> None:
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO plugins (name, enabled, metadata) VALUES (?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET enabled = excluded.enabled, "
                "metadata = excluded.metadata",
                (name.lower(), 1 if enabled else 0, metadata or "{}"),
            )
            conn.commit()

    def get_plugin_enabled(self, name: str) -> Optional[bool]:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT enabled FROM plugins WHERE name = ?", (name.lower(),)
            ).fetchone()
            return bool(row["enabled"]) if row else None

    def all_plugin_rows(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM plugins ORDER BY name").fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ Task log
    def log_task(
        self,
        task_id: str,
        kind: str,
        command: str,
        status: str,
        duration_seconds: float = 0.0,
        error: str = "",
    ) -> None:
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO task_log (task_id, kind, command, status, finished_at, "
                "duration_seconds, error) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP, ?, ?)",
                (task_id, kind, command, status, float(duration_seconds), error[:500]),
            )
            # Bounded retention: keep the newest 200 rows.
            conn.execute(
                "DELETE FROM task_log WHERE id NOT IN "
                "(SELECT id FROM task_log ORDER BY id DESC LIMIT 200)"
            )
            conn.commit()

    def recent_tasks(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM task_log ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        with self.get_connection() as conn:
            groups_count = conn.execute("SELECT COUNT(*) FROM group_settings").fetchone()[0]
            warnings_count = conn.execute("SELECT COUNT(*) FROM warnings").fetchone()[0]
            filters_count = conn.execute("SELECT COUNT(*) FROM filters").fetchone()[0]
            notes_count = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            logs_count = conn.execute("SELECT COUNT(*) FROM admin_logs").fetchone()[0]
            archive_count = conn.execute("SELECT COUNT(*) FROM archive").fetchone()[0]
            pending_reminders = conn.execute(
                "SELECT COUNT(*) FROM reminders WHERE status = 'pending'"
            ).fetchone()[0]
            automations_count = conn.execute("SELECT COUNT(*) FROM automations").fetchone()[0]
            return {
                "groups": groups_count,
                "warnings": warnings_count,
                "filters": filters_count,
                "notes": notes_count,
                "admin_logs": logs_count,
                "archive": archive_count,
                "reminders": pending_reminders,
                "automations": automations_count,
            }

# The path comes from REZE_DATABASE_URL (or REZE_DATA_DIR on PaaS volumes).
db = Database(settings.database_url)
