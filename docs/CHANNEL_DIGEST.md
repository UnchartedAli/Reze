# Channel Digest

Developer: **UnchartedAli** · Channel: **[@yamods](https://t.me/yamods)**

Channel Digest collects new posts from channels you select and sends one digest to
your Saved Messages at a time you choose. It is **OFF by default**. Nothing is read
or sent until you turn it on.

## Turning it on

1. `.features enable channel_digest confirm` — the global feature (sensitive; needs confirmation).
2. `.digest add @channel` for each channel. Only posts published after the moment you add a channel are collected.
3. `.digest time 21:00` and `.digest timezone Asia/Tehran`.
4. `.digest on` — the digest's own switch (separate from the feature).
5. `.digest now` sends a digest immediately, to check the result.

Optional: `.digest ai on` (needs an AI provider configured for REZE), `.digest language fa`,
`.digest days weekly fri`, `.digest days custom mon,thu`, `.digest limit 200 12000`.

## Commands

| Command | Purpose |
| --- | --- |
| `.digest` | Status: on/off, schedule, next digest, last run, undelivered digests |
| `.digest channels` | Selected channels, priority, last successful sync |
| `.digest add <@username\|id>` / `remove` | Select or deselect a channel. Groups and private chats are refused |
| `.digest priority <channel> <1-10>` | Lower numbers come first in the digest |
| `.digest filter <channel> include\|exclude <words\|clear>` | Keyword filters (comma-separated, case-insensitive) |
| `.digest on` / `off`, `pause` / `resume` | Scheduled delivery |
| `.digest time HH:MM`, `timezone <IANA>`, `days ...` | Schedule |
| `.digest ai on\|off`, `language en\|fa`, `limit <messages> [chars]` | Summary settings |
| `.digest now` | Manual digest (works while paused) |
| `.digest history`, `settings` | Inspection. Never shows post text |
| `.digest clear confirm` | Deletes digest history and any digest text not yet delivered. Channel selections stay |

All management commands are owner-only.

## How a digest is built

* **One digest per schedule slot.** A slot is a local date and time (for example `2026-11-13T21:00@Asia/Tehran`).
  The database refuses a second run for the same slot, so repeated checks never duplicate a digest.
* **Missed slots after downtime** produce one catch-up digest, not one per missed slot. Collection starts from
  where the last successful collection stopped, so no posts are skipped.
* **Checkpoints move only with the stored digest.** The digest text and the new checkpoints are saved in one
  transaction before anything is sent. A crash or a flood wait therefore cannot lose posts or resend them.
* **Limits.** At most `limit` posts per digest, collected in channel priority order. Posts beyond the limit
  stay uncollected and go into the next digest.
* **Failed channels are skipped.** If one channel cannot be read (for example after a long flood wait), the digest
  says so, and that channel's posts are collected next time. The run fails only when every channel fails.
* **Delivery.** Each digest is split into Telegram-sized messages (at most 2000 characters each, which keeps every
  part under Telegram's 4096-unit limit). If sending fails, the digest is kept and retried with exponential backoff
  (1 minute, doubling, capped at 1 hour). It is never discarded.
* **No empty digests.** A window with no new posts sends nothing. The checkpoint still moves forward.

## AI summaries and the grounding check

With AI on, the model receives the collected posts and must answer in a fixed JSON shape. Before anything is
sent, each statement is checked:

1. Channel titles must match a channel that was actually collected. Other titles are dropped.
2. Every number and link in a statement must appear in the posts it summarizes. Statements that do not are removed,
   and the digest reports how many were removed.
3. If nothing survives, the digest uses the **basic** summary and labels it as such.

Original message links are attached by REZE from the source posts, not written by the model.

Post text is untrusted. It is sent to the AI provider you configured. Use `.digest ai off` to keep text entirely
local. The basic digest never calls an AI provider.

The basic digest chooses posts by a simple score (numbers, dates, links, and length), then recency. It reports how
many posts it does not show. Nothing is hidden silently.

## Privacy

* Only channels you explicitly add are read. Listing your dialogs for `.digest add` reads titles and ids, not content.
* Post text is never written to logs. Errors are stored as exception names or short fixed messages.
* A digest's text is deleted after successful delivery. Undelivered digests are kept until delivered or cleared.
* `.digest clear confirm` deletes history and undelivered digest text.
* Media is **not** downloaded. Captions and a media label (for example `[photo]`) are used. OCR and transcription
  are not implemented.

## Web panel

Open **Channel Digest** in the panel (Personal section). It shows the feature state, the next digest time,
the last run, undelivered digests, and the run history. It has controls to:

* turn the digest on or off, pause and resume scheduled digests, and turn AI summaries on or off
* change the delivery time, timezone, schedule (daily, weekly, custom), limits, and language
* search the selected channels, and set each channel's priority, keyword filters, and read on/off
* remove a channel, and delete history (with a confirmation tick)
* **Generate now**: the panel records a request, and the digest loop sends one digest on its next pass
  (about a minute), even while scheduled digests are paused

Adding channels, and reading their posts, need the live Telegram connection, so they stay in commands.
The AI provider is chosen in the AI settings, not on this page.

## Limitations (read before relying on it)

* **Not tested against a live Telegram account.** The test suite uses fake clients and fake AI responses. It checks
  the logic: selection, checkpoints, scheduling, recovery, retries, splitting, and privacy. The Telethon calls
  (`iter_dialogs`, `get_entity`, `get_messages`, `iter_messages`, `send_message("me", ...)`) follow the Telethon
  documentation but have not been run against a real account.
* **At-least-once delivery.** If REZE crashes between a successful send and saving its progress, that one part can
  be sent twice. Duplicate digests are otherwise prevented.
* **Schedule times in DST gaps** resolve to a deterministic time, which may differ from the nominal time for one day.
* **No OCR or transcription.** Media is described, not read.
* **AI quality is not guaranteed.** The grounding check removes statements with unsupported numbers and links. It
  does not check meaning, opinions, or omissions. Check important digests against the source.

## Where the code lives

| Part | File |
| --- | --- |
| Schema | `reze/migrations/v5.py` |
| Scheduling rules (pure) | `reze/digest/schedule.py` |
| Text, links, splitting, grounding, basic digest | `reze/digest/text.py` |
| AI prompt, JSON parsing, verification | `reze/digest/summarize.py` |
| Storage (all SQL) | `reze/digest/store.py` |
| Telegram access | `reze/digest/collect.py` |
| Pipeline and recovery | `reze/digest/service.py` |
| Commands | `reze/commands/digest.py` |
| Tests | `tests/test_reze4_digest.py` |
