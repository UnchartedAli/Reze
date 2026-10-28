"""Core tests: configuration, storage, auth, router, moderation helpers."""

import asyncio
import os
import unittest
from unittest.mock import patch

import support  # noqa: F401  (prepares the test environment before reze imports)

from reze.command_router import CommandContext, CommandRouter
from reze.config import Settings, settings
from reze.database import Database
from reze.exceptions import DuplicateCommandError
from reze.modules.antiflood import AntiFloodTracker
from reze.modules.filters import check_blacklists, check_message_filters, contains_link
from reze.modules.greetings import format_welcome_message
from reze.web.auth import (
    create_session,
    destroy_session,
    get_session,
    hash_password,
    validate_csrf,
    verify_password,
)


class SettingsTests(unittest.TestCase):
    def test_validation_reports_missing_required_values(self):
        empty = Settings(REZE_API_ID=0, REZE_API_HASH="", REZE_OWNER_ID=0)
        self.assertGreaterEqual(len(empty.validate_production()), 3)

        complete = Settings(
            REZE_API_ID=12345,
            REZE_API_HASH="hash",
            REZE_OWNER_ID=999,
            REZE_PANEL_PASSWORD="secret",
        )
        self.assertEqual(complete.validate_production(), [])

    def test_hosted_port_overrides_binding(self):
        with patch.dict(os.environ, {"PORT": "10000"}, clear=False):
            loaded = Settings.load_from_env()
            self.assertEqual(loaded.web_port, 10000)
            self.assertEqual(loaded.effective_web_host, "0.0.0.0")

    def test_data_dir_derives_paths(self):
        data_dir = os.path.join("tmp", "volume")
        with patch.dict(
            os.environ,
            {"REZE_DATA_DIR": data_dir, "REZE_SESSION_PATH": "", "REZE_DATABASE_URL": ""},
            clear=False,
        ):
            loaded = Settings.load_from_env()
            self.assertEqual(loaded.session_path, os.path.join(data_dir, "reze.session"))
            self.assertIn(data_dir, loaded.database_url)

    def test_display_url_never_advertises_wildcard(self):
        self.assertEqual(
            Settings(REZE_WEB_HOST="0.0.0.0", REZE_WEB_PORT=9000).display_url,
            "http://127.0.0.1:9000",
        )
        self.assertEqual(
            Settings(REZE_PUBLIC_URL="https://reze.example").display_url,
            "https://reze.example",
        )

    def test_env_example_documents_every_setting(self):
        """Every REZE_* setting must appear in .env.example."""
        import pathlib
        import re

        text = pathlib.Path(".env.example").read_text(encoding="utf-8")
        documented = set(re.findall(r"^(REZE_[A-Z0-9_]+)=", text, re.MULTILINE))
        aliases = {field.alias for field in Settings.model_fields.values() if field.alias}
        missing = sorted(aliases - documented)
        self.assertEqual(missing, [], f"settings missing from .env.example: {missing}")

    def test_ai_disabled_without_credentials(self):
        self.assertFalse(Settings().ai_enabled)
        self.assertTrue(
            Settings(
                REZE_AI_PROVIDER="openai",
                REZE_AI_MODEL="gpt-4o-mini",
                REZE_AI_API_KEY="key",
            ).ai_enabled
        )

    def test_vision_auto_detection(self):
        self.assertTrue(Settings(REZE_AI_MODEL="gpt-4o-mini").ai_vision_enabled)
        self.assertFalse(Settings(REZE_AI_MODEL="gpt-3.5-turbo").ai_vision_enabled)
        self.assertTrue(Settings(REZE_AI_MODEL="gpt-3.5-turbo", REZE_AI_VISION="on").ai_vision_enabled)


class AuthTests(unittest.TestCase):
    def test_password_hashing_is_salted_and_verifiable(self):
        first = hash_password("Reze@2.0")
        second = hash_password("Reze@2.0")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("Reze@2.0", first))
        self.assertTrue(verify_password("Reze@2.0", second))
        self.assertFalse(verify_password("wrong", first))
        self.assertFalse(verify_password("Reze@2.0", "not-a-hash"))

    def test_session_lifecycle_and_csrf(self):
        token = create_session("admin")
        session = get_session(token)
        self.assertIsNotNone(session)
        self.assertTrue(validate_csrf(session, session["csrf_token"]))
        self.assertFalse(validate_csrf(session, "wrong-token"))
        self.assertFalse(validate_csrf(session, ""))
        destroy_session(token)
        self.assertIsNone(get_session(token))
        self.assertFalse(validate_csrf(None, "token"))


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(os.path.join(support.TEST_DATA_DIR, "unit.db"))

    def test_group_settings_and_warnings(self):
        chat_id = -100777
        self.db.update_group_settings(chat_id, antiflood_enabled=1, rules="Be kind")
        config = self.db.get_group_settings(chat_id)
        self.assertEqual(config["antiflood_enabled"], 1)
        self.assertEqual(config["rules"], "Be kind")

        self.assertEqual(self.db.add_warning(chat_id, 5, 1, "spam"), 1)
        self.assertEqual(self.db.add_warning(chat_id, 5, 1, "again"), 2)
        self.assertEqual(self.db.get_warnings_count(chat_id, 5), 2)
        self.assertEqual(self.db.remove_warning(chat_id, 5), 1)
        self.db.reset_warnings(chat_id, 5)
        self.assertEqual(self.db.get_warnings_count(chat_id, 5), 0)

    def test_filters_and_blacklists(self):
        chat_id = -100778
        self.db.set_filter(chat_id, "Hello", "Hi there")
        self.assertEqual(self.db.get_filters(chat_id)[0]["keyword"], "hello")
        self.assertTrue(self.db.remove_filter(chat_id, "hello"))
        self.assertFalse(self.db.remove_filter(chat_id, "hello"))

        self.db.add_blacklist(chat_id, "Badword")
        self.assertEqual(self.db.get_blacklists(chat_id)[0]["trigger"], "badword")
        self.assertTrue(self.db.remove_blacklist(chat_id, "badword"))

    def test_key_value_settings(self):
        self.assertIsNone(self.db.get_setting("pref:theme"))
        self.db.set_setting("pref:theme", "GHOST")
        self.assertEqual(self.db.get_setting("pref:theme"), "GHOST")
        self.db.set_setting("pref:theme", "CYBER")
        self.assertEqual(self.db.all_settings()["pref:theme"], "CYBER")
        self.assertTrue(self.db.delete_setting("pref:theme"))

    def test_archive_search_and_delete(self):
        entry = self.db.add_archive(
            kind="link", title="MTProto docs", content="session strings", url="https://core.telegram.org"
        )
        self.assertGreater(entry, 0)
        self.assertEqual(len(self.db.search_archive("mtproto")), 1)
        self.assertEqual(len(self.db.search_archive("nothing-here")), 0)
        self.assertEqual(self.db.archive_count(), 1)
        self.assertTrue(self.db.delete_archive(entry))
        self.assertEqual(self.db.archive_count(), 0)

    def test_personal_notes_roundtrip(self):
        self.db.set_personal_note("Deploy", "Run the checklist")
        self.assertEqual(self.db.get_personal_note("deploy"), "Run the checklist")
        self.assertEqual(len(self.db.list_personal_notes()), 1)
        self.db.set_personal_note("Deploy", "Updated")
        self.assertEqual(self.db.get_personal_note("deploy"), "Updated")
        self.assertTrue(self.db.delete_personal_note("deploy"))
        self.assertFalse(self.db.delete_personal_note("deploy"))

    def test_reminder_lifecycle(self):
        from datetime import datetime, timedelta

        reminder_id = self.db.add_reminder(-1001, 4242, "Stretch", datetime.utcnow() - timedelta(minutes=1))
        due = self.db.due_reminders()
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0]["text"], "Stretch")
        self.assertTrue(self.db.mark_reminder_fired(reminder_id))
        self.assertEqual(self.db.due_reminders(), [])
        self.assertFalse(self.db.cancel_reminder(reminder_id))

    def test_plugin_state_persistence(self):
        self.db.set_plugin_enabled("demo", False)
        self.assertFalse(self.db.get_plugin_enabled("demo"))
        self.db.set_plugin_enabled("demo", True)
        self.assertTrue(self.db.get_plugin_enabled("demo"))
        self.assertIsNone(self.db.get_plugin_enabled("unknown"))

    def test_task_log_is_bounded(self):
        for index in range(205):
            self.db.log_task(f"t{index}", "sticker", "sticker", "completed", 0.1)
        rows = self.db.recent_tasks(limit=300)
        self.assertLessEqual(len(rows), 200)


class RouterTests(unittest.TestCase):
    def setUp(self):
        self.router = CommandRouter(default_prefix=".")

    def test_registration_aliases_and_duplicates(self):
        @self.router.register(name="ping", aliases=["p"])
        async def ping(ctx):
            return "pong"

        self.assertIsNotNone(self.router.resolve("p"))
        self.assertEqual(self.router.resolve("p").name, "ping")
        with self.assertRaises(DuplicateCommandError):
            self.router.register(name="ping")(ping)
        with self.assertRaises(DuplicateCommandError):
            self.router.register(name="other", aliases=["p"])(ping)
        with self.assertRaises(Exception):
            self.router.register(name="Bad Name")(ping)

    def test_dispatch_alias_and_unknown(self):
        calls = []

        @self.router.register(name="hello", aliases=["hi"])
        async def hello(ctx):
            calls.append(ctx.command_name)
            await ctx.reply("ok")

        ctx_message = support.DummyMessage(text=".hi there")
        support.run(self.router.handle_message(ctx_message, support.DummyClient()))
        self.assertEqual(calls, ["hello"])
        self.assertEqual(ctx_message.replies, ["ok"])

        unknown = support.DummyMessage(text=".nope")
        support.run(self.router.handle_message(unknown, support.DummyClient()))
        self.assertIn("not a registered command", unknown.replies[0])

    def test_long_reply_is_split(self):
        @self.router.register(name="long")
        async def long_cmd(ctx):
            await ctx.reply("line\n" * 3000)

        message = support.DummyMessage(text=".long")
        support.run(self.router.handle_message(message, support.DummyClient()))
        self.assertGreater(len(message.replies), 1)
        for chunk in message.replies:
            self.assertLessEqual(len(chunk), 4096)

    def test_owner_only_denied_silently(self):
        calls = []

        @self.router.register(name="secret", owner_only=True)
        async def secret(ctx):
            calls.append(1)
            await ctx.reply("done")

        message = support.DummyMessage(text=".secret", sender_id=1)
        support.run(self.router.handle_message(message, support.DummyClient()))
        self.assertEqual(calls, [])
        self.assertEqual(message.replies, [])
        self.assertEqual(self.router.denied_count, 1)

    def test_owner_allowed(self):
        calls = []

        @self.router.register(name="secret", owner_only=True)
        async def secret(ctx):
            calls.append(1)
            await ctx.reply("done")

        message = support.DummyMessage(text=".secret", sender_id=4242)
        support.run(self.router.handle_message(message, support.DummyClient()))
        self.assertEqual(calls, [1])

    def test_cooldown_blocks_second_call(self):
        @self.router.register(name="slow", cooldown=60)
        async def slow(ctx):
            await ctx.reply("ran")

        first = support.DummyMessage(text=".slow")
        support.run(self.router.handle_message(first, support.DummyClient()))
        second = support.DummyMessage(text=".slow")
        support.run(self.router.handle_message(second, support.DummyClient()))
        self.assertEqual(first.replies, ["ran"])
        self.assertIn("again in 60s", second.replies[0])

    def test_handler_exception_is_reported_not_raised(self):
        @self.router.register(name="boom")
        async def boom(ctx):
            raise RuntimeError("exploded")

        message = support.DummyMessage(text=".boom")
        support.run(self.router.handle_message(message, support.DummyClient()))
        self.assertIn("failed", message.replies[0].lower())
        self.assertEqual(self.router.errors_count, 1)

    def test_categories_and_search(self):
        @self.router.register(name="alpha", category="Demo", description="first command")
        async def alpha(ctx):
            return None

        self.assertIn("Demo", self.router.categories())
        self.assertEqual([c.name for c in self.router.search("first")], ["alpha"])


class ModerationHelperTests(unittest.TestCase):
    def test_link_detection(self):
        self.assertTrue(contains_link("see https://telegram.org"))
        self.assertTrue(contains_link("join t.me/example"))
        self.assertFalse(contains_link("no links here"))

    def test_greeting_formatting(self):
        from reze.database import db

        chat_id = -1004321
        db.update_group_settings(
            chat_id, welcome_enabled=1, welcome_text="Welcome {mention} to {title}!"
        )
        text = format_welcome_message(chat_id, "Ali", 5, "Reze Group")
        self.assertIn("Ali", text)
        self.assertIn("Reze Group", text)
        self.assertIn("tg://user?id=5", text)
        self.assertIsNone(format_welcome_message(-1009999, "Ali", 5, "Other"))

    def test_antiflood_tracker(self):
        import reze.modules.antiflood as antiflood_module

        tracker = AntiFloodTracker()
        chat_id, user_id = -10099, 555
        database = Database(os.path.join(support.TEST_DATA_DIR, "flood.db"))
        database.update_group_settings(chat_id, antiflood_enabled=1, antiflood_limit=3, antiflood_seconds=5)
        original = antiflood_module.db
        antiflood_module.db = database
        try:
            self.assertFalse(tracker.record_and_check(chat_id, user_id)[0])
            self.assertFalse(tracker.record_and_check(chat_id, user_id)[0])
            flooded, action = tracker.record_and_check(chat_id, user_id)
            self.assertTrue(flooded)
            self.assertEqual(action, "mute")
        finally:
            antiflood_module.db = original

    def test_message_filters(self):
        import reze.modules.filters as filters_module

        database = Database(os.path.join(support.TEST_DATA_DIR, "filters.db"))
        chat_id = -10055
        database.set_filter(chat_id, "hello", "Hi!")
        database.add_blacklist(chat_id, "scam")
        original = filters_module.db
        filters_module.db = database
        try:
            self.assertEqual(check_message_filters(chat_id, "well hello there"), "Hi!")
            self.assertIsNone(check_message_filters(chat_id, "nothing"))
            self.assertEqual(check_blacklists(chat_id, "this is a SCAM")[0], "scam")
        finally:
            filters_module.db = original


if __name__ == "__main__":
    unittest.main()
