# REZE 4.0 — Roadmap and Status

Developer: **UnchartedAli** · Channel: **[@yamods](https://t.me/yamods)**

Status labels: **DONE** (implemented and verified by tests), **PARTIAL**
(implemented but incomplete or not fully verified), **BLOCKED** (needs an
external dependency or access that this repository cannot provide), **PLANNED**
(not implemented). Nothing below is marked DONE without test evidence.

The current package version is still **3.0.0**. The 4.0.0 version bump happens
at release, after the milestones below are complete.

## Milestone 1 — Audit, critical fixes, security review, database safety

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Repository audit (`docs/REZE_4_AUDIT.md`) | PARTIAL | Covers the areas listed in its scope. Installers, msglog, workflows, and the UI were not audited in depth. |
| Login rate limit bypass fix (H-4) | DONE | `tests/test_reze4_security_fixes.py` |
| Restore schema guard (M-1) | DONE | `tests/test_reze4_backup_security.py` |
| Exact backup identifiers (M-2) | DONE | `tests/test_reze4_backup_security.py` |
| Test runner false green (M-5) | DONE | `run_tests.py` exits 1 on failure; checked with a deliberately failing test. |
| Version label consistency (L-2) | DONE | Dockerfile label now `3.0.0`. |
| At-rest protection for message data (H-1) | PARTIAL | Message guard cache and archive, style samples and drafts, and digest bodies are sealed when `REZE_VAULT_KEY` is set. Personal archive, search index, reminders and notes are not yet. Tests in `tests/test_reze4_text_at_rest.py`. |
| Atomic migrations (a failed migration rolls back its tables too) | DONE | Fixed: DDL ran outside a transaction, so a failure left tables behind. Test `tests/test_reze4_upgrade.py::MigrationSafetyTests`. |
| Verified copy before any upgrade (migration validation and backup) | DONE | `reze/core/upgrade_backup.py`, run before any startup write. Copy checked by integrity and version, newest 5 kept. Startup stops if the copy fails. `REZE_SKIP_UPGRADE_BACKUP=1` disables it. Tests in `tests/test_reze4_upgrade_backup.py`. |

## Milestone 2 — Backup and recovery, account security, plugin isolation

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Backup encryption (AES-256-GCM, key never stored in the backup) | PARTIAL | Active only when a vault key is configured. Tests: encrypted round trip, wrong key, tampering, missing key, plaintext fallback. |
| Restore verification and safety backup | DONE | Existing REZE 3.0 behaviour, now covering encrypted backups. |
| Backup warning when unencrypted (H-3) | DONE | Security center check `_check_backup_encryption`. Tested in `tests/test_reze4_sessions_sentinel.py`. The `.backup` command output does not show it yet. |
| Streaming encryption for large databases (M-7) | PLANNED | |
| Scheduled backups, retention policies, backup health | PLANNED | Retention is currently count-based pruning only. |
| Export and import, SFTP, S3-compatible destinations | PLANNED | Remote destinations are disabled by default when implemented. |
| Sign out everywhere (M-3, part one) | DONE | `POST /logout-all` with CSRF check, plus a header button. Sessions are still held in memory. Persistence and per-session revocation are PLANNED. |
| Multi-factor authentication (M-4) | PLANNED | |
| Telegram session inventory and security alerts | PLANNED | Only what Telethon's authorization APIs expose may be claimed. |
| Plugin process isolation (H-2) | PLANNED | Currently disclosed as in-process. |

## Milestone 3 — Plugin SDK, plugin manager, marketplace foundation

PLANNED. Install from ZIP and Git, enable, disable, version pinning, integrity
verification, and an owner-approved marketplace. Nothing is implemented yet.

## Milestone 4 — AI Brain 2.0

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Model Council honest disagreement reporting | DONE (REZE 3.0) | Existing behaviour, not changed. |
| Daily call budget | PARTIAL | Counts calls. Token and cost budgets are PLANNED. |
| Semantic memory, embeddings, memory confidence and expiry | PLANNED | |
| AI activity timeline with privacy levels | PLANNED | |

## Milestone 5 — Personal OS integration and cross-module search

PLANNED. Existing modules (memory, life graph, CRM, decisions, focus, timeline,
projects, expenses, reminders, search) are present from REZE 3.0 but are not
integrated under a shared identity model in this release.

## Milestone 6 — Visual workflow builder

PLANNED. The automation engine (`reze/automation/`) exists, but the web editor
does not.

## Milestone 7 — Web Panel 4.0

PLANNED. Live updates, responsive redesign, and full Persian RTL support.
The current panel keeps its existing pages.

## Milestone 8 — Installers, Docker and managed hosting, documentation

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Compose file uses a declared named volume | DONE | `docker-compose.yml` mounts `reze_data:/app/data`. |
| `.dockerignore` keeps secrets and local state out of the image | DONE | `.dockerignore` |
| Cloady deployment guidance | PARTIAL | `DEPLOY.md` section 5a. Based on Cloady's public templates and samples repositories. Not verified on a live Cloady deployment. |
| Compose checker against Cloady's documented rules | DONE (CLI) | `python -m reze.deploy.compose_check`. See Module B. |
| Docker image build | PARTIAL | Built from the repository's Dockerfile on a local stand-in for `python:3.12-slim` (Ubuntu 24.04 Python 3.12, with the sandbox certificate trusted). The official base could not be pulled here. |
| Container run (health, login, sessions, restart on the same volume) | DONE (locally) | Verified with `docker run` on the built image: `/healthz` on the `PORT`, login success and failure, session redirects, data volume reused after restart. |
| `docker compose` with the shipped file | DONE (locally) | Rendered by Compose v2.29.7. Started with `--no-build`, because BuildKit needs Docker Hub. Found and fixed a real bug: the container did not receive `PORT`. |
| Windows installation check | BLOCKED (in this environment) | No Windows machine available. |

## Milestone 9 — Regression tests, security verification, release

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Full test suite | DONE for this release | 394 tests pass with `python run_tests.py`. |
| Upgrade from REZE 2 and 3.0 databases | PARTIAL | Tests in `tests/test_reze4_upgrade.py` (rebuilt 3.0 database; REZE 2 shape). The uploaded `data/reze.db` is a REZE 2 file (version 2); a copy upgraded to version 6 with its row intact, integrity OK, new features OFF. No real REZE 3.0 file was available. |
| Release notes and 4.0.0 version metadata | PLANNED | Version remains 3.0.0. |

## Module A — Telegram Power Tools

| Feature | Status |
| --- | --- |
| Smart Inbox | PLANNED |
| Advanced Message Scheduler (persistent, retry, timezone-aware, duplicate prevention) | PLANNED. REZE 3.0 automation and reminders are the starting point. |
| Smart Saved Messages | PLANNED |
| Universal Telegram Search | PLANNED. A REZE 3.0 search module exists. |
| Quick Replies (templates, variables, AI rewrite) | PLANNED |
| Privacy Control Center | PLANNED |
| Media Manager | PLANNED |
| Telegram Analytics | PLANNED |
| AI Chat Assistant | PLANNED |
| Chat Workspace | PLANNED |
| Group and Channel Tools | PLANNED |

## Module B — Cloady Deployment Manager

Cloady's public material: a CLI (`cloady deploy`), a dashboard, an MCP server at
`https://cloady.com/api/mcp` (OAuth, scopes read / deploy / full), and build paths
(Railpack, a Dockerfile, or a compose template). Its REST endpoints are not
documented in any source reachable from this environment.

| Item | Status | Reason / evidence |
| --- | --- | --- |
| Offline Compose checker (`python -m reze.deploy.compose_check`) | DONE (CLI only) | `reze/deploy/compose_check.py`, 25 tests in `tests/test_reze4_compose_check.py`. Found the fixed-port and bind-mount problems. Not yet exposed through Telegram or the web panel (PARTIAL for interfaces). |
| Cloady deployment guidance | PARTIAL | `DEPLOY.md` section 5a. Based on Cloady's public samples and templates repositories. Not verified on a live Cloady deployment. |
| Cloady MCP client (deploy, status, logs, env, domains) | PLANNED | Confirmed from the public `Cloady/cloady-mcp` repository: about 88 tools generated from Cloady's OpenAPI contract, named after operation IDs (for example `listVars`, `createVar`, `deployApp`, `readServiceLogs`, `queryAppLogs`); endpoint `https://cloady.com/api/mcp`; OAuth or a dashboard API token (Account → API tokens); scopes read, deploy, full. Needs a per-capability permission design in REZE before any write tool is exposed. |
| Cloady REST API integration | BLOCKED | No public REST reference was reachable in this environment. Not invented. |
| GitHub OAuth (repositories, branches, commits) | BLOCKED | Needs an OAuth app registered by the owner (client ID and secret). |
| Environment manager with secret redaction | PLANNED | |
| Deployment monitor, AI deployment assistant | PLANNED | Depends on the Cloady MCP or API. |

## Next step

Ask the owner to deploy once with the Cloady CLI from the repository. Then:
1. Report the first failure, if any, to the checker and the deploy guide.
2. Confirm the three items listed in `DEPLOY.md` (port resolution, disk default,
   build path). Update the guide and the checker's source tags to match.
3. Then design the Cloady MCP client, with a scope per capability (read, deploy,
   full), before implementing any write action.

## Channel Digest (specification: Channel Digest module)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Schema, migration 5, OFF by default | DONE | `reze/migrations/v5.py`; tests in `tests/test_reze4_digest.py` |
| Scheduling: daily / weekly / custom, timezone, DST | DONE | `reze/digest/schedule.py`; scheduling tests |
| One run per slot, duplicate prevention | DONE | UNIQUE slot key; tests |
| Missed slots after downtime, one catch-up digest | DONE | Test with a three-day outage |
| Checkpoints moved with the stored digest only | DONE | Atomicity and failure tests |
| Delivery retries with backoff; digest never discarded | DONE | Retry test |
| Flood-wait handling while reading and sending | DONE | Fake flood-wait tests |
| AI summaries with grounding check; basic fallback | DONE | Verification and fallback tests |
| Long digests split without losing content | DONE | Splitting tests |
| Saved Messages as the only destination | DONE | Destination test |
| Privacy: only selected channels read; OFF by default | DONE | Tests for unselected and disabled channels |
| Commands (`.digest ...`) and `.chatdigest` compatibility | DONE | Command tests |
| Persistence across restarts | DONE (logic) | Restart test with a fake client. A real restart has not been run |
| Telegram behaviour against a live account | BLOCKED | No live account available for testing |
| Web panel dashboard (Persian and English, RTL) | DONE | Channel Digest page with settings, channel controls, Generate now, history, and confirmed deletion. Tests in `tests/test_reze4_digest_panel.py`. Not checked in a browser. |
| Media OCR and transcription | PLANNED | Not implemented; media is described only |
| Digest history deletion in the web panel | DONE | Confirmed deletion on the Channel Digest page |

## Style Assistant (owner's writing style, drafts, labelled auto-replies)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Learn only the owner's own text messages from named chats | DONE | `reze/style/service.py`; tests in `tests/test_reze4_style.py` |
| Deterministic style profile (no AI needed) | DONE | `reze/style/profile.py` |
| Drafts for approval in Saved Messages, sent only on `.style send` | DONE | Draft tests; no incoming text stored |
| Automatic replies: allow list, private only, never bots or groups | DONE | Gate tests in `reze/style/safety.py` |
| Fixed automation label on every automatic reply | DONE | Label tests, including a mutation check |
| Sensitive messages get no reply; owner notified without text | DONE | Sensitive-word tests |
| Quiet hours, owner-active check, cooldown, hourly cap | DONE | Gate tests |
| No canned fallback when AI is unavailable | DONE | AI-failure tests |
| Forget everything | DONE | Forget test and confirmation |
| Telegram behaviour against a live account | BLOCKED | No live account available for testing |
| Web panel for the assistant | PLANNED | Not started |

## Audit items closed in this round

| Item | Status | Evidence |
| --- | --- | --- |
| Migrations atomic (D-4) | DONE | `tests/test_reze4_upgrade.py` |
| Verified copy before upgrades | DONE | `tests/test_reze4_upgrade_backup.py` |
| Message text sealed at rest (H-1, partial) | PARTIAL | `tests/test_reze4_text_at_rest.py` |

## Plugin isolation (audit H-2)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Separate process for isolated plugins | DONE | `reze/sandbox/isolation.py`; tests start real processes |
| Clean environment, standard library only | DONE | Secrets test; import-block test |
| Reply-only capability gated by declared permission | DONE | Permission tests |
| Timeouts, output limits, crash and hang containment | DONE | Failure-containment tests |
| Memory and CPU limits | DONE on POSIX only | Resource-limit test (skipped on Windows) |
| Approval by file hash | DONE | Approval tests |
| Chat command to load isolated plugins (`.isolated`) | DONE | Owner only, OFF by default. Name-only input, folder confinement, symlink refusal, change detection. Tests in `tests/test_reze4_isolated_command.py`. |
| More host capabilities (storage, settings, Telegram calls) | PLANNED | Each needs its own permission |
| Operating-system sandbox (filesystem and network confinement) | BLOCKED | Not provided by Python; needs OS-specific tooling. Not claimed. |

## End-to-end check (new in this round)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Application starts in panel-only mode; panel answers | DONE | `python -m reze.app`, `/healthz` returns 200 |
| Every navigation page loads for a signed-in owner | DONE | `scripts/smoke_panel.py`: 15 pages returned 200 |
| No errors or tracebacks in the startup log | DONE | Only expected warnings about missing Telegram credentials |
| Telegram behaviour with a live account | BLOCKED | No account available here |
| Browser rendering and layout | BLOCKED | Not checked in a browser |

## Watchdog bridge and sticker bot (new in this round)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Sticker bot defaults to @watchdogappbot; other bots refused | DONE | `tests/test_reze4_watchdog.py` (mutation check: removing the check fails the tests) |
| Sticker bot token stored encrypted, never in plain text on disk | DONE | `reze/storage/secret_store.py`; the raw database value is checked in tests |
| Reze → Watchdog signed events | DONE | Python client and Node worker verify the same signature (shared vector) |
| Watchdog → Reze health alert and recovery notice | DONE | `integrations/watchdog/test_bridge.mjs`, 13 tests on the real worker code |
| Real client to real worker over HTTP | DONE | `tests/test_reze4_watchdog_e2e.py` (Node required) |
| Watchdog worker deployed on Cloudflare | BLOCKED | Needs your Cloudflare account and secrets |
| Telegram delivery of owner messages | BLOCKED | Telegram is stubbed; no live account here |

## Consent, shared summaries and worker features (this round)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Consent per data type, off by default, revocable, enforced before any send | DONE | `reze/consent.py`; `tests/test_reze4_consent.py` (20 tests) |
| Consent page in the Reze panel (grant and revoke buttons, CSRF) | DONE | Page and routes tested over HTTP; not checked in a browser |
| Summaries of chosen channel posts by the Watchdog bot | DONE | Worker route tested in `integrations/watchdog/test_summarize.mjs` (8); end-to-end in `tests/test_reze4_watchdog_e2e.py` |
| Summary lines checked against the posts; unsupported numbers and links removed | DONE | `verify_summary`; tests in `tests/test_reze4_consent.py` |
| Nothing stored or sent to Telegram by the summary route | DONE | Test checks the worker's storage contents and Telegram calls |
| Premium emoji: several packs, list, remove; old single map migrated | DONE | `integrations/watchdog/test_premium.mjs` (8) through the real webhook |
| Install Reze on a Telegram account through the Watchdog bot | REFUSED | A bot that asks for login codes or session strings is the usual phishing pattern, and Telegram forbids it. Use `scripts/generate_session.py` on your own machine instead. |
| Style sharing with the Watchdog bot (consent scope) | PLANNED | Not built. It needs its own consent scope and storage rules. |
| Channel autopilot: media on the draft edit button | DONE | Edit accepts photos, GIFs, video, documents, stickers and forwards. Tests in `integrations/watchdog/test_autopilot.mjs`. |
| Channel autopilot: manual channel description used by drafts | DONE | The 📝 channel note is stored and used in the draft prompt. Test covers save, reset, length cap and admin check. |
| Channel autopilot: publish a forwarded message without the sender name (copy) | DONE | Drafts with a forwarded post or media publish with `copyMessage`. Tests check that no forward method is called. |
| Anonymous link with a custom name (t.me/bot?start=name) | PLANNED | Not built. The start handler must be changed carefully. |

## Autopilot changes (second part)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Premium emoji packs, list and remove (earlier in the round) | DONE | `test_premium.mjs` |
| Autopilot copy, media and channel note | DONE | `test_autopilot.mjs` (7 tests, real SQL). Two mutation checks confirmed the tests catch a broken publish path and a missing admin check. Not run against a live channel. |

## Anonymous links and reactions (this round)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Anonymous link: visitor, owner reply by button | DONE | `test_anon.mjs` (flow tests passed before any change) |
| Anonymous link: Telegram Reply in both directions (was silently ignored) | DONE | Found by `test_anon.mjs`; fixed by a reply mapping. Mutation check: removing the mapping fails the test. |
| Anonymous link: custom name `start=<name>` | DONE | `/anon name <name>`; tests in `test_anon.mjs` |
| Reactions in channels (one emoji the channel allows) | DONE | `test_reactions.mjs`; off by default |
| Reactions in groups (chance, rate-limited) | DONE | `test_reactions.mjs`; off by default |
| Reactions in private chats (random standard emoji) | DONE | `test_reactions.mjs`; off by default |
| Switches are owner-only | DONE | Test: a non-owner cannot switch reactions on |
| Real Telegram behaviour of these features | BLOCKED | Telegram is stubbed; no live channel, group or account here |

## Buttons for the custom name and reaction switches (this round)

| Item | Status | Evidence / notes |
| --- | --- | --- |
| Custom anonymous name from a button in the `/anon` panel | DONE | `test_anon.mjs` presses the button; the link then opens |
| Reaction switches as buttons in `/react` (owner only) | DONE | `test_reactions.mjs` presses each button; a non-owner changes nothing |
| Callback gate accepts the reaction prefix | DONE | Found by the tests: `rx:` was missing from the gate list, so the buttons did nothing |
| Panel in the Reze web interface for these | NOT DONE | These controls live in the Watchdog bot, which is where the anonymous link and reactions run |
