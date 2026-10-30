"""
Mention & keyword alerts.

    .alerts on | off | status | list
    .alerts mentions on|off          alert when someone mentions or replies to you
    .alerts add <word or phrase>     alert on a keyword (case-insensitive)
    .alerts del <word or phrase>
    .alerts ignore [chat_id]         never alert for this chat   (.alerts unignore to undo)
    .alerts dest me|here|<chat_id>   where alerts go (default: Saved Messages)
"""

from reze.command_router import CommandContext, router
from reze.modules.alerts import alert_service as alerts
from reze.ui import ascii

CATEGORY = "Guard"
_TRUE, _FALSE = {"on", "1", "yes", "true"}, {"off", "0", "no", "false"}


def _flag(value: bool) -> str:
    return "ON" if value else "OFF"


def _chat(ctx: CommandContext):
    if len(ctx.args) > 1 and ctx.args[1].lstrip("-").isdigit():
        return int(ctx.args[1])
    return ctx.chat_id if len(ctx.args) <= 1 else None


@router.register(
    name="alerts", category=CATEGORY, owner_only=True, aliases=["alert"],
    description="Send group mentions and keyword matches to Saved Messages.",
    usage=".alerts <on|off|status|list|mentions|add|del|ignore|unignore|dest>",
    examples=[".alerts on", ".alerts add deploy", ".alerts ignore"],
)
async def alerts_cmd(ctx: CommandContext):
    action = ctx.args[0].lower() if ctx.args else "status"
    cfg = alerts.config

    if action in ("status", "show", "list"):
        dest = "Saved Messages" if cfg["dest"] == "me" else str(cfg["dest"])
        lines = [f"Alerts: {_flag(cfg['enabled'])}", f"Mentions & replies: {_flag(cfg['mentions'])}",
                 f"Deliver to: {dest}", f"Muted chats: {len(cfg['ignore'])}", f"Keywords ({len(cfg['keywords'])}):"]
        lines += [f"  - {k}" for k in cfg["keywords"][:20]] or ["  (none)"]
        lines.append(f"This session: {alerts.stats['sent']} sent")
        return await ctx.reply(ascii.frame("Alerts", lines))

    if action in _TRUE | _FALSE:
        alerts.update(enabled=action in _TRUE)
        return await ctx.reply(ascii.success(f"Alerts {_flag(action in _TRUE)}", [
            "Alerts only cover groups; private chats already notify you." if action in _TRUE else "No alerts will be sent."]))

    if action == "mentions":
        value = ctx.args[1].lower() if len(ctx.args) > 1 else ""
        if value not in _TRUE | _FALSE:
            return await ctx.reply_usage(".alerts mentions on|off")
        alerts.update(mentions=value in _TRUE)
        return await ctx.reply(ascii.success("Mention alerts", [f"Now {_flag(value in _TRUE)}."]))

    if action == "add":
        word = ctx.args_text[len(ctx.args[0]):].strip()
        if not word:
            return await ctx.reply_usage(".alerts add <word or phrase>")
        try:
            added = alerts.add_keyword(word)
        except ValueError as exc:
            return await ctx.reply(ascii.error("Keyword rejected", [str(exc)]))
        return await ctx.reply(ascii.success("Keyword added" if added else "Already there", [word[:60]]))

    if action in ("del", "remove", "rm"):
        word = ctx.args_text[len(ctx.args[0]):].strip()
        if not word:
            return await ctx.reply_usage(".alerts del <word or phrase>")
        removed = alerts.remove_keyword(word)
        return await ctx.reply(ascii.success("Keyword removed", [word[:60]]) if removed
                               else ascii.warning("Not found", [f"'{word[:40]}' is not a keyword."]))

    if action in ("ignore", "unignore"):
        chat_id = _chat(ctx)
        if chat_id is None:
            return await ctx.reply_usage(f".alerts {action} [chat_id]")
        changed = alerts.toggle_ignore(chat_id, action == "ignore")
        verb = "muted" if action == "ignore" else "unmuted"
        return await ctx.reply(ascii.success(f"Chat {verb}", [str(chat_id)]) if changed
                               else ascii.warning("No change", [f"Chat {chat_id} was already {verb}."]))

    if action == "dest":
        target = ctx.args[1].lower() if len(ctx.args) > 1 else ""
        if target in ("me", "saved", "self"):
            dest = "me"
        elif target == "here":
            dest = str(ctx.chat_id)
        elif target.lstrip("-").isdigit():
            dest = target
        else:
            return await ctx.reply_usage(".alerts dest me|here|<chat_id>")
        alerts.update(dest=dest)
        return await ctx.reply(ascii.success("Destination set", ["Saved Messages" if dest == "me" else dest]))

    return await ctx.reply_usage()
