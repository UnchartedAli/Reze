"""Digital Vault encryption and safe backup/restore behaviour."""

import os
import sqlite3
import tempfile
import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.config import settings
from reze.database import db
from reze.storage import encryption
from reze.storage.backups.service import BackupError, BackupService
from reze.storage.encryption import VaultDecryptError
from reze.storage.vault.service import vault_service


class VaultTests(unittest.TestCase):
    KEY_A = "test-vault-key-alpha-0123456789"
    KEY_B = "test-vault-key-bravo-9876543210"

    def setUp(self):
        self._original_key = settings.vault_key
        settings.vault_key = self.KEY_A
        db.execute("DELETE FROM vault_entries")
        db.execute("DELETE FROM search_index WHERE kind = 'vault'")

    def tearDown(self):
        db.execute("DELETE FROM vault_entries")
        db.execute("DELETE FROM search_index WHERE kind = 'vault'")
        settings.vault_key = self._original_key

    def test_secret_round_trip(self):
        self.assertTrue(vault_service.configured)
        vault_service.set_secret("wifi", "correct horse battery staple")
        self.assertEqual(vault_service.get_secret("wifi"), "correct horse battery staple")
        meta = vault_service.get_meta("wifi")
        self.assertEqual(meta["kind"], "secret")
        # The plaintext must never appear in the stored row.
        row = db.query_one("SELECT * FROM vault_entries WHERE id = ?", (meta["id"],))
        self.assertNotIn(b"correct horse", bytes(row["ciphertext"]))
        self.assertNotEqual(row["nonce"], row["ciphertext"])

    def test_overwrite_and_case_insensitive_lookup(self):
        vault_service.set_secret("Token", "one")
        vault_service.set_secret("token", "two")
        count = db.query_one("SELECT COUNT(*) AS total FROM vault_entries")["total"]
        self.assertEqual(count, 1)
        self.assertEqual(vault_service.get_secret("TOKEN"), "two")

    def test_file_round_trip_and_limits(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as handle:
            handle.write(b"vault file payload")
            path = handle.name
        try:
            vault_service.put_file("payload", path, mime="text/plain")
            self.assertEqual(vault_service.get_file_bytes("payload"), b"vault file payload")
            self.assertEqual(vault_service.get_meta("payload")["filename"], os.path.basename(path))
        finally:
            os.remove(path)

    def test_wrong_key_cannot_decrypt(self):
        vault_service.set_secret("secret", "unreadable")
        settings.vault_key = self.KEY_B
        with self.assertRaises(VaultDecryptError):
            vault_service.get_secret("secret")
        settings.vault_key = self.KEY_A
        self.assertEqual(vault_service.get_secret("secret"), "unreadable")

    def test_unconfigured_vault_refuses_to_encrypt(self):
        original_secret = settings.secret_key
        settings.vault_key = ""
        settings.secret_key = encryption.DEFAULT_SECRET
        try:
            self.assertFalse(encryption.is_configured())
            with self.assertRaises(encryption.VaultLocked):
                vault_service.set_secret("nope", "value")
        finally:
            settings.secret_key = original_secret

    def test_fingerprint_never_reveals_the_key(self):
        fingerprint = encryption.fingerprint()
        self.assertEqual(len(fingerprint), 8)
        self.assertNotIn(self.KEY_A, fingerprint)

    def test_long_secret_is_rejected(self):
        with self.assertRaises(ValueError):
            vault_service.set_secret("huge", "x" * (64 * 1024 + 1))


class _TempBackupService(BackupService):
    """Backs up an isolated database instead of the shared test database."""

    def __init__(self, live_path, directory):
        super().__init__()
        self._live = live_path
        self.directory = directory

    def _live_path(self):
        return self._live


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="reze-backups-")
        self.live = os.path.join(self.tmp, "live.db")
        self.backups = os.path.join(self.tmp, "backups")
        self.service = _TempBackupService(self.live, self.backups)
        connection = sqlite3.connect(self.live)
        try:
            connection.execute("CREATE TABLE marker (value TEXT)")
            connection.execute("INSERT INTO marker VALUES ('original')")
            connection.commit()
        finally:
            connection.close()

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)
        db.execute("DELETE FROM backups WHERE path LIKE ?", (f"%{self.tmp}%",))
        for key in ("backup.restore_code", "backup.restore_path", "backup.restore_expires"):
            db.delete_setting(key)

    def _marker(self):
        connection = sqlite3.connect(self.live)
        try:
            return connection.execute("SELECT value FROM marker").fetchone()[0]
        finally:
            connection.close()

    def _set_marker(self, value):
        connection = sqlite3.connect(self.live)
        try:
            connection.execute("UPDATE marker SET value = ?", (value,))
            connection.commit()
        finally:
            connection.close()

    def test_backup_is_verified_and_restorable(self):
        created = self.service.create(kind="test")
        self.assertTrue(os.path.isfile(created["path"]))
        report = self.service.verify(created["path"])
        self.assertTrue(report["ok"])
        self.assertEqual(report["integrity"], "ok")

        self._set_marker("changed")
        prepared = self.service.prepare_restore(os.path.basename(created["path"]))
        self.assertRegex(prepared["code"], r"^\d{6}$")

        with self.assertRaises(BackupError):
            self.service.restore("000000" if prepared["code"] != "000000" else "111111")

        result = self.service.restore(prepared["code"])
        self.assertEqual(self._marker(), "original")
        self.assertTrue(os.path.isfile(result["safety"]))
        self.assertEqual(db.get_setting("backup.restore_code", ""), "")

    def test_verify_rejects_missing_and_corrupt_files(self):
        with self.assertRaises(BackupError):
            self.service.verify(os.path.join(self.tmp, "missing.db"))
        corrupt = os.path.join(self.tmp, "corrupt.db")
        with open(corrupt, "wb") as handle:
            handle.write(b"this is not sqlite")
        with self.assertRaises(BackupError):
            self.service.verify(corrupt)

    def test_restore_requires_preparation(self):
        with self.assertRaises(BackupError):
            self.service.restore("123456")

    def test_prune_keeps_newest(self):
        for _ in range(3):
            self.service.create(kind="test")
        rows = self.service.list(limit=10)
        self.assertGreaterEqual(len(rows), 3)
        removed = self.service.prune(keep=1)
        self.assertGreaterEqual(removed, 2)
        self.assertEqual(len(self.service.list(limit=10)), 1)


if __name__ == "__main__":
    unittest.main()
