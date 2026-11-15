"""``.consent`` command (owner only): see and change consent for sharing data with other services."""

from __future__ import annotations

from typing import Any, List

from reze import consent
from reze.command_router import router
from reze.permissions import PermissionManager
from reze.ui import ascii


async def _list(ctx, args: List[str]) -> Any:
    lines = []
    for row in consent.status():
        state = "granted" if row["granted"] else "not granted"
        lines.append(f"{row['scope']}: {state}")
        lines.append(f"  {row['label_en']}")
    return await ctx.reply(ascii.section("Consent", lines))


async def _change(ctx, args: List[str], grant: bool) -> Any:
    if len(args) < 1:
        return await ctx.reply_usage("Example: .consent grant watchdog.channel_posts")
    scope = args[0]
    if grant:
        consent.grant(scope)
        return await ctx.reply(ascii.success("Consent granted", [scope]))
    consent.revoke(scope)
    return await ctx.reply(ascii.success("Consent revoked", [scope]))


HANDLERS = {"list": _list, "grant": lambda c, a: _change(c, a, True), "revoke": lambda c, a: _change(c, a, False)}


@router.register(
    name="consent",
    category="Privacy",
    description="See and change consent for sharing data with other services (owner).",
    usage=".consent [grant|revoke <scope>]",
    owner_only=True,
    examples=[".consent", ".consent grant watchdog.channel_posts"],
)
async def consent_cmd(ctx):
    if not PermissionManager.is_owner(ctx.sender_id):
        return await ctx.reply(ascii.warning("Owner only", ["Consent is owner-only."]))
    action = ctx.args[0].lower() if ctx.args else "list"
    handler = HANDLERS.get(action)
    if handler is None:
        return await ctx.reply(ascii.section("Consent commands", [".consent", ".consent grant <scope>", ".consent revoke <scope>"]))
    try:
        return await handler(ctx, ctx.args[1:])
    except consent.ConsentError as exc:
        return await ctx.reply(ascii.warning("Unknown scope", [str(exc)]))


__all__ = ["HANDLERS", "consent_cmd"]
