# Database, migrations and retention

REZE stores everything in one SQLite file (default `data/reze.db`). The
connection runs in WAL mode with foreign keys enabled. There is no external
database server and no cloud dependency.

## Files

| Path | Contents |
| --- | --- |
| `data/reze.db` | Main database |
| `data/reze.db-wal`, `-shm` | WAL files; back up with the database or while stopped |
| `data/backups/` | Timestamped SQLite copies created by `.backup create` |
| `data/msglog/` | Message Guard temporary cache and permanent archive |
| `data/media/` | Temporary media workspaces (deleted after each conversion) |
| `data/reze.session` | Telethon file session when `REZE_SESSION_STRING` is not used |

Protect this directory. The database is plaintext SQLite; only vault rows are
stored as ciphertext.

## Schema versions

| Version | Contents |
| --- | --- |
| 2 | REZE 2 baseline. Created with `CREATE TABLE IF NOT EXISTS`, version kept in `PRAGMA user_version` |
| 3 | REZE 3 services: feature state, audit, memories, timeline, life graph, CRM, decisions, focus, writing, projects, tasks, expenses, inbox, vault, workflows, AI tool audit/approvals/usage, sentinel, documents, voice notes, maintenance, backups |
| 4 | Universal search: `search_index` plus an FTS5 virtual table and triggers |

The current version is stored in `PRAGMA user_version` **and** in
`schema_migrations(version, name, applied_at)`, so history is inspectable:

```sql
PRAGMA user_version;
SELECT version, name, applied_at FROM schema_migrations ORDER BY version;
```

## How migrations run

`reze/core/migrations.py`:

1. Creates `schema_migrations` if needed.
2. Treats a pre-versioning database as baseline 2 and records it without
   touching data.
3. Applies each migration newer than the stored version, in one transaction.
4. Records the version and moves `PRAGMA user_version` forward.
5. On failure: rolls back that migration, logs the reason and leaves the
   database at its previous version.

Migrations are append-only. Applied files are never edited; new changes are new
numbered files in `reze/migrations/`. They only add tables, indexes and
triggers — no migration drops or recreates user data.

Migration 4 tries to create the FTS5 table. SQLite builds without FTS5 still
work: the failure is caught, `global_settings['search.fts5']` is set to `0`, and
universal search falls back to a bounded `LIKE` scan.

## Important tables

| Table | Purpose |
| --- | --- |
| `feature_state` | `key`, `enabled`, `updated_at`, `updated_by`; the source of truth for the 23 optional features |
| `audit_log` | Feature toggles, approvals, security-relevant actions |
| `memories` | Durable AI memories with tags, pin/archive flags |
| `timeline_events` | One stream of events from all subsystems |
| `life_entities`, `life_relations` | Life Graph nodes and typed edges |
| `crm_contacts`, `crm_interactions` | Contacts and interaction history |
| `decisions` | Decisions, options, expected outcome, review date, outcome |
| `focus_sessions` | Start/stop, duration, label |
| `writing_samples` | Text samples for the Writing DNA profile |
| `projects`, `tasks` | Local project/task tracker |
| `expenses` | Amount, category, note, date |
| `inbox_items`, `inbox_rules` | Classified incoming messages and local rules |
| `vault_entries` | Name, kind, filename/mime/size, `nonce`, `ciphertext` |
| `workflows`, `workflow_runs`, `workflow_steps` | Workflow definitions, runs and step attempts |
| `ai_tool_audit`, `ai_approvals`, `ai_usage` | Tool calls, pending approvals, daily budget |
| `sentinel_findings` | Security checks and resolution state |
| `documents`, `voice_notes` | Extracted document text and transcriptions |
| `maintenance_runs` | Integrity/retention runs |
| `backups` | Backup path, size, kind, status |
| `search_index` + `search_fts` | Universal search documents and FTS5 index |

Feature state and preferences are separate: preferences live in
`global_settings`, keyed `pref:<name>`. A preference can never enable a feature.

## Vault encryption

- Cipher: AES-256-GCM (`cryptography`), 12-byte random nonce per entry.
- Key: scrypt (n=2^14, r=8, p=1, 32 bytes) over `REZE_VAULT_KEY` with the fixed
  salt `reze-vault-v1`. If `REZE_VAULT_KEY` is empty a non-default
  `REZE_SECRET_KEY` is used; if neither exists, the vault reports "locked" and
  stores nothing.
- Stored columns: `nonce` and `ciphertext` BLOBs. Plaintext is never written to
  the database, logs or command output.
- Names are unique case-insensitively: storing `Token` then `token` updates one
  row.
- A wrong key or tampered ciphertext raises an authentication error; Reze does
  not return partial plaintext.

Because the key is derived from an environment value, losing it means losing
vault data. There is no recovery path and no backdoor.

## Backups and restore

`.backup` uses the SQLite online backup API, so it is consistent while Reze runs:

```text
.backup create              create data/backups/reze-<timestamp>-<kind>.db
.backup list                list known backups with existence and size
.backup verify <id>         integrity_check and schema version of a backup
.backup restore <id>        prepare a restore; prints a 6-digit code
.backup confirm <code>      perform the restore (constant-time compare)
.backup prune [keep]        delete old backups, keeping the newest N
```

Before a restore, Reze creates a safety copy of the live database. Backups are
plain SQLite files: vault rows stay encrypted inside them, but the rest of the
data is readable, so protect `data/backups/`.

## Retention

| Setting | Default | Applies to |
| --- | --- | --- |
| `REZE_RETENTION_DAYS` | 365 | Service history such as old timeline events, runs and inbox items |
| `REZE_AUDIT_RETENTION_DAYS` | 180 | `audit_log`, tool audit and AI usage rows |

Retention is never applied silently. `.maintain` shows the plan and
`.maintain apply confirm` performs the deletions. Message Guard has its own
settings (`.watch keep`, `.watch archive`); the permanent archive is not touched
by retention.

## Integrity checks

`.maintain` reports database integrity, backup age and the retention plan.
`.sentinel run` adds security-oriented checks (default credentials, missing
vault key, permissive settings). Findings are stored in `sentinel_findings` and
resolved explicitly with `.sentinel resolve <id>`.

## Moving or copying a deployment

1. Stop Reze.
2. Copy `.env` and the whole `data/` directory.
3. Start Reze on the new host and run `.status`, `.maintain` and `.vault status`.
4. Keep the same `REZE_VAULT_KEY`; otherwise vault entries and encrypted content
   cannot be read.

Never copy a live WAL database with a plain file copy while the process is
running — use `.backup create` instead.
