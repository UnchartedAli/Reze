# Automation

REZE has two automation layers:

1. **Rules** — a deliberately small `trigger → conditions → actions` engine that
   runs by default (`REZE_AUTOMATION_ENABLED=true`).
2. **Workflows** — a persistent multi-step engine behind the `workflows` feature,
   which is **OFF by default and sensitive**.

Neither layer executes shell commands or arbitrary Python, and neither can be
created remotely by another Telegram user.

## 1. Rules model

```
trigger (when)  →  conditions (if)  →  actions (do)
```

| Trigger | Config | Fires when |
| --- | --- | --- |
| `schedule` | `at=HH:MM` | every day at that local time (`REZE_TIMEZONE`) |
| `interval` | `minutes=N` (1-1440) | every N minutes since the last run |
| `keyword` | `text=WORD` | an incoming message contains WORD (case-insensitive) |
| `task_failed` | — | a background task failed or timed out |

| Action | Config | Effect |
| --- | --- | --- |
| `remind` | `text=...` | creates a reminder due in one minute |
| `save` | `text=...` | writes an archive entry |
| `notify` | `text=...` | sends a message to the chat or the owner — **owner-created rules only** |
| `ai_summary` | `text=...` | summarizes content with the AI gateway and stores the result |
| `command` | `name=<cmd> args=<...>` | dispatches an allowlisted command — **owner-created rules only** |

Allowlisted commands: `remind`, `save`, `notes`, `qr`, `ping`, `aiinfo`, `id`,
`version`.

Conditions: `contains` (substring), `chat_id` (exact chat), `media` (has media).

Placeholders available in action text: `{text}`, `{chat_id}`, `{sender_id}`.

## 2. Creating rules

```text
.automation create daily | trigger=schedule at=18:30 | action=notify text=Review the day
.automation create deploy | trigger=keyword text=deploy | action=save text=Deploy mentioned in {chat_id}
.automation create water | trigger=interval minutes=90 | action=remind text=Drink water

.automation list
.automation show daily
.automation enable daily
.automation disable daily
.automation delete daily
```

Rules are created **disabled** and validated again before enabling. Invalid
rules are rejected with the specific problem (bad time, missing action, command
not on the allowlist, …). The panel can create the same rules from a form.

## 3. Safety controls

| Control | Behaviour |
| --- | --- |
| Validation | trigger/action types, config ranges, allowlist, cooldown bounds |
| Enable gate | a rule must pass validation again before it can run |
| Cooldown | minimum seconds between two runs of one rule (5-86400) |
| Hourly cap | `REZE_AUTOMATION_RUNS_PER_HOUR` (default 30) per rule |
| Rule cap | `REZE_AUTOMATION_MAX_RULES` (default 50) |
| Recursion guard | actions cannot re-enter the engine more than two levels deep |
| Outgoing messages | `notify`/`command` require `created_by == REZE_OWNER_ID` |
| No shell | there is no action that starts a process or evaluates Python |
| Execution log | run count, last run and a short error are stored, no message bodies |

Keyword rules ignore outgoing messages (`message.out`), so a reply cannot
trigger itself.

## 4. Operational notes

- The engine polls every 20 seconds; schedule triggers fire once per minute
  window and are marked to avoid duplicates.
- Rules run inside the main event loop; long AI calls are bounded by the AI
  timeout and run in worker threads.
- `task_failed` evaluates the in-process task history, which is not persisted
  across restarts.
- Disabling a rule stops future runs immediately; running actions are not
  interrupted.

## 5. Example: daily digest

```text
.automation create digest | trigger=schedule at=21:00 | action=ai_summary text=Summarize today's archive
.automation enable digest
```

Requires a configured AI provider. Without one, the action records an error and
the rest of the rule set keeps running.

## 6. Persistent workflows

Workflows are a separate engine in `reze/automation/workflow.py`. They are
disabled until you run:

```text
.features enable workflows confirm
```

A workflow definition is a name plus up to **20 ordered steps** stored as JSON.
Every step has an `action` and action-specific fields:

| Action | Fields | Effect |
| --- | --- | --- |
| `send_message` | `chat_id`, `text` | send a message |
| `notify_owner` | `text` | message the owner |
| `save_memory` | `content`, `tags` | store a memory (needs `memory` for recall) |
| `add_timeline` | `kind`, `title`, `body` | append a timeline event |
| `add_task` | `title`, `project`, `priority` | add a local task |
| `add_reminder` | `text`, `minutes` | schedule a reminder |
| `log` | `message` | write to the log |
| `wait` | `seconds` | pause between steps |

Steps are validated strictly: unknown actions, unknown fields and missing
required fields are rejected before anything runs.

```text
.workflow simulate [{"action":"notify_owner","text":"Daily review at {date}"}]
.workflow add morning [{"action":"log","message":"start"},{"action":"notify_owner","text":"Good morning"}]
.workflow enable morning
.workflow run morning
.workflow history morning
```

- **Created disabled.** `.workflow add` stores the definition with
  `enabled=0`; `.workflow enable <name>` is a separate, explicit step.
- **Simulation first.** `.workflow simulate <json>` validates and renders every
  step without sending messages, writing rows or calling the AI.
- **Triggers.** `manual`, `interval` (60–2,592,000 seconds) or `daily`
  (`{"at": "HH:MM"}` in UTC). The scheduler polls every 60 seconds.
- **Retries.** A failed step is retried up to 3 attempts with short backoff,
  only for retryable errors. A successful retry clears the failure flag, so a
  recovered run is not marked failed.
- **Idempotency.** Every run has an idempotency key. Submitting the same key
  again returns the existing run instead of executing twice.
- **History.** `workflow_runs` and `workflow_steps` store status, attempts,
  timestamps, output and error per step.
- **Restart recovery.** A run that was `pending`/`running` when the process
  stopped is marked `interrupted`. It is **not** resumed automatically;
  `.workflow resume <run-id>` continues it explicitly, and refuses runs that
  already finished or exhausted retries.
- **Cancellation.** `.workflow cancel <run-id>` stops at the next step boundary
  and records the cancellation.

Without the feature enabled, every `.workflow` subcommand explains the exact
enable command and does nothing else.

## 7. Random reactions

`.reactions` is its own sensitive feature (`random_reactions`, OFF by default).
It reacts only in chats you list, with a configured emoji set and a per-chat
probability, and only to a small share of messages. It never reacts in bulk,
never sends messages and never acts on chats you did not add.

```text
.reactions status
.reactions add -1001234567890 5
.reactions emoji 👍,🔥,🎯
```

## 8. Limitations

- Rules have no cron expressions, no branching and no per-action retries.
- Rule conditions are evaluated against the triggering message only.
- Time-based rules use `REZE_TIMEZONE`; if the process sleeps through a schedule
  window, that run is skipped.
- Workflow `daily` triggers are evaluated in UTC; interval triggers use seconds.
- Workflows do not branch or loop; a step can wait, but the definition is a
  linear list.
- `task_failed` rule triggers evaluate in-process task history, which is not
  persisted across restarts.
