"""
Task and diagnostics commands.

.queue             active and queued background tasks
.cancel <task_id>  request cancellation
.status [task_id]  system status, or one task in detail
.diagnostics       integration readiness and recent errors (owner only)
"""

import os
import platform
import sys
import time

from reze import __version__
from reze.command_router import CommandContext, router
from reze.config import settings
from reze.core.presence import presence_service
from reze.core.tasks import task_manager
from reze.database import db
from reze.media import ffmpeg, images
from reze.plugin_manager import plugin_manager
from reze.telegram_client import telegram_manager
from reze.ui import ascii

CATEGORY = "System"
PROCESS_STARTED_AT = time.time()


def _uptime() -> str:
    seconds = int(time.time() - PROCESS_STARTED_AT)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}h {minutes}m {secs}s"


@router.register(
    name="queue",
    category=CATEGORY,
    description="Show running and queued background tasks.",
    usage=".queue",
    owner_only=True,
    cooldown=2,
)
async def queue_cmd(ctx: CommandContext):
    active = task_manager.active()
    queued = task_manager.queued()
    lines = [
        f"Concurrency: {task_manager.concurrency}",
        f"Queue limit: {task_manager.queue_limit}",
        "",
    ]
    if active:
        lines.append("Running:")
        for record in active:
            lines.append(
                f"  {record.id}  {record.kind:<12} {record.progress:5.1f}%  {record.elapsed:5.1f}s  {record.detail}"
            )
    else:
        lines.append("Running: none")
    if queued:
        lines.append("Queued:")
        lines.extend(f"  {record.id}  {record.kind}" for record in queued)
    else:
        lines.append("Queued: none")

    finished = task_manager.finished(limit=5)
    if finished:
        lines.append("")
        lines.append("Recent:")
        for record in finished:
            lines.append(f"  {record.id}  {record.kind:<12} {record.status.value:<10} {record.elapsed:5.1f}s")
    return await ctx.reply(ascii.section("Task queue", lines))


@router.register(
    name="cancel",
    category=CATEGORY,
    description="Cancel a running or queued background task.",
    usage=".cancel <task_id>",
    owner_only=True,
    cooldown=1,
)
async def cancel_cmd(ctx: CommandContext):
    if not ctx.args:
        return await ctx.reply_usage("Example: .cancel a1b2c3d4")
    task_id = ctx.args[0].lower()
    try:
        cancelled = await task_manager.cancel(task_id)
    except Exception as exc:
        return await ctx.reply(ascii.error("Cancel failed", [ascii.sanitize(str(exc))[:200]]))
    if cancelled:
        return await ctx.reply(ascii.success("Cancellation requested", [f"Task {ascii.code(task_id)}"]))
    return await ctx.reply(
        ascii.info("Task finished", [f"Task {ascii.code(task_id)} already reached a final state."])
    )


@router.register(
    name="status",
    category=CATEGORY,
    description="Show overall system status, or one task in detail.",
    usage=".status [task_id]",
    cooldown=1,
)
async def status_cmd(ctx: CommandContext):
    if ctx.args:
        record = task_manager.get(ctx.args[0].lower())
        if record is None:
            return await ctx.reply(ascii.warning("Unknown task", [ctx.args[0]]))
        lines = [
            f"Kind: {record.kind}",
            f"Command: .{record.command or 'unknown'}",
            f"Status: {record.status.value}",
            f"Progress: {record.progress:.1f}%",
            f"Elapsed: {record.elapsed:.1f}s",
            f"Detail: {record.detail or '-'}",
        ]
        if record.error:
            lines.append(f"Error: {record.error}")
        if record.result_summary:
            lines.append(f"Result: {record.result_summary[:200]}")
        return await ctx.reply(ascii.frame(f"Task {record.id}", lines))

    telegram = telegram_manager.status()
    plugin_status = plugin_manager.status()
    ai_status = _ai_status()
    lines = [
        f"Version: {__version__}",
        f"Uptime: {_uptime()}",
        f"Telegram: {'connected' if telegram['connected'] else 'not connected'} "
        f"({'configured' if telegram['configured'] else 'missing credentials'})",
        f"Session backend: {settings.session_backend}",
        f"Tasks: {len(task_manager.active())} running, {len(task_manager.queued())} queued",
        f"Plugins: {plugin_status['loaded']} loaded, {plugin_status['failed']} failed",
        f"AI: {ai_status}",
        f"Always online: {'enabled' if presence_service.enabled() else 'disabled'}",
        f"Reminders pending: {db.get_stats().get('reminders', 0)}",
        f"Prefix: {router.prefix} · Theme: {ascii.active_theme_name()}",
    ]
    return await ctx.reply(ascii.frame("System status", lines))


def _ai_status() -> str:
    try:
        from reze.ai.gateway import ai_gateway

        status = ai_gateway.status()
        return f"{status['provider']}/{status['model']}" if status["configured"] else "not configured"
    except Exception:
        return "unavailable"


@router.register(
    name="diagnostics",
    category=CATEGORY,
    description="Integration readiness, dependency health and recent errors.",
    usage=".diagnostics",
    owner_only=True,
    cooldown=5,
)
async def diagnostics_cmd(ctx: CommandContext):
    from reze.logging_config import LOG_BUFFER

    telegram = telegram_manager.status()
    plugin_status = plugin_manager.status()
    disk_ok = os.access(settings.media_work_path if os.path.isdir(settings.media_work_path) else ".", os.W_OK)
    database_exists = os.path.isfile(db.db_path)

    checks = [
        ("Telegram credentials", "ok" if telegram["configured"] else "missing REZE_API_ID / REZE_API_HASH"),
        ("Telegram session", "connected" if telegram["connected"] else "not connected"),
        ("Panel password", "set" if settings.has_panel_credentials else "not set"),
        ("Database", f"{db.db_path} ({'present' if database_exists else 'new'})"),
        ("Writable media dir", "ok" if disk_ok else "not writable"),
        ("Pillow", "available" if images.available() else "missing (image and sticker commands disabled)"),
        ("FFmpeg", "available" if ffmpeg.available() else "missing (video/audio commands disabled)"),
        ("AI provider", _ai_status()),
        ("Plugins", f"{plugin_status['loaded']} loaded, {plugin_status['failed']} failed"),
        ("Secret key", "default value" if settings.secret_key == "reze-super-secret-key-change-me-in-production" else "customized"),
        ("Python", f"{sys.version.split()[0]} on {platform.system()}"),
    ]
    lines = [f"{name}: {status}" for name, status in checks]

    warnings = settings.deployment_notes()
    if warnings:
        lines.append("")
        lines.append("Deployment notes:")
        lines.extend(f"  - {note}" for note in warnings)

    errors = [entry for entry in list(LOG_BUFFER)[-50:] if entry.get("level") in {"ERROR", "CRITICAL"}]
    lines.append("")
    if errors:
        lines.append("Recent errors:")
        lines.extend(f"  {ascii.sanitize(entry.get('message', ''))[:120]}" for entry in errors[-5:])
    else:
        lines.append("Recent errors: none")

    return await ctx.reply(ascii.frame("Diagnostics", lines, footer="No secrets are displayed"))
