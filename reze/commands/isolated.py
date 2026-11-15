"""``.isolated`` command (owner only, feature OFF by default): manage isolated plugins from chat."""

from __future__ import annotations

from typing import Any, List

from reze.command_router import router
from reze.features import require
from reze.permissions import PermissionManager
from reze.sandbox import service
from reze.sandbox.isolation import IsolationError
from reze.ui import ascii

CATEGORY = "Plugins"
HELP_LINES = [
    ".isolated list — plugin files and their status",
    ".isolated load <name> — start a plugin in its own process",
    ".isolated unload <name> — stop it and remove its commands",
    ".isolated approve <name> — approve the file as it is on disk (review it first)",
]


async def _list(ctx, args: List[str]) -> Any:
    names = service.list_plugin_names()
    if not names:
        return await ctx.reply(
            ascii.info("Isolated plugins", [f"No files in {service.isolated_dir()}."])
        )
    lines = [f"{name}: {service.plugin_status(name)}" for name in names]
    return await ctx.reply(ascii.section("Isolated plugins", lines))


async def _load(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .isolated load word_count")
    name = args[0]
    path = service.resolve_plugin_path(name)
    commands = await service.isolated_host.load(name, path)
    return await ctx.reply(
        ascii.success("Plugin loaded", [f"{name} runs in its own process.", "Commands: " + ", ".join(f".{c}" for c in commands)])
    )


async def _unload(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .isolated unload word_count")
    removed = await service.isolated_host.unload(args[0])
    if not removed:
        return await ctx.reply(ascii.info("Not loaded", [args[0]]))
    return await ctx.reply(ascii.success("Plugin unloaded", [args[0]]))


async def _approve(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .isolated approve word_count")
    name = args[0]
    path = service.resolve_plugin_path(name)
    digest = service.isolated_host.approve(name, path)
    return await ctx.reply(
        ascii.success("Approved", [f"{name}: sha256 {digest[:16]}…", "Load it again with .isolated load " + name])
    )


HANDLERS = {"list": _list, "load": _load, "unload": _unload, "approve": _approve}


@router.register(
    name="isolated",
    category=CATEGORY,
    description="Load, unload and approve isolated plugins (owner). Each runs in its own process.",
    usage=".isolated [list|load|unload|approve] [name]",
    owner_only=True,
    examples=[".isolated list", ".isolated load word_count"],
)
async def isolated_cmd(ctx):
    if not PermissionManager.is_owner(ctx.sender_id):
        return await ctx.reply(ascii.warning("Owner only", ["Isolated plugins are owner-only."]))
    hint = require("isolated_plugins")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = ctx.args[0].lower() if ctx.args else "list"
    handler = HANDLERS.get(action)
    if handler is None:
        return await ctx.reply(ascii.section("Isolated plugin commands", HELP_LINES))
    try:
        return await handler(ctx, ctx.args[1:])
    except (ValueError, IsolationError) as exc:
        return await ctx.reply(ascii.warning("Not done", [str(exc)[:300]]))


__all__ = ["HANDLERS", "isolated_cmd"]
