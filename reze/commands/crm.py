"""Personal CRM commands: contacts, interactions and relationship reminders."""

from reze.command_router import CommandContext, router
from reze.features import require
from reze.personal.crm import crm_service
from reze.ui import ascii

CATEGORY = "Personal"


async def _blocked(ctx: CommandContext) -> bool:
    hint = require("crm")
    if hint:
        await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        return True
    return False


def _contact_line(row) -> str:
    last = row.get("last_contact_at") or "never"
    return f"{row['name']} · @{row.get('username') or '-'} · last: {last}"


@router.register(
    name="crm",
    category=CATEGORY,
    description="Manage contacts, interaction history and birthdays locally.",
    usage=".crm [list|add <name> [@user] [birthday:YYYY-MM-DD] [tags:a,b]|show <name>|log <name> <summary>|birthday [days]|stale [days]|delete <name>]",
    owner_only=True,
    examples=[
        ".crm add Sara @sara birthday:1994-05-12 tags:work",
        ".crm log Sara We reviewed the roadmap",
        ".crm birthday 30",
    ],
)
async def crm_cmd(ctx: CommandContext):
    if await _blocked(ctx):
        return
    action = (ctx.args[0].lower() if ctx.args else "list")

    if action == "list":
        rows = crm_service.list(limit=30)
        if not rows:
            return await ctx.reply(ascii.info("No contacts", ["Add one: .crm add Sara @sara"]))
        return await ctx.reply(
            ascii.section(f"Contacts · {len(rows)}", [_contact_line(row) for row in rows])
        )

    if action == "add":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .crm add Sara @sara birthday:1994-05-12")
        name = ctx.args[1]
        username = ""
        birthday = ""
        tags = ""
        notes = []
        for token in ctx.args[2:]:
            lowered = token.lower()
            if lowered.startswith("@"):
                username = token
            elif lowered.startswith("birthday:"):
                birthday = token.split(":", 1)[1]
            elif lowered.startswith("tags:"):
                tags = token.split(":", 1)[1]
            else:
                notes.append(token)
        contact_id = crm_service.save(
            name,
            username=username,
            tags=tags,
            notes=" ".join(notes),
            birthday=birthday,
        )
        return await ctx.reply(
            ascii.success(
                "Contact saved",
                [f"Name: {name}", f"ID: {contact_id}", f"Birthday: {birthday or '-'}"],
            )
        )

    if action == "show":
        name = " ".join(ctx.args[1:]).strip()
        row = crm_service.get(name) if name else None
        if not row:
            return await ctx.reply(ascii.warning("Not found", ["Use .crm list to see names."]))
        interactions = crm_service.interactions(name, limit=10)
        lines = [
            f"Username: @{row.get('username') or '-'}",
            f"Birthday: {row.get('birthday') or '-'}",
            f"Tags: {row.get('tags') or '-'}",
            f"Last contact: {row.get('last_contact_at') or 'never'}",
            f"Notes: {row.get('notes') or '-'}",
        ]
        if interactions:
            lines.append("")
            lines.append("Recent interactions:")
            lines.extend(
                f"  {item['occurred_at']} [{item['kind']}] {item['summary'][:80]}"
                for item in interactions
            )
        return await ctx.reply(ascii.section(f"Contact: {name}", lines))

    if action == "log":
        if len(ctx.args) < 3:
            return await ctx.reply_usage("Example: .crm log Sara We reviewed the roadmap")
        name = ctx.args[1]
        summary = " ".join(ctx.args[2:])
        try:
            interaction_id = crm_service.log_interaction(name, "note", summary)
        except ValueError as exc:
            return await ctx.reply(ascii.warning("Unknown contact", [str(exc)]))
        return await ctx.reply(
            ascii.success("Interaction logged", [f"Contact: {name}", f"ID: {interaction_id}"])
        )

    if action == "birthday":
        days = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 30
        rows = crm_service.upcoming_birthdays(days=days)
        if not rows:
            return await ctx.reply(
                ascii.info("No birthdays", [f"No birthdays in the next {days} days."])
            )
        lines = [
            f"{row['name']} — {row['next_birthday']} (in {row['in_days']} days)" for row in rows
        ]
        return await ctx.reply(ascii.section(f"Birthdays · {days} days", lines))

    if action == "stale":
        days = int(ctx.args[1]) if len(ctx.args) > 1 and ctx.args[1].isdigit() else 30
        rows = crm_service.stale(days=days)
        if not rows:
            return await ctx.reply(ascii.info("All fresh", [f"Nobody is older than {days} days."]))
        lines = [
            f"{row['name']} — last: {row.get('last_contact_at') or 'never'}" for row in rows
        ]
        return await ctx.reply(ascii.section(f"Follow up · {days} days", lines))

    if action == "delete":
        name = " ".join(ctx.args[1:]).strip()
        if not name:
            return await ctx.reply_usage("Example: .crm delete Sara")
        if not crm_service.delete(name):
            return await ctx.reply(ascii.warning("Not found", ["No contact with that name."]))
        return await ctx.reply(ascii.success("Contact deleted", [f"Name: {name}"]))

    return await ctx.reply_usage("Subcommands: list, add, show, log, birthday, stale, delete.")
