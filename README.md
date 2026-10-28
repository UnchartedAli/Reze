# REZE 2.0 — Personal Telegram Operating System

A Telegram **userbot platform** built on Telethon: an Extreme-ASCII message
engine, a media studio, a multi-provider AI gateway, personal productivity
tools, an automation engine, a manifest-validated plugin system and a
dependency-free web control panel.

Version **2.0.0** · Author **UnchartedAli** · Channel [@yamods](https://t.me/yamods) · MIT

```
██████╗ ███████╗███████╗███████╗
██╔══██╗██╔════╝╚══███╔╝██╔════╝
██████╔╝█████╗    ███╔╝ █████╗
██╔══██╗██╔══╝   ███╔╝  ██╔══╝
██║  ██║███████╗███████╗███████╗
╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝
   PERSONAL TELEGRAM OS  //  v2.0.0
```

---

## What is Reze?

Reze logs in as **your own Telegram account** (a userbot) and exposes a dot
command interface plus a web panel. It is designed as a personal operating
system for Telegram: convert media, generate sticker packs, run AI commands,
schedule reminders, automate small workflows, and inspect everything from a
terminal-styled control panel.

Everything is English-only, every message is rendered by one shared ASCII
engine, and optional integrations (AI, FFmpeg, background removal) degrade
gracefully instead of breaking the core commands.

## Highlights

- **Extreme-ASCII message engine** — CYBER / GHOST / TERMINAL / COMPACT themes,
  framed panels, status tags, progress bars, tables, safe message splitting.
- **REZE Studio** — image resize/compress/caption/meme/thumbnail, real 512×512
  WebP static sticker conversion, real Telegram sticker-set creation, GIF and
  video/audio conversion through FFmpeg, background removal through a configured
  provider.
- **REZE Intelligence** — OpenAI, Anthropic, Gemini and OpenAI-compatible
  endpoints behind one gateway with timeouts, bounded retries, explicit fallback
  and usage metadata. No provider SDK required.
- **Plugin ecosystem** — validated manifests, declared capabilities, dependency
  checks, duplicate-command detection, per-plugin settings, enable/disable with
  honest isolation limits.
- **Automation** — trigger → condition → action rules with cooldowns, hourly
  caps, recursion guards and an allowlisted internal command dispatcher.
- **Personal tools** — archive, notes, bookmarks, reminders, bounded chat search
  and a dependency-free QR generator.
- **Web panel** — real service state, plugin/task management, settings, logs,
  archive and automation editing; session auth, CSRF tokens, strict CSP, no
  JavaScript.
- **Task manager** — bounded concurrency, queue limits, per-task timeout,
  cancellation and progress reporting.

## Requirements

| Component | Requirement |
| --- | --- |
| Python | 3.11 or newer |
| Telegram | API id/hash from https://my.telegram.org and an authorized session |
| Images | `Pillow` (installed from `requirements.txt`) |
| Video/audio | **FFmpeg** on `PATH` (optional) — `winget install Gyan.FFmpeg` on Windows, `apt install ffmpeg` on Debian/Ubuntu |
| AI | An API key for one supported provider (optional) |

## Quick start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # then fill in the values
python scripts/generate_session.py    # creates a StringSession
# paste the printed string into REZE_SESSION_STRING in .env

python -m reze.app
```

The console prints the ASCII banner, the panel URL and the health endpoint.
Open `http://127.0.0.1:8080`, sign in with `REZE_PANEL_USERNAME` and the panel
password, then send `.help` to your own account from any chat.

> A userbot acts as **you**. Only run Reze on an account you own, and keep the
> session string and API hash private.

## Configuration

All settings use the `REZE_` prefix and are documented in
[`.env.example`](.env.example). The most important ones:

| Variable | Purpose |
| --- | --- |
| `REZE_API_ID`, `REZE_API_HASH` | Telegram application credentials |
| `REZE_OWNER_ID` | Account allowed to run owner-only commands |
| `REZE_SESSION_STRING` | Portable session (recommended on PaaS) |
| `REZE_PANEL_PASSWORD` / `REZE_PANEL_PASSWORD_HASH` | Panel login (exactly one) |
| `REZE_WEB_HOST`, `REZE_WEB_PORT` | Panel bind address (loopback by default) |
| `REZE_AI_PROVIDER`, `REZE_AI_MODEL`, `REZE_AI_API_KEY` | AI gateway |
| `REZE_MEDIA_MAX_INPUT_MB`, `REZE_MEDIA_QUALITY` | Media limits |
| `REZE_TASK_CONCURRENCY`, `REZE_TASK_QUEUE_LIMIT` | Background work limits |

Runtime preferences (theme, prefix, AI model, media defaults, log level) are
stored in SQLite and edited with `.config` or the panel. Secrets are
environment-only and are never rendered by the panel.

## Commands

Every command has usage help: `.help <command>`. Full reference:
[docs/COMMANDS.md](docs/COMMANDS.md).

| Family | Examples |
| --- | --- |
| Core | `.help` `.ping` `.status` `.info` `.stats` `.diagnostics` `.logs` |
| Appearance | `.theme` `.preview` `.config` `.prefix` |
| Presence | `.setonlinepermanently on/off/status` |
| Media | `.sticker` `.stickerpack` `.addsticker` `.resize` `.compress` `.meme` `.caption` `.thumbnail` `.gif` `.tovideo` `.toaudio` `.trim` `.speed` `.toimage` `.removebg` `.download` |
| AI | `.ai` `.summarize` `.translate` `.rewrite` `.digest` `.describe` `.aiinfo` |
| Personal | `.save` `.find` `.bookmark` `.notes` `.remind` `.schedule` `.search` `.links` `.files` `.qr` `.whois` `.chatinfo` `.id` |
| Tasks | `.queue` `.cancel` `.status` |
| Plugins | `.plugins` `.plugin` `.plugininfo` `.plugintemplate` |
| Automation | `.automation list/show/create/enable/disable/delete` |
| Groups | `.ban` `.kick` `.mute` `.warn` `.purge` `.pin` `.admins` `.tagall` `.antiflood` `.lock` `.filter` |

Long outputs are split automatically at Telegram's 4096-character limit, and
code spans are rebalanced so pagination never breaks Markdown parsing.

## Always-online presence

`.setonlinepermanently on` keeps the account showing as online while Reze runs:
the presence service refreshes `account.updateStatus(offline=False)` every
`REZE_PRESENCE_INTERVAL_SECONDS` (default 60s). It is off by default, owner-only,
persisted in SQLite, and survives restarts. `.setonlinepermanently off` returns
to normal Telegram presence; `.setonlinepermanently status` reports the refresh
count, last refresh, interval and any FloodWait cooldown. It cannot override
account privacy settings that hide "online" from other users.

## Media studio

- `.sticker` converts a replied image into a valid **512×512 WebP** static
  sticker (transparent padding, size checked).
- `.stickerpack <title> | <emoji>` asks for a confirmation code, then creates a
  real sticker set with `messages.CreateStickerSet` and reports the pack URL
  **only after Telegram confirms it**.
- `.addsticker <short_name> [emoji]` uses `messages.AddStickerToSet`.
- FFmpeg commands check for the binary before starting and explain how to
  install it when it is missing.
- Every conversion runs in an isolated temporary directory that is deleted in a
  `finally` block; input and output sizes are bounded by configuration.

## AI gateway

`.ai`, `.summarize`, `.translate`, `.rewrite`, `.digest` and `.describe` work
only when a provider is configured. Requests use the official HTTP APIs, honor
timeouts, retry only on rate limits/timeouts, and never log prompts or
responses. Vision is used only when the configured model is known to accept
images. Fallback is opt-in via `REZE_AI_FALLBACK` and is disclosed in the
response metadata (provider, model, duration, tokens). See
[docs/AI.md](docs/AI.md).

## Web panel

`python -m reze.app` also starts the panel (default `127.0.0.1:8080`).

- Dashboard: uptime, Telegram state, plugin/task counts, integration readiness,
  recent errors, deployment notes.
- Plugins: manifest metadata, declared capabilities, enable/disable, isolation
  warnings.
- Tasks: running/queued/finished tasks with cancellation.
- Settings: validated preferences (theme, prefix, AI model, media limits, log
  level).
- Logs: in-memory buffer with severity filter; secrets masked.
- Archive and automations: local notes/bookmarks/reminders and rule editing.

Security: session cookies are `HttpOnly; SameSite=Lax` (`Secure` over HTTPS),
every POST carries a session-bound CSRF token, bodies are size-limited, and the
panel binds to loopback unless configured otherwise. See
[docs/SECURITY.md](docs/SECURITY.md).

## Plugins

Drop a file in `reze/plugins/`, declare a `MANIFEST`, and restart (or
`.plugin enable <id>`). The manager validates the manifest, checks dependencies,
rejects duplicate commands, and isolates failures per plugin.

```python
MANIFEST = {
    "name": "My Plugin", "id": "my_plugin", "version": "1.0.0",
    "description": "Does one useful thing.",
    "commands": ["mycommand"],
    "permissions": ["telegram.message"],
    "min_reze_version": "2.0.0",
}
```

Full guide and template: [docs/PLUGIN_GUIDE.md](docs/PLUGIN_GUIDE.md) and
`.plugintemplate`.

**Isolation honesty:** plugins run in-process with the same privileges as
Reze. The manifest is a consent document, not a sandbox.

## Automation

Rules are persisted in SQLite and run as `trigger → conditions → actions`:
schedule, interval, keyword or failed-task triggers; save, remind, notify,
AI-summary or allowlisted-command actions. Rules are created disabled and must
be validated before enabling. Cooldowns, hourly caps and recursion guards apply.

```text
.automation create daily | trigger=schedule at=18:30 | action=notify text=Review the day
.automation enable daily
```

See [docs/AUTOMATION.md](docs/AUTOMATION.md).

## Testing

```bash
python -m unittest discover -s tests -v
```

The suite covers the ASCII engine, configuration, storage, auth and CSRF, the
task manager, confirmations, manifests and plugin isolation, media helpers,
sticker request construction with a fake client, AI adapters and error mapping,
the web panel over real HTTP, the QR encoder and the automation engine. It
requires no Telegram or paid AI credentials. Details and limitations:
[docs/TESTING.md](docs/TESTING.md).

## Project layout

```
reze/
  app.py             application wiring and lifecycle
  command_router.py  command registry, permissions, cooldowns, long replies
  plugin_manager.py  plugin lifecycle and settings
  config.py          settings and deployment detection
  ui/                ASCII engine and themes
  core/              task manager and confirmations
  media/             Pillow images, FFmpeg, sticker sets, workspaces
  ai/                provider adapters and gateway
  automation/        rule engine
  productivity/      QR generator, reminders
  commands/          command suites
  web/               panel server, pages, auth, theme
  plugins/           built-in example plugins
docs/                security, plugin, command, AI, automation, testing docs
tests/               unittest suite
```

## Known limitations

- No OS-level sandbox for third-party plugins (documented, not simulated).
- Animated/video sticker sets are not implemented; only the static WebP path.
- `.digest`, `.search` and `.links` are bounded scans, not full-history search.
- The QR generator covers byte mode, levels L/M and versions 1–10.
- FFmpeg is required for video/audio commands and is not bundled.

See [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## License and credits

MIT. Built by **UnchartedAli** — channel [@yamods](https://t.me/yamods).
