# Changelog

All notable changes to **Reze** are documented here.
Developer: **UnchartedAli** · Channel: **[@yamods](https://t.me/yamods)**

## [2.1.0] — Unreleased

### Added
- **Message Guard** (`reze/modules/msglog.py`, `.watch`): keeps a short-lived
  local copy of messages from the chats you choose and sends deleted (and
  optionally edited) messages to Saved Messages. Small media files are cached
  immediately so deleted photos, videos, voice notes and files can be re-sent.
  Per-chat watch list, all-private / all-groups switches, custom destination,
  configurable retention (default 48 h, auto-purged) and a 25 MB media limit.
  Channel/supergroup ids are scoped separately from private-chat ids, because
  Telegram's delete events carry no chat id for private chats.

### Added (owner suite, 2.1)
- **Owner-only command handling:** strangers typing `.something` in a group get no reaction at all (no reply, no "unknown command"). `REZE_PUBLIC_COMMANDS=true` restores the old behaviour. Their messages still pass through filters and automation.
- Owner: `.owner`, `.botinfo`, `.exec` (opt-in via `REZE_ENABLE_EXEC`), `.setvar/.getvar/.delvar` (`REZE_*` only, secrets masked), `.block/.unblock`, `.broadcast/.bc` (confirmation code, rate limit), `.update`.
- Group: `.promote`, `.demote`, `.hidetag`, `.setdesc`, `.settitle`, `.invite`, `.join`, `.leave`.
- Download: `.yt/.play`, `.ytv`, `.yta`, `.song`, `.instagram/.ig`, `.tiktok/.tt`, `.facebook/.fb`, `.pinterest`, `.mediafire` (yt-dlp is optional).
- Tools: `.weather`, `.github`, `.tts`, `.url`. Fun: `.quote`, `.joke`, `.roast`, `.ship`, `.truth`, `.dare`, `.tictactoe` (unbeatable AI or two players).
- `.sticker` / `.s` now converts GIFs and videos to WebM video stickers and sends real stickers; aliases `.toimg`, `.tomp3`, `.tr`.

- **Message Guard: timed media.** Self-destructing (timer / view-once) photos, videos and voice notes in watched chats are copied to Saved Messages as soon as they arrive. `.watch ttl on|off`; on by default for watched chats.

- **Permanent archive:** deleted messages and timed media that were delivered are also kept locally (metadata in SQLite, files in `data/msglog/archive/`) and are never purged automatically. `.watch archive on|off|clear`, `.watch keep forever`.

### Fixed
- `CommandContext.send_file` passed the chat as a `chat_id` keyword, but
  Telethon's signature is `send_file(entity, file, ...)`. Every media reply
  (stickers, GIFs, images, `.qr`, `.download`) failed with "missing 1 required
  positional argument: 'entity'". The chat is now passed positionally.
- The test double `DummyClient.send_file` now mirrors Telethon's signature so
  this class of bug is caught by the suite.

## [2.0.0] — 2026-10-28

REZE 2.0 turns the userbot into a coherent platform. Everything is English-only,
every message is rendered by one shared engine, and optional integrations fail
with actionable errors instead of breaking the core.

### Added
- **Extreme-ASCII message engine** (`reze/ui`): banner, framed panels, tagged
  status lines, key/value blocks, tables, progress bars and safe message
  splitting with Markdown code-span balancing. Themes: `CYBER`, `GHOST`,
  `TERMINAL`, `COMPACT`; `.theme`, `.preview`, `.config`, `.prefix`.
- **Task manager** (`reze/core/tasks.py`): bounded concurrency and queue,
  progress, timeout, cancellation, history mirrored to SQLite; `.queue`,
  `.cancel`, `.status`.
- **Bound confirmations** (`reze/core/confirmations.py`): single-use codes bound
  to action/chat/user with a two-minute expiry, used by `.stickerpack` and
  `.removebg`.
- **Always-online presence** (`reze/core/presence.py`): opt-in background service
  that refreshes `account.updateStatus(offline=False)` on an interval, with
  FloodWait cooldowns and persisted state; controlled by
  `.setonlinepermanently on|off|status` (aliases `.alwaysonline`,
  `.onlineforever`) and the panel settings page.
- **REZE Studio** (`reze/media`): Pillow image pipeline, real 512×512 WebP
  static sticker conversion, real `messages.CreateStickerSet` /
  `messages.AddStickerToSet` integration, FFmpeg wrapper with dependency
  detection, isolated media workspaces with guaranteed cleanup.
- **Media commands**: `.sticker`, `.stickerpack`, `.addsticker`, `.toimage`,
  `.resize`, `.compress`, `.meme`, `.caption`, `.thumbnail`, `.gif`, `.tovideo`,
  `.toaudio`, `.trim`, `.speed`, `.removebg`, `.download`.
- **REZE Intelligence** (`reze/ai`): OpenAI, Anthropic, Gemini and
  OpenAI-compatible adapters over the official HTTP APIs with normalized errors,
  timeouts, bounded retries, opt-in fallback, usage metadata and vision gating;
  `.ai`, `.summarize`, `.translate`, `.rewrite`, `.digest`, `.describe`,
  `.aiinfo`.
- **Plugin ecosystem**: validated manifests, declared capabilities, dependency
  checks, duplicate-command detection, failure isolation, per-plugin typed
  settings, enable/disable persistence, `.plugins`, `.plugin`, `.plugininfo`,
  `.plugintemplate`, plus `docs/PLUGIN_GUIDE.md`.
- **Personal tools**: local archive (`.save`, `.find`, `.bookmark`), personal
  notes (`.notes`), reminders and schedules (`.remind`, `.schedule`), bounded
  chat search (`.search`), link and media extraction (`.links`, `.files`),
  identity helpers (`.whois`, `.chatinfo`), and a dependency-free QR generator
  (`.qr`).
- **Automation engine**: schedule/interval/keyword/task-failed triggers,
  conditions, save/remind/notify/AI-summary/allowlisted-command actions,
  cooldowns, hourly caps, recursion guard and owner-only outbound actions
  (`.automation`).
- **Web panel rewrite**: English LTR terminal UI, CSRF protection, session TTL,
  strict CSP, body limits, loopback binding, dashboard/plugins/tasks/settings/
  logs/archive/automations/groups/filters/security pages, `/api/status`.
- **Diagnostics**: `.diagnostics` reports integration readiness and recent
  errors without secrets; `/healthz` reports service state.
- **Documentation**: rewritten `README.md`, `.env.example`, new
  `docs/SECURITY.md`, `docs/PLUGIN_GUIDE.md`, `docs/COMMANDS.md`,
  `docs/AI.md`, `docs/AUTOMATION.md`, `docs/TESTING.md`,
  `docs/KNOWN_LIMITATIONS.md`, and an English `DEPLOY.md`.
- **Tests**: 145 unit/integration tests covering the engine, storage, auth,
  router, tasks, confirmations, plugins, media, stickers, AI, web panel, QR and
  automation.

### Changed
- Version metadata is `2.0.0` in `reze/__init__.py`, `pyproject.toml` and the
  panel.
- The command router rejects duplicate command names and aliases, supports
  cooldowns, records denials, splits long replies automatically and answers
  unknown commands with a hint.
- Errors raised by handlers are rendered through the ASCII engine and logged
  with a traceback instead of leaking raw exceptions.
- `.setname`, `.setbio`, `.lock` and `.unlock` now perform real Telegram
  operations; `.accountstatus` reports real connection state.
- The web panel binds to `127.0.0.1` by default and only trusts proxy headers
  when `REZE_WEB_TRUST_PROXY=true`.
- `requirements.txt` drops unused `aiofiles`/`cryptography` and adds `Pillow`.

### Security
- CSRF tokens are required on every panel POST, including sign-out.
- Panel responses send a restrictive CSP, `X-Frame-Options: DENY`,
  `Referrer-Policy: no-referrer` and HSTS behind HTTPS.
- Request bodies are capped; settings and automation input are validated
  server-side; log masking covers API keys and bearer tokens.
- Plugin capability declarations are surfaced before enabling, with explicit
  documentation that they are not a sandbox.
- Confirmation codes are bound, expiring and single-use.
- The web layer never exposes the Telethon client, session or credentials.

### Removed
- Persian UI strings and the RTL panel layout.
- The unvalidated `eval()` calculator in the example plugin (replaced with an
  AST-based evaluator).
- Fabricated success messages in `.lock`, `.unlock` and `.accountstatus`.

### Known limitations
See `docs/KNOWN_LIMITATIONS.md`: no plugin sandbox, static stickers only, FFmpeg
required for video/audio, bounded search, in-memory sessions.

## [1.1.0] — 2026-10-27

### Added
- Creator branding across the package, startup banner, web panel, README, license, and deployment files.
- `.credits` command (aliases: `creator`, `developer`, `support`).
- Portable Telethon `StringSession` support via `REZE_SESSION_STRING` (PaaS-friendly).
- `scripts/generate_session.py` to create or convert a session string.
- Public `/healthz` endpoint for Render/Railway/Koyeb/Fly health checks (GET and HEAD).
- Docker support: `Dockerfile`, `docker-entrypoint.sh`, `.dockerignore`, `HEALTHCHECK`.
- Deployment configs: `render.yaml`, `railway.json`, `fly.toml`, `docker-compose.yml`, `Procfile`.
- Deployment guide (`DEPLOY.md`) for Render/Railway/Koyeb/Fly/Docker/VPS.
- Optional SOCKS5/HTTP proxy support via `REZE_PROXY`.
- Optional persistent-volume support via `REZE_DATA_DIR`.
- Graceful `SIGTERM` shutdown and MTProto reconnect with exponential backoff.
- One-time interactive phone/code login on VPS/local terminals.
- Trust-proxy aware client IP detection and secure cookies behind HTTPS.
- Automatic `.env` loading for local/VPS runs (`python-dotenv`).

### Changed
- The web panel binds to `0.0.0.0` on PaaS and uses the platform `PORT` automatically.
- The database path derives from `REZE_DATA_DIR`; falls back to a temporary DB if the volume is unwritable.
- Panel login is disabled until `REZE_PANEL_PASSWORD` or `REZE_PANEL_PASSWORD_HASH` is set.
- The HTTP server is threaded, so health checks stay responsive.
- Log HTML is escaped; security headers added.

### Security
- Removed the insecure default admin/admin login unless `REZE_ALLOW_INSECURE_DEFAULT_LOGIN=true` is explicitly set.
- Session snapshot files are written with `0600` permissions and ignored by git.
- Sensitive log masking no longer mangles ports/paths.

## [1.0.0]
- Initial public Reze release.
