"""Productivity tools, automation engine and end-to-end command flows."""

import json
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import support

from reze.automation.engine import AutomationEngine, AutomationError, validate_rule
from reze.command_router import router
from reze.database import db
from reze.preferences import set_pref
from reze.productivity import qr
from reze.productivity.reminders import ReminderService, parse_absolute, parse_duration

class QrTests(unittest.TestCase):
    def test_format_and_version_words_match_the_specification(self):
        self.assertEqual(qr.format_info("L", 0), 0x77C4)
        self.assertEqual(qr.format_info("M", 0), 0x5412)
        self.assertEqual(qr.version_info(7), 0x07C94)

    def test_reed_solomon_matches_the_published_example(self):
        data = [0x10, 0x20, 0x0C, 0x56, 0x61, 0x80, 0xEC, 0x11,
                0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11, 0xEC, 0x11]
        expected = [0xA5, 0x24, 0xD4, 0xC1, 0xED, 0x36, 0xC7, 0x87, 0x2C, 0x55]
        self.assertEqual(qr.rs_encode(data, 10), expected)
        self.assertEqual(qr.rs_syndromes(data + expected, 10), [0] * 10)

    def test_matrix_geometry_and_format_readback(self):
        code = qr.encode_qr("https://t.me/yamods", "M")
        self.assertEqual(code.size, 17 + 4 * code.version)
        self.assertEqual(len(code.modules), code.size)
        for row in code.modules:
            self.assertEqual(len(row), code.size)
        level, mask = qr.read_format(code.modules)
        self.assertEqual((level, mask), ("M", code.mask))
        # Finder pattern centres must be dark, separators light.
        self.assertTrue(code.modules[3][3])
        self.assertFalse(code.modules[7][7])
        self.assertTrue(code.modules[0][0])

    def test_capacity_limit(self):
        with self.assertRaises(ValueError):
            qr.encode_qr("x" * 1000, "M")
        with self.assertRaises(ValueError):
            qr.encode_qr("", "M")

    def test_png_output(self):
        directory = tempfile.mkdtemp(prefix="reze-qr-")
        try:
            path = os.path.join(directory, "qr.png")
            qr.qr_png("reze", path, scale=4)
            self.assertTrue(os.path.getsize(path) > 100)
            with open(path, "rb") as handle:
                self.assertEqual(handle.read(8), b"\x89PNG\r\n\x1a\n")
            try:
                from PIL import Image
            except ImportError:
                return
            with Image.open(path) as image:
                code = qr.encode_qr("reze", "M")
                expected = (code.size + 8) * 4
                self.assertEqual(image.size, (expected, expected))
        finally:
            shutil.rmtree(directory, ignore_errors=True)


class ReminderParsingTests(unittest.TestCase):
    def test_durations(self):
        self.assertEqual(parse_duration("30s"), 30)
        self.assertEqual(parse_duration("10m"), 600)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1d"), 86400)
        self.assertEqual(parse_duration("15"), 900)
        with self.assertRaises(ValueError):
            parse_duration("0m")
        with self.assertRaises(ValueError):
            parse_duration("abc")

    def test_absolute_time_in_timezone(self):
        due = parse_absolute("2030-01-01 12:00", "UTC")
        self.assertEqual(due, datetime(2030, 1, 1, 12, 0))
        with self.assertRaises(ValueError):
            parse_absolute("not-a-date", "UTC")

    def test_reminder_service_delivers(self):
        db.add_reminder(-100500, 4242, "Drink water", datetime.utcnow() - timedelta(seconds=1))
        client = support.DummyClient()
        service = ReminderService(client_provider=lambda: client)
        delivered = support.run(service.tick())
        self.assertGreaterEqual(delivered, 1)
        self.assertTrue(any("reminder" in text.lower() for _chat, text in client.sent))
        self.assertEqual(db.due_reminders(), [])


class ProductivityCommandTests(unittest.TestCase):
    def setUp(self):
        set_pref("prefix", ".")

    def test_save_and_find(self):
        from reze.commands.productivity import find_cmd, save_cmd

        reply = support.DummyMessage(text="A saved insight about MTProto")
        ctx = support.make_context(text=".save", reply=reply)
        support.run(save_cmd(ctx))
        self.assertIn("SAVED TO ARCHIVE", ctx.message.replies[0])

        find_ctx = support.make_context(text=".find mtproto", args=["mtproto"])
        support.run(find_cmd(find_ctx))
        self.assertIn("mtproto", find_ctx.message.replies[0].lower())

    def test_notes_lifecycle(self):
        from reze.commands.productivity import notes_cmd

        add_ctx = support.make_context(text=".notes add deploy run the checklist", args=["add", "deploy", "run", "the", "checklist"])
        support.run(notes_cmd(add_ctx))
        self.assertIn("saved", add_ctx.message.replies[0].lower())

        show_ctx = support.make_context(text=".notes show deploy", args=["show", "deploy"])
        support.run(notes_cmd(show_ctx))
        self.assertIn("checklist", show_ctx.message.replies[0])

        list_ctx = support.make_context(text=".notes", args=[])
        support.run(notes_cmd(list_ctx))
        self.assertIn("deploy", list_ctx.message.replies[0])

        delete_ctx = support.make_context(text=".notes delete deploy", args=["delete", "deploy"])
        support.run(notes_cmd(delete_ctx))
        self.assertIsNone(db.get_personal_note("deploy"))

    def test_remind_creates_reminder(self):
        from reze.commands.productivity import remind_cmd

        ctx = support.make_context(text=".remind 10m stretch", args=["10m", "stretch"])
        support.run(remind_cmd(ctx))
        self.assertIn("REMINDER SCHEDULED", ctx.message.replies[0])
        self.assertTrue(db.list_reminders(status="pending"))

    def test_links_from_reply(self):
        from reze.commands.productivity import links_cmd

        reply = support.DummyMessage(text="see https://telegram.org and t.me/yamods")
        ctx = support.make_context(text=".links", reply=reply)
        support.run(links_cmd(ctx))
        self.assertIn("telegram.org", ctx.message.replies[0])

    def test_qr_command_sends_png(self):
        from reze.commands.productivity import qr_cmd

        client = support.DummyClient()
        ctx = support.make_context(text=".qr https://t.me/yamods", args=["https://t.me/yamods"], client=client)
        support.run(qr_cmd(ctx))
        self.assertEqual(len(client.sent_files), 1)
        self.assertTrue(client.sent_files[0]["file"].endswith(".png"))


class AutomationEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AutomationEngine()
        for rule in self.engine.rules():
            self.engine.delete(rule.name)

    def tearDown(self):
        for rule in self.engine.rules():
            self.engine.delete(rule.name)

    def test_validation_errors(self):
        self.assertTrue(validate_rule("", "schedule", {"at": "18:30"}, [], [{"type": "save", "text": "x"}]))
        self.assertTrue(validate_rule("ok", "bogus", {}, [], [{"type": "save", "text": "x"}]))
        self.assertTrue(validate_rule("ok", "schedule", {"at": "99:99"}, [], [{"type": "save", "text": "x"}]))
        self.assertTrue(validate_rule("ok", "schedule", {"at": "08:00"}, [], []))
        self.assertTrue(
            validate_rule("ok", "schedule", {"at": "08:00"}, [], [{"type": "command", "name": "shutdown"}])
        )
        self.assertEqual(
            validate_rule("ok", "schedule", {"at": "08:00"}, [], [{"type": "save", "text": "x"}]),
            [],
        )

    def test_create_enable_disable_delete(self):
        rule = self.engine.create(
            "daily", "schedule", {"at": "18:30"}, [{"type": "save", "text": "note"}], created_by=4242
        )
        self.assertFalse(rule.enabled)
        self.engine.enable("daily")
        self.assertTrue(self.engine.rules()[0].enabled)
        self.engine.disable("daily")
        self.assertFalse(self.engine.rules()[0].enabled)
        self.assertTrue(self.engine.delete("daily"))
        self.assertEqual(self.engine.rules(), [])

    def test_duplicate_rule_rejected(self):
        self.engine.create("dup", "interval", {"minutes": 30}, [{"type": "save", "text": "x"}])
        with self.assertRaises(AutomationError):
            self.engine.create("dup", "interval", {"minutes": 30}, [{"type": "save", "text": "x"}])

    def test_keyword_rule_runs_and_persists(self):
        self.engine.create(
            "capture",
            "keyword",
            {"text": "deploy"},
            [{"type": "save", "text": "deploy detected for {chat_id}"}],
            cooldown=5,
            created_by=4242,
        )
        self.engine.enable("capture")
        message = support.DummyMessage(text="we should deploy now")
        ran = support.run(self.engine.on_message(message, -100700, 777, "we should deploy now"))
        self.assertEqual(ran, 1)
        entries = db.search_archive("deploy detected")
        self.assertTrue(entries)
        rule = self.engine.rules()[0]
        self.assertEqual(rule.run_count, 1)

    def test_cooldown_blocks_immediate_second_run(self):
        self.engine.create(
            "limited",
            "keyword",
            {"text": "ping"},
            [{"type": "save", "text": "hit"}],
            cooldown=120,
            created_by=4242,
        )
        self.engine.enable("limited")
        first = support.run(self.engine.on_message(support.DummyMessage(text="ping"), -1, 1, "ping"))
        second = support.run(self.engine.on_message(support.DummyMessage(text="ping"), -1, 1, "ping"))
        self.assertEqual((first, second), (1, 0))

    def test_outbound_notify_requires_owner_rule(self):
        self.engine.create(
            "notify",
            "keyword",
            {"text": "alert"},
            [{"type": "notify", "text": "heads up"}],
            cooldown=5,
            created_by=999,  # not the configured owner
        )
        self.engine.enable("notify")
        client = support.DummyClient()
        self.engine.client_provider = lambda: client
        ran = support.run(self.engine.on_message(support.DummyMessage(text="alert"), -1, 1, "alert"))
        self.assertEqual(ran, 1)
        self.assertEqual(client.sent, [])
        self.assertIn("owner", self.engine.rules()[0].last_error)

    def test_command_action_enforces_allowlist(self):
        with self.assertRaises(AutomationError) as context:
            self.engine.create(
                "cmd", "keyword", {"text": "run"},
                [{"type": "command", "name": "shutdown"}], cooldown=5, created_by=4242,
            )
        self.assertIn("allowlist", str(context.exception))
        self.assertEqual(self.engine.rules(), [])

    def test_recursion_guard(self):
        from reze.automation import engine as engine_module

        rule = self.engine.create(
            "deep", "keyword", {"text": "go"}, [{"type": "save", "text": "x"}], cooldown=5
        )
        self.engine.enable("deep")
        token = engine_module._DEPTH.set(2)
        try:
            ran = support.run(self.engine._execute(rule, {"text": "go", "chat_id": 0}, time.time()))
        finally:
            engine_module._DEPTH.reset(token)
        self.assertFalse(ran)


@unittest.skipUnless(__import__("reze.media.images", fromlist=["available"]).available(), "Pillow missing")
class CommandIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image

        cls.directory = tempfile.mkdtemp(prefix="reze-flow-")
        cls.image = os.path.join(cls.directory, "photo.png")
        Image.new("RGB", (640, 480), (30, 90, 160)).save(cls.image)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def test_sticker_command_end_to_end(self):
        from reze.commands.media import sticker_cmd

        client = support.DummyClient(downloads=[self.image])
        reply = support.DummyMessage(media=object(), file=support.DummyFile(name="photo.png"))
        ctx = support.make_context(text=".sticker", client=client, reply=reply)
        support.run(sticker_cmd(ctx))

        self.assertTrue(ctx.message.replies)
        self.assertIn("STARTED", ctx.message.replies[0])
        self.assertEqual(len(client.sent_files), 1)
        self.assertIn("force_document", client.sent_files[0])
        assert any("ready" in edit.lower() for edit in ctx.message.edits), ctx.message.edits

    def test_stickerpack_requires_confirmation_then_creates_set(self):
        from reze.commands.media import stickerpack_cmd

        client = support.DummyClient(downloads=[self.image, self.image])
        reply = support.DummyMessage(media=object(), file=support.DummyFile(name="photo.png"))

        plan_ctx = support.make_context(text=".stickerpack Reze Pack | 🙂", args=["Reze", "Pack", "|", "🙂"], client=client, reply=reply)
        support.run(stickerpack_cmd(plan_ctx))
        text = plan_ctx.message.replies[0]
        self.assertIn("CONFIRM STICKER SET CREATION", text)
        import re

        token = re.search(r"confirm ([0-9A-F]{8})", text).group(1)

        confirm_ctx = support.make_context(text=f".stickerpack confirm {token}", args=["confirm", token], client=client, reply=reply)
        support.run(stickerpack_cmd(confirm_ctx))
        self.assertEqual(len(client.requests), 1)
        request = client.requests[0]
        self.assertEqual(request.title, "Reze Pack")
        joined = " ".join(confirm_ctx.message.edits)
        self.assertIn("addstickers", joined)

    def test_theme_and_aiinfo_dispatch(self):
        import reze.commands.ai  # noqa: F401  (registers .aiinfo)
        import reze.commands.general  # noqa: F401  (registers .help)

        set_pref("prefix", ".")
        message = support.DummyMessage(text=".aiinfo")
        support.run(router.handle_message(message, support.DummyClient()))
        self.assertIn("AI CONFIGURATION", message.replies[0])

        help_message = support.DummyMessage(text=".help media")
        support.run(router.handle_message(help_message, support.DummyClient()))
        self.assertIn("MEDIA COMMANDS", help_message.replies[0])

    def test_sticker_command_rejects_non_reply(self):
        from reze.commands.media import sticker_cmd

        ctx = support.make_context(text=".sticker")
        support.run(sticker_cmd(ctx))
        self.assertIn("Usage", ctx.message.replies[0])


if __name__ == "__main__":
    unittest.main()

