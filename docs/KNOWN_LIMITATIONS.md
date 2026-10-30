# Known limitations

This page lists what REZE 3.0 does **not** do, so the documentation never
overstates the product.

## Plugins

- **No sandbox.** Plugins run in-process with the full privileges of the
  userbot. Capability manifests are a consent and audit mechanism only.
- **No safe hot-unload guarantee.** Disabling removes a plugin's commands, but
  Python cannot force it to release threads, tasks, sockets or references.
- **No remote registry, signatures or trust scores.** Installation is a manual
  file drop; Reze never downloads or executes code from the internet.
- No dependency resolution or automatic installation of plugin requirements;
  missing modules are reported and the plugin fails in isolation.

## Stickers and media

- Only the **static WebP** sticker path is implemented (512×512, ≤512 KB).
  Animated (`.TGS`) and video (`.WEBM`) sticker sets are not supported.
- `.addsticker` requires the set to be owned by the account and Telegram to
  accept the asset; failures are reported, never hidden.
- Video/audio commands require a local FFmpeg binary; it is not bundled. Codec
  availability depends on the FFmpeg build.
- Background removal needs `REZE_REMOVEBG_API_KEY`; there is no local model, so
  the command is unavailable without a provider. Nothing is faked.
- Media commands act on the replied-to message only (no batch/bulk conversion).

## AI

- Text completions only: no streaming, embeddings, structured output or
  fine-tuning.
- Tool calling is limited to six allowlisted tools and always requires a manual
  approval code; the model cannot execute anything on its own.
- Vision support depends on the configured model; unknown models are treated as
  text-only.
- There is no prompt/response caching; persistent memory is a REZE feature you
  must enable, not an automatic conversation transcript.
- Provider pricing, availability and model ids are not managed by Reze.
- Fallback uses the same credentials and is opt-in only.
- The Model Council uses one API key for every member and reports a single
  answer as "not a consensus".

## Personal tools

- `.search`, `.links` and `.files` scan a bounded number of recent messages
  (`REZE_SEARCH_SCAN_LIMIT`, hard cap 200). They are not a full archive search.
- `.digest` reads at most 60 recent messages.
- The archive is a local SQLite database; it does not sync across devices and
  there is no conflict resolution.
- Reminders require the process to be running; a stopped process delivers
  nothing until it starts again, then delivers only overdue pending items.
- `.setonlinepermanently` only refreshes the status while Reze runs and the
  account is connected. It cannot override Telegram privacy settings, and
  Telegram may still mark a session offline after long inactivity elsewhere.
- QR generation covers byte mode, error-correction levels L/M and versions 1-10
  (up to 213 bytes at level M). Kanji/alphanumeric modes are not implemented.

## REZE 3 services

- **Everything optional is OFF by default.** That is a design rule, not a
  missing feature. Each key must be enabled explicitly; sensitive keys need the
  word `confirm`.
- **Memory is local text search.** Memories are stored in SQLite and matched by
  normalized text; there are no embeddings or vector search.
- **Life Graph, CRM, decisions, focus, projects, tasks and expenses are local.**
  They do not sync across devices and there is no conflict resolution.
- **Writing DNA is deterministic analysis** of samples (lengths, vocabulary,
  repeated phrases, punctuation). It does not clone a writing style with AI.
- **Smart Inbox never replies.** It classifies and stores; rules are local
  keyword/regex rules.
- **Universal search depends on the SQLite build.** Without FTS5 it falls back
  to a bounded `LIKE` scan and is slower.
- **Voice transcription and document extraction need a provider/key** and are
  bounded by size. Persian accuracy depends on the chosen model.
- **Insights are local statistics.** The AI narrative is optional and only runs
  when a provider is configured.
- **Inbox, sentinel, maintenance and retention are owner-only** and operate on
  this machine's data only.

## Vault, workflows and automation

- **Losing `REZE_VAULT_KEY` loses vault data.** There is no recovery key, no
  escrow and no backdoor. Changing the key does not re-encrypt old entries.
- **Backups are not encrypted as a whole.** Vault rows stay encrypted inside a
  backup, but the rest of the SQLite file is plaintext. Protect `data/backups/`.
- **Workflows are linear.** No branching, no loops and no parallel steps; each
  run has at most 20 steps and 3 attempts per step.
- **Workflow restart recovery is explicit.** Interrupted runs are marked and
  wait for `.workflow resume <run-id>`; nothing resumes silently.
- **Random reactions are intentionally rare and chat-scoped.** They never send
  messages and never act outside the chats you list.
- **Rules and workflows cannot execute shell commands or arbitrary Python.**
  This is a deliberate restriction, not a pending feature.
- **The Bot Companion is a single-owner front end.** It is not a multi-user bot
  platform and answers only `REZE_OWNER_ID`.

## Localization

- **Command descriptions in `.help` remain English** in 3.0; interface labels,
  help framing, errors and the panel are translated.
- **Command names are identical in both languages.** They are not localized.
- **Jalali conversion is arithmetic** over the supported range, not a full
  historical calendar library.
- **Persian text inside AI answers depends on the model**, not on REZE.

## Installer

- **Non-interactive mode does not ask questions.** It keeps existing values and
  uses defaults; secrets such as the AI key and companion token must already be
  in the environment or `.env`.
- **The installer never stores secrets in the database.** They stay in `.env`.
- **`.env` backup files contain secrets too.** Delete old `.env.bak-*` files
  when you no longer need them.

## Web panel

- Sessions live in memory: restarting signs everyone out.
- Single administrator account; no roles or multi-user access control.
- No JavaScript, no live updates — pages are rendered per request.
- Logs are the in-memory buffer (500 records) plus whatever the process prints;
  there is no log rotation or file viewer.
- The panel manages Telegram account settings (profile clock) but not arbitrary
  Telegram operations.

## Platform

- SQLite only; no Postgres or external queue.
- One Telegram account per process.
- The task manager is in-process; queued work is lost on restart.
- Automation rules are evaluated by the running process only (no distributed
  scheduler).
- Windows: `asyncio` signal handlers are unavailable, so `SIGTERM` handling is
  best-effort (Ctrl+C path).
- No Docker image is published by this repository; the included `Dockerfile` is
  a starting point, not a verified release artifact.

## Message Guard

- Only messages received **while Reze is running** can be recovered. Anything deleted while the process was offline is lost.
- Secret chats are end-to-end encrypted and invisible to userbots.
- Media above `max_media_mb` (25 MB) is reported as text only; self-destructing media is not saved.
- Copies are kept for `retention_hours` (default 48) and then purged. Telegram's delete events carry no chat id for private chats and basic groups, so lookups use the account-wide message id there.

## Owner suite and downloaders

- Downloaders depend on third-party sites and on `yt-dlp` staying current (`pip install -U yt-dlp`). Instagram and Facebook often require login cookies. They were not tested against the live sites in the test suite.
- `.tts` uses gTTS, which sends the text to Google. `.url` uploads files to catbox.moe, where links are public.
- `.exec` gives shell access to anyone who controls your Telegram account. Leave it disabled unless you need it.
- `.broadcast` is rate limited, but mass messaging can still get an account restricted by Telegram.
- Tic-tac-toe uses plain digit messages because userbots cannot send inline buttons.

## Timed media

- Telegram decides whether a self-destructing file can be downloaded by a third-party client. If it refuses (this can apply to view-once media), Reze sends a short notice instead of the file. This behaviour was not verified against live Telegram.
- The copy is saved when the message arrives; Reze cannot recover timed media that arrived while it was offline.

## Archive

- The archive grows without limit until you run `.watch archive clear`; media files stop being archived once it reaches 2 GB (text and metadata are still kept).
- Archived files are stored unencrypted in `data/`. Protect that folder (disk encryption, file permissions, backups) because it contains other people's messages and media.

## Stickers, AFK and alerts

- Real stickers need your own bot (`REZE_STICKER_BOT_TOKEN`) and one press of Start in it. The Bot API calls were tested against a simulated API only, not against live Telegram.
- As far as I know a user account cannot create sticker sets over MTProto, so the older no-token `.stickerpack` path may be refused by Telegram; use the bot token.
- Static and video stickers live in separate sets (Telegram does not allow mixing).
- AFK replies only in private chats and only once per person per 6 hours; groups are logged, never answered.
- Alerts cover groups and supergroups only. Basic groups have no message links.
