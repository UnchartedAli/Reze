"""Optional Bot Companion status and configuration hints."""

from reze.command_router import CommandContext, router
from reze.core.companion import companion_service
from reze.features import require
from reze.ui import ascii

CATEGORY = "Settings"


@router.register(
    name="companion",
    category=CATEGORY,
    description="Show the owner-only Telegram Bot Companion status.",
    usage=".companion",
    owner_only=True,
    examples=[".companion", ".features enable bot_companion confirm"],
)
async def companion_cmd(ctx: CommandContext):
    hint = require("bot_companion")
    configured = companion_service.configured()
    lines = [
        f"Feature: {'ON' if not hint else 'OFF (default)'}",
        f"Bot token configured: {'yes' if configured else 'no'}",
        f"Service state: {companion_service.status}",
        "",
        "The companion is a separate Bot API bot that answers only the owner.",
        "It shows a settings menu and never sends prompts, secrets or transcripts.",
        "Sensitive features always require the typed 'confirm' word.",
    ]
    if companion_service.error:
        lines.append(f"Last error: {companion_service.error}")
    if hint:
        lines.append("")
        lines.append(hint)
    if not configured:
        lines.append("Set REZE_COMPANION_TOKEN (from @BotFather) and REZE_OWNER_ID, then restart.")
    return await ctx.reply(ascii.section("Bot Companion", lines))
