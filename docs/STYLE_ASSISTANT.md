# Style Assistant

Developer: **UnchartedAli** · Channel: **[@yamods](https://t.me/yamods)**

The Style Assistant learns how **you** write, drafts replies in that style for your
approval, and can send **labelled automatic replies** in private chats you allow.
It is **OFF by default**.

## Design rule: automatic replies are always labelled

Automatic replies are never sent as if you wrote them. Every automatic reply starts
with a fixed line saying it is an automated reply from REZE and that you are not
available right now. The label cannot be turned off. The model is instructed not to
claim to be you or a person, and not to promise, agree to, or confirm anything.

Replies that imitate your voice without disclosure would deceive the people who
receive them. That mode is intentionally not offered.

## Turning it on

1. `.features enable style_assistant confirm`
2. `.style learn @friend 200` — learn from your own messages in one or more chats.
   Repeat for other chats. At least 5 of your messages are needed.
3. `.style show` — see the learned style (aggregate numbers and a few common phrases).
4. Drafts: reply to a message with `.style draft`. The draft is sent to your Saved Messages.
   Send it with `.style send <id>` once you approve.
5. Automatic replies (optional):
   - `.style auto allow @friend` — a private chat with a person (never a bot or a group)
   - `.style auto quiet 23:00 07:00 Asia/Tehran` (optional)
   - `.style auto on`

## What is stored, and what is not

| Stored | Not stored |
| --- | --- |
| Your own text messages from the chats you name (up to 500, newest kept) | Anyone else's messages, including incoming messages |
| A statistical profile: lengths, emoji and script shares, common openers | Media, forwards, and messages with no text |
| Draft text you asked for (until sent or forgotten) | The text of an incoming message you asked to draft from |
| Allow list and the time of the last automatic reply per chat | Incoming message text of automatic replies |

`.style forget confirm` deletes all of the above and turns auto-reply off.

## When an automatic reply is sent

All of these must pass. The first failing check is the reason, which is returned to logs and tests:

1. The chat is on the allow list.
2. It is a private chat, and the sender is not a bot.
3. The message has text.
4. The message does not look sensitive. Sensitive means words about money, accounts,
   passwords, codes, addresses, locations, medical or legal matters, meetings, prices,
   or any long number. Those messages get no reply. You receive a note in Saved Messages
   saying the chat needs you, without the text.
5. It is not within quiet hours.
6. You were not active in that chat in the last 30 minutes (default).
7. The chat has not received an automatic reply within the cooldown (6 hours by default).
8. The hourly total across chats is under the cap (10 by default).
9. The AI returns a reply. If it does not, nothing is sent. There is no canned fallback
   that could be mistaken for you.

Each automatic reply also produces a note in your Saved Messages, so you can see what went out.

## Commands

| Command | Purpose |
| --- | --- |
| `.style` | Status |
| `.style learn <@user\|id> [count]` | Learn from your own messages in one chat (no other messages are read) |
| `.style show` | The learned style, without message text |
| `.style draft` (as a reply) | Draft a reply to that message; sent to Saved Messages for approval |
| `.style send <id>` | Send an approved draft |
| `.style auto on \| off` | Automatic labelled replies |
| `.style auto allow \| block <@user\|id>`, `allowed` | Allow list (private chats with people only) |
| `.style auto quiet HH:MM HH:MM [tz] \| off` | Quiet hours (may cross midnight) |
| `.style auto cooldown <hours>`, `cap <per hour>` | Limits |
| `.style language en \| fa` | Language of the label and of the prompts |
| `.style forget confirm` | Delete everything learned and turn auto-reply off |

All commands are owner-only.

## Web panel

Open **Style Assistant** in the panel (Personal section). It shows:

* feature state (with a link to enable it through the features form, which asks for confirmation)
* whether automatic replies are on, and how many were sent in the last 24 hours
* the learned style in plain numbers
* settings: quiet hours, timezone, cooldown, hourly cap, the owner-active window, and language
* the allow list, with a remove button for each chat
* pending drafts (read-only; send them with `.style send <id>` in Telegram)
* a delete-everything button that needs a confirmation tick

Learning, adding chats to the allow list, and sending drafts need the live Telegram connection,
so they stay in the commands. The panel never sends a message itself.

## Limits and honesty

* **Not tested against a live Telegram account.** The tests use fake clients and fake
  AI responses. They check the rules, the label, sensitive handling, limits, and privacy.
  The Telethon calls (`iter_messages(from_user="me")`, `get_messages`, `send_message`,
  `reply_to`) follow the Telethon documentation and have not been run against a real account.
* **Style matching is approximate.** The profile is statistical and the model imitates
  tone. It will not reproduce your voice exactly, and it may miss your humour or your
  context.
* **Automated messaging is subject to Telegram's terms.** Automatic replies from a user
  account can draw rate limits or restrictions. Keep the allow list short and the caps low.
* **You are responsible for what is sent from your account**, including drafts you approve.
* **Incoming messages are sent to the AI provider you configured** when a reply or draft is
  generated. Use `.features disable style_assistant` or leave auto-reply off to keep them local.
* The sensitive-word check is conservative. It can miss a sensitive message, so the
  allow list should hold only people you trust with an automatic reply.

## Where the code lives

| Part | File |
| --- | --- |
| Schema | `reze/migrations/v6.py` |
| Profile statistics (pure) | `reze/style/profile.py` |
| Auto-reply gate and sensitive check (pure) | `reze/style/safety.py` |
| Storage | `reze/style/store.py` |
| Learning, drafts, auto-replies | `reze/style/service.py` |
| Commands | `reze/commands/style.py` |
| Tests | `tests/test_reze4_style.py` |
