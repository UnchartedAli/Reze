"""
Owner suite: account/bot info, shell, environment variables, blocking,
broadcast and self-update.

Everything here is owner-only (the router ignores everyone else silently).
The two most powerful commands are opt-in:

* ``.exec`` needs ``REZE_ENABLE_EXEC=true``;
* ``.broadcast`` needs a confirmation code and is rate-limited.
"""

import asyncio
import json
import os
import platform
import random
import sys
import time
from datetime import timedelta

from reze import __author__, __version__
from reze.command_router import CommandContext, router
from reze.commands.general import START_TIME
from reze.config import settings
from reze.core import envfile, shell
from reze.core.confirmations import confirmations as _confirmations
from reze.exceptions import ConfirmationError
from reze.logging_config import logger
from reze.ui import ascii

CATEGORY = "Owner"
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
EXEC_TIMEOUT = 60
BROADCAST_DEFAULT_MAX = 100
BROADCAST_TEXT_LIMIT = 400

_sleep = asyncio.sleep  # swapped out in tests


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_path() -> str:
    return os.environ.get("REZE_ENV_FILE") or os.path.join(REPO_ROOT, ".env")


def _after_command(ctx: CommandContext) -> str:
    """Everything after the command word, with the original spacing."""
    parts = (ctx.raw_text or "").split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


async def _delete_command(ctx: CommandContext) -> None:
    try:
        await ctx.message.delete()
    except Exception:  # noqa: BLE001 - best effort
        pass


# ----------------------------------------------------------------- owner / botinfo
@router.register(
    name="owner", category=CATEGORY, owner_only=True,
    description="Show the owner (this account) details.", usage=".owner",
)
async def owner_cmd(ctx: CommandContext):
    me = None
    try:
        me = await ctx.client.get_me()
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_me failed: %s", exc)
    lines = []
    if me is not None:
        name = " ".join(p for p in (getattr(me, "first_name", ""), getattr(me, "last_name", "")) if p)
        lines += [f"Name: {name or '-'}", f"Username: @{me.username}" if getattr(me, "username", None) else "Username: -",
                  f"Account id: {me.id}"]
        if getattr(me, "premium", False):
            lines.append("Telegram Premium: yes")
        if settings.owner_id and settings.owner_id != me.id:
            lines.append(f"Note: REZE_OWNER_ID ({settings.owner_id}) differs from this account.")
    lines += [f"Configured owner id: {settings.owner_id or 'not set'}",
              f"Command prefix: {router.prefix}", f"Developer: {__author__}"]
    return await ctx.reply(ascii.frame("Owner", lines))


@router.register(
    name="botinfo", category=CATEGORY, owner_only=True,
    description="Show version, uptime, runtime and enabled features.", usage=".botinfo",
)
async def botinfo_cmd(ctx: CommandContext):
    from reze.media import ffmpeg

    try:
        import yt_dlp  # noqa: F401
        ytdlp = "installed"
    except ImportError:
        ytdlp = "missing (pip install yt-dlp)"
    try:
        import gtts  # noqa: F401
        tts = "installed"
    except ImportError:
        tts = "missing (pip install gTTS)"

    try:
        from reze.plugin_manager import plugin_manager

        plugins = len(plugin_manager.states)
    except Exception:  # noqa: BLE001
        plugins = 0
    lines = [
        f"Reze {__version__} by {__author__}",
        f"Uptime: {timedelta(seconds=int(time.time() - START_TIME))}",
        f"Python {platform.python_version()} on {platform.system()}",
        f"Commands: {len(router.commands)}   Plugins: {plugins}",
        f"Executed: {router.total_executed}   Errors: {router.errors_count}   Ignored: {router.denied_count}",
        f"FFmpeg: {'available' if ffmpeg.available() else 'missing'}",
        f"yt-dlp: {ytdlp}",
        f"gTTS: {tts}",
        f".exec: {'ENABLED' if _flag('REZE_ENABLE_EXEC') else 'disabled'}",
        f"Public commands: {'ON' if router.public_commands_enabled() else 'off (owner only)'}",
    ]
    return await ctx.reply(ascii.frame("Bot info", lines))


# ------------------------------------------------------------------------- exec
@router.register(
    name="exec", category=CATEGORY, owner_only=True, cooldown=2,
    description="Run a shell command on the host (needs REZE_ENABLE_EXEC=true).",
    usage=".exec <command>",
    examples=[".exec uname -a", ".exec df -h"],
)
async def exec_cmd(ctx: CommandContext):
    if not _flag("REZE_ENABLE_EXEC"):
        return await ctx.reply(ascii.warning("Exec is disabled", [
            "Remote shell access is off by default.",
            "Enable it with: .setvar REZE_ENABLE_EXEC true",
            "then restart Reze (.restart).",
        ]))
    command = _after_command(ctx)
    if not command:
        return await ctx.reply_usage("Example: .exec uname -a")

    logger.warning("EXEC by %s: %s", ctx.sender_id, command[:200])
    result = await shell.run(command, timeout=EXEC_TIMEOUT, cwd=REPO_ROOT)
    status = "timed out" if result.timed_out else f"exit {result.code}"
    body = [f"$ {command[:300]}", f"{status} in {result.elapsed:.1f}s", ""]
    body += (result.output or "(no output)").splitlines()
    title = "Exec" if (result.code == 0 and not result.timed_out) else "Exec (failed)"
    return await ctx.reply(ascii.frame(title, body))


# ---------------------------------------------------------------- setvar / getvar
@router.register(
    name="setvar", category=CATEGORY, owner_only=True,
    description="Set a REZE_* variable in .env (most need a restart).",
    usage=".setvar <REZE_NAME> <value>", examples=[".setvar REZE_THEME GHOST"],
)
async def setvar_cmd(ctx: CommandContext):
    parts = _after_command(ctx).split(None, 1)
    if len(parts) != 2:
        return await ctx.reply_usage("Example: .setvar REZE_THEME GHOST")
    try:
        key = envfile.valid_key(parts[0])
        value = envfile.valid_value(parts[1].strip())
    except envfile.EnvFileError as exc:
        return await ctx.reply(ascii.error("Invalid variable", [str(exc)]))

    secret = envfile.is_secret(key)
    if secret:
        await _delete_command(ctx)  # never leave a key or password sitting in the chat
    try:
        _, replaced = envfile.set_value(_env_path(), key, value)
    except OSError as exc:
        return await ctx.reply(ascii.error("Could not write .env", [ascii.sanitize(str(exc))[:150]]))
    os.environ[key] = value
    return await ctx.reply(ascii.success("Variable saved", [
        f"{key} = {envfile.display(key, value)}",
        "Updated existing value." if replaced else "Added new value.",
        "Restart Reze for it to take full effect: .restart",
    ]))


@router.register(
    name="getvar", category=CATEGORY, owner_only=True,
    description="Show a REZE_* variable (secrets are masked) or list them all.",
    usage=".getvar [REZE_NAME]",
)
async def getvar_cmd(ctx: CommandContext):
    if not ctx.args:
        items = envfile.listing(_env_path())
        lines = [f"{k} = {v}" for k, v in items] or ["(no REZE_* values in .env)"]
        return await ctx.reply(ascii.frame("Variables", lines))
    try:
        key = envfile.valid_key(ctx.args[0])
    except envfile.EnvFileError as exc:
        return await ctx.reply(ascii.error("Invalid variable", [str(exc)]))
    stored = envfile.read(_env_path()).get(key)
    live = os.environ.get(key)
    if stored is None and live is None:
        return await ctx.reply(ascii.warning("Not set", [f"{key} has no value."]))
    lines = []
    if stored is not None:
        lines.append(f".env: {envfile.display(key, stored)}")
    if live is not None and live != stored:
        lines.append(f"running: {envfile.display(key, live)}")
    return await ctx.reply(ascii.frame(key, lines))


@router.register(
    name="delvar", category=CATEGORY, owner_only=True,
    description="Remove a REZE_* variable from .env.", usage=".delvar <REZE_NAME>",
)
async def delvar_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .delvar REZE_ENABLE_EXEC")
    try:
        key = envfile.valid_key(ctx.args[0])
    except envfile.EnvFileError as exc:
        return await ctx.reply(ascii.error("Invalid variable", [str(exc)]))
    removed = envfile.delete_value(_env_path(), key)
    os.environ.pop(key, None)
    if not removed:
        return await ctx.reply(ascii.warning("Not found", [f"{key} was not in .env."]))
    return await ctx.reply(ascii.success("Variable removed", [key, "Restart Reze to apply: .restart"]))


# -------------------------------------------------------------------- block / unblock
async def _user_target(ctx: CommandContext):
    """Resolve a user from reply, @username, numeric id, or the current private chat."""
    target = await ctx.get_target_user_id()
    if target:
        return target
    if ctx.args and ctx.args[0].startswith("@") and len(ctx.args[0]) > 2:
        return ctx.args[0]
    if ctx.chat_id and ctx.chat_id > 0:
        return ctx.chat_id
    return None


async def _set_block(ctx: CommandContext, block: bool):
    from telethon.tl import functions

    target = await _user_target(ctx)
    if target is None:
        return await ctx.reply(ascii.warning("No target", [
            "Reply to a user, pass a numeric id or @username, or run it in their private chat."]))
    try:
        entity = await ctx.client.get_input_entity(target)
        me = await ctx.client.get_me()
        if getattr(entity, "user_id", None) == getattr(me, "id", None):
            return await ctx.reply(ascii.warning("Not allowed", ["You cannot block yourself."]))
        request = functions.contacts.BlockRequest(id=entity) if block else functions.contacts.UnblockRequest(id=entity)
        await ctx.client(request)
    except Exception as exc:  # noqa: BLE001
        return await ctx.reply(ascii.error("Block failed" if block else "Unblock failed",
                                           [ascii.sanitize(str(exc))[:200]]))
    return await ctx.reply(ascii.success("User blocked" if block else "User unblocked", [f"Target: {target}"]))


@router.register(name="block", category=CATEGORY, owner_only=True,
                 description="Block a user.", usage=".block (reply, @username, id or private chat)")
async def block_cmd(ctx: CommandContext):
    return await _set_block(ctx, True)


@router.register(name="unblock", category=CATEGORY, owner_only=True,
                 description="Unblock a user.", usage=".unblock (reply, @username, id or private chat)")
async def unblock_cmd(ctx: CommandContext):
    return await _set_block(ctx, False)


# --------------------------------------------------------------------- broadcast
def broadcast_limit() -> int:
    try:
        return max(1, min(500, int(os.environ.get("REZE_BROADCAST_MAX", BROADCAST_DEFAULT_MAX))))
    except ValueError:
        return BROADCAST_DEFAULT_MAX


async def broadcast_targets(client, scope: str, limit: int):
    """Chats that may receive a broadcast: never bots, deleted accounts, channels or Saved Messages."""
    targets = []
    me = await client.get_me()
    async for dialog in client.iter_dialogs(limit=2000):
        entity = getattr(dialog, "entity", None)
        if dialog.id == getattr(me, "id", None):
            continue
        if dialog.is_user:
            if scope not in ("users", "all") or getattr(entity, "bot", False) or getattr(entity, "deleted", False):
                continue
        elif dialog.is_group:
            if scope not in ("groups", "all"):
                continue
        else:
            continue  # broadcast channels: you cannot post there as a member
        targets.append(dialog.id)
        if len(targets) >= limit:
            break
    return targets


@router.register(
    name="broadcast", category=CATEGORY, owner_only=True, aliases=["bc"], cooldown=10,
    description="Send a message to many chats (confirmation code + rate limit).",
    usage=".broadcast <groups|users|all> <text>   then   .broadcast confirm <code>",
    examples=[".broadcast groups Server maintenance at 22:00"],
)
async def broadcast_cmd(ctx: CommandContext):
    args = ctx.args
    if args and args[0].lower() == "confirm":
        return await _broadcast_confirm(ctx, args[1] if len(args) > 1 else "")

    if not args or args[0].lower() not in ("groups", "users", "all"):
        return await ctx.reply_usage("Scope must be groups, users or all.")
    scope = args[0].lower()
    text = " ".join(args[1:]).strip()
    reply = await ctx.get_reply_message()
    if not text and reply is None:
        return await ctx.reply_usage("Write the text, or reply to the message to copy.")
    if text and len(text) > BROADCAST_TEXT_LIMIT:
        return await ctx.reply(ascii.error("Text too long", [f"Max {BROADCAST_TEXT_LIMIT} characters; reply to a message instead."]))

    targets = await broadcast_targets(ctx.client, scope, broadcast_limit())
    if not targets:
        return await ctx.reply(ascii.warning("No recipients", ["No matching chats were found."]))

    payload = json.dumps({"scope": scope, "text": text, "reply": getattr(reply, "id", None)})
    token = _confirmations.issue("broadcast", ctx.chat_id, ctx.sender_id, payload=payload)
    preview = text[:120] if text else "(copy of the replied message)"
    return await ctx.reply(ascii.warning("Confirm broadcast", [
        f"Recipients: {len(targets)} ({scope}, max {broadcast_limit()})",
        f"Message: {preview}",
        "Messages are sent slowly (about 2s apart) to protect your account.",
        f"Confirm within 2 minutes: .broadcast confirm {token}",
    ]))


async def _broadcast_confirm(ctx: CommandContext, token: str):
    from telethon import errors

    if not token:
        return await ctx.reply_usage("Example: .broadcast confirm AB12CD34")
    try:
        confirmation = _confirmations.consume(token, "broadcast", ctx.chat_id, ctx.sender_id)
    except ConfirmationError as exc:
        return await ctx.reply(ascii.error("Not confirmed", [str(exc)]))
    data = json.loads(confirmation.payload)

    source = None
    if data.get("reply"):
        source = await ctx.client.get_messages(ctx.chat_id, ids=data["reply"])
    content = source if source is not None else data["text"]
    targets = await broadcast_targets(ctx.client, data["scope"], broadcast_limit())

    progress = await ctx.reply(ascii.loading("Broadcast started", [f"0/{len(targets)} sent"]))
    sent = failed = 0
    aborted = ""
    for index, chat in enumerate(targets, 1):
        try:
            await ctx.client.send_message(chat, content)
            sent += 1
        except errors.FloodWaitError as exc:
            wait = int(getattr(exc, "seconds", 0) or 0)
            if wait > 60:
                aborted = f"Stopped: Telegram asked to wait {wait}s."
                break
            await _sleep(wait + 1)
            failed += 1
        except Exception as exc:  # noqa: BLE001 - one bad chat must not stop the run
            failed += 1
            logger.debug("Broadcast to %s failed: %s", chat, exc)
        if index % 10 == 0 and progress is not None:
            try:
                await progress.edit(ascii.loading("Broadcast running", [f"{index}/{len(targets)} processed"]))
            except Exception:  # noqa: BLE001
                pass
        await _sleep(random.uniform(1.5, 3.0))

    lines = [f"Sent: {sent}", f"Failed: {failed}", f"Total: {len(targets)}"]
    if aborted:
        lines.append(aborted)
    return await ctx.reply(ascii.success("Broadcast finished", lines) if not aborted else ascii.warning("Broadcast stopped", lines))


# ------------------------------------------------------------------------ update
@router.register(
    name="update", category=CATEGORY, owner_only=True, cooldown=5,
    description="Check for updates (git) and apply them with `.update now`.",
    usage=".update [now]",
)
async def update_cmd(ctx: CommandContext):
    if not os.path.isdir(os.path.join(REPO_ROOT, ".git")):
        return await ctx.reply(ascii.warning("Not a git checkout", [
            "Updates are applied with git.",
            "Docker/PaaS: pull the new image or redeploy the repository instead."]))

    apply_now = bool(ctx.args and ctx.args[0].lower() in ("now", "apply", "yes"))
    fetch = await shell.run("git fetch --quiet", timeout=60, cwd=REPO_ROOT)
    if fetch.code != 0:
        return await ctx.reply(ascii.error("Fetch failed", fetch.output.splitlines()[-3:] or ["git fetch failed."]))

    behind = await shell.run("git rev-list --count HEAD..@{u}", timeout=20, cwd=REPO_ROOT)
    if behind.code != 0:
        return await ctx.reply(ascii.error("No upstream", ["This branch does not track a remote branch."]))
    count = int((behind.output or "0").strip() or 0)
    if count == 0:
        return await ctx.reply(ascii.success("Up to date", [f"Version {__version__}"]))

    log = await shell.run("git log --oneline -n 8 HEAD..@{u}", timeout=20, cwd=REPO_ROOT)
    if not apply_now:
        return await ctx.reply(ascii.info("Update available", [f"{count} new commit(s):", *log.output.splitlines(), "",
                                                              "Apply with: .update now"]))

    pull = await shell.run("git pull --ff-only", timeout=120, cwd=REPO_ROOT)
    if pull.code != 0:
        return await ctx.reply(ascii.error("Update failed", pull.output.splitlines()[-4:] or ["git pull failed."]))
    deps = await shell.run(f'"{sys.executable}" -m pip install -q -r requirements.txt', timeout=300, cwd=REPO_ROOT)
    lines = [f"Pulled {count} commit(s)."]
    lines.append("Dependencies updated." if deps.code == 0 else "Dependency install failed; run pip manually.")
    lines.append("Restart to load the new code: .restart")
    return await ctx.reply(ascii.success("Updated", lines))
