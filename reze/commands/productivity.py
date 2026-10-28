"""
Personal productivity commands.

Local archive, notes, bookmarks, reminders, bounded chat search and identity
tools. Everything is explicit about its limits: search only looks at a bounded
number of recent messages, never downloads history in bulk, and distinguishes
the local archive from Telegram's own history.
"""

import os
import re
from datetime import datetime, timedelta

from reze.command_router import CommandContext, router
from reze.config import settings
from reze.database import db
from reze.media.workspace import MediaWorkspace
from reze.productivity.qr import encode_qr, to_png
from reze.productivity.reminders import parse_absolute, parse_duration
from reze.ui import ascii

CATEGORY = "Personal"
LINK_RE = re.compile(r"https?://[^\s<>\"']+|t\.me/[^\s<>\"']+", re.IGNORECASE)


def _snippet(value: str, size: int = 90) -> str:
    text = " ".join((value or "").split())
    return text[:size] + ("..." if len(text) > size else "")


@router.register(
    name="save",
    category=CATEGORY,
    description="Save a replied message, link or note to your local archive.",
    usage=".save [note text]",
    owner_only=True,
)
async def save_cmd(ctx: CommandContext):
    reply = await ctx.get_reply_message()
    if reply is not None:
        content = getattr(reply, "message", "") or ""
        if not content and getattr(reply, "media", None):
            content = "[media message]"
        title = _snippet(content, 60) or "Saved message"
        entry_id = db.add_archive(
            kind="message",
            title=title,
            content=content,
            chat_id=ctx.chat_id,
            message_id=getattr(reply, "id", None),
        )
        return await ctx.reply(
            ascii.success("Saved to archive", [f"Entry: {ascii.code(entry_id)}", f"Title: {title}"])
        )

    text = ctx.args_text.strip()
    if not text:
        return await ctx.reply_usage("Reply to a message, or pass the text to save.")
    links = LINK_RE.findall(text)
    kind = "link" if links and len(links[0]) > len(text) // 2 else "note"
    entry_id = db.add_archive(
        kind=kind,
        title=_snippet(text, 60),
        content=text,
        url=links[0] if links else "",
    )
    return await ctx.reply(
        ascii.success("Saved to archive", [f"Entry: {ascii.code(entry_id)}", f"Type: {kind}"])
    )


@router.register(
    name="find",
    category=CATEGORY,
    description="Search your local archive by title, content, URL or tag.",
    usage=".find <query>",
    owner_only=True,
)
async def find_cmd(ctx: CommandContext):
    query = ctx.args_text.strip()
    if not query:
        return await ctx.reply_usage("Example: .find mtproto")
    rows = db.search_archive(query, limit=15)
    if not rows:
        return await ctx.reply(
            ascii.info("No matches", [f"Nothing in the local archive matches '{query}'."])
        )
    lines = []
    for row in rows:
        detail = row.get("url") or row.get("content") or ""
        lines.append(f"#{row['id']} [{row['kind']}] {_snippet(row.get('title') or detail, 70)}")
    lines.append("")
    lines.append(f"Matches: {len(rows)} (local archive only)")
    return await ctx.reply(ascii.section(f"Archive: {query}", lines))


@router.register(
    name="bookmark",
    category=CATEGORY,
    description="Bookmark a URL or message reference.",
    usage=".bookmark <url> [note]",
    owner_only=True,
    aliases=["bm"],
)
async def bookmark_cmd(ctx: CommandContext):
    text = ctx.args_text.strip()
    if not text:
        return await ctx.reply_usage("Example: .bookmark https://telegram.org/docs")
    urls = LINK_RE.findall(text)
    entry_id = db.add_archive(
        kind="bookmark",
        title=_snippet(text, 60),
        content=text,
        url=urls[0] if urls else "",
    )
    return await ctx.reply(
        ascii.success("Bookmarked", [f"Entry: {ascii.code(entry_id)}", f"URL: {urls[0] if urls else 'none'}"])
    )


@router.register(
    name="notes",
    category=CATEGORY,
    description="Create, list, show and delete personal notes.",
    usage=".notes [add <name> <text> | show <name> | delete <name>]",
    owner_only=True,
)
async def notes_cmd(ctx: CommandContext):
    action = ctx.args[0].lower() if ctx.args else "list"

    if action == "list" or not ctx.args:
        notes = db.list_personal_notes()
        if not notes:
            return await ctx.reply(
                ascii.info("No notes yet", ["Create one with .notes add <name> <text>"])
            )
        lines = [f"{row['name']}  ({_snippet(row['content'], 50)})" for row in notes]
        return await ctx.reply(ascii.section(f"Personal notes ({len(notes)})", lines))

    if action == "add" and len(ctx.args) >= 2:
        name = ctx.args[1].lower()
        text = " ".join(ctx.args[2:]).strip()
        if not text:
            reply = await ctx.get_reply_message()
            text = (getattr(reply, "message", "") or "").strip() if reply else ""
        if not text:
            return await ctx.reply_usage("Example: .notes add deploy Run the checklist")
        if not re.match(r"^[a-z0-9_-]{1,32}$", name):
            return await ctx.reply(
                ascii.error("Invalid note name", ["Use 1-32 lowercase letters, digits, - or _."])
            )
        db.set_personal_note(name, text[:4000])
        return await ctx.reply(ascii.success("Note saved", [f"Name: {ascii.code(name)}"]))

    if action == "show" and len(ctx.args) >= 2:
        content = db.get_personal_note(ctx.args[1])
        if content is None:
            return await ctx.reply(ascii.warning("Note not found", [ctx.args[1]]))
        return await ctx.reply(ascii.frame(f"Note: {ctx.args[1]}", [content]))

    if action == "delete" and len(ctx.args) >= 2:
        deleted = db.delete_personal_note(ctx.args[1])
        message = "Note deleted." if deleted else "No such note."
        return await ctx.reply(ascii.info("Notes", [message]))

    return await ctx.reply_usage("Actions: list, add, show, delete")


@router.register(
    name="remind",
    category=CATEGORY,
    description="Schedule a personal reminder (duration or absolute time).",
    usage=".remind <10m|2h|2d|YYYY-MM-DD HH:MM> <text>   |   .remind list",
    owner_only=True,
)
async def remind_cmd(ctx: CommandContext):
    if ctx.args and ctx.args[0].lower() == "list":
        rows = db.list_reminders(status="pending", limit=20)
        if not rows:
            return await ctx.reply(ascii.info("No reminders", ["Nothing is scheduled."]))
        lines = [f"#{row['id']}  {row['due_at']} UTC  {_snippet(row['text'], 50)}" for row in rows]
        return await ctx.reply(ascii.section("Pending reminders", lines))

    if ctx.args and ctx.args[0].lower() == "cancel" and len(ctx.args) > 1:
        try:
            reminder_id = int(ctx.args[1])
        except ValueError:
            return await ctx.reply_usage("Example: .remind cancel 12")
        ok = db.cancel_reminder(reminder_id, ctx.sender_id)
        return await ctx.reply(
            ascii.info("Reminders", ["Reminder cancelled." if ok else "No matching pending reminder."])
        )

    if len(ctx.args) < 2:
        return await ctx.reply_usage("Example: .remind 10m stretch")

    first = ctx.args[0]
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}", first):
            stamp = f"{first} {ctx.args[1]}" if len(ctx.args) > 1 and re.match(r"^\d{1,2}:\d{2}$", ctx.args[1]) else first
            due = parse_absolute(stamp, settings.timezone)
            text = " ".join(ctx.args[2:]) if stamp != first else " ".join(ctx.args[1:])
        else:
            seconds = parse_duration(first)
            due = datetime.utcnow() + timedelta(seconds=seconds)
            text = " ".join(ctx.args[1:])
    except ValueError as exc:
        return await ctx.reply(ascii.error("Invalid reminder", [str(exc)]))

    if not text.strip():
        return await ctx.reply_usage("Add the reminder text after the time.")

    reminder_id = db.add_reminder(ctx.chat_id or ctx.sender_id, ctx.sender_id, text[:1000], due)
    return await ctx.reply(
        ascii.success(
            "Reminder scheduled",
            [f"ID: {ascii.code(reminder_id)}", f"Due: {due.strftime('%Y-%m-%d %H:%M')} UTC"],
            footer="Delivered by the reminder service",
        )
    )


@router.register(
    name="schedule",
    category=CATEGORY,
    description="Show scheduled reminders and automations.",
    usage=".schedule",
    owner_only=True,
)
async def schedule_cmd(ctx: CommandContext):
    reminders = db.list_reminders(status="pending", limit=10)
    automations = db.list_automations(limit=10)
    lines = ["Reminders:"]
    if reminders:
        lines.extend(
            f"  #{row['id']}  {row['due_at']} UTC  {_snippet(row['text'], 40)}" for row in reminders
        )
    else:
        lines.append("  none")
    lines.append("")
    lines.append("Automation rules:")
    if automations:
        for row in automations:
            state = "on" if row["enabled"] else "off"
            lines.append(f"  {row['name']}  [{state}]  {row['trigger_type']}")
    else:
        lines.append("  none")
    return await ctx.reply(ascii.section("Schedule", lines))


@router.register(
    name="search",
    category=CATEGORY,
    description="Search recent messages in this chat (bounded scan).",
    usage=".search <query> [limit]",
    owner_only=True,
    cooldown=3,
)
async def search_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .search deploy 50")
    limit = settings.search_scan_limit
    words = list(ctx.args)
    if words[-1].isdigit():
        limit = min(int(words.pop()), settings.search_scan_limit)
    query = " ".join(words).strip()
    limit = max(5, min(limit, 200))

    client = ctx.client
    if client is None or not hasattr(client, "iter_messages"):
        return await ctx.reply(ascii.warning("Search unavailable", ["No Telegram client is connected."]))

    matches = []
    try:
        async for message in client.iter_messages(ctx.chat_id, limit=limit, search=query):
            text = (getattr(message, "message", "") or "").strip()
            if text:
                matches.append((message.id, text))
            if len(matches) >= 10:
                break
    except Exception as exc:  # noqa: BLE001 - Telegram search failures
        return await ctx.reply(ascii.error("Search failed", [ascii.sanitize(str(exc))[:200]]))

    if not matches:
        return await ctx.reply(
            ascii.info(
                "No matches",
                [f"Nothing matched '{query}' in the last {limit} messages."],
            )
        )
    lines = [f"#{message_id}: {_snippet(text, 80)}" for message_id, text in matches]
    lines.append("")
    lines.append(f"Scanned up to {limit} recent messages · {len(matches)} matches")
    return await ctx.reply(ascii.section(f"Search: {query}", lines))


@router.register(
    name="links",
    category=CATEGORY,
    description="Extract links from the replied message or recent chat messages.",
    usage=".links [limit]",
    owner_only=True,
    cooldown=3,
)
async def links_cmd(ctx: CommandContext):
    reply = await ctx.get_reply_message()
    if reply is not None:
        text = getattr(reply, "message", "") or ""
        links = list(dict.fromkeys(LINK_RE.findall(text)))
        if not links:
            return await ctx.reply(ascii.info("No links", ["The replied message contains no links."]))
        return await ctx.reply(ascii.section("Links", links[:20]))

    limit = min(settings.search_scan_limit, 100)
    if ctx.args and ctx.args[0].isdigit():
        limit = max(5, min(int(ctx.args[0]), 100))
    client = ctx.client
    if client is None or not hasattr(client, "iter_messages"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    found = []
    try:
        async for message in client.iter_messages(ctx.chat_id, limit=limit):
            for link in LINK_RE.findall(getattr(message, "message", "") or ""):
                if link not in found:
                    found.append(link)
            if len(found) >= 20:
                break
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Scan failed", [ascii.sanitize(str(exc))[:200]]))
    if not found:
        return await ctx.reply(ascii.info("No links", [f"None in the last {limit} messages."]))
    return await ctx.reply(
        ascii.section("Links", found[:20] + ["", f"Scanned up to {limit} messages"])
    )


@router.register(
    name="files",
    category=CATEGORY,
    description="List media found in recent chat messages (bounded scan).",
    usage=".files [limit]",
    owner_only=True,
    cooldown=3,
)
async def files_cmd(ctx: CommandContext):
    limit = min(settings.search_scan_limit, 100)
    if ctx.args and ctx.args[0].isdigit():
        limit = max(5, min(int(ctx.args[0]), 100))
    client = ctx.client
    if client is None or not hasattr(client, "iter_messages"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    rows = []
    try:
        async for message in client.iter_messages(ctx.chat_id, limit=limit):
            if getattr(message, "media", None) is None:
                continue
            file_info = getattr(message, "file", None)
            name = getattr(file_info, "name", "") or getattr(file_info, "mime_type", "") or "media"
            size = getattr(file_info, "size", 0) or 0
            rows.append(f"#{message.id}  {_snippet(name, 40)}  {size // 1024} KB")
            if len(rows) >= 15:
                break
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Scan failed", [ascii.sanitize(str(exc))[:200]]))
    if not rows:
        return await ctx.reply(ascii.info("No media", [f"None in the last {limit} messages."]))
    return await ctx.reply(ascii.section("Media", rows))


@router.register(
    name="qr",
    category=CATEGORY,
    description="Generate a QR code image locally from text or a URL.",
    usage=".qr <text or URL>",
    cooldown=2,
)
async def qr_cmd(ctx: CommandContext):
    text = ctx.args_text.strip()
    if not text:
        reply = await ctx.get_reply_message()
        text = (getattr(reply, "message", "") or "").strip() if reply else ""
    if not text:
        return await ctx.reply_usage("Example: .qr https://t.me/yamods")
    if len(text.encode("utf-8")) > 213:
        return await ctx.reply(
            ascii.error(
                "Text is too long",
                ["QR codes generated locally hold up to 213 bytes at level M."],
            )
        )

    workspace = MediaWorkspace("qr")
    try:
        code = encode_qr(text, "M")
        target = os.path.join(workspace.directory, "qr.png")
        to_png(code, target, scale=8)
        await ctx.send_file(
            file=target,
            caption=ascii.escape_for_caption(f"QR · {_snippet(text, 60)}"),
            force_document=False,
        )
        return None
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("QR generation failed", [ascii.sanitize(str(exc))[:150]]))
    finally:
        workspace.cleanup()


@router.register(
    name="whois",
    category=CATEGORY,
    description="Show Telegram identity details for a user.",
    usage=".whois [user id | @username] (or reply)",
    cooldown=2,
)
async def whois_cmd(ctx: CommandContext):
    client = ctx.client
    if client is None or not hasattr(client, "get_entity"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))

    candidate = None
    if ctx.args:
        arg = ctx.args[0]
        candidate = int(arg) if arg.lstrip("-").isdigit() else arg
    else:
        reply = await ctx.get_reply_message()
        if reply is not None:
            candidate = getattr(reply, "sender_id", None)
        if candidate is None:
            try:
                candidate = await client.get_me()
            except Exception:
                candidate = None

    if candidate is None:
        return await ctx.reply(
            ascii.warning("No target", ["Reply to a user, or pass an id or @username."])
        )

    try:
        entity = await client.get_entity(candidate)
    except Exception as exc:  # noqa: BLE001 - unresolved entity or privacy
        return await ctx.reply(
            ascii.error(
                "Lookup failed",
                ["The user could not be resolved.", ascii.sanitize(str(exc))[:120]],
            )
        )

    name = " ".join(
        filter(None, [getattr(entity, "first_name", ""), getattr(entity, "last_name", "")])
    )
    lines = [
        f"ID: {getattr(entity, 'id', 'unknown')}",
        f"Username: @{getattr(entity, 'username', '') or 'none'}",
        f"Name: {name or 'unknown'}",
        f"Bot: {'yes' if getattr(entity, 'bot', False) else 'no'}",
        f"Verified: {'yes' if getattr(entity, 'verified', False) else 'no'}",
        f"Deleted: {'yes' if getattr(entity, 'deleted', False) else 'no'}",
    ]
    return await ctx.reply(ascii.frame("User info", lines))


@router.register(
    name="chatinfo",
    category=CATEGORY,
    description="Show metadata for the current chat.",
    usage=".chatinfo",
    cooldown=2,
)
async def chatinfo_cmd(ctx: CommandContext):
    lines = [f"Chat ID: {ctx.chat_id}", f"Type: {'group' if (ctx.chat_id or 0) < 0 else 'private'}"]
    client = ctx.client
    if client is not None and hasattr(client, "get_entity"):
        try:
            entity = await client.get_entity(ctx.chat_id)
            lines.extend(
                [
                    f"Title: {getattr(entity, 'title', '') or getattr(entity, 'first_name', '') or 'unknown'}",
                    f"Username: @{getattr(entity, 'username', '') or 'none'}",
                ]
            )
            if hasattr(entity, "participants_count") and getattr(entity, "participants_count", None):
                lines.append(f"Participants: {entity.participants_count}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"Metadata: unavailable ({ascii.sanitize(str(exc))[:80]})")
    return await ctx.reply(ascii.frame("Chat info", lines))
