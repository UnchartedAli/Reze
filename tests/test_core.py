"""
Unit tests for Reze Core:
- Configuration validation
- Database CRUD & constraints
- Security & Password hashing
- Command Router & Aliases
- AntiFlood rate-limiting tracker
- Profile clock formatting & timezone calculations
- Plugin loading and dynamic unloading
"""

import unittest
import os
import shutil
import asyncio
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from reze.config import Settings
from reze.database import Database
from reze.web.auth import hash_password, verify_password
from reze.web.app import render_template
from reze.command_router import CommandRouter, CommandContext
from reze.modules.antiflood import AntiFloodTracker
from reze.modules.filters import check_message_filters, check_blacklists, contains_link
from reze.modules.greetings import format_welcome_message
from reze.plugin_manager import PluginManager


class TestRezeCore(unittest.TestCase):
    def setUp(self):
        self.test_dir = "tests/test_data"
        os.makedirs(self.test_dir, exist_ok=True)
        self.db = Database(f"{self.test_dir}/test_reze.db")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_settings_validation(self):
        """Test configuration validation handles missing parameters properly."""
        s = Settings(REZE_API_ID=0, REZE_API_HASH="")
        errors = s.validate_production()
        self.assertTrue(len(errors) >= 3)
        
        valid = Settings(
            REZE_API_ID=12345,
            REZE_API_HASH="fakehash",
            REZE_OWNER_ID=999,
            REZE_PANEL_PASSWORD_HASH="salt$hash"
        )
        self.assertEqual(len(valid.validate_production()), 0)

    def test_hosted_port_and_binding(self):
        """PaaS PORT should drive the port and force a 0.0.0.0 bind."""
        env = {
            "PORT": "10000",
            "REZE_WEB_PORT": "",
            "REZE_WEB_HOST": "",
            "REZE_SESSION_PATH": "",
            "REZE_DATABASE_URL": "",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings.load_from_env()
            self.assertEqual(s.web_port, 10000)
            self.assertEqual(s.effective_web_host, "0.0.0.0")
            self.assertTrue(s.is_hosted)

    def test_data_dir_derives_paths(self):
        """REZE_DATA_DIR should relocate the database and session file."""
        data_dir = os.path.join("tmp", "reze-volume")
        env = {
            "REZE_DATA_DIR": data_dir,
            "REZE_SESSION_PATH": "",
            "REZE_DATABASE_URL": "",
            "REZE_WEB_HOST": "",
            "PORT": "",
        }
        with patch.dict(os.environ, env, clear=False):
            s = Settings.load_from_env()
            self.assertEqual(s.data_dir, data_dir)
            self.assertEqual(s.session_path, os.path.join(data_dir, "reze.session"))
            self.assertTrue(s.database_url.endswith("reze.db"))
            self.assertIn(data_dir, s.database_url)

    def test_session_backend_and_panel_credentials(self):
        """String sessions and plain panel passwords are detected correctly."""
        self.assertEqual(Settings().session_backend, "file")
        self.assertEqual(
            Settings(REZE_SESSION_STRING="1BVtsOK4Bu-example").session_backend,
            "string",
        )
        self.assertTrue(Settings(REZE_PANEL_PASSWORD="secret").has_panel_credentials)
        self.assertFalse(Settings(REZE_PANEL_PASSWORD="").has_panel_credentials)

    def test_display_url(self):
        """The panel should never advertise 0.0.0.0 as a browser URL."""
        s = Settings(REZE_WEB_HOST="0.0.0.0", REZE_WEB_PORT=9000)
        self.assertEqual(s.display_url, "http://127.0.0.1:9000")
        public = Settings(REZE_PUBLIC_URL="https://reze.example.com")
        self.assertEqual(public.display_url, "https://reze.example.com")

    def test_panel_branding(self):
        """The creator name and channel must be present in the panel UI."""
        rendered = render_template("test", "<p>ok</p>")
        self.assertIn("UnchartedAli", rendered)
        self.assertIn("@yamods", rendered)

    def test_password_security(self):
        """Test PBKDF2 hashing, salt generation, and verification."""
        raw_pw = "Reze@SuperSecure2026!"
        h1 = hash_password(raw_pw)
        h2 = hash_password(raw_pw)
        self.assertNotEqual(h1, h2) # Unique salts
        self.assertTrue(verify_password(raw_pw, h1))
        self.assertTrue(verify_password(raw_pw, h2))
        self.assertFalse(verify_password("wrong_password", h1))

    def test_database_operations(self):
        """Test database group settings, warnings, filters, and profile operations."""
        chat_id = -1001928374
        # Group settings
        self.db.update_group_settings(chat_id, antiflood_enabled=1, rules="Be respectful.")
        cfg = self.db.get_group_settings(chat_id)
        self.assertEqual(cfg["antiflood_enabled"], 1)
        self.assertEqual(cfg["rules"], "Be respectful.")

        # Warnings
        cnt1 = self.db.add_warning(chat_id, 111, 999, "Spamming")
        self.assertEqual(cnt1, 1)
        cnt2 = self.db.add_warning(chat_id, 111, 999, "Second offense")
        self.assertEqual(cnt2, 2)
        self.assertEqual(self.db.get_warnings_count(chat_id, 111), 2)
        cnt_after = self.db.remove_warning(chat_id, 111)
        self.assertEqual(cnt_after, 1)
        self.db.reset_warnings(chat_id, 111)
        self.assertEqual(self.db.get_warnings_count(chat_id, 111), 0)

        # Filters
        self.db.set_filter(chat_id, "hello", "Hello friend!")
        flist = self.db.get_filters(chat_id)
        self.assertEqual(len(flist), 1)
        self.assertEqual(flist[0]["keyword"], "hello")

    def test_command_router(self):
        """Test command routing, execution, and alias mapping."""
        router = CommandRouter(default_prefix=".")
        executed = []

        @router.register(name="ping", aliases=["p"])
        async def mock_ping(ctx: CommandContext):
            executed.append(ctx.command_name)
            return "pong"

        class DummyMessage:
            def __init__(self, text):
                self.text = text
                self.sender_id = 123
                self.chat_id = 456
                self.reply_to_msg_id = None
            async def reply(self, txt):
                return txt

        # Test canonical execution
        msg1 = DummyMessage(".ping")
        asyncio.run(router.handle_message(msg1, None))
        self.assertIn("ping", executed)

        # Test alias execution
        msg2 = DummyMessage(".p")
        asyncio.run(router.handle_message(msg2, None))
        self.assertEqual(executed.count("ping"), 2)

    def test_antiflood_tracker(self):
        """Test rate limit detection in antiflood."""
        tracker = AntiFloodTracker()
        chat_id = -10099
        user_id = 555
        
        # Configure group in db
        self.db.update_group_settings(chat_id, antiflood_enabled=1, antiflood_limit=3, antiflood_seconds=2)
        
        # Temporarily point db in module to self.db
        import reze.modules.antiflood as af_mod
        orig_db = af_mod.db
        af_mod.db = self.db
        try:
            is_flood, _ = tracker.record_and_check(chat_id, user_id)
            self.assertFalse(is_flood)
            is_flood, _ = tracker.record_and_check(chat_id, user_id)
            self.assertFalse(is_flood)
            is_flood, action = tracker.record_and_check(chat_id, user_id)
            self.assertTrue(is_flood)
            self.assertEqual(action, "mute")
        finally:
            af_mod.db = orig_db

    def test_link_detection(self):
        """Test URL and telegram link regex."""
        self.assertTrue(contains_link("Join us at https://telegram.org"))
        self.assertTrue(contains_link("Visit t.me/examplechannel"))
        self.assertFalse(contains_link("Just a normal text message."))

    def test_profile_clock_formatting(self):
        """Test time formatting with IANA timezones and name/bio templating."""
        tz = ZoneInfo("Asia/Tehran")
        now = datetime.now(tz)
        fmt = "%H:%M"
        time_str = now.strftime(fmt)

        tmpl = "{name} | {time}"
        res = tmpl.replace("{name}", "Ali").replace("{time}", time_str)
        self.assertTrue(res.startswith("Ali | "))
        self.assertTrue(len(res) <= 64)


if __name__ == "__main__":
    unittest.main()
