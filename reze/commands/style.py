"""``.style`` command family for the Style Assistant (owner only, feature OFF by default)."""

from __future__ import annotations

from typing import Any, List, Optional

from reze.command_router import router
from reze.features import require
from reze.permissions import PermissionManager
from reze.style import profile as prof
from reze.style import store
from reze.style.service import style_service
from reze.ui import ascii

CATEGORY = "Automation"
HELP_LINES = [
    ".style — status",
    ".style learn <@user|id> [count] — learn from your own messages in one chat",
    ".style show — what the learned style looks like (no message text)",
    ".style draft — reply to a message: a draft is sent to Saved Messages for approval",
    ".style send <draft id> — send an approved draft",
    ".style auto on | off — automatic labelled replies (OFF by default)",
    ".style auto allow <@user|id> | block <@user|id> | allowed",
    ".style auto quiet HH:MM HH:MM [timezone] | off",
    ".style auto cooldown <hours> | cap <per hour>",
    ".style language en | fa",
    ".style forget confirm — delete everything learned and turn auto-reply off",
]


async def _resolve(ctx, ref: str) -> Optional[dict]:
    value = (ref or "").strip()
    if not value:
        return None
    target: Any = int(value) if value.lstrip("-").isdigit() else (value if value.startswith("@") else f"@{value}")
    entity = await ctx.client.get_entity(target)
    return {
        "id": int(entity.id),
        "title": getattr(entity, "title", "") or getattr(entity, "first_name", "") or str(entity.id),
        "bot": bool(getattr(entity, "bot", False)),
        "is_user": hasattr(entity, "first_name") and not getattr(entity, "title", None),
    }


async def _status(ctx, args: List[str]) -> Any:
    cfg = store.get_settings()
    lines = [
        f"Auto-reply: {'ON' if cfg['auto_enabled'] else 'OFF'}",
        f"Allowed private chats: {len(store.list_allowed())}",
        f"Learned messages: {store.sample_count()}",
        f"Language: {cfg['language']}",
        f"Quiet hours: {cfg['quiet_start'] or '—'}–{cfg['quiet_end'] or '—'} ({cfg['timezone']})",
    ]
    return await ctx.reply(ascii.section("Style Assistant", lines))


async def _learn(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .style learn @friend 200")
    target = await _resolve(ctx, args[0])
    count = int(args[1]) if len(args) > 1 else 300
    result = await style_service.learn(ctx.client, target["id"], limit=count)
    profile = style_service.reprofile()
    lines = [
        f"Read {result['seen']} message(s) from {target['title']}.",
        f"Stored {result['stored']} of your own messages.",
        f"Total learned: {result['total']}",
    ]
    if int(profile.get("count", 0)) < prof.MIN_SAMPLES_FOR_STYLE:
        lines.append(f"Learn from more chats: at least {prof.MIN_SAMPLES_FOR_STYLE} messages are needed.")
    return await ctx.reply(ascii.success("Style learned", lines))


async def _show(ctx, args: List[str]) -> Any:
    profile = store.get_profile()
    lines = prof.describe(profile, store.get_settings()["language"])
    return await ctx.reply(ascii.section("Your writing style", lines))


async def _draft(ctx, args: List[str]) -> Any:
    reply_to = getattr(ctx.message, "reply_to_msg_id", None)
    if not reply_to:
        return await ctx.reply(ascii.info("Reply to a message", ["Use .style draft as a reply to the message."]))
    result = await style_service.draft(ctx.client, ctx.chat_id, int(reply_to))
    status = result["status"]
    if status == "drafted":
        return await ctx.reply(ascii.success("Draft ready", [f"Sent to Saved Messages as #{result['id']}."]))
    messages = {
        "not_enough_data": f"Learn first: at least {prof.MIN_SAMPLES_FOR_STYLE} of your messages are needed.",
        "no_text": "That message has no text to reply to.",
        "ai_unavailable": "No AI result. Check the AI provider and try again.",
    }
    return await ctx.reply(ascii.warning("No draft", [messages.get(status, status)]))


async def _send(ctx, args: List[str]) -> Any:
    if not args or not args[0].isdigit():
        return await ctx.reply_usage("Example: .style send 3")
    result = await style_service.send_draft(ctx.client, int(args[0]))
    if result["status"] == "sent":
        return await ctx.reply(ascii.success("Draft sent", [f"Draft #{args[0]} was sent."]))
    return await ctx.reply(ascii.warning("Not sent", [f"Draft #{args[0]}: {result['status']}."]))


async def _auto(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .style auto on")
    action = args[0].lower()
    if action in ("on", "off"):
        store.set_setting("auto_enabled", 1 if action == "on" else 0)
        note = "Labelled automatic replies only go to allowed private chats." if action == "on" else "No automatic replies will be sent."
        return await ctx.reply(ascii.success(f"Auto-reply {action.upper()}", [note]))
    if action == "allow":
        if len(args) < 2:
            return await ctx.reply_usage("Example: .style auto allow @friend")
        target = await _resolve(ctx, args[1])
        if target["bot"] or not target["is_user"]:
            return await ctx.reply(ascii.warning("Not allowed", ["Only private chats with people can be allowed."]))
        store.allow_chat(target["id"], target["title"])
        return await ctx.reply(ascii.success("Chat allowed", [target["title"]]))
    if action == "block":
        if len(args) < 2:
            return await ctx.reply_usage("Example: .style auto block @friend")
        target = await _resolve(ctx, args[1])
        removed = store.block_chat(target["id"])
        return await ctx.reply(ascii.info("Chat removed" if removed else "Not on the list", [target["title"]]))
    if action == "allowed":
        rows = store.list_allowed()
        lines = [row["title"] or str(row["chat_id"]) for row in rows] or ["No chats allowed."]
        return await ctx.reply(ascii.section("Allowed for auto-reply", lines))
    if action == "quiet":
        if len(args) >= 2 and args[1].lower() == "off":
            store.clear_quiet()
            return await ctx.reply(ascii.success("Quiet hours off", []))
        if len(args) < 3:
            return await ctx.reply_usage("Example: .style auto quiet 23:00 07:00 Asia/Tehran")
        zone = args[3] if len(args) > 3 else store.get_settings()["timezone"]
        store.set_quiet(args[1], args[2], zone)
        return await ctx.reply(ascii.success("Quiet hours set", [f"{args[1]}–{args[2]} ({zone})"]))
    if action == "cooldown":
        store.set_setting("cooldown_hours", max(1, min(int(args[1]), 168)))
        return await ctx.reply(ascii.success("Cooldown set", [f"{args[1]} hour(s) per chat"]))
    if action == "cap":
        store.set_setting("hourly_cap", max(1, min(int(args[1]), 100)))
        return await ctx.reply(ascii.success("Hourly cap set", [f"{args[1]} automatic reply(ies) per hour"]))
    return await ctx.reply_usage("Options: on, off, allow, block, allowed, quiet, cooldown, cap")


async def _language(ctx, args: List[str]) -> Any:
    if not args or args[0].lower() not in ("en", "fa"):
        return await ctx.reply_usage("Example: .style language fa")
    store.set_setting("language", args[0].lower())
    return await ctx.reply(ascii.success("Language", [args[0].lower()]))


async def _forget(ctx, args: List[str]) -> Any:
    if not args or args[0].lower() != "confirm":
        return await ctx.reply(
            ascii.warning(
                "Confirmation needed",
                [
                    "This deletes everything learned, all drafts, the auto-reply log and the allow list,",
                    "and turns auto-reply off. Run: .style forget confirm",
                ],
            )
        )
    removed = style_service.forget()
    return await ctx.reply(ascii.success("Forgotten", [f"{k}: {v}" for k, v in removed.items()]))


HANDLERS = {
    "status": _status,
    "learn": _learn,
    "show": _show,
    "draft": _draft,
    "send": _send,
    "auto": _auto,
    "language": _language,
    "forget": _forget,
}


@router.register(
    name="style",
    category=CATEGORY,
    description="Style Assistant (owner): learn your writing style, draft replies, optional labelled auto-replies.",
    usage=".style [status|learn|show|draft|send|auto|language|forget]",
    owner_only=True,
    examples=[".style learn @friend 200", ".style draft", ".style auto on"],
)
async def style_cmd(ctx):
    if not PermissionManager.is_owner(ctx.sender_id):
        return await ctx.reply(ascii.warning("Owner only", ["Style Assistant is owner-only."]))
    hint = require("style_assistant")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = ctx.args[0].lower() if ctx.args else "status"
    handler = HANDLERS.get(action)
    if handler is None:
        return await ctx.reply(ascii.section("Style Assistant commands", HELP_LINES))
    try:
        return await handler(ctx, ctx.args[1:])
    except (ValueError, IndexError) as exc:
        return await ctx.reply(ascii.warning("Could not apply", [str(exc) or "Check the arguments."]))


__all__ = ["HANDLERS", "HELP_LINES", "style_cmd"]
