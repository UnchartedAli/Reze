"""
Privacy and account-safety commands.

These commands never expose session strings, API hashes or tokens; they report
connection state and give the owner a checklist for account safety.
"""

from reze.command_router import CommandContext, router
from reze.config import settings
from reze.storage.backups.service import BackupError, backup_service
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
    description="Create, list, verify, restore or prune local database backups.",
    usage=".backup [create|list|verify <id>|restore <id>|confirm <code>|prune [keep]]",
    owner_only=True,
    cooldown=10,
    examples=[".backup", ".backup list", ".backup verify 1", ".backup restore 1"],
)
async def backup_cmd(ctx: CommandContext):
    action = (ctx.args[0].lower() if ctx.args else "create")

    if action in {"create", "now"}:
        try:
            report = backup_service.create(kind="manual")
        except BackupError as exc:
            return await ctx.reply(ascii.error("Backup failed", [str(exc)]))
        return await ctx.reply(
            ascii.success(
                "Backup created",
                [
                    f"Path: {report['path']}",
                    f"Size: {report['size'] // 1024} KB",
                    "Verify it with: .backup verify " + report["name"],
                ],
                footer="The database contains no Telegram credentials",
            )
        )

    if action == "list":
        rows = backup_service.list(limit=15)
        if not rows:
            return await ctx.reply(ascii.info("No backups", ["Create one with .backup"]))
        lines = [
            f"#{row['id']} {row['created_at']} {row['size_bytes'] // 1024} KB "
            f"[{row['kind']}] {'ok' if row['exists'] else 'MISSING'}"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Backups", lines))

    if action == "verify":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .backup verify 1")
        row = backup_service.resolve(ctx.args[1])
        if row is None:
            return await ctx.reply(ascii.warning("Not found", ["No backup with that ID or name."]))
        try:
            report = backup_service.verify(row["path"])
        except BackupError as exc:
            return await ctx.reply(ascii.warning("Verification failed", [str(exc)]))
        return await ctx.reply(
            ascii.section(
                "Backup verification",
                [
                    f"Integrity: {report['integrity']}",
                    f"Schema version: {report['schema_version']}",
                    f"Core tables: {', '.join(report['core_tables']) or 'missing'}",
                    f"Size: {report['size'] // 1024} KB",
                ],
            )
        )

    if action == "restore":
        from reze.features import require

        hint = require("self_maintenance")
        if hint:
            return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .backup restore 1")
        try:
            report = backup_service.prepare_restore(ctx.args[1])
        except BackupError as exc:
            return await ctx.reply(ascii.warning("Restore not prepared", [str(exc)]))
        return await ctx.reply(
            ascii.warning(
                "Restore prepared",
                [
                    f"Backup: {report['path']}",
                    f"Expires: {report['expires']} UTC",
                    "A safety copy is created before restoring.",
                    f"Confirm with: .backup confirm {report['code']}",
                ],
                footer="Nothing has been changed yet",
            )
        )

    if action == "confirm":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .backup confirm 123456")
        try:
            report = backup_service.restore(ctx.args[1])
        except BackupError as exc:
            return await ctx.reply(ascii.warning("Restore failed", [str(exc)]))
        return await ctx.reply(
            ascii.success(
                "Database restored",
                [
                    f"Source: {report['path']}",
                    f"Schema version: {report['schema_version']}",
                    f"Safety copy: {report['safety']}",
                    "Restart REZE so every service reloads the restored data.",
                ],
            )
        )

    if action == "prune":
        keep = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 10
        removed = backup_service.prune(keep=keep)
        return await ctx.reply(
            ascii.success("Backups pruned", [f"Removed: {removed}", f"Kept: {max(0, keep)} newest"])
        )

    return await ctx.reply_usage("Subcommands: create, list, verify, restore, confirm, prune.")
