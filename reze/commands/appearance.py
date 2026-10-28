"""
Appearance and configuration commands.

.theme [name]         switch the ASCII theme
.preview [name]       render a sample of the message engine
.config               show effective preferences and integration readiness
.config set <k> <v>   change a validated preference
.config reset <k>     remove an override
.prefix <char>        change the command prefix
"""

from reze.command_router import CommandContext, router
from reze.preferences import PREFERENCE_KEYS, all_prefs, get_pref, reset_pref, set_pref
from reze.ui import ascii
from reze.ui.themes import THEMES, theme_names

CATEGORY = "Appearance"


def _integration_lines() -> list:
    from reze.media import ffmpeg, images

    ai = "configured"
    try:
        from reze.ai.gateway import ai_gateway

        status = ai_gateway.status()
        ai = f"{status['provider']}/{status['model']}" if status["configured"] else "not configured"
    except Exception:
        ai = "unavailable"

    return [
        f"Pillow: {'available' if images.available() else 'missing'}",
        f"FFmpeg: {'available' if ffmpeg.available() else 'missing'}",
        f"AI provider: {ai}",
        f"Background removal: {'configured' if _removebg_configured() else 'not configured'}",
    ]


def _removebg_configured() -> bool:
    from reze.config import settings

    return bool(settings.removebg_api_key)


@router.register(
    name="theme",
    category=CATEGORY,
    description="Switch the message theme (CYBER, GHOST, TERMINAL, COMPACT).",
    usage=".theme [name]",
    cooldown=1,
)
async def theme_cmd(ctx: CommandContext):
    if not ctx.args:
        current = get_pref("theme")
        lines = [f"Current: {current}", ""] + [
            f"{THEMES[name].accent} {name:<9} {THEMES[name].description}" for name in theme_names()
        ]
        return await ctx.reply(ascii.section("Themes", lines))

    requested = ctx.args[0].upper()
    if requested not in THEMES:
        return await ctx.reply(
            ascii.warning("Unknown theme", [f"Available: {', '.join(theme_names())}"])
        )
    set_pref("theme", requested)
    return await ctx.reply(
        ascii.success(
            f"Theme: {requested}",
            [THEMES[requested].description, "Use .preview to check the layout."],
        )
    )


@router.register(
    name="preview",
    category=CATEGORY,
    description="Preview the ASCII message engine in a given theme.",
    usage=".preview [theme]",
    cooldown=2,
)
async def preview_cmd(ctx: CommandContext):
    theme = ctx.args[0].upper() if ctx.args else None
    if theme and theme not in THEMES:
        return await ctx.reply(
            ascii.warning("Unknown theme", [f"Available: {', '.join(theme_names())}"])
        )
    return await ctx.reply(ascii.preview(theme))


@router.register(
    name="config",
    category=CATEGORY,
    description="Show or change validated user preferences.",
    usage=".config [set <key> <value> | reset <key>]",
    owner_only=True,
)
async def config_cmd(ctx: CommandContext):
    action = ctx.args[0].lower() if ctx.args else ""

    if action == "set":
        if len(ctx.args) < 3:
            return await ctx.reply_usage("Example: .config set theme GHOST")
        key = ctx.args[1].lower()
        value = " ".join(ctx.args[2:])
        try:
            set_pref(key, value)
        except KeyError:
            return await ctx.reply(
                ascii.error("Unknown setting", [f"Valid keys: {', '.join(PREFERENCE_KEYS)}"])
            )
        except ValueError as exc:
            return await ctx.reply(ascii.error("Invalid value", [str(exc)]))
        if key == "prefix":
            router.prefix = get_pref("prefix")
        return await ctx.reply(ascii.success("Preference saved", [f"{key} = {get_pref(key)}"]))

    if action == "reset":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .config reset theme")
        removed = reset_pref(ctx.args[1].lower())
        return await ctx.reply(
            ascii.info("Preferences", ["Override removed." if removed else "No override was stored."])
        )

    prefs = all_prefs()
    lines = [
        f"Prefix: {prefs['prefix']}",
        f"Theme: {prefs['theme']}",
        f"Compact mode: {'on' if prefs['compact'] in {'1', 'true'} else 'off'}",
        f"AI provider: {prefs['ai_provider'] or 'not set'}",
        f"AI model: {prefs['ai_model'] or 'not set'}",
        f"Media quality: {prefs['media_quality']}",
        f"Media input limit: {prefs['media_max_input_mb']} MB",
        f"Log level: {prefs['log_level']}",
        "",
        "Integrations:",
        *_integration_lines(),
        "",
        f"Keys: {', '.join(PREFERENCE_KEYS)}",
    ]
    return await ctx.reply(ascii.frame("Configuration", lines))


@router.register(
    name="prefix",
    category=CATEGORY,
    description="Change the command prefix (1-2 characters).",
    usage=".prefix <char>",
    owner_only=True,
)
async def prefix_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply(ascii.info("Prefix", [f"Current prefix: {router.prefix}"]))
    value = ctx.args[0]
    try:
        set_pref("prefix", value)
    except ValueError as exc:
        return await ctx.reply(ascii.error("Invalid prefix", [str(exc)]))
    router.prefix = get_pref("prefix")
    return await ctx.reply(ascii.success("Prefix updated", [f"Commands now start with {router.prefix}"]))
