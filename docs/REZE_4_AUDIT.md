# REZE 4.0 — Repository Audit

Developer: **UnchartedAli** · Channel: **[@yamods](https://t.me/yamods)**

This audit covers the areas listed below, checked against the source code, the
tests, and the CI workflow. Each finding has a classification and a status.
Status labels: **DONE** (implemented and verified by tests), **PARTIAL**
(implemented but incomplete), **OPEN** (confirmed, not fixed), **PLANNED** (not
implemented), **BLOCKED** (needs something outside this repository).

## Scope and method

Audited in this pass:

- Web panel authentication, sessions, CSRF, headers, cookies, client address
  resolution, login rate limiting
- Backup service (creation, verification, restore, retention)
- Digital Vault encryption and AI tool approval gating
- Plugin loader isolation claims
- Test runner and CI workflow
- Version metadata and the Dockerfile

Not audited in depth in this pass, so no findings are claimed for them:
the installers (Windows and Linux), the message archive (`msglog`), the
workflow engine, the individual command modules, the Persian RTL UI, and
Telegram reconnect behaviour under real network failure. Docker build and
Windows checks were **not run**: Docker is not installed in the build sandbox,
and no Windows machine was available.

## Verified working (evidence)

| Area | Evidence |
| --- | --- |
| Test suite | 378 original tests passed before changes; 394 after this release's additions (`python run_tests.py`, CI runs `python -m unittest discover -s tests -v`). |
| CSRF | `validate_csrf` is applied to state-changing panel requests (`reze/web/app.py`). |
| Security headers | CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, and HSTS when served over HTTPS. |
| Session cookies | `HttpOnly`, `SameSite=Lax`, and `Secure` when the public URL is HTTPS. |
| Password storage | PBKDF2-HMAC-SHA256 with salt (`reze/web/auth.py`). |
| Login throttling | Five failures per window per client address (`check_rate_limit`). |
| AI tool gating | Allowlisted tools, owner-only approval with a short code and TTL, audit table (`reze/ai/tools/registry.py`). |
| Shell execution | `.exec` is off unless `REZE_ENABLE_EXEC=true`. |
| Digital Vault | AES-256-GCM, scrypt key derivation, tests for wrong key and tampering. |
| Model Council | Reports failed members instead of hiding them. Does not invent a consensus. |
| Backups (REZE 3.0 baseline) | SQLite online backup API, integrity check, restore confirmation code with TTL, safety backup before restore. |
| Plugin isolation disclosure | `reze/plugin_manager.py` states that plugins run in the main process. |

## Findings

### HIGH

**H-1. Message content was unencrypted at rest.** PARTIAL. When `REZE_VAULT_KEY` is set, message text is
now encrypted (AES-256-GCM) in the message-guard cache and archive, the style samples and drafts, and undelivered
digest bodies. Reads decrypt. Rows written before the key was set stay readable. Still plaintext: the personal
`archive` table in `database.py` (your own saves and links), the full-text search index, reminders, and notes.
Archive search reads at most 20,000 of the newest rows and filters them in Python, because encrypted text cannot be
searched with SQL. Tests inspect the raw rows: `tests/test_reze4_text_at_rest.py`.

**H-2. Plugins are not isolated.** PARTIAL. An isolated mode now exists alongside the in-process loader:
each isolated plugin runs in its own process with a clean environment, the standard library only, reply as its only
capability (gated by `telegram.message`), timeouts, output limits, containment of crashes and hangs, and approval by
file hash. It is not a sandbox against hostile code: the worker runs as the same OS user and can read the same files.
The in-process loader is unchanged, and isolated loading is not yet exposed in chat. See `docs/PLUGIN_ISOLATION.md`.
Tests start real processes: `tests/test_reze4_plugin_isolation.py`.

**M-3. Web sessions live only in process memory.** PARTIAL. "Sign out everywhere" is DONE (`POST /logout-all`, CSRF-checked, with a header button). Sessions are still kept in
`ACTIVE_SESSIONS`. A restart still signs everyone out. Persistence and per-session revocation are planned for Milestone 2.

**M-4. No multi-factor authentication.** PLANNED.

**M-5. Local test runner reported a false green.** DONE. `run_tests.py` discovered
only module-level functions named `test_*`. It printed "0 passed, 0 failed" and
exited 0 without running the unittest classes. CI was not affected, because it
uses `unittest discover`. The runner now uses unittest discovery, reports real
counts, and exits 1 on failure (checked with a deliberately failing test).

**M-6. Restore replaces the live database file while the process is running.**
PARTIAL. The restore now reports `restart_required` when the schema differs, but
the running process is not restarted automatically, and no lock is taken during
the copy. Restore should be done with the userbot stopped, or followed by a
restart.

**M-7. Backup encryption reads the whole file into memory.** OPEN (performance).
A very large database produces a memory spike during backup and restore. Chunked
authenticated encryption is needed.

### Deployment findings (added in this pass)

**D-1. Compose published a fixed host port (MEDIUM).** DONE. `docker-compose.yml`
published `8080:8080`. Cloady starts apps on `PORT`, so the published port and
the listening port could disagree. Now `${PORT:-8080}` on both sides. The checker
flags fixed ports (`PORT-FIXED`).

**D-2. Compose file rejected by Cloady for a bind mount (HIGH, deployment blocker).**
DONE. The shipped `docker-compose.yml` mounted `./data:/app/data`. Fixed in an
earlier pass; the checker rejects bind mounts (`VOLUME-BIND`) with the same
wording as Cloady's error.

**D-3. Literal `$` in configuration values (LOW).** The panel password hash format
(`salt$hash`) contains `$`, which Compose reads as a variable. DONE: the checker
warns (`DOLLAR-ESCAPE`), and `DEPLOY.md` says to write `$$`.


**D-4. Migrations were not atomic (HIGH, data-safety).** DONE. The runner called `rollback()` after a
failed migration, but Python's `sqlite3` runs `CREATE TABLE` outside a transaction, so the failed step's
tables survived. Each migration now runs inside an explicit `BEGIN IMMEDIATE`. Found by
`tests/test_reze4_upgrade.py`.

### LOW

**L-1. `datetime.utcnow()` is deprecated.** DONE in `reze/`: all call sites now use `reze.timeutil.utcnow()`, which returns the same naive UTC values. Test files still contain a few calls.

**L-2. Image version label was `2.0.0`** while the package is `3.0.0`. DONE.

**L-3. Decrypted backup scratch files** are created in the system temp directory
during verify and restore and removed in a `finally` block. A killed process can
leave one behind. OPEN. Acceptable for now, but should be documented.

**L-4. AI budgets count calls, not tokens or cost.** `reze/ai/budget.py` enforces
a daily call count. Per-provider token and cost accounting is PLANNED (Milestone 4).

## Missing capabilities (requested by REZE 4.0, not present in the code)

- Multi-factor authentication
- Live updates (server-sent events) for the web panel
- Plugin marketplace, plugin signatures, integrity verification
- Process-isolated plugins
- Visual workflow editor
- Semantic memory and embeddings; the knowledge graph
- Module A (Telegram power tools): smart inbox, the upgraded scheduler, quick reply
  templates, the media manager, Telegram analytics, the chat workspace
- Module B (Cloady deployment manager): **BLOCKED**, see the roadmap

## Recommended order

1. H-1 at-rest design decision, then implementation (Milestone 2).
2. H-2 plugin process isolation (Milestone 2–3).
3. M-3 persistent and revocable sessions; M-4 MFA.
4. H-3 `.backup` output showing encryption state, and M-7 streaming encryption.
5. Module A and the Module B preparation tooling, after the foundations above.
