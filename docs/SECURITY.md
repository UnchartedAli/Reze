# Security guide

Reze is a **userbot**: it acts as your Telegram account. Treat the host, the
`.env` file, the session and the web panel as account credentials.

## 1. Secrets

| Secret | Where it lives | Protection |
| --- | --- | --- |
| `REZE_API_HASH` | environment/.env | never logged, never rendered by the panel |
| `REZE_SESSION_STRING` | environment/.env | never logged; a copy written to `data/session_string.txt` is `chmod 600` |
| Telethon session file | `REZE_SESSION_PATH` | restrictive permissions are applied on connect when the OS supports it |
| Panel password/hash | environment | the hash is PBKDF2-HMAC-SHA256 (120k iterations, per-password salt) |
| AI provider key | environment | passed only to the selected provider |
| `REZE_VAULT_KEY` | environment | never stored, logged or rendered; scrypt-derived AES-256-GCM key |
| Bot Companion token | environment | sent only to the Telegram Bot API |
| remove.bg key | environment | sent only to `api.remove.bg` |

- `.env`, `*.session`, `data/*.db` and media scratch space are git-ignored.
- The logging filter masks `api_hash`, `password_hash`, `session`, `secret_key`,
  `api_key`, bearer tokens and five-digit Telegram login codes before a record
  reaches the console, the in-memory panel buffer or disk.
- `.diagnostics` and the panel report *whether* a secret is configured, never
  its value.

## 2. Web panel

- **Authentication** is required for every page except `/healthz` and `/login`.
  Sessions are random 32-byte tokens stored in memory with a configurable TTL
  (`REZE_SESSION_TTL_SECONDS`, default 4h).
- **CSRF**: every state-changing request is a POST carrying a session-bound
  token validated with a constant-time compare. Missing or stale tokens get
  `403`.
- **Cookies**: `HttpOnly`, `SameSite=Lax`, `Secure` when the request is known to
  be HTTPS.
- **Headers**: strict CSP (`default-src 'none'`, no JavaScript), `X-Frame-Options:
  DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
  `Cache-Control: no-store`, HSTS behind HTTPS.
- **Input**: bodies are capped by `REZE_WEB_MAX_BODY_BYTES` (256 KiB). Settings
  are validated server-side; template output is HTML-escaped.
- **No path traversal**: the panel renders database state only; there is no
  endpoint that reads arbitrary files.
- **Binding**: `REZE_WEB_HOST` defaults to `127.0.0.1`. Exposing the panel
  publicly is an explicit configuration change and the startup log warns if no
  password is set.
- **Proxy headers** (`X-Forwarded-For`, `X-Forwarded-Proto`, `CF-Connecting-IP`)
  are ignored unless `REZE_WEB_TRUST_PROXY=true`, so a direct client cannot
  spoof its address or the HTTPS flag.
- **Rate limiting**: five failed logins per client address per five minutes.
- **Privileged Telegram operations stay on the backend**; the browser never
  receives the Telethon client, the session or raw API credentials.

## 3. Plugins and permissions

Plugins declare capabilities in their manifest:

`telegram.message`, `telegram.media`, `telegram.account`, `filesystem.read`,
`filesystem.write`, `network`, `ai.provider`, `process.exec`, `config.read`,
`config.secrets`.

The panel shows requested capabilities before a plugin is enabled, and the
plugin manager records which commands each plugin registered.

**This is a consent mechanism, not a sandbox.** A plugin runs in the same Python
process as Reze with the same privileges: it can import `telethon`, read files
its process can read, and ignore its manifest. Reze therefore:

- does not claim that permission declarations prevent code from bypassing them;
- does not promise safe hot-unloading — removing a plugin unregisters its
  commands, but Python cannot force it to release tasks, threads or handles;
- requires a manual install step: dropping a file into `reze/plugins/` and
  restarting. Nothing downloads or executes code from the internet, and Reze
  has no remote registry, signature or trust score.

Run third-party plugins only after reading their code.

## 4. Confirmations

Consequential operations use one-time confirmation codes (`.stickerpack`,
`.removebg`). A code is bound to one action, one chat and one user, expires after
two minutes, and is consumed on first use. It cannot be replayed for a different
operation.

REZE 3 sensitive features add their own gates:

- Enabling `vault`, `workflows`, `ai_agent`, `model_council`, `security_sentinel`,
  `smart_inbox`, `voice_intelligence`, `document_intelligence`, `bot_companion`,
  `random_reactions` or `background_monitoring` requires the literal word
  `confirm` in Telegram, a checkbox/confirm field in the panel and an explicit
  confirmation in the companion.
- AI tool calls need a 6-digit approval code (15 minutes, single use, owner
  only). Turning `ai_agent` off invalidates pending approvals.
- Backup restore needs a 6-digit code compared with `hmac.compare_digest`, after
  the backup has passed `PRAGMA integrity_check` and a safety copy of the live
  database was created.
- `.broadcast` and `.maintain apply` require their own confirmation words/codes.

## 4a. Feature default-off policy

Every optional feature and automation is disabled on a fresh install, after a
migration, after a restart and after a configuration reset. There is no cascade:
enabling `memory` never enables `ai_agent`, and enabling a feature never starts a
service that belongs to another key. Missing or unknown feature values resolve to
OFF. Background services are started at one choke point
(`registry.start_all()`), which skips every service whose feature is not
explicitly enabled.

## 4b. Digital Vault and backups

- Vault entries are AES-256-GCM ciphertext with a random 12-byte nonce per entry.
- The key is scrypt-derived from `REZE_VAULT_KEY` (fallback: a non-default
  `REZE_SECRET_KEY`). With neither set, the vault reports "locked" and stores
  nothing.
- Plaintext is never written to SQLite, logs or command output.
- Names are unique case-insensitively; storing the same name updates one row.
- Backups are SQLite copies made through the online backup API. Vault rows stay
  encrypted inside them, but the rest of the database is plaintext: protect
  `data/backups/`.
- Losing the vault key is unrecoverable. There is no recovery key and no backdoor.

## 4c. AI privacy

- Prompts and responses are never logged; only provider, model, duration and
  token counts are recorded.
- AI tools are strictly allowlisted with typed arguments. The model proposes; it
  never executes. Every call is audited in `ai_tool_audit`.
- Daily budgets (`REZE_AI_DAILY_BUDGET_CALLS`) and per-run tool ceilings
  (`REZE_AI_TOOL_MAX_CALLS`) bound cost and blast radius.
- `.voice` and `.describe` upload content to the configured provider only when
  you invoke them, and the response names the provider.
- Fallback providers are opt-in and disclosed in response metadata.

## 5. Media handling

- Inputs and outputs are bounded by `REZE_MEDIA_MAX_INPUT_MB` and
  `REZE_MEDIA_MAX_OUTPUT_MB`.
- Each job gets a unique directory; generated file names are sanitised and
  writes outside the workspace are refused.
- Directories are removed in `finally` blocks, including on failure and
  cancellation.
- FFmpeg is invoked with an argument array (never a shell string), a timeout and
  a size check on the result.
- Nothing scans or bulk-downloads chat history; media commands act on the
  replied-to message only, and search commands are bounded.

## 6. Automation

Rules are validated before they can be enabled. `notify` and `command` actions
require a rule created by the owner. The `command` action can only dispatch an
allowlist of safe internal commands through the router — never a shell, never
arbitrary Python. Cooldowns, hourly caps and a recursion guard prevent loops,
and each execution records a short error without storing message content.

## 7. Secrets in diagnostics

`.diagnostics` lists integration readiness and the last five errors after the
logging filter has run. It never prints environment values, stack traces or
session contents.

## 8. Remaining limitations

- In-process plugins are not isolated from the userbot's memory; OS-level
  sandboxing is out of scope for this release.
- The panel's sessions are in memory, so a restart signs everyone out (by design,
  but it also means no "remember me" across restarts).
- A compromised host or account can read the session no matter what Reze does;
  use a dedicated account and a dedicated machine where possible.
- `remove.bg` receives the image you confirm; that is a third-party transfer,
  disclosed in the confirmation prompt.
