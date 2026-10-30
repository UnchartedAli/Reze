"""
Automation Simulator and persistent workflows.

The simulator is always available: it validates steps and prints what *would*
happen without sending anything or writing rows. Creating, enabling and running
a stored workflow requires the ``workflows`` feature to be explicitly ON.
"""

import json

from reze.automation.simulator import SimulationError, simulate
from reze.automation.workflow import WorkflowError, WorkflowUnavailable, workflow_service
from reze.command_router import CommandContext, router
from reze.features import require
from reze.ui import ascii

CATEGORY = "Automation"
HELP = (
    "Steps are JSON. Allowed actions: send_message(chat_id,text), notify_owner(text), "
    "save_memory(content), add_timeline(title,body), add_task(title,project), "
    "add_reminder(text,minutes), log(message), wait(seconds)."
)


def _json_payload(ctx: CommandContext, skip: int) -> str:
    parts = ctx.raw_text.split(None, skip)
    if len(parts) <= skip:
        return ""
    return " ".join(parts[skip:])


def _format_simulation(report) -> list:
    lines = []
    for step in report.steps:
        lines.append(f"{step.index}. [{step.status}] {step.action}: {step.detail}")
    if report.errors:
        lines.append("")
        lines.extend(f"! {error}" for error in report.errors)
    lines.append("")
    lines.append("Dry run: no message was sent and no row was written.")
    return lines


@router.register(
    name="workflow",
    category=CATEGORY,
    description="Simulate and run persistent multi-step workflows (OFF by default).",
    usage=".workflow [list|simulate <json>|add <name> <json>|enable <name>|disable <name>|run <name>|history [name]|resume <run-id>|cancel <run-id>|delete <name>]",
    owner_only=True,
    cooldown=5,
    examples=[
        '.workflow simulate [{"action":"notify_owner","text":"hello"}]',
        '.workflow add daily-digest [{"action":"notify_owner","text":"Good morning"}]',
        ".workflow run daily-digest",
    ],
)
async def workflow_cmd(ctx: CommandContext):
    action = (ctx.args[0].lower() if ctx.args else "list")

    if action == "simulate":
        payload = _json_payload(ctx, 2)
        if not payload:
            return await ctx.reply_usage(HELP)
        report = simulate(payload)
        return await ctx.reply(
            ascii.section(
                "Workflow simulation",
                _format_simulation(report),
            )
        )

    if action in {"add", "create", "edit", "update"}:
        hint = require("workflows")
        if hint:
            return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        if len(ctx.args) < 3:
            return await ctx.reply_usage(HELP)
        name = ctx.args[1]
        payload = _json_payload(ctx, 3)
        try:
            data = json.loads(payload)
        except ValueError as exc:
            return await ctx.reply(ascii.warning("Invalid JSON", [str(exc)]))
        if isinstance(data, list):
            steps, options = data, {}
        elif isinstance(data, dict):
            steps = data.get("steps")
            options = data
            if steps is None:
                return await ctx.reply(ascii.warning("Invalid workflow", ["A 'steps' list is required."]))
        else:
            return await ctx.reply(ascii.warning("Invalid workflow", ["Use a JSON list or object."]))
        trigger_type = str(options.get("trigger") or "manual").lower()
        trigger_config = {}
        if trigger_type == "interval":
            trigger_config = {"seconds": int(options.get("seconds") or 0)}
        elif trigger_type == "daily":
            trigger_config = {"at": options.get("at") or ""}
        try:
            workflow_id = workflow_service.create(
                name,
                steps,
                description=str(options.get("description") or ""),
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                cooldown_seconds=int(options.get("cooldown_seconds") or 60),
            )
        except (WorkflowError, WorkflowUnavailable, SimulationError) as exc:
            return await ctx.reply(ascii.warning("Workflow rejected", [str(exc)]))
        return await ctx.reply(
            ascii.success(
                "Workflow saved",
                [
                    f"ID: {workflow_id}",
                    f"Name: {name}",
                    f"Trigger: {trigger_type}",
                    "State: OFF — enable it with .workflow enable " + name,
                ],
            )
        )

    if action == "list":
        rows = workflow_service.list(limit=30)
        if not rows:
            return await ctx.reply(
                ascii.info("No workflows", ["Create one with: .workflow add <name> <json>"])
            )
        lines = [
            f"#{row['id']} {'ON ' if row['enabled'] else 'OFF'} {row['name']} "
            f"· {row['step_count']} steps · {row['trigger_type']} · runs {row['run_count']}"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Workflows", lines))

    if action in {"enable", "disable"}:
        hint = require("workflows")
        if hint:
            return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        if len(ctx.args) < 2:
            return await ctx.reply_usage(f"Example: .workflow {action} daily-digest")
        enabled = action == "enable"
        try:
            found = workflow_service.set_enabled(ctx.args[1], enabled)
        except WorkflowUnavailable as exc:
            return await ctx.reply(ascii.warning("Feature is OFF", [str(exc)]))
        if not found:
            return await ctx.reply(ascii.warning("Not found", ["No workflow with that name or ID."]))
        return await ctx.reply(
            ascii.success(
                "Workflow updated",
                [f"Name: {ctx.args[1]}", f"State: {'ON' if enabled else 'OFF'}"],
            )
        )

    if action == "run":
        hint = require("workflows")
        if hint:
            return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .workflow run daily-digest")
        try:
            result = await workflow_service.run(ctx.args[1], manual=True)
        except (WorkflowError, WorkflowUnavailable) as exc:
            return await ctx.reply(ascii.warning("Workflow failed", [str(exc)]))
        run = result.get("run") or {}
        lines = [
            f"Status: {result.get('status')}",
            f"Run ID: {run.get('id')}",
        ]
        if result.get("error"):
            lines.append(f"Error: {result['error']}")
        return await ctx.reply(ascii.section("Workflow run", lines))

    if action == "history":
        identifier = ctx.args[1] if len(ctx.args) > 1 else ""
        rows = workflow_service.history(identifier, limit=15)
        if not rows:
            return await ctx.reply(ascii.info("No runs", ["Run a workflow to see history."]))
        lines = [
            f"#{row['id']} wf{row['workflow_id']} [{row['status']}] attempts {row['attempts']} "
            f"· {row['started_at']}"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Workflow history", lines))

    if action == "resume":
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .workflow resume 7")
        try:
            result = await workflow_service.resume(int(ctx.args[1]))
        except (WorkflowError, WorkflowUnavailable) as exc:
            return await ctx.reply(ascii.warning("Resume failed", [str(exc)]))
        return await ctx.reply(
            ascii.success("Workflow resumed", [f"Status: {result.get('status')}"])
        )

    if action == "cancel":
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .workflow cancel 7")
        cancelled = workflow_service.cancel(int(ctx.args[1]))
        if not cancelled:
            return await ctx.reply(ascii.warning("Not running", ["No pending or running run with that ID."]))
        return await ctx.reply(ascii.success("Run cancelled", [f"Run: {ctx.args[1]}"]))

    if action == "delete":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .workflow delete daily-digest")
        if not workflow_service.delete(ctx.args[1]):
            return await ctx.reply(ascii.warning("Not found", ["No workflow with that name or ID."]))
        return await ctx.reply(ascii.success("Workflow deleted", [f"Name: {ctx.args[1]}"]))

    return await ctx.reply_usage("Subcommands: list, simulate, add, enable, disable, run, history, resume, cancel, delete.")
