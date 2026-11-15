"""REZE 4.0: upgrades keep data, and new features stay OFF.

These tests build real databases with the project's own Database class, then move
them back to an older state, then open them with the current code.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime

import support  # noqa: F401  - prepares the shared database before reze imports

from reze.core.migrations import current_version, run_migrations, Migration
from reze.database import Database

NEW_TABLES = (
    "digest_config", "digest_channels", "digest_runs",
    "style_samples", "style_profile", "style_settings", "style_auto_chats", "style_auto_log", "style_drafts",
)


def _counts(path):
    conn = sqlite3.connect(path)
    try:
        return {
            "reminders": conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0],
            "settings": conn.execute("SELECT COUNT(*) FROM global_settings").fetchone()[0],
        }
    finally:
        conn.close()


def _tables(path):
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


class UpgradeTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="reze-upgrade-")
        self.path = os.path.join(self.dir, "reze.db")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _make_3_0_database(self):
        """A database as REZE 3.0 left it: versions 1-4 applied, no digest or style tables."""
        old = Database(self.path)
        old.set_setting("upgrade.note", "keep me")
        old.add_reminder(-1001, 4242, "drink water", datetime(2026, 11, 14, 9, 0))
        old.add_reminder(-1002, 4242, "call the landlord", datetime(2026, 11, 15, 10, 0))
        with old.get_connection() as conn:
            for table in NEW_TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute("DELETE FROM schema_migrations WHERE version >= 5")
            conn.execute("PRAGMA user_version = 4")
            conn.commit()

    def test_3_0_database_upgrades_with_data_intact_and_new_features_off(self):
        self._make_3_0_database()
        before = _counts(self.path)
        self.assertEqual(before["reminders"], 2)
        self.assertFalse(set(NEW_TABLES) & _tables(self.path))

        Database(self.path)  # the upgrade: current code opens the old file

        self.assertEqual(_counts(self.path), before, "no rows were lost or duplicated")
        self.assertTrue(set(NEW_TABLES) <= _tables(self.path))
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(conn.execute("SELECT value FROM global_settings WHERE key = 'upgrade.note'").fetchone()[0], "keep me")
            self.assertEqual(conn.execute("SELECT enabled FROM digest_config WHERE id = 1").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT auto_enabled FROM style_settings WHERE id = 1").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM digest_runs").fetchone()[0], 0)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            applied = [row[0] for row in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]
            self.assertIn(5, applied)
            self.assertIn(6, applied)
        finally:
            conn.close()

    def test_reopening_an_upgraded_database_changes_nothing(self):
        self._make_3_0_database()
        Database(self.path)
        conn = sqlite3.connect(self.path)
        versions = conn.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version").fetchall()
        conn.close()
        Database(self.path)
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version").fetchall(), versions)
        finally:
            conn.close()

    def test_very_old_database_without_version_history_upgrades(self):
        """A REZE 2 database has tables but no version record. It must upgrade without losing data."""
        Database(self.path)
        with Database(self.path).get_connection() as conn:
            conn.execute("DROP TABLE IF EXISTS schema_migrations")
            for table in NEW_TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute("PRAGMA user_version = 0")
            conn.commit()
        Database(self.path)
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertTrue(set(NEW_TABLES) <= _tables(self.path))
        finally:
            conn.close()


class MigrationSafetyTests(unittest.TestCase):
    def test_a_failing_migration_rolls_back_and_keeps_the_previous_version(self):
        conn = sqlite3.connect(":memory:")

        def good(c):
            c.execute("CREATE TABLE step_one (id INTEGER)")

        def broken(c):
            c.execute("CREATE TABLE step_two (id INTEGER)")
            raise RuntimeError("disk full")

        migrations = [
            Migration(version=3, name="ok", apply=good),
            Migration(version=4, name="broken", apply=broken),
        ]
        with self.assertRaises(RuntimeError):
            run_migrations(conn, migrations, baseline=2)
        self.assertEqual(current_version(conn), 3, "the database stays at the last good version")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertIn("step_one", tables)
        self.assertNotIn("step_two", tables, "the failed step leaves nothing behind")
        conn.close()


if __name__ == "__main__":
    unittest.main()
