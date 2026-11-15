"""REZE 4.0: Style Assistant web panel. Logic first, then real HTTP requests."""

import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import support  # noqa: F401  - prepares the database before reze imports

from reze.database import db
from reze.features import features
from reze.style import panel, store
from reze.web import auth
from reze.web import pages
from reze.web.app import RezePanelHandler
from reze.web.theme import esc

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _form(**fields):
    return {key: [value] for key, value in fields.items()}


def _reset():
    db.execute("DELETE FROM style_samples")
    db.execute("DELETE FROM style_drafts")
    db.execute("DELETE FROM style_auto_log")
    db.execute("DELETE FROM style_auto_chats")
    db.execute("UPDATE style_profile SET profile = '{}', sample_count = 0, updated_at = NULL WHERE id = 1")
    db.execute(
        "UPDATE style_settings SET auto_enabled = 0, quiet_start = '', quiet_end = '', timezone = 'UTC', "
        "cooldown_hours = 6, hourly_cap = 10, owner_active_minutes = 30, language = 'en' WHERE id = 1"
    )


class PanelLogicTests(unittest.TestCase):
    def setUp(self):
        _reset()
        self._was_on = features.is_enabled("style_assistant")

    def tearDown(self):
        _reset()
        if features.is_enabled("style_assistant") and not self._was_on:
            features.disable("style_assistant", actor=4242)

    def test_valid_settings_are_saved(self):
        panel.save_settings(_form(quiet_start="23:00", quiet_end="07:00", timezone="Asia/Tehran",
                                  cooldown_hours="4", hourly_cap="5", owner_active_minutes="45", language="fa"))
        cfg = store.get_settings()
        self.assertEqual((cfg["quiet_start"], cfg["quiet_end"], cfg["timezone"]), ("23:00", "07:00", "Asia/Tehran"))
        self.assertEqual((cfg["cooldown_hours"], cfg["hourly_cap"], cfg["owner_active_minutes"], cfg["language"]),
                         (4, 5, 45, "fa"))

    def test_invalid_settings_are_refused_with_a_reason(self):
        cases = [
            (_form(quiet_start="23:00", quiet_end=""), "both quiet hour"),
            (_form(cooldown_hours="0"), "Cooldown"),
            (_form(hourly_cap="500"), "Hourly cap"),
            (_form(owner_active_minutes="99999"), "Owner-active"),
            (_form(language="de"), "Language"),
            (_form(timezone="Nowhere/Land"), "Unknown timezone"),
        ]
        for form, expected in cases:
            with self.subTest(form=form):
                with self.assertRaisesRegex(ValueError, expected):
                    panel.save_settings(form)

    def test_auto_switch_accepts_only_on_or_off(self):
        panel.set_auto("on")
        self.assertTrue(store.get_settings()["auto_enabled"])
        panel.set_auto("off")
        self.assertFalse(store.get_settings()["auto_enabled"])
        with self.assertRaises(ValueError):
            panel.set_auto("maybe")

    def test_removing_a_chat_from_the_allow_list(self):
        store.allow_chat(5551, "Friend")
        with self.assertRaises(ValueError):
            panel.block_chat("not-a-number")
        panel.block_chat("5551")
        self.assertIsNone(store.allowed_chat(5551))

    def test_forget_needs_the_explicit_confirmation(self):
        store.add_samples(5551, [(1, "keep until confirmed")], __import__("datetime").datetime(2026, 11, 13))
        with self.assertRaises(ValueError):
            panel.forget("no")
        self.assertEqual(store.sample_count(), 1)
        panel.forget("yes")
        self.assertEqual(store.sample_count(), 0)

    def test_state_reports_the_real_feature_flag(self):
        features.disable("style_assistant", actor=4242) if features.is_enabled("style_assistant") else None
        self.assertFalse(panel.build_state()["feature_on"])


class PageTests(unittest.TestCase):
    def state(self, **overrides):
        base = {
            "feature_on": True,
            "settings": {"auto_enabled": False, "quiet_start": "", "quiet_end": "", "timezone": "UTC",
                         "cooldown_hours": 6, "hourly_cap": 10, "owner_active_minutes": 30, "language": "en"},
            "samples": 12,
            "profile_lines": ["Median length: 6 words"],
            "allowed": [],
            "drafts": [],
            "replies_24h": 0,
            "message": "",
            "error": "",
        }
        base.update(overrides)
        return base

    def test_english_and_persian_pages_render(self):
        self.assertIn("Style Assistant", pages.style_page(self.state(), "tok", "en"))
        self.assertIn("دستیار سبک نوشتن", pages.style_page(self.state(), "tok", "fa"))

    def test_draft_text_is_escaped(self):
        drafts = [{"id": 1, "chat_id": 5551, "reply_to_id": 9, "draft": "<script>alert(1)</script>", "created_at": "2026-11-13"}]
        html = pages.style_page(self.state(drafts=drafts), "tok", "en")
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_every_post_form_carries_the_csrf_token(self):
        html = pages.style_page(self.state(allowed=[{"chat_id": 1, "title": "A", "last_reply_at": None}]), "tok", "en")
        posts = len(re.findall(r'method="POST"', html))
        tokens = len(re.findall(r'name="csrf_token" value="tok"', html))
        self.assertGreater(posts, 0)
        self.assertEqual(posts, tokens)

    def test_the_panel_offers_no_control_that_needs_telegram(self):
        html = pages.style_page(self.state(), "tok", "en")
        self.assertNotIn('action="/style/allow"', html)
        self.assertNotIn('action="/style/learn"', html)
        self.assertNotIn('action="/style/send"', html)
        self.assertIn(".style learn", html, "the command is shown as the way to do it")


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth.ACTIVE_SESSIONS.clear()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RezePanelHandler)
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        auth.ACTIVE_SESSIONS.clear()

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def request(self, path, method="GET", data=None, cookie=None):
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method)
        if cookie:
            req.add_header("Cookie", cookie)

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        try:
            response = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        return response, response.read().decode("utf-8", errors="replace")

    def login(self):
        response, _ = self.request("/login", "POST", {"username": "admin", "password": "test-password"})
        return response.headers.get("Set-Cookie", "").split(";")[0]

    def token(self, cookie):
        _, page = self.request("/style", cookie=cookie)
        return CSRF_RE.search(page).group(1)

    def test_page_loads_for_a_signed_in_owner(self):
        cookie = self.login()
        response, page = self.request("/style", cookie=cookie)
        self.assertEqual(response.status, 200)
        self.assertIn("Style Assistant", page)

    def test_signed_out_visitors_are_redirected(self):
        response, _ = self.request("/style")
        self.assertIn(response.status, (302, 303))

    def test_settings_save_through_the_real_route(self):
        cookie = self.login()
        token = self.token(cookie)
        response, _ = self.request(
            "/style/settings", "POST",
            {"csrf_token": token, "quiet_start": "", "quiet_end": "", "timezone": "UTC",
             "cooldown_hours": "3", "hourly_cap": "7", "owner_active_minutes": "30", "language": "en"},
            cookie=cookie,
        )
        self.assertIn(response.status, (302, 303))
        self.assertEqual(store.get_settings()["cooldown_hours"], 3)

    def test_post_without_csrf_is_refused_and_changes_nothing(self):
        cookie = self.login()
        store.set_setting("hourly_cap", 10)
        response, _ = self.request("/style/settings", "POST", {"hourly_cap": "1"}, cookie=cookie)
        self.assertNotIn(response.status, (302, 303))
        self.assertEqual(store.get_settings()["hourly_cap"], 10)

    def test_forget_without_confirmation_keeps_data(self):
        from datetime import datetime

        cookie = self.login()
        store.add_samples(5551, [(1, "still here")], datetime(2026, 11, 13))
        token = self.token(cookie)
        self.request("/style/forget", "POST", {"csrf_token": token}, cookie=cookie)
        self.assertEqual(store.sample_count(), 1)


if __name__ == "__main__":
    unittest.main()
