"""Self-maintenance and Security Sentinel commands (both OFF by default)."""

from datetime import datetime

from reze.command_router import CommandContext, router
from reze.database import db
from reze.features import require
from reze.security.retention import apply as apply_retention
from reze.security.retention import policies, preview
from reze.security.sentinel import sentinel_service
from reze.storage.backups.service import BackupError, backup_service
from reze.ui import ascii

CATEGORY = "Security"


@router.register(
    name="maintain",
    category=CATEGORY,
    description="Inspect integrity, backup age and retention, or apply retention.",
    usage=".maintain | .maintain apply confirm",
    owner_only=True,
    cooldown=30,
    examples=[".maintain", ".maintain apply confirm"],
)
async def maintain_cmd(ctx: CommandContext):
    action = (ctx.args[0].lower() if ctx.args else "status")

    if action == "status":
        try:
            integrity = db.query_one("PRAGMA quick_check")
        except Exception:  # noqa: BLE001
            integrity = None
        result = ""
        if integrity:
            result = str(next(iter(integrity.values()), ""))
        age = backup_service.latest_age_days()
        pending = preview()
        lines = [
            f"SQLite quick_check: {result or 'unknown'}",
            f"Schema version: {db.schema_version}",
            f"Latest backup: {'never' if age is None else f'{age} days old'}",
            f"Retention: audit {policies()['audit_log_days']}d, maintenance {policies()['maintenance_days']}d",
            "Pending deletions: " + ", ".join(f"{key}={value}" for key, value in pending.items()),
            "",
            "Apply retention with: .maintain apply confirm (feature must be ON)",
        ]
        return await ctx.reply(ascii.section("Self-maintenance", lines))

    if action == "apply":
        hint = require("self_maintenance")
        if hint:
            return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        if "confirm" not in {value.lower() for value in ctx.args[1:]}:
            return await ctx.reply(
                ascii.warning(
                    "Confirmation required",
                    [
                        "This permanently deletes rows older than the retention limits.",
                        "Run: .maintain apply confirm",
                    ],
                )
            )
        try:
            safety = backup_service.create(kind="pre-maintenance")
        except BackupError as exc:
            return await ctx.reply(ascii.warning("Backup failed; nothing deleted", [str(exc)]))
        removed = apply_retention()
        detail = ", ".join(f"{key}={value}" for key, value in removed.items())
        try:
            db.execute(
                "INSERT INTO maintenance_runs (action, status, detail) VALUES ('retention', 'ok', ?)",
                (detail[:1000],),
            )
        except Exception:  # noqa: BLE001 - the row is informational
            pass
        return await ctx.reply(
            ascii.success(
                "Retention applied",
                [
                    f"Removed: {detail or 'nothing'}",
                    f"Safety backup: {safety['path']}",
                ],
            )
        )

    return await ctx.reply_usage("Subcommands: status, apply confirm.")


@router.register(
    name="sentinel",
    category=CATEGORY,
    description="Run local security checks and review findings.",
    usage=".sentinel [run|open|summary|resolve <id>]",
    owner_only=True,
    cooldown=15,
    examples=[".sentinel", ".sentinel open", ".sentinel resolve 2"],
)
async def sentinel_cmd(ctx: CommandContext):
    hint = require("security_sentinel")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    action = (ctx.args[0].lower() if ctx.args else "run")

    if action in {"run", "check"}:
        findings = sentinel_service.run()
        if not findings:
            return await ctx.reply(
                ascii.success("Security check", ["No findings. Keep the Vault key and panel password secret."])
            )
        lines = []
        for finding in findings:
            lines.append(f"[{finding['severity']}] {finding['title']}")
            lines.append(f"  {finding['detail'][:180]}")
        lines.append("")
        lines.append(f"Findings: {len(findings)} · stored locally")
        return await ctx.reply(ascii.warning("Security findings", lines))

    if action == "open":
        rows = sentinel_service.open(limit=20)
        if not rows:
            return await ctx.reply(ascii.info("No open findings", ["Run .sentinel to check again."]))
        lines = [
            f"#{row['id']} [{row['severity']}] {row['title']} · {row['created_at']}" for row in rows
        ]
        return await ctx.reply(ascii.section("Open findings", lines))

    if action == "summary":
        summary = sentinel_service.summary()
        return await ctx.reply(
            ascii.section(
                "Sentinel",
                [
                    f"Open: {summary['total']}",
                    f"Critical: {summary['critical']}",
                    f"Warnings: {summary['warning']}",
                    f"Checked at: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC",
                ],
            )
        )

    if action == "resolve":
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .sentinel resolve 2")
        sentinel_service.resolve(int(ctx.args[1]))
        return await ctx.reply(ascii.success("Finding resolved", [f"ID: {ctx.args[1]}"]))

    return await ctx.reply_usage("Subcommands: run, open, summary, resolve.")
