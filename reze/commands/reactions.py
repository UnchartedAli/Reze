"""Random-reaction configuration (the feature itself is OFF by default)."""

from reze.command_router import CommandContext, router
from reze.features import require
from reze.modules.reactions import MAX_PROBABILITY, random_reaction_service
from reze.ui import ascii

CATEGORY = "Automation"


@router.register(
    name="reactions",
    category=CATEGORY,
    description="Configure rare emoji reactions in chats you list (feature OFF by default).",
    usage=".reactions [status|add <chat_id> [percent]|remove <chat_id>|emoji <a,b,c>|clear]",
    owner_only=True,
    examples=[".reactions status", ".reactions add -1001234567890 10", ".reactions emoji 👍,🔥"],
)
async def reactions_cmd(ctx: CommandContext):
    hint = require("random_reactions")
    action = (ctx.args[0].lower() if ctx.args else "status")

    if action == "status":
        report = random_reaction_service.status_report()
        lines = [
            f"Feature: {'ON' if report['enabled'] else 'OFF'}",
            f"Emoji: {' '.join(report['emoji'])}",
            f"Limits: {report['limits']}",
            "Chats:",
        ]
        if report["chats"]:
            lines.extend(
                f"  {chat_id}: {round(probability * 100, 1)}%"
                for chat_id, probability in report["chats"].items()
            )
        else:
            lines.append("  none — add one with .reactions add <chat_id> 10")
        if hint:
            lines.append("")
            lines.append(hint)
        return await ctx.reply(ascii.section("Random reactions", lines))

    if action == "add":
        if len(ctx.args) < 2 or not ctx.args[1].lstrip("-").isdigit():
            return await ctx.reply_usage("Example: .reactions add -1001234567890 10")
        percent = 10.0
        if len(ctx.args) > 2:
            try:
                percent = float(ctx.args[2].rstrip("%"))
            except ValueError:
                return await ctx.reply_usage("Probability is a percent between 1 and 25.")
        probability = random_reaction_service.add_chat(int(ctx.args[1]), percent / 100)
        lines = [
            f"Chat: {ctx.args[1]}",
            f"Probability: {round(probability * 100, 1)}% (max {int(MAX_PROBABILITY * 100)}%)",
            "Reactions only; no messages are sent.",
        ]
        if hint:
            lines.append(hint)
        return await ctx.reply(ascii.success("Chat added", lines))

    if action == "remove":
        if len(ctx.args) < 2 or not ctx.args[1].lstrip("-").isdigit():
            return await ctx.reply_usage("Example: .reactions remove -1001234567890")
        removed = random_reaction_service.remove_chat(int(ctx.args[1]))
        if not removed:
            return await ctx.reply(ascii.warning("Not found", ["That chat is not configured."]))
        return await ctx.reply(ascii.success("Chat removed", [f"Chat: {ctx.args[1]}"]))

    if action == "emoji":
        raw = ctx.args_text[len(ctx.args[0]):].strip()
        items = [item for item in raw.replace(" ", ",").split(",") if item]
        if not items:
            return await ctx.reply_usage("Example: .reactions emoji 👍,🔥,✨")
        emoji = random_reaction_service.set_emoji(items)
        return await ctx.reply(ascii.success("Emoji updated", [" ".join(emoji)]))

    if action == "clear":
        count = random_reaction_service.clear()
        return await ctx.reply(ascii.success("Reaction chats cleared", [f"Removed: {count}"]))

    return await ctx.reply_usage("Subcommands: status, add, remove, emoji, clear.")
