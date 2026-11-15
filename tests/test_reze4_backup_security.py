"""REZE 4.0: encrypted backups, schema guard and exact backup identifiers."""

import os
import shutil
import sqlite3
import tempfile
import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.config import settings
from reze.database import db
from reze.migrations import MIGRATIONS
from reze.storage import encryption
from reze.storage.backups.service import ENCRYPTED_MAGIC, BackupError, BackupService, supported_schema_version

MARKER = "marker-value-7f3a9c"


class _IsolatedBackupService(BackupService):
    """Backs up a private database so the shared test database is untouched."""

    def __init__(self, live_path, directory):
        super().__init__()
        self._live = live_path
        self.directory = directory

    def _live_path(self):
        return self._live


class BackupSecurityTests(unittest.TestCase):
    KEY_A = "backup-test-key-alpha-0123456789"
    KEY_B = "backup-test-key-bravo-9876543210"

    def setUp(self):
        self._original_vault_key = settings.vault_key
        self._original_secret_key = settings.secret_key
        settings.vault_key = self.KEY_A
        self.tmp = tempfile.mkdtemp(prefix="reze-backup-sec-")
        self.live = os.path.join(self.tmp, "live.db")
        self.directory = os.path.join(self.tmp, "backups")
        self.service = _IsolatedBackupService(self.live, self.directory)
        connection = sqlite3.connect(self.live)
        try:
            connection.execute("CREATE TABLE marker (value TEXT)")
            connection.execute("INSERT INTO marker VALUES (?)", (MARKER,))
            connection.commit()
        finally:
            connection.close()

    def tearDown(self):
        settings.vault_key = self._original_vault_key
        settings.secret_key = self._original_secret_key
        shutil.rmtree(self.tmp, ignore_errors=True)
        db.execute("DELETE FROM backups WHERE path LIKE ?", (f"%{self.tmp}%",))
        for key in ("backup.restore_code", "backup.restore_path", "backup.restore_expires"):
            db.delete_setting(key)

    def _set_marker(self, value):
        connection = sqlite3.connect(self.live)
        try:
            connection.execute("UPDATE marker SET value = ?", (value,))
            connection.commit()
        finally:
            connection.close()

    def _marker(self):
        connection = sqlite3.connect(self.live)
        try:
            return connection.execute("SELECT value FROM marker").fetchone()[0]
        finally:
            connection.close()

    def _restore(self, identifier):
        prepared = self.service.prepare_restore(identifier)
        return self.service.restore(prepared["code"])

    # ---------------------------------------------------------- encryption
    def test_backup_is_encrypted_and_contains_no_plaintext(self):
        created = self.service.create(kind="test")
        self.assertTrue(created["encrypted"])
        self.assertTrue(created["path"].endswith(".db.enc"))
        with open(created["path"], "rb") as handle:
            raw = handle.read()
        self.assertTrue(raw.startswith(ENCRYPTED_MAGIC))
        self.assertNotIn(b"SQLite format 3", raw)
        self.assertNotIn(MARKER.encode(), raw)
        self.assertNotIn(self.KEY_A.encode(), raw)

    def test_encrypted_backup_verifies_and_restores(self):
        created = self.service.create(kind="test")
        report = self.service.verify(created["path"])
        self.assertTrue(report["ok"])
        self.assertTrue(report["encrypted"])
        self._set_marker("changed")
        result = self._restore(os.path.basename(created["path"]))
        self.assertEqual(self._marker(), MARKER)
        self.assertTrue(result["encrypted"])

    def test_wrong_key_cannot_verify_or_restore(self):
        created = self.service.create(kind="test")
        settings.vault_key = self.KEY_B
        with self.assertRaises(BackupError):
            self.service.verify(created["path"])
        with self.assertRaises(BackupError):
            self.service.prepare_restore(os.path.basename(created["path"]))

    def test_tampered_ciphertext_is_rejected(self):
        created = self.service.create(kind="test")
        with open(created["path"], "rb") as handle:
            blob = bytearray(handle.read())
        blob[-1] ^= 0x01
        with open(created["path"], "wb") as handle:
            handle.write(bytes(blob))
        with self.assertRaises(BackupError):
            self.service.verify(created["path"])

    def test_encrypted_backup_without_key_explains_the_problem(self):
        created = self.service.create(kind="test")
        settings.vault_key = ""
        settings.secret_key = encryption.DEFAULT_SECRET
        with self.assertRaises(BackupError) as ctx:
            self.service.verify(created["path"])
        self.assertIn("REZE_VAULT_KEY", str(ctx.exception))

    def test_plaintext_backup_still_works_without_a_key(self):
        settings.vault_key = ""
        settings.secret_key = encryption.DEFAULT_SECRET
        created = self.service.create(kind="test")
        self.assertFalse(created["encrypted"])
        self.assertTrue(created["path"].endswith(".db"))
        report = self.service.verify(created["path"])
        self.assertTrue(report["ok"])
        self.assertFalse(report["encrypted"])
        self._set_marker("changed")
        self._restore(os.path.basename(created["path"]))
        self.assertEqual(self._marker(), MARKER)

    def test_no_plaintext_scratch_files_are_left_behind(self):
        self.service.create(kind="test")
        leftovers = [name for name in os.listdir(self.directory) if name.startswith((".snapshot-", "reze-plain-"))]
        self.assertEqual(leftovers, [])

    # ------------------------------------------------------- schema guard
    def test_restore_refuses_a_backup_from_a_newer_schema(self):
        connection = sqlite3.connect(self.live)
        try:
            connection.execute(f"PRAGMA user_version = {supported_schema_version() + 1}")
            connection.commit()
        finally:
            connection.close()
        created = self.service.create(kind="future")
        with self.assertRaises(BackupError) as ctx:
            self.service.prepare_restore(os.path.basename(created["path"]))
        self.assertIn("Upgrade REZE", str(ctx.exception))

    def test_supported_schema_matches_registered_migrations(self):
        self.assertEqual(supported_schema_version(), max(m.version for m in MIGRATIONS))

    # ---------------------------------------------------- exact identifiers
    def test_partial_identifiers_do_not_select_a_backup(self):
        created = self.service.create(kind="test")
        name = os.path.basename(created["path"])
        self.assertIsNotNone(self.service.resolve(name))
        self.assertIsNotNone(self.service.resolve(created["path"]))
        self.assertIsNone(self.service.resolve(name[:12]))
        self.assertIsNone(self.service.resolve("reze-"))

    def test_resolve_by_numeric_id(self):
        created = self.service.create(kind="test")
        row = db.query_one("SELECT id FROM backups WHERE path = ?", (created["path"],))
        self.assertEqual(self.service.resolve(str(row["id"]))["path"], created["path"])


if __name__ == "__main__":
    unittest.main()
