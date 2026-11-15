"""
HTML page renderers for the Reze control panel.

Every page renders real backend state. Values are escaped with ``esc`` and every
state-changing control is a POST form carrying the session CSRF token.
"""

import time

from reze import __version__
from reze.web.theme import esc


def csrf_field(token: str) -> str:
    return f'<input type="hidden" name="csrf_token" value="{esc(token)}">'


def banner(kind: str, title: str, items=None) -> str:
    """A page-level message block (kind: ok, warn, bad)."""
    payload = ""
    if items:
        payload = '<ul style="padding-left:1.2rem">' + "".join(
            f"<li>{esc(item)}</li>" for item in items
        ) + "</ul>"
    return f'<div class="alert {esc(kind)}"><strong>{esc(title)}</strong>{payload}</div>'


def card_error(title: str, message: str) -> str:
    return (
        '<div class="card"><h1>' + esc(title) + "</h1>"
        '<p class="sub">' + esc(message) + "</p></div>"
    )


def pill(text: str, kind: str = "off") -> str:
    return f'<span class="pill {kind}">{esc(text)}</span>'


def _duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


# ------------------------------------------------------------------ dashboard
def dashboard(state: dict, csrf: str) -> str:
    status = state["status"]
    telegram = status["telegram"]
    tasks = status["tasks"]
    plugins = status["plugins"]

    alerts = []
    if not telegram["configured"]:
        alerts.append(
            '<div class="alert bad"><strong>Telegram is not configured.</strong> '
            "Set REZE_API_ID, REZE_API_HASH and REZE_OWNER_ID, then restart.</div>"
        )
    elif not telegram["connected"]:
        alerts.append(
            '<div class="alert"><strong>Telegram is not connected.</strong> '
            "Provide REZE_SESSION_STRING (or run the login script) to enable the userbot.</div>"
        )
    if not status["panel_password_set"]:
        alerts.append(
            '<div class="alert bad"><strong>No panel password is configured.</strong> '
            "Login stays disabled until REZE_PANEL_PASSWORD or REZE_PANEL_PASSWORD_HASH is set.</div>"
        )
    for note in status["deployment_notes"]:
        alerts.append(f'<div class="alert">{esc(note)}</div>')

    integration_rows = "".join(
        f"<tr><td>{esc(name)}</td><td>{pill(ok and 'ready' or 'unavailable', 'ok' if ok else 'warn')}</td>"
        f"<td class=\"muted\">{esc(detail)}</td></tr>"
        for name, ok, detail in state["integrations"]
    )

    error_rows = "".join(
        f"<tr><td>{esc(entry.get('level'))}</td><td>{esc(entry.get('message', '')[:180])}</td></tr>"
        for entry in state["recent_errors"][-6:]
    ) or '<tr><td colspan="2" class="muted">No recent errors.</td></tr>'

    task_rows = "".join(
        f"<tr><td>{esc(task['id'])}</td><td>{esc(task['kind'])}</td><td>{esc(task['status'])}</td>"
        f"<td>{task['progress']}%</td><td>{task['elapsed']}s</td></tr>"
        for task in (tasks["active"] + tasks["queued"])[:8]
    ) or '<tr><td colspan="5" class="muted">No running tasks.</td></tr>'

    return f"""
<h1>Dashboard</h1>
<p class="sub">Live service state for this instance. No fabricated metrics.</p>
{''.join(alerts)}
<div class="grid">
    <div class="stat"><div class="label">Status</div><div class="value">{pill('online', 'ok')}</div></div>
    <div class="stat"><div class="label">Telegram</div><div class="value">{pill('connected' if telegram['connected'] else 'offline', 'ok' if telegram['connected'] else 'bad')}</div></div>
    <div class="stat"><div class="label">Uptime</div><div class="value">{esc(_duration(status['uptime']))}</div></div>
    <div class="stat"><div class="label">Plugins</div><div class="value">{plugins['loaded']} loaded</div></div>
    <div class="stat"><div class="label">Tasks</div><div class="value">{len(tasks['active'])} run / {len(tasks['queued'])} queue</div></div>
    <div class="stat"><div class="label">Version</div><div class="value">{esc(__version__)}</div></div>
</div>

<h2>Service</h2>
<div class="card">
<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Platform</td><td><code>{esc(status['platform'])}</code></td></tr>
<tr><td>Panel URL</td><td><code>{esc(status['panel_url'])}</code></td></tr>
<tr><td>Session backend</td><td><code>{esc(status['session_backend'])}</code></td></tr>
<tr><td>Telethon</td><td>{pill('available' if telegram['telethon_available'] else 'missing', 'ok' if telegram['telethon_available'] else 'bad')}</td></tr>
<tr><td>Prefix / theme</td><td><code>{esc(status['prefix'])}</code> / <code>{esc(status['theme'])}</code></td></tr>
<tr><td>Reminders pending</td><td>{status['counts']['reminders']}</td></tr>
<tr><td>Automation rules</td><td>{status['counts']['automations']}</td></tr>
<tr><td>Archive entries</td><td>{status['counts']['archive']}</td></tr>
</table>
</div>

<h2>Integrations</h2>
<div class="card">
<table>
<tr><th>Component</th><th>State</th><th>Detail</th></tr>
{integration_rows}
</table>
</div>

<h2>Active tasks</h2>
<div class="card">
<table>
<tr><th>Task</th><th>Kind</th><th>Status</th><th>Progress</th><th>Elapsed</th></tr>
{task_rows}
</table>
</div>

<h2>Recent errors</h2>
<div class="card">
<table>
<tr><th>Level</th><th>Message</th></tr>
{error_rows}
</table>
</div>
"""


# -------------------------------------------------------------------- plugins
def plugins(state: dict, csrf: str) -> str:
    status = state["plugins"]
    rows = []
    for plugin in status["plugins"]:
        manifest = plugin.get("manifest") or {}
        commands = ", ".join(plugin.get("commands") or []) or "-"
        permissions = ", ".join(manifest.get("permissions") or []) or "none"
        state_pill = {
            "loaded": pill("loaded", "ok"),
            "failed": pill("failed", "bad"),
            "disabled": pill("disabled", "off"),
        }.get(plugin["status"], pill(plugin["status"], "warn"))

        action = (
            f'<form method="POST" action="/plugins/toggle">{csrf_field(csrf)}'
            f'<input type="hidden" name="name" value="{esc(plugin["name"])}">'
            f'<input type="hidden" name="action" value="disable"><button class="danger">Disable</button></form>'
            if plugin["status"] == "loaded"
            else f'<form method="POST" action="/plugins/toggle">{csrf_field(csrf)}'
            f'<input type="hidden" name="name" value="{esc(plugin["name"])}">'
            f'<input type="hidden" name="action" value="enable"><button>Enable</button></form>'
        )
        rows.append(
            f"<tr><td><strong>{esc(plugin['name'])}</strong><br><span class=\"muted\">{esc(manifest.get('description', ''))}</span></td>"
            f"<td>{esc(manifest.get('version', '-'))}</td><td>{state_pill}</td>"
            f"<td><code>{esc(commands)}</code></td><td class=\"muted\">{esc(permissions)}</td>"
            f"<td>{action}</td></tr>"
            if plugin["status"] != "failed"
            else f"<tr><td><strong>{esc(plugin['name'])}</strong></td><td>-</td><td>{state_pill}</td>"
            f"<td colspan=\"3\" class=\"muted\">{esc(plugin.get('error', ''))}</td></tr>"
        )

    if not rows:
        rows.append('<tr><td colspan="6" class="muted">No plugins installed.</td></tr>')

    warnings = []
    for plugin in status["plugins"]:
        for note in plugin.get("warnings") or []:
            warnings.append(f"<li>{esc(plugin['name'])}: {esc(note)}</li>")
        if plugin.get("status") == "loaded":
            warnings.append(
                f"<li>{esc(plugin['name'])}: runs in-process and is not sandboxed.</li>"
            )

    capabilities = "".join(
        f"<li><code>{esc(name)}</code> - {esc(description)}</li>"
        for name, description in sorted(status["capabilities"].items())
    )

    return f"""
<h1>Plugins</h1>
<p class="sub">Manifest metadata is a consent mechanism. It is not a sandbox.</p>
<div class="card">
<table>
<tr><th>Plugin</th><th>Version</th><th>State</th><th>Commands</th><th>Capabilities</th><th>Action</th></tr>
{''.join(rows)}
</table>
</div>
<div class="card">
<h2 style="margin-top:0">Isolation notice</h2>
<ul class="muted" style="padding-left:1.2rem">
{''.join(warnings) or '<li>No warnings.</li>'}
</ul>
<p class="sub" style="margin-top:.8rem">Plugins execute inside the Reze process with the same privileges as the userbot.
Disabling a plugin removes its commands but cannot revoke permissions Python already granted it.</p>
</div>
<div class="card">
<h2 style="margin-top:0">Declared capabilities</h2>
<ul class="muted" style="padding-left:1.2rem">{capabilities}</ul>
</div>
"""


# ---------------------------------------------------------------------- tasks
def tasks(state: dict, csrf: str) -> str:
    snapshot = state["tasks"]
    rows = []
    for task in snapshot["active"] + snapshot["queued"] + snapshot["finished"]:
        cancel = ""
        if task["status"] in {"running", "queued"}:
            cancel = (
                f'<form method="POST" action="/tasks/cancel">{csrf_field(csrf)}'
                f'<input type="hidden" name="task_id" value="{esc(task["id"])}">'
                f'<button class="danger">Cancel</button></form>'
            )
        rows.append(
            f"<tr><td><code>{esc(task['id'])}</code></td><td>{esc(task['kind'])}</td>"
            f"<td>{esc(task['command'] or '-')}</td><td>{pill(task['status'], 'ok' if task['status'] == 'completed' else ('bad' if task['status'] in {'failed', 'timeout'} else 'warn'))}</td>"
            f"<td>{task['progress']}%</td><td>{task['elapsed']}s</td>"
            f"<td class=\"muted\">{esc(task['error'][:120] if task['error'] else task['detail'][:80])}</td>"
            f"<td>{cancel}</td></tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="8" class="muted">No tasks yet.</td></tr>')

    history = "".join(
        f"<tr><td><code>{esc(row['task_id'])}</code></td><td>{esc(row['kind'])}</td><td>{esc(row['status'])}</td>"
        f"<td>{row['duration_seconds']:.1f}s</td><td class=\"muted\">{esc(row['error'][:100])}</td></tr>"
        for row in state["task_history"]
    ) or '<tr><td colspan="5" class="muted">No completed tasks recorded.</td></tr>'

    return f"""
<h1>Tasks</h1>
<p class="sub">Concurrency {snapshot['concurrency']} · queue limit {snapshot['queue_limit']}.</p>
<div class="card">
<table>
<tr><th>Task</th><th>Kind</th><th>Command</th><th>Status</th><th>Progress</th><th>Elapsed</th><th>Detail</th><th></th></tr>
{''.join(rows)}
</table>
</div>
<h2>History</h2>
<div class="card">
<table>
<tr><th>Task</th><th>Kind</th><th>Status</th><th>Duration</th><th>Error</th></tr>
{history}
</table>
</div>
"""


# ------------------------------------------------------------------- settings
def settings_page(state: dict, csrf: str) -> str:
    prefs = state["prefs"]
    themes = "".join(
        f'<option value="{esc(name)}" {"selected" if name == prefs["theme"] else ""}>{esc(name)}</option>'
        for name in state["themes"]
    )
    providers = ["", "openai", "anthropic", "gemini", "openai_compatible"]
    provider_options = "".join(
        f'<option value="{esc(name)}" {"selected" if name == prefs["ai_provider"] else ""}>{esc(name or "not configured")}</option>'
        for name in providers
    )
    vision_options = "".join(
        f'<option value="{esc(name)}" {"selected" if name == prefs["ai_vision"] else ""}>{esc(name)}</option>'
        for name in ("auto", "on", "off")
    )
    language_options = "".join(
        f'<option value="{esc(code)}" {"selected" if code == prefs.get("language", "en") else ""}>'
        f'{esc(name)} ({esc(code)})</option>'
        for code, name in (state.get("languages") or {"en": "English"}).items()
    )
    feature_rows = []
    for feature in state.get("features") or []:
        if feature["enabled"]:
            action_html = (
                '<input type="hidden" name="action" value="disable">'
                '<button type="submit" class="secondary">Disable</button>'
            )
        else:
            confirm_html = (
                '<label class="sub"><input type="checkbox" name="confirm" value="1" required> '
                "I understand this is sensitive</label> "
                if feature["sensitive"]
                else ""
            )
            action_html = (
                '<input type="hidden" name="action" value="enable">'
                + confirm_html
                + '<button type="submit">Enable</button>'
            )
        feature_rows.append(
            "<tr>"
            f"<td><code>{esc(feature['key'])}</code>{' *' if feature['sensitive'] else ''}</td>"
            f"<td>{esc(feature['label'])}<br><span class=\"sub\">{esc(feature['description'])}</span></td>"
            f"<td>{pill('ON', 'ok') if feature['enabled'] else pill('OFF', 'off')}</td>"
            "<td><form method=\"POST\" action=\"/features/toggle\">"
            f"{csrf_field(csrf)}"
            f"<input type=\"hidden\" name=\"key\" value=\"{esc(feature['key'])}\">"
            f"{action_html}</form></td></tr>"
        )
    features_html = "".join(feature_rows) or "<tr><td colspan=\"4\">No features registered.</td></tr>"
    return f"""
<h1>Settings</h1>
<p class="sub">Validated server-side. Secrets are never rendered back to the browser.</p>
<div class="card">
<form method="POST" action="/settings/save">
{csrf_field(csrf)}
<div class="form-row">
    <div><label>Theme</label><select name="theme">{themes}</select></div>
    <div><label>Language</label><select name="language">{language_options}</select></div>
    <div><label>Command prefix</label><input name="prefix" value="{esc(prefs['prefix'])}" maxlength="2"></div>
    <div><label>Log level</label><input name="log_level" value="{esc(prefs['log_level'])}"></div>
</div>
<div class="form-row">
    <div><label>AI provider</label><select name="ai_provider">{provider_options}</select></div>
    <div><label>AI model</label><input name="ai_model" value="{esc(prefs['ai_model'])}"></div>
    <div><label>Vision</label><select name="ai_vision">{vision_options}</select></div>
</div>
<div class="form-row">
    <div><label>Media quality (1-100)</label><input name="media_quality" value="{esc(prefs['media_quality'])}"></div>
    <div><label>Media input limit (MB)</label><input name="media_max_input_mb" value="{esc(prefs['media_max_input_mb'])}"></div>
    <div><label>Always online</label>
        <select name="online_always">
            <option value="off" {"selected" if prefs.get('online_always') != '1' else ""}>off</option>
            <option value="on" {"selected" if prefs.get('online_always') == '1' else ""}>on</option>
        </select>
    </div>
</div>
<p class="sub" style="margin-top:.4rem">Always online refreshes the account status while Reze runs; it does not override your Telegram privacy settings.</p>
<div style="margin-top:1rem"><button type="submit">Save settings</button></div>
</form>
</div>

<h2>Runtime configuration</h2>
<div class="card">
<table>
<tr><th>Setting</th><th>Value</th></tr>
<tr><td>Task concurrency</td><td><code>{esc(state['limits']['concurrency'])}</code></td></tr>
<tr><td>Task queue limit</td><td><code>{esc(state['limits']['queue'])}</code></td></tr>
<tr><td>Task timeout</td><td><code>{esc(state['limits']['timeout'])}s</code></td></tr>
<tr><td>AI credential</td><td>{pill('configured', 'ok') if state['ai']['api_key_present'] else pill('missing', 'bad')}</td></tr>
<tr><td>AI base URL</td><td><code>{esc(state['ai']['base_url'] or 'default')}</code></td></tr>
<tr><td>Automation enabled</td><td>{pill('yes', 'ok') if state['limits']['automation'] else pill('no', 'off')}</td></tr>
</table>
<p class="sub" style="margin-top:.8rem">API keys, session strings and hashes are environment-only and are never stored in the browser-accessible database.</p>
</div>

<h2 id="features">Optional features</h2>
<div class="card">
<p class="sub">Every optional feature is OFF by default. Enabling one never enables another. * = sensitive, requires the confirmation checkbox.</p>
<table>
<tr><th>Key</th><th>Feature</th><th>State</th><th>Action</th></tr>
{features_html}
</table>
</div>
"""


# ----------------------------------------------------------------------- logs
def logs(state: dict, csrf: str) -> str:
    level = esc(state.get("log_filter", ""))
    rows = []
    for entry in state["logs"]:
        entries_level = esc(entry.get("level", "INFO"))
        if level and entries_level != level:
            continue
        stamp = time.strftime("%H:%M:%S", time.localtime(entry.get("created", time.time())))
        rows.append(
            f'<div><span class="muted">{stamp}</span> <span class="lvl {entries_level}">{entries_level}</span> '
            f'<span class="muted">{esc(entry.get("module", ""))}</span> {esc(entry.get("message", ""))}</div>'
        )
    body = "".join(rows) or '<div class="muted">No log entries for this filter.</div>'
    options = "".join(
        f'<option value="{name}" {"selected" if name == state.get("log_filter") else ""}>{name or "ALL"}</option>'
        for name in ("", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    )
    return f"""
<h1>Logs</h1>
<p class="sub">In-memory buffer, secrets masked by the logging filter.</p>
<div class="card">
<form method="GET" action="/logs">
    <div class="form-row">
        <div><label>Severity</label><select name="level">{options}</select></div>
        <div style="align-self:end"><button type="submit">Apply filter</button></div>
    </div>
</form>
<div class="log">{body}</div>
</div>
"""


# ------------------------------------------------------------------ productivity
def productivity(state: dict, csrf: str) -> str:
    notes = "".join(
        f"<tr><td><code>{esc(row['name'])}</code></td><td>{esc(row['content'][:140])}</td>"
        f'<td><form method="POST" action="/productivity/delete">{csrf_field(csrf)}'
        f'<input type="hidden" name="kind" value="note"><input type="hidden" name="key" value="{esc(row["name"])}">'
        f'<button class="danger">Delete</button></form></td></tr>'
        for row in state["notes"]
    ) or '<tr><td colspan="3" class="muted">No personal notes.</td></tr>'

    archive = "".join(
        f"<tr><td>#{row['id']}</td><td>{esc(row['kind'])}</td><td>{esc((row.get('title') or '')[:80])}</td>"
        f"<td class=\"muted\">{esc((row.get('content') or row.get('url') or '')[:100])}</td>"
        f'<td><form method="POST" action="/productivity/delete">{csrf_field(csrf)}'
        f'<input type="hidden" name="kind" value="archive"><input type="hidden" name="key" value="{row["id"]}">'
        f'<button class="danger">Delete</button></form></td></tr>'
        for row in state["archive"]
    ) or '<tr><td colspan="5" class="muted">The archive is empty.</td></tr>'

    reminders = "".join(
        f"<tr><td>#{row['id']}</td><td>{esc(row['text'][:80])}</td><td><code>{esc(row['due_at'])}</code> UTC</td>"
        f'<td><form method="POST" action="/productivity/delete">{csrf_field(csrf)}'
        f'<input type="hidden" name="kind" value="reminder"><input type="hidden" name="key" value="{row["id"]}">'
        f'<button class="danger">Cancel</button></form></td></tr>'
        for row in state["reminders"]
    ) or '<tr><td colspan="4" class="muted">No pending reminders.</td></tr>'

    return f"""
<h1>Personal archive</h1>
<p class="sub">Stored locally in SQLite. Deletion is immediate and permanent.</p>
<h2>Notes</h2>
<div class="card">
<table><tr><th>Name</th><th>Content</th><th></th></tr>{notes}</table>
</div>
<h2>Saved items</h2>
<div class="card">
<table><tr><th>ID</th><th>Type</th><th>Title</th><th>Detail</th><th></th></tr>{archive}</table>
</div>
<h2>Reminders</h2>
<div class="card">
<table><tr><th>ID</th><th>Text</th><th>Due</th><th></th></tr>{reminders}</table>
</div>
"""


# ------------------------------------------------------------------ automation
def automations(state: dict, csrf: str) -> str:
    rows = []
    for rule in state["rules"]:
        trigger = f"{rule['trigger_type']} {rule['trigger_config']}"
        actions = ", ".join(str(entry.get("type")) for entry in rule["actions"])
        toggle = (
            f'<form method="POST" action="/automations/toggle">{csrf_field(csrf)}'
            f'<input type="hidden" name="name" value="{esc(rule["name"])}">'
            f'<input type="hidden" name="action" value="{"disable" if rule["enabled"] else "enable"}">'
            f'<button>{"Disable" if rule["enabled"] else "Enable"}</button></form>'
        )
        delete = (
            f'<form method="POST" action="/automations/delete">{csrf_field(csrf)}'
            f'<input type="hidden" name="name" value="{esc(rule["name"])}">'
            f'<button class="danger">Delete</button></form>'
        )
        rows.append(
            f"<tr><td><code>{esc(rule['name'])}</code></td>"
            f"<td>{pill('enabled', 'ok') if rule['enabled'] else pill('disabled', 'off')}</td>"
            f"<td class=\"muted\">{esc(trigger)}</td><td class=\"muted\">{esc(actions)}</td>"
            f"<td>{rule['run_count']}</td><td class=\"actions\">{toggle}{delete}</td></tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6" class="muted">No automation rules yet.</td></tr>')

    return f"""
<h1>Automations</h1>
<p class="sub">Trigger → condition → action. Outbound actions require an owner-created rule.</p>
<div class="card">
<table><tr><th>Rule</th><th>State</th><th>Trigger</th><th>Actions</th><th>Runs</th><th></th></tr>{''.join(rows)}</table>
</div>
<h2>Create rule</h2>
<div class="card">
<form method="POST" action="/automations/create">
{csrf_field(csrf)}
<div class="form-row">
    <div><label>Name</label><input name="name" maxlength="40" required></div>
    <div><label>Trigger</label>
        <select name="trigger_type">
            <option value="schedule">schedule</option>
            <option value="interval">interval</option>
            <option value="keyword">keyword</option>
            <option value="task_failed">task failed</option>
        </select>
    </div>
    <div><label>At (HH:MM)</label><input name="at" placeholder="18:30"></div>
    <div><label>Interval (minutes)</label><input name="minutes" placeholder="60"></div>
    <div><label>Keyword</label><input name="keyword" placeholder="deploy"></div>
</div>
<div class="form-row">
    <div><label>Action</label>
        <select name="action_type">
            <option value="notify">notify</option>
            <option value="remind">remind</option>
            <option value="save">save</option>
            <option value="command">command</option>
        </select>
    </div>
    <div><label>Text (supports {{text}}, {{chat_id}}, {{sender_id}})</label><input name="action_text"></div>
    <div><label>Cooldown (seconds)</label><input name="cooldown" value="60"></div>
</div>
<div style="margin-top:1rem"><button type="submit">Create rule (disabled)</button></div>
</form>
</div>
"""


# --------------------------------------------------------------------- profile
def profile(state: dict, csrf: str) -> str:
    config = state["profile"]
    checked_name = "checked" if config.get("name_clock_enabled") else ""
    checked_bio = "checked" if config.get("bio_clock_enabled") else ""
    return f"""
<h1>Profile clock</h1>
<p class="sub">Updates the account name and bio on a schedule with FloodWait protection.</p>
<div class="card">
<form method="POST" action="/profile/save">
{csrf_field(csrf)}
<label><input type="checkbox" name="name_clock_enabled" value="1" {checked_name}> Clock in the display name</label>
<label><input type="checkbox" name="bio_clock_enabled" value="1" {checked_bio}> Clock in the bio</label>
<div class="form-row">
    <div><label>Timezone (IANA)</label><input name="timezone" value="{esc(config.get('timezone', 'UTC'))}"></div>
    <div><label>strftime format</label><input name="clock_format" value="{esc(config.get('clock_format', '%H:%M'))}"></div>
</div>
<div style="margin-top:1rem"><button type="submit">Save profile clock</button></div>
</form>
</div>
<div class="card">
<table>
<tr><th>Field</th><th>Value</th></tr>
<tr><td>Base name</td><td><code>{esc(config.get('original_name') or 'not set')}</code></td></tr>
<tr><td>Base bio</td><td><code>{esc(config.get('original_bio') or 'not set')}</code></td></tr>
<tr><td>Last update</td><td><code>{esc(config.get('last_updated') or 'never')}</code></td></tr>
</table>
</div>
"""


# ---------------------------------------------------------------------- groups
def groups(state: dict, csrf: str) -> str:
    rows = "".join(
        f"<tr><td><code>{row['chat_id']}</code></td><td>{esc(row.get('chat_title') or '-')}</td>"
        f"<td>{pill('on', 'ok') if row.get('antiflood_enabled') else pill('off', 'off')}</td>"
        f"<td>{pill('on', 'ok') if row.get('antiraid_enabled') else pill('off', 'off')}</td>"
        f"<td>{pill('on', 'ok') if row.get('antilink_enabled') else pill('off', 'off')}</td>"
        f"<td>{row.get('slowmode_seconds', 0)}s</td></tr>"
        for row in state["groups"]
    ) or '<tr><td colspan="6" class="muted">No groups are configured yet.</td></tr>'
    return f"""
<h1>Groups</h1>
<p class="sub">Groups are registered when Reze first sees them.</p>
<div class="card">
<table>
<tr><th>Chat ID</th><th>Title</th><th>Anti-flood</th><th>Anti-raid</th><th>Anti-link</th><th>Slow mode</th></tr>
{rows}
</table>
</div>
"""


# --------------------------------------------------------------------- filters
def filters(state: dict, csrf: str) -> str:
    rows = "".join(
        f"<tr><td><code>{esc(row['keyword'])}</code></td><td>{esc(row['reply_text'][:120])}</td><td><code>{row['chat_id']}</code></td></tr>"
        for row in state["filters"]
    ) or '<tr><td colspan="3" class="muted">No filters configured.</td></tr>'
    return f"""
<h1>Filters</h1>
<p class="sub">Automatic replies, managed per group. Manage them in Telegram with .filter.</p>
<div class="card">
<table><tr><th>Keyword</th><th>Reply</th><th>Chat</th></tr>{rows}</table>
</div>
"""


# -------------------------------------------------------------------- security
def security(state: dict, csrf: str) -> str:
    rows = "".join(
        f"<tr><td><code>{row['chat_id']}</code></td>"
        f"<td>{pill('on', 'ok') if row.get('antiflood_enabled') else pill('off', 'off')}</td>"
        f"<td>{row.get('antiflood_limit', 0)} / {row.get('antiflood_seconds', 0)}s</td>"
        f"<td>{esc(row.get('antiflood_action', 'mute'))}</td>"
        f"<td>{pill('on', 'ok') if row.get('antiraid_enabled') else pill('off', 'off')}</td></tr>"
        for row in state["groups"]
    ) or '<tr><td colspan="5" class="muted">No security settings recorded.</td></tr>'
    return f"""
<h1>Security</h1>
<p class="sub">Anti-flood and anti-raid configuration per group.</p>
<div class="card">
<table><tr><th>Chat</th><th>Anti-flood</th><th>Limit / window</th><th>Action</th><th>Anti-raid</th></tr>{rows}</table>
</div>
<div class="card">
<h2 style="margin-top:0">Panel protection</h2>
<ul class="muted" style="padding-left:1.2rem">
<li>Session cookies are HttpOnly and SameSite=Lax (Secure behind HTTPS).</li>
<li>Every POST requires a session-bound CSRF token.</li>
<li>Login attempts are rate limited per client address.</li>
<li>Panel binds to loopback by default; proxy headers are ignored unless enabled.</li>
</ul>
</div>
"""


STYLE_TEXT = {
    "en": {
        "title": "Style Assistant",
        "sub": "Learns your own writing style. Drafts wait for your approval. Automatic replies are always labelled as automated.",
        "status": "Status",
        "feature": "Feature",
        "auto": "Automatic replies",
        "learned": "Learned messages",
        "replies24": "Automatic replies in the last 24 hours",
        "profile": "Your style",
        "not_enabled": "The feature is OFF. Turn it on below, or with .features enable style_assistant confirm.",
        "enable": "Enable feature",
        "confirm": "I understand that drafts and automatic replies are sent from my account",
        "on": "ON",
        "off": "OFF",
        "turn_on": "Turn auto-reply on",
        "turn_off": "Turn auto-reply off",
        "settings": "Settings",
        "quiet_start": "Quiet hours start (HH:MM)",
        "quiet_end": "Quiet hours end (HH:MM)",
        "timezone": "Timezone",
        "cooldown": "Cooldown per chat (hours)",
        "cap": "Hourly cap (all chats)",
        "active": "Skip if you were active in the chat within (minutes)",
        "language": "Language of the label and prompts",
        "save": "Save settings",
        "allowed": "Allowed private chats",
        "allowed_empty": "No chats allowed. Add one with .style auto allow @username in Telegram.",
        "remove": "Remove",
        "drafts": "Pending drafts",
        "drafts_empty": "No pending drafts. Create one with .style draft as a reply in Telegram.",
        "drafts_note": "Send a draft from Telegram with .style send <id>. The panel cannot send messages.",
        "forget": "Forget everything",
        "forget_note": "Deletes learned messages, profile, drafts, the allow list and the auto-reply log, and turns auto-reply off.",
        "forget_button": "Delete everything learned",
        "telegram_only": "Learning from chats, adding allowed chats and sending drafts need the live Telegram connection, so they stay in the commands.",
        "learn_hint": ".style learn @username 200",
    },
    "fa": {
        "title": "دستیار سبک نوشتن",
        "sub": "سبک نوشتن خودِ شما را یاد می‌گیرد. پیش‌نویس‌ها منتظر تأیید شما می‌مانند. پاسخ‌های خودکار همیشه با برچسب «خودکار» ارسال می‌شوند.",
        "status": "وضعیت",
        "feature": "قابلیت",
        "auto": "پاسخ خودکار",
        "learned": "پیام‌های یادگرفته‌شده",
        "replies24": "پاسخ‌های خودکار در ۲۴ ساعت گذشته",
        "profile": "سبک شما",
        "not_enabled": "این قابلیت خاموش است. از پایین روشنش کنید یا با دستور .features enable style_assistant confirm.",
        "enable": "روشن کردن قابلیت",
        "confirm": "می‌پذیرم که پیش‌نویس‌ها و پاسخ‌های خودکار از حساب من ارسال می‌شوند",
        "on": "روشن",
        "off": "خاموش",
        "turn_on": "روشن کردن پاسخ خودکار",
        "turn_off": "خاموش کردن پاسخ خودکار",
        "settings": "تنظیمات",
        "quiet_start": "شروع ساعت سکوت (HH:MM)",
        "quiet_end": "پایان ساعت سکوت (HH:MM)",
        "timezone": "منطقهٔ زمانی",
        "cooldown": "فاصلهٔ هر گفتگو (ساعت)",
        "cap": "سقف ساعتی (همهٔ گفتگوها)",
        "active": "اگر در این گفتگو در این مدت (دقیقه) فعال بودید، پاسخ نده",
        "language": "زبان برچسب و دستورها",
        "save": "ذخیرهٔ تنظیمات",
        "allowed": "گفتگوهای خصوصی مجاز",
        "allowed_empty": "گفتگوی مجازی وجود ندارد. با دستور .style auto allow @username در تلگرام اضافه کنید.",
        "remove": "حذف",
        "drafts": "پیش‌نویس‌های در انتظار",
        "drafts_empty": "پیش‌نویسی در انتظار نیست. با .style draft در تلگرام یکی بسازید.",
        "drafts_note": "پیش‌نویس را از تلگرام با .style send <id> بفرستید. پنل نمی‌تواند پیام بفرستد.",
        "forget": "فراموش کردن همه‌چیز",
        "forget_note": "پیام‌های یادگرفته‌شده، سبک، پیش‌نویس‌ها، فهرست مجاز و گزارش پاسخ‌ها حذف می‌شوند و پاسخ خودکار خاموش می‌شود.",
        "forget_button": "حذف همهٔ داده‌های یادگرفته‌شده",
        "telegram_only": "یادگیری از گفتگوها، افزودن گفتگوی مجاز و ارسال پیش‌نویس به اتصال زندهٔ تلگرام نیاز دارد و در دستورها باقی می‌ماند.",
        "learn_hint": ".style learn @username 200",
    },
}


def style_page(state: dict, csrf: str, language: str = "en") -> str:
    t = STYLE_TEXT.get(language, STYLE_TEXT["en"])
    rtl = language == "fa"
    yes_no = lambda flag: pill(t["on"] if flag else t["off"], "ok" if flag else "off")  # noqa: E731

    banner_html = ""
    if state.get("message"):
        banner_html = f'<div class="card"><strong>{esc(state["message"])}</strong></div>'
    if state.get("error"):
        banner_html = f'<div class="card"><strong class="danger">{esc(state["error"])}</strong></div>'

    feature_block = ""
    if not state["feature_on"]:
        feature_block = (
            f'<div class="card"><p class="muted">{esc(t["not_enabled"])}</p>'
            f'<form method="POST" action="/features/toggle">{csrf_field(csrf)}'
            f'<input type="hidden" name="key" value="style_assistant">'
            f'<input type="hidden" name="action" value="enable">'
            f'<label><input type="checkbox" name="confirm" value="yes"> {esc(t["confirm"])}</label>'
            f'<button>{esc(t["enable"])}</button></form></div>'
        )

    s = state["settings"]
    auto_toggle = (
        f'<form method="POST" action="/style/auto">{csrf_field(csrf)}'
        f'<input type="hidden" name="action" value="{"off" if s["auto_enabled"] else "on"}">'
        f'<button class="{"danger" if s["auto_enabled"] else ""}">'
        f'{esc(t["turn_off"] if s["auto_enabled"] else t["turn_on"])}</button></form>'
    )

    profile_items = "".join(f"<li>{esc(line)}</li>" for line in state["profile_lines"])

    allowed_rows = "".join(
        f"<tr><td>{esc(row.get('title') or row['chat_id'])}</td>"
        f"<td class=\"muted\">{esc(row.get('last_reply_at') or '—')}</td>"
        f'<td><form method="POST" action="/style/block">{csrf_field(csrf)}'
        f'<input type="hidden" name="chat_id" value="{esc(row["chat_id"])}">'
        f'<button class="danger">{esc(t["remove"])}</button></form></td></tr>'
        for row in state["allowed"]
    ) or f'<tr><td colspan="3" class="muted">{esc(t["allowed_empty"])}</td></tr>'

    draft_rows = "".join(
        f"<tr><td><code>#{esc(row['id'])}</code></td><td class=\"muted\">{esc(row['chat_id'])}</td>"
        f"<td class=\"muted\">{esc(row['created_at'])}</td><td>{esc(row['draft'])}</td></tr>"
        for row in state["drafts"]
    ) or f'<tr><td colspan="4" class="muted">{esc(t["drafts_empty"])}</td></tr>'

    def field(name, label, value, kind="text"):
        return (
            f'<label>{esc(label)}<input type="{kind}" name="{name}" value="{esc(value)}"></label>'
        )

    language_options = "".join(
        f'<option value="{code}"{" selected" if s["language"] == code else ""}>{name}</option>'
        for code, name in (("en", "English"), ("fa", "فارسی"))
    )

    settings_form = (
        f'<form method="POST" action="/style/settings">{csrf_field(csrf)}'
        + field("quiet_start", t["quiet_start"], s.get("quiet_start") or "")
        + field("quiet_end", t["quiet_end"], s.get("quiet_end") or "")
        + field("timezone", t["timezone"], s.get("timezone") or "UTC")
        + field("cooldown_hours", t["cooldown"], s.get("cooldown_hours") or 6, "number")
        + field("hourly_cap", t["cap"], s.get("hourly_cap") or 10, "number")
        + field("owner_active_minutes", t["active"], s.get("owner_active_minutes") or 30, "number")
        + f'<label>{esc(t["language"])}<select name="language">{language_options}</select></label>'
        + f'<button>{esc(t["save"])}</button></form>'
    )

    body = f"""
<div class="{'rtl' if rtl else ''}">
<h1>{esc(t["title"])}</h1>
<p class="sub">{esc(t["sub"])}</p>
{banner_html}
{feature_block}
<div class="card">
<h2>{esc(t["status"])}</h2>
<table>
<tr><td>{esc(t["feature"])}</td><td>{yes_no(state["feature_on"])}</td></tr>
<tr><td>{esc(t["auto"])}</td><td>{yes_no(s["auto_enabled"])} {auto_toggle}</td></tr>
<tr><td>{esc(t["learned"])}</td><td>{esc(state["samples"])}</td></tr>
<tr><td>{esc(t["replies24"])}</td><td>{esc(state["replies_24h"])}</td></tr>
</table>
<p class="muted">{esc(t["telegram_only"])} <code>{esc(t["learn_hint"])}</code></p>
</div>
<div class="card"><h2>{esc(t["profile"])}</h2><ul>{profile_items}</ul></div>
<div class="card"><h2>{esc(t["settings"])}</h2>{settings_form}</div>
<div class="card"><h2>{esc(t["allowed"])}</h2>
<table><tr><th>Chat</th><th>Last reply</th><th></th></tr>{allowed_rows}</table></div>
<div class="card"><h2>{esc(t["drafts"])}</h2>
<p class="muted">{esc(t["drafts_note"])}</p>
<table><tr><th>ID</th><th>Chat</th><th>Created (UTC)</th><th>Draft</th></tr>{draft_rows}</table></div>
<div class="card danger-zone"><h2>{esc(t["forget"])}</h2>
<p class="muted">{esc(t["forget_note"])}</p>
<form method="POST" action="/style/forget">{csrf_field(csrf)}
<label><input type="checkbox" name="confirm" value="yes"> {esc(t["confirm"])}</label>
<button class="danger">{esc(t["forget_button"])}</button></form></div>
</div>
"""
    return body


DIGEST_TEXT = {
    "en": {
        "title": "Channel Digest",
        "sub": "Summaries of the channels you select, sent to your Saved Messages at the time you choose. Off until you turn it on.",
        "feature": "Feature", "digest": "Digest", "paused": "Paused", "ai": "AI summaries",
        "next": "Next digest", "last": "Last run", "pending": "Undelivered digests",
        "on": "ON", "off": "OFF", "yes": "yes", "no": "no",
        "not_enabled": "The feature is OFF. Enable it below, or with .features enable channel_digest confirm.",
        "enable": "Enable feature",
        "confirm": "I understand that digests are built from the channels I select and sent to my Saved Messages",
        "turn_on": "Turn digest on", "turn_off": "Turn digest off",
        "pause": "Pause scheduled digests", "resume": "Resume scheduled digests",
        "ai_on": "Turn AI summaries on", "ai_off": "Turn AI summaries off",
        "ai_note": "The AI provider is chosen in the AI settings. Turning AI on or off here only affects this digest.",
        "settings": "Schedule and limits",
        "time": "Delivery time (HH:MM)", "timezone": "Timezone", "schedule": "Schedule",
        "days": "Days (for weekly or custom: e.g. fri or mon,thu)", "max_messages": "Posts per digest",
        "max_chars": "Digest length (characters)", "language": "Language", "save": "Save settings",
        "run": "Generate now", "run_note": "Sends one digest on the next check (about a minute). Works while scheduled digests are paused.",
        "channels": "Selected channels", "search": "Search channels", "search_button": "Search",
        "priority": "Priority (1 = first)", "include": "Include keywords", "exclude": "Exclude keywords",
        "enabled": "Read this channel", "save_channel": "Save", "remove": "Remove",
        "channels_empty": "No channels selected. Add one in Telegram with .digest add @channel.",
        "history": "Recent runs", "history_empty": "No digests yet.",
        "clear": "Delete digest history", "clear_note": "Deletes run history and any digest text not yet delivered. Channel selections are kept.",
        "clear_button": "Delete history",
        "telegram_only": "Adding channels and reading their posts need the live Telegram connection, so they stay in the commands.",
    },
    "fa": {
        "title": "خلاصهٔ کانال‌ها",
        "sub": "خلاصهٔ کانال‌های انتخابی شما، در زمانی که تعیین می‌کنید به پیام‌های ذخیره‌شده فرستاده می‌شود. تا روشن نکنید خاموش است.",
        "feature": "قابلیت", "digest": "خلاصه", "paused": "متوقف", "ai": "خلاصهٔ هوش مصنوعی",
        "next": "خلاصهٔ بعدی", "last": "آخرین اجرا", "pending": "خلاصه‌های ارسال‌نشده",
        "on": "روشن", "off": "خاموش", "yes": "بله", "no": "خیر",
        "not_enabled": "این قابلیت خاموش است. از پایین روشنش کنید یا با .features enable channel_digest confirm.",
        "enable": "روشن کردن قابلیت",
        "confirm": "می‌پذیرم که خلاصه‌ها از کانال‌های انتخابی من ساخته و به پیام‌های ذخیره‌شده فرستاده می‌شوند",
        "turn_on": "روشن کردن خلاصه", "turn_off": "خاموش کردن خلاصه",
        "pause": "توقف خلاصه‌های زمان‌بندی‌شده", "resume": "ادامهٔ خلاصه‌های زمان‌بندی‌شده",
        "ai_on": "روشن کردن خلاصهٔ هوش مصنوعی", "ai_off": "خاموش کردن خلاصهٔ هوش مصنوعی",
        "ai_note": "ارائه‌دهندهٔ هوش مصنوعی در تنظیمات هوش مصنوعی انتخاب می‌شود. این گزینه فقط بر همین خلاصه اثر دارد.",
        "settings": "زمان‌بندی و محدودیت‌ها",
        "time": "ساعت ارسال (HH:MM)", "timezone": "منطقهٔ زمانی", "schedule": "برنامه",
        "days": "روزها (برای هفتگی یا سفارشی: مثلاً fri یا mon,thu)", "max_messages": "تعداد پست در هر خلاصه",
        "max_chars": "طول خلاصه (نویسه)", "language": "زبان", "save": "ذخیرهٔ تنظیمات",
        "run": "ساخت همین حالا", "run_note": "یک خلاصه در بررسی بعدی (حدود یک دقیقه) ارسال می‌شود. حتی وقتی زمان‌بندی متوقف است کار می‌کند.",
        "channels": "کانال‌های انتخابی", "search": "جست‌وجوی کانال", "search_button": "جست‌وجو",
        "priority": "اولویت (۱ = اول)", "include": "واژه‌های الزامی", "exclude": "واژه‌های حذفی",
        "enabled": "خواندن این کانال", "save_channel": "ذخیره", "remove": "حذف",
        "channels_empty": "کانالی انتخاب نشده. در تلگرام با .digest add @channel اضافه کنید.",
        "history": "اجراهای اخیر", "history_empty": "هنوز خلاصه‌ای نیست.",
        "clear": "حذف تاریخچهٔ خلاصه", "clear_note": "تاریخچهٔ اجرا و متن خلاصه‌های ارسال‌نشده حذف می‌شود. انتخاب کانال‌ها نگه داشته می‌شود.",
        "clear_button": "حذف تاریخچه",
        "telegram_only": "افزودن کانال و خواندن پست‌ها به اتصال زندهٔ تلگرام نیاز دارد و در دستورها باقی می‌ماند.",
    },
}


def digest_page(state: dict, csrf: str, language: str = "en") -> str:
    t = DIGEST_TEXT.get(language, DIGEST_TEXT["en"])
    rtl = language == "fa"
    cfg = state["config"]
    flag = lambda on: pill(t["on"] if on else t["off"], "ok" if on else "off")  # noqa: E731

    banner_html = ""
    if state.get("message"):
        banner_html = f'<div class="card"><strong>{esc(state["message"])}</strong></div>'
    if state.get("error"):
        banner_html = f'<div class="card"><strong class="danger">{esc(state["error"])}</strong></div>'

    feature_block = ""
    if not state["feature_on"]:
        feature_block = (
            f'<div class="card"><p class="muted">{esc(t["not_enabled"])}</p>'
            f'<form method="POST" action="/features/toggle">{csrf_field(csrf)}'
            f'<input type="hidden" name="key" value="channel_digest">'
            f'<input type="hidden" name="action" value="enable">'
            f'<label><input type="checkbox" name="confirm" value="yes"> {esc(t["confirm"])}</label>'
            f'<button>{esc(t["enable"])}</button></form></div>'
        )

    def toggle_button(name, on, on_label, off_label):
        return (
            f'<form method="POST" action="/digest/toggle">{csrf_field(csrf)}'
            f'<input type="hidden" name="name" value="{name}">'
            f'<input type="hidden" name="value" value="{"off" if on else "on"}">'
            f'<button class="{"danger" if on else ""}">{esc(off_label if on else on_label)}</button></form>'
        )

    controls = (
        toggle_button("enabled", cfg["enabled"], t["turn_on"], t["turn_off"])
        + toggle_button("paused", not cfg["paused"], t["pause"], t["resume"])
        + toggle_button("ai_enabled", cfg["ai_enabled"], t["ai_on"], t["ai_off"])
    )

    run_form = (
        f'<form method="POST" action="/digest/run">{csrf_field(csrf)}<button>{esc(t["run"])}</button></form>'
        if cfg["enabled"] else ""
    )

    def field(name, label, value, kind="text"):
        return f'<label>{esc(label)}<input type="{kind}" name="{name}" value="{esc(value)}"></label>'

    days_value = "" if cfg["schedule"] == "daily" else cfg["days"]
    language_options = "".join(
        f'<option value="{code}"{" selected" if cfg["language"] == code else ""}>{name}</option>'
        for code, name in (("en", "English"), ("fa", "فارسی"))
    )
    schedule_options = "".join(
        f'<option value="{code}"{" selected" if cfg["schedule"] == code else ""}>{code}</option>'
        for code in ("daily", "weekly", "custom")
    )
    settings_form = (
        f'<form method="POST" action="/digest/settings">{csrf_field(csrf)}'
        + field("time_of_day", t["time"], cfg["time_of_day"])
        + field("timezone", t["timezone"], cfg["timezone"])
        + f'<label>{esc(t["schedule"])}<select name="schedule">{schedule_options}</select></label>'
        + field("days", t["days"], days_value)
        + field("max_messages", t["max_messages"], cfg["max_messages"], "number")
        + field("max_chars", t["max_chars"], cfg["max_chars"], "number")
        + f'<label>{esc(t["language"])}<select name="language">{language_options}</select></label>'
        + f'<button>{esc(t["save"])}</button></form>'
    )

    search_form = (
        f'<form method="GET" action="/digest">'
        f'<input type="text" name="q" value="{esc(state["search"])}" placeholder="{esc(t["search"])}">'
        f'<button>{esc(t["search_button"])}</button></form>'
    )

    channel_rows = []
    for row in state["channels"]:
        handle = f"@{row['username']}" if row.get("username") else str(row["chat_id"])
        channel_rows.append(
            f'<tr><td>{esc(row.get("title") or handle)}<div class="muted">{esc(handle)}</div></td>'
            f'<td colspan="4"><form method="POST" action="/digest/channel" class="inline">{csrf_field(csrf)}'
            f'<input type="hidden" name="chat_id" value="{esc(row["chat_id"])}">'
            f'<label>{esc(t["priority"])} <input type="number" min="1" max="10" name="priority" value="{esc(row["priority"])}"></label>'
            f'<label>{esc(t["include"])} <input type="text" name="include_keywords" value="{esc(row["include_keywords"])}"></label>'
            f'<label>{esc(t["exclude"])} <input type="text" name="exclude_keywords" value="{esc(row["exclude_keywords"])}"></label>'
            f'<label><input type="checkbox" name="enabled" value="1"{" checked" if row["enabled"] else ""}> {esc(t["enabled"])}</label>'
            f'<button>{esc(t["save_channel"])}</button></form>'
            f'<div class="muted">last sync: {esc(row.get("last_synced_at") or "—")}</div></td>'
            f'<td><form method="POST" action="/digest/channel/remove">{csrf_field(csrf)}'
            f'<input type="hidden" name="chat_id" value="{esc(row["chat_id"])}">'
            f'<button class="danger">{esc(t["remove"])}</button></form></td></tr>'
        )
    channels_html = "".join(channel_rows) or (
        f'<tr><td colspan="6" class="muted">{esc(t["channels_empty"])}</td></tr>'
    )

    run_rows = "".join(
        f"<tr><td><code>#{esc(r['id'])}</code></td><td>{esc(r['kind'])}</td><td>{esc(r['status'])}</td>"
        f"<td>{esc(r['message_count'])}</td><td>{esc(r['summary_mode'] or '—')}</td>"
        f"<td class=\"muted\">{esc(r['finished_at'] or r['created_at'])}</td>"
        f"<td class=\"muted\">{esc(r['last_error'] or '')}</td></tr>"
        for r in state["runs"]
    ) or f'<tr><td colspan="7" class="muted">{esc(t["history_empty"])}</td></tr>'

    last = state["last_run"]
    last_text = f"{last['status']} · {last['finished_at'] or last['created_at']}" if last else "—"
    body = f"""
<div class="{'rtl' if rtl else ''}">
<h1>{esc(t["title"])}</h1>
<p class="sub">{esc(t["sub"])}</p>
{banner_html}
{feature_block}
<div class="card">
<table>
<tr><td>{esc(t["feature"])}</td><td>{flag(state["feature_on"])}</td></tr>
<tr><td>{esc(t["digest"])}</td><td>{flag(cfg["enabled"])} {"<span class='pill off'>" + esc(t["paused"]) + "</span>" if cfg["paused"] and cfg["enabled"] else ""}</td></tr>
<tr><td>{esc(t["ai"])}</td><td>{flag(cfg["ai_enabled"])}</td></tr>
<tr><td>{esc(t["next"])}</td><td>{esc(state["next_slot"] or "—")}</td></tr>
<tr><td>{esc(t["last"])}</td><td>{esc(last_text)}</td></tr>
<tr><td>{esc(t["pending"])}</td><td>{esc(state["pending"])}</td></tr>
</table>
<div class="actions">{controls}</div>
<p class="muted">{esc(t["ai_note"])}</p>
</div>
<div class="card"><h2>{esc(t["run"])}</h2>
<p class="muted">{esc(t["run_note"])}</p>{run_form}</div>
<div class="card"><h2>{esc(t["settings"])}</h2>{settings_form}</div>
<div class="card"><h2>{esc(t["channels"])} ({esc(state["channel_total"])})</h2>
{search_form}
<table><tr><th>Channel</th><th colspan="4"></th><th></th></tr>{channels_html}</table>
<p class="muted">{esc(t["telegram_only"])}</p></div>
<div class="card"><h2>{esc(t["history"])}</h2>
<table><tr><th>ID</th><th>Kind</th><th>Status</th><th>Posts</th><th>Summary</th><th>Time (UTC)</th><th>Note</th></tr>{run_rows}</table></div>
<div class="card danger-zone"><h2>{esc(t["clear"])}</h2>
<p class="muted">{esc(t["clear_note"])}</p>
<form method="POST" action="/digest/clear">{csrf_field(csrf)}
<label><input type="checkbox" name="confirm" value="yes"> {esc(t["clear"])}</label>
<button class="danger">{esc(t["clear_button"])}</button></form></div>
</div>
"""
    return body



CONSENT_TEXT = {
    "en": {"title": "Consent", "sub": "Nothing leaves Reze without your consent. You can revoke any of these at any time.",
           "granted": "Granted", "not_granted": "Not granted", "grant": "Grant", "revoke": "Revoke", "since": "since"},
    "fa": {"title": "رضایت", "sub": "بدون رضایت شما چیزی از ریزه خارج نمی‌شود. هر کدام را هر وقت خواستی لغو کن.",
           "granted": "داده شده", "not_granted": "داده نشده", "grant": "اجازه می‌دهم", "revoke": "لغو", "since": "از"},
}


def consent_page(rows: list, csrf: str, language: str = "en", message: str = "", error: str = "") -> str:
    t = CONSENT_TEXT.get(language, CONSENT_TEXT["en"])
    rtl = language == "fa"
    banner = ""
    if message:
        banner = f'<div class="card"><strong>{esc(message)}</strong></div>'
    if error:
        banner = f'<div class="card"><strong class="danger">{esc(error)}</strong></div>'
    cards = []
    for row in rows:
        label = row["label_fa"] if rtl else row["label_en"]
        detail = row["detail_fa"] if rtl else row["detail_en"]
        state = t["granted"] if row["granted"] else t["not_granted"]
        since = f' <span class="muted">{esc(t["since"])} {esc(row["at"])}</span>' if row.get("at") else ""
        if row["granted"]:
            action_path, action_label, css = "/consent/revoke", t["revoke"], "danger"
        else:
            action_path, action_label, css = "/consent/grant", t["grant"], ""
        cards.append(
            f'<div class="card"><h2>{esc(label)}</h2><p class="muted">{esc(detail)}</p>'
            f'<p>{pill(state, "ok" if row["granted"] else "off")}{since}</p>'
            f'<form method="POST" action="{action_path}">{csrf_field(csrf)}'
            f'<input type="hidden" name="scope" value="{esc(row["scope"])}">'
            f'<button class="{css}">{esc(action_label)}</button></form></div>'
        )
    return f"""
<div class="{'rtl' if rtl else ''}">
<h1>{esc(t["title"])}</h1>
<p class="sub">{esc(t["sub"])}</p>
{banner}
{''.join(cards)}
</div>
"""
