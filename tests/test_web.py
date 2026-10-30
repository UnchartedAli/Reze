"""Web panel tests: authentication, CSRF, headers, escaping and real state."""

import json
import re
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import support

from reze.config import settings
from reze.database import db
from reze.web.app import RezePanelHandler

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class PanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RezePanelHandler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

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
        payload = response.read().decode("utf-8", errors="replace")
        return response, payload

    def login(self):
        response, _ = self.request(
            "/login", "POST", {"username": "admin", "password": "test-password"}
        )
        self.assertIn(response.status, (302, 303))
        cookie_header = response.headers.get("Set-Cookie", "")
        self.assertIn("reze_session=", cookie_header)
        return cookie_header.split(";")[0]

    def test_health_endpoint_is_public_and_clean(self):
        response, body = self.request("/healthz")
        self.assertEqual(response.status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["status"], "ok")
        self.assertNotIn("api_hash", body.lower())
        self.assertNotIn("session_string", body.lower())
        self.assertNotIn("password", body.lower())

    def test_unauthenticated_redirect_and_security_headers(self):
        response, _ = self.request("/")
        self.assertEqual(response.status, 302)
        self.assertEqual(response.headers.get("Location"), "/login")
        self.assertIn("frame-ancestors 'none'", response.headers.get("Content-Security-Policy"))
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("Cache-Control"), "no-store")

    def test_wrong_password_is_rejected(self):
        response, body = self.request("/login", "POST", {"username": "admin", "password": "nope"})
        self.assertEqual(response.status, 200)
        self.assertIn("Invalid username or password", body)
        self.assertNotIn("Set-Cookie", str(response.headers))

    def test_login_then_dashboard(self):
        cookie = self.login()
        response, body = self.request("/", cookie=cookie)
        self.assertEqual(response.status, 200)
        self.assertIn("Dashboard", body)
        self.assertIn(str(db.get_stats()["archive"]), body)
        # The panel must never render secrets.
        self.assertNotIn(settings.panel_password, body)

    def test_csrf_required_for_state_changes(self):
        cookie = self.login()
        response, body = self.request("/settings/save", "POST", {"theme": "GHOST"}, cookie=cookie)
        self.assertEqual(response.status, 403)
        self.assertIn("CSRF", body)
        from reze.preferences import get_pref

        self.assertNotEqual(get_pref("theme"), "GHOST")

    def test_csrf_protected_settings_save(self):
        cookie = self.login()
        _, settings_page = self.request("/settings", cookie=cookie)
        match = CSRF_RE.search(settings_page)
        self.assertIsNotNone(match)
        token = match.group(1)

        response, _ = self.request(
            "/settings/save",
            "POST",
            {"csrf_token": token, "theme": "GHOST", "prefix": ".", "log_level": "INFO"},
            cookie=cookie,
        )
        self.assertEqual(response.status, 302)
        from reze.preferences import get_pref, set_pref

        self.assertEqual(get_pref("theme"), "GHOST")
        set_pref("theme", "CYBER")

    def test_invalid_setting_is_rejected_with_400(self):
        cookie = self.login()
        _, settings_page = self.request("/settings", cookie=cookie)
        token = CSRF_RE.search(settings_page).group(1)
        response, body = self.request(
            "/settings/save",
            "POST",
            {"csrf_token": token, "theme": "NEON", "prefix": "."},
            cookie=cookie,
        )
        self.assertEqual(response.status, 400)
        self.assertIn("rejected", body.lower())

    def test_html_escaping_of_stored_content(self):
        cookie = self.login()
        db.set_personal_note("xss", "<script>alert(1)</script>")
        try:
            _, body = self.request("/productivity", cookie=cookie)
            self.assertNotIn("<script>alert(1)</script>", body)
            self.assertIn("&lt;script&gt;", body)
        finally:
            db.delete_personal_note("xss")

    def test_api_status_requires_authentication(self):
        response, _ = self.request("/api/status")
        self.assertEqual(response.status, 302)
        cookie = self.login()
        response, body = self.request("/api/status", cookie=cookie)
        self.assertEqual(response.status, 200)
        payload = json.loads(body)
        self.assertIn("version", payload)
        self.assertIn("telegram", payload)

    def test_logout_invalidates_session(self):
        cookie = self.login()
        _, dashboard = self.request("/", cookie=cookie)
        token = CSRF_RE.search(dashboard).group(1)
        response, _ = self.request("/logout", "POST", {"csrf_token": token}, cookie=cookie)
        self.assertEqual(response.status, 302)
        response, _ = self.request("/", cookie=cookie)
        self.assertEqual(response.status, 302)

    def test_optional_features_page_and_sensitive_toggle(self):
        from reze.features import features

        features.disable("vault")
        try:
            cookie = self.login()
            _, settings_page = self.request("/settings", cookie=cookie)
            self.assertIn("Optional features", settings_page)
            self.assertIn("vault", settings_page)
            self.assertIn("OFF", settings_page)
            token = CSRF_RE.search(settings_page).group(1)

            # Sensitive features need the explicit confirmation checkbox.
            response, _ = self.request(
                "/features/toggle",
                "POST",
                {"csrf_token": token, "key": "vault", "action": "enable"},
                cookie=cookie,
            )
            self.assertEqual(response.status, 302)
            self.assertFalse(features.is_enabled("vault"))

            response, _ = self.request(
                "/features/toggle",
                "POST",
                {"csrf_token": token, "key": "vault", "action": "enable", "confirm": "1"},
                cookie=cookie,
            )
            self.assertEqual(response.status, 302)
            self.assertTrue(features.is_enabled("vault"))

            response, _ = self.request(
                "/features/toggle",
                "POST",
                {"csrf_token": token, "key": "vault", "action": "disable"},
                cookie=cookie,
            )
            self.assertEqual(response.status, 302)
            self.assertFalse(features.is_enabled("vault"))
        finally:
            features.disable("vault")

    def test_plugin_and_task_pages_render(self):
        cookie = self.login()
        for path in ("/plugins", "/tasks", "/automations", "/groups", "/filters", "/security", "/profile", "/logs"):
            response, body = self.request(path, cookie=cookie)
            self.assertEqual(response.status, 200, f"{path} returned {response.status}")
            self.assertIn("REZE", body)

    def test_injection_in_query_is_escaped(self):
        cookie = self.login()
        response, body = self.request("/logs?level=%3Cscript%3E", cookie=cookie)
        self.assertEqual(response.status, 200)
        self.assertNotIn("<script>", body)


import urllib.parse  # noqa: E402  (used by the request helper)


if __name__ == "__main__":
    unittest.main()
