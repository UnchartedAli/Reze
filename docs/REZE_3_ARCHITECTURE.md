# REZE 3 architecture

REZE 3.0 is a modular monolith: one Python process, one SQLite database, one
command router and one feature switch. Subsystems are packages with explicit
service objects rather than microservices. This keeps deployment simple
(one process, no message broker) without turning the codebase into a pile of
imports.

## Layers

```
Telegram events ─┐
                 ├─► command_router ─► commands/ ─► subsystem packages
Web panel ───────┘                          │
                                            ├─► storage/ (SQLite, vault, backups)
                                            ├─► ai/ (gateway, tools, council)
                                            ├─► automation/ (rules, workflows)
                                            └─► core/registry (services, events)
```

- **Transport** — Telethon userbot handlers and the HTTP panel both end in the
  same command router or service APIs. There is no second business-logic path.
- **Commands** — thin adapters: parse arguments, check permissions and feature
  state, call a subsystem, render with the ASCII engine.
- **Subsystems** — `personal/`, `productivity/`, `capture/`, `security/`,
  `storage/`, `automation/`, `ai/`. Each owns its tables and validation.
- **Storage** — `database.py` (connection, WAL, baseline schema, migrations) and
  `core/migrations.py` (versioned runner).
- **Presentation** — `ui/` for Telegram, `web/` for the panel. Both read the same
  state; neither caches business data.

## Feature gate

`reze/features.py` is the single source of truth for optional behaviour:

- 23 keys, each with a category, a label, a description and a `sensitive` flag.
- State lives in the `feature_state` table. A missing row, empty value or unknown
  key resolves to **OFF**.
- Enabling a sensitive key requires `confirmed=True`; otherwise
  `FeatureConfirmationRequired` is raised and nothing changes.
- `set_enabled` writes exactly one row. It never calls another key's setter, so
  there is no cascade.
- Every change is written to `audit_log` with the actor.

Commands follow one pattern:

```python
if not features.is_enabled("vault"):
    return await ctx.reply(ascii.info(
        "Vault is OFF",
        ["Enable it with: .features enable vault confirm"],
    ))
```

They never enable the feature for the user and never simulate the result.

## Service registry and event bus

`reze/core/registry.py`:

- `Service` has a `name`, an optional `feature` key, a status
  (`registered|running|stopped|failed|disabled`) and a `health()` dict.
- `registry.start_all()` starts **only** services whose `feature` is enabled.
  Services with no feature key always start. A failing service is marked
  `failed` and does not stop the rest.
- `registry.stop_all()` stops in reverse order and never raises during shutdown.
- `EventBus` is a small in-process pub/sub with a bounded history of event names
  (payload keys only, no secret values) and isolated handlers.

Registered optional services in 3.0: `focus`, `workflow`, `random_reactions`
and `bot_companion`. Each declares its feature key, so a restart after enabling
one starts that one only.

## The 23 optional features

| Key | Category | Sensitive | Command(s) |
| --- | --- | --- | --- |
| `memory` | Knowledge | no | `.memory` |
| `life_graph` | Knowledge | no | `.graph` |
| `crm` | Personal | no | `.crm` |
| `decisions` | Personal | no | `.decide` |
| `focus` | Personal | no | `.focus` |
| `timeline` | Knowledge | no | `.timeline` |
| `writing_dna` | Knowledge | no | `.writing` |
| `projects` | Productivity | no | `.project` |
| `expenses` | Productivity | no | `.expense` |
| `workflows` | Automation | yes | `.workflow` |
| `random_reactions` | Automation | yes | `.reactions` |
| `background_monitoring` | Automation | yes | (guard/alert background work) |
| `vault` | Security | yes | `.vault` |
| `security_sentinel` | Security | yes | `.sentinel` |
| `self_maintenance` | Security | no | `.maintain` |
| `bot_companion` | Security | yes | `.companion` |
| `ai_agent` | AI | yes | `.agent` |
| `model_council` | AI | yes | `.council` |
| `insights` | AI | no | `.insights` |
| `smart_inbox` | Capture | yes | `.inbox` |
| `universal_search` | Capture | no | `.usearch` |
| `voice_intelligence` | Capture | yes | `.voice` |
| `document_intelligence` | Capture | yes | `.doc` |

Feature metadata is reported by `.features`, the panel's Optional features page
and the installer menu. The list above is derived from `FEATURES`; a test checks
that the default state is OFF for every key.

## Subsystem notes

### Personal knowledge (`reze/personal/`)

- `memory` — durable notes with tags, pin/archive, search and optional use as AI
  context. When the feature is OFF, `.memory` explains how to enable it.
- `life graph` — entities (`life_entities`) and typed relations
  (`life_relations`), created with `.graph add` and `.graph link`.
- `crm` — contacts, interaction log, birthday and stale-contact views.
- `decisions` — options, expected outcome, review date and outcome review.
- `focus` — timed sessions written to `focus_sessions` and `timeline_events`.
- `timeline` — read-only chronological view over events emitted by other
  subsystems.
- `writing_dna` — samples, deterministic style metrics and comparison of new
  text. It does not claim to clone a writing style with AI.

### Productivity (`reze/productivity/`)

Projects, tasks (priority, due date, project link) and expenses with monthly
summaries. Reminders and QR generation remain from 2.0.

### Capture (`reze/capture/`, `reze/search/`)

- `inbox` — classifies incoming messages locally using rules; it never replies.
- `usearch` — searches `search_index` through FTS5 when available, otherwise a
  bounded `LIKE` scan.
- `voice` — sends a replied voice note to the configured provider for
  transcription, subject to `REZE_VOICE_MAX_MB`.
- `doc` — extracts text from replied documents and indexes it in
  `documents` + `search_index`.

### Security (`reze/security/`, `reze/storage/`)

- `sentinel` — local checks (default credentials, missing vault key, permissive
  flags) stored as findings.
- `maintenance` — integrity, backup age and a retention plan that is applied
  only with `.maintain apply confirm`.
- `vault` — AES-256-GCM entries, scrypt-derived key, case-insensitive names.
- `backups` — SQLite online backups, verify, restore with a 6-digit code.

### AI (`reze/ai/`)

Provider adapters (OpenAI, Anthropic, Gemini, OpenAI-compatible) share one
gateway. Tool calling adds `tools/` (allowlist), `ai_approvals` (6-digit code,
15 minutes), `ai_tool_audit` and `ai_usage` (daily budget). Approving a call is
owner-only, idempotent and invalidated when `ai_agent` is turned off.

### Automation (`reze/automation/`)

Rules are `trigger → conditions → actions` with cooldowns, hourly caps and
recursion guards. Workflows add persistent steps, retries, run history,
idempotency keys and explicit resume after a restart. See
[AUTOMATION.md](AUTOMATION.md).

## Lifecycle

`reze/app.py`:

1. Configure console and logging, print the banner.
2. Load plugins, start the panel thread.
3. Start always-on services (clock, reminders, presence, automation rules).
4. Register optional services and call `registry.start_all()` — only enabled
   features start.
5. Start Message Guard, AFK and alerts if configured.
6. Warn about production configuration problems.
7. Wait for a signal; stop services, the client and the panel.

## Failure policy

- Optional integrations degrade: no AI key means AI commands say "not
  configured"; no FFmpeg means video commands explain how to install it.
- A failing service is isolated and reported by `.status` and `/health`.
- A failing event handler is counted and logged; the emitter continues.
- A failing migration rolls back and the process reports the version it kept.
- Plugins run in-process with full privileges. The manifest is a consent
  document, **not** a sandbox; a broken plugin can affect the whole process.

## Why a monolith

The alternative — separate processes per subsystem — would add a broker, service
discovery, duplicated models and a much harder backup story, while the workload
is a single user's personal data. One SQLite file makes backup, restore, export
and portability trivial, which is the actual requirement here.
