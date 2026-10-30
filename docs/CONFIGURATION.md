# Configuration

REZE reads two kinds of settings:

1. **Environment (`REZE_*`)** — credentials, paths, limits and secrets. Loaded
   from `.env` (or the real process environment on PaaS) at startup. Secrets are
   never written to logs or rendered by the panel.
2. **Preferences (SQLite)** — user choices such as theme, prefix, language, AI
   model and media defaults. Edited with `.config`, the panel or the relevant
   command. Environment values are the fallback when no preference is stored.

Nothing in this file enables an optional feature. Feature keys live in
`.features` and default to OFF. See [COMMANDS.md](COMMANDS.md) and `.features`.

## Environment reference

### Telegram

| Variable | Default | Notes |
| --- | --- | --- |
| `REZE_API_ID` | `0` | From https://my.telegram.org |
| `REZE_API_HASH` | empty | Keep secret; equivalent to a password |
| `REZE_OWNER_ID` | `0` | Only this numeric account can use the bot |
| `REZE_SESSION_STRING` | empty | Portable StringSession, recommended on PaaS |
| `REZE_PHONE` | empty | Only for the interactive login prompt |
| `REZE_SESSION_PATH` | `data/reze.session` | File session when no string is set |
| `REZE_PROXY` | empty | `socks5://user:pass@host:1080` or `http://host:8080` |

If the API id/hash are missing, Reze starts with the Telegram client disabled and
the panel/health endpoints still work; every command that needs Telegram reports
that instead of pretending to work.

### Storage

| Variable | Default | Notes |
| --- | --- | --- |
| `REZE_DATA_DIR` | `data` | Vault, backups, Message Guard cache and archive |
| `REZE_DATABASE_URL` | `sqlite:///data/reze.db` | Only SQLite is supported |
| `REZE_RETENTION_DAYS` | `365` | Applied by `.maintain`, never silently |
| `REZE_AUDIT_RETENTION_DAYS` | `180` | Audit and tool-call history |

### Web panel

| Variable | Default | Notes |
| --- | --- | --- |
| `REZE_WEB_HOST` | `127.0.0.1` | Keep loopback unless a reverse proxy fronts it |
| `REZE_WEB_PORT` | `8080` | |
| `REZE_PUBLIC_URL` | empty | Public HTTPS URL for links and cookies |
| `REZE_WEB_TRUST_PROXY` | `false` | Only with a trusted proxy |
| `REZE_ALLOWED_ORIGINS` | empty | Extra origins for origin checks |
| `REZE_PANEL_USERNAME` | `admin` | |
| `REZE_PANEL_PASSWORD` | empty | Set exactly one password form |
| `REZE_PANEL_PASSWORD_HASH` | empty | Preferred; `python scripts/generate_hash.py` |
| `REZE_SECRET_KEY` | default placeholder | Change it; used for signing/session material |
| `REZE_ALLOW_INSECURE_DEFAULT_LOGIN` | `false` | Allows the default password; not for production |
| `REZE_SESSION_TTL_SECONDS` | `14400` | Panel session lifetime |
| `REZE_WEB_MAX_BODY_BYTES` | `262144` | Request body limit |

The panel refuses to start a session with the default login unless explicitly
allowed. Cookies are `HttpOnly; SameSite=Lax` (`Secure` over HTTPS), every POST
carries a session-bound CSRF token, and the CSP forbids inline and remote script.

### General and presence

| Variable | Default | Notes |
| --- | --- | --- |
| `REZE_LANGUAGE` | `en` | `en` or `fa`; `.language` overrides at runtime |
| `REZE_TIMEZONE` | `UTC` | IANA name; reminders and dates |
| `REZE_LOG_LEVEL` | `INFO` | Logging buffer level |
| `REZE_DEFAULT_PREFIX` | `.` | `.prefix` / `.config set prefix` override |
| `REZE_THEME` | `CYBER` | CYBER, GHOST, TERMINAL or COMPACT |
| `REZE_COMPACT_MODE` | `false` | Compact frames |
| `REZE_CLOCK_INTERVAL_MINUTES` | `1` | Name clock refresh |
| `REZE_PRESENCE_INTERVAL_SECONDS` | `60` | `.setonlinepermanently` refresh (off by default) |

### Media and tasks

| Variable | Default | Notes |
| --- | --- | --- |
| `REZE_MEDIA_WORK_DIR` | empty | Temporary conversion directory |
| `REZE_MEDIA_MAX_INPUT_MB` | `20` | Download limit |
| `REZE_MEDIA_MAX_OUTPUT_MB` | `48` | Result limit |
| `REZE_MEDIA_QUALITY` | `82` | Encoder quality |
| `REZE_FFMPEG_PATH` | empty | Explicit binary path |
| `REZE_REMOVEBG_API_KEY` | empty | Background removal provider |
| `REZE_TASK_CONCURRENCY` | `2` | Parallel background tasks |
| `REZE_TASK_QUEUE_LIMIT` | `8` | Queue ceiling |
| `REZE_TASK_TIMEOUT_SECONDS` | `300` | Per-task timeout |
| `REZE_VOICE_MODEL` | `whisper-1` | Transcription model |
| `REZE_VOICE_MAX_MB` | `25` | Voice note size ceiling |

### AI

| Variable | Default | Notes |
| --- | --- | --- |
| `REZE_AI_PROVIDER` | empty | `openai`, `anthropic`, `gemini`, `openai_compatible` |
| `REZE_AI_MODEL` | empty | Provider model name |
| `REZE_AI_API_KEY` | empty | Never logged or rendered |
| `REZE_AI_BASE_URL` | empty | For compatible endpoints |
| `REZE_AI_FALLBACK` | empty | Comma-separated fallback providers |
| `REZE_AI_TIMEOUT_SECONDS` | `60` | Per-request timeout |
| `REZE_AI_MAX_INPUT_CHARS` | `12000` | Prompt input cap |
| `REZE_AI_MAX_OUTPUT_TOKENS` | `900` | Output cap |
| `REZE_AI_VISION` | `auto` | `auto`, `on`, `off` |
| `REZE_AI_DAILY_BUDGET_CALLS` | `200` | Daily provider-call budget |
| `REZE_AI_TOOL_MAX_CALLS` | `20` | Per-run tool-call ceiling |

Without provider/model/key the AI commands are disabled and say so. They never
fall back to a fake local answer.

### Digital Vault and security

| Variable | Default | Notes |
| --- | --- | --- |
| `REZE_VAULT_KEY` | empty | AES-256-GCM key material; losing it loses vault data |
| `REZE_COMPANION_TOKEN` | empty | Bot token for the optional companion |
| `REZE_COMPANION_POLL_SECONDS` | `3` | Companion polling interval |

If `REZE_VAULT_KEY` is empty, a non-default `REZE_SECRET_KEY` is used as key
material. If neither is set, `.vault` reports "locked" and refuses to store
anything rather than writing weakly protected data.

### Automation and limits

| Variable | Default | Notes |
| --- | --- | --- |
| `REZE_AUTOMATION_ENABLED` | `true` | Master switch for the rule engine |
| `REZE_AUTOMATION_MAX_RULES` | `50` | Rule cap |
| `REZE_AUTOMATION_RUNS_PER_HOUR` | `30` | Hourly run cap |
| `REZE_MAX_PURGE_LIMIT` | `100` | `.purge` ceiling |
| `REZE_MAX_TAGALL_LIMIT` | `50` | `.tagall` ceiling |
| `REZE_SEARCH_SCAN_LIMIT` | `200` | Bounded search scans |

### Environment-only safety flags

These are read directly from the environment and are intentionally absent from
the panel:

| Variable | Default | Effect |
| --- | --- | --- |
| `REZE_PUBLIC_COMMANDS` | `false` | Let non-owners use public/admin commands |
| `REZE_ENABLE_EXEC` | `false` | Enable `.exec` shell access |
| `REZE_BROADCAST_MAX` | `100` | Max chats per broadcast (1–500) |
| `REZE_YTDLP_COOKIES` | empty | Netscape cookies file for yt-dlp |
| `REZE_GITHUB_TOKEN` | empty | Higher GitHub API rate limit |
| `REZE_STICKER_BOT_TOKEN` | empty | Real sticker creation through your bot |

## Preferences (SQLite)

`.config` shows the current values. `.config set <key> <value>` validates and
stores a value; `.config reset <key>` removes the override and falls back to the
environment.

| Key | Example | Validation |
| --- | --- | --- |
| `theme` | `.config set theme GHOST` | One of CYBER, GHOST, TERMINAL, COMPACT |
| `compact` | `.config set compact on` | on/off |
| `prefix` | `.config set prefix !` | Single character |
| `language` | `.config set language fa` | `en` or `fa` |
| `ai_provider` | `.config set ai_provider openai` | Supported provider |
| `ai_model` | `.config set ai_model gpt-4o-mini` | Non-empty text |
| `ai_vision` | `.config set ai_vision off` | auto/on/off |
| `media_quality` | `.config set media_quality 80` | 40–100 |
| `media_max_input_mb` | `.config set media_max_input_mb 15` | 1–2000 |
| `log_level` | `.config set log_level DEBUG` | DEBUG/INFO/WARNING/ERROR |
| `online_always` | `.config set online_always on` | on/off |

Preferences never change feature state. Enabling `memory` is done with
`.features enable memory`, not `.config`.

## Feature state

Feature state is stored in its own table and is deliberately separate from
preferences:

- 23 keys exist; all default to OFF.
- Missing, empty or unknown values resolve to OFF.
- Sensitive keys require the literal word `confirm`.
- No command, migration, restart or reset enables more than the one key asked
  for.
- The panel shows ON/OFF and applies the same confirmation rule.

```text
.features
.features status vault
.features enable memory
.features enable vault confirm
.features disable vault
```

## Secrets hygiene

- Never commit `.env`, `data/`, session files, backups or vault exports.
- API keys, session strings, panel passwords and the vault key are masked in
  logs and never returned by `.config`, `.info` or the panel.
- `REZE_SECRET_KEY` and `REZE_VAULT_KEY` must be long random values, generated
  with `secrets.token_urlsafe`, and stored in a password manager.
- Rotating `REZE_VAULT_KEY` does not re-encrypt old entries. Export what you
  need first with `.vault export <name>`.
