# REZE 3.0 — Your Personal Digital Operating System

A self-hosted **Telegram userbot** that runs as your own account: an
Extreme-ASCII message engine, a media studio, a multi-provider AI gateway,
persistent memory and personal knowledge tools, encrypted storage, a workflow
engine, optional integrations and a dependency-free web control panel. One
Python process and one SQLite file.

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Telethon](https://img.shields.io/badge/built%20with-Telethon-2CA5E0?logo=telegram&logoColor=white)](https://github.com/LonamiWebs/Telethon)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Telegram channel](https://img.shields.io/badge/channel-%40yamods-2CA5E0?logo=telegram&logoColor=white)](https://t.me/yamods)

Version **3.0.0** · Author **UnchartedAli** · Channel [@yamods](https://t.me/yamods) · MIT

> **اسناد فارسی:** [docs/README.fa.md](docs/README.fa.md) — راهنمای فارسی
> نصب، تنظیمات و شروع به کار.

```
██████╗ ███████╗███████╗███████╗
██╔══██╗██╔════╝╚══███╔╝██╔════╝
██████╔╝█████╗    ███╔╝ █████╗
██╔══██╗██╔══╝   ███╔╝  ██╔══╝
██║  ██║███████╗███████╗███████╗
╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝
   YOUR PERSONAL DIGITAL OS  //  v3.0.0
```

Every reply is rendered by one shared engine, so the whole product looks the
same. This is real output of `reze.ui.ascii`:

```text
╔══════════════════════════════════════╗
║ ◆ REZE 3.0                           ║
╠══════════════════════════════════════╣
║ Feature : memory                     ║
║ State   : OFF                        ║
║ Enable  : .features enable memory    ║
╠══════════════════════════════════════╣
║ UnchartedAli · @yamods               ║
╚══════════════════════════════════════╝
```

## What is Reze?

Reze logs in as **your own Telegram account** (a userbot) and exposes a dot
command interface plus a local web panel. It is built as a modular monolith:
172 commands share one router, one storage layer, one ASCII renderer and one
feature switch, so optional subsystems cannot leak into the core.

REZE 3.0 adds a second layer on top of the 2.0 Telegram toolkit: persistent
memory for the AI, a life graph, a personal CRM, a decision journal, focus
sessions, a timeline, writing analysis, projects/tasks/expenses, an encrypted
vault, a security sentinel, an insight engine, multi-model council answers,
persistent workflows, a smart inbox, universal search and voice/document
intelligence.

**Every optional feature is OFF by default.** Installing, migrating, restarting
or resetting a setting never turns one on. You enable features one at a time,
and sensitive features require an explicit confirmation word. Security checks
themselves are always active.

## Feature grid

| Area | What works | Default |
| --- | --- | --- |
| Core commands | help, status, diagnostics, logs, config, theme, tasks, plugins | always on |
| Media studio | 512×512 WebP stickers, real sticker sets, resize, compress, meme, GIF/video/audio via FFmpeg, background removal | always on |
| Message Guard | deleted/edited message recovery, self-destruct media copies, permanent local archive | always on |
| AI gateway | OpenAI, Anthropic, Gemini and OpenAI-compatible endpoints with fallback and usage metadata | off until configured |
| Persistent memory | `.memory` add/search/pin/forget, used by the AI when `memory` is ON | **OFF** |
| Life Graph | people, projects, places, topics and relations with `.graph` | **OFF** |
| Personal CRM | contacts, interaction log, birthdays, stale contacts | **OFF** |
| Decision journal | decisions, expected outcomes, later review | **OFF** |
| Focus mode | timed sessions, statistics, timeline events | **OFF** |
| Timeline | one chronological stream of everything REZE records | **OFF** |
| Writing DNA | writing samples, style profile, comparison of new text | **OFF** |
| Projects & tasks | local projects, tasks with priority/due date, completion stats | **OFF** |
| Expenses | amounts, categories, monthly summaries | **OFF** |
| Workflows | trigger → steps with retries, history, resume, idempotency | **OFF** (sensitive) |
| Random reactions | rare emoji reactions in chats you list, never bulk | **OFF** (sensitive) |
| Digital Vault | AES-256-GCM secrets and files, scrypt-derived key, export | **OFF** (sensitive) |
| Security Sentinel | local checks and findings for sessions, config and exposure | **OFF** (sensitive) |
| Self-maintenance | integrity check, backup age, retention application | **OFF** |
| AI agent | allowlisted tools, approval codes, budgets, audit trail | **OFF** (sensitive) |
| Model Council | ask several configured models and synthesize one answer | **OFF** (sensitive) |
| Insight engine | local weekly statistics, optional AI narrative | **OFF** |
| Smart inbox | locally classified incoming messages, rules, no auto-replies | **OFF** (sensitive) |
| Universal search | FTS5 search over memories, contacts, tasks, decisions, documents | **OFF** |
| Voice intelligence | transcription of replied voice notes through the AI provider | **OFF** (sensitive) |
| Document intelligence | text extraction and local indexing of replied documents | **OFF** (sensitive) |
| Bot Companion | optional owner-only Telegram bot front end | **OFF** (sensitive) |

The authoritative list is generated by `reze/features.py` (23 keys) and is always
visible in `.features`, the web panel and the installer menu.

## Architecture

```
reze/
  app.py               application wiring, lifecycle, signal handling
  command_router.py    registry, permissions, cooldowns, long replies
  features.py          the single 23-key optional-feature store (default OFF)
  config.py            REZE_* settings and deployment detection
  database.py          connection, WAL, migrations runner
  migrations/          versioned, incremental SQL migrations (v3, v4)
  core/registry.py     service registry + event bus (start only enabled features)
  ui/                  one ASCII engine and four themes
  media/               Pillow, FFmpeg, sticker sets, workspaces
  ai/                  provider adapters, gateway, tools/ allowlist
  modules/             afk, alerts, antiflood, antiraid, filters, greetings, msglog
  personal/            life graph, crm, decisions, focus, timeline, writing, memory
  productivity/        projects, tasks, expenses, reminders
  capture/             inbox, voice, documents, universal search
  search/              FTS5 index (schema v4)
  security/            sentinel, retention, maintenance
  storage/             encryption, vault, backups
  automation/          rules, simulator, persistent workflow engine
  localization/        en/fa catalogs, normalization, Jalali dates
  commands/            command suites
  web/                 panel server, pages, auth, CSRF, theme
  plugins/             built-in example plugins
  installer.py         guided terminal installer (reze-install)
docs/                  installation, configuration, database, localization,
                       architecture, commands, security, testing, limitations
tests/                 unittest suite
```

Data flow for a new subsystem: a service object registers itself in
`core/registry.py`, declares the feature key it belongs to, and is started only
when that feature is enabled. Commands read the feature store before doing any
work and print the exact enable hint when it is off.

## Requirements

| Component | Requirement |
| --- | --- |
| Python | 3.11 or newer |
| Telegram | API id/hash from https://my.telegram.org and an authorized session |
| Database | SQLite (bundled with Python) |
| Images | `Pillow` (installed from `requirements.txt`) |
| Encryption | `cryptography` (installed from `requirements.txt`) |
| Video/audio | **FFmpeg** on `PATH` (optional) — `winget install Gyan.FFmpeg`, `apt install ffmpeg` |
| AI | An API key for one supported provider (optional) |
| Downloads/speech | `pip install yt-dlp gTTS` (optional) |

## Install

### Guided installer (recommended)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate      Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

python -m reze.installer
```

The installer prints the ASCII logo, runs system checks, asks for Telegram
credentials, panel login, language, data directory, optional AI settings and
vault key, masks every secret while typing, validates input, never overwrites an
existing `.env` without confirmation (it writes a timestamped `.bak-*` first),
and finishes with a post-install menu where every optional feature is listed as
OFF. Ctrl+C exits gracefully.

Flags: `--check` (system checks only), `--non-interactive`, `--yes`,
`--no-menu`, `--env-file PATH`, `--data-dir PATH`, `--language en|fa`. After a
`pip install .` the same installer is available as `reze-install`.

### Manual install

```bash
cp .env.example .env        # then fill in the values
python scripts/generate_session.py    # creates a StringSession
# paste the printed string into REZE_SESSION_STRING in .env

python -m reze.app
```

Open `http://127.0.0.1:8080`, sign in with `REZE_PANEL_USERNAME` and the panel
password, then send `.help` to your own account from any chat.

> A userbot acts as **you**. Only run Reze on an account you own, and keep the
> session string, API hash and vault key private.

Full walkthroughs (Docker, systemd, PaaS, reverse proxy): [docs/INSTALLATION.md](docs/INSTALLATION.md)
and [DEPLOY.md](DEPLOY.md).

## Configuration

All settings use the `REZE_` prefix. Secrets live in the environment only and
are never rendered by the panel. Runtime preferences (theme, prefix, language,
AI model, media defaults, log level) are stored in SQLite and edited with
`.config` or the panel.

| Variable | Purpose |
| --- | --- |
| `REZE_API_ID`, `REZE_API_HASH` | Telegram application credentials |
| `REZE_OWNER_ID` | The only account allowed to run commands |
| `REZE_SESSION_STRING` | Portable session (recommended on PaaS) |
| `REZE_PANEL_USERNAME`, `REZE_PANEL_PASSWORD` / `_HASH` | Panel login (exactly one password form) |
| `REZE_WEB_HOST`, `REZE_WEB_PORT` | Panel bind address (loopback by default) |
| `REZE_LANGUAGE` | `en` or `fa` |
| `REZE_TIMEZONE` | IANA timezone used for dates and reminders |
| `REZE_VAULT_KEY` | AES-256-GCM key for the Digital Vault |
| `REZE_AI_PROVIDER`, `REZE_AI_MODEL`, `REZE_AI_API_KEY` | AI gateway |
| `REZE_AI_DAILY_BUDGET_CALLS`, `REZE_AI_TOOL_MAX_CALLS` | AI usage ceilings |
| `REZE_RETENTION_DAYS`, `REZE_AUDIT_RETENTION_DAYS` | Retention windows |
| `REZE_TASK_CONCURRENCY`, `REZE_TASK_QUEUE_LIMIT` | Background work limits |

Full reference with defaults and examples: [docs/CONFIGURATION.md](docs/CONFIGURATION.md)
and [`.env.example`](.env.example).

## First run

1. `python -m reze.app` prints the ASCII banner, the panel URL and the health
   endpoint.
2. Send `.alive` and `.status` to your own account. `.diagnostics` reports which
   optional integrations are ready and which are not.
3. Send `.features`. Every key is OFF. Enable one at a time, for example
   `.features enable memory`; sensitive keys need `.features enable vault confirm`.
4. Send `.help` for the index or `.help <command>` for usage and examples.

The first start applies migrations up to schema **v4** and creates the database
without enabling anything. Existing 2.0 databases are migrated in place; feature
state is preserved and still defaults to OFF for keys that never existed.

## Language (English / Persian)

- `.language fa` switches catalog-backed interface text, help framing, feature
  names, panel navigation/login and reply framing to Persian; `.language en`
  switches back. Panel page bodies remain English in 3.0.
- Persian input is normalized: `ي`/`ی`, `ك`/`ک`, Arabic-Indic digits, diacritics
  and bidi marks, ZWNJ and whitespace.
- Persian replies are wrapped with a right-to-left mark. Stored timestamps stay
  ISO-8601 UTC; Jalali rendering is available for dates.
- Command names and syntax are identical in both languages.
- Per-command one-line descriptions in `.help` remain English in 3.0; see
  [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

Details: [docs/LOCALIZATION.md](docs/LOCALIZATION.md).

## AI setup

Set one provider in `.env`:

```ini
REZE_AI_PROVIDER=openai          # openai | anthropic | gemini | openai_compatible
REZE_AI_MODEL=gpt-4o-mini
REZE_AI_API_KEY=sk-...
# REZE_AI_BASE_URL=...           # for openai_compatible endpoints
```

Then use `.ai`, `.summarize`, `.translate`, `.rewrite`, `.digest` and
`.describe`. Requests honor timeouts, retry only on rate limits/timeouts and
never log prompts or responses. Fallback is opt-in via `REZE_AI_FALLBACK` and is
disclosed in response metadata.

AI tool calling (`.agent`) is a separate, sensitive feature. Tools are
allowlisted, every call needs a 6-digit approval code that expires after 15
minutes, calls are budgeted per day and audited, and turning `ai_agent` off
invalidates pending approvals. `.council` asks multiple configured models and
synthesizes one answer. See [docs/AI.md](docs/AI.md).

## Usage

| Family | Examples |
| --- | --- |
| Core | `.help` `.ping` `.status` `.diagnostics` `.logs` `.features` `.language` |
| Media | `.sticker` `.stickerpack` `.resize` `.compress` `.meme` `.gif` `.tovideo` `.toaudio` `.removebg` |
| Personal OS | `.memory` `.graph` `.crm` `.decide` `.focus` `.timeline` `.writing` |
| Productivity | `.project` `.task` `.expense` `.remind` `.schedule` `.notes` `.bookmark` |
| Capture | `.inbox` `.usearch` `.voice` `.doc` |
| AI | `.ai` `.summarize` `.translate` `.rewrite` `.digest` `.agent` `.council` `.insights` |
| Security | `.vault` `.sentinel` `.maintain` `.backup` `.privacy` `.sessions` |
| Automation | `.workflow` `.reactions` `.automation` |
| Guard | `.watch on/add/list/status` `.alerts` `.afk` |
| Groups | `.ban` `.mute` `.warn` `.purge` `.antiflood` `.antiraid` `.lock` `.filter` |

The full reference of all 172 commands — aliases, syntax, arguments,
permissions, examples, behaviour, errors and language availability — is
[docs/COMMANDS.md](docs/COMMANDS.md). It is generated from the live router, so
nothing is documented that does not exist.

Long outputs are split at Telegram's 4096-character limit and code spans are
rebalanced so pagination never breaks Markdown parsing.

### Example workflows

```text
.memory add The deploy key rotates every 90 days
.memory search deploy
.task add Renew the domain @infra p:2 due:2026-11-30
.crm add Sara @sara birthday:1994-04-12 tags:work
.decide add Move off the old host | stay, migrate | migrate saves ~40 EUR/month | 30
.focus start 50 deep work
.workflow simulate [{"action":"notify_owner","text":"Daily review"}]
.features enable workflows confirm
```

`.workflow` requires the feature to be enabled; a new workflow starts disabled
and must be enabled explicitly.

## Security and privacy

- The bot answers **only the owner account**. Other members get no reply and no
  "unknown command" hint. `REZE_PUBLIC_COMMANDS=true` re-enables public commands
  and is a deliberate downgrade.
- Secrets (API keys, session strings, vault key) are environment-only, masked in
  logs and never rendered by the panel.
- Vault entries use AES-256-GCM with a scrypt-derived key. Losing
  `REZE_VAULT_KEY` makes that data unrecoverable.
- Backups use the SQLite online backup API, can be verified, and restore needs a
  6-digit confirmation code compared in constant time. A backup is a local
  SQLite copy: vault rows stay encrypted inside it, but the rest of the file is
  plaintext, so protect the data and backup directories.
- `.exec` is disabled until `REZE_ENABLE_EXEC=true`. `.broadcast` requires a
  confirmation code and a per-run cap.
- The panel uses session cookies (`HttpOnly; SameSite=Lax`), a session-bound
  CSRF token on every POST, a strict CSP, size-limited bodies and no JavaScript.
- Retention is configurable; `.maintain apply confirm` applies it explicitly.
- Message Guard stores other people's messages locally. Use `.watch ttl` only
  where that is acceptable and tell people in shared groups.

Details: [SECURITY.md](SECURITY.md) and [docs/SECURITY.md](docs/SECURITY.md).
Database schema, encryption layout and retention: [docs/DATABASE.md](docs/DATABASE.md).

## Plugins

Drop a file in `reze/plugins/`, declare a `MANIFEST`, and restart (or
`.plugin enable <id>`). The manager validates the manifest, checks declared
dependencies, rejects duplicate commands and isolates failures per plugin.

```python
MANIFEST = {
    "name": "My Plugin", "id": "my_plugin", "version": "1.0.0",
    "description": "Does one useful thing.",
    "commands": ["mycommand"],
    "permissions": ["telegram.message"],
    "min_reze_version": "3.0.0",
}
```

**Isolation honesty:** plugins run in-process with the same privileges as Reze.
The manifest is a consent document, not a sandbox. Do not install plugins you do
not trust. Guide: [docs/PLUGIN_GUIDE.md](docs/PLUGIN_GUIDE.md).

## Web panel

`python -m reze.app` also starts the panel (default `127.0.0.1:8080`):
dashboard, optional features (ON/OFF with confirmation for sensitive keys),
plugins, tasks, groups, filters, automations, productivity, profile, security,
settings, logs, archive, and health endpoints (`/health`, `/healthz`, `/livez`,
`/readyz`).

## Testing

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

The suite runs offline and needs no Telegram or paid AI credentials. It covers
the ASCII engine, configuration, storage and migrations, auth/CSRF, task
manager, media helpers, sticker request construction, AI adapters and error
mapping, the panel over real HTTP, QR encoding, automation, and every REZE 3
subsystem: default-off policy, feature store, vault encryption, backups,
AI tool approvals and budgets, workflows and idempotency, localization and
Jalali dates, and the installer.

Current state of this repository: **378 tests, 0 failures, 21 skipped**. Details
and limitations: [docs/TESTING.md](docs/TESTING.md).

## Project scope

REZE is a personal tool. It deliberately contains **no advertising, bulk
unsolicited messaging, member scraping or promotional campaign functionality**.
Automation that spams or mass-messages can get an account limited or banned by
Telegram — keep `.tagall`, broadcasts, reactions and workflows conservative.

Reze is an independent project and is not affiliated with Telegram.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `REZE_API_ID / REZE_API_HASH are missing` | Fill both values in `.env`; the client stays disabled otherwise. |
| Panel login refused | Set exactly one of `REZE_PANEL_PASSWORD` or `REZE_PANEL_PASSWORD_HASH`; default login is refused unless explicitly allowed. |
| A command says the feature is OFF | That is the default. Run the printed `.features enable <key>` hint (add `confirm` for sensitive keys). |
| Vault errors after moving hosts | `REZE_VAULT_KEY` changed or is missing; old entries cannot be decrypted without the original key. |
| FFmpeg commands refuse to start | Install FFmpeg and put it on `PATH`, or set `REZE_FFMPEG_PATH`. |
| AI commands return "not configured" | Set provider, model and key; check `.aiinfo` and `.diagnostics`. |
| Sticker uploads arrive as files | Real stickers need `REZE_STICKER_BOT_TOKEN` from @BotFather; start the bot once. |
| Messages deleted while Reze was offline are missing | Guard only sees messages delivered while it runs. |

More: [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md).

## Documentation

| Document | Contents |
| --- | --- |
| [docs/README.fa.md](docs/README.fa.md) | راهنمای فارسی — Persian quick start |
| [docs/INSTALLATION.md](docs/INSTALLATION.md) | Installer, manual setup, Docker, systemd, PaaS |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every `REZE_*` variable and runtime setting |
| [docs/COMMANDS.md](docs/COMMANDS.md) | All 172 commands and beginner tutorials |
| [docs/REZE_3_ARCHITECTURE.md](docs/REZE_3_ARCHITECTURE.md) | Services, feature gating, storage, event bus |
| [docs/DATABASE.md](docs/DATABASE.md) | Schema, migrations, FTS5, encryption, retention |
| [docs/LOCALIZATION.md](docs/LOCALIZATION.md) | Persian/English, normalization, Jalali |
| [docs/AI.md](docs/AI.md) | Providers, tools, approvals, budgets, council |
| [docs/AUTOMATION.md](docs/AUTOMATION.md) | Rules, simulator, workflows, recovery |
| [docs/SECURITY.md](docs/SECURITY.md) | Threat model and hardening |
| [docs/PLUGIN_GUIDE.md](docs/PLUGIN_GUIDE.md) | Writing and validating plugins |
| [docs/TESTING.md](docs/TESTING.md) | What the suite proves and what it does not |
| [docs/KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | Honest limits of 3.0 |
| [CHANGELOG.md](CHANGELOG.md) | Release history |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) for the dev setup, the test command and
how to write a plugin. Security problems: [SECURITY.md](SECURITY.md) — please do
not open a public issue.

## License and credits

MIT. Built by **UnchartedAli** — channel [@yamods](https://t.me/yamods).

If Reze is useful to you, a ⭐ on GitHub helps other people find it.
