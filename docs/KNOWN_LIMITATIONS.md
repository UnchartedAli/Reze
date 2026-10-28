# Known limitations

This page lists what REZE 2.0 does **not** do, so the documentation never
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

- Text completions only: no streaming, tool calling, embeddings, structured
  output or fine-tuning.
- Vision support depends on the configured model; unknown models are treated as
  text-only.
- No prompt/response caching or conversation memory.
- Provider pricing, availability and model ids are not managed by Reze.
- Fallback uses the same credentials and is opt-in only.

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
