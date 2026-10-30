"""`.watch` command flows (Message Guard control)."""

import unittest

import support

from reze.commands.watch import watch_cmd
from reze.modules.msglog import message_logger as guard


def _reset():
    guard._cfg = None
    guard.update(enabled=False, dest="me", chats=[], private=False, groups=False,
                 edits=True, media=True, ttl=True, archive=True, own=False, retention_hours=48)


def _flat(text):
    """Frames uppercase titles and wrap lines; compare on letters and digits."""
    import re

    return re.sub(r"[^a-z0-9|\-]+", " ", str(text).lower())


class WatchCommandTests(unittest.TestCase):
    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def call(self, *args, chat_id=-100777):
        ctx = support.make_context(text=".watch " + " ".join(args), args=list(args), chat_id=chat_id)
        support.run(watch_cmd(ctx))
        return "\n".join(str(r) for r in ctx.message.replies)

    def test_status_is_the_default(self):
        self.assertIn("Guard: OFF", self.call())

    def test_on_off(self):
        self.call("on")
        self.assertTrue(guard.config["enabled"])
        self.call("off")
        self.assertFalse(guard.config["enabled"])

    def test_add_current_chat_and_explicit_id_then_delete(self):
        self.call("add")
        self.call("add", "-100123")
        self.assertEqual(guard.config["chats"], [-100777, -100123])
        self.assertIn("-100777", _flat(self.call("list")))
        self.call("del")
        self.assertEqual(guard.config["chats"], [-100123])
        self.assertIn("was not in the list", self.call("del", "555"))

    def test_toggles_and_validation(self):
        self.call("private", "on")
        self.call("groups", "on")
        self.call("edits", "off")
        self.call("ttl", "off")
        self.assertTrue(guard.config["private"] and guard.config["groups"])
        self.assertFalse(guard.config["edits"])
        self.assertFalse(guard.config["ttl"])
        self.call("ttl", "on")
        self.assertTrue(guard.config["ttl"])
        self.assertIn("invalid arguments", _flat(self.call("private", "maybe")))

    def test_destination_and_retention(self):
        self.call("dest", "here")
        self.assertEqual(guard.destination(), -100777)
        self.call("dest", "me")
        self.assertEqual(guard.destination(), "me")
        self.call("keep", "72")
        self.assertEqual(guard.config["retention_hours"], 72)
        self.call("keep", "forever")
        self.assertEqual(guard.config["retention_hours"], 0)
        self.assertIn("never auto-deleted", _flat(self.call("keep", "0")))
        self.assertIn("dest me|here", _flat(self.call("dest", "nowhere")))

    def test_archive_toggle_and_clear(self):
        self.call("archive", "off")
        self.assertFalse(guard.config["archive"])
        self.call("archive", "on")
        self.assertTrue(guard.config["archive"])
        self.assertIn("archive cleared", _flat(self.call("archive", "clear")))
        self.assertIn("archive 0 items", _flat(self.call("status")))

    def test_command_is_owner_only(self):
        from reze.command_router import router

        self.assertTrue(router.commands["watch"].owner_only)


if __name__ == "__main__":
    unittest.main()
