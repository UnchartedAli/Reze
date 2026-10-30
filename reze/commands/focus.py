"""Focus Mode commands backed by the default-off focus service."""

from reze.command_router import CommandContext, router
from reze.features import require
from reze.personal.focus import MAX_MINUTES, focus_service
from reze.ui import ascii

CATEGORY = "Personal"


@router.register(
    name="focus",
    category=CATEGORY,
    description="Start or stop a timed focus session and read your statistics.",
    usage=".focus [start [minutes] [label]|stop|status|stats [days]]",
    owner_only=True,
    examples=[".focus start 50 Deep work", ".focus status", ".focus stop", ".focus stats 7"],
)
async def focus_cmd(ctx: CommandContext):
    hint = require("focus")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = (ctx.args[0].lower() if ctx.args else "status")

    if action == "start":
        minutes = 25
        label_parts = []
        for arg in ctx.args[1:]:
            if arg.isdigit() and minutes == 25:
                minutes = int(arg)
            else:
                label_parts.append(arg)
        result = focus_service.start_session(" ".join(label_parts), minutes=minutes)
        if not result.get("started"):
            session = result.get("session") or {}
            return await ctx.reply(
                ascii.warning(
                    "A session is already running",
                    [
                        f"Started: {session.get('started_at')}",
                        f"Planned: {session.get('minutes')} min",
                        "Stop it with .focus stop",
                    ],
                )
            )
        session = result["session"]
        return await ctx.reply(
            ascii.success(
                "Focus session started",
                [
                    f"ID: {session['id']}",
                    f"Duration: {session['minutes']} min (max {MAX_MINUTES})",
                    "The session closes automatically when the timer expires.",
                ],
            )
        )

    if action == "stop":
        session = focus_service.stop_session(completed=False)
        if not session:
            return await ctx.reply(ascii.info("No active session", ["Start one with .focus start 25"]))
        return await ctx.reply(
            ascii.success(
                "Focus session stopped",
                [
                    f"Elapsed: {session.get('elapsed_minutes', 0)} min",
                    f"Planned: {session.get('minutes')} min",
                    "Marked as interrupted.",
                ],
            )
        )

    if action == "status":
        session = focus_service.active()
        if not session:
            return await ctx.reply(
                ascii.info("No active session", ["Start one with: .focus start 25 Deep work"])
            )
        return await ctx.reply(
            ascii.section(
                "Focus session",
                [
                    f"ID: {session['id']}",
                    f"Started: {session['started_at']}",
                    f"Planned: {session['minutes']} min",
                    f"Label: {session.get('label') or '-'}",
                ],
            )
        )

    if action == "stats":
        days = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 7
        stats = focus_service.stats(days=days)
        return await ctx.reply(
            ascii.section(
                f"Focus · {days} days",
                [
                    f"Sessions: {stats['sessions']}",
                    f"Completed: {stats['completed']} ({stats['completion_rate']}%)",
                    f"Focus time: {stats['minutes']} min ({stats['hours']} h)",
                ],
            )
        )

    return await ctx.reply_usage("Subcommands: start, stop, status, stats.")
