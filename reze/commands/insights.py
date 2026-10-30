"""Insight Engine: local weekly statistics with an optional AI narrative."""

from reze.ai import ai_gateway
from reze.ai.budget import BudgetExceeded
from reze.command_router import CommandContext, router
from reze.exceptions import AIError
from reze.features import require
from reze.personal.insights import narrative, snapshot
from reze.ui import ascii

CATEGORY = "AI"


@router.register(
    name="insights",
    category=CATEGORY,
    description="Show local weekly statistics; optionally ask the AI for a narrative.",
    usage=".insights [days] | .insights ai [days]",
    owner_only=True,
    examples=[".insights", ".insights 30", ".insights ai 7"],
)
async def insights_cmd(ctx: CommandContext):
    hint = require("insights")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))

    want_ai = bool(ctx.args and ctx.args[0].lower() in {"ai", "narrative"})
    days_arg = ctx.args[1] if want_ai and len(ctx.args) > 1 else (ctx.args[0] if ctx.args else "7")
    days = int(days_arg) if str(days_arg).isdigit() else 7
    data = snapshot(days=days)
    lines = narrative(data)

    if not want_ai:
        lines.append("")
        lines.append("AI narrative: .insights ai 7 (uses the configured provider)")
        return await ctx.reply(ascii.section("Insights", lines))

    status = ai_gateway.status()
    if not status.get("configured"):
        return await ctx.reply(
            ascii.warning(
                "AI is not configured",
                [
                    "Local statistics above are available without AI.",
                    "Set REZE_AI_PROVIDER and REZE_AI_API_KEY to add a narrative.",
                ],
            )
        )
    prompt = (
        "Here are factual local statistics from the user's own assistant. "
        "Write a short, neutral weekly review in at most 120 words. "
        "Do not invent numbers or events. Do not give medical or financial advice.\n\n"
        + "\n".join(lines)
    )
    try:
        result = await ai_gateway.complete(prompt, system="You summarize statistics faithfully.")
    except BudgetExceeded as exc:
        return await ctx.reply(ascii.warning("AI budget", [str(exc)]))
    except AIError as exc:
        return await ctx.reply(ascii.warning("AI unavailable", [str(exc)]))
    lines.extend(["", "AI narrative:", result.text, "", result.metadata_line()])
    return await ctx.reply(ascii.section("Insights", lines))
