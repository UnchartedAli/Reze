# REZE 2.0.0 command reference

Generated from the live command registry. The default prefix is `.` and can be
changed with `.prefix <char>`. Every command also answers `.help <command>`.

Access markers: `owner` = only REZE_OWNER_ID; `admin` = group administrators;
`group` = groups only. A cooldown is the minimum interval between two runs by the same user.


## Admin

| Command | Access | Description |
| --- | --- | --- |
| `.admins` | group | List group administrators. |
| `.ban (reply or id)` | admin, group | Ban a member from the group. |
| `.del (reply)` | admin | Delete the replied-to message. |
| `.kick (reply or id)` | admin, group | Kick a member (they can rejoin). |
| `.mute (reply or id)` | admin, group | Mute a member. |
| `.pin (reply)` | admin, group | Pin the replied-to message. |
| `.purge [count]` | admin, group | Delete recent messages (bounded). |
| `.slowmode <seconds>` | admin, group | Set the group slow-mode interval. |
| `.tagall [message]` | admin, group, cooldown 30s | Mention recent members in chunks. |
| `.unban (reply or id)` | admin, group | Remove a ban from a member. |
| `.unmute (reply or id)` | admin, group | Unmute a member. |
| `.unpin` | admin, group | Unpin the current pinned message. |


## Appearance

| Command | Access | Description |
| --- | --- | --- |
| `.config [set <key> <value> | reset <key>]` | owner | Show or change validated user preferences. |
| `.prefix <char>` | owner | Change the command prefix (1-2 characters). |
| `.preview [theme]` | cooldown 2s | Preview the ASCII message engine in a given theme. |
| `.theme [name]` | cooldown 1s | Switch the message theme (CYBER, GHOST, TERMINAL, COMPACT). |


## Automation

| Command | Access | Description |
| --- | --- | --- |
| `.automation <list|show|create|enable|disable|delete> ...` | owner | Create and manage trigger → condition → action rules. |

Aliases: `.automation` = .auto


## General

| Command | Access | Description |
| --- | --- | --- |
| `.alive` | - | Confirm the userbot is running. |
| `.credits` | - | Show the author and the official channel. |
| `.help [category | command]` | cooldown 1s | Show command help by category or for one command. |
| `.id` | - | Show user, chat and message identifiers. |
| `.info` | - | Account and deployment information. |
| `.logs [count]` | owner | Show the most recent log lines. |
| `.ping` | - | Measure command round-trip latency. |
| `.restart` | owner | Restart the Reze process. |
| `.settings` | owner | Show environment configuration (no secrets). |
| `.shutdown` | owner | Stop the Reze process safely. |
| `.stats` | - | Local database and usage statistics. |
| `.uptime` | - | Show process uptime. |
| `.version` | - | Show the running Reze version. |
| `.webpanel` | owner | Show the web panel URL and health endpoint. |

Aliases: `.credits` = .creator, .developer, .support


## Intelligence

| Command | Access | Description |
| --- | --- | --- |
| `.ai <prompt>` | cooldown 3s | Ask the configured AI provider a question (or transform replied text). |
| `.aiinfo` | - | Show the configured AI provider and model without revealing secrets. |
| `.describe (reply to an image)` | cooldown 5s | Describe a replied image using a vision-capable model. |
| `.digest [count]` | cooldown 10s | Summarize the last few messages of this chat (bounded, explicit limit). |
| `.rewrite <shorter|formal|casual|clearer|bullets>` | cooldown 5s | Rewrite replied or provided text in a chosen style. |
| `.summarize [text]` | cooldown 5s | Summarize replied text or the provided text with the AI provider. |
| `.translate <language> [text]` | cooldown 5s | Translate replied or provided text into another language. |

Aliases: `.aiinfo` = .ai_info


## Media

| Command | Access | Description |
| --- | --- | --- |
| `.addsticker <set_short_name> [emoji]` | cooldown 3s | Add a replied image as a sticker to an existing set you own. |
| `.caption <text> [top|center|bottom]` | cooldown 2s | Draw text on a replied image (top, center or bottom). |
| `.compress [quality|crf]` | cooldown 2s | Compress a replied image or video. |
| `.download` | cooldown 2s | Download replied media to a file (subject to Telegram access rules). |
| `.gif [fps] [width]` | cooldown 3s | Convert replied video or animation into a GIF. |
| `.meme <top> | <bottom>` | cooldown 2s | Add top/bottom meme text to a replied image. |
| `.removebg   then   .removebg confirm <code>` | cooldown 5s | Remove the background of a replied image through a configured provider. |
| `.resize <width> [height]` | cooldown 2s | Resize a replied image (or video) with aspect-ratio handling. |
| `.speed <factor>   (0.25 - 4.0)` | cooldown 3s | Change playback speed of replied audio or video. |
| `.sticker (reply to an image)` | cooldown 2s | Convert a replied image into a 512x512 Telegram static sticker. |
| `.stickerpack <title> | <emoji>  then  .stickerpack confirm <code>` | cooldown 5s | Create a real Telegram sticker set from a replied image. |
| `.thumbnail [size]` | cooldown 2s | Generate a thumbnail from a replied image or video. |
| `.toaudio` | cooldown 3s | Extract the audio track from replied video or media. |
| `.toimage [frame_index]` | cooldown 2s | Extract a still image from replied media (first frame by default). |
| `.tovideo` | cooldown 3s | Convert replied media into an H.264 MP4 video. |
| `.trim <start> <end>   (e.g. .trim 0:05 0:35)` | cooldown 3s | Trim replied audio or video between two timestamps. |


## Moderation

| Command | Access | Description |
| --- | --- | --- |
| `.blacklist add|remove|list ...` | admin, group | Manage forbidden words. |
| `.filter add|remove|list ...` | admin, group | Manage automatic keyword replies. |
| `.goodbye on|off` | admin, group | Enable or disable goodbye messages. |
| `.resetwarns (reply or id)` | admin, group | Clear every warning for a member. |
| `.rules` | group | Show the group rules. |
| `.setrules <text>` | admin, group | Set the group rules text. |
| `.setwelcome <text with {mention} and {title}>` | admin, group | Set the welcome message template. |
| `.unwarn (reply or id)` | admin, group | Remove one warning from a member. |
| `.warn [reason] (reply or id)` | admin, group | Warn a member and count it toward the limit. |
| `.warns (reply or id)` | group | Show a member's warning count. |
| `.welcome on|off` | admin, group | Enable or disable welcome messages. |


## Personal

| Command | Access | Description |
| --- | --- | --- |
| `.bookmark <url> [note]` | owner | Bookmark a URL or message reference. |
| `.chatinfo` | cooldown 2s | Show metadata for the current chat. |
| `.files [limit]` | owner, cooldown 3s | List media found in recent chat messages (bounded scan). |
| `.find <query>` | owner | Search your local archive by title, content, URL or tag. |
| `.links [limit]` | owner, cooldown 3s | Extract links from the replied message or recent chat messages. |
| `.notes [add <name> <text> | show <name> | delete <name>]` | owner | Create, list, show and delete personal notes. |
| `.qr <text or URL>` | cooldown 2s | Generate a QR code image locally from text or a URL. |
| `.remind <10m|2h|2d|YYYY-MM-DD HH:MM> <text>   |   .remind list` | owner | Schedule a personal reminder (duration or absolute time). |
| `.save [note text]` | owner | Save a replied message, link or note to your local archive. |
| `.schedule` | owner | Show scheduled reminders and automations. |
| `.search <query> [limit]` | owner, cooldown 3s | Search recent messages in this chat (bounded scan). |
| `.whois [user id | @username] (or reply)` | cooldown 2s | Show Telegram identity details for a user. |

Aliases: `.bookmark` = .bm


## Plugins

| Command | Access | Description |
| --- | --- | --- |
| `.plugin <info|enable|disable|reload> <name>` | owner | Manage a plugin: info, enable, disable, reload. |
| `.plugininfo <name>` | owner | Show one plugin's manifest, capabilities and settings. |
| `.plugins [search]` | owner | List installed plugins with status, version and commands. |
| `.plugintemplate` | owner | Print the copy-paste plugin template. |

Aliases: `.plugininfo` = .pinfo


## Privacy

| Command | Access | Description |
| --- | --- | --- |
| `.accountstatus` | owner | Report real connection state for this account. |
| `.backup` | owner, cooldown 30s | Copy the local database to a timestamped backup file. |
| `.privacy` | owner | Show the privacy and secret-handling rules Reze follows. |
| `.sessions` | owner | Explain how to review active Telegram sessions. |


## Profile

| Command | Access | Description |
| --- | --- | --- |
| `.bioclock on|off` | owner | Toggle the clock in the bio. |
| `.clockformat %H:%M` | owner | Set the strftime format for the clock. |
| `.clockpreview` | owner | Preview the name and bio with the current time. |
| `.clockstatus` | owner | Show the current clock configuration. |
| `.nameclock on|off` | owner | Toggle the clock in the display name. |
| `.setbio <text>` | owner | Set the account bio. |
| `.setname <name>` | owner | Set the account display name. |
| `.setonlinepermanently <on|off|status>` | owner, cooldown 2s | Keep the account appearing online while Reze runs. |
| `.setprefix <char>` | owner | Change the command prefix. |
| `.timezone Asia/Tehran` | owner | Set the IANA timezone for the clock. |

Aliases: `.setonlinepermanently` = .alwaysonline, .onlineforever


## Security

| Command | Access | Description |
| --- | --- | --- |
| `.antiflood on|off` | admin, group | Enable or disable anti-flood protection. |
| `.antilink on|off` | admin, group | Delete messages that contain links. |
| `.antiraid on|off` | admin, group | Enable or disable anti-raid protection. |
| `.cleanservice on|off` | admin, group | Delete join and leave service messages. |
| `.lock <messages|media|stickers|gifs|links|forwards|games|inline|polls>` | admin, group | Lock a content type in this group using real chat permissions. |
| `.unlock <type>` | admin, group | Unlock a content type in this group. |


## System

| Command | Access | Description |
| --- | --- | --- |
| `.cancel <task_id>` | owner, cooldown 1s | Cancel a running or queued background task. |
| `.diagnostics` | owner, cooldown 5s | Integration readiness, dependency health and recent errors. |
| `.queue` | owner, cooldown 2s | Show running and queued background tasks. |
| `.status [task_id]` | cooldown 1s | Show overall system status, or one task in detail. |


## Notes

- Media commands operate on the replied-to message only.
- `.stickerpack` and `.removebg` print a one-time confirmation code that expires after two minutes.
- `.setonlinepermanently` refreshes the account status only while Reze runs and respects privacy settings.
- Long responses are split automatically; captions stay under 1024 characters.
- `.search`, `.links` and `.files` scan a bounded number of recent messages (REZE_SEARCH_SCAN_LIMIT, hard cap 200).
