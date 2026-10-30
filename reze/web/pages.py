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
