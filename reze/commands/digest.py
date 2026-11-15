"""``.digest`` command family for Channel Digest (owner only).

Every subcommand is gated by the global ``channel_digest`` feature, which is OFF
by default. The digest also has its own on/off switch, which is OFF until the
owner turns it on, so enabling the feature alone sends nothing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from reze.command_router import router
from reze.commands.ai import chat_digest_cmd
from reze.permissions import PermissionManager
from reze.digest import collect, store
from reze.digest.schedule import describe_days
from reze.digest.service import digest_service
from reze.features import require
from reze.ui import ascii

CATEGORY = "Automation"
HELP_LINES = [
    ".digest — status",
    ".digest channels — list selected channels",
    ".digest add <@username|id> — add a channel (only new posts from now on)",
    ".digest remove <@username|id> — remove a channel",
    ".digest priority <channel> <1-10> — 1 is highest",
    ".digest filter <channel> include|exclude <words|clear>",
    ".digest on | off — turn scheduled digests on or off",
    ".digest pause | resume — pause or resume scheduled digests",
    ".digest time HH:MM — delivery time",
    ".digest timezone <IANA name> — e.g. Asia/Tehran",
    ".digest days daily | weekly <day> | custom <mon,fri,...>",
    ".digest ai on | off — AI summaries (basic digest otherwise)",
    ".digest language en | fa",
    ".digest limit <messages> [characters]",
    ".digest now — send a digest immediately",
    ".digest history — recent runs",
    ".digest settings — full configuration",
    ".digest clear confirm — delete digest history and stored digest text",
]


def _fmt_when(value: Optional[str]) -> str:
    return value or "never"


def _find_channel(reference: str) -> Optional[Dict[str, Any]]:
    ref = (reference or "").strip()
    if not ref:
        return None
    if ref.lstrip("-").isdigit():
        return store.get_channel(int(ref))
    wanted = ref.lstrip("@").lower()
    for row in store.list_channels():
        if (row.get("username") or "").lower() == wanted:
            return row
    return None


async def _status(ctx) -> Any:
    snap = digest_service.snapshot()
    cfg = snap["config"]
    last = snap["last_run"]
    lines = [
        f"Digest: {'ON' if cfg['enabled'] else 'OFF'}" + (" (paused)" if cfg["paused"] else ""),
        f"Delivery: {cfg['time_of_day']} {cfg['timezone']} — {describe_days(cfg['schedule'], cfg['days'])}",
        f"Channels: {len(store.list_channels())} selected",
        f"AI summaries: {'on' if cfg['ai_enabled'] else 'off (basic digest)'}",
        f"Language: {cfg['language']}",
        f"Next digest: {snap['next_slot'] or '—'}",
        f"Last run: {last['status'] if last else 'none'}"
        + (f" at {_fmt_when(last['finished_at'] or last['created_at'])} UTC" if last else ""),
        f"Undelivered digests: {snap['pending']}",
    ]
    return await ctx.reply(ascii.section("Channel Digest", lines))


async def _channels(ctx, args: List[str]) -> Any:
    rows = store.list_channels()
    if not rows:
        return await ctx.reply(
            ascii.info("Channel Digest", ["No channels selected.", "Add one with: .digest add @channel"])
        )
    lines = []
    for row in rows[:30]:
        state = "on" if row["enabled"] else "off"
        handle = f"@{row['username']}" if row["username"] else str(row["chat_id"])
        keywords = []
        if row["include_keywords"]:
            keywords.append(f"include: {row['include_keywords']}")
        if row["exclude_keywords"]:
            keywords.append(f"exclude: {row['exclude_keywords']}")
        extra = f" [{'; '.join(keywords)}]" if keywords else ""
        lines.append(
            f"{row['title'] or handle} ({handle}) · priority {row['priority']} · {state} · "
            f"last sync {_fmt_when(row['last_synced_at'])}{extra}"
        )
    if len(rows) > 30:
        lines.append(f"… {len(rows) - 30} more not shown")
    return await ctx.reply(ascii.section("Selected channels", lines))


async def _add(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .digest add @channelname")
    info = await collect.resolve_channel(ctx.client, args[0])
    latest = await collect.latest_message_id(ctx.client, info["chat_id"])
    from reze.timeutil import utcnow

    added = store.add_channel(info["chat_id"], info["title"], info["username"], latest, utcnow())
    if not added:
        return await ctx.reply(ascii.info("Already selected", [info["title"] or args[0]]))
    return await ctx.reply(
        ascii.success(
            "Channel added",
            [info["title"] or args[0], "Only posts published from now on will be collected."],
        )
    )


async def _remove(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .digest remove @channelname")
    row = _find_channel(args[0])
    if row is None:
        return await ctx.reply(ascii.warning("Not selected", [f"{args[0]} is not in the digest."]))
    store.remove_channel(row["chat_id"])
    return await ctx.reply(ascii.success("Channel removed", [row["title"] or args[0]]))


async def _priority(ctx, args: List[str]) -> Any:
    if len(args) < 2:
        return await ctx.reply_usage("Example: .digest priority @channelname 2")
    row = _find_channel(args[0])
    if row is None:
        return await ctx.reply(ascii.warning("Not selected", [f"{args[0]} is not in the digest."]))
    store.update_channel(row["chat_id"], priority=int(args[1]))
    return await ctx.reply(ascii.success("Priority updated", [f"{row['title'] or args[0]}: {args[1]}"]))


async def _filter(ctx, args: List[str]) -> Any:
    if len(args) < 3 or args[1].lower() not in ("include", "exclude"):
        return await ctx.reply_usage("Example: .digest filter @channelname include bitcoin,rate")
    row = _find_channel(args[0])
    if row is None:
        return await ctx.reply(ascii.warning("Not selected", [f"{args[0]} is not in the digest."]))
    field = "include_keywords" if args[1].lower() == "include" else "exclude_keywords"
    words = "" if args[2].lower() == "clear" else " ".join(args[2:]).replace(" ", "")
    store.update_channel(row["chat_id"], **{field: words})
    return await ctx.reply(
        ascii.success("Filter updated", [f"{args[1].lower()}: {words or 'cleared'}"])
    )


async def _toggle(name: str, value: bool, title: str, ctx) -> Any:
    store.set_toggle(name, value)
    return await ctx.reply(ascii.success(title, [f"Now: {'on' if value else 'off'}"]))


async def _time(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .digest time 21:00")
    value = store.set_time(args[0])
    return await ctx.reply(ascii.success("Delivery time set", [value]))


async def _timezone(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .digest timezone Asia/Tehran")
    value = store.set_timezone(args[0])
    return await ctx.reply(ascii.success("Timezone set", [value]))


async def _days(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Examples: .digest days daily | .digest days weekly fri | .digest days custom mon,thu")
    kind = args[0]
    days_text = " ".join(args[1:])
    result = store.set_schedule(kind, days_text)
    return await ctx.reply(
        ascii.success("Schedule set", [f"{result['schedule']}: {describe_days(result['schedule'], result['days'])}"])
    )


async def _ai(ctx, args: List[str]) -> Any:
    if not args or args[0].lower() not in ("on", "off"):
        return await ctx.reply_usage("Example: .digest ai on")
    return await _toggle("ai_enabled", args[0].lower() == "on", "AI summaries", ctx)


async def _language(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .digest language fa")
    value = store.set_language(args[0])
    return await ctx.reply(ascii.success("Digest language", [value]))


async def _limit(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .digest limit 200 12000")
    messages = int(args[0])
    chars = int(args[1]) if len(args) > 1 else None
    result = store.set_limits(max_messages=messages, max_chars=chars)
    return await ctx.reply(ascii.success("Limits updated", [f"{k}: {v}" for k, v in result.items()]))


async def _now(ctx, args: List[str]) -> Any:
    result = await digest_service.run_now()
    status = result.get("status")
    if status == "disabled":
        return await ctx.reply(ascii.warning("Digest is OFF", [".digest on turns it on."]))
    if status == "offline":
        return await ctx.reply(ascii.warning("Telegram is not connected", ["Try again when the userbot is online."]))
    if status == "empty":
        return await ctx.reply(ascii.info("Nothing new", ["No new posts in the selected channels."]))
    if status == "failed":
        return await ctx.reply(ascii.error("Digest failed", [result.get("error", "unknown error")]))
    if status == "sent":
        return await ctx.reply(
            ascii.success("Digest sent", [f"Saved Messages · {result.get('messages', 0)} post(s) · {result.get('mode')}"])
        )
    if status == "pending":
        return await ctx.reply(
            ascii.warning("Digest stored, not sent yet", [result.get("error", "delivery failed"), "It will be retried automatically."])
        )
    return await ctx.reply(ascii.info("Digest", [str(status)]))


async def _history(ctx, args: List[str]) -> Any:
    rows = store.list_runs(limit=10)
    if not rows:
        return await ctx.reply(ascii.info("Digest history", ["No digests yet."]))
    lines = []
    for row in rows:
        lines.append(
            f"#{row['id']} {row['status']} · {row['kind']} · {row['message_count']} post(s) · "
            f"{row['summary_mode'] or '-'} · {_fmt_when(row['finished_at'] or row['created_at'])} UTC"
        )
    return await ctx.reply(ascii.section("Digest history", lines))


async def _settings(ctx, args: List[str]) -> Any:
    cfg = store.get_config()
    lines = [
        f"enabled: {cfg['enabled']}",
        f"paused: {cfg['paused']}",
        f"time: {cfg['time_of_day']} ({cfg['timezone']})",
        f"schedule: {cfg['schedule']} — {describe_days(cfg['schedule'], cfg['days'])}",
        f"ai_enabled: {cfg['ai_enabled']}",
        f"language: {cfg['language']}",
        f"max_messages: {cfg['max_messages']}",
        f"max_chars: {cfg['max_chars']}",
        "media processing: not available (captions and metadata only)",
    ]
    return await ctx.reply(ascii.section("Digest settings", lines))


async def _clear(ctx, args: List[str]) -> Any:
    if not args or args[0].lower() != "confirm":
        return await ctx.reply(
            ascii.warning(
                "Confirmation needed",
                [
                    "This deletes digest history and any digest text not yet delivered.",
                    "Channel selections are kept. Run: .digest clear confirm",
                ],
            )
        )
    removed = store.clear_history()
    return await ctx.reply(ascii.success("History cleared", [f"{removed} run record(s) deleted."]))


HANDLERS = {
    "channels": _channels,
    "add": _add,
    "remove": _remove,
    "priority": _priority,
    "filter": _filter,
    "on": lambda ctx, args: _toggle("enabled", True, "Digest ON", ctx),
    "off": lambda ctx, args: _toggle("enabled", False, "Digest OFF", ctx),
    "pause": lambda ctx, args: _toggle("paused", True, "Digest paused", ctx),
    "resume": lambda ctx, args: _toggle("paused", False, "Digest resumed", ctx),
    "time": _time,
    "timezone": _timezone,
    "days": _days,
    "ai": _ai,
    "language": _language,
    "limit": _limit,
    "now": _now,
    "history": _history,
    "settings": _settings,
    "clear": _clear,
    "status": _status,
}


@router.register(
    name="digest",
    category=CATEGORY,
    description="Channel Digest (owner). Bare or numeric .digest keeps the chat summary for everyone else.",
    usage=".digest [status|channels|add|remove|on|off|pause|resume|time|timezone|days|now|settings|<count>]",
    examples=[".digest", ".digest add @channel", ".digest time 21:00", ".digest now", ".digest 30"],
)
async def digest_cmd(ctx):
    action = ctx.args[0].lower() if ctx.args else ""
    # Compatibility: REZE 3.0 users summarize a chat with `.digest <count>`, and
    # non-owners with a bare `.digest`. Both keep the old behaviour.
    if action.isdigit() or (not action and not PermissionManager.is_owner(ctx.sender_id)):
        return await chat_digest_cmd(ctx)
    if not PermissionManager.is_owner(ctx.sender_id):
        return await ctx.reply(ascii.warning("Owner only", ["Channel Digest settings are owner-only."]))
    hint = require("channel_digest")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    handler = HANDLERS.get(action or "status")
    if handler is None:
        return await ctx.reply(ascii.section("Channel Digest commands", HELP_LINES))
    try:
        return await handler(ctx, ctx.args[1:])
    except ValueError as exc:
        return await ctx.reply(ascii.warning("Could not apply", [str(exc)]))


__all__ = ["digest_cmd", "HANDLERS", "HELP_LINES"]
