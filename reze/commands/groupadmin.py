"""
Group administration extras: promote/demote, hidden mentions, description,
title, invite links, joining and leaving chats.

All commands are owner-only; Telegram still enforces the account's own admin
rights, and any refusal is reported instead of hidden.
"""

import re
from typing import Optional

from reze.command_router import CommandContext, router
from reze.config import settings
from reze.core.confirmations import confirmations
from reze.exceptions import ConfirmationError
from reze.logging_config import logger
from reze.ui import ascii

CATEGORY = "Group"

_INVITE_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)([A-Za-z0-9_-]{8,})", re.I)
_PUBLIC_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z][A-Za-z0-9_]{3,})/?$", re.I)
_USERNAME_RE = re.compile(r"^@([A-Za-z][A-Za-z0-9_]{3,})$")


def parse_join_target(text: str):
    """Return ``('hash', value)``, ``('username', value)`` or ``None``."""
    text = (text or "").strip()
    match = _INVITE_RE.match(text)
    if match:
        return "hash", match.group(1)
    match = _PUBLIC_RE.match(text)
    if match:
        return "username", match.group(1)
    match = _USERNAME_RE.match(text)
    if match:
        return "username", match.group(1)
    return None


def _fail(title: str, exc: Exception):
    return ascii.error(title, [ascii.sanitize(str(exc))[:200]])


async def _target(ctx: CommandContext):
    target = await ctx.get_target_user_id()
    if not target:
        await ctx.reply(ascii.warning("No target", ["Reply to a member or pass their numeric id."]))
    return target


# ------------------------------------------------------------- promote / demote
@router.register(
    name="promote", category=CATEGORY, owner_only=True, group_only=True,
    description="Make a member admin (add `full` to also let them add admins).",
    usage=".promote (reply or id) [full] [custom title]",
)
async def promote_cmd(ctx: CommandContext):
    target = await _target(ctx)
    if not target:
        return None
    rest = [a for a in ctx.args if not (a.lstrip("-").isdigit() and int(a) == target)]
    full = bool(rest and rest[0].lower() == "full")
    title = " ".join(rest[1:] if full else rest)[:16] or None
    try:
        await ctx.client.edit_admin(
            ctx.chat_id, target, is_admin=True,
            change_info=True, delete_messages=True, ban_users=True,
            invite_users=True, pin_messages=True, manage_call=True,
            add_admins=full, title=title,
        )
    except Exception as exc:  # noqa: BLE001 - Telegram permission errors
        return await ctx.reply(_fail("Promote failed", exc))
    return await ctx.reply(ascii.success("Promoted", [f"User: {target}", "Can add admins: " + ("yes" if full else "no"),
                                                      f"Title: {title}" if title else "Title: default"]))


@router.register(
    name="demote", category=CATEGORY, owner_only=True, group_only=True,
    description="Remove admin rights from a member.", usage=".demote (reply or id)",
)
async def demote_cmd(ctx: CommandContext):
    target = await _target(ctx)
    if not target:
        return None
    try:
        await ctx.client.edit_admin(ctx.chat_id, target, is_admin=False)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(_fail("Demote failed", exc))
    return await ctx.reply(ascii.success("Demoted", [f"User: {target}"]))


# ----------------------------------------------------------------------- hidetag
def build_hidden_mentions(user_ids, text: str) -> str:
    """Visible *text* plus invisible mention links (zero-width space) for each user."""
    hidden = "".join(f"[\u200b](tg://user?id={int(uid)})" for uid in user_ids)
    return f"{ascii.escape_md(text)}{hidden}"


@router.register(
    name="hidetag", category=CATEGORY, owner_only=True, group_only=True, cooldown=30,
    description="Mention everyone invisibly: members get a notification, the chat sees only your text.",
    usage=".hidetag <text>",
)
async def hidetag_cmd(ctx: CommandContext):
    reply = await ctx.get_reply_message()
    text = ctx.args_text.strip() or (getattr(reply, "text", "") or "").strip()
    if not text:
        return await ctx.reply_usage("Example: .hidetag Meeting starts now")
    limit = max(1, int(settings.max_tagall_limit or 50))
    try:
        me = await ctx.client.get_me()
        members = await ctx.client.get_participants(ctx.chat_id, limit=limit)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(_fail("Could not list members", exc))
    ids = [m.id for m in members
           if not getattr(m, "bot", False) and not getattr(m, "deleted", False) and m.id != getattr(me, "id", None)]
    if not ids:
        return await ctx.reply(ascii.warning("No members", ["Nobody to mention."]))

    try:
        await ctx.message.delete()
    except Exception:  # noqa: BLE001
        pass
    for start in range(0, len(ids), 25):
        chunk = ids[start:start + 25]
        try:
            await ctx.client.send_message(ctx.chat_id, build_hidden_mentions(chunk, text), parse_mode="md")
        except Exception as exc:  # noqa: BLE001
            logger.warning("hidetag chunk failed: %s", exc)
            break
    return None


# ------------------------------------------------------- setdesc / settitle / invite
@router.register(
    name="setdesc", category=CATEGORY, owner_only=True, group_only=True,
    description="Change the group description.", usage=".setdesc <text>   (max 255 characters)",
)
async def setdesc_cmd(ctx: CommandContext):
    from telethon.tl import functions

    about = ctx.args_text.strip()
    if not about:
        return await ctx.reply_usage("Example: .setdesc Friendly place to talk about Python")
    if len(about) > 255:
        return await ctx.reply(ascii.error("Too long", ["Descriptions can have at most 255 characters."]))
    try:
        peer = await ctx.client.get_input_entity(ctx.chat_id)
        await ctx.client(functions.messages.EditChatAboutRequest(peer=peer, about=about))
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(_fail("Description not changed", exc))
    return await ctx.reply(ascii.success("Description updated", [about[:120]]))


@router.register(
    name="settitle", category=CATEGORY, owner_only=True, group_only=True,
    description="Rename the group (`.setname` changes your own profile name).",
    usage=".settitle <new group name>",
)
async def settitle_cmd(ctx: CommandContext):
    from telethon.tl import functions
    from telethon.tl.types import Channel

    title = ctx.args_text.strip()
    if not title:
        return await ctx.reply_usage("Example: .settitle Reze Lounge")
    if len(title) > 128:
        return await ctx.reply(ascii.error("Too long", ["Group names can have at most 128 characters."]))
    try:
        entity = await ctx.client.get_entity(ctx.chat_id)
        if isinstance(entity, Channel):
            await ctx.client(functions.channels.EditTitleRequest(channel=entity, title=title))
        else:
            await ctx.client(functions.messages.EditChatTitleRequest(chat_id=entity.id, title=title))
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(_fail("Rename failed", exc))
    return await ctx.reply(ascii.success("Group renamed", [title]))


@router.register(
    name="invite", category=CATEGORY, owner_only=True, group_only=True,
    description="Create an invite link for this group.", usage=".invite",
)
async def invite_cmd(ctx: CommandContext):
    from telethon.tl import functions

    try:
        peer = await ctx.client.get_input_entity(ctx.chat_id)
        exported = await ctx.client(functions.messages.ExportChatInviteRequest(peer=peer))
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(_fail("Invite failed", exc))
    return await ctx.reply(ascii.success("Invite link", [getattr(exported, "link", "(no link returned)")]))


# --------------------------------------------------------------------- join / leave
@router.register(
    name="join", category=CATEGORY, owner_only=True, cooldown=10,
    description="Join a group or channel by invite link or @username.",
    usage=".join <t.me/+hash | t.me/name | @name>",
)
async def join_cmd(ctx: CommandContext):
    from telethon.tl import functions

    target = parse_join_target(ctx.args[0] if ctx.args else "")
    if target is None:
        return await ctx.reply_usage("Example: .join https://t.me/+AbCdEf123456")
    kind, value = target
    try:
        if kind == "hash":
            await ctx.client(functions.messages.ImportChatInviteRequest(value))
        else:
            entity = await ctx.client.get_input_entity(value)
            await ctx.client(functions.channels.JoinChannelRequest(entity))
    except Exception as exc:  # noqa: BLE001 - expired link, banned, already joined...
        return await ctx.reply(_fail("Join failed", exc))
    return await ctx.reply(ascii.success("Joined", [ctx.args[0][:100]]))


@router.register(
    name="leave", category=CATEGORY, owner_only=True,
    description="Leave this group/channel (needs a confirmation code).",
    usage=".leave   then   .leave confirm <code>",
)
async def leave_cmd(ctx: CommandContext):
    if ctx.args and ctx.args[0].lower() == "confirm":
        try:
            confirmations.consume(ctx.args[1] if len(ctx.args) > 1 else "", "leave", ctx.chat_id, ctx.sender_id)
        except ConfirmationError as exc:
            return await ctx.reply(ascii.error("Not confirmed", [str(exc)]))
        try:
            await ctx.client.delete_dialog(ctx.chat_id)
        except Exception as exc:  # noqa: BLE001
            return await ctx.reply(_fail("Leave failed", exc))
        return None
    if not ctx.chat_id or ctx.chat_id > 0:
        return await ctx.reply(ascii.warning("Groups only", ["Run it inside the group or channel you want to leave."]))
    token = confirmations.issue("leave", ctx.chat_id, ctx.sender_id)
    return await ctx.reply(ascii.warning("Leave this chat?", [
        "You will have to be re-invited to come back.",
        f"Confirm within 2 minutes: .leave confirm {token}"]))
