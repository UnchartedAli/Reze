"""
Admin commands: membership control, purge, pins, admins, mentions and slow mode.
"""

from reze.command_router import CommandContext, router
from reze.config import settings
from reze.database import db
from reze.logging_config import logger
from reze.ui import ascii

CATEGORY = "Admin"


async def _resolve_target(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        await ctx.reply(ascii.warning("No target", ["Reply to a member or pass their numeric id."]))
        return None
    return target_id


async def _restrict(ctx: CommandContext, target_id: int, view_messages: bool, send_messages: bool, action: str):
    client = ctx.client
    if client is None or not hasattr(client, "edit_permissions"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    try:
        from telethon.tl.types import ChatBannedRights

        await client.edit_permissions(
            ctx.chat_id,
            target_id,
            ChatBannedRights(
                until_date=None,
                view_messages=view_messages,
                send_messages=send_messages,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - Telegram permission errors
        return await ctx.reply(ascii.error(f"{action.title()} failed", [ascii.sanitize(str(exc))[:200]]))
    db.log_admin_action(action, ctx.sender_id, ctx.chat_id, target_id, action)
    return await ctx.reply(ascii.success(action.replace("_", " ").title(), [f"User: {target_id}"]))


@router.register(name="ban", category=CATEGORY, description="Ban a member from the group.", usage=".ban (reply or id)", admin_only=True, group_only=True)
async def ban_cmd(ctx: CommandContext):
    target_id = await _resolve_target(ctx)
    if target_id:
        return await _restrict(ctx, target_id, view_messages=True, send_messages=True, action="ban")


@router.register(name="unban", category=CATEGORY, description="Remove a ban from a member.", usage=".unban (reply or id)", admin_only=True, group_only=True)
async def unban_cmd(ctx: CommandContext):
    target_id = await _resolve_target(ctx)
    if target_id:
        return await _restrict(ctx, target_id, view_messages=False, send_messages=False, action="unban")


@router.register(name="mute", category=CATEGORY, description="Mute a member.", usage=".mute (reply or id)", admin_only=True, group_only=True)
async def mute_cmd(ctx: CommandContext):
    target_id = await _resolve_target(ctx)
    if target_id:
        return await _restrict(ctx, target_id, view_messages=False, send_messages=True, action="mute")


@router.register(name="unmute", category=CATEGORY, description="Unmute a member.", usage=".unmute (reply or id)", admin_only=True, group_only=True)
async def unmute_cmd(ctx: CommandContext):
    target_id = await _resolve_target(ctx)
    if target_id:
        return await _restrict(ctx, target_id, view_messages=False, send_messages=False, action="unmute")


@router.register(name="kick", category=CATEGORY, description="Kick a member (they can rejoin).", usage=".kick (reply or id)", admin_only=True, group_only=True)
async def kick_cmd(ctx: CommandContext):
    target_id = await _resolve_target(ctx)
    if not target_id:
        return None
    client = ctx.client
    if client is None or not hasattr(client, "kick_participant"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    try:
        await client.kick_participant(ctx.chat_id, target_id)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Kick failed", [ascii.sanitize(str(exc))[:200]]))
    db.log_admin_action("kick", ctx.sender_id, ctx.chat_id, target_id, "kick")
    return await ctx.reply(ascii.success("Kicked", [f"User: {target_id}"]))


@router.register(name="purge", category=CATEGORY, description="Delete recent messages (bounded).", usage=".purge [count]", admin_only=True, group_only=True)
async def purge_cmd(ctx: CommandContext):
    limit = 20
    if ctx.args and ctx.args[0].isdigit():
        limit = max(1, min(int(ctx.args[0]), settings.max_purge_limit))
    client = ctx.client
    if client is None or not hasattr(client, "iter_messages"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    message_ids = []
    try:
        async for message in client.iter_messages(ctx.chat_id, limit=limit):
            message_ids.append(message.id)
        if message_ids and hasattr(client, "delete_messages"):
            await client.delete_messages(ctx.chat_id, message_ids)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Purge failed", [ascii.sanitize(str(exc))[:200]]))
    db.log_admin_action("purge", ctx.sender_id, ctx.chat_id, None, str(len(message_ids)))
    return await ctx.reply(ascii.success("Purged", [f"Deleted up to {len(message_ids)} messages"]))


@router.register(name="del", category=CATEGORY, description="Delete the replied-to message.", usage=".del (reply)", admin_only=True)
async def del_cmd(ctx: CommandContext):
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to the message you want to delete.")
    try:
        reply = await ctx.get_reply_message()
        if reply is not None and hasattr(reply, "delete"):
            await reply.delete()
        await ctx.delete()
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Delete failed", [ascii.sanitize(str(exc))[:200]]))
    return None


@router.register(name="pin", category=CATEGORY, description="Pin the replied-to message.", usage=".pin (reply)", admin_only=True, group_only=True)
async def pin_cmd(ctx: CommandContext):
    if not ctx.is_reply:
        return await ctx.reply_usage("Reply to the message you want to pin.")
    reply = await ctx.get_reply_message()
    if reply is None or ctx.client is None or not hasattr(ctx.client, "pin_message"):
        return await ctx.reply(ascii.warning("Unavailable", ["The message could not be pinned."]))
    try:
        await ctx.client.pin_message(ctx.chat_id, reply.id)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Pin failed", [ascii.sanitize(str(exc))[:200]]))
    return await ctx.reply(ascii.success("Pinned", [f"Message: {reply.id}"]))


@router.register(name="unpin", category=CATEGORY, description="Unpin the current pinned message.", usage=".unpin", admin_only=True, group_only=True)
async def unpin_cmd(ctx: CommandContext):
    if ctx.client is None or not hasattr(ctx.client, "unpin_message"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    try:
        await ctx.client.unpin_message(ctx.chat_id)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Unpin failed", [ascii.sanitize(str(exc))[:200]]))
    return await ctx.reply(ascii.success("Unpinned"))


@router.register(name="admins", category=CATEGORY, description="List group administrators.", usage=".admins", group_only=True)
async def admins_cmd(ctx: CommandContext):
    client = ctx.client
    if client is None or not hasattr(client, "get_participants"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    try:
        from telethon.tl.types import ChannelParticipantsAdmins

        admins = await client.get_participants(ctx.chat_id, filter=ChannelParticipantsAdmins)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Lookup failed", [ascii.sanitize(str(exc))[:200]]))
    lines = []
    for admin in admins:
        name = getattr(admin, "first_name", "") or "Admin"
        lines.append(f"{name} ({admin.id})")
        if len(lines) >= 50:
            break
    if not lines:
        return await ctx.reply(ascii.info("Admins", ["No administrators were returned."]))
    return await ctx.reply(ascii.section(f"Administrators ({len(lines)})", lines))


@router.register(name="tagall", category=CATEGORY, description="Mention recent members in chunks.", usage=".tagall [message]", admin_only=True, group_only=True, cooldown=30)
async def tagall_cmd(ctx: CommandContext):
    message = ctx.args_text.strip() or "Attention everyone"
    max_members = min(50, settings.max_tagall_limit)
    client = ctx.client
    if client is None or not hasattr(client, "get_participants"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    mentions = []
    try:
        async for participant in client.get_participants(ctx.chat_id, limit=max_members):
            if getattr(participant, "bot", False) or getattr(participant, "deleted", False):
                continue
            name = getattr(participant, "first_name", "User")
            mentions.append(f"[{name}](tg://user?id={participant.id})")
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Tagall failed", [ascii.sanitize(str(exc))[:200]]))
    if not mentions:
        return await ctx.reply(ascii.info("Tagall", ["No members to mention."]))
    for offset in range(0, len(mentions), 5):
        chunk = mentions[offset: offset + 5]
        try:
            await client.send_message(ctx.chat_id, f"{message}\n\n" + " ".join(chunk))
        except Exception as exc:  # noqa: BLE001
            logger.warning("tagall chunk failed: %s", exc)
            break
    return None


@router.register(name="slowmode", category=CATEGORY, description="Set the group slow-mode interval.", usage=".slowmode <seconds>", admin_only=True, group_only=True)
async def slowmode_cmd(ctx: CommandContext):
    if not ctx.args or not ctx.args[0].isdigit():
        return await ctx.reply_usage("Example: .slowmode 10 (0 disables it)")
    seconds = min(int(ctx.args[0]), 3600)
    if ctx.client is None or not hasattr(ctx.client, "set_slow_mode"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    try:
        await ctx.client.set_slow_mode(ctx.chat_id, seconds)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Slow mode failed", [ascii.sanitize(str(exc))[:200]]))
    db.update_group_settings(ctx.chat_id, slowmode_seconds=seconds)
    return await ctx.reply(ascii.success("Slow mode updated", [f"{seconds}s"]))
