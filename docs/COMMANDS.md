# REZE 3.0 — Command Reference

This document lists **every command registered by REZE 3.0** (172 at the time of
writing). It is generated from the live command router, so a command that is not
in this file does not exist.

- Prefix: `.` by default. Change it with `.prefix <char>`.
- Syntax: `<required>` and `[optional]`; `a|b` means "choose one".
- Access: `owner` means the configured `REZE_OWNER_ID` account only. Commands
  marked "group admin" also require Telegram admin rights in that group.
- Optional features are **OFF by default**. A command that needs a feature
  explains which key to enable and never enables it for you.
- Run `.help <command>` for the live usage and examples registered by the
  command itself.

## Language availability (fa / en)

REZE is bilingual at the interface level:

| Surface | English | Persian |
| --- | --- | --- |
| Command names, aliases and syntax | Yes | Yes — the same names work in both languages |
| Free-text input, search and stored notes | Yes | Yes, with Persian normalization and digit conversion |
| Reply framing, status words, help labels, feature names, web panel | Yes | Yes, switch with `.language fa` |
| Per-command one-line descriptions in `.help` | Yes | English only in 3.0 (see `docs/KNOWN_LIMITATIONS.md`) |
| Documentation | Yes (this file) | Persian quick start in [`docs/README.fa.md`](README.fa.md) |

Persian mode adds the right-to-left mark to replies and can render dates with the
Jalali calendar; stored timestamps remain ISO-8601 UTC. Persian/Arabic letter
variants (`ي`/`ی`, `ك`/`ک`), Arabic-Indic digits and diacritics are normalized
before storage and search.

## First-run tutorials

### 1. Install and start

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python -m reze.installer          # or: reze-install
python -m reze.app               # or: reze
```

The installer checks dependencies, writes `.env`, creates the data directory and
applies database migrations. Every optional feature stays OFF after installation.

### 2. Confirm the install

```text
.ping
.status
.version
.features
```

`.features` must show `Enabled: 0/23` on a fresh install.

### 3. Turn on only what you need

```text
.features enable memory
.features enable focus
.features enable vault confirm
```

`confirm` is required for sensitive features (vault, workflows, AI agent, voice,
documents, sentinel, companion, reactions, monitoring). Enabling one feature
never enables another.

### 4. Keep your first memory

```text
.memory add The landlord's number is on the fridge
.memory search landlord
.memory show 1
```

### 5. Start a focus session

```text
.focus start 25 writing the report
.focus status
.focus stop
```

### 6. Store a secret safely

```text
.vault set wifi
# reply to a message containing the secret, or send it as the next argument
.vault get wifi
.vault list
```

The Vault needs `REZE_VAULT_KEY` (the installer can generate one). Losing that key
makes existing Vault data unrecoverable.

### 7. Back up before you experiment

```text
.backup create
.backup list
.backup verify 1
```

Restoring requires a second step and a six-digit code:

```text
.backup restore 1
.backup confirm 123456
```

### 8. Build a workflow

Simulation is always available; running and saving need the feature:

```text
.workflow simulate [{"action":"log","message":"hello {date}"}]
.features enable workflows confirm
.workflow add morning [{"action":"notify_owner","text":"Good morning"}]
.workflow run morning
```

## REZE 3 command handbooks

### Optional features and language

```text
.features                         # every key with ON/OFF and sensitivity
.features status vault            # details and background service state
.features enable memory           # standard feature
.features enable workflows confirm
.features disable memory
.features reset confirm           # turn everything OFF; data is preserved
.language                         # current language and direction
.language fa                      # Persian UI
.language en
```

Errors: an unknown key returns "Unknown feature". Enabling a sensitive key
without `confirm` returns a confirmation hint and changes nothing.

### Memory, Timeline and Life Graph

```text
.memory recent [count]
.memory add <text>
.memory search <query>
.memory show <id>
.memory forget <id>
.memory pin <id> | .memory unpin <id>
.memory archive <id>

.timeline [count] [kind]
.graph list [kind]
.graph add <kind> <name> [notes]
.graph link <a> | <relation> | <b>
.graph show <name>
```

Features: `memory`, `timeline`, `life_graph`. Memory entries are local, indexed
with FTS5 and capped at 8,000 characters. Timeline kinds are free-form labels
(`note`, `person`, `work`, ...). Graph relations are stored in both directions
where applicable.

### Personal CRM and Decision Journal

```text
.crm list
.crm add Sara @sara_username birthday:1994-05-12 tags:work,design
.crm show Sara
.crm log Sara Met for coffee; moving to Berlin in spring
.crm birthday 30
.crm stale 60
.crm delete Sara

.decide add Accept the offer | stay | move | 3 months
.decide list
.decide choose 1 accept
.decide review 1 It worked out, but the commute was long
.decide due
```

Features: `crm`, `decisions`. Contact names are matched case-insensitively.
`.decide add` takes `title | options | expected outcome | review-days`; `.decide
due` lists decisions whose review date has arrived.

### Projects, tasks and expenses

```text
.project list
.project add Website refresh | Q4 marketing site
.project close Website refresh

.task list
.task list todo
.task add Send invoice @Website refresh p:2 due:2026-11-05
.task done 12
.task stats

.expense add 42.50 food groceries
.expense list 2026-10
.expense summary 2026-10
.expense delete 3
```

Features: `projects`, `expenses`. Priorities run `1` (highest) to `5`. Amounts are
stored as decimals with the currency label you type in the note; REZE does not
convert currencies.

### Writing DNA and Insight Engine

```text
.writing add <sample text>
.writing samples
.writing profile
.writing check <new text>

.insights [days]
.insights ai [days]
```

Features: `writing_dna`, `insights`. The profile is computed locally from your
samples (length, sentence rhythm, punctuation and common words); nothing is sent
anywhere. `.insights ai` calls the configured provider and reports a budget error
instead of guessing when the daily budget is exhausted.

### Capture: inbox, universal search, documents and voice

```text
.inbox list
.inbox stats
.inbox read <id>
.inbox rules
.inbox rule add keyword invoice
.inbox rule add regex ^urgent
.inbox rule delete <id>

.usearch <query> [kind]

.doc                                  # reply to a PDF/DOCX/TXT file
.doc list | .doc search <q> | .doc status | .doc delete <id>

.voice                                # reply to a voice message
```

Features: `smart_inbox`, `universal_search`, `document_intelligence`,
`voice_intelligence`. The inbox classifies messages locally and **never replies
on its own**. `.usearch` kinds include `memory`, `crm`, `decision`, `task`,
`document`, `timeline`, `vault`. Voice transcription requires an OpenAI-
compatible key and `REZE_VOICE_MODEL`; the audio is uploaded to that provider.

### Vault, backups, maintenance and sentinel

```text
.vault status
.vault list
.vault set <name> <secret>            # or reply to a message with .vault set <name>
.vault put <name>                     # reply to a file (max 10 MB)
.vault get <name>
.vault export <name>
.vault delete <name>

.backup | .backup create
.backup list
.backup verify <id>
.backup restore <id>
.backup confirm <code>
.backup prune [keep]

.maintain
.maintain apply confirm

.sentinel
.sentinel run
.sentinel open
.sentinel summary
.sentinel resolve <id>
```

Features: `vault`, `self_maintenance`, `security_sentinel`. Vault payloads use
AES-256-GCM with a scrypt-derived key and are never indexed in plaintext. Backups
use SQLite's online backup API, are verified with `PRAGMA integrity_check` and
restore only after a six-digit code. `.maintain apply confirm` creates a safety
backup before pruning retention data.

### Workflows (persistent automation)

```text
.workflow simulate [{"action":"log","message":"hello"}]
.workflow list
.workflow add <name> <json>
.workflow enable <name>
.workflow disable <name>
.workflow run <name>
.workflow history [name]
.workflow resume <run-id>
.workflow cancel <run-id>
.workflow delete <name>
```

Feature: `workflows` (sensitive). Definitions are saved **disabled**. Supported
actions: `send_message`, `notify_owner`, `save_memory`, `add_timeline`,
`add_task`, `add_reminder`, `log`, `wait` (0–60 s). Each step is recorded once;
retries are capped at three attempts; a restart marks unfinished runs
`interrupted` and never resumes them silently. Delete a definition with care: its
run history is deleted with it.

JSON object form accepted by `.workflow add`:

```json
{
  "description": "Morning check-in",
  "trigger": "daily",
  "at": "07:30",
  "cooldown_seconds": 300,
  "steps": [{"action": "notify_owner", "text": "Good morning"}]
}
```

An `interval` trigger uses `"seconds": 600` (60–2,592,000). Optional
`idempotency_key` arguments are available through the API, and a duplicate key
returns `duplicate` instead of running twice.

### AI Agent, approvals and Model Council

```text
.agent tools
.agent run <request>
.agent call <tool> <json>
.agent pending
.agent approve <code>
.agent deny <code>
.agent history
.agent budget
.agent status

.council <question>
```

Features: `ai_agent`, `model_council` (both sensitive). The model can only
propose names from a fixed allowlist (`memory.save`, `memory.search`, `task.add`,
`timeline.add`, `features.list`, `budget.status`). Every call is schema-checked,
rejected if its feature is off, counted against a daily budget, and requires a
six-digit approval that expires after 15 minutes. Nothing executes on proposal.
The audit trail lives in `ai_tool_audit`.

### Bot Companion and random reactions

```text
.companion                         # status and configuration hints
.reactions status
.reactions add <chat_id> [percent]
.reactions remove <chat_id>
.reactions emoji 🙂,🔥,👍
.reactions clear
```

Features: `bot_companion`, `random_reactions` (sensitive, OFF by default). The
companion uses a bot token you create yourself, answers only the owner and opens
an inline ON/OFF menu. Random reactions are bounded to the chats you list, a
maximum of 25% probability, a 120-second cooldown per chat and 20 per hour; REZE
never sends a message, scrapes members or contacts people who did not message
you.

## Complete command index

Every entry below is a real registered command. "Aliases" are alternative names
with the same behaviour.

### AI

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.agent` | — | `.agent [tools\|run <request>\|call <tool> <json>\|pending\|approve <code>\|deny <code>\|history\|budget]` | Let the AI propose an allowlisted tool; you approve before it runs. | owner |
| `.council` | — | `.council <question>` | Ask several configured models and synthesize one answer. | owner |
| `.insights` | — | `.insights [days] \| .insights ai [days]` | Show local weekly statistics; optionally ask the AI for a narrative. | owner |

### Admin

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.admins` | — | `.admins` | List group administrators. | group only |
| `.ban` | — | `.ban (reply or id)` | Ban a member from the group. | group admin, group only |
| `.del` | — | `.del (reply)` | Delete the replied-to message. | group admin |
| `.kick` | — | `.kick (reply or id)` | Kick a member (they can rejoin). | group admin, group only |
| `.mute` | — | `.mute (reply or id)` | Mute a member. | group admin, group only |
| `.pin` | — | `.pin (reply)` | Pin the replied-to message. | group admin, group only |
| `.purge` | — | `.purge [count]` | Delete recent messages (bounded). | group admin, group only |
| `.slowmode` | — | `.slowmode <seconds>` | Set the group slow-mode interval. | group admin, group only |
| `.tagall` | — | `.tagall [message]` | Mention recent members in chunks. | group admin, group only |
| `.unban` | — | `.unban (reply or id)` | Remove a ban from a member. | group admin, group only |
| `.unmute` | — | `.unmute (reply or id)` | Unmute a member. | group admin, group only |
| `.unpin` | — | `.unpin` | Unpin the current pinned message. | group admin, group only |

### Appearance

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.config` | — | `.config [set <key> <value> \| reset <key>]` | Show or change validated user preferences. | owner |
| `.prefix` | — | `.prefix <char>` | Change the command prefix (1-2 characters). | owner |
| `.preview` | — | `.preview [theme]` | Preview the ASCII message engine in a given theme. | everyone allowed by policy |
| `.theme` | — | `.theme [name]` | Switch the message theme (CYBER, GHOST, TERMINAL, COMPACT). | everyone allowed by policy |

### Automation

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.automation` | .auto | `.automation <list\|show\|create\|enable\|disable\|delete> ...` | Create and manage trigger → condition → action rules. | owner |
| `.reactions` | — | `.reactions [status\|add <chat_id> [percent]\|remove <chat_id>\|emoji <a,b,c>\|clear]` | Configure rare emoji reactions in chats you list (feature OFF by default). | owner |
| `.workflow` | — | `.workflow [list\|simulate <json>\|add <name> <json>\|enable <name>\|disable <name>\|run <name>\|history [name]\|resume <run-id>\|cancel <run-id>\|delete <name>]` | Simulate and run persistent multi-step workflows (OFF by default). | owner |

### Capture

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.doc` | .document | `.doc [list\|search <q>\|delete <id>\|status] (or reply to a file with .doc)` | Extract text from a replied document and index it locally. | owner |
| `.inbox` | — | `.inbox [list\|stats\|read <id>\|rules\|rule add <keyword\|regex> <pattern>\|rule delete <id>]` | Review locally classified incoming messages (never replies). | owner |
| `.usearch` | — | `.usearch <query> [kind]` | Search memories, contacts, decisions, tasks, documents and the timeline. | owner |
| `.voice` | .transcribe | `.voice (as a reply to a voice message)` | Transcribe a replied voice note through the configured AI provider. | owner |

### Download

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.facebook` | .fb | `.facebook <link>` | Download a Facebook video. | everyone allowed by policy |
| `.instagram` | .ig | `.instagram <link>` | Download an Instagram post or reel (video). | everyone allowed by policy |
| `.mediafire` | — | `.mediafire <link>` | Download a file from a MediaFire link. | everyone allowed by policy |
| `.pinterest` | — | `.pinterest <pin link>` | Download the image or video of a Pinterest pin. | everyone allowed by policy |
| `.song` | — | `.song <song name>` | Search a song by name and send it as audio. | everyone allowed by policy |
| `.tiktok` | .tt | `.tiktok <link>` | Download a TikTok video. | everyone allowed by policy |
| `.yt` | .play | `.yt <link \| search words>` | Download a YouTube video (<=720p) by link or search words. | everyone allowed by policy |
| `.yta` | — | `.yta <link \| search words>` | Download only the audio of a YouTube video (mp3). | everyone allowed by policy |
| `.ytv` | — | `.ytv [144\|240\|360\|480\|720\|1080] <link \| search words>` | Download a YouTube video in a chosen quality. | everyone allowed by policy |

### Fun

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.dare` | — | `.dare` | A random dare. | everyone allowed by policy |
| `.joke` | — | `.joke` | Tell a random joke. | everyone allowed by policy |
| `.quote` | — | `.quote` | Show a random quote. | everyone allowed by policy |
| `.roast` | — | `.roast (reply \| id \| name)` | Playfully roast someone (reply, id, or a name). | owner |
| `.ship` | — | `.ship <name1> <name2>  or reply + <name>` | Chance of a relationship between two people. | everyone allowed by policy |
| `.tictactoe` | — | `.tictactoe [stop]  (reply to challenge someone)` | Play tic-tac-toe: reply to a member to challenge them, or play against Reze. | everyone allowed by policy |
| `.truth` | — | `.truth` | A random truth question. | everyone allowed by policy |

### General

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.alive` | — | `.alive` | Confirm the userbot is running. | everyone allowed by policy |
| `.credits` | .creator, .developer, .support | `.credits` | Show the author and the official channel. | everyone allowed by policy |
| `.help` | — | `.help [category \| command]` | Show command help by category or for one command. | everyone allowed by policy |
| `.id` | — | `.id` | Show user, chat and message identifiers. | everyone allowed by policy |
| `.info` | — | `.info` | Account and deployment information. | everyone allowed by policy |
| `.logs` | — | `.logs [count]` | Show the most recent log lines. | owner |
| `.ping` | — | `.ping` | Measure command round-trip latency. | everyone allowed by policy |
| `.restart` | — | `.restart` | Restart the Reze process. | owner |
| `.settings` | — | `.settings` | Show environment configuration (no secrets). | owner |
| `.shutdown` | — | `.shutdown` | Stop the Reze process safely. | owner |
| `.stats` | — | `.stats` | Local database and usage statistics. | everyone allowed by policy |
| `.uptime` | — | `.uptime` | Show process uptime. | everyone allowed by policy |
| `.version` | — | `.version` | Show the running Reze version. | everyone allowed by policy |
| `.webpanel` | — | `.webpanel` | Show the web panel URL and health endpoint. | owner |

### Group

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.demote` | — | `.demote (reply or id)` | Remove admin rights from a member. | owner, group only |
| `.hidetag` | — | `.hidetag <text>` | Mention everyone invisibly: members get a notification, the chat sees only your text. | owner, group only |
| `.invite` | — | `.invite` | Create an invite link for this group. | owner, group only |
| `.join` | — | `.join <t.me/+hash \| t.me/name \| @name>` | Join a group or channel by invite link or @username. | owner |
| `.leave` | — | `.leave   then   .leave confirm <code>` | Leave this group/channel (needs a confirmation code). | owner |
| `.promote` | — | `.promote (reply or id) [full] [custom title]` | Make a member admin (add `full` to also let them add admins). | owner, group only |
| `.setdesc` | — | `.setdesc <text>   (max 255 characters)` | Change the group description. | owner, group only |
| `.settitle` | — | `.settitle <new group name>` | Rename the group (`.setname` changes your own profile name). | owner, group only |

### Guard

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.alerts` | .alert | `.alerts <on\|off\|status\|list\|mentions\|add\|del\|ignore\|unignore\|dest>` | Send group mentions and keyword matches to Saved Messages. | owner |
| `.watch` | .guard, .msglog | `.watch <on\|off\|add\|del\|list\|status\|private\|groups\|edits\|media\|ttl\|archive\|find\|show\|export\|own\|dest\|keep\|clear>` | Save deleted/edited messages of chosen chats to Saved Messages. | owner |

### Intelligence

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.ai` | — | `.ai <prompt>` | Ask the configured AI provider a question (or transform replied text). | everyone allowed by policy |
| `.aiinfo` | .ai_info | `.aiinfo` | Show the configured AI provider and model without revealing secrets. | everyone allowed by policy |
| `.describe` | — | `.describe (reply to an image)` | Describe a replied image using a vision-capable model. | everyone allowed by policy |
| `.digest` | — | `.digest [count]` | Summarize the last few messages of this chat (bounded, explicit limit). | everyone allowed by policy |
| `.rewrite` | — | `.rewrite <shorter\|formal\|casual\|clearer\|bullets>` | Rewrite replied or provided text in a chosen style. | everyone allowed by policy |
| `.summarize` | — | `.summarize [text]` | Summarize replied text or the provided text with the AI provider. | everyone allowed by policy |
| `.translate` | .tr | `.translate <language> [text]` | Translate replied or provided text into another language. | everyone allowed by policy |

### Knowledge

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.graph` | — | `.graph [list [kind]\|add <kind> <name> [notes]\|link <a> \| <relation> \| <b>\|show <name>]` | Connect people, projects, places and topics in the Life Graph. | owner |
| `.memory` | — | `.memory [recent\|add <text>\|search <query>\|show <id>\|forget <id>\|pin <id>\|archive <id>]` | Save and search durable memories the AI can recall. | owner |
| `.timeline` | — | `.timeline [events] [kind]` | Show the chronological stream of events recorded in REZE. | owner |
| `.writing` | — | `.writing [add <text>\|profile\|check <text>\|samples]` | Add writing samples, view your profile or compare new text. | owner |

### Media

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.addsticker` | — | `.addsticker <set_short_name> [emoji]` | Add a replied image as a sticker to an existing set you own. | everyone allowed by policy |
| `.caption` | — | `.caption <text> [top\|center\|bottom]` | Draw text on a replied image (top, center or bottom). | everyone allowed by policy |
| `.compress` | — | `.compress [quality\|crf]` | Compress a replied image or video. | everyone allowed by policy |
| `.download` | — | `.download` | Download replied media to a file (subject to Telegram access rules). | everyone allowed by policy |
| `.gif` | — | `.gif [fps] [width]` | Convert replied video or animation into a GIF. | everyone allowed by policy |
| `.meme` | — | `.meme <top> \| <bottom>` | Add top/bottom meme text to a replied image. | everyone allowed by policy |
| `.removebg` | — | `.removebg   then   .removebg confirm <code>` | Remove the background of a replied image through a configured provider. | everyone allowed by policy |
| `.resize` | — | `.resize <width> [height]` | Resize a replied image (or video) with aspect-ratio handling. | everyone allowed by policy |
| `.speed` | — | `.speed <factor>   (0.25 - 4.0)` | Change playback speed of replied audio or video. | everyone allowed by policy |
| `.sticker` | .s | `.sticker [emoji]  (reply to an image, GIF or video)` | Convert a replied image, GIF or video into a Telegram sticker. | everyone allowed by policy |
| `.stickerpack` | — | `.stickerpack <title> \| <emoji>  then  .stickerpack confirm <code>` | Create a real Telegram sticker set from a replied image. | everyone allowed by policy |
| `.thumbnail` | — | `.thumbnail [size]` | Generate a thumbnail from a replied image or video. | everyone allowed by policy |
| `.toaudio` | .tomp3 | `.toaudio` | Extract the audio track from replied video or media. | everyone allowed by policy |
| `.toimage` | .toimg | `.toimage [frame_index]` | Extract a still image from replied media (first frame by default). | everyone allowed by policy |
| `.tovideo` | — | `.tovideo` | Convert replied media into an H.264 MP4 video. | everyone allowed by policy |
| `.trim` | — | `.trim <start> <end>   (e.g. .trim 0:05 0:35)` | Trim replied audio or video between two timestamps. | everyone allowed by policy |

### Moderation

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.blacklist` | — | `.blacklist add\|remove\|list ...` | Manage forbidden words. | group admin, group only |
| `.filter` | — | `.filter add\|remove\|list ...` | Manage automatic keyword replies. | group admin, group only |
| `.goodbye` | — | `.goodbye on\|off` | Enable or disable goodbye messages. | group admin, group only |
| `.resetwarns` | — | `.resetwarns (reply or id)` | Clear every warning for a member. | group admin, group only |
| `.rules` | — | `.rules` | Show the group rules. | group only |
| `.setrules` | — | `.setrules <text>` | Set the group rules text. | group admin, group only |
| `.setwelcome` | — | `.setwelcome <text with {mention} and {title}>` | Set the welcome message template. | group admin, group only |
| `.unwarn` | — | `.unwarn (reply or id)` | Remove one warning from a member. | group admin, group only |
| `.warn` | — | `.warn [reason] (reply or id)` | Warn a member and count it toward the limit. | group admin, group only |
| `.warns` | — | `.warns (reply or id)` | Show a member's warning count. | group only |
| `.welcome` | — | `.welcome on\|off` | Enable or disable welcome messages. | group admin, group only |

### Owner

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.block` | — | `.block (reply, @username, id or private chat)` | Block a user. | owner |
| `.botinfo` | — | `.botinfo` | Show version, uptime, runtime and enabled features. | owner |
| `.broadcast` | .bc | `.broadcast <groups\|users\|all> <text>   then   .broadcast confirm <code>` | Send a message to many chats (confirmation code + rate limit). | owner |
| `.delvar` | — | `.delvar <REZE_NAME>` | Remove a REZE_* variable from .env. | owner |
| `.exec` | — | `.exec <command>` | Run a shell command on the host (needs REZE_ENABLE_EXEC=true). | owner |
| `.getvar` | — | `.getvar [REZE_NAME]` | Show a REZE_* variable (secrets are masked) or list them all. | owner |
| `.owner` | — | `.owner` | Show the owner (this account) details. | owner |
| `.setvar` | — | `.setvar <REZE_NAME> <value>` | Set a REZE_* variable in .env (most need a restart). | owner |
| `.unblock` | — | `.unblock (reply, @username, id or private chat)` | Unblock a user. | owner |
| `.update` | — | `.update [now]` | Check for updates (git) and apply them with `.update now`. | owner |

### Personal

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.bookmark` | .bm | `.bookmark <url> [note]` | Bookmark a URL or message reference. | owner |
| `.chatinfo` | — | `.chatinfo` | Show metadata for the current chat. | everyone allowed by policy |
| `.crm` | — | `.crm [list\|add <name> [@user] [birthday:YYYY-MM-DD] [tags:a,b]\|show <name>\|log <name> <summary>\|birthday [days]\|stale [days]\|delete <name>]` | Manage contacts, interaction history and birthdays locally. | owner |
| `.decide` | .decision | `.decide [list\|add <title> \| <options> \| <expected> \| <review-days>\|choose <id> <choice>\|review <id> <outcome>\|due]` | Record decisions, expected outcomes and later reviews. | owner |
| `.files` | — | `.files [limit]` | List media found in recent chat messages (bounded scan). | owner |
| `.find` | — | `.find <query>` | Search your local archive by title, content, URL or tag. | owner |
| `.focus` | — | `.focus [start [minutes] [label]\|stop\|status\|stats [days]]` | Start or stop a timed focus session and read your statistics. | owner |
| `.links` | — | `.links [limit]` | Extract links from the replied message or recent chat messages. | owner |
| `.notes` | — | `.notes [add <name> <text> \| show <name> \| delete <name>]` | Create, list, show and delete personal notes. | owner |
| `.qr` | — | `.qr <text or URL>` | Generate a QR code image locally from text or a URL. | everyone allowed by policy |
| `.remind` | — | `.remind <10m\|2h\|2d\|YYYY-MM-DD HH:MM> <text>   \|   .remind list` | Schedule a personal reminder (duration or absolute time). | owner |
| `.save` | — | `.save [note text]` | Save a replied message, link or note to your local archive. | owner |
| `.schedule` | — | `.schedule` | Show scheduled reminders and automations. | owner |
| `.search` | — | `.search <query> [limit]` | Search recent messages in this chat (bounded scan). | owner |
| `.whois` | — | `.whois [user id \| @username] (or reply)` | Show Telegram identity details for a user. | everyone allowed by policy |

### Plugins

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.plugin` | — | `.plugin <info\|enable\|disable\|reload> <name>` | Manage a plugin: info, enable, disable, reload. | owner |
| `.plugininfo` | .pinfo | `.plugininfo <name>` | Show one plugin's manifest, capabilities and settings. | owner |
| `.plugins` | — | `.plugins [search]` | List installed plugins with status, version and commands. | owner |
| `.plugintemplate` | — | `.plugintemplate` | Print the copy-paste plugin template. | owner |

### Presence

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.afk` | — | `.afk [30m\|2h\|1d] [reason]  \|  .afk text <message>  \|  .afk autooff on\|off  \|  .afk status` | Away mode: auto-reply once to private chats and log what you missed. | owner |
| `.back` | — | `.back` | End AFK mode and show what you missed. | owner |

### Privacy

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.accountstatus` | — | `.accountstatus` | Report real connection state for this account. | owner |
| `.backup` | — | `.backup [create\|list\|verify <id>\|restore <id>\|confirm <code>\|prune [keep]]` | Create, list, verify, restore or prune local database backups. | owner |
| `.privacy` | — | `.privacy` | Show the privacy and secret-handling rules Reze follows. | owner |
| `.sessions` | — | `.sessions` | Explain how to review active Telegram sessions. | owner |

### Productivity

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.expense` | .expenses | `.expense [list [YYYY-MM]\|add <amount> [category] [note]\|summary [YYYY-MM]\|delete <id>]` | Record expenses and read monthly summaries locally. | owner |
| `.project` | .projects | `.project [list\|add <name> [description]\|close <name>]` | Create, list and close local projects. | owner |
| `.task` | .tasks | `.task [list [status]\|add <title> [@project] [p:1-5] [due:YYYY-MM-DD]\|done <id>\|stats]` | Add, list and complete local tasks. | owner |

### Profile

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.bioclock` | — | `.bioclock on\|off` | Toggle the clock in the bio. | owner |
| `.clockformat` | — | `.clockformat %H:%M` | Set the strftime format for the clock. | owner |
| `.clockpreview` | — | `.clockpreview` | Preview the name and bio with the current time. | owner |
| `.clockstatus` | — | `.clockstatus` | Show the current clock configuration. | owner |
| `.nameclock` | — | `.nameclock on\|off` | Toggle the clock in the display name. | owner |
| `.setbio` | — | `.setbio <text>` | Set the account bio. | owner |
| `.setname` | — | `.setname <name>` | Set the account display name. | owner |
| `.setonlinepermanently` | .alwaysonline, .onlineforever | `.setonlinepermanently <on\|off\|status>` | Keep the account appearing online while Reze runs. | owner |
| `.setprefix` | — | `.setprefix <char>` | Change the command prefix. | owner |
| `.timezone` | — | `.timezone Asia/Tehran` | Set the IANA timezone for the clock. | owner |

### Security

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.antiflood` | — | `.antiflood on\|off` | Enable or disable anti-flood protection. | group admin, group only |
| `.antilink` | — | `.antilink on\|off` | Delete messages that contain links. | group admin, group only |
| `.antiraid` | — | `.antiraid on\|off` | Enable or disable anti-raid protection. | group admin, group only |
| `.cleanservice` | — | `.cleanservice on\|off` | Delete join and leave service messages. | group admin, group only |
| `.lock` | — | `.lock <messages\|media\|stickers\|gifs\|links\|forwards\|games\|inline\|polls>` | Lock a content type in this group using real chat permissions. | group admin, group only |
| `.maintain` | — | `.maintain \| .maintain apply confirm` | Inspect integrity, backup age and retention, or apply retention. | owner |
| `.sentinel` | — | `.sentinel [run\|open\|summary\|resolve <id>]` | Run local security checks and review findings. | owner |
| `.unlock` | — | `.unlock <type>` | Unlock a content type in this group. | group admin, group only |
| `.vault` | — | `.vault [status\|list\|set <name> (reply with the secret)\|put <name> (reply with a file)\|get <name>\|export <name>\|delete <name>]` | Store encrypted secrets and files, unlocked only by the owner. | owner |

### Settings

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.companion` | — | `.companion` | Show the owner-only Telegram Bot Companion status. | owner |
| `.language` | .lang | `.language [en\|fa]` | Show or change the interface language (en / fa). | owner |

### System

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.cancel` | — | `.cancel <task_id>` | Cancel a running or queued background task. | owner |
| `.diagnostics` | — | `.diagnostics` | Integration readiness, dependency health and recent errors. | owner |
| `.features` | .feature, .flags | `.features [list\|status <key>\|enable <key> [confirm]\|disable <key>\|reset confirm]` | List optional features and turn them ON or OFF (OFF by default). | owner |
| `.queue` | — | `.queue` | Show running and queued background tasks. | owner |
| `.status` | — | `.status [task_id]` | Show overall system status, or one task in detail. | everyone allowed by policy |

### Tools

| Command | Aliases | Syntax / arguments | What it does | Access |
| --- | --- | --- | --- | --- |
| `.github` | — | `.github <owner/repo \| owner \| url>` | Information about a GitHub repository or user. | everyone allowed by policy |
| `.tts` | — | `.tts [lang] <text>   or reply to a message` | Turn text into a voice message (gTTS; the text is sent to Google). | everyone allowed by policy |
| `.url` | — | `.url (reply to a file)` | Upload a replied file to catbox.moe and get a public link. | everyone allowed by policy |
| `.weather` | — | `.weather <city>` | Current weather and today's range for a city (Open-Meteo). | everyone allowed by policy |

## Common errors and what they mean

| Reply | Cause | Fix |
| --- | --- | --- |
| `Unknown command` | The name is not registered or the prefix is wrong | Run `.help`; check `.prefix` |
| `Owner only` / silent ignore | You are not `REZE_OWNER_ID` | Use the owner account |
| `Invalid arguments` | Missing or malformed parameters | Read the usage line in the reply or `.help <command>` |
| `<Feature> is OFF by default` | The optional feature is disabled | `.features enable <key>` (add `confirm` if sensitive) |
| `Confirmation required` | A sensitive action needs explicit consent | Repeat with `confirm` |
| `Confirmation code` mismatch/expired | Broadcast, leave, backup restore or approval codes are single-use | Start the action again |
| `AI is not configured` / budget error | No provider key, or the daily budget is spent | Configure `REZE_AI_*`; check `.agent budget` |
| `FFmpeg is not available` | Media conversion needs FFmpeg on PATH | Install FFmpeg or set `REZE_FFMPEG_PATH` |
| `Pillow` / image error | Optional image library missing | `pip install Pillow` |
| `The Vault is locked` | No `REZE_VAULT_KEY` (and only the default secret key) | Set `REZE_VAULT_KEY` and restart |
| `The Vault entry could not be decrypted` | Wrong key or modified data | Restore the original key; do not edit ciphertext |

## Examples by task

```text
# inspect the system
.ping
.version
.status
.diagnostics
.botinfo
.features list

# media on a replied image
.resize 512
.compress 80
.caption deploy passed bottom
.sticker 🙌
.stickerpack My Pack | 🙌

# AI on replied text
.summarize
.translate Persian
.rewrite formal
.describe                      # reply to an image
.digest 50

# personal organisation
.notes add landlord 0912...
.remind 2h call the landlord
.bookmark https://example.com/article read later
.save                            # reply to a message
.search invoice
.find invoice

# group administration (admin rights required)
.warn reason
.warns
.antilink on
.lock links
.setwelcome Welcome {mention} to {title}
.tagall meeting in 5 minutes

# automations
.automation list
.workflow simulate [{"action":"log","message":"tick"}]
.agent tools
```

## Permissions model

1. `REZE_OWNER_ID` is the only account that can run owner commands, regardless
   of chat membership.
2. Group admin commands additionally require Telegram admin rights; REZE checks
   them at execution time and reports the reason when Telegram refuses.
3. Plugins run with the same permissions as REZE itself. They are **not
   sandboxed**: install only code you trust (see `docs/PLUGIN_GUIDE.md`).
4. Optional feature switches are per-installation, not per-chat. Enabling a
   feature affects the whole process; enabling the Bot Companion or AI Agent also
   needs `REZE_*` credentials where documented.

## Documentation map

| Document | Contents |
| --- | --- |
| [README](../README.md) | Overview, install, configuration, first run |
| [INSTALLATION](INSTALLATION.md) | Platform-specific installation and upgrades |
| [CONFIGURATION](CONFIGURATION.md) | Every environment variable and default |
| [AI](AI.md) | Providers, budgets, tools, approvals, Model Council |
| [AUTOMATION](AUTOMATION.md) | Rules, workflows, simulator, restarts |
| [SECURITY](SECURITY.md) | Threat model, secrets, vault, retention, backups |
| [DATABASE](DATABASE.md) | Schema, migrations, FTS5, backup/restore |
| [LOCALIZATION](LOCALIZATION.md) | Persian mode, normalization, Jalali dates |
| [PLUGIN_GUIDE](PLUGIN_GUIDE.md) | Manifest, capabilities and isolation limits |
| [REZE_3_ARCHITECTURE](REZE_3_ARCHITECTURE.md) | Modules, services and data flow |
| [TESTING](TESTING.md) | Running the suite and what it covers |
| [KNOWN_LIMITATIONS](KNOWN_LIMITATIONS.md) | Honest gaps in 3.0 |
