"""
Moderation commands: warnings, rules, greetings, notes, filters and blacklists.
"""

from reze.command_router import CommandContext, router
from reze.database import db
from reze.ui import ascii

CATEGORY = "Moderation"


@router.register(name="warn", category=CATEGORY, description="Warn a member and count it toward the limit.", usage=".warn [reason] (reply or id)", admin_only=True, group_only=True)
async def warn_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply(ascii.warning("No target", ["Reply to a member or pass their numeric id."]))
    reason = ctx.args_text.strip() or "no reason given"
    count = db.add_warning(ctx.chat_id, target_id, ctx.sender_id, reason)
    lines = [f"User: {target_id}", f"Warnings: {count}/3", f"Reason: {reason}"]
    if count >= 3:
        lines.append("The warning limit was reached; consider muting or banning.")
    return await ctx.reply(ascii.warning("Warning issued", lines))


@router.register(name="unwarn", category=CATEGORY, description="Remove one warning from a member.", usage=".unwarn (reply or id)", admin_only=True, group_only=True)
async def unwarn_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply(ascii.warning("No target", ["Reply to a member or pass their numeric id."]))
    count = db.remove_warning(ctx.chat_id, target_id)
    return await ctx.reply(ascii.info("Warning removed", [f"User: {target_id}", f"Remaining: {count}"]))


@router.register(name="warns", category=CATEGORY, description="Show a member's warning count.", usage=".warns (reply or id)", group_only=True)
async def warns_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id() or ctx.sender_id
    count = db.get_warnings_count(ctx.chat_id, target_id)
    return await ctx.reply(ascii.info("Warnings", [f"User: {target_id}", f"Active warnings: {count}"]))


@router.register(name="resetwarns", category=CATEGORY, description="Clear every warning for a member.", usage=".resetwarns (reply or id)", admin_only=True, group_only=True)
async def resetwarns_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id()
    if not target_id:
        return await ctx.reply(ascii.warning("No target", ["Reply to a member or pass their numeric id."]))
    db.reset_warnings(ctx.chat_id, target_id)
    return await ctx.reply(ascii.success("Warnings cleared", [f"User: {target_id}"]))


@router.register(name="rules", category=CATEGORY, description="Show the group rules.", usage=".rules", group_only=True)
async def rules_cmd(ctx: CommandContext):
    config = db.get_group_settings(ctx.chat_id)
    rules = config.get("rules") or "No rules have been configured for this group yet."
    return await ctx.reply(ascii.frame("Group rules", [rules]))


@router.register(name="setrules", category=CATEGORY, description="Set the group rules text.", usage=".setrules <text>", admin_only=True, group_only=True)
async def setrules_cmd(ctx: CommandContext):
    if not ctx.args_text.strip():
        return await ctx.reply_usage("Example: .setrules Be respectful and stay on topic.")
    db.update_group_settings(ctx.chat_id, rules=ctx.args_text.strip())
    return await ctx.reply(ascii.success("Rules updated"))


@router.register(name="welcome", category=CATEGORY, description="Enable or disable welcome messages.", usage=".welcome on|off", admin_only=True, group_only=True)
async def welcome_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply_usage("Example: .welcome on")
    enabled = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, welcome_enabled=enabled)
    return await ctx.reply(ascii.info("Welcome messages", ["enabled" if enabled else "disabled"]))


@router.register(name="setwelcome", category=CATEGORY, description="Set the welcome message template.", usage=".setwelcome <text with {mention} and {title}>", admin_only=True, group_only=True)
async def setwelcome_cmd(ctx: CommandContext):
    if not ctx.args_text.strip():
        return await ctx.reply_usage("Example: .setwelcome Welcome {mention} to {title}!")
    db.update_group_settings(ctx.chat_id, welcome_text=ctx.args_text.strip())
    return await ctx.reply(ascii.success("Welcome template saved"))


@router.register(name="goodbye", category=CATEGORY, description="Enable or disable goodbye messages.", usage=".goodbye on|off", admin_only=True, group_only=True)
async def goodbye_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply_usage("Example: .goodbye on")
    enabled = 1 if ctx.args[0].lower() == "on" else 0
    db.update_group_settings(ctx.chat_id, goodbye_enabled=enabled)
    return await ctx.reply(ascii.info("Goodbye messages", ["enabled" if enabled else "disabled"]))


@router.register(name="filter", category=CATEGORY, description="Manage automatic keyword replies.", usage=".filter add|remove|list ...", admin_only=True, group_only=True)
async def filter_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage(".filter add <keyword> <reply> | .filter remove <keyword> | .filter list")
    action = ctx.args[0].lower()

    if action == "add" and len(ctx.args) >= 3:
        keyword = ctx.args[1]
        reply_text = " ".join(ctx.args[2:])
        db.set_filter(ctx.chat_id, keyword, reply_text)
        return await ctx.reply(ascii.success("Filter saved", [f"Keyword: {keyword}"]))

    if action == "remove" and len(ctx.args) >= 2:
        removed = db.remove_filter(ctx.chat_id, ctx.args[1])
        return await ctx.reply(
            ascii.info("Filters", ["Filter removed." if removed else "No such filter."])
        )

    if action == "list":
        filters = db.get_filters(ctx.chat_id)
        if not filters:
            return await ctx.reply(ascii.info("Filters", ["No filters configured."]))
        lines = [f"{entry['keyword']} -> {entry['reply_text']}" for entry in filters]
        return await ctx.reply(ascii.section(f"Filters ({len(filters)})", lines))

    return await ctx.reply_usage("Actions: add, remove, list")


@router.register(name="blacklist", category=CATEGORY, description="Manage forbidden words.", usage=".blacklist add|remove|list ...", admin_only=True, group_only=True)
async def blacklist_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage(".blacklist add <word> | .blacklist remove <word> | .blacklist list")
    action = ctx.args[0].lower()

    if action == "add" and len(ctx.args) >= 2:
        db.add_blacklist(ctx.chat_id, ctx.args[1])
        return await ctx.reply(ascii.success("Word blocked", [ctx.args[1]]))

    if action == "remove" and len(ctx.args) >= 2:
        removed = db.remove_blacklist(ctx.chat_id, ctx.args[1])
        return await ctx.reply(
            ascii.info("Blacklist", ["Word removed." if removed else "The word was not blocked."])
        )

    if action == "list":
        words = db.get_blacklists(ctx.chat_id)
        if not words:
            return await ctx.reply(ascii.info("Blacklist", ["The blacklist is empty."]))
        return await ctx.reply(
            ascii.section("Blocked words", [entry["trigger"] for entry in words])
        )

    return await ctx.reply_usage("Actions: add, remove, list")
