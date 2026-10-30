"""
General commands: help, identity, account info, stats, logs, process control.
"""

import os
import sys
import time
from datetime import timedelta

from reze import __author__, __channel__, __channel_url__, __version__
from reze.command_router import CommandContext, router
from reze.config import settings
from reze.database import db
from reze.localization import get_language, t
from reze.logging_config import LOG_BUFFER
from reze.telegram_client import telegram_manager
from reze.ui import ascii

START_TIME = time.time()


@router.register(
    name="help",
    category="General",
    description="Show command help by category or for one command.",
    usage=".help [category | command]",
    cooldown=1,
    examples=[".help", ".help media", ".help sticker"],
)
async def help_cmd(ctx: CommandContext):
    target = ctx.args[0].lower() if ctx.args else ""

    if target:
        command = router.resolve(target)
        if command is not None:
            lines = [
                f"Command: {router.prefix}{command.name}",
                f"{t('common.category', 'Category')}: {command.category}",
                f"{t('router.usage', 'Usage')}: {command.usage}",
                f"Description: {command.description}",
            ]
            if command.aliases:
                lines.append(
                    f"{t('help.aliases', 'Aliases')}: "
                    + ", ".join(router.prefix + alias for alias in command.aliases)
                )
            if command.examples:
                lines.append(f"{t('help.examples', 'Examples')}:")
                lines.extend(f"  {example}" for example in command.examples)
            access = []
            if command.owner_only:
                access.append(t("help.owner", "owner") + " only")
            if command.admin_only:
                access.append(t("help.admin", "group admins"))
            if command.group_only:
                access.append(t("help.group", "groups only"))
            if command.cooldown:
                access.append(f"{command.cooldown}s cooldown")
            if access:
                lines.append(f"{t('help.access', 'Access')}: " + ", ".join(access))
            return await ctx.reply(ascii.frame(t("help.command_help", "Command help"), lines))

        for category, commands in router.categories().items():
            if category.lower() == target:
                lines = [f"{command.usage}  -  {command.description}" for command in commands]
                return await ctx.reply(ascii.section(f"{category} commands", lines))

    categories = router.categories()
    summary = [
        t("help.category_line", f"{name}: {len(commands)} commands", name=name, count=len(commands))
        for name, commands in categories.items()
    ]
    body = [
        f"Version: {__version__}",
        f"Prefix: {router.prefix}",
        f"{t('help.count', f'{len(router.commands)} commands', count=len(router.commands))}",
        f"Language: {get_language()}",
        "",
        *summary,
        "",
        t("help.hint", "Use .help <category> for the command list,"),
        t("help.hint2", "or .help <command> for usage and examples."),
        t("features.hint", "Every optional feature is OFF by default. See .features."),
    ]
    return await ctx.reply(
        ascii.frame(
            t("help.title", "Command index"),
            body,
            footer=f"{__author__} · {__channel__}",
        )
    )


@router.register(name="ping", category="General", description="Measure command round-trip latency.", usage=".ping")
async def ping_cmd(ctx: CommandContext):
    started = time.time()
    latency = (time.time() - started) * 1000
    return await ctx.reply(
        ascii.success("Pong", [f"Handler latency: {latency:.1f} ms", f"Uptime: {str(timedelta(seconds=int(time.time() - START_TIME)))}"])
    )


@router.register(name="alive", category="General", description="Confirm the userbot is running.", usage=".alive")
async def alive_cmd(ctx: CommandContext):
    telegram = telegram_manager.status()
    return await ctx.reply(
        ascii.success(
            "Reze is alive",
            [
                f"Version: {__version__}",
                f"Uptime: {str(timedelta(seconds=int(time.time() - START_TIME)))}",
                f"Telegram: {'connected' if telegram['connected'] else 'panel-only mode'}",
                f"Theme: {ascii.active_theme_name()}",
            ],
            footer=f"{__author__} · {__channel__}",
        )
    )


@router.register(
    name="credits",
    category="General",
    description="Show the author and the official channel.",
    usage=".credits",
    aliases=["creator", "developer", "support"],
)
async def credits_cmd(ctx: CommandContext):
    return await ctx.reply(
        ascii.frame(
            "Reze",
            [
                f"Author: {__author__}",
                f"Channel: {__channel__}",
                f"Source: {__channel_url__}",
                f"Version: {__version__}",
            ],
            footer="MIT licensed",
        )
    )


@router.register(name="info", category="General", description="Account and deployment information.", usage=".info")
async def info_cmd(ctx: CommandContext):
    return await ctx.reply(
        ascii.frame(
            "Account",
            [
                f"Owner id: {settings.owner_id}",
                f"Timezone: {settings.timezone}",
                f"Database: SQLite (WAL)",
                f"Session backend: {settings.session_backend}",
                f"Platform: {settings.platform_name}",
            ],
        )
    )


@router.register(name="id", category="General", description="Show user, chat and message identifiers.", usage=".id")
async def id_cmd(ctx: CommandContext):
    target_id = await ctx.get_target_user_id() or ctx.sender_id
    lines = [f"User: {target_id}", f"Chat: {ctx.chat_id}"]
    if ctx.is_reply:
        lines.append(f"Reply message: {getattr(ctx.message, 'reply_to_msg_id', 'unknown')}")
    lines.append(f"Your id: {ctx.sender_id}")
    return await ctx.reply(ascii.frame("Identifiers", lines))


@router.register(name="stats", category="General", description="Local database and usage statistics.", usage=".stats")
async def stats_cmd(ctx: CommandContext):
    stats = db.get_stats()
    return await ctx.reply(
        ascii.frame(
            "Statistics",
            [
                f"Commands executed: {router.total_executed}",
                f"Errors: {router.errors_count}",
                f"Denied: {router.denied_count}",
                f"Configured groups: {stats.get('groups', 0)}",
                f"Filters: {stats.get('filters', 0)}",
                f"Group notes: {stats.get('notes', 0)}",
                f"Warnings: {stats.get('warnings', 0)}",
                f"Archive entries: {stats.get('archive', 0)}",
                f"Pending reminders: {stats.get('reminders', 0)}",
                f"Automation rules: {stats.get('automations', 0)}",
            ],
        )
    )


@router.register(name="uptime", category="General", description="Show process uptime.", usage=".uptime")
async def uptime_cmd(ctx: CommandContext):
    return await ctx.reply(
        ascii.info("Uptime", [str(timedelta(seconds=int(time.time() - START_TIME)))])
    )


@router.register(name="version", category="General", description="Show the running Reze version.", usage=".version")
async def version_cmd(ctx: CommandContext):
    return await ctx.reply(
        ascii.frame(
            "Version",
            [f"Version: {__version__}", f"Author: {__author__}", f"Channel: {__channel__}"],
        )
    )


@router.register(
    name="settings",
    category="General",
    description="Show environment configuration (no secrets).",
    usage=".settings",
    owner_only=True,
)
async def settings_cmd(ctx: CommandContext):
    return await ctx.reply(
        ascii.frame(
            "Environment",
            [
                f"Prefix: {router.prefix}",
                f"Timezone: {settings.timezone}",
                f"Clock interval: {settings.clock_interval_minutes} min",
                f"Web port: {settings.web_port}",
                f"Log level: {settings.log_level}",
                f"Task concurrency: {settings.task_concurrency}",
                f"Media input limit: {settings.media_max_input_mb} MB",
                f"AI configured: {'yes' if settings.ai_enabled else 'no'}",
            ],
            footer="User preferences: .config",
        )
    )


@router.register(
    name="webpanel",
    category="General",
    description="Show the web panel URL and health endpoint.",
    usage=".webpanel",
    owner_only=True,
)
async def webpanel_cmd(ctx: CommandContext):
    url = settings.display_url
    return await ctx.reply(
        ascii.frame(
            "Web panel",
            [
                f"URL: {url}",
                f"Username: {settings.panel_username}",
                f"Health: {url.rstrip('/')}{settings.healthcheck_path}",
                "Change the password with scripts/generate_hash.py",
            ],
        )
    )


@router.register(
    name="logs",
    category="General",
    description="Show the most recent log lines.",
    usage=".logs [count]",
    owner_only=True,
)
async def logs_cmd(ctx: CommandContext):
    count = 10
    if ctx.args and ctx.args[0].isdigit():
        count = max(1, min(int(ctx.args[0]), 30))
    if not LOG_BUFFER:
        return await ctx.reply(ascii.info("Logs", ["The log buffer is empty."]))
    recent = list(LOG_BUFFER)[-count:]
    lines = [f"[{item.get('level')}] {ascii.sanitize(item.get('message', ''))[:160]}" for item in recent]
    return await ctx.reply(ascii.section("Recent logs", lines))


@router.register(
    name="shutdown",
    category="General",
    description="Stop the Reze process safely.",
    usage=".shutdown",
    owner_only=True,
)
async def shutdown_cmd(ctx: CommandContext):
    await ctx.reply(ascii.warning("Shutting down", ["The process will stop now."]))
    sys.exit(0)


@router.register(
    name="restart",
    category="General",
    description="Restart the Reze process.",
    usage=".restart",
    owner_only=True,
)
async def restart_cmd(ctx: CommandContext):
    await ctx.reply(ascii.warning("Restarting", ["The process will restart now."]))
    os.execv(sys.executable, [sys.executable] + sys.argv)
