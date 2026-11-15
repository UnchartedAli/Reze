"""REZE 4.0 Milestone 2: sign-out-everywhere, backup-encryption warning, UTC helper."""

import re
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from unittest import mock

import support  # noqa: F401  - prepares the database before reze imports

from reze import timeutil
from reze.security import sentinel
from reze.storage.backups.service import backup_service
from reze.web import auth
from reze.web.app import RezePanelHandler

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SessionAuthTests(unittest.TestCase):
    def setUp(self):
        auth.ACTIVE_SESSIONS.clear()

    def tearDown(self):
        auth.ACTIVE_SESSIONS.clear()

    def test_destroy_all_sessions_removes_every_session_and_counts_them(self):
        tokens = [auth.create_session("admin") for _ in range(3)]
        self.assertEqual(auth.destroy_all_sessions(), 3)
        for token in tokens:
            self.assertIsNone(auth.get_session(token))
        self.assertEqual(auth.destroy_all_sessions(), 0)


class SignOutEverywhereHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth.ACTIVE_SESSIONS.clear()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RezePanelHandler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        auth.ACTIVE_SESSIONS.clear()

    def request(self, path, method="GET", data=None, cookie=None):
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        request = urllib.request.Request(self.base + path, data=body, method=method)
        if cookie:
            request.add_header("Cookie", cookie)
        opener = urllib.request.build_opener(NoRedirect)
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        return response, response.read().decode("utf-8", errors="replace")

    def login(self):
        response, _ = self.request("/login", "POST", {"username": "admin", "password": "test-password"})
        self.assertIn(response.status, (302, 303))
        return response.headers.get("Set-Cookie", "").split(";")[0]

    def csrf_for(self, cookie):
        _, page = self.request("/", cookie=cookie)
        match = CSRF_RE.search(page)
        self.assertIsNotNone(match, "dashboard should expose a CSRF token to a signed-in client")
        return match.group(1)

    def test_sign_out_everywhere_ends_other_sessions_too(self):
        first = self.login()
        second = self.login()
        token = self.csrf_for(first)
        response, _ = self.request("/logout-all", "POST", {"csrf_token": token}, cookie=first)
        self.assertIn(response.status, (302, 303))
        response, _ = self.request("/", cookie=second)
        self.assertIn(response.status, (302, 303), "the second session must no longer be accepted")

    def test_sign_out_everywhere_rejects_a_missing_csrf_token(self):
        cookie = self.login()
        response, _ = self.request("/logout-all", "POST", {}, cookie=cookie)
        self.assertNotIn(response.status, (302, 303))
        response, _ = self.request("/", cookie=cookie)
        self.assertEqual(response.status, 200, "a rejected request must not end the session")


class BackupEncryptionWarningTests(unittest.TestCase):
    def _findings(self, rows):
        with mock.patch.object(backup_service, "list", return_value=rows):
            return sentinel._check_backup_encryption()

    def test_warns_when_latest_backup_is_plaintext(self):
        findings = self._findings([{"exists": True, "encrypted": False, "path": "x.db"}])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].check, "backups")
        self.assertEqual(findings[0].severity, "warning")
        self.assertIn("not encrypted", findings[0].title)
        self.assertIn("REZE_VAULT_KEY", findings[0].detail)

    def test_quiet_when_latest_backup_is_encrypted(self):
        self.assertEqual(self._findings([{"exists": True, "encrypted": True, "path": "x.db.enc"}]), [])

    def test_quiet_when_there_are_no_backups_or_the_file_is_gone(self):
        self.assertEqual(self._findings([]), [])
        self.assertEqual(self._findings([{"exists": False, "encrypted": False, "path": "gone.db"}]), [])


class UtcHelperTests(unittest.TestCase):
    def test_utcnow_is_naive_and_close_to_current_utc(self):
        now = timeutil.utcnow()
        self.assertIsNone(now.tzinfo)
        reference = datetime.fromtimestamp(time.time(), timezone.utc).replace(tzinfo=None)
        self.assertLess(abs((reference - now).total_seconds()), 5)


if __name__ == "__main__":
    unittest.main()
