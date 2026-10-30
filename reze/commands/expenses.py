"""Local expense tracking."""

from reze.command_router import CommandContext, router
from reze.features import require
from reze.personal.expenses import expense_service
from reze.ui import ascii

CATEGORY = "Productivity"


@router.register(
    name="expense",
    category=CATEGORY,
    description="Record expenses and read monthly summaries locally.",
    usage=".expense [list [YYYY-MM]|add <amount> [category] [note]|summary [YYYY-MM]|delete <id>]",
    aliases=["expenses"],
    owner_only=True,
    examples=[".expense add 250000 food lunch", ".expense summary", ".expense list 2026-10"],
)
async def expense_cmd(ctx: CommandContext):
    hint = require("expenses")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = (ctx.args[0].lower() if ctx.args else "summary")

    if action == "add":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .expense add 250000 food lunch")
        try:
            amount = float(ctx.args[1].replace(",", ""))
        except ValueError:
            return await ctx.reply_usage("The amount must be a number, for example 250000.")
        category = ctx.args[2] if len(ctx.args) > 2 else "general"
        note = " ".join(ctx.args[3:])
        expense_id = expense_service.add(amount, category=category, note=note)
        return await ctx.reply(
            ascii.success(
                "Expense recorded",
                [f"ID: {expense_id}", f"Amount: {amount:g} IRT", f"Category: {category}"],
            )
        )

    if action == "list":
        month = ctx.args[1] if len(ctx.args) > 1 else ""
        rows = expense_service.list(month=month)
        if not rows:
            return await ctx.reply(ascii.info("No expenses", ["Nothing recorded for that month."]))
        lines = [
            f"#{row['id']} {row['spent_on']} {row['amount']:g} {row['currency']} [{row['category']}] {row['note'][:40]}"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Expenses", lines))

    if action == "summary":
        month = ctx.args[1] if len(ctx.args) > 1 else ""
        summary = expense_service.summary(month=month)
        lines = [f"Month: {summary['month']}", f"Entries: {summary['count']}"]
        for row in summary["by_category"]:
            lines.append(
                f"{row['category']}: {float(row['total']):g} {row['currency']} ({row['count']})"
            )
        if summary["totals"]:
            totals = ", ".join(f"{value:g} {currency}" for currency, value in summary["totals"].items())
            lines.append(f"Total: {totals}")
        return await ctx.reply(ascii.section("Expense summary", lines))

    if action == "delete":
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .expense delete 4")
        if not expense_service.delete(int(ctx.args[1])):
            return await ctx.reply(ascii.warning("Not found", ["No expense with that ID."]))
        return await ctx.reply(ascii.success("Expense deleted", [f"ID: {ctx.args[1]}"]))

    return await ctx.reply_usage("Subcommands: add, list, summary, delete.")
