"""REZE 4.0: Channel Digest web panel, plus the run request from the panel to the loop."""

import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer

import support  # noqa: F401  - prepares the database before reze imports

from reze.database import db
from reze.digest import panel, store
from reze.digest.service import DigestService
from reze.features import features
from reze.web import auth
from reze.web import pages
from reze.web.app import RezePanelHandler
from reze.web.theme import esc

import test_reze4_digest as digest_tests

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
CH = digest_tests.CH_A
T_EVENING = datetime(2026, 11, 13, 21, 5)
T_MORNING = datetime(2026, 11, 13, 9, 0)


def _form(**fields):
    return {key: [value] for key, value in fields.items()}


class PanelLogicTests(digest_tests.DigestCase):
    def setUp(self):
        super().setUp()
        self._was_on = features.is_enabled("channel_digest")
        features.enable("channel_digest", actor=digest_tests.OWNER, confirmed=True)

    def tearDown(self):
        if features.is_enabled("channel_digest") and not self._was_on:
            features.disable("channel_digest", actor=digest_tests.OWNER)
        super().tearDown()

    def test_settings_are_validated_and_saved(self):
        panel.save_settings(_form(time_of_day="20:30", timezone="Asia/Tehran", schedule="custom",
                                  days="mon,thu", max_messages="50", max_chars="8000", language="fa"))
        cfg = store.get_config()
        self.assertEqual((cfg["time_of_day"], cfg["timezone"], cfg["schedule"], cfg["days"]), ("20:30", "Asia/Tehran", "custom", "0,3"))
        self.assertEqual((cfg["max_messages"], cfg["max_chars"], cfg["language"]), (50, 8000, "fa"))
        for bad, expected in [
            (_form(time_of_day="25:00"), "24-hour"),
            (_form(timezone="Mars/Base"), "Unknown timezone"),
            (_form(schedule="weekly", days="mon,fri"), "exactly one day"),
            (_form(max_messages="999"), "between"),
            (_form(language="de"), "en or fa"),
        ]:
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, expected):
                    panel.save_settings(bad)

    def test_switches_accept_only_known_names(self):
        panel.toggle("ai_enabled", "on")
        self.assertTrue(store.get_config()["ai_enabled"])
        with self.assertRaises(ValueError):
            panel.toggle("everything", "on")

    def test_channel_edits_and_removal(self):
        store.add_channel(CH, "Alpha", "alpha", 10, T_MORNING)
        panel.update_channel(_form(chat_id=str(CH), priority="2", include_keywords="rate, bitcoin",
                                   exclude_keywords="spam", enabled="1"))
        row = store.get_channel(CH)
        self.assertEqual((row["priority"], row["include_keywords"], row["exclude_keywords"], row["enabled"]),
                         (2, "rate,bitcoin", "spam", True))
        panel.update_channel(_form(chat_id=str(CH), priority="5"))  # unchecked box: not sent
        self.assertFalse(store.get_channel(CH)["enabled"])
        with self.assertRaises(ValueError):
            panel.update_channel(_form(chat_id=str(CH + 1), priority="2"))
        with self.assertRaises(ValueError):
            panel.update_channel(_form(chat_id=str(CH), priority="99"))
        panel.remove_channel(_form(chat_id=str(CH)))
        self.assertIsNone(store.get_channel(CH))

    def test_run_request_needs_the_digest_on_and_is_taken_once(self):
        store.set_toggle("enabled", False)
        with self.assertRaisesRegex(ValueError, "on first"):
            panel.request_run()
        store.set_toggle("enabled", True)
        panel.request_run()
        self.assertTrue(store.take_run_request())
        self.assertFalse(store.take_run_request(), "a request is consumed once")

    def test_history_deletion_needs_confirmation(self):
        run = store.create_run("k-panel", "scheduled", T_MORNING)
        with self.assertRaises(ValueError):
            panel.clear_history("no")
        self.assertIsNotNone(store.get_run(run))
        panel.clear_history("yes")
        self.assertIsNone(store.get_run(run))

    def test_search_filters_the_channel_list(self):
        store.add_channel(CH, "Market Watch", "market", 10, T_MORNING)
        store.add_channel(CH + 1, "Cooking", "food", 10, T_MORNING)
        state = panel.build_state({"q": ["market"]})
        self.assertEqual([c["title"] for c in state["channels"]], ["Market Watch"])
        self.assertEqual(state["channel_total"], 2)


class RunRequestThroughTheLoopTests(digest_tests.DigestCase):
    def setUp(self):
        super().setUp()
        self._was_on = features.is_enabled("channel_digest")
        features.enable("channel_digest", actor=digest_tests.OWNER, confirmed=True)

    def tearDown(self):
        if features.is_enabled("channel_digest") and not self._was_on:
            features.disable("channel_digest", actor=digest_tests.OWNER)
        super().tearDown()

    def test_panel_request_sends_a_digest_even_while_paused(self):
        self.configure()
        store.set_toggle("paused", True)
        self.select(CH, "Alpha", 10)
        client = digest_tests.FakeClient({CH: [digest_tests.post(11, "panel asked for this")]})
        svc = self.service(client)
        self.assertEqual(digest_tests.asyncio_run(svc.tick(T_MORNING))["status"], "paused")
        self.assertEqual(client.sent, [])
        panel.request_run()
        result = digest_tests.asyncio_run(svc.tick(T_MORNING))
        self.assertEqual(result["status"], "sent")
        self.assertEqual(store.list_runs(limit=1)[0]["kind"], "manual")
        self.assertIn("panel asked for this", self.sent_text(client))
        self.assertFalse(store.take_run_request(), "the request was consumed")


class PageTests(unittest.TestCase):
    def state(self, **overrides):
        base = {
            "feature_on": True,
            "config": {"enabled": True, "paused": False, "ai_enabled": False, "time_of_day": "21:00",
                       "timezone": "UTC", "schedule": "daily", "days": "0,1,2,3,4,5,6",
                       "max_messages": 200, "max_chars": 12000, "language": "en"},
            "next_slot": "2026-11-13 21:00 (UTC)",
            "last_run": None,
            "pending": 0,
            "channels": [],
            "search": "",
            "channel_total": 0,
            "runs": [],
            "message": "",
            "error": "",
        }
        base.update(overrides)
        return base

    def test_both_languages_render(self):
        self.assertIn("Channel Digest", pages.digest_page(self.state(), "tok", "en"))
        self.assertIn("خلاصهٔ کانال‌ها", pages.digest_page(self.state(), "tok", "fa"))

    def test_feature_off_offers_the_enable_form_with_confirmation(self):
        html = pages.digest_page(self.state(feature_on=False), "tok", "en")
        self.assertIn('action="/features/toggle"', html)
        self.assertIn('name="key" value="channel_digest"', html)
        self.assertIn('name="confirm" value="yes"', html)

    def test_channel_titles_are_escaped(self):
        channels = [{"chat_id": 1, "title": "<img src=x onerror=alert(1)>", "username": "", "priority": 5,
                     "include_keywords": "", "exclude_keywords": "", "enabled": True, "last_synced_at": None}]
        html = pages.digest_page(self.state(channels=channels, channel_total=1), "tok", "en")
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;img src=x", html)

    def test_every_post_form_carries_the_csrf_token(self):
        channels = [{"chat_id": 1, "title": "A", "username": "a", "priority": 5, "include_keywords": "",
                     "exclude_keywords": "", "enabled": True, "last_synced_at": None}]
        html = pages.digest_page(self.state(channels=channels, channel_total=1), "tok", "en")
        self.assertEqual(len(re.findall(r'method="POST"', html)), len(re.findall(r'name="csrf_token" value="tok"', html)))

    def test_no_control_offers_telegram_only_actions(self):
        html = pages.digest_page(self.state(), "tok", "en")
        self.assertNotIn('action="/digest/add"', html)
        self.assertIn(".digest add", html)


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
        digest_tests._reset_digest_tables()

    def tearDown(self):
        digest_tests._reset_digest_tables()

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
        _, page = self.request("/digest", cookie=cookie)
        return CSRF_RE.search(page).group(1)

    def test_page_loads(self):
        cookie = self.login()
        response, page = self.request("/digest", cookie=cookie)
        self.assertEqual(response.status, 200)
        self.assertIn("Channel Digest", page)

    def test_run_request_refused_while_off_shows_a_reason(self):
        cookie = self.login()
        token = self.token(cookie)
        response, _ = self.request("/digest/run", "POST", {"csrf_token": token}, cookie=cookie)
        location = response.headers.get("Location", "")
        self.assertIn("/digest?err=", location)
        self.assertFalse(store.take_run_request())

    def test_post_without_csrf_changes_nothing(self):
        cookie = self.login()
        store.set_toggle("enabled", False)
        response, _ = self.request("/digest/toggle", "POST", {"name": "enabled", "value": "on"}, cookie=cookie)
        self.assertNotIn(response.status, (302, 303))
        self.assertFalse(store.get_config()["enabled"])

    def test_clear_history_without_confirmation_keeps_runs(self):
        cookie = self.login()
        run = store.create_run("k-http", "scheduled", T_MORNING)
        token = self.token(cookie)
        self.request("/digest/clear", "POST", {"csrf_token": token}, cookie=cookie)
        self.assertIsNotNone(store.get_run(run))


if __name__ == "__main__":
    unittest.main()
