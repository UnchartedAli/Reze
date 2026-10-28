"""
Privacy and account-safety commands.

These commands never expose session strings, API hashes or tokens; they report
connection state and give the owner a checklist for account safety.
"""

import os
import shutil
from datetime import datetime

from reze.command_router import CommandContext, router
from reze.config import settings
from reze.telegram_client import telegram_manager
from reze.ui import ascii

CATEGORY = "Privacy"


@router.register(
    name="privacy",
    category=CATEGORY,
    description="Show the privacy and secret-handling rules Reze follows.",
    usage=".privacy",
    owner_only=True,
)
async def privacy_cmd(ctx: CommandContext):
    return await ctx.reply(
        ascii.frame(
            "Privacy",
            [
                "Sessions are stored on disk with restrictive permissions.",
                "API hashes, keys and session strings are never sent to the panel.",
                "Logs mask credentials, auth codes and tokens.",
                "AI prompts and responses are never logged.",
                "Media is processed in a temporary workspace and deleted afterwards.",
                "Personal archives stay in your local SQLite database.",
            ],
            footer="See docs/SECURITY.md",
        )
    )


@router.register(
    name="sessions",
    category=CATEGORY,
    description="Explain how to review active Telegram sessions.",
    usage=".sessions",
    owner_only=True,
)
async def sessions_cmd(ctx: CommandContext):
    status = telegram_manager.status()
    return await ctx.reply(
        ascii.frame(
            "Sessions",
            [
                f"Current backend: {status['session_backend']}",
                f"Connected: {'yes' if status['connected'] else 'no'}",
                "",
                "To review every device:",
                "Telegram app -> Settings -> Devices",
                "Terminate any session you do not recognise.",
                "",
                "Reze cannot decrypt or bypass account protections.",
            ],
        )
    )


@router.register(
    name="accountstatus",
    category=CATEGORY,
    description="Report real connection state for this account.",
    usage=".accountstatus",
    owner_only=True,
)
async def accountstatus_cmd(ctx: CommandContext):
    status = telegram_manager.status()
    return await ctx.reply(
        ascii.frame(
            "Account status",
            [
                f"Configured: {'yes' if status['configured'] else 'no'}",
                f"Connected: {'yes' if status['connected'] else 'no'}",
                f"Session backend: {status['session_backend']}",
                f"Telethon available: {'yes' if status['telethon_available'] else 'no'}",
                f"Platform: {settings.platform_name}",
            ],
        )
    )


@router.register(
    name="backup",
    category=CATEGORY,
    description="Copy the local database to a timestamped backup file.",
    usage=".backup",
    owner_only=True,
    cooldown=30,
)
async def backup_cmd(ctx: CommandContext):
    source = settings.database_path
    if not os.path.isfile(source):
        return await ctx.reply(ascii.warning("No database", [f"Nothing to back up at {source}."]))
    directory = os.path.dirname(source) or "."
    stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(directory, f"reze-backup-{stamp}.db")
    try:
        shutil.copy2(source, target)
    except OSError as exc:
        return await ctx.reply(ascii.error("Backup failed", [ascii.sanitize(str(exc))[:200]]))
    return await ctx.reply(
        ascii.success(
            "Backup created",
            [f"Path: {target}", f"Size: {os.path.getsize(target) // 1024} KB"],
            footer="The database contains no Telegram credentials",
        )
    )
