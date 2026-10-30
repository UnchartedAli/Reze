"""
Presence commands.

``.setonlinepermanently`` keeps the account showing as online while Reze is
running by refreshing ``account.updateStatus(offline=False)`` on an interval.
It is an opt-in account preference, stored in SQLite, and off by default.
"""

from reze.command_router import CommandContext, router
from reze.core.presence import presence_service
from reze.ui import ascii

import time

CATEGORY = "Profile"

_ON_VALUES = {"on", "enable", "enabled", "1", "true", "yes"}
_OFF_VALUES = {"off", "disable", "disabled", "0", "false", "no"}
_STATUS_VALUES = {"", "status", "state", "show"}


def _state_lines() -> list:
    status = presence_service.status()
    lines = [
        f"Option: {'ENABLED' if status['enabled'] else 'DISABLED'}",
        f"Refresh interval: {status['interval']}s",
        f"Status refreshes: {status['applied_count']}",
    ]
    if status["last_applied"]:
        ago = int(time.time() - status["last_applied"])
        lines.append(f"Last refresh: {ago}s ago")
    if not status["running"]:
        lines.append("Service loop: not running (starts with the application)")
    if status["last_error"]:
        lines.append(f"Last error: {status['last_error']}")
    if status["cooldown_remaining"]:
        lines.append(f"Telegram cooldown: {status['cooldown_remaining']}s remaining")
    lines.append("")
    lines.append("Works while Reze is running and the account is connected.")
    lines.append("Privacy settings still decide who can see your online status.")
    return lines


@router.register(
    name="setonlinepermanently",
    category=CATEGORY,
    description="Keep the account appearing online while Reze runs.",
    usage=".setonlinepermanently <on|off|status>",
    owner_only=True,
    cooldown=2,
    aliases=["alwaysonline", "onlineforever"],
    examples=[".setonlinepermanently on", ".setonlinepermanently off"],
)
async def setonlinepermanently_cmd(ctx: CommandContext):
    action = ctx.args[0].lower() if ctx.args else ""

    if action in _STATUS_VALUES:
        return await ctx.reply(
            ascii.frame(
                "Always online",
                _state_lines(),
                footer="Disable with .setonlinepermanently off",
            )
        )

    if action in _ON_VALUES:
        presence_service.set_enabled(True)
        applied = await presence_service.apply_now(ctx.client)
        lines = _state_lines()
        if not applied:
            lines.insert(0, "Saved. The status will refresh once Telegram is connected.")
        return await ctx.reply(
            ascii.success("Always online enabled", lines, footer="REZE 3.0 presence service")
        )

    if action in _OFF_VALUES:
        presence_service.set_enabled(False)
        return await ctx.reply(
            ascii.info(
                "Always online disabled",
                [
                    "Reze no longer refreshes your online status.",
                    "Normal Telegram presence rules apply again.",
                ],
            )
        )

    return await ctx.reply_usage(
        "Example: .setonlinepermanently on  (use off to stop, status to inspect)"
    )
