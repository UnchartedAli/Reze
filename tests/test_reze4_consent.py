"""REZE 4.0: consent for sharing data with the Watchdog bot, and consent-gated summaries."""

import asyncio
import json
import os
import re
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace
from unittest import mock

import support  # noqa: F401  - prepares the shared database before reze imports

from reze import consent
from reze.commands import consent as consent_cmd_module
from reze.commands import watchdog as watchdog_cmd_module
from reze.config import settings
from reze.integrations import watchdog
from reze.storage import secret_store
from reze.web import auth
from reze.web.app import RezePanelHandler

OWNER = 4242
SCOPE = "watchdog.channel_posts"
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def run(coro):
    return asyncio.run(coro)


class ConsentCase(unittest.TestCase):
    def setUp(self):
        self._vault = settings.vault_key
        self._owner = settings.owner_id
        settings.vault_key = "consent-tests-vault-key-0123456789abcdef"
        settings.owner_id = OWNER
        consent.revoke(SCOPE)
        secret_store.forget(watchdog.BRIDGE_SECRET)

    def tearDown(self):
        consent.revoke(SCOPE)
        secret_store.forget(watchdog.BRIDGE_SECRET)
        settings.vault_key = self._vault
        settings.owner_id = self._owner


class RuleTests(ConsentCase):
    def test_consent_is_off_by_default(self):
        self.assertFalse(consent.is_granted(SCOPE))

    def test_sharing_is_refused_without_consent_with_a_clear_reason(self):
        with self.assertRaisesRegex(consent.ConsentRequired, "Grant it in the Reze panel"):
            consent.require(SCOPE)

    def test_grant_and_revoke(self):
        consent.grant(SCOPE)
        consent.require(SCOPE)
        self.assertTrue(consent.is_granted(SCOPE))
        consent.revoke(SCOPE)
        self.assertFalse(consent.is_granted(SCOPE))
        with self.assertRaises(consent.ConsentRequired):
            consent.require(SCOPE)

    def test_unknown_scopes_are_rejected(self):
        with self.assertRaises(consent.ConsentError):
            consent.grant("everything.everywhere")
        with self.assertRaises(consent.ConsentError):
            consent.is_granted("everything.everywhere")

    def test_status_lists_every_scope_with_its_state(self):
        consent.grant(SCOPE)
        rows = {row["scope"]: row for row in consent.status()}
        self.assertTrue(rows[SCOPE]["granted"])
        self.assertIn("label_fa", rows[SCOPE])


class VerifySummaryTests(unittest.TestCase):
    def test_lines_with_numbers_the_posts_do_not_contain_are_removed(self):
        text, removed = watchdog.verify_summary("• Launch on 2026-11-20\n• Price 999 USD", ["Launch on 2026-11-20"])
        self.assertEqual(removed, 1)
        self.assertEqual(text, "• Launch on 2026-11-20")

    def test_lines_without_numbers_are_kept(self):
        text, removed = watchdog.verify_summary("• The author is worried about the plan.", ["any post"])
        self.assertEqual(removed, 0)
        self.assertIn("worried", text)


class SummaryClientTests(ConsentCase):
    def posts(self, n=2):
        return [{"channel": "News", "date": "2026-11-13 09:00", "text": f"Launch on 2026-11-20 post {i}"} for i in range(n)]

    def test_no_request_is_made_without_consent(self):
        secret_store.store(watchdog.BRIDGE_SECRET, "b" * 40)
        with mock.patch.object(watchdog, "_post_summary") as post:
            with self.assertRaises(consent.ConsentRequired):
                run(watchdog.summarize_posts(self.posts()))
            post.assert_not_called()

    def test_with_consent_the_summary_comes_back_checked(self):
        consent.grant(SCOPE)
        secret_store.store(watchdog.BRIDGE_SECRET, "b" * 40)
        reply = {"ok": True, "summary": "• Launch on 2026-11-20\n• Price 999 USD", "posts": 2}
        with mock.patch.object(watchdog, "_post_summary", return_value=reply) as post:
            result = run(watchdog.summarize_posts(self.posts()))
        self.assertEqual(result["removed"], 1)
        self.assertIn("2026-11-20", result["summary"])
        self.assertNotIn("999", result["summary"])
        body = post.call_args[0][1]
        self.assertIn(b"Launch on 2026-11-20 post 0", body)

    def test_nothing_is_sent_without_the_bridge_secret(self):
        consent.grant(SCOPE)
        with self.assertRaisesRegex(watchdog.WatchdogError, "bridge secret"):
            run(watchdog.summarize_posts(self.posts()))

    def test_too_many_posts_is_refused_before_sending(self):
        consent.grant(SCOPE)
        secret_store.store(watchdog.BRIDGE_SECRET, "b" * 40)
        with mock.patch.object(watchdog, "_post_summary") as post:
            with self.assertRaisesRegex(watchdog.WatchdogError, "at most"):
                run(watchdog.summarize_posts(self.posts(watchdog.MAX_POSTS + 1)))
            post.assert_not_called()

    def test_worker_errors_become_plain_messages(self):
        consent.grant(SCOPE)
        secret_store.store(watchdog.BRIDGE_SECRET, "b" * 40)
        error = urllib.error.HTTPError("u", 503, "x", {}, None)
        error.read = lambda: b'{"ok": false, "error": "ai_not_configured"}'
        with mock.patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(watchdog.WatchdogError, "no AI key"):
                watchdog._post_summary("b" * 40, b"{}")

    def test_the_log_never_contains_the_post_text_or_the_secret(self):
        consent.grant(SCOPE)
        secret_store.store(watchdog.BRIDGE_SECRET, "b" * 40)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
            with self.assertLogs("reze", level="WARNING") as logged:
                with self.assertRaises(watchdog.WatchdogError):
                    run(watchdog.summarize_posts(self.posts()))
        joined = " ".join(logged.output)
        self.assertNotIn("Launch on 2026-11-20", joined)
        self.assertNotIn("b" * 40, joined)


class FakeCtx:
    def __init__(self, args, sender_id=OWNER, client=None):
        self.args = args
        self.sender_id = sender_id
        self.client = client
        self.replies = []

    async def reply(self, text=""):
        self.replies.append(str(text))
        return str(text)

    async def reply_usage(self, note=""):
        self.replies.append("USAGE " + str(note))
        return note


def flat(text):
    cleaned = "".join(ch if ch not in "╔╗╚╝║═╠╣─│" else " " for ch in text)
    return " ".join(cleaned.upper().split())


class FakeClient:
    def __init__(self, messages):
        self._messages = messages
        self.sent = []

    async def get_entity(self, target):
        return SimpleNamespace(id=7, title="Market News", username="market")

    async def iter_messages(self, entity, limit=None):
        for message in self._messages[: limit or len(self._messages)]:
            yield message

    async def send_message(self, target, text):
        self.sent.append((target, text))


def msg(text, day=13):
    from datetime import datetime, timezone
    return SimpleNamespace(message=text, date=datetime(2026, 11, day, 9, 0, tzinfo=timezone.utc))


class CommandTests(ConsentCase):
    def test_consent_command_lists_and_changes_consent(self):
        ctx = FakeCtx([], OWNER)
        run(consent_cmd_module.consent_cmd(ctx))
        self.assertTrue(any(SCOPE in r for r in ctx.replies))
        ctx = FakeCtx(["grant", SCOPE], OWNER)
        run(consent_cmd_module.consent_cmd(ctx))
        self.assertTrue(consent.is_granted(SCOPE))
        ctx = FakeCtx(["revoke", SCOPE], OWNER)
        run(consent_cmd_module.consent_cmd(ctx))
        self.assertFalse(consent.is_granted(SCOPE))

    def test_consent_commands_are_owner_only(self):
        ctx = FakeCtx(["grant", SCOPE], 999)
        run(consent_cmd_module.consent_cmd(ctx))
        self.assertFalse(consent.is_granted(SCOPE))
        self.assertTrue(any("OWNER ONLY" in flat(r) for r in ctx.replies))

    def test_summarize_is_refused_without_consent_and_sends_nothing(self):
        client = FakeClient([msg("Launch on 2026-11-20")])
        ctx = FakeCtx(["summarize", "@market", "5"], OWNER, client=client)
        run(watchdog_cmd_module.watchdog_cmd(ctx))
        self.assertEqual(client.sent, [])
        self.assertTrue(any("CONSENT NEEDED" in flat(r) for r in ctx.replies))

    def test_summarize_with_consent_sends_the_result_to_saved_messages(self):
        consent.grant(SCOPE)
        secret_store.store(watchdog.BRIDGE_SECRET, "b" * 40)
        client = FakeClient([msg("Launch on 2026-11-20"), msg("   "), msg("Price 120 USD", day=14)])
        reply = {"ok": True, "summary": "• Launch on 2026-11-20\n• Price 999 USD", "posts": 2}
        ctx = FakeCtx(["summarize", "@market", "5"], OWNER, client=client)
        with mock.patch.object(watchdog, "_post_summary", return_value=reply):
            run(watchdog_cmd_module.watchdog_cmd(ctx))
        self.assertEqual(client.sent[0][0], "me")
        self.assertIn("2026-11-20", client.sent[0][1])
        self.assertNotIn("999", client.sent[0][1])
        self.assertIn("1 خط حذف شد", client.sent[0][1])
        self.assertTrue(any("SUMMARY SENT" in flat(r) for r in ctx.replies))


class PanelTests(ConsentCase):
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

    def test_the_consent_page_offers_grant_and_revoke_with_csrf(self):
        cookie = self.login()
        response, page = self.request("/consent", cookie=cookie)
        self.assertEqual(response.status, 200)
        self.assertIn("Send channel posts to the Watchdog bot", page)
        self.assertIn('action="/consent/grant"', page)
        token = CSRF_RE.search(page).group(1)
        response, _ = self.request("/consent/grant", "POST", {"csrf_token": token, "scope": SCOPE}, cookie=cookie)
        self.assertIn(response.status, (302, 303))
        self.assertTrue(consent.is_granted(SCOPE))

    def test_a_consent_change_without_csrf_is_refused(self):
        cookie = self.login()
        response, _ = self.request("/consent/grant", "POST", {"scope": SCOPE}, cookie=cookie)
        self.assertNotIn(response.status, (302, 303))
        self.assertFalse(consent.is_granted(SCOPE))

    def test_revoke_from_the_page(self):
        consent.grant(SCOPE)
        cookie = self.login()
        _, page = self.request("/consent", cookie=cookie)
        token = CSRF_RE.search(page).group(1)
        self.request("/consent/revoke", "POST", {"csrf_token": token, "scope": SCOPE}, cookie=cookie)
        self.assertFalse(consent.is_granted(SCOPE))


if __name__ == "__main__":
    unittest.main()
