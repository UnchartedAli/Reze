"""
Reze Web Control Panel server.

Dependency-free HTTP server built on the standard library. Every page renders
real backend state, every state-changing request requires a session-bound CSRF
token, and every administrative route is authenticated server-side.

Security posture:
* loopback binding by default (``REZE_WEB_HOST``);
* proxy headers ignored unless ``REZE_WEB_TRUST_PROXY`` is enabled;
* request bodies capped at ``REZE_WEB_MAX_BODY_BYTES``;
* no JavaScript, no inline event handlers, strict CSP;
* logs and diagnostics are redacted by the logging filter and never expose
  sessions, API hashes or keys.
"""

import html
import json
import time
import urllib.parse
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from reze import __version__
from reze.automation.engine import AutomationError, automation_engine
from reze.command_router import router
from reze.config import settings
from reze.core.tasks import task_manager
from reze.database import db
from reze.logging_config import LOG_BUFFER, logger
from reze.media import ffmpeg, images
from reze.plugin_manager import plugin_manager
from reze.preferences import PREFERENCE_KEYS, all_prefs, set_pref
from reze.runtime import run_coroutine
from reze.telegram_client import telegram_manager
from reze.ui.themes import THEMES
from reze.web import pages
from reze.web.auth import (
    check_rate_limit,
    create_session,
    csrf_token_for,
    destroy_session,
    get_session,
    record_failed_login,
    reset_rate_limit,
    validate_csrf,
    verify_password,
)
from reze.web.theme import esc, render_login, render_shell

PANEL_STARTED_AT = time.time()
HEALTH_PATHS = {"/health", "/healthz", "/livez", "/readyz"}
SESSION_COOKIE = "reze_session"
CSP = (
    "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


class RezePanelHandler(BaseHTTPRequestHandler):
    server_version = f"Reze/{__version__}"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------------ helpers
    def log_message(self, fmt, *args):  # route access logs through Reze's logger
        logger.debug("panel: " + fmt, *args)

    def auth_token(self) -> str:
        header = self.headers.get("Cookie")
        if header:
            cookie = SimpleCookie(header)
            if SESSION_COOKIE in cookie:
                return cookie[SESSION_COOKIE].value
        return ""

    def session(self):
        return get_session(self.auth_token())

    def client_ip(self) -> str:
        if settings.web_trust_proxy:
            for header in ("CF-Connecting-IP", "X-Real-IP", "X-Forwarded-For"):
                value = self.headers.get(header)
                if value:
                    return value.split(",")[0].strip()
        return self.client_address[0] if self.client_address else "unknown"

    def is_https(self) -> bool:
        if settings.web_trust_proxy:
            proto = (self.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip().lower()
            if proto:
                return proto == "https"
        return bool(settings.public_url and settings.public_url.startswith("https://"))

    def session_cookie(self, token: str, max_age: int = None) -> str:
        parts = [f"{SESSION_COOKIE}={token}", "Path=/", "HttpOnly", "SameSite=Lax"]
        if max_age is not None:
            parts.append(f"Max-Age={int(max_age)}")
        if self.is_https():
            parts.append("Secure")
        return "; ".join(parts)

    def _send(self, body: bytes, content_type: str, status: int = 200, cookie: str = "", extra: dict = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        self.send_header("Content-Security-Policy", CSP)
        if self.is_https():
            self.send_header("Strict-Transport-Security", "max-age=15552000")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_html(self, body: str, status: int = 200, cookie: str = "", extra: dict = None):
        self._send(body.encode("utf-8"), "text/html; charset=utf-8", status, cookie, extra)

    def send_json(self, payload: dict, status: int = 200):
        self._send(
            json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            "application/json; charset=utf-8",
            status,
        )

    def redirect(self, path: str, cookie: str = ""):
        self._send(b"", "text/html; charset=utf-8", 302, cookie, {"Location": path})

    def read_form(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            return None
        if length < 0 or length > settings.web_max_body_bytes:
            return None
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return urllib.parse.parse_qs(raw, keep_blank_values=True)

    def page(self, title: str, content: str, active: str, status: int = 200, cookie: str = ""):
        token = csrf_token_for(self.session())
        self.send_html(render_shell(title, content, active, csrf=token), status, cookie)

    def forbidden(self, reason: str):
        body = pages.card_error("Request rejected", reason)
        self.page("Forbidden", body, "dashboard", status=403)

    # ------------------------------------------------------------------- state
    def build_status(self) -> dict:
        telegram = telegram_manager.status()
        plugin_status = plugin_manager.status()
        tasks = task_manager.snapshot()
        counts = db.get_stats()
        return {
            "telegram": telegram,
            "plugins": plugin_status,
            "tasks": tasks,
            "counts": counts,
            "uptime": time.time() - PANEL_STARTED_AT,
            "platform": settings.platform_name,
            "panel_url": settings.display_url,
            "session_backend": settings.session_backend,
            "prefix": router.prefix,
            "theme": all_prefs().get("theme", settings.theme),
            "deployment_notes": settings.deployment_notes(),
            "panel_password_set": settings.has_panel_credentials,
        }

    @staticmethod
    def build_integrations() -> list:
        from reze.ai.gateway import ai_gateway

        ai = ai_gateway.status()
        return [
            ("Pillow (images and stickers)", images.available(), "pip install Pillow"),
            ("FFmpeg (video and audio)", ffmpeg.available(), "system package or REZE_FFMPEG_PATH"),
            (
                "AI provider",
                ai["configured"],
                f"{ai['provider']}/{ai['model']}" if ai["configured"] else "set REZE_AI_* variables",
            ),
            (
                "Background removal",
                bool(settings.removebg_api_key),
                "REZE_REMOVEBG_API_KEY",
            ),
            (
                "Telegram session",
                telegram_manager.status()["connected"],
                "REZE_SESSION_STRING or interactive login",
            ),
        ]

    def recent_errors(self) -> list:
        return [
            entry
            for entry in LOG_BUFFER
            if entry.get("level") in {"ERROR", "CRITICAL", "WARNING"}
        ][-10:]

    # ---------------------------------------------------------------------- GET
    def do_HEAD(self):
        if urllib.parse.urlparse(self.path).path in HEALTH_PATHS:
            self._send(b"", "application/json; charset=utf-8")
            return
        self._send(b"", "text/plain; charset=utf-8", 404)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path
        query = urllib.parse.parse_qs(url.query)

        if path in HEALTH_PATHS:
            return self.handle_health()
        if path == "/favicon.ico":
            return self._send(b"", "image/x-icon", 204)
        if path == "/login":
            return self.handle_login_page()

        session = self.session()
        if session is None:
            return self.redirect("/login")
        csrf = csrf_token_for(session)

        if path == "/":
            return self.page("Dashboard", pages.dashboard(self.dashboard_state(), csrf), "dashboard")
        if path == "/plugins":
            return self.page("Plugins", pages.plugins({"plugins": plugin_manager.status()}, csrf), "plugins")
        if path == "/tasks":
            state = {"tasks": task_manager.snapshot(), "task_history": db.recent_tasks(limit=20)}
            return self.page("Tasks", pages.tasks(state, csrf), "tasks")
        if path == "/settings":
            saved = "saved=1" in url.query
            content = pages.settings_page(self.settings_state(), csrf)
            if saved:
                content = pages.banner("ok", "Settings saved.") + content
            return self.page("Settings", content, "settings")
        if path == "/logs":
            level = (query.get("level", [""])[0] or "").upper()
            state = {
                "logs": list(LOG_BUFFER)[-300:],
                "log_filter": level,
            }
            return self.page("Logs", pages.logs(state, csrf), "logs")
        if path == "/productivity":
            state = {
                "notes": db.list_personal_notes(limit=50),
                "archive": db.list_archive(limit=50),
                "reminders": db.list_reminders(status="pending", limit=30),
            }
            return self.page("Archive", pages.productivity(state, csrf), "productivity")
        if path == "/profile":
            return self.page(
                "Profile clock", pages.profile({"profile": db.get_profile_settings()}, csrf), "profile"
            )
        if path == "/groups":
            return self.page(
                "Groups", pages.groups({"groups": self.group_rows()}, csrf), "groups"
            )
        if path == "/filters":
            with db.get_connection() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT chat_id, keyword, reply_text FROM filters ORDER BY id DESC LIMIT 100"
                    ).fetchall()
                ]
            return self.page("Filters", pages.filters({"filters": rows}, csrf), "filters")
        if path == "/security":
            return self.page(
                "Security", pages.security({"groups": self.group_rows()}, csrf), "security"
            )
        if path == "/automations":
            rules = [rule.to_dict() for rule in automation_engine.rules()]
            return self.page(
                "Automations", pages.automations({"rules": rules}, csrf), "automations"
            )
        if path == "/api/status":
            status = self.build_status()
            return self.send_json(
                {
                    "version": __version__,
                    "uptime": round(status["uptime"], 2),
                    "telegram": status["telegram"],
                    "plugins": {
                        "loaded": status["plugins"]["loaded"],
                        "failed": status["plugins"]["failed"],
                    },
                    "tasks": {
                        "active": len(status["tasks"]["active"]),
                        "queued": len(status["tasks"]["queued"]),
                    },
                    "counts": status["counts"],
                }
            )
        if path == "/logout":
            token = self.auth_token()
            destroy_session(token)
            return self.redirect("/login", self.session_cookie("", max_age=0))

        return self.page("Not found", pages.card_error("404", "Page not found."), "dashboard", 404)

    def group_rows(self) -> list:
        with db.get_connection() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM group_settings ORDER BY chat_id LIMIT 200"
                ).fetchall()
            ]

    def dashboard_state(self) -> dict:
        return {
            "status": self.build_status(),
            "integrations": self.build_integrations(),
            "recent_errors": self.recent_errors(),
        }

    def settings_state(self) -> dict:
        from reze.ai.gateway import ai_gateway

        return {
            "prefs": all_prefs(),
            "themes": sorted(THEMES),
            "limits": {
                "concurrency": settings.task_concurrency,
                "queue": settings.task_queue_limit,
                "timeout": settings.task_timeout_seconds,
                "automation": settings.automation_enabled,
            },
            "ai": ai_gateway.status(),
        }

    # --------------------------------------------------------------------- POST
    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        form = self.read_form()
        if form is None:
            return self.send_html(
                render_shell("Rejected", pages.card_error("Request too large", "The body exceeded the limit."), "dashboard"),
                status=413,
            )

        if path == "/login":
            return self.handle_login_post(form)

        session = self.session()
        if session is None:
            return self.redirect("/login")

        csrf = form.get("csrf_token", [""])[0]
        if not validate_csrf(session, csrf):
            logger.warning("Rejected a POST without a valid CSRF token for %s", path)
            return self.forbidden("The CSRF token is missing or invalid. Reload the page and retry.")

        if path == "/logout":
            destroy_session(self.auth_token())
            return self.redirect("/login", self.session_cookie("", max_age=0))
        if path == "/settings/save":
            return self.handle_settings_save(form, session)
        if path == "/plugins/toggle":
            return self.handle_plugin_toggle(form)
        if path == "/tasks/cancel":
            return self.handle_task_cancel(form)
        if path == "/profile/save":
            return self.handle_profile_save(form)
        if path == "/productivity/delete":
            return self.handle_productivity_delete(form)
        if path == "/automations/create":
            return self.handle_automation_create(form)
        if path == "/automations/toggle":
            return self.handle_automation_toggle(form)
        if path == "/automations/delete":
            return self.redirect(self.handle_automation_delete(form))

        return self.page("Not found", pages.card_error("404", "Page not found."), "dashboard", 404)

    # --------------------------------------------------------------------- auth
    def handle_login_page(self, error: str = ""):
        if not settings.has_panel_credentials and not settings.allow_insecure_default_login:
            setup = (
                "<strong>Login is disabled.</strong> Set <code>REZE_PANEL_PASSWORD</code> or "
                "<code>REZE_PANEL_PASSWORD_HASH</code> and restart the service."
            )
            return self.send_html(render_login(setup=setup))
        return self.send_html(render_login(error=error))

    def handle_login_post(self, form: dict):
        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        ip = self.client_ip()

        if not settings.has_panel_credentials and not settings.allow_insecure_default_login:
            return self.handle_login_page()

        if not check_rate_limit(ip):
            return self.handle_login_page("Too many failed attempts. Wait five minutes and try again.")

        expected_username = settings.panel_username or "admin"
        valid_user = _constant_time_equals(username, expected_username)

        if settings.panel_password_hash:
            valid_password = verify_password(password, settings.panel_password_hash)
        elif settings.panel_password:
            valid_password = _constant_time_equals(password, settings.panel_password)
        else:
            valid_password = _constant_time_equals(password, "admin")

        if valid_user and valid_password:
            reset_rate_limit(ip)
            token = create_session(expected_username)
            logger.info("Successful panel login by %s from %s", expected_username, ip)
            return self.redirect("/", self.session_cookie(token))

        record_failed_login(ip)
        return self.handle_login_page("Invalid username or password.")

    # ----------------------------------------------------------------- handlers
    def handle_settings_save(self, form: dict, session: dict):
        errors = []
        for key in PREFERENCE_KEYS:
            if key not in form:
                continue
            value = form.get(key, [""])[0]
            if key == "compact":
                value = "1" if value else "0"
            try:
                set_pref(key, value)
            except (KeyError, ValueError) as exc:
                errors.append(f"{key}: {exc}")
        if errors:
            content = pages.banner("bad", "Some settings were rejected.", errors) + pages.settings_page(
                self.settings_state(), csrf_token_for(session)
            )
            return self.page("Settings", content, "settings", status=400)
        router.prefix = all_prefs().get("prefix", router.prefix)
        return self.redirect("/settings?saved=1")

    def handle_plugin_toggle(self, form: dict):
        name = form.get("name", [""])[0]
        action = form.get("action", [""])[0]
        try:
            if action == "enable":
                plugin_manager.enable(name)
            elif action == "disable":
                plugin_manager.disable(name)
            else:
                raise ValueError("Unknown action")
        except Exception as exc:  # noqa: BLE001 - surfaced on the plugins page
            logger.warning("Plugin toggle failed for %s: %s", name, exc)
        return self.redirect("/plugins")

    def handle_task_cancel(self, form: dict):
        task_id = form.get("task_id", [""])[0]
        try:
            run_coroutine(task_manager.cancel(task_id), timeout=10)
        except Exception as exc:  # noqa: BLE001 - loop missing or unknown task
            logger.warning("Task cancel failed for %s: %s", task_id, exc)
        return self.redirect("/tasks")

    def handle_profile_save(self, form: dict):
        name_on = 1 if form.get("name_clock_enabled") else 0
        bio_on = 1 if form.get("bio_clock_enabled") else 0
        timezone = form.get("timezone", ["UTC"])[0][:64]
        clock_format = form.get("clock_format", ["%H:%M"])[0][:20]
        db.update_profile_settings(
            name_clock_enabled=name_on,
            bio_clock_enabled=bio_on,
            timezone=timezone,
            clock_format=clock_format,
        )
        return self.redirect("/profile")

    def handle_productivity_delete(self, form: dict):
        kind = form.get("kind", [""])[0]
        key = form.get("key", [""])[0]
        if kind == "note":
            db.delete_personal_note(key)
        elif kind == "archive" and key.isdigit():
            db.delete_archive(int(key))
        elif kind == "reminder" and key.isdigit():
            db.cancel_reminder(int(key))
        return self.redirect("/productivity")

    def handle_automation_create(self, form: dict):
        trigger_type = form.get("trigger_type", ["schedule"])[0]
        action_type = form.get("action_type", ["notify"])[0]
        name = form.get("name", [""])[0]
        try:
            cooldown = int(form.get("cooldown", ["60"])[0] or 60)
        except ValueError:
            cooldown = 60

        if trigger_type == "schedule":
            trigger_config = {"at": form.get("at", [""])[0].strip()}
        elif trigger_type == "interval":
            try:
                trigger_config = {"minutes": int(form.get("minutes", ["60"])[0] or 60)}
            except ValueError:
                trigger_config = {"minutes": 0}
        elif trigger_type == "keyword":
            trigger_config = {"text": form.get("keyword", [""])[0].strip()}
        else:
            trigger_config = {}

        action = {"type": action_type}
        text = form.get("action_text", [""])[0].strip()
        if text:
            action["text"] = text

        try:
            automation_engine.create(
                name=name,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                actions=[action],
                cooldown=cooldown,
                created_by=int(settings.owner_id or 0),
            )
        except AutomationError as exc:
            session = self.session()
            content = pages.banner("bad", "Rule rejected", [str(exc)]) + pages.automations(
                {"rules": [rule.to_dict() for rule in automation_engine.rules()]},
                csrf_token_for(session) if session else "",
            )
            return self.page("Automations", content, "automations", status=400)
        return self.redirect("/automations")

    def handle_automation_toggle(self, form: dict):
        name = form.get("name", [""])[0]
        action = form.get("action", [""])[0]
        try:
            if action == "enable":
                automation_engine.enable(name)
            else:
                automation_engine.disable(name)
        except AutomationError as exc:
            logger.warning("Automation toggle failed: %s", exc)
        return self.redirect("/automations")

    def handle_automation_delete(self, form: dict):
        automation_engine.delete(form.get("name", [""])[0])
        return "/automations"

    # ------------------------------------------------------------------- health
    def handle_health(self):
        telegram = telegram_manager.status()
        self.send_json(
            {
                "status": "ok",
                "service": "reze-userbot",
                "version": __version__,
                "uptime_seconds": int(time.time() - PANEL_STARTED_AT),
                "telegram_connected": bool(telegram["connected"]),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )


def _constant_time_equals(left: str, right: str) -> bool:
    import hmac

    return hmac.compare_digest((left or "").encode("utf-8"), (right or "").encode("utf-8"))


_httpd = None


def run_web_server(host: str = None, port: int = None):
    """Bind the panel and serve until stopped."""
    global _httpd
    bind_host = host or settings.effective_web_host
    bind_port = int(port if port is not None else settings.web_port)

    try:
        httpd = ThreadingHTTPServer((bind_host, bind_port), RezePanelHandler)
    except OSError as exc:
        logger.error("Could not bind the web panel to %s:%d - %s", bind_host, bind_port, exc)
        return None

    httpd.daemon_threads = True
    _httpd = httpd
    logger.info(
        "Reze Web Panel listening on http://%s:%d (health: %s)",
        bind_host,
        bind_port,
        settings.healthcheck_path,
    )
    if bind_host not in ("127.0.0.1", "localhost", "::1") and not settings.has_panel_credentials:
        logger.warning(
            "The panel is exposed on %s without a configured password. "
            "Set REZE_PANEL_PASSWORD before exposing it publicly.",
            bind_host,
        )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        _httpd = None


def stop_web_server():
    """Stop the panel from another thread (shutdown path)."""
    global _httpd
    if _httpd is not None:
        try:
            _httpd.shutdown()
        except Exception:
            pass
        try:
            _httpd.server_close()
        except Exception:
            pass
        _httpd = None
