"""
Message Guard commands.

    .watch on | off                 enable / disable the guard
    .watch add [chat_id]            watch this chat (or the given id)
    .watch del [chat_id]            stop watching a chat
    .watch private on|off           watch every private chat
    .watch groups on|off            watch every group / supergroup
    .watch edits on|off             also report edited messages
    .watch media on|off             cache media so deleted files can be re-sent
    .watch ttl on|off               save self-destructing (timed / view-once) media at once
    .watch own on|off               also log your own messages
    .watch dest me|here|<chat_id>   where reports are delivered (default: Saved Messages)
    .watch archive on|off|clear     permanent local copy of deleted + timed media (never auto-deleted)
    .watch keep <hours|forever>     how long NOT-yet-reported copies are cached (1-720)
    .watch find <text>              search the archive (newest first)
    .watch show <id>                send one archived item to the destination
    .watch export [json|csv|zip]    send the whole archive as a file (zip includes media)
    .watch list | status | clear
"""

from typing import List

from reze.command_router import CommandContext, router
from reze.modules.msglog import message_logger as guard
from reze.ui import ascii

CATEGORY = "Guard"

_TRUE = {"on", "1", "yes", "true", "enable"}
_FALSE = {"off", "0", "no", "false", "disable"}
_TOGGLES = {
    "private": "private",
    "groups": "groups",
    "edits": "edits",
    "media": "media",
    "ttl": "ttl",
    "archive": "archive",
    "own": "own",
}
_LABELS = {
    "private": "All private chats",
    "groups": "All groups",
    "edits": "Report edits",
    "media": "Cache media",
    "ttl": "Save timed media",
    "archive": "Permanent archive",
    "own": "Log own messages",
}


def _flag(value: bool) -> str:
    return "ON" if value else "OFF"


def _status_lines() -> List[str]:
    cfg = guard.config
    dest = "Saved Messages" if cfg["dest"] == "me" else str(cfg["dest"])
    lines = [
        f"Guard: {_flag(cfg['enabled'])}",
        f"Deliver to: {dest}",
        f"Keep cache: {'forever' if cfg['retention_hours'] <= 0 else str(cfg['retention_hours']) + 'h'}",
    ]
    lines += [f"{label}: {_flag(cfg[key])}" for key, label in _LABELS.items()]
    lines.append(f"Watched chats: {len(cfg['chats'])}")
    items, megabytes = guard.archive_stats()
    lines.append(f"Archive: {items} items, {megabytes:.1f} MB")
    lines.append(f"Cached now: {guard.count()}")
    stats = guard.stats
    lines.append(f"This session: {stats['stored']} saved, {stats['deleted']} deleted, {stats['edited']} edited, {stats['timed']} timed")
    return lines


def _chat_id(ctx: CommandContext, index: int = 1):
    if len(ctx.args) > index:
        raw = ctx.args[index]
        if raw.lstrip("-").isdigit():
            return int(raw)
        return None
    return ctx.chat_id


@router.register(
    name="watch",
    category=CATEGORY,
    description="Save deleted/edited messages of chosen chats to Saved Messages.",
    usage=".watch <on|off|add|del|list|status|private|groups|edits|media|ttl|archive|find|show|export|own|dest|keep|clear>",
    owner_only=True,
    aliases=["guard", "msglog"],
    examples=[".watch on", ".watch add", ".watch private on", ".watch dest me"],
)
async def watch_cmd(ctx: CommandContext):
    action = ctx.args[0].lower() if ctx.args else "status"

    if action == "status":
        return await ctx.reply(ascii.frame("Message Guard", _status_lines()))

    if action in _TRUE | {"start"} or action in _FALSE | {"stop"}:
        enabled = action in _TRUE | {"start"}
        guard.update(enabled=enabled)
        if enabled:
            guard.start()
            hint = "Add chats with .watch add, or use .watch private on."
        else:
            hint = "Nothing will be saved until you turn it on again."
        return await ctx.reply(ascii.success(f"Guard {_flag(enabled)}", [hint]))

    if action == "add":
        chat_id = _chat_id(ctx)
        if chat_id is None:
            return await ctx.reply_usage("Use a numeric chat id, or run it inside the chat.")
        added = guard.add_chat(chat_id)
        lines = [f"Chat {chat_id} {'added' if added else 'was already watched'}."]
        if not guard.config["enabled"]:
            lines.append("The guard is OFF. Enable it with: .watch on")
        return await ctx.reply(ascii.success("Watching chat", lines))

    if action in ("del", "remove", "rm"):
        chat_id = _chat_id(ctx)
        if chat_id is None:
            return await ctx.reply_usage("Use a numeric chat id, or run it inside the chat.")
        removed = guard.remove_chat(chat_id)
        return await ctx.reply(
            ascii.success("Chat removed", [f"Chat {chat_id} is no longer watched."])
            if removed
            else ascii.warning("Not watched", [f"Chat {chat_id} was not in the list."])
        )

    if action == "list":
        chats = guard.config["chats"]
        lines = []
        for chat_id in chats:
            title = ""
            try:
                entity = await ctx.client.get_entity(chat_id)
                title = getattr(entity, "title", None) or getattr(entity, "first_name", "") or ""
            except Exception:  # noqa: BLE001 - names are decoration only
                pass
            lines.append(f"{chat_id}  {title}".rstrip())
        extras = [f"{_LABELS[k]}: {_flag(guard.config[k])}" for k in ("private", "groups")]
        return await ctx.reply(ascii.frame("Watched chats", (lines or ["(none)"]) + [""] + extras))

    if action == "find":
        query = " ".join(ctx.args[1:]).strip()
        rows = guard.search_archive(query, limit=8)
        if not rows:
            return await ctx.reply(ascii.warning("No matches", ["Nothing in the archive matches that."]))
        lines = []
        for row in rows:
            when = guard._stamp(row["saved_at"])[5:16]
            who = (row["sender_name"] or "?")[:14]
            what = (row["text"] or f"[{row['media_kind'] or 'media'}]").replace("\n", " ")[:28]
            lines.append(f"#{row['id']} {when} {who}: {what}")
        lines += ["", "Open one with: .watch show <id>"]
        return await ctx.reply(ascii.frame(f"Archive ({len(rows)} shown)", lines))

    if action == "show":
        raw = ctx.args[1].lstrip("#") if len(ctx.args) > 1 else ""
        if not raw.isdigit():
            return await ctx.reply_usage(".watch show <id>   (ids come from .watch find)")
        if not await guard.send_archived(ctx.client, int(raw)):
            return await ctx.reply(ascii.warning("Not found", [f"No archived item #{raw}."]))
        return await ctx.reply(ascii.success("Sent", [f"Item #{raw} was sent to the destination."]))

    if action == "export":
        import shutil
        import tempfile

        fmt = (ctx.args[1] if len(ctx.args) > 1 else "json").lower()
        workdir = tempfile.mkdtemp(prefix="reze_export_")
        try:
            try:
                path = guard.export_archive(workdir, fmt)
            except ValueError as exc:
                return await ctx.reply(ascii.error("Export failed", [str(exc)]))
            await ctx.client.send_file(guard.destination(), path, caption="Reze archive export", force_document=True)
            return await ctx.reply(ascii.success("Export sent", [f"Format: {fmt}", "Check the destination chat."]))
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    if action == "archive" and len(ctx.args) > 1 and ctx.args[1].lower() == "clear":
        removed = guard.clear_archive()
        return await ctx.reply(ascii.success("Archive cleared", [f"{removed} archived items removed."]))

    if action in _TOGGLES:
        value = ctx.args[1].lower() if len(ctx.args) > 1 else ""
        if value not in _TRUE | _FALSE:
            return await ctx.reply_usage(f".watch {action} on|off")
        guard.update(**{_TOGGLES[action]: value in _TRUE})
        return await ctx.reply(ascii.success(_LABELS[action], [f"Now {_flag(value in _TRUE)}."]))

    if action == "dest":
        target = ctx.args[1].lower() if len(ctx.args) > 1 else ""
        if target in ("me", "saved", "self"):
            dest = "me"
        elif target == "here":
            dest = str(ctx.chat_id)
        elif target.lstrip("-").isdigit():
            dest = target
        else:
            return await ctx.reply_usage(".watch dest me|here|<chat_id>")
        guard.update(dest=dest)
        label = "Saved Messages" if dest == "me" else dest
        return await ctx.reply(ascii.success("Destination set", [f"Reports go to: {label}"]))

    if action == "keep":
        raw = (ctx.args[1] if len(ctx.args) > 1 else "").lower()
        if raw in ("forever", "0", "never"):
            guard.update(retention_hours=0)
            return await ctx.reply(ascii.success("Retention set", ["Cached copies are never auto-deleted."]))
        if not raw.isdigit() or not 1 <= int(raw) <= 720:
            return await ctx.reply_usage(".watch keep <hours 1-720 | forever>")
        guard.update(retention_hours=int(raw))
        return await ctx.reply(ascii.success("Retention set", [f"Cached copies are kept for {raw}h."]))

    if action == "clear":
        removed = guard.clear()
        return await ctx.reply(ascii.success("Cache cleared", [f"{removed} saved messages removed."]))

    return await ctx.reply_usage()
