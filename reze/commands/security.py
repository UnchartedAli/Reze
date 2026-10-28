"""
Security commands: anti-flood, anti-raid, anti-link, service cleanup and locks.
"""

from reze.command_router import CommandContext, router
from reze.database import db
from reze.ui import ascii

CATEGORY = "Security"

LOCK_FIELDS = {
    "messages": "send_messages",
    "media": "send_media",
    "stickers": "send_stickers",
    "gifs": "send_gifs",
    "links": "embed_links",
    "forwards": "forwards",
    "games": "send_games",
    "inline": "send_inline",
    "polls": "send_polls",
}


async def _toggle(ctx: CommandContext, keyword: str, label: str):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply_usage(f"Example: .{ctx.command_name} on")
    enabled = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, **{keyword: enabled})
    return await ctx.reply(ascii.info(label, ["enabled" if enabled else "disabled"]))


@router.register(name="antiflood", category=CATEGORY, description="Enable or disable anti-flood protection.", usage=".antiflood on|off", admin_only=True, group_only=True)
async def antiflood_cmd(ctx: CommandContext):
    return await _toggle(ctx, "antiflood_enabled", "Anti-flood")


@router.register(name="antiraid", category=CATEGORY, description="Enable or disable anti-raid protection.", usage=".antiraid on|off", admin_only=True, group_only=True)
async def antiraid_cmd(ctx: CommandContext):
    return await _toggle(ctx, "antiraid_enabled", "Anti-raid")


@router.register(name="antilink", category=CATEGORY, description="Delete messages that contain links.", usage=".antilink on|off", admin_only=True, group_only=True)
async def antilink_cmd(ctx: CommandContext):
    return await _toggle(ctx, "antilink_enabled", "Anti-link")


@router.register(name="cleanservice", category=CATEGORY, description="Delete join and leave service messages.", usage=".cleanservice on|off", admin_only=True, group_only=True)
async def cleanservice_cmd(ctx: CommandContext):
    return await _toggle(ctx, "cleanservice_enabled", "Service message cleanup")


@router.register(
    name="lock",
    category=CATEGORY,
    description="Lock a content type in this group using real chat permissions.",
    usage=".lock <messages|media|stickers|gifs|links|forwards|games|inline|polls>",
    admin_only=True,
    group_only=True,
)
async def lock_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Types: " + ", ".join(sorted(LOCK_FIELDS)))
    kind = ctx.args[0].lower()
    field = LOCK_FIELDS.get(kind)
    if field is None:
        return await ctx.reply(ascii.error("Unknown lock", ["Types: " + ", ".join(sorted(LOCK_FIELDS))]))
    if ctx.client is None or not hasattr(ctx.client, "edit_permissions"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    try:
        from telethon.tl.types import ChatBannedRights

        await ctx.client.edit_permissions(ctx.chat_id, None, ChatBannedRights(**{field: True}))
    except Exception as exc:  # noqa: BLE001 - Telegram permission errors
        return await ctx.reply(ascii.error("Lock failed", [ascii.sanitize(str(exc))[:200]]))
    db.log_admin_action("lock", ctx.sender_id, ctx.chat_id, None, kind)
    return await ctx.reply(ascii.success("Locked", [kind]))


@router.register(
    name="unlock",
    category=CATEGORY,
    description="Unlock a content type in this group.",
    usage=".unlock <type>",
    admin_only=True,
    group_only=True,
)
async def unlock_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Types: " + ", ".join(sorted(LOCK_FIELDS)))
    kind = ctx.args[0].lower()
    field = LOCK_FIELDS.get(kind)
    if field is None:
        return await ctx.reply(ascii.error("Unknown lock", ["Types: " + ", ".join(sorted(LOCK_FIELDS))]))
    if ctx.client is None or not hasattr(ctx.client, "edit_permissions"):
        return await ctx.reply(ascii.warning("Unavailable", ["No Telegram client is connected."]))
    try:
        from telethon.tl.types import ChatBannedRights

        await ctx.client.edit_permissions(ctx.chat_id, None, ChatBannedRights(**{field: False}))
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Unlock failed", [ascii.sanitize(str(exc))[:200]]))
    db.log_admin_action("unlock", ctx.sender_id, ctx.chat_id, None, kind)
    return await ctx.reply(ascii.success("Unlocked", [kind]))
