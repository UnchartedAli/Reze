"""Decision journal: log a decision, record the choice and review the outcome."""

from reze.command_router import CommandContext, router
from reze.features import require
from reze.personal.decisions import decision_service
from reze.ui import ascii

CATEGORY = "Personal"


@router.register(
    name="decide",
    category=CATEGORY,
    description="Record decisions, expected outcomes and later reviews.",
    usage=".decide [list|add <title> | <options> | <expected> | <review-days>|choose <id> <choice>|review <id> <outcome>|due]",
    aliases=["decision"],
    owner_only=True,
    examples=[
        ".decide add Move to a new VPS | stay or move | lower latency | 14",
        ".decide choose 1 Move to Hetzner",
        ".decide review 1 Latency dropped by half",
    ],
)
async def decide_cmd(ctx: CommandContext):
    hint = require("decisions")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = (ctx.args[0].lower() if ctx.args else "list")

    if action == "list":
        rows = decision_service.list(limit=20)
        if not rows:
            return await ctx.reply(
                ascii.info("Decision journal is empty", ["Add one: .decide add <title>"])
            )
        lines = []
        for row in rows:
            review = f" · review {row['review_at'][:10]}" if row.get("review_at") else ""
            lines.append(f"#{row['id']} [{row['status']}] {row['title'][:70]}{review}")
        return await ctx.reply(ascii.section("Decisions", lines))

    if action == "add":
        raw = ctx.args_text[len(ctx.args[0]):].strip()
        parts = [part.strip() for part in raw.split("|")]
        if not parts or not parts[0]:
            return await ctx.reply_usage("Example: .decide add Move to a new VPS | stay or move | lower latency | 14")
        review_days = 0
        if len(parts) >= 4 and parts[3].isdigit():
            review_days = int(parts[3])
        decision_id = decision_service.log(
            parts[0],
            options=parts[1] if len(parts) > 1 else "",
            expected=parts[2] if len(parts) > 2 else "",
            review_in_days=review_days,
        )
        return await ctx.reply(
            ascii.success(
                "Decision recorded",
                [
                    f"ID: {decision_id}",
                    f"Title: {parts[0]}",
                    f"Review in: {review_days} days" if review_days else "No review scheduled",
                ],
            )
        )

    if action == "choose":
        if len(ctx.args) < 3 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .decide choose 1 Move to Hetzner")
        choice = " ".join(ctx.args[2:])
        if not decision_service.decide(int(ctx.args[1]), choice):
            return await ctx.reply(ascii.warning("Not found", ["No decision with that ID."]))
        return await ctx.reply(
            ascii.success("Choice recorded", [f"ID: {ctx.args[1]}", f"Choice: {choice}"])
        )

    if action == "review":
        if len(ctx.args) < 3 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .decide review 1 Latency dropped by half")
        outcome = " ".join(ctx.args[2:])
        if not decision_service.review(int(ctx.args[1]), outcome):
            return await ctx.reply(ascii.warning("Not found", ["No decision with that ID."]))
        return await ctx.reply(
            ascii.success("Review saved", [f"ID: {ctx.args[1]}", f"Outcome: {outcome}"])
        )

    if action == "due":
        rows = decision_service.due_reviews()
        if not rows:
            return await ctx.reply(ascii.info("Nothing due", ["No decision review is due."]))
        lines = [
            f"#{row['id']} {row['title'][:60]} · due {row['review_at'][:10]}" for row in rows
        ]
        return await ctx.reply(ascii.section("Reviews due", lines))

    return await ctx.reply_usage("Subcommands: list, add, choose, review, due.")
