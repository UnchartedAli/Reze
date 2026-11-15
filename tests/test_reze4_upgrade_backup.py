"""REZE 4.0: a verified copy is saved before any upgrade that would change the database."""

import glob
import os
import shutil
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from unittest import mock

import support  # noqa: F401  - prepares the shared database before reze imports

from reze.core import upgrade_backup as ub
from reze.database import Database
from reze.migrations import MIGRATIONS

VERSIONS = [m.version for m in MIGRATIONS]
NEW_TABLES = (
    "digest_config", "digest_channels", "digest_runs",
    "style_samples", "style_profile", "style_settings", "style_auto_chats", "style_auto_log", "style_drafts",
)


class UpgradeBackupTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="reze-upgrade-backup-")
        self.path = os.path.join(self.dir, "reze.db")
        self._skip = os.environ.pop(ub.SKIP_ENV, None)

    def tearDown(self):
        if self._skip is not None:
            os.environ[ub.SKIP_ENV] = self._skip
        shutil.rmtree(self.dir, ignore_errors=True)

    def backups(self):
        return sorted(glob.glob(os.path.join(self.dir, "backups", ub.PREFIX + "*.db")))

    def make_3_0_database(self):
        old = Database(self.path)
        old.set_setting("keep.me", "yes")
        old.add_reminder(-1001, 4242, "still here", datetime(2026, 11, 14, 9, 0))
        with old.get_connection() as conn:
            for table in NEW_TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute("DELETE FROM schema_migrations WHERE version >= 5")
            conn.execute("PRAGMA user_version = 4")
            conn.commit()

    def test_upgrade_saves_a_verified_copy_of_the_old_version(self):
        self.make_3_0_database()
        Database(self.path)
        found = self.backups()
        self.assertEqual(len(found), 1)
        conn = sqlite3.connect(found[0])
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0], 1)
            self.assertFalse(set(NEW_TABLES) & {r[0] for r in conn.execute("SELECT name FROM sqlite_master")})
        finally:
            conn.close()

    def test_a_new_database_gets_no_copy(self):
        Database(self.path)
        self.assertEqual(self.backups(), [])

    def test_reopening_a_current_database_gets_no_copy(self):
        Database(self.path)
        Database(self.path)
        self.assertEqual(self.backups(), [])

    def test_if_the_copy_cannot_be_made_the_upgrade_does_not_happen(self):
        self.make_3_0_database()
        with mock.patch.object(ub, "backup_before_upgrade", side_effect=ub.UpgradeBackupError("no space")):
            with self.assertRaises(ub.UpgradeBackupError):
                Database(self.path)
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4, "the database was not changed")
            self.assertFalse(set(NEW_TABLES) & {r[0] for r in conn.execute("SELECT name FROM sqlite_master")})
        finally:
            conn.close()

    def test_an_unwritable_copy_location_stops_the_upgrade_with_a_clear_message(self):
        self.make_3_0_database()
        blocker = os.path.join(self.dir, "backups")
        with open(blocker, "w") as handle:  # a file where the directory should be
            handle.write("x")
        with self.assertRaisesRegex(ub.UpgradeBackupError, "SKIP|upgrading"):
            Database(self.path)

    def test_the_escape_hatch_upgrades_without_a_copy(self):
        self.make_3_0_database()
        os.environ[ub.SKIP_ENV] = "1"
        try:
            Database(self.path)
        finally:
            os.environ.pop(ub.SKIP_ENV, None)
        self.assertEqual(self.backups(), [])
        conn = sqlite3.connect(self.path)
        try:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 6)
        finally:
            conn.close()

    def test_only_the_newest_copies_are_kept(self):
        directory = os.path.join(self.dir, "backups")
        os.makedirs(directory)
        for index in range(8):
            path = os.path.join(directory, f"{ub.PREFIX}v5-{index:02d}.db")
            with open(path, "w") as handle:
                handle.write("x")
            stamp = time.time() - (8 - index) * 60
            os.utime(path, (stamp, stamp))
        removed = ub.prune(directory, keep=5)
        self.assertEqual(removed, 3)
        remaining = sorted(os.path.basename(p) for p in glob.glob(os.path.join(directory, ub.PREFIX + "*.db")))
        self.assertEqual(remaining, [f"{ub.PREFIX}v5-{i:02d}.db" for i in range(3, 8)])


if __name__ == "__main__":
    unittest.main()
