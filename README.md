# REZE 2.0 — Personal Telegram Operating System

A Telegram **userbot platform** built on Telethon: an Extreme-ASCII message
engine, a media studio, a multi-provider AI gateway, personal productivity
tools, an automation engine, a manifest-validated plugin system and a
dependency-free web control panel.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Telethon](https://img.shields.io/badge/built%20with-Telethon-2CA5E0?logo=telegram&logoColor=white)](https://github.com/LonamiWebs/Telethon)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Telegram channel](https://img.shields.io/badge/channel-%40yamods-2CA5E0?logo=telegram&logoColor=white)](https://t.me/yamods)

Version **2.0.0** · Author **UnchartedAli** · Channel [@yamods](https://t.me/yamods) · MIT

> **Self-hosted, terminal-styled Telegram userbot** — sticker/GIF studio, AI
> commands, message recovery, automation and a web panel. One process, SQLite,
> no cloud lock-in.

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

## Preview

Every reply is rendered by one shared engine, so all commands look the same.
These blocks are real output of `reze.ui.ascii`:

```text
╔══════════════════════════════════════╗
║ ◆ [ OK ] STICKER READY               ║
╠══════════════════════════════════════╣
║ Format : WEBP 512x512                ║
║ Size   : 38 KB                       ║
║ Status : SUCCESS                     ║
╚══════════════════════════════════════╝
```

```text
╔══════════════════════════════════════╗
║ ◆ DELETED MESSAGE                    ║
╠══════════════════════════════════════╣
║ From : Sara (@sara) [77]             ║
║ Chat : Team Chat (group)             ║
║ Sent : 2026-10-29 12:00:00           ║
║                                      ║
║ Meeting moved to 18:30               ║
╚══════════════════════════════════════╝
```

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
- **Message Guard** — saves deleted (and edited) messages of the chats you
  choose, including cached media, to Saved Messages. See [below](#message-guard).
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

### Docker

```bash
cp .env.example .env              # fill in the values
python scripts/generate_session.py   # run once, locally, to get REZE_SESSION_STRING
docker compose up -d --build
docker compose logs -f
```

More targets (systemd, Render, Railway, Fly.io, nginx): [DEPLOY.md](DEPLOY.md).

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
| Owner | `.owner` `.botinfo` `.exec` `.setvar` `.getvar` `.delvar` `.block` `.unblock` `.broadcast` `.update` |
| Group+ | `.promote` `.demote` `.hidetag` `.setdesc` `.settitle` `.invite` `.join` `.leave` |
| Download | `.yt` `.ytv` `.yta` `.song` `.ig` `.tt` `.fb` `.pinterest` `.mediafire` |
| Tools | `.weather` `.github` `.tts` `.url` `.sticker` / `.s` (images, GIFs, videos) |
| Fun | `.quote` `.joke` `.roast` `.ship` `.truth` `.dare` `.tictactoe` |
| Guard | `.watch on/off/add/del/list/private/groups/edits/media/dest/keep/clear` |
| Groups | `.ban` `.kick` `.mute` `.warn` `.purge` `.pin` `.admins` `.tagall` `.antiflood` `.lock` `.filter` |

Long outputs are split automatically at Telegram's 4096-character limit, and
code spans are rebalanced so pagination never breaks Markdown parsing.

## Message Guard

`.watch` keeps a short-lived local copy of messages from the chats you choose.
When one is **deleted** (or **edited**), the saved copy is sent to Saved Messages.
Small media (photos, videos, voice notes, files up to 25 MB) is cached right away,
because a deleted file can no longer be downloaded afterwards.

```text
.watch on                  enable the guard
.watch add                 watch the current chat   (or: .watch add <chat_id>)
.watch private on          watch every private chat
.watch groups on           watch every group
.watch edits on|off        also report edits (before / after)
.watch ttl on|off          save self-destructing (timed / view-once) media at once
.watch dest me|here|<id>   where reports go (default: Saved Messages)
.watch archive on|off|clear permanent local copy of deleted + timed media (default ON)
.watch keep 72|forever     how long the temporary cache is kept (default 48 h)
.watch list | status | clear | del
```

Self-destructing photos, videos and voice notes are copied to Saved Messages the moment they
arrive (`.watch ttl off` disables this). Messages removed by a chat's auto-delete timer are
recovered like any other deleted message. Your own messages are ignored unless you enable `.watch own on`. Everything that was delivered is also kept in a **permanent archive** (`data/msglog/archive/`, never
auto-deleted; `.watch archive clear` empties it). Only the temporary cache is purged automatically. Limits: it cannot recover messages that
were deleted while Reze was offline, secret chats are not visible to any userbot,
and nothing is saved for chats you did not select.

## Owner-only by design

Reze reacts **only to your own account**. If a stranger types `.something` in a group, they get no reply,
no error and no "unknown command" hint, so nobody knows a userbot is listening. Commands are never
exposed to other members. (`REZE_PUBLIC_COMMANDS=true` re-enables the old public behaviour.)
`.exec` is disabled until you set `REZE_ENABLE_EXEC=true`, and `.broadcast` needs a confirmation code.

Optional extras for downloads and speech: `pip install yt-dlp gTTS` (plus FFmpeg).

## Responsible use

- A userbot acts as **you**. Automation that spams, mass-messages or scrapes can
  get an account limited or banned by Telegram. Keep `.tagall`, broadcasts and
  automation rules conservative.
- Message Guard stores other people's messages (temporarily, on your machine) and keeps copies of
  media the sender set to self-destruct. Senders expect that media to disappear, so use `.watch ttl`
  only where that is acceptable, and tell people in shared groups.
  Check the privacy laws and chat rules that apply to you, and tell people if you
  run it in shared groups.
- Never share `REZE_SESSION_STRING`, `REZE_API_HASH` or your `.env`. Anyone with
  the session string controls your account.
- Reze is an independent project and is not affiliated with Telegram.

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

## Contributing

Issues and pull requests are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md)
first: it covers the dev setup, the test command and how to write a plugin.
Security problems: see [SECURITY.md](SECURITY.md) (please do not open a public issue).

## Documentation

[Commands](docs/COMMANDS.md) · [Plugin guide](docs/PLUGIN_GUIDE.md) ·
[AI](docs/AI.md) · [Automation](docs/AUTOMATION.md) ·
[Security](docs/SECURITY.md) · [Testing](docs/TESTING.md) ·
[Known limitations](docs/KNOWN_LIMITATIONS.md) · [Deploy](DEPLOY.md) ·
[Changelog](CHANGELOG.md)

## License and credits

MIT. Built by **UnchartedAli** — channel [@yamods](https://t.me/yamods).

If Reze is useful to you, a ⭐ on GitHub helps other people find it.
