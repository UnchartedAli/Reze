"""Projects and tasks stored locally in SQLite."""

from reze.command_router import CommandContext, router
from reze.features import require
from reze.personal.projects import PRIORITIES, project_service
from reze.ui import ascii

CATEGORY = "Productivity"


async def _blocked(ctx: CommandContext) -> bool:
    hint = require("projects")
    if hint:
        await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        return True
    return False


@router.register(
    name="project",
    category=CATEGORY,
    description="Create, list and close local projects.",
    usage=".project [list|add <name> [description]|close <name>]",
    aliases=["projects"],
    owner_only=True,
    examples=[".project add REZE 3.0 Website redesign", ".project list", ".project close REZE 3.0"],
)
async def project_cmd(ctx: CommandContext):
    if await _blocked(ctx):
        return
    action = (ctx.args[0].lower() if ctx.args else "list")

    if action == "list":
        rows = project_service.list(status="active")
        if not rows:
            return await ctx.reply(
                ascii.info("No active projects", ["Create one: .project add <name>"])
            )
        lines = [
            f"#{row['id']} {row['name']} — {row['open_tasks']}/{row['total_tasks']} open tasks"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Projects", lines))

    if action == "add":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .project add Website redesign")
        name = ctx.args[1]
        description = " ".join(ctx.args[2:])
        project_id = project_service.create(name, description)
        return await ctx.reply(
            ascii.success("Project saved", [f"ID: {project_id}", f"Name: {name}"])
        )

    if action == "close":
        name = " ".join(ctx.args[1:]).strip()
        if not name:
            return await ctx.reply_usage("Example: .project close Website redesign")
        if not project_service.close(name):
            return await ctx.reply(ascii.warning("Not found", ["No project with that name."]))
        return await ctx.reply(ascii.success("Project closed", [f"Name: {name}"]))

    return await ctx.reply_usage("Subcommands: list, add, close.")


@router.register(
    name="task",
    category=CATEGORY,
    description="Add, list and complete local tasks.",
    usage=".task [list [status]|add <title> [@project] [p:1-5] [due:YYYY-MM-DD]|done <id>|stats]",
    aliases=["tasks"],
    owner_only=True,
    examples=[
        ".task add Write the README @REZE 3.0 p:4 due:2026-11-02",
        ".task list todo",
        ".task done 12",
    ],
)
async def task_cmd(ctx: CommandContext):
    if await _blocked(ctx):
        return
    action = (ctx.args[0].lower() if ctx.args else "list")

    if action == "list":
        status = ctx.args[1].lower() if len(ctx.args) > 1 else ""
        if status and status not in {"todo", "doing", "done", "blocked"}:
            status = ""
        rows = project_service.tasks(status=status, limit=30)
        if not rows:
            return await ctx.reply(ascii.info("No tasks", ["Add one: .task add <title>"]))
        lines = []
        for row in rows:
            due = f" due {row['due_at']}" if row.get("due_at") else ""
            project = f" @{row['project_name']}" if row.get("project_name") else ""
            lines.append(
                f"#{row['id']} [{row['status']}] p{row['priority']} {row['title'][:60]}{project}{due}"
            )
        return await ctx.reply(ascii.section("Tasks", lines))

    if action == "add":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .task add Write the README @REZE p:4")
        project = ""
        priority = 3
        due = ""
        title_parts = []
        for token in ctx.args[1:]:
            lowered = token.lower()
            if lowered.startswith("@"):
                project = token[1:]
            elif lowered.startswith("p:") and lowered[2:].isdigit():
                priority = max(1, min(int(lowered[2:]), 5))
            elif lowered.startswith("due:"):
                due = token.split(":", 1)[1]
            else:
                title_parts.append(token)
        title = " ".join(title_parts).strip()
        if not title:
            return await ctx.reply_usage("A task needs a title.")
        task_id = project_service.add_task(title, project=project, priority=priority, due_at=due)
        return await ctx.reply(
            ascii.success(
                "Task added",
                [
                    f"ID: {task_id}",
                    f"Priority: {priority} ({PRIORITIES.get(priority, '-')})",
                    f"Project: {project or '-'}",
                ],
            )
        )

    if action in {"done", "complete"}:
        if len(ctx.args) < 2 or not ctx.args[1].isdigit():
            return await ctx.reply_usage("Example: .task done 12")
        if not project_service.complete(int(ctx.args[1])):
            return await ctx.reply(ascii.warning("Not found", ["No task with that ID."]))
        return await ctx.reply(ascii.success("Task completed", [f"ID: {ctx.args[1]}"]))

    if action == "stats":
        summary = project_service.summary()
        return await ctx.reply(
            ascii.section(
                "Tasks",
                [
                    f"Open: {summary['open']}",
                    f"Done: {summary['done']}",
                    f"Overdue: {summary['overdue']}",
                ],
            )
        )

    return await ctx.reply_usage("Subcommands: list, add, done, stats.")
