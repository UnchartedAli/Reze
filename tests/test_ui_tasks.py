"""Tests for the ASCII engine, themes, task manager and confirmations."""

import asyncio
import time
import unittest

import support

from reze.core.confirmations import ConfirmationStore
from reze.core.tasks import TaskManager, TaskQueueFull, TaskStatus
from reze.exceptions import ConfirmationError, TaskNotFound
from reze.preferences import get_pref, set_pref
from reze.ui import ascii
from reze.ui.themes import THEMES, theme_names


class AsciiEngineTests(unittest.TestCase):
    def test_banner_contains_identity(self):
        from reze import __version__

        banner = ascii.banner("CYBER")
        self.assertIn("PERSONAL DIGITAL OS", banner)
        self.assertIn(__version__, banner)
        self.assertNotIn("\x1b", banner)

    def test_frames_are_rectangular(self):
        for name in ("CYBER", "GHOST", "TERMINAL"):
            rendered = ascii.frame(
                "System",
                ["short", "a much longer line that has to wrap inside the frame width without breaking words"],
                footer="footer",
                theme=name,
            )
            widths = {len(line) for line in rendered.splitlines()}
            self.assertEqual(len(widths), 1, f"{name} produced ragged lines: {widths}")

    def test_compact_theme_has_no_borders(self):
        rendered = ascii.frame("Compact", ["one", "two"], theme="COMPACT")
        self.assertNotIn("╔", rendered)
        self.assertNotIn("|", rendered)
        self.assertTrue(rendered.startswith("›"))

    def test_tags_and_panels(self):
        success = ascii.success("Done", ["all good"])
        error = ascii.error("Failed", ["nope"])
        warning = ascii.warning("Careful", [])
        self.assertIn("[ OK ]", success)
        self.assertIn("FAIL", error)
        self.assertIn("WARN", warning)

    def test_escape_markdown_and_control_codes(self):
        escaped = ascii.escape_md("user_name *bold* [link]\x1b[31m")
        self.assertIn("\\_", escaped)
        self.assertIn("\\*", escaped)
        self.assertNotIn("\x1b", escaped)
        self.assertEqual(ascii.code("a`b"), "`a'b`")

    def test_split_respects_limit_and_balances_backticks(self):
        text = "\n".join(["`value_%d` %s" % (index, "x" * 80) for index in range(200)])
        chunks = ascii.split_text(text, 400)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), 400)
            self.assertEqual(chunk.count("`") % 2, 0)

    def test_split_never_drops_content(self):
        text = "alpha beta gamma\n" * 500
        chunks = ascii.split_text(text, 1000)
        self.assertEqual("".join(chunks).replace("\n", ""), text.replace("\n", ""))

    def test_preview_covers_themes_and_progress(self):
        preview = ascii.preview("GHOST")
        self.assertIn("GHOST", preview)
        self.assertIn("Available themes", preview)
        self.assertIn("%", ascii.progress("working", 42.0, "half", "abc123"))
        self.assertIn("████", ascii.bar(100, 8))

    def test_theme_registry(self):
        self.assertEqual(set(theme_names()), {"CYBER", "GHOST", "TERMINAL", "COMPACT"})
        self.assertEqual(THEMES["COMPACT"].compact, True)

    def test_unknown_theme_falls_back(self):
        self.assertEqual(ascii.theme_for("does-not-exist").key, "CYBER")


class PreferenceTests(unittest.TestCase):
    def test_theme_preference_roundtrip_and_validation(self):
        set_pref("theme", "ghost")
        self.assertEqual(get_pref("theme"), "GHOST")
        with self.assertRaises(ValueError):
            set_pref("theme", "neon")
        set_pref("theme", "CYBER")

    def test_prefix_validation(self):
        set_pref("prefix", "!")
        self.assertEqual(get_pref("prefix"), "!")
        with self.assertRaises(ValueError):
            set_pref("prefix", "!!!")
        set_pref("prefix", ".")

    def test_media_quality_validation(self):
        with self.assertRaises(ValueError):
            set_pref("media_quality", "0")
        set_pref("media_quality", "70")
        self.assertEqual(get_pref("media_quality"), "70")


class TaskManagerTests(unittest.TestCase):
    def test_completion_and_value(self):
        async def scenario():
            manager = TaskManager(concurrency=2, queue_limit=4, default_timeout=5)
            seen = {}

            async def work(record):
                record.update(50, "halfway")
                await asyncio.sleep(0.01)
                return "artifact.webp"

            task = await manager.submit("sticker", work)
            record = await manager.wait(task.id, timeout=5)
            seen["status"] = record.status
            seen["value"] = record.value
            seen["progress"] = record.progress
            seen["result"] = record.result_summary
            return seen

        result = support.run(scenario())
        self.assertEqual(result["status"], TaskStatus.COMPLETED)
        self.assertEqual(result["value"], "artifact.webp")
        self.assertEqual(result["progress"], 100.0)
        self.assertIn("artifact", result["result"])

    def test_failure_is_recorded(self):
        async def scenario():
            manager = TaskManager(concurrency=1, queue_limit=2, default_timeout=5)

            async def boom(record):
                raise ValueError("bad input")

            task = await manager.submit("convert", boom)
            return await manager.wait(task.id, timeout=5)

        record = support.run(scenario())
        self.assertEqual(record.status, TaskStatus.FAILED)
        self.assertIn("bad input", record.error)

    def test_timeout(self):
        async def scenario():
            manager = TaskManager(concurrency=1, queue_limit=2, default_timeout=0.2)

            async def slow(record):
                await asyncio.sleep(5)

            task = await manager.submit("slow", slow)
            return await manager.wait(task.id, timeout=5)

        record = support.run(scenario())
        self.assertEqual(record.status, TaskStatus.TIMEOUT)
        self.assertIn("timeout", record.error.lower())

    def test_cancel_running_and_queued(self):
        async def scenario():
            manager = TaskManager(concurrency=1, queue_limit=3, default_timeout=30)
            gate = asyncio.Event()

            async def blocker(record):
                await gate.wait()

            running = await manager.submit("block", blocker)
            await asyncio.sleep(0.01)
            queued = await manager.submit("block", blocker)
            cancelled_running = await manager.cancel(running.id)
            await asyncio.sleep(0.05)
            cancelled_queued = await manager.cancel(queued.id)
            await asyncio.sleep(0.05)
            return (
                cancelled_running,
                cancelled_queued,
                manager.get(running.id).status,
                manager.get(queued.id).status,
            )

        running_cancelled, queued_cancelled, running_status, queued_status = support.run(scenario())
        self.assertTrue(running_cancelled)
        self.assertTrue(queued_cancelled)
        self.assertEqual(running_status, TaskStatus.CANCELLED)
        self.assertEqual(queued_status, TaskStatus.CANCELLED)

    def test_queue_limit(self):
        async def scenario():
            manager = TaskManager(concurrency=1, queue_limit=1, default_timeout=30)
            gate = asyncio.Event()

            async def blocker(record):
                await gate.wait()

            await manager.submit("block", blocker)
            await asyncio.sleep(0.01)
            await manager.submit("block", blocker)
            with self.assertRaises(TaskQueueFull):
                await manager.submit("block", blocker)
            await manager.shutdown()
            await asyncio.sleep(0.05)

        support.run(scenario())

    def test_unknown_task_id(self):
        manager = TaskManager()
        with self.assertRaises(TaskNotFound):
            support.run(manager.cancel("nope"))
        self.assertIsNone(manager.get("nope"))


class ConfirmationTests(unittest.TestCase):
    def test_single_use_token(self):
        store = ConfirmationStore()
        token = store.issue("stickerpack", -100, 4242, payload="Pack|🙂")
        confirmation = store.consume(token, "stickerpack", -100, 4242)
        self.assertEqual(confirmation.payload, "Pack|🙂")
        with self.assertRaises(ConfirmationError):
            store.consume(token, "stickerpack", -100, 4242)

    def test_action_and_owner_binding(self):
        store = ConfirmationStore()
        token = store.issue("removebg", -100, 4242)
        with self.assertRaises(ConfirmationError):
            store.consume(token, "other-action", -100, 4242)
        with self.assertRaises(ConfirmationError):
            store.consume(token, "removebg", -200, 4242)
        with self.assertRaises(ConfirmationError):
            store.consume(token, "removebg", -100, 1)
        self.assertIsNotNone(store.consume(token, "removebg", -100, 4242))

    def test_expiry(self):
        store = ConfirmationStore(ttl=15)
        token = store.issue("removebg", 1, 2)
        store._pending[token].expires_at = time.time() - 1
        with self.assertRaises(ConfirmationError):
            store.consume(token, "removebg", 1, 2)

    def test_unknown_token(self):
        store = ConfirmationStore()
        with self.assertRaises(ConfirmationError):
            store.consume("DEADBEEF", "removebg", 1, 2)


if __name__ == "__main__":
    unittest.main()
