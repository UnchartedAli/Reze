"""
Reze Web Control Panel Server.

A dependency-free HTTP panel built on Python's standard library with a modern
dark dashboard, deployment diagnostics, a public health endpoint for PaaS
platforms, and Persian UI.

Designed and maintained by UnchartedAli — https://t.me/yamods
"""

import html
import hmac
import json
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from reze import __author__, __channel__, __channel_url__, __version__
from reze.config import settings
from reze.database import db
from reze.command_router import router
from reze.logging_config import LOG_BUFFER, logger
from reze.telegram_client import telegram_manager
from reze.web.auth import (
    verify_password,
    create_session,
    get_session,
    destroy_session,
    check_rate_limit,
    record_failed_login,
)

PANEL_STARTED_AT = time.time()
HEALTH_PATHS = {"/health", "/healthz", "/livez", "/readyz"}

PANEL_CSS = """
:root {
    --bg-dark: #0b0f19;
    --card-bg: #111827;
    --border-color: #1f2937;
    --accent-cyan: #06b6d4;
    --accent-blue: #3b82f6;
    --text-light: #f3f4f6;
    --text-muted: #9ca3af;
    --danger: #ef4444;
    --success: #10b981;
    --warning: #f59e0b;
}
* { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Tahoma, sans-serif; }
body { background-color: var(--bg-dark); color: var(--text-light); min-height: 100vh; display: flex; flex-direction: column; }
header { background: var(--card-bg); border-bottom: 1px solid var(--border-color); padding: 1rem 2rem; display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
.brand { font-size: 1.3rem; font-weight: 700; color: var(--accent-cyan); display: flex; align-items: center; gap: 0.5rem; }
.badge { font-size: 0.75rem; background: #1e293b; color: var(--accent-cyan); padding: 0.2rem 0.5rem; border-radius: 4px; }
.header-meta { color: var(--text-muted); font-size: 0.85rem; }
.header-meta a { color: var(--accent-cyan); text-decoration: none; }
.container { display: flex; flex: 1; }
aside { width: 260px; background: #0f172a; border-left: 1px solid var(--border-color); padding: 1.5rem 1rem; display: flex; flex-direction: column; gap: 0.5rem; }
aside .nav-title { color: var(--text-muted); font-size: 0.75rem; letter-spacing: 0.05em; text-transform: uppercase; margin: 0.5rem 0.5rem 0; }
.nav-item { display: block; padding: 0.75rem 1rem; color: var(--text-muted); text-decoration: none; border-radius: 8px; transition: all 0.2s; }
.nav-item:hover, .nav-item.active { background: rgba(6, 182, 212, 0.1); color: var(--accent-cyan); border-right: 3px solid var(--accent-cyan); }
.sidebar-credit { margin-top: auto; border-top: 1px solid var(--border-color); padding-top: 1rem; color: var(--text-muted); font-size: 0.78rem; line-height: 1.8; }
.sidebar-credit a { color: var(--accent-cyan); text-decoration: none; }
main { flex: 1; padding: 2rem; overflow-y: auto; }
h2 { margin-bottom: 1.25rem; font-size: 1.35rem; }
h3 { margin-bottom: 0.75rem; font-size: 1.05rem; }
.card { background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
.stat-box { background: #1e293b; border-radius: 8px; padding: 1rem; border-right: 4px solid var(--accent-cyan); }
.stat-val { font-size: 1.8rem; font-weight: bold; color: #fff; margin-top: 0.5rem; }
.stat-label { color: var(--text-muted); font-size: 0.85rem; }
.btn { display: inline-block; padding: 0.6rem 1.2rem; background: var(--accent-cyan); color: #000; text-decoration: none; border-radius: 6px; font-weight: 600; border: none; cursor: pointer; }
.btn-danger { background: var(--danger); color: #fff; }
.form-group { margin-bottom: 1rem; }
.form-group label { display: block; margin-bottom: 0.4rem; color: var(--text-muted); font-size: 0.9rem; }
input, select, textarea { width: 100%; padding: 0.6rem 0.8rem; background: #1e293b; border: 1px solid var(--border-color); border-radius: 6px; color: #fff; }
table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
th, td { padding: 0.75rem; text-align: right; border-bottom: 1px solid var(--border-color); vertical-align: top; }
th { color: var(--text-muted); font-weight: 600; }
code { background: #0f172a; border: 1px solid var(--border-color); padding: 0.1rem 0.35rem; border-radius: 4px; font-size: 0.85rem; word-break: break-all; }
.log-stream { background: #000; color: #10b981; font-family: ui-monospace, Consolas, monospace; padding: 1rem; border-radius: 8px; max-height: 400px; overflow-y: auto; font-size: 0.85rem; line-height: 1.7; }
.alert { border-radius: 8px; padding: 0.9rem 1rem; margin-bottom: 1rem; font-size: 0.9rem; line-height: 1.8; border: 1px solid; }
.alert-warn { background: rgba(245, 158, 11, 0.08); border-color: rgba(245, 158, 11, 0.4); color: #fbbf24; }
.alert-info { background: rgba(59, 130, 246, 0.08); border-color: rgba(59, 130, 246, 0.4); color: #93c5fd; }
.alert-danger { background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.4); color: #fca5a5; }
.pill { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 999px; font-size: 0.78rem; font-weight: 700; }
.pill.ok { background: rgba(16, 185, 129, 0.15); color: var(--success); }
.pill.bad { background: rgba(239, 68, 68, 0.15); color: var(--danger); }
.muted { color: var(--text-muted); }
footer { border-top: 1px solid var(--border-color); padding: 1rem 2rem; text-align: center; color: var(--text-muted); font-size: 0.82rem; }
footer a { color: var(--accent-cyan); text-decoration: none; }
@media (max-width: 820px) {
    .container { flex-direction: column; }
    aside { width: 100%; border-left: none; border-bottom: 1px solid var(--border-color); }
    main { padding: 1rem; }
    header { padding: 1rem; }
}
"""


def _esc(value) -> str:
    """Escape untrusted values before rendering them in HTML."""
    return html.escape(str(value if value is not None else ""))


def render_template(title: str, content: str, active_tab: str = "dashboard") -> str:
    nav_items = [
        ("dashboard", "📊 داشبورد", "/"),
        ("profile", "⏰ ساعت و پروفایل", "/profile"),
        ("groups", "👥 مدیریت گروه‌ها", "/groups"),
        ("antiflood", "🛡️ ضد اسپم و هجوم", "/security"),
        ("filters", "🔍 فیلترها و کلمات", "/filters"),
        ("logs", "📋 لاگ‌های زنده", "/logs"),
        ("settings", "⚙️ تنظیمات سیستم", "/settings"),
    ]
    nav_html = "".join([
        f'<a href="{url}" class="nav-item {"active" if key == active_tab else ""}">{label}</a>'
        for key, label, url in nav_items
    ])

    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="author" content="{__author__}">
    <meta name="description" content="Reze Telegram Userbot control panel by {__author__} ({__channel__})">
    <title>Reze Panel — {_esc(title)}</title>
    <style>{PANEL_CSS}</style>
</head>
<body>
    <header>
        <div class="brand">🌸 Reze Control Panel <span class="badge">v{__version__}</span></div>
        <div class="header-meta">ساخته‌شده توسط <strong>{__author__}</strong> · کانال: <a href="{__channel_url__}" target="_blank" rel="noopener">{__channel__}</a></div>
        <div><a href="/logout" class="btn btn-danger" style="padding: 0.4rem 0.8rem; font-size: 0.85rem;">خروج</a></div>
    </header>
    <div class="container">
        <aside>
            <div class="nav-title">منوی مدیریت</div>
            {nav_html}
            <div class="sidebar-credit">
                🌸 Reze Userbot v{__version__}<br>
                سازنده: <a href="{__channel_url__}" target="_blank" rel="noopener">{__author__}</a><br>
                کانال رسمی: <a href="{__channel_url__}" target="_blank" rel="noopener">{__channel__}</a>
            </div>
        </aside>
        <main>{content}</main>
    </div>
    <footer>
        ساخته‌شده با ❤️ توسط <strong>{__author__}</strong> —
        کانال تلگرام: <a href="{__channel_url__}" target="_blank" rel="noopener">{__channel__}</a>
        · نسخه {__version__}
    </footer>
</body>
</html>"""


def render_login_page(error: str = "", setup_html: str = "") -> str:
    footer = (
        f'ساخته‌شده توسط <strong>{__author__}</strong> · '
        f'<a href="{__channel_url__}" target="_blank" rel="noopener">{__channel__}</a>'
    )
    error_html = f'<div class="err">{_esc(error)}</div>' if error else ""
    body = setup_html if setup_html else f"""
        {error_html}
        <form method="POST" action="/login">
            <input type="text" name="username" placeholder="نام کاربری" required autofocus>
            <input type="password" name="password" placeholder="کلمه عبور" required>
            <button type="submit">ورود به داشبورد</button>
        </form>
    """
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="author" content="{__author__}">
    <title>ورود به پنل Reze</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ background: #0b0f19; color: #f3f4f6; display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 100vh; margin: 0; font-family: Tahoma, -apple-system, sans-serif; padding: 1.5rem; }}
        .card {{ background: #111827; padding: 2.2rem; border-radius: 12px; border: 1px solid #1f2937; width: 100%; max-width: 380px; }}
        h2 {{ color: #06b6d4; text-align: center; margin: 0 0 0.4rem; }}
        .sub {{ color: #9ca3af; text-align: center; font-size: 0.82rem; margin-bottom: 1.5rem; }}
        input {{ width: 100%; padding: 0.75rem; margin-bottom: 1rem; background: #1e293b; border: 1px solid #374151; border-radius: 6px; color: #fff; box-sizing: border-box; }}
        button {{ width: 100%; padding: 0.75rem; background: #06b6d4; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; }}
        .err {{ color: #ef4444; font-size: 0.85rem; margin-bottom: 1rem; text-align: center; line-height: 1.7; }}
        .setup {{ color: #d1d5db; font-size: 0.85rem; line-height: 2; }}
        .setup code {{ background: #0b0f19; border: 1px solid #1f2937; padding: 0.15rem 0.4rem; border-radius: 4px; word-break: break-all; }}
        .setup a {{ color: #06b6d4; }}
        footer {{ margin-top: 1.5rem; color: #9ca3af; font-size: 0.78rem; text-align: center; }}
        footer a {{ color: #06b6d4; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>🌸 Reze Panel</h2>
        <div class="sub">پنل مدیریت یوزربات تلگرام</div>
        {body}
    </div>
    <footer>{footer}</footer>
</body>
</html>"""


class RezePanelHandler(BaseHTTPRequestHandler):
    server_version = f"Reze/{__version__}"
    sys_version = ""

    # ------------------------------------------------------------------ helpers
    def get_auth_token(self) -> str:
        cookie_header = self.headers.get("Cookie")
        if cookie_header:
            cookie = SimpleCookie(cookie_header)
            if "reze_session" in cookie:
                return cookie["reze_session"].value
        return ""

    def get_client_ip(self) -> str:
        """Resolve the real client IP when running behind a PaaS proxy."""
        for header in ("CF-Connecting-IP", "X-Real-IP"):
            value = self.headers.get(header)
            if value:
                return value.split(",")[0].strip()
        forwarded = self.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def request_is_https(self) -> bool:
        proto = self.headers.get("X-Forwarded-Proto", "")
        if proto:
            return proto.split(",")[0].strip().lower() == "https"
        return bool(settings.public_url and settings.public_url.startswith("https://"))

    def is_authenticated(self) -> bool:
        return bool(get_session(self.get_auth_token()))

    def session_cookie(self, token: str) -> str:
        cookie = f"reze_session={token}; Path=/; HttpOnly; SameSite=Lax"
        if self.request_is_https():
            cookie += "; Secure"
        return cookie

    def redirect(self, path: str, cookie: str = ""):
        self.send_response(302)
        self.send_header("Location", path)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_body(self, body: bytes, content_type: str, status: int = 200, cookie: str = ""):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "same-origin")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, page: str, status: int = 200, cookie: str = ""):
        self._send_body(page.encode("utf-8"), "text/html; charset=utf-8", status, cookie)

    def send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send_body(body, "application/json; charset=utf-8", status)

    # --------------------------------------------------------------------- HTTP
    def do_HEAD(self):
        path = urllib.parse.urlparse(self.path).path
        if path in HEALTH_PATHS:
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path

        # Public, unauthenticated health endpoint used by Render/Railway/Koyeb.
        if path in HEALTH_PATHS:
            return self.handle_health()

        if path == "/favicon.ico":
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path == "/login":
            return self.handle_login_page()

        if not self.is_authenticated():
            return self.redirect("/login")

        if path == "/":
            return self.handle_dashboard()
        elif path == "/profile":
            return self.handle_profile()
        elif path == "/groups":
            return self.handle_groups()
        elif path == "/security":
            return self.handle_security()
        elif path == "/filters":
            return self.handle_filters()
        elif path == "/logs":
            return self.handle_logs()
        elif path == "/settings":
            return self.handle_settings()
        elif path == "/logout":
            token = self.get_auth_token()
            destroy_session(token)
            cookie = "reze_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
            if self.request_is_https():
                cookie += "; Secure"
            return self.redirect("/login", cookie)
        elif path == "/api/stats":
            stats = db.get_stats()
            stats["total_executed"] = router.total_executed
            stats["telegram"] = telegram_manager.status()
            return self.send_json(stats)
        else:
            self.send_html("<h1>404 Not Found</h1>", 404)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path

        try:
            content_length = int(self.headers.get("Content-Length", 0) or 0)
        except ValueError:
            content_length = 0
        post_data = self.rfile.read(content_length).decode("utf-8", errors="replace")
        form = urllib.parse.parse_qs(post_data)

        if path == "/login":
            return self.handle_login_post(form)

        if not self.is_authenticated():
            return self.redirect("/login")

        if path == "/profile/save":
            name_on = 1 if "name_clock_enabled" in form else 0
            bio_on = 1 if "bio_clock_enabled" in form else 0
            tz = form.get("timezone", ["Asia/Tehran"])[0]
            fmt = form.get("clock_format", ["%H:%M"])[0]
            db.update_profile_settings(
                name_clock_enabled=name_on,
                bio_clock_enabled=bio_on,
                timezone=tz,
                clock_format=fmt,
            )
            return self.redirect("/profile")
        elif path == "/filters/add":
            try:
                chat_id = int(form.get("chat_id", [0])[0])
            except ValueError:
                chat_id = 0
            kw = form.get("keyword", [""])[0]
            reply_text = form.get("reply_text", [""])[0]
            if chat_id and kw and reply_text:
                db.set_filter(chat_id, kw, reply_text)
            return self.redirect("/filters")

        self.redirect("/")

    # ------------------------------------------------------------------- health
    def handle_health(self):
        telegram = telegram_manager.status()
        payload = {
            "status": "ok",
            "service": "reze-userbot",
            "version": __version__,
            "author": __author__,
            "channel": __channel__,
            "platform": settings.platform_name,
            "hosted": settings.is_hosted,
            "uptime_seconds": int(time.time() - PANEL_STARTED_AT),
            "telegram": telegram,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self.send_json(payload)

    # --------------------------------------------------------------------- auth
    def handle_login_page(self, error: str = ""):
        credentials_configured = settings.has_panel_credentials
        insecure_allowed = settings.allow_insecure_default_login

        if not credentials_configured and not insecure_allowed:
            setup_html = """
            <div class="setup">
                <p style="color:#fbbf24; margin-bottom: 0.8rem;">⚠️ ورود به پنل غیرفعال است، چون رمز عبور تنظیم نشده.</p>
                <p>متغیر محیطی زیر را اضافه کنید و سرویس را ری‌استارت کنید:</p>
                <p><code>REZE_PANEL_PASSWORD=یک-رمز-قوی</code></p>
                <p style="margin-top: 0.8rem;">یا هش امن بسازید و مقدار زیر را تنظیم کنید:</p>
                <p><code>REZE_PANEL_PASSWORD_HASH=...</code></p>
                <p style="margin-top: 0.8rem;">راهنما: <code>python scripts/generate_hash.py</code></p>
                <p style="margin-top: 0.8rem;">برای سلامت سرویس: <a href="/healthz">/healthz</a></p>
            </div>
            """
            return self.send_html(render_login_page(setup_html=setup_html))

        hint = ""
        if not credentials_configured:
            hint = (
                "حالت توسعه: نام کاربری admin و رمز admin فعال است. "
                "برای امنیت، REZE_PANEL_PASSWORD را تنظیم کنید."
            )
            return self.send_html(render_login_page(error=hint))
        return self.send_html(render_login_page(error=error))

    def handle_login_post(self, form: dict):
        username = form.get("username", [""])[0]
        password = form.get("password", [""])[0]
        client_ip = self.get_client_ip()

        credentials_configured = settings.has_panel_credentials
        insecure_allowed = settings.allow_insecure_default_login

        if not credentials_configured and not insecure_allowed:
            return self.handle_login_page()

        if not check_rate_limit(client_ip):
            return self.handle_login_page(
                "تعداد تلاش‌های ناموفق بیش از حد مجاز. ۵ دقیقه صبر کنید."
            )

        expected_username = settings.panel_username or "admin"
        is_valid_user = hmac.compare_digest(
            username.encode("utf-8"), expected_username.encode("utf-8")
        )

        if settings.panel_password_hash:
            is_valid_pass = verify_password(password, settings.panel_password_hash)
        elif settings.panel_password:
            is_valid_pass = hmac.compare_digest(
                password.encode("utf-8"), settings.panel_password.encode("utf-8")
            )
        else:
            # Only reachable when REZE_ALLOW_INSECURE_DEFAULT_LOGIN=true.
            is_valid_pass = password == "admin"

        if is_valid_user and is_valid_pass:
            token = create_session(username)
            logger.info("Successful login to Web Panel by %s from %s", username, client_ip)
            return self.redirect("/", self.session_cookie(token))

        record_failed_login(client_ip)
        logger.warning("Failed login attempt to Web Panel from IP %s", client_ip)
        return self.handle_login_page("نام کاربری یا رمز عبور اشتباه است.")

    # ---------------------------------------------------------------- dashboard
    def handle_dashboard(self):
        stats = db.get_stats()
        cfg = db.get_profile_settings()
        telegram = telegram_manager.status()
        connected = telegram["connected"]
        status_pill = (
            '<span class="pill ok">متصل</span>'
            if connected
            else '<span class="pill bad">قطع / نیازمند ورود</span>'
        )

        alerts = []
        if not telegram["configured"]:
            alerts.append(
                '<div class="alert alert-danger">'
                "🔑 <strong>اتصال تلگرام پیکربندی نشده است.</strong><br>"
                "مقادیر <code>REZE_API_ID</code>، <code>REZE_API_HASH</code> و "
                "<code>REZE_OWNER_ID</code> را در متغیرهای محیطی تنظیم کنید."
                "</div>"
            )
        elif not connected:
            alerts.append(
                '<div class="alert alert-warn">'
                "🔐 <strong>تلگرام متصل نیست.</strong><br>"
                "روی سرویس‌های ابری با فایل‌سیستم موقت، از "
                "<code>REZE_SESSION_STRING</code> استفاده کنید. ساخت سشن: "
                "<code>python scripts/generate_session.py</code>"
                "</div>"
            )

        if settings.is_hosted and settings.session_backend == "file":
            alerts.append(
                '<div class="alert alert-info">'
                "💾 در حال اجرا روی سرویس ابری با سشن فایلی هستید. برای جلوگیری از "
                "خروج از حساب پس از هر ری‌استارت، یک دیسک/ولوم دائمی متصل کنید یا "
                "<code>REZE_SESSION_STRING</code> را تنظیم کنید."
                "</div>"
            )

        if not settings.has_panel_credentials:
            alerts.append(
                '<div class="alert alert-danger">'
                "🔒 رمز پنل تنظیم نشده و ورود غیرفعال است. "
                "<code>REZE_PANEL_PASSWORD</code> را تنظیم کنید."
                "</div>"
            )

        alerts_html = "".join(alerts)

        content = f"""
        <h2>داشبورد نظارت و آمار کلی</h2>
        {alerts_html}
        <div class="grid">
            <div class="stat-box">
                <div class="stat-label">دستورات اجراشده</div>
                <div class="stat-val">{router.total_executed}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">گروه‌های فعال</div>
                <div class="stat-val">{stats.get('groups', 0)}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">ساعت نام و بیو</div>
                <div class="stat-val">{'فعال ✅' if cfg.get('name_clock_enabled') else 'خاموش ⏸️'}</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">خطاهای ثبت‌شده</div>
                <div class="stat-val">{router.errors_count}</div>
            </div>
        </div>
        <div class="card">
            <h3>وضعیت اتصال سرویس MTProto</h3>
            <p style="margin-top: 0.5rem; line-height: 2;">
                وضعیت: {status_pill}<br>
                بک‌اند سشن: <code>{_esc(settings.session_backend)}</code> |
                پلتفرم: <code>{_esc(settings.platform_name)}</code><br>
                پیشوند فعال: <code>{_esc(router.prefix)}</code> |
                منطقه زمانی: <code>{_esc(settings.timezone)}</code><br>
                شناسه مالک: <code>{_esc(settings.owner_id)}</code>
            </p>
        </div>
        <div class="card">
            <h3>دسترسی سریع</h3>
            <p class="muted" style="line-height: 2;">
                پنل: <code>{_esc(settings.display_url)}</code><br>
                سلامت سرویس: <a style="color: var(--accent-cyan);" href="/healthz">/healthz</a><br>
                راهنمای دیپلوی: <code>DEPLOY.md</code>
            </p>
        </div>
        """
        self.send_html(render_template("داشبورد", content, "dashboard"))

    # ------------------------------------------------------------------ profile
    def handle_profile(self):
        cfg = db.get_profile_settings()
        content = f"""
        <h2>تنظیمات ساعت نام و بیوگرافی</h2>
        <div class="card">
            <form method="POST" action="/profile/save">
                <div class="form-group">
                    <label>
                        <input type="checkbox" name="name_clock_enabled" value="1" {'checked' if cfg.get('name_clock_enabled') else ''}>
                        فعال‌سازی نمایش ساعت در نام کاربری
                    </label>
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" name="bio_clock_enabled" value="1" {'checked' if cfg.get('bio_clock_enabled') else ''}>
                        فعال‌سازی نمایش ساعت در بیوگرافی (Bio)
                    </label>
                </div>
                <div class="form-group">
                    <label>منطقه زمانی (IANA Timezone):</label>
                    <input type="text" name="timezone" value="{_esc(cfg.get('timezone', 'Asia/Tehran'))}">
                </div>
                <div class="form-group">
                    <label>فرمت نمایش زمان (strftime):</label>
                    <input type="text" name="clock_format" value="{_esc(cfg.get('clock_format', '%H:%M'))}">
                </div>
                <button type="submit" class="btn">ذخیره تغییرات ساعت</button>
            </form>
        </div>
        """
        self.send_html(render_template("ساعت پروفایل", content, "profile"))

    # ------------------------------------------------------------------- groups
    def handle_groups(self):
        content = """
        <h2>مدیریت گروه‌ها و سوپرگروه‌ها</h2>
        <div class="card">
            <p style="color: var(--text-muted);">فهرست گروه‌های پیکربندی‌شده در دیتابیس Reze:</p>
            <table>
                <thead>
                    <tr>
                        <th>شناسه گروه</th>
                        <th>نام گروه</th>
                        <th>وضعیت AntiFlood</th>
                        <th>وضعیت AntiLink</th>
                        <th>پیام خوشامد</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td colspan="5" style="text-align: center; color: var(--text-muted);">گروهی به صورت محلی ثبت نشده است. دستورات را در گروه اجرا کنید تا خودکار ثبت شوند.</td>
                    </tr>
                </tbody>
            </table>
        </div>
        """
        self.send_html(render_template("گروه‌ها", content, "groups"))

    # ----------------------------------------------------------------- security
    def handle_security(self):
        content = """
        <h2>تنظیمات امنیت، AntiFlood و AntiRaid</h2>
        <div class="card">
            <h3>تنظیمات ضداسپم گروهی</h3>
            <p style="color: var(--text-muted); margin-top: 0.5rem; line-height: 2;">
                سیستم AntiFlood با ثبت نرخ ارسال پیام هر کاربر از اسپم ممانعت به عمل می‌آورد.
                همچنین مکانیزم AntiRaid ورودهای همزمان را بلافاصله مسدود می‌کند.
            </p>
        </div>
        """
        self.send_html(render_template("امنیت", content, "antiflood"))

    # ------------------------------------------------------------------ filters
    def handle_filters(self):
        content = """
        <h2>فیلترها و پاسخ‌های خودکار</h2>
        <div class="card">
            <h3>افزودن فیلتر جدید</h3>
            <form method="POST" action="/filters/add">
                <div class="form-group">
                    <label>شناسه چت یا گروه:</label>
                    <input type="number" name="chat_id" placeholder="-100123456789" required>
                </div>
                <div class="form-group">
                    <label>کلمه کلیدی:</label>
                    <input type="text" name="keyword" placeholder="سلام" required>
                </div>
                <div class="form-group">
                    <label>متن پاسخ:</label>
                    <input type="text" name="reply_text" placeholder="درود، به گروه خوش آمدید!" required>
                </div>
                <button type="submit" class="btn">ثبت فیلتر</button>
            </form>
        </div>
        """
        self.send_html(render_template("فیلترها", content, "filters"))

    # --------------------------------------------------------------------- logs
    def handle_logs(self):
        logs_html = "".join(
            [
                f"<div>[{_esc(item.get('level'))}] {_esc(item.get('message'))}</div>"
                for item in LOG_BUFFER
            ]
        ) or "در انتظار ثبت لاگ جدید..."
        content = f"""
        <h2>لاگ‌های سیستم (زنده)</h2>
        <div class="card">
            <div class="log-stream">{logs_html}</div>
        </div>
        """
        self.send_html(render_template("لاگ‌ها", content, "logs"))

    # ----------------------------------------------------------------- settings
    def handle_settings(self):
        public_url = settings.display_url
        credentials_state = "تنظیم شده ✅" if settings.has_panel_credentials else "تنظیم نشده ⚠️"
        content = f"""
        <h2>تنظیمات محیطی و سیستمی</h2>
        <div class="card">
            <h3>سازنده و پشتیبانی</h3>
            <p style="line-height: 2.1;">
                👤 سازنده: <strong>{__author__}</strong><br>
                📣 کانال رسمی: <a style="color: var(--accent-cyan);" href="{__channel_url__}" target="_blank" rel="noopener">{__channel__}</a><br>
                🏷️ نسخه: <code>{__version__}</code>
            </p>
        </div>
        <div class="card">
            <h3>وضعیت استقرار</h3>
            <table>
                <tbody>
                    <tr><th>پلتفرم</th><td><code>{_esc(settings.platform_name)}</code></td></tr>
                    <tr><th>حالت ابری (PaaS)</th><td>{'بله' if settings.is_hosted else 'خیر'}</td></tr>
                    <tr><th>آدرس عمومی پنل</th><td><code>{_esc(public_url)}</code></td></tr>
                    <tr><th>آدرس سلامت سرویس</th><td><a style="color: var(--accent-cyan);" href="/healthz">/healthz</a></td></tr>
                    <tr><th>تنظیم رمز پنل</th><td>{credentials_state}</td></tr>
                    <tr><th>بک‌اند سشن تلگرام</th><td><code>{_esc(settings.session_backend)}</code></td></tr>
                </tbody>
            </table>
        </div>
        <div class="card">
            <h3>تنظیمات فعال</h3>
            <p style="line-height: 2.1;">
                <strong>شناسه مالک:</strong> <code>{_esc(settings.owner_id)}</code><br>
                <strong>منطقه زمانی پیش‌فرض:</strong> <code>{_esc(settings.timezone)}</code><br>
                <strong>پورت وب پنل:</strong> <code>{_esc(settings.web_port)}</code><br>
                <strong>میزبان اتصال:</strong> <code>{_esc(settings.effective_web_host)}</code><br>
                <strong>پوشه داده:</strong> <code>{_esc(settings.data_dir)}</code><br>
                <strong>مسیر دیتابیس:</strong> <code>{_esc(db.db_path)}</code>
            </p>
        </div>
        <div class="card">
            <h3>چک‌لیست متغیرهای محیطی</h3>
            <table>
                <thead><tr><th>متغیر</th><th>وضعیت</th></tr></thead>
                <tbody>
                    <tr><td><code>REZE_API_ID</code> / <code>REZE_API_HASH</code></td><td>{'✅' if settings.api_id and settings.api_hash else '❌'}</td></tr>
                    <tr><td><code>REZE_OWNER_ID</code></td><td>{'✅' if settings.owner_id else '❌'}</td></tr>
                    <tr><td><code>REZE_SESSION_STRING</code></td><td>{'✅' if settings.session_string else '➖ (فایل سشن)'}</td></tr>
                    <tr><td><code>REZE_PANEL_PASSWORD</code> یا <code>REZE_PANEL_PASSWORD_HASH</code></td><td>{'✅' if settings.has_panel_credentials else '❌'}</td></tr>
                </tbody>
            </table>
        </div>
        """
        self.send_html(render_template("تنظیمات", content, "settings"))


_httpd = None


def run_web_server(host: str = None, port: int = None):
    """Bind the panel to the platform port and serve forever."""
    global _httpd

    bind_host = host or settings.effective_web_host
    bind_port = int(port or settings.web_port)

    try:
        httpd = ThreadingHTTPServer((bind_host, bind_port), RezePanelHandler)
    except OSError as exc:
        logger.error(
            "Could not bind the web panel to %s:%d - %s", bind_host, bind_port, exc
        )
        return None

    httpd.daemon_threads = True
    _httpd = httpd
    logger.info(
        "Reze Web Panel listening on http://%s:%d (health endpoint: %s)",
        bind_host,
        bind_port,
        settings.healthcheck_path,
    )
    if bind_host == "0.0.0.0" and not settings.has_panel_credentials:
        logger.warning(
            "The web panel is exposed on 0.0.0.0 without a configured password. "
            "Set REZE_PANEL_PASSWORD before exposing it publicly."
        )

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        _httpd = None


def stop_web_server():
    """Stop the panel from another thread (used on SIGTERM/shutdown)."""
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
