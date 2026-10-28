# Automation

Reze automation is a deliberately small `trigger → conditions → actions` engine.
It is not a workflow platform: there is no shell execution, no arbitrary Python,
and no remote rule creation.

## 1. Model

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

## 6. Limitations

- No cron expressions, no multi-step branching, no retries per action.
- Conditions are evaluated against the triggering message only.
- Time-based triggers use the process timezone configured by `REZE_TIMEZONE`; if
  the process sleeps through a schedule window, that run is skipped.
