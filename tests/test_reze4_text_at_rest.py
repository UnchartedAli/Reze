"""REZE 4.0: message text is encrypted at rest when REZE_VAULT_KEY is set.

The tests read the raw SQLite rows, so they check what is really on disk, not just
what the code returns.
"""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.config import settings
from reze.modules.msglog import MessageLogger
from reze.storage import text_at_rest as tar
from test_reze4_guard_bot_split import FakeClient, FakeEntity, FakeEvent, FakeMessage

HUMAN = 8001
SECRET = "the launch code is marigold-9931"
KEY_A = "vault-key-alpha-for-tests-0123456789"
KEY_B = "vault-key-bravo-for-tests-9876543210"


class TextAtRestTests(unittest.TestCase):
    def setUp(self):
        self._vault = settings.vault_key
        self._secret = settings.secret_key
        settings.vault_key = KEY_A
        self.dir = tempfile.mkdtemp(prefix="reze-at-rest-")
        self.db_path = os.path.join(self.dir, "guard.db")
        self.settings = {}
        self.client = FakeClient()
        self.guard = MessageLogger(
            connect=self._connect,
            get_setting=lambda key, default=None: self.settings.get(key, default),
            set_setting=lambda key, value: self.settings.__setitem__(key, value),
            cache_dir=os.path.join(self.dir, "cache"),
            clock=lambda: 1_800_000_000.0,
        )
        self.guard.client_provider = lambda: self.client
        self.guard.update(enabled=True, private=True, archive=True)

    def tearDown(self):
        settings.vault_key = self._vault
        settings.secret_key = self._secret
        shutil.rmtree(self.dir, ignore_errors=True)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def raw(self, table):
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]

    def run_(self, coro):
        return asyncio.run(coro)

    def person_says(self, msg_id, text):
        event = FakeEvent(chat_id=HUMAN, message=FakeMessage(msg_id, text), private=True,
                          chat=FakeEntity(HUMAN), sender=FakeEntity(HUMAN))
        self.run_(self.guard.on_new_message(event))

    def person_deletes(self, msg_id):
        event = FakeEvent(chat_id=None, message=None, private=True, client=self.client, deleted_ids=[msg_id])
        self.run_(self.guard.on_deleted(event))

    # ------------------------------------------------------------ on disk
    def test_cached_and_archived_text_is_not_readable_in_the_database(self):
        self.person_says(1, SECRET)
        cached = self.raw("msglog")[0]["text"]
        self.assertTrue(cached.startswith(tar.PREFIX))
        self.assertNotIn("marigold", cached)
        self.person_deletes(1)
        archived = self.raw("msglog_archive")[0]["text"]
        self.assertTrue(archived.startswith(tar.PREFIX))
        self.assertNotIn("marigold", archived)

    def test_without_a_vault_key_text_is_stored_as_before(self):
        settings.vault_key = ""
        settings.secret_key = "default-secret-only-for-tests"  # secret key alone never turns this on
        self.person_says(1, SECRET)
        self.person_deletes(1)
        self.assertIn("marigold", self.raw("msglog_archive")[0]["text"])

    # -------------------------------------------------------------- reads
    def test_the_archive_search_finds_text_by_its_content(self):
        self.person_says(1, SECRET)
        self.person_deletes(1)
        found = self.guard.search_archive("marigold")
        self.assertEqual(len(found), 1)
        self.assertIn("marigold-9931", found[0]["text"])
        self.assertEqual(self.guard.search_archive("nothing like this"), [])

    def test_archive_item_and_export_are_readable_by_the_owner(self):
        self.person_says(1, SECRET)
        self.person_deletes(1)
        item_id = self.raw("msglog_archive")[0]["id"]
        self.assertIn("marigold", self.guard.get_archived(item_id)["text"])
        out = os.path.join(self.dir, "export")
        path = self.guard.export_archive(out, "json")
        with open(path, encoding="utf-8") as handle:
            self.assertIn("marigold", json.dumps(json.load(handle), ensure_ascii=False))

    def test_an_edit_is_stored_sealed_and_the_report_shows_the_original(self):
        self.person_says(1, "first wording")
        edit = FakeEvent(chat_id=HUMAN, message=FakeMessage(1, "second wording"), private=True, client=self.client)
        self.run_(self.guard.on_edited(edit))
        stored = self.raw("msglog")[0]["text"]
        self.assertTrue(stored.startswith(tar.PREFIX))
        self.assertNotIn("second", stored)
        self.assertTrue(any("first wording" in text for _, text in self.client.sent))

    def test_text_from_before_the_key_was_added_is_still_readable(self):
        settings.vault_key = ""
        self.person_says(1, SECRET)
        self.person_deletes(1)
        settings.vault_key = KEY_A
        found = self.guard.search_archive("marigold")
        self.assertEqual(len(found), 1, "old plain-text rows stay readable")

    # --------------------------------------------------------- wrong key
    def test_with_a_different_key_the_text_shows_a_placeholder_and_nothing_crashes(self):
        self.person_says(1, SECRET)
        self.person_deletes(1)
        settings.vault_key = KEY_B
        item_id = self.raw("msglog_archive")[0]["id"]
        self.assertEqual(self.guard.get_archived(item_id)["text"], tar.PLACEHOLDER)
        self.assertEqual(self.guard.search_archive("marigold"), [])

    def test_sealed_values_round_trip_and_plain_values_pass_through(self):
        sealed = tar.seal("round trip ✓")
        self.assertNotEqual(sealed, "round trip ✓")
        self.assertEqual(tar.open_text(sealed), "round trip ✓")
        self.assertEqual(tar.open_text("plain"), "plain")
        self.assertEqual(tar.open_text(None), "")


class NewStoresAtRestTests(unittest.TestCase):
    """The Style and Digest stores keep the same protection as the message guard."""

    def setUp(self):
        self._vault = settings.vault_key
        settings.vault_key = KEY_A

    def tearDown(self):
        settings.vault_key = self._vault
        from reze.database import db
        db.execute("DELETE FROM style_samples")
        db.execute("DELETE FROM style_drafts")
        db.execute("DELETE FROM digest_runs")

    def test_style_samples_are_sealed_on_disk_and_read_back_in_plain_text(self):
        from datetime import datetime
        from reze.database import db
        from reze.style import store as style_store
        style_store.add_samples(5551, [(1, "my private phrase kumquat")], datetime(2026, 11, 13))
        raw = db.query("SELECT text FROM style_samples")[0]["text"]
        self.assertTrue(raw.startswith(tar.PREFIX))
        self.assertNotIn("kumquat", raw)
        self.assertIn("kumquat", style_store.sample_texts()[0])

    def test_style_drafts_are_sealed_on_disk(self):
        from datetime import datetime
        from reze.database import db
        from reze.style import store as style_store
        draft_id = style_store.create_draft(5551, 7, "draft words pomelo", datetime(2026, 11, 13))
        raw = db.query_one("SELECT draft FROM style_drafts WHERE id = ?", (draft_id,))["draft"]
        self.assertNotIn("pomelo", raw)
        self.assertEqual(style_store.get_draft(draft_id)["draft"], "draft words pomelo")

    def test_undelivered_digest_bodies_are_sealed_and_deliver_correctly(self):
        from datetime import datetime
        from reze.database import db
        from reze.digest import store as digest_store
        now = datetime(2026, 11, 13, 21, 0)
        run = digest_store.create_run("k-sealed", "scheduled", now)
        digest_store.commit_collection(
            run, body="digest body with papaya", chunk_total=1, mode="basic", period_start=None,
            period_end=None, channel_count=1, message_count=1, important_count=0, checkpoints={}, now=now,
        )
        raw = db.query_one("SELECT body FROM digest_runs WHERE id = ?", (run,))["body"]
        self.assertNotIn("papaya", raw)
        self.assertEqual(digest_store.get_run(run)["body"], "digest body with papaya")

    def test_a_sealed_value_survives_a_failed_reseal_with_the_wrong_key(self):
        sealed = tar.seal("keep me safe")
        settings.vault_key = KEY_B
        self.assertEqual(tar.reseal(sealed), sealed)
        settings.vault_key = KEY_A
        self.assertEqual(tar.open_text(sealed), "keep me safe")


if __name__ == "__main__":
    unittest.main()
