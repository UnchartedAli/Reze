"""REZE 4.0: bots and private chats are separate in the Message Guard.

Bug being guarded against: bot conversations were covered by the "private" switch,
and bot messages in watched groups were stored and reported to Saved Messages.
"""

import asyncio
import os
import shutil
import sqlite3
import tempfile
import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.modules.msglog import MessageLogger


class FakeEntity:
    def __init__(self, ident, bot=False, first_name="Someone", title=None):
        self.id = ident
        self.bot = bot
        self.first_name = first_name
        self.last_name = None
        self.title = title
        self.username = None


class FakeMessage:
    def __init__(self, msg_id, text):
        self.id = msg_id
        self.raw_text = text
        self.message = text
        self.out = False
        self.action = None
        self.media = None
        self.file = None
        self.date = None


class FakeEvent:
    def __init__(self, *, chat_id, message, private=False, group=False, channel=False,
                 chat=None, sender=None, client=None, deleted_ids=None):
        self.chat_id = chat_id
        self.message = message
        self.is_private = private
        self.is_group = group
        self.is_channel = channel
        self._chat = chat
        self._sender = sender
        self.client = client
        self.deleted_ids = deleted_ids or []

    async def get_chat(self):
        return self._chat

    async def get_sender(self):
        return self._sender


class FakeClient:
    def __init__(self):
        self.sent = []

    async def send_message(self, entity, text, **kwargs):
        self.sent.append((entity, text))
        return None

    async def send_file(self, entity, file, **kwargs):
        self.sent.append((entity, "file"))


BOT_USER = 7001
HUMAN_USER = 8001
GROUP = -1001500000001
HUMAN_CHAT = 8001
BOT_CHAT = 7001


class BotSplitTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="reze-guard-bots-")
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
        self.guard.update(enabled=True, archive=False)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def stored(self):
        with self._connect() as conn:
            return [dict(r) for r in conn.execute("SELECT scope, msg_id, chat_id, chat_kind FROM msglog").fetchall()]

    def run_(self, coro):
        return asyncio.run(coro)

    def capture_private(self, chat_id, msg_id, text, bot):
        event = FakeEvent(
            chat_id=chat_id,
            message=FakeMessage(msg_id, text),
            private=True,
            chat=FakeEntity(chat_id, bot=bot),
            sender=FakeEntity(chat_id, bot=bot),
        )
        self.run_(self.guard.on_new_message(event))

    def capture_group(self, msg_id, text, sender_bot):
        event = FakeEvent(
            chat_id=GROUP,
            message=FakeMessage(msg_id, text),
            group=True,
            sender=FakeEntity(9000 + msg_id, bot=sender_bot),
        )
        self.run_(self.guard.on_new_message(event))

    # -------------------------------------------------------- configuration
    def test_bots_switch_exists_and_is_off_by_default(self):
        self.assertFalse(self.guard.config["bots"])

    def test_watch_truth_table(self):
        self.guard.update(private=True, groups=True, bots=False)
        self.assertTrue(self.guard.is_watched(HUMAN_CHAT, private=True, group=False))
        self.assertFalse(self.guard.is_watched(BOT_CHAT, private=True, group=False, bot=True))
        self.assertFalse(self.guard.is_watched(GROUP, private=False, group=True, bot=True))
        self.guard.update(bots=True)
        self.assertTrue(self.guard.is_watched(BOT_CHAT, private=False, group=False, bot=True))

    def test_explicit_chat_is_an_intentional_choice_even_for_a_bot(self):
        self.guard.add_chat(BOT_CHAT)
        self.assertTrue(self.guard.is_watched(BOT_CHAT, private=False, group=False, bot=True))

    # ------------------------------------------------------------ capture
    def test_private_switch_stores_people_but_not_bots(self):
        self.guard.update(private=True)
        self.capture_private(HUMAN_CHAT, 1, "hi from a person", bot=False)
        self.capture_private(BOT_CHAT, 2, "hi from a bot", bot=True)
        rows = self.stored()
        self.assertEqual([r["msg_id"] for r in rows], [1])
        self.assertEqual(rows[0]["chat_kind"], "private")

    def test_bots_switch_stores_bot_chats_with_their_own_kind(self):
        self.guard.update(bots=True)
        self.capture_private(BOT_CHAT, 2, "bot says hi", bot=True)
        rows = self.stored()
        self.assertEqual(rows[0]["chat_kind"], "bot")

    def test_group_bot_messages_are_not_stored_unless_bots_is_on(self):
        self.guard.update(groups=True)
        self.capture_group(10, "human in the group", sender_bot=False)
        self.capture_group(11, "bot spam in the group", sender_bot=True)
        self.assertEqual([r["msg_id"] for r in self.stored()], [10])
        self.guard.update(bots=True)
        self.capture_group(12, "bot news in the group", sender_bot=True)
        self.assertIn(12, [r["msg_id"] for r in self.stored()])

    # ----------------------------------------------------- report delivery
    def test_deleting_a_bot_message_is_not_reported_after_bots_are_switched_off(self):
        self.guard.update(bots=True)
        self.capture_private(BOT_CHAT, 2, "bot secret text", bot=True)
        self.guard.update(bots=False)
        event = FakeEvent(chat_id=None, message=None, private=True, client=self.client, deleted_ids=[2])
        self.run_(self.guard.on_deleted(event))
        self.assertEqual(self.client.sent, [], "a bot message must not reach Saved Messages")
        self.assertEqual(self.stored(), [], "the cached row is forgotten")

    def test_editing_a_bot_message_is_not_reported_after_bots_are_switched_off(self):
        self.guard.update(bots=True)
        self.capture_private(BOT_CHAT, 3, "original bot text", bot=True)
        self.guard.update(bots=False)
        edit = FakeEvent(
            chat_id=BOT_CHAT,
            message=FakeMessage(3, "edited bot text"),
            private=True,
            client=self.client,
        )
        self.run_(self.guard.on_edited(edit))
        self.assertEqual(self.client.sent, [])

    def test_deleting_a_person_private_message_is_still_reported(self):
        self.guard.update(private=True)
        self.capture_private(HUMAN_CHAT, 4, "person message", bot=False)
        event = FakeEvent(chat_id=None, message=None, private=True, client=self.client, deleted_ids=[4])
        self.run_(self.guard.on_deleted(event))
        self.assertTrue(self.client.sent)
        self.assertEqual(self.client.sent[0][0], "me")
        self.assertIn("person message", self.client.sent[0][1])

    def test_bot_rows_cached_before_the_upgrade_are_cleared_once(self):
        self.guard.update(private=True)
        self.capture_private(HUMAN_CHAT, 5, "old private row", bot=False)
        self.guard.update(bots=True)
        self.capture_private(BOT_CHAT, 6, "old bot row", bot=True)
        # Simulate rows saved by the previous version: everything was "private".
        with self._connect() as conn:
            conn.execute("UPDATE msglog SET chat_kind = 'private'")
            conn.commit()
        self.guard._split_bots_once()
        self.assertEqual(self.stored(), [])
        self.assertEqual(self.settings.get("msglog:split_bots_v1"), "1")
        # Runs once: rows saved afterwards are kept.
        self.guard.update(private=True)
        self.capture_private(HUMAN_CHAT, 7, "new private row", bot=False)
        self.guard._split_bots_once()
        self.assertEqual([r["msg_id"] for r in self.stored()], [7])


if __name__ == "__main__":
    unittest.main()
