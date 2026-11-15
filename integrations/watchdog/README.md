# Watchdog bridge (سگ نگهبان ↔ Reze)

Developer: **UnchartedAli** · Channel: **[@yamods](https://t.me/yamods)**

The Watchdog bot is `@watchdogappbot`. Its Cloudflare worker is `worker.js` in this folder. The
worker is the file you already had, with one addition: a **Reze bridge** (signed events, replay
protection, and a health check). The rest of the file is unchanged.

## What the two sides do

* **Reze → Watchdog.** Reze sends signed events (startup, stopping, new sticker pack, test) to
  `POST /reze/event`. The worker checks the signature and forwards the event to the owner.
* **Watchdog → Reze.** The worker's cron calls `REZE_HEALTH_URL` every minute. After three failed
  checks in a row it tells the owner Reze is not answering. When Reze answers again, it says so.
* **Sticker bot.** Reze creates its sticker packs through `@watchdogappbot`. The token is checked
  on first use: a token that belongs to any other bot is refused.

## Summaries of channel posts (with your consent)

* In Reze's panel open **Consent** and allow *Send channel posts to the Watchdog bot for summaries*,
  or run `.consent grant watchdog.channel_posts`.
* Then `.watchdog summarize @channel 20` reads the last 20 text posts of that chat and sends them to the
  worker's `/reze/summarize` route. The worker asks its AI and returns the summary to Reze. It stores
  nothing and sends nothing to Telegram.
* Reze checks every number and link in the summary against the posts it sent. Lines with a number or link
  the posts do not contain are removed, and Reze says how many. The result goes to your Saved Messages.
* Limits: 40 posts per request, 1,500 characters per post, 64 KB per request. More than that is refused.
* Worker setting: `AI_GATEWAY_API_KEY` (secret, required for summaries). `MODEL` and `AI_GATEWAY_BASE_URL`
  are optional.
* Without consent, nothing is sent, and the command says so.

## Premium emoji packs (worker)

`/emojipack https://t.me/addemoji/PACK` adds a pack. Each pack is kept on its own, so a second pack does not
replace the first. `/emojipack list` shows the packs and `/emojipack remove PACK` removes one. An emoji in
two packs uses either one.

## Channel autopilot (X4): edits, media, forwards, notes

* **Edit a draft with media.** Under a draft press ✏️ and then send a photo, GIF, video, document or sticker
  (with an optional caption), or forward a post. The draft keeps a reference to that message, and publishing
  **copies** it to the channel with `copyMessage`, so no "forwarded from" header appears. A plain text edit
  clears the reference and publishes text as before.
* **Channel note (📝 توضیح دستی کانال).** On a channel card, send your own description of the channel. It
  is stored (up to 1,500 characters), and the next drafts are written to follow it. It outranks the automatic
  analysis. Send `reset` to clear it.
* Only admins of the channel can set a note, and only the owner can see or change drafts that are not theirs.

## Anonymous links

* The owner gets a link from `/anon`: `t.me/<bot>?start=anon_<code>`. Opening it lets a visitor send an
  anonymous message; the owner answers with the Reply button or with Telegram's Reply. The visitor's
  identity is never shown to the owner, and the owner's identity is never shown to the visitor.
* Custom name: press **🏷 نام اختصاصی** in the `/anon` panel and send the name, or use `/anon name ali`. It makes `t.me/<bot>?start=ali` open the same link. 3 to 32 letters, digits or `_`,
  starting with a letter. Names used by other links (`lang`, `anon`, `menu`, `games`, …) are refused.
* Blocking, pausing, and a new link (`nx:new`) stop the old link at once.

## Reactions

* `/react` shows toggle buttons (channels, groups, the group chance 5/10/25/50%, private). Only the owner can press them. Text commands still work: `/react status`, `/react channel on|off`, `/react group on|off [percent]`, `/react private on|off`. All are off until you turn them on:
  * `/react channel on|off`: a channel post gets one emoji the channel allows. If the channel lists its
    allowed emoji, only those are used; if it lists none, no reaction is sent.
  * `/react group on|off [percent]`: a group message gets a reaction with that chance (default 10%). Rate-limited.
  * `/react private on|off`: every person who writes to the bot gets a random standard emoji reaction.
    Your own messages are never reacted to.
* The bot must be an admin in a channel to react there.

## Secrets: where each one lives

| Secret | Where it is kept | Never |
| --- | --- | --- |
| Watchdog bot token (`BOT_TOKEN`) | Cloudflare secret of the worker | in the file, in Git, in a chat |
| Bridge secret | Cloudflare secret `REZE_BRIDGE_SECRET`, and Reze stores it encrypted | in logs or in events |
| Sticker bot token | Reze, encrypted with `REZE_VAULT_KEY` | in plain text on disk |

The worker file contains no token. It reads `env.BOT_TOKEN`, which Cloudflare provides as a secret.

## Setup

**1. Watchdog worker (Cloudflare)**

* Deploy `worker.js` from this folder. It is your original worker plus the Reze bridge; nothing else changed.
* Add secrets: `BOT_TOKEN` (the @watchdogappbot token), `REZE_BRIDGE_SECRET` (32+ random characters),
  `WEBHOOK_SECRET`, `OWNER_ID`.
* Add the variable `REZE_HEALTH_URL`, for example `https://your-reze-host/healthz`.
* Keep the KV binding named `KV`. The bridge uses it for replay protection and health state.
* Open `/setup?key=WEBHOOK_SECRET` once, as the worker's header describes.

**2. Reze**

* Set `REZE_VAULT_KEY` (any long random string). Keep it; without it nothing can be opened later.
* Set `REZE_STICKER_BOT_TOKEN` once, then remove it. Reze stores it encrypted.
* Set `REZE_WATCHDOG_BRIDGE_SECRET` to the same value as the worker's `REZE_BRIDGE_SECRET`, once, then remove it.
* `REZE_WATCHDOG_URL` defaults to `https://amo.alimmazza043.workers.dev`. Change it only if your worker has another address.

**3. Check it**

* In Reze, `.watchdog status` shows yes/no facts only.
* `.watchdog test` sends a test event. The owner receives `🐕‍🦺 Reze · test`.

## Security notes

* Events are accepted for five minutes, and each signature once.
* Bodies larger than 4 KB are refused. Text is flattened and capped at 500 characters.
* Without a bridge secret of 32+ characters, the route is closed (HTTP 503).
* Sticker packs are owned by the Watchdog bot. Telegram lets the bot that created a set manage it.

## Tests

* `node --test integrations/watchdog/test_bridge.mjs integrations/watchdog/test_summarize.mjs integrations/watchdog/test_premium.mjs integrations/watchdog/test_autopilot.mjs integrations/watchdog/test_anon.mjs integrations/watchdog/test_reactions.mjs`: 63 tests on the real worker code. Autopilot and anonymous-link tests use real SQL (node:sqlite) behind the D1 API.
* `python -m pytest tests/test_reze4_watchdog.py tests/test_reze4_watchdog_e2e.py tests/test_reze4_consent.py`: the Reze side,
  and end-to-end runs between the Reze client and the worker (needs Node.js; skipped otherwise).

## Limits

* Telegram delivery of the owner messages was not tested against a live account. The tests stub Telegram.
* The worker's other features (AI, moderation, Filmyar, channel autopilot) are not changed by the bridge.
* Replay protection uses KV. If KV is not bound, the timestamp window is the only protection.
