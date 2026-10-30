"""
AFK commands.

    .afk [30m|2h|1d] [reason]    go away (optionally for a limited time)
    .afk text <message>          your own auto-reply text
    .afk autooff on|off          end AFK automatically when you write in a chat
    .afk status                  current state
    .back  (or .afk off)         come back and get the summary of what you missed
"""

from reze.command_router import CommandContext, router
from reze.modules.afk import afk_service as afk, human_duration, parse_duration
from reze.ui import ascii

CATEGORY = "Presence"


def _status_lines():
    state = afk.state
    if not afk.active:
        return ["AFK: OFF", f"Auto-off on activity: {'ON' if state.get('auto_off') else 'OFF'}"]
    lines = ["AFK: ON", f"Since: {human_duration(afk._clock() - state['since'])} ago"]
    if state.get("until"):
        lines.append(f"Ends in: {human_duration(state['until'] - afk._clock())}")
    lines.append(f"Reply: {afk.reply_text()[:120]}")
    lines.append(f"Auto-off on activity: {'ON' if state.get('auto_off') else 'OFF'}")
    return lines


async def _come_back(ctx: CommandContext):
    if not afk.active:
        return await ctx.reply(ascii.warning("Not away", ["AFK mode is not active."]))
    summary = afk.disable()
    return await ctx.reply(afk.format_summary(summary))


@router.register(
    name="afk", category=CATEGORY, owner_only=True,
    description="Away mode: auto-reply once to private chats and log what you missed.",
    usage=".afk [30m|2h|1d] [reason]  |  .afk text <message>  |  .afk autooff on|off  |  .afk status",
    examples=[".afk 2h in a meeting", ".afk text Back tomorrow!", ".afk status"],
)
async def afk_cmd(ctx: CommandContext):
    args = ctx.args
    head = args[0].lower() if args else ""

    if head == "status":
        return await ctx.reply(ascii.frame("AFK", _status_lines()))
    if head in ("off", "back", "stop"):
        return await _come_back(ctx)
    if head == "text":
        text = ctx.args_text[len(args[0]):].strip() if args else ""
        if not text:
            afk.set_text("")
            return await ctx.reply(ascii.success("Reply reset", ["The default auto-reply text is used again."]))
        afk.set_text(text)
        return await ctx.reply(ascii.success("Reply saved", [text[:200]]))
    if head == "autooff":
        value = args[1].lower() if len(args) > 1 else ""
        if value not in ("on", "off"):
            return await ctx.reply_usage(".afk autooff on|off")
        afk.set_auto_off(value == "on")
        return await ctx.reply(ascii.success("Auto-off", [f"Now {value.upper()}."]))

    seconds = parse_duration(head) if head else None
    reason_words = args[1:] if seconds else args
    afk.enable(" ".join(reason_words), seconds or 0)
    lines = ["Private chats get one automatic reply each.", "Mentions in groups are logged."]
    if seconds:
        lines.append(f"Ends automatically in {human_duration(seconds)}.")
    lines.append("Come back with .back")
    return await ctx.reply(ascii.success("You are AFK", lines))


@router.register(name="back", category=CATEGORY, owner_only=True,
                 description="End AFK mode and show what you missed.", usage=".back")
async def back_cmd(ctx: CommandContext):
    return await _come_back(ctx)
