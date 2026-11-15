"""``.watchdog`` command (owner only): status, test and forget for the Watchdog bridge.

Shows only yes/no facts. Tokens and secrets are never printed.
"""

from __future__ import annotations

from typing import Any, List

from reze import consent
from reze.command_router import router
from reze.integrations import watchdog
from reze.media import stickerbot
from reze.permissions import PermissionManager
from reze.storage import secret_store
from reze.ui import ascii


def _sticker_token_source() -> str:
    if secret_store.is_stored(stickerbot.STICKER_SECRET):
        return "stored (encrypted)"
    import os

    if os.environ.get(stickerbot.ENV_TOKEN, "").strip():
        return "environment variable"
    return "not set"


async def _status(ctx, args: List[str]) -> Any:
    try:
        target = watchdog.url()
    except watchdog.WatchdogError as exc:
        target = str(exc)
    lines = [
        f"Watchdog URL: {target}",
        f"Bridge secret: {'stored (encrypted)' if watchdog.bridge_secret() else 'not set'}",
        f"Sticker bot: @{stickerbot.expected_username()}",
        f"Sticker bot token: {_sticker_token_source()}",
    ]
    return await ctx.reply(ascii.section("Watchdog", lines))


async def _test(ctx, args: List[str]) -> Any:
    delivered = await watchdog.send_event("test", "Test event from Reze.")
    if delivered:
        return await ctx.reply(ascii.success("Delivered", ["The Watchdog bot received the event."]))
    return await ctx.reply(
        ascii.warning(
            "Not delivered",
            ["Check REZE_WATCHDOG_URL, the bridge secret (same value as REZE_BRIDGE_SECRET) and the Watchdog worker."],
        )
    )


async def _forget(ctx, args: List[str]) -> Any:
    if not args or args[0].lower() != "confirm":
        return await ctx.reply(
            ascii.warning(
                "Confirmation needed",
                ["This removes the stored bridge secret and the stored sticker bot token.", "Run: .watchdog forget confirm"],
            )
        )
    watchdog.forget()
    secret_store.forget(stickerbot.STICKER_SECRET)
    return await ctx.reply(ascii.success("Forgotten", ["Stored secrets removed. Environment variables are not changed."]))


async def _summarize(ctx, args: List[str]) -> Any:
    if not args:
        return await ctx.reply_usage("Example: .watchdog summarize @channel 20")
    consent.require("watchdog.channel_posts")
    ref = args[0]
    count = max(1, min(int(args[1]) if len(args) > 1 else 20, watchdog.MAX_POSTS))
    target = int(ref) if ref.lstrip("-").isdigit() else (ref if ref.startswith("@") else "@" + ref)
    entity = await ctx.client.get_entity(target)
    title = getattr(entity, "title", "") or getattr(entity, "first_name", "") or ref
    posts = []
    async for message in ctx.client.iter_messages(entity, limit=count):
        text = (getattr(message, "message", "") or "").strip()
        if not text:
            continue
        stamp = message.date.strftime("%Y-%m-%d %H:%M") if getattr(message, "date", None) else ""
        posts.append({"channel": title, "date": stamp, "text": text})
    if not posts:
        return await ctx.reply(ascii.info("Nothing to summarize", ["No text posts were found in that chat."]))
    result = await watchdog.summarize_posts(posts)
    note = f"🐕‍🦺 خلاصه {len(posts)} پست «{title}»\n\n{result['summary']}"
    if result["removed"]:
        note += f"\n\n({result['removed']} خط حذف شد: عدد یا لینکی داشت که در پست‌ها نبود.)"
    await ctx.client.send_message("me", note[:4000])
    return await ctx.reply(ascii.success("Summary sent", [f"{len(posts)} post(s) from {title}, saved to Saved Messages."]))


HANDLERS = {"status": _status, "test": _test, "forget": _forget, "summarize": _summarize}


@router.register(
    name="watchdog",
    category="Automation",
    description="Watchdog bridge: status, test event, forget stored secrets (owner).",
    usage=".watchdog [status|test|forget confirm]",
    owner_only=True,
    examples=[".watchdog status", ".watchdog test"],
)
async def watchdog_cmd(ctx):
    if not PermissionManager.is_owner(ctx.sender_id):
        return await ctx.reply(ascii.warning("Owner only", ["The Watchdog bridge is owner-only."]))
    action = ctx.args[0].lower() if ctx.args else "status"
    handler = HANDLERS.get(action)
    if handler is None:
        return await ctx.reply(ascii.section("Watchdog commands", [".watchdog status", ".watchdog test", ".watchdog summarize @channel 20", ".watchdog forget confirm"]))
    try:
        return await handler(ctx, ctx.args[1:])
    except consent.ConsentRequired as exc:
        return await ctx.reply(ascii.warning("Consent needed", [str(exc)]))
    except watchdog.WatchdogError as exc:
        return await ctx.reply(ascii.warning("Not done", [str(exc)[:300]]))


__all__ = ["HANDLERS", "watchdog_cmd"]
