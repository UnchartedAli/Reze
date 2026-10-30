"""
Knowledge commands: persistent memory, timeline and the Life Graph.

All three features are optional and OFF by default. Each command checks its own
feature only — using memory never turns the timeline on.
"""

from reze.command_router import CommandContext, router
from reze.features import require
from reze.personal.life_graph import ENTITY_KINDS, life_graph
from reze.personal.memory import memory_service
from reze.personal.timeline import timeline_service
from reze.ui import ascii

CATEGORY = "Knowledge"


def _snippet(value: str, size: int = 90) -> str:
    text = " ".join((value or "").split())
    return text[:size] + ("..." if len(text) > size else "")


async def _blocked(ctx: CommandContext, key: str) -> bool:
    hint = require(key)
    if hint:
        await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        return True
    return False


# ----------------------------------------------------------------------- memory
@router.register(
    name="memory",
    category=CATEGORY,
    description="Save and search durable memories the AI can recall.",
    usage=".memory [recent|add <text>|search <query>|show <id>|forget <id>|pin <id>|archive <id>]",
    owner_only=True,
    examples=[".memory", ".memory add I prefer UTC deadlines", ".memory search deadline"],
)
async def memory_cmd(ctx: CommandContext):
    if await _blocked(ctx, "memory"):
        return
    action = (ctx.args[0].lower() if ctx.args else "recent")
    rest = ctx.args[1:]

    if action in {"recent", "list", "last"}:
        rows = memory_service.recent(limit=15)
        if not rows:
            return await ctx.reply(
                ascii.info("Memory is empty", ["Add one with: .memory add <text>"])
            )
        lines = []
        for row in rows:
            pin = "pinned " if row.get("pinned") else ""
            lines.append(
                f"#{row['id']} {pin}[{row['importance']}/5] {_snippet(row.get('content', ''), 80)}"
            )
        return await ctx.reply(ascii.section(f"Memories · {len(rows)}", lines))

    if action == "add":
        reply = await ctx.get_reply_message()
        text = " ".join(rest).strip() or (getattr(reply, "message", "") if reply else "")
        if not text:
            return await ctx.reply_usage("Example: .memory add I prefer short answers")
        memory_id = memory_service.save(text, source="command", source_ref=str(ctx.chat_id or ""))
        return await ctx.reply(
            ascii.success("Memory saved", [f"ID: {ascii.code(memory_id)}", f"Chars: {len(text)}"])
        )

    if action == "search":
        query = " ".join(rest).strip()
        if not query:
            return await ctx.reply_usage("Example: .memory search deadlines")
        rows = memory_service.search(query, limit=10)
        if not rows:
            return await ctx.reply(ascii.info("No matches", [f"Nothing stored matches '{query}'."]))
        lines = [f"#{row['id']} {_snippet(row.get('content', ''), 90)}" for row in rows]
        return await ctx.reply(ascii.section(f"Memory: {query}", lines))

    if action in {"show", "get"}:
        if not rest or not rest[0].isdigit():
            return await ctx.reply_usage("Example: .memory show 3")
        row = memory_service.get(int(rest[0]))
        if not row:
            return await ctx.reply(ascii.warning("Not found", ["No memory with that ID."]))
        lines = [
            f"Source: {row.get('source') or 'manual'}",
            f"Importance: {row.get('importance')}/5",
            f"Tags: {row.get('tags') or '-'}",
            f"Created: {row.get('created_at')}",
            "",
            row.get("content") or "",
        ]
        return await ctx.reply(ascii.section(f"Memory #{row['id']}", lines))

    if action == "forget":
        if not rest or not rest[0].isdigit():
            return await ctx.reply_usage("Example: .memory forget 3")
        removed = memory_service.forget(int(rest[0]))
        if not removed:
            return await ctx.reply(ascii.warning("Not found", ["No memory with that ID."]))
        return await ctx.reply(ascii.success("Memory deleted", [f"ID: {rest[0]}", "The search index was updated."]))

    if action in {"pin", "unpin"}:
        if not rest or not rest[0].isdigit():
            return await ctx.reply_usage("Example: .memory pin 3")
        pinned = action == "pin"
        if not memory_service.get(int(rest[0])):
            return await ctx.reply(ascii.warning("Not found", ["No memory with that ID."]))
        memory_service.pin(int(rest[0]), pinned)
        return await ctx.reply(
            ascii.success("Memory updated", [f"ID: {rest[0]}", f"Pinned: {'yes' if pinned else 'no'}"])
        )

    if action == "archive":
        if not rest or not rest[0].isdigit():
            return await ctx.reply_usage("Example: .memory archive 3")
        if not memory_service.get(int(rest[0])):
            return await ctx.reply(ascii.warning("Not found", ["No memory with that ID."]))
        memory_service.archive(int(rest[0]), True)
        return await ctx.reply(ascii.success("Memory archived", [f"ID: {rest[0]}"]))

    return await ctx.reply_usage("Subcommands: recent, add, search, show, forget, pin, archive.")


# --------------------------------------------------------------------- timeline
@router.register(
    name="timeline",
    category=CATEGORY,
    description="Show the chronological stream of events recorded in REZE.",
    usage=".timeline [events] [kind]",
    owner_only=True,
    examples=[".timeline", ".timeline 40 focus"],
)
async def timeline_cmd(ctx: CommandContext):
    if await _blocked(ctx, "timeline"):
        return
    limit = 20
    kind = ""
    for arg in ctx.args:
        if arg.isdigit():
            limit = max(1, min(int(arg), 100))
        elif arg.strip():
            kind = arg.strip().lower()
    rows = timeline_service.recent(limit=limit, kind=kind or None)
    if not rows:
        return await ctx.reply(
            ascii.info("Timeline is empty", ["Events appear as you use REZE 3.0 features."])
        )
    lines = [f"{row['created_at']} [{row['kind']}] {_snippet(row['title'], 60)}" for row in rows]
    header = f"Timeline · last {len(rows)}" + (f" · {kind}" if kind else "")
    return await ctx.reply(ascii.section(header, lines))


# -------------------------------------------------------------------- life graph
@router.register(
    name="graph",
    category=CATEGORY,
    description="Connect people, projects, places and topics in the Life Graph.",
    usage=".graph [list [kind]|add <kind> <name> [notes]|link <a> | <relation> | <b>|show <name>]",
    owner_only=True,
    examples=[
        ".graph add person Sara",
        ".graph link Sara | works with | Reze",
        ".graph show Sara",
    ],
)
async def graph_cmd(ctx: CommandContext):
    if await _blocked(ctx, "life_graph"):
        return
    action = (ctx.args[0].lower() if ctx.args else "list")

    if action == "list":
        kind = ctx.args[1].lower() if len(ctx.args) > 1 else ""
        rows = life_graph.entities(kind=kind, limit=40)
        if not rows:
            return await ctx.reply(
                ascii.info("Graph is empty", ["Add an entity: .graph add person Sara"])
            )
        lines = [f"#{row['id']} [{row['kind']}] {row['name']}" for row in rows]
        return await ctx.reply(ascii.section("Life Graph", lines))

    if action == "add":
        if len(ctx.args) < 3:
            return await ctx.reply_usage(
                "Kinds: " + ", ".join(ENTITY_KINDS) + ". Example: .graph add person Sara"
            )
        kind = ctx.args[1].lower()
        name = ctx.args[2]
        notes = " ".join(ctx.args[3:])
        entity_id = life_graph.add_entity(kind, name, notes)
        return await ctx.reply(
            ascii.success("Graph updated", [f"Entity: {name}", f"Kind: {kind}", f"ID: {entity_id}"])
        )

    if action == "link":
        raw = ctx.args_text[len(ctx.args[0]):].strip() if ctx.args else ""
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) != 3 or not all(parts):
            return await ctx.reply_usage("Example: .graph link Sara | works with | Reze")
        relation_id = life_graph.link(parts[0], parts[1], parts[2])
        return await ctx.reply(
            ascii.success(
                "Relation saved",
                [f"{parts[0]} --{parts[1]}--> {parts[2]}", f"ID: {relation_id}"],
            )
        )

    if action == "show":
        name = " ".join(ctx.args[1:]).strip()
        if not name:
            return await ctx.reply_usage("Example: .graph show Sara")
        rows = life_graph.neighbors(name)
        if not rows:
            return await ctx.reply(ascii.info("No relations", [f"Nothing is linked to '{name}'."]))
        lines = []
        for row in rows:
            arrow = "-->" if row.get("direction") == "out" else "<--"
            lines.append(f"{arrow} [{row['kind']}] {row['name']} ({row['relation']})")
        return await ctx.reply(ascii.section(f"Graph: {name}", lines))

    return await ctx.reply_usage("Subcommands: list, add, link, show.")
