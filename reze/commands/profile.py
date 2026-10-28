"""
Profile commands: display name, bio, live clock and prefix.

Name and bio changes are applied to the real Telegram account when a client is
connected, and the base values are stored so the clock template can be rebuilt.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from reze.command_router import CommandContext, router
from reze.database import db
from reze.preferences import get_pref, set_pref
from reze.ui import ascii

CATEGORY = "Profile"


async def _apply_profile(ctx: CommandContext, **fields) -> str:
    """Send UpdateProfileRequest and return a status note."""
    client = ctx.client
    if client is None:
        return "stored locally (no Telegram client connected)"
    try:
        from telethon.tl.functions.account import UpdateProfileRequest

        await client(UpdateProfileRequest(**fields))
        return "applied to the Telegram account"
    except Exception as exc:  # noqa: BLE001 - Telegram errors are shown to the owner
        return f"stored locally, Telegram rejected the update: {ascii.sanitize(str(exc))[:120]}"


@router.register(name="setname", category=CATEGORY, description="Set the account display name.", usage=".setname <name>", owner_only=True)
async def setname_cmd(ctx: CommandContext):
    if not ctx.args_text.strip():
        return await ctx.reply_usage("Example: .setname Ali")
    name = ctx.args_text.strip()[:64]
    note = await _apply_profile(ctx, first_name=name)
    db.update_profile_settings(original_name=name)
    return await ctx.reply(ascii.success("Name updated", [name, note]))


@router.register(name="setbio", category=CATEGORY, description="Set the account bio.", usage=".setbio <text>", owner_only=True)
async def setbio_cmd(ctx: CommandContext):
    if not ctx.args_text.strip():
        return await ctx.reply_usage("Example: .setbio Building things with Reze")
    bio = ctx.args_text.strip()[:70]
    note = await _apply_profile(ctx, about=bio)
    db.update_profile_settings(original_bio=bio)
    return await ctx.reply(ascii.success("Bio updated", [bio, note]))


@router.register(name="nameclock", category=CATEGORY, description="Toggle the clock in the display name.", usage=".nameclock on|off", owner_only=True)
async def nameclock_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply_usage("Example: .nameclock on")
    enabled = 1 if ctx.args[0].lower() == "on" else 0
    db.update_profile_settings(name_clock_enabled=enabled)
    return await ctx.reply(ascii.info("Name clock", ["enabled" if enabled else "disabled"]))


@router.register(name="bioclock", category=CATEGORY, description="Toggle the clock in the bio.", usage=".bioclock on|off", owner_only=True)
async def bioclock_cmd(ctx: CommandContext):
    if not ctx.args or ctx.args[0].lower() not in ("on", "off"):
        return await ctx.reply_usage("Example: .bioclock on")
    enabled = 1 if ctx.args[0].lower() == "on" else 0
    db.update_profile_settings(bio_clock_enabled=enabled)
    return await ctx.reply(ascii.info("Bio clock", ["enabled" if enabled else "disabled"]))


@router.register(name="clockformat", category=CATEGORY, description="Set the strftime format for the clock.", usage=".clockformat %H:%M", owner_only=True)
async def clockformat_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .clockformat %H:%M")
    value = ctx.args[0][:20]
    try:
        datetime.now().strftime(value)
    except Exception:
        return await ctx.reply(ascii.error("Invalid format", ["Use a strftime pattern such as %H:%M."]))
    db.update_profile_settings(clock_format=value)
    return await ctx.reply(ascii.success("Clock format updated", [value]))


@router.register(name="timezone", category=CATEGORY, description="Set the IANA timezone for the clock.", usage=".timezone Asia/Tehran", owner_only=True)
async def timezone_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .timezone Europe/London")
    zone = ctx.args[0]
    try:
        ZoneInfo(zone)
    except Exception:
        return await ctx.reply(
            ascii.error("Invalid timezone", ["Use an IANA name such as Asia/Tehran, UTC or Europe/London."])
        )
    db.update_profile_settings(timezone=zone)
    return await ctx.reply(ascii.success("Timezone updated", [zone]))


@router.register(name="clockstatus", category=CATEGORY, description="Show the current clock configuration.", usage=".clockstatus", owner_only=True)
async def clockstatus_cmd(ctx: CommandContext):
    config = db.get_profile_settings()
    return await ctx.reply(
        ascii.frame(
            "Profile clock",
            [
                f"Name clock: {'on' if config.get('name_clock_enabled') else 'off'}",
                f"Bio clock: {'on' if config.get('bio_clock_enabled') else 'off'}",
                f"Timezone: {config.get('timezone', 'Asia/Tehran')}",
                f"Format: {config.get('clock_format', '%H:%M')}",
                f"Last update: {config.get('last_updated') or 'never'}",
            ],
        )
    )


@router.register(name="clockpreview", category=CATEGORY, description="Preview the name and bio with the current time.", usage=".clockpreview", owner_only=True)
async def clockpreview_cmd(ctx: CommandContext):
    config = db.get_profile_settings()
    try:
        zone = ZoneInfo(config.get("timezone", "Asia/Tehran"))
    except Exception:
        zone = ZoneInfo("UTC")
    time_text = datetime.now(zone).strftime(config.get("clock_format", "%H:%M"))

    name = (config.get("name_template") or "{name} | {time}").replace(
        "{name}", config.get("original_name") or "Reze User"
    ).replace("{time}", time_text)
    bio = (config.get("bio_template") or "{bio} · {time}").replace(
        "{bio}", config.get("original_bio") or "Reze Userbot"
    ).replace("{time}", time_text)
    return await ctx.reply(
        ascii.frame(
            "Clock preview",
            [f"Name: {name[:64]} ({len(name[:64])}/64)", f"Bio: {bio[:70]} ({len(bio[:70])}/70)"],
        )
    )


@router.register(name="setprefix", category=CATEGORY, description="Change the command prefix.", usage=".setprefix <char>", owner_only=True)
async def setprefix_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .setprefix !")
    try:
        set_pref("prefix", ctx.args[0])
    except ValueError as exc:
        return await ctx.reply(ascii.error("Invalid prefix", [str(exc)]))
    router.prefix = get_pref("prefix")
    return await ctx.reply(ascii.success("Prefix updated", [router.prefix]))
