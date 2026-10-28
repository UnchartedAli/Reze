"""
Web panel shell: terminal-inspired CSS, navigation, login page.

The panel is English-only, left-to-right, and uses no JavaScript: every action is
a form POST protected by a CSRF token, which keeps the dependency-free server
easy to audit.
"""

import html

from reze import __author__, __channel__, __channel_url__, __version__

PANEL_CSS = """
:root {
    --bg: #070b12;
    --panel: #0d1420;
    --panel-2: #111a29;
    --border: #1d2b3f;
    --text: #e6edf3;
    --muted: #8296ad;
    --accent: #22d3ee;
    --accent-dim: #0e7490;
    --ok: #34d399;
    --warn: #fbbf24;
    --bad: #f87171;
    --mono: ui-monospace, "Cascadia Code", Consolas, "Courier New", monospace;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: var(--bg); color: var(--text); min-height: 100vh; display: flex; flex-direction: column;
       font-family: var(--mono); font-size: 14px; line-height: 1.6; }
header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap;
         padding: 1rem 1.5rem; background: var(--panel); border-bottom: 1px solid var(--border); }
.brand { color: var(--accent); font-weight: 700; letter-spacing: .08em; display: flex; align-items: center; gap: .6rem; }
.badge { font-size: .72rem; border: 1px solid var(--accent-dim); color: var(--accent); padding: .15rem .45rem; border-radius: 4px; }
.meta { color: var(--muted); font-size: .78rem; }
.meta a { color: var(--accent); text-decoration: none; }
.layout { display: flex; flex: 1; min-height: 0; }
aside { width: 232px; flex-shrink: 0; background: var(--panel); border-right: 1px solid var(--border); padding: 1.25rem .75rem; }
.nav-label { color: var(--muted); font-size: .68rem; text-transform: uppercase; letter-spacing: .12em; margin: .75rem .5rem .35rem; }
.nav a { display: block; padding: .5rem .7rem; color: var(--muted); text-decoration: none; border-left: 2px solid transparent; }
.nav a:hover, .nav a.active { color: var(--accent); border-left-color: var(--accent); background: rgba(34, 211, 238, .06); }
.nav .sig { color: var(--accent-dim); }
main { flex: 1; padding: 1.5rem; overflow-y: auto; min-width: 0; }
h1 { font-size: 1.15rem; letter-spacing: .06em; margin-bottom: .35rem; }
h2 { font-size: .95rem; margin: 1.5rem 0 .6rem; color: var(--accent); letter-spacing: .08em; }
p.sub { color: var(--muted); font-size: .8rem; margin-bottom: 1rem; }
.card { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 1rem 1.1rem; margin-bottom: 1rem; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: .8rem; margin-bottom: 1rem; }
.stat { background: var(--panel-2); border: 1px solid var(--border); border-left: 3px solid var(--accent); padding: .8rem .9rem; }
.stat .label { color: var(--muted); font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; }
.stat .value { font-size: 1.35rem; margin-top: .25rem; word-break: break-word; }
table { width: 100%; border-collapse: collapse; font-size: .82rem; }
th, td { text-align: left; padding: .5rem .55rem; border-bottom: 1px solid var(--border); vertical-align: top; }
th { color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: .7rem; letter-spacing: .08em; }
tr:last-child td { border-bottom: none; }
code { background: #050a11; border: 1px solid var(--border); padding: .05rem .3rem; border-radius: 3px;
       font-size: .8rem; word-break: break-all; }
.pill { display: inline-block; padding: .1rem .5rem; border-radius: 999px; font-size: .7rem; font-weight: 700; text-transform: uppercase; }
.pill.ok { background: rgba(52, 211, 153, .12); color: var(--ok); }
.pill.warn { background: rgba(251, 191, 36, .12); color: var(--warn); }
.pill.bad { background: rgba(248, 113, 113, .12); color: var(--bad); }
.pill.off { background: rgba(130, 150, 173, .12); color: var(--muted); }
.alert { border: 1px solid var(--border); border-left: 3px solid var(--warn); background: var(--panel-2);
         padding: .7rem .9rem; margin-bottom: .8rem; font-size: .8rem; }
.alert.bad { border-left-color: var(--bad); }
.alert.ok { border-left-color: var(--ok); }
.muted { color: var(--muted); }
button, .btn { font-family: var(--mono); font-size: .78rem; padding: .4rem .9rem; border-radius: 4px; cursor: pointer;
               border: 1px solid var(--accent-dim); background: transparent; color: var(--accent); }
button:hover, .btn:hover { background: rgba(34, 211, 238, .1); }
button.danger { border-color: #7f1d1d; color: var(--bad); }
button.danger:hover { background: rgba(248, 113, 113, .1); }
input, select, textarea { width: 100%; background: #050a11; color: var(--text); border: 1px solid var(--border);
                          border-radius: 4px; padding: .45rem .6rem; font-family: var(--mono); font-size: .82rem; }
label { display: block; color: var(--muted); font-size: .74rem; margin: .6rem 0 .25rem; text-transform: uppercase; letter-spacing: .06em; }
.form-row { display: flex; gap: .8rem; flex-wrap: wrap; }
.form-row > div { flex: 1; min-width: 160px; }
.actions { display: flex; gap: .4rem; flex-wrap: wrap; }
.log { background: #04080e; border: 1px solid var(--border); border-radius: 6px; padding: .8rem; max-height: 520px;
       overflow: auto; font-size: .78rem; line-height: 1.7; }
.log .lvl { font-weight: 700; }
.log .lvl.ERROR, .log .lvl.CRITICAL { color: var(--bad); }
.log .lvl.WARNING { color: var(--warn); }
.log .lvl.INFO { color: var(--ok); }
.log .lvl.DEBUG { color: var(--muted); }
footer { border-top: 1px solid var(--border); padding: .8rem 1.5rem; color: var(--muted); font-size: .72rem; }
footer a { color: var(--accent); text-decoration: none; }
.login-wrap { display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 100vh; padding: 1.5rem; }
.login-card { width: 100%; max-width: 360px; background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 1.8rem; }
.login-card h1 { color: var(--accent); text-align: center; letter-spacing: .12em; }
.login-card .sub { text-align: center; margin-bottom: 1.2rem; }
.err { color: var(--bad); font-size: .8rem; margin-bottom: .8rem; }
@media (max-width: 860px) {
    .layout { flex-direction: column; }
    aside { width: 100%; border-right: none; border-bottom: 1px solid var(--border); }
    main { padding: 1rem; }
    .form-row { flex-direction: column; }
}
"""

NAV_SECTIONS = [
    ("Overview", [("dashboard", "Dashboard", "/"), ("logs", "Logs", "/logs")]),
    ("Platform", [
        ("plugins", "Plugins", "/plugins"),
        ("tasks", "Tasks", "/tasks"),
        ("automations", "Automations", "/automations"),
        ("settings", "Settings", "/settings"),
    ]),
    ("Community", [("groups", "Groups", "/groups"), ("filters", "Filters", "/filters"), ("security", "Security", "/security")]),
    ("Personal", [("productivity", "Archive", "/productivity"), ("profile", "Profile clock", "/profile")]),
]


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def render_shell(title: str, content: str, active: str = "dashboard", csrf: str = "") -> str:
    nav_html = []
    for section, items in NAV_SECTIONS:
        nav_html.append(f'<div class="nav-label">{esc(section)}</div>')
        for key, label, url in items:
            klass = "active" if key == active else ""
            nav_html.append(f'<a href="{url}" class="{klass}">{esc(label)}</a>')

    return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<meta name="author" content="{esc(__author__)}">
<title>REZE // {esc(title)}</title>
<style>{PANEL_CSS}</style>
</head>
<body>
<header>
    <div class="brand">REZE<span class="badge">v{esc(__version__)}</span></div>
    <div class="meta">{esc(__author__)} · <a href="{esc(__channel_url__)}" target="_blank" rel="noopener noreferrer">{esc(__channel__)}</a></div>
    <form method="POST" action="/logout"><input type="hidden" name="csrf_token" value="{esc(csrf)}"><button type="submit" class="danger">Sign out</button></form>
</header>
<div class="layout">
    <aside><nav class="nav">{''.join(nav_html)}</nav></aside>
    <main>{content}</main>
</div>
<footer>REZE — Personal Telegram OS · version {esc(__version__)} · <a href="{esc(__channel_url__)}" target="_blank" rel="noopener noreferrer">{esc(__channel__)}</a></footer>
</body>
</html>"""


def render_login(error: str = "", setup: str = "") -> str:
    if setup:
        body = f'<div class="alert">{setup}</div>'
    else:
        error_html = f'<div class="err">{esc(error)}</div>' if error else ""
        body = f"""
        {error_html}
        <form method="POST" action="/login">
            <label for="username">Username</label>
            <input id="username" name="username" type="text" autocomplete="username" required autofocus>
            <label for="password">Password</label>
            <input id="password" name="password" type="password" autocomplete="current-password" required>
            <div style="margin-top:1.2rem"><button type="submit" style="width:100%">Unlock panel</button></div>
        </form>
        """
    return f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>REZE // Sign in</title>
<style>{PANEL_CSS}</style>
</head>
<body>
<div class="login-wrap">
    <div class="login-card">
        <h1>REZE</h1>
        <p class="sub muted">Personal Telegram OS · control panel</p>
        {body}
        <p class="sub muted" style="margin-top:1.2rem; text-align:center">Health endpoint: <a href="/healthz">/healthz</a></p>
    </div>
    <footer>REZE {esc(__version__)} · <a href="{esc(__channel_url__)}" target="_blank" rel="noopener noreferrer">{esc(__channel__)}</a></footer>
</div>
</body>
</html>"""
