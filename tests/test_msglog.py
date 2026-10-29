"""Message Guard: capture, deletion/edit reports, scoping, retention."""

import asyncio
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime

from reze.modules.msglog import MessageLogger


def run(coro):
    return asyncio.run(coro)


class FakeFile:
    def __init__(self, size=1000):
        self.size = size


class FakeMedia:
    def __init__(self, ttl_seconds=None):
        self.ttl_seconds = ttl_seconds


class FakeMessage:
    def __init__(self, msg_id, text="", out=False, photo=False, size=1000, action=None, ttl=None):
        self.id = msg_id
        self.raw_text = text
        self.message = text
        self.out = out
        self.action = action
        self.photo = photo or None
        self.media = FakeMedia(ttl) if photo else None
        self.file = FakeFile(size) if photo else None
        self.date = datetime(2026, 10, 29, 12, 0, 0)

    async def download_media(self, file=None):
        path = f"{file}.jpg"
        with open(path, "wb") as handle:
            handle.write(b"fake-image")
        return path


class FakeEntity:
    def __init__(self, first_name=None, title=None, username=None, ident=1):
        self.first_name, self.title, self.username, self.id = first_name, title, username, ident
        self.last_name = None


class FakeClient:
    def __init__(self):
        self.messages, self.files = [], []

    async def send_message(self, entity, text, **kwargs):
        self.messages.append((entity, text, kwargs))

    async def send_file(self, entity, file, **kwargs):
        self.files.append((entity, file, kwargs))


class FakeEvent:
    def __init__(self, message, chat_id=-100500, private=False, group=True, channel=False,
                 sender_id=77, client=None):
        self.message = message
        self.chat_id = chat_id
        self.is_private, self.is_group, self.is_channel = private, group, channel
        self.sender_id = sender_id
        self.client = client

    async def get_sender(self):
        return FakeEntity(first_name="Sara", username="sara", ident=self.sender_id)

    async def get_chat(self):
        return FakeEntity(title="Team Chat", ident=self.chat_id)


class FakeDeleted:
    def __init__(self, ids, chat_id=None, client=None):
        self.deleted_ids, self.chat_id, self.client = ids, chat_id, client


class GuardCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="reze-guard-")
        self.db_path = os.path.join(self.dir, "guard.db")
        self.settings = {}
        self.now = [1_800_000_000.0]
        self.guard = self._make()
        self.client = FakeClient()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _make(self):
        return MessageLogger(
            connect=self._connect,
            get_setting=lambda key, default=None: self.settings.get(key, default),
            set_setting=lambda key, value: self.settings.__setitem__(key, value),
            cache_dir=os.path.join(self.dir, "cache"),
            clock=lambda: self.now[0],
        )

    def capture(self, message, **kwargs):
        kwargs.setdefault("client", self.client)
        run(self.guard.on_new_message(FakeEvent(message, **kwargs)))


class ConfigTests(GuardCase):
    def test_defaults_and_persistence(self):
        self.assertFalse(self.guard.config["enabled"])
        self.guard.update(enabled=True, dest="12345", retention_hours=6)
        self.assertTrue(self.guard.add_chat(-100500))
        self.assertFalse(self.guard.add_chat(-100500))
        reloaded = self._make()
        self.assertTrue(reloaded.config["enabled"])
        self.assertEqual(reloaded.config["chats"], [-100500])
        self.assertEqual(reloaded.destination(), 12345)
        self.assertTrue(reloaded.remove_chat(-100500))
        self.assertFalse(reloaded.remove_chat(-100500))

    def test_unknown_key_is_rejected_and_corrupt_json_is_ignored(self):
        with self.assertRaises(KeyError):
            self.guard.update(bogus=1)
        self.settings["msglog:config"] = "{not json"
        self.assertFalse(self._make().config["enabled"])

    def test_watch_rules(self):
        g = self.guard
        self.assertFalse(g.is_watched(-1, private=False, group=True))  # disabled
        g.update(enabled=True)
        self.assertFalse(g.is_watched(-1, private=False, group=True))
        g.add_chat(-1)
        self.assertTrue(g.is_watched(-1, private=False, group=True))
        self.assertFalse(g.is_watched(5, private=True, group=False))
        g.update(private=True)
        self.assertTrue(g.is_watched(5, private=True, group=False))
        self.assertFalse(g.is_watched(-9, private=False, group=True))
        g.update(groups=True)
        self.assertTrue(g.is_watched(-9, private=False, group=True))
        self.assertFalse(g.is_watched(None, private=True, group=False))


class CaptureTests(GuardCase):
    def test_disabled_guard_stores_nothing(self):
        self.capture(FakeMessage(1, "hello"))
        self.assertEqual(self.guard.count(), 0)

    def test_unwatched_chat_is_ignored(self):
        self.guard.update(enabled=True)
        self.capture(FakeMessage(1, "hello"))
        self.assertEqual(self.guard.count(), 0)

    def test_own_messages_and_service_messages_are_skipped(self):
        self.guard.update(enabled=True, groups=True)
        self.capture(FakeMessage(1, "mine", out=True))
        self.capture(FakeMessage(2, "joined", action=object()))
        self.capture(FakeMessage(3, ""))  # nothing worth saving
        self.assertEqual(self.guard.count(), 0)
        self.guard.update(own=True)
        self.capture(FakeMessage(4, "mine", out=True))
        self.assertEqual(self.guard.count(), 1)


class DeleteTests(GuardCase):
    def test_deleted_text_is_delivered_to_saved_messages(self):
        self.guard.update(enabled=True)
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(10, "secret plan *bold*"))
        self.assertEqual(self.guard.count(), 1)

        run(self.guard.on_deleted(FakeDeleted([10], chat_id=None, client=self.client)))

        self.assertEqual(len(self.client.messages), 1)
        entity, text, kwargs = self.client.messages[0]
        self.assertEqual(entity, "me")
        self.assertIn("DELETED MESSAGE", text)
        self.assertIn("secret plan *bold*", text)
        self.assertIn("Sara (@sara) [77]", text)
        self.assertIn("Team Chat", text)
        self.assertIsNone(kwargs["parse_mode"])  # user text must never be parsed as markdown
        self.assertEqual(self.guard.count(), 0)  # consumed
        self.assertEqual(self.guard.stats["deleted"], 1)

    def test_unknown_ids_are_silent(self):
        self.guard.update(enabled=True)
        run(self.guard.on_deleted(FakeDeleted([999], client=self.client)))
        self.assertEqual(self.client.messages, [])

    def test_media_is_cached_and_resent(self):
        self.guard.update(enabled=True)
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(11, "look", photo=True))

        run(self.guard.on_deleted(FakeDeleted([11], client=self.client)))

        self.assertEqual(self.client.messages, [])
        self.assertEqual(len(self.client.files), 1)
        entity, path, kwargs = self.client.files[0]
        self.assertEqual(entity, "me")
        self.assertTrue(path.endswith(".jpg"))
        self.assertIn("look", kwargs["caption"])
        self.assertFalse(os.path.exists(path))  # cache file removed after delivery

    def test_media_over_the_size_limit_is_not_downloaded(self):
        self.guard.update(enabled=True, max_media_mb=1)
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(12, "huge", photo=True, size=5 * 1024 * 1024))
        run(self.guard.on_deleted(FakeDeleted([12], client=self.client)))
        self.assertEqual(self.client.files, [])
        self.assertEqual(len(self.client.messages), 1)  # text report still delivered

    def test_media_caching_can_be_turned_off(self):
        self.guard.update(enabled=True, media=False)
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(13, "pic", photo=True))
        run(self.guard.on_deleted(FakeDeleted([13], client=self.client)))
        self.assertEqual(self.client.files, [])
        self.assertIn("Media: photo", self.client.messages[0][1])

    def test_custom_destination(self):
        self.guard.update(enabled=True, dest="-100999")
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(14, "x"))
        run(self.guard.on_deleted(FakeDeleted([14], client=self.client)))
        self.assertEqual(self.client.messages[0][0], -100999)

    def test_channel_scope_does_not_collide_with_private_ids(self):
        self.guard.update(enabled=True, groups=True, private=True)
        self.capture(FakeMessage(5, "in channel A"), chat_id=-1001, channel=True)
        self.capture(FakeMessage(5, "in channel B"), chat_id=-1002, channel=True)
        self.capture(FakeMessage(5, "in a DM"), chat_id=900, private=True, group=False)
        self.assertEqual(self.guard.count(), 3)

        run(self.guard.on_deleted(FakeDeleted([5], chat_id=-1002, client=self.client)))
        run(self.guard.on_deleted(FakeDeleted([5], chat_id=None, client=self.client)))
        texts = " ".join(m[1] for m in self.client.messages)
        self.assertIn("in channel B", texts)
        self.assertIn("in a DM", texts)
        self.assertNotIn("in channel A", texts)
        self.assertEqual(self.guard.count(), 1)

    def test_mass_deletion_is_capped_with_a_summary(self):
        self.guard.update(enabled=True)
        self.guard.add_chat(-100500)
        for i in range(1, 21):
            self.capture(FakeMessage(i, f"m{i}"))
        run(self.guard.on_deleted(FakeDeleted(list(range(1, 21)), client=self.client)))
        self.assertEqual(len(self.client.messages), 16)  # 15 reports + 1 summary
        self.assertIn("5 more", self.client.messages[-1][1])
        self.assertEqual(self.guard.count(), 0)


class NoDownloadMessage(FakeMessage):
    async def download_media(self, file=None):
        return None  # e.g. Telegram refuses to serve view-once media to API clients


class TimedMediaTests(GuardCase):
    def setUp(self):
        super().setUp()
        self.guard.update(enabled=True)
        self.guard.add_chat(-100500)

    def test_timed_photo_is_sent_to_saved_messages_immediately(self):
        self.capture(FakeMessage(50, "secret pic", photo=True, ttl=10))
        self.assertEqual(len(self.client.files), 1)
        entity, path, kwargs = self.client.files[0]
        self.assertEqual(entity, "me")
        self.assertTrue(path.endswith(".jpg"))
        self.assertIn("SELF-DESTRUCTING MEDIA", kwargs["caption"])
        self.assertIn("10s timer", kwargs["caption"])
        self.assertIn("secret pic", kwargs["caption"])
        self.assertIsNone(kwargs["parse_mode"])
        self.assertFalse(os.path.exists(path))  # temp copy removed after sending
        self.assertEqual(self.guard.count(), 0)  # never stored in the database
        self.assertEqual(self.guard.stats["timed"], 1)

    def test_view_once_is_labelled(self):
        self.capture(FakeMessage(51, "", photo=True, ttl=0x7FFFFFFF))
        self.assertIn("view once", self.client.files[0][2]["caption"])

    def test_download_refusal_still_produces_a_notice(self):
        self.capture(NoDownloadMessage(52, "", photo=True, ttl=0x7FFFFFFF))
        self.assertEqual(self.client.files, [])
        self.assertEqual(len(self.client.messages), 1)
        self.assertIn("could not be downloaded", self.client.messages[0][1])

    def test_switch_off_falls_back_to_normal_handling(self):
        self.guard.update(ttl=False)
        self.capture(FakeMessage(53, "x", photo=True, ttl=10))
        self.assertEqual(self.client.files, [])
        self.assertEqual(self.guard.count(), 1)  # treated like any other message

    def test_own_unwatched_and_oversized_are_respected(self):
        self.capture(FakeMessage(54, "mine", photo=True, ttl=10, out=True))
        self.assertEqual(self.client.files, [])
        self.capture(FakeMessage(55, "elsewhere", photo=True, ttl=10), chat_id=-999)
        self.assertEqual(self.client.files, [])
        self.guard.update(max_media_mb=1)
        self.capture(FakeMessage(56, "huge", photo=True, ttl=10, size=5 * 1024 * 1024))
        self.assertEqual(self.client.files, [])
        self.assertIn("could not be downloaded", self.client.messages[-1][1])

    def test_custom_destination_is_used(self):
        self.guard.update(dest="-100999")
        self.capture(FakeMessage(57, "", photo=True, ttl=5))
        self.assertEqual(self.client.files[0][0], -100999)


class ArchiveTests(GuardCase):
    def setUp(self):
        super().setUp()
        self.guard.update(enabled=True)
        self.guard.add_chat(-100500)

    def archive_rows(self):
        with self.guard.connect() as conn:  # also makes sure the schema exists
            return conn.execute("SELECT * FROM msglog_archive ORDER BY id").fetchall()

    def test_timed_media_is_kept_permanently_as_well_as_sent(self):
        self.capture(FakeMessage(60, "keep me", photo=True, ttl=10))
        self.assertEqual(len(self.client.files), 1)  # still delivered to Saved Messages
        rows = self.archive_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "timed")
        self.assertEqual(rows[0]["sender_name"], "Sara (@sara)")
        self.assertIn("keep me", rows[0]["text"])
        self.assertTrue(os.path.isfile(rows[0]["media_path"]))
        self.assertTrue(rows[0]["media_path"].startswith(self.guard.archive_dir))
        self.assertEqual(self.guard.archive_stats()[0], 1)

    def test_deleted_message_and_media_are_archived_after_delivery(self):
        self.capture(FakeMessage(61, "bye", photo=True))
        run(self.guard.on_deleted(FakeDeleted([61], client=self.client)))
        self.assertEqual(self.guard.count(), 0)  # cache row consumed...
        rows = self.archive_rows()               # ...but a permanent copy remains
        self.assertEqual([r["kind"] for r in rows], ["deleted"])
        self.assertTrue(os.path.isfile(rows[0]["media_path"]))

    def test_purge_never_touches_the_archive(self):
        self.guard.update(retention_hours=1)
        self.capture(FakeMessage(62, "x", photo=True, ttl=5))
        self.now[0] += 10 * 3600
        self.guard.purge_expired()
        rows = self.archive_rows()
        self.assertEqual(len(rows), 1)
        self.assertTrue(os.path.isfile(rows[0]["media_path"]))

    def test_keep_forever_disables_cache_purge(self):
        self.guard.update(retention_hours=0)
        self.capture(FakeMessage(63, "old"))
        self.now[0] += 10_000 * 3600
        self.assertEqual(self.guard.purge_expired(), 0)
        self.assertEqual(self.guard.count(), 1)

    def test_archive_can_be_switched_off(self):
        self.guard.update(archive=False)
        self.capture(FakeMessage(64, "", photo=True, ttl=5))
        self.assertEqual(self.archive_rows(), [])
        self.assertEqual(os.listdir(self.guard.archive_dir), [])

    def test_clear_archive_removes_rows_and_files(self):
        self.capture(FakeMessage(65, "", photo=True, ttl=5))
        path = self.archive_rows()[0]["media_path"]
        self.assertEqual(self.guard.clear_archive(), 1)
        self.assertEqual(self.archive_rows(), [])
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.guard.clear(), 0)  # clearing the cache never reports archive rows

    def test_clearing_the_cache_does_not_remove_the_archive(self):
        self.capture(FakeMessage(66, "", photo=True, ttl=5))
        self.guard.clear()
        self.assertEqual(len(self.archive_rows()), 1)

    def test_mass_deletion_summary_mentions_the_archive(self):
        for i in range(100, 120):
            self.capture(FakeMessage(i, f"m{i}"))
        run(self.guard.on_deleted(FakeDeleted(list(range(100, 120)), client=self.client)))
        self.assertIn("local archive", self.client.messages[-1][1])
        self.assertEqual(len(self.archive_rows()), 20)  # all 20 kept, even the 5 not shown


class EditTests(GuardCase):
    def edit(self, message, **kwargs):
        kwargs.setdefault("client", self.client)
        run(self.guard.on_edited(FakeEvent(message, **kwargs)))

    def test_edit_reports_before_and_after_and_updates_the_copy(self):
        self.guard.update(enabled=True)
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(20, "price is 10"))
        self.edit(FakeMessage(20, "price is 99"))

        text = self.client.messages[0][1]
        self.assertIn("EDITED MESSAGE", text)
        self.assertIn("price is 10", text)
        self.assertIn("price is 99", text)

        self.edit(FakeMessage(20, "price is 99"))  # unchanged text (e.g. a reaction)
        self.assertEqual(len(self.client.messages), 1)

        run(self.guard.on_deleted(FakeDeleted([20], client=self.client)))
        self.assertIn("price is 99", self.client.messages[-1][1])  # latest version kept

    def test_edits_can_be_disabled(self):
        self.guard.update(enabled=True, edits=False)
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(21, "a"))
        self.edit(FakeMessage(21, "b"))
        self.assertEqual(self.client.messages, [])


class RetentionTests(GuardCase):
    def test_purge_removes_old_rows_and_their_files(self):
        self.guard.update(enabled=True, retention_hours=1)
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(30, "old", photo=True))
        run(asyncio.sleep(0))
        with self._connect() as conn:
            path = conn.execute("SELECT media_path FROM msglog").fetchone()[0]
        self.assertTrue(path and os.path.exists(path))

        self.now[0] += 30 * 60
        self.capture(FakeMessage(31, "fresh"))
        self.now[0] += 45 * 60  # 'old' is 75 min old, 'fresh' is 45 min old
        self.assertEqual(self.guard.purge_expired(), 1)
        self.assertEqual(self.guard.count(), 1)
        self.assertFalse(os.path.exists(path))

    def test_clear_wipes_everything(self):
        self.guard.update(enabled=True)
        self.guard.add_chat(-100500)
        self.capture(FakeMessage(40, "a"))
        self.capture(FakeMessage(41, "b"))
        self.assertEqual(self.guard.clear(), 2)
        self.assertEqual(self.guard.count(), 0)


if __name__ == "__main__":
    unittest.main()
