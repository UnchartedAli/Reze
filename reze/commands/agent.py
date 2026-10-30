"""
AI Agent command surface: proposals, approvals and audit history.

The model can only *propose* an allowlisted tool. Nothing runs until the owner
sends the six-digit approval code. Every proposal and execution is audited.
"""

import json

from reze.ai.agent import AgentUnavailable, agent_service
from reze.ai.budget import snapshot as budget_snapshot
from reze.ai.council import CouncilUnavailable, council_service
from reze.ai.tools.registry import (
    APPROVAL_TTL_MINUTES,
    TOOLS,
    ToolError,
    describe_tools,
    tool_registry,
)
from reze.command_router import CommandContext, router
from reze.features import require
from reze.ui import ascii

CATEGORY = "AI"


@router.register(
    name="agent",
    category=CATEGORY,
    description="Let the AI propose an allowlisted tool; you approve before it runs.",
    usage=".agent [tools|run <request>|call <tool> <json>|pending|approve <code>|deny <code>|history|budget]",
    owner_only=True,
    cooldown=5,
    examples=[
        ".agent tools",
        ".agent run save a memory that I prefer dark themes",
        '.agent call memory.save {"content": "I prefer dark themes"}',
        ".agent approve 123456",
    ],
)
async def agent_cmd(ctx: CommandContext):
    action = (ctx.args[0].lower() if ctx.args else "status")

    if action == "tools":
        rows = describe_tools()
        lines = [
            f"{row['name']} · feature {row['feature']} · {'ready' if row['enabled'] else 'needs feature'}"
            for row in rows
        ]
        lines.append("")
        lines.append("Tools only run after .agent approve <code>.")
        return await ctx.reply(ascii.section("AI tools", lines))

    if action == "run":
        hint = require("ai_agent")
        if hint:
            return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        request = " ".join(ctx.args[1:]).strip()
        if not request:
            return await ctx.reply_usage("Example: .agent run save a memory that I prefer dark themes")
        try:
            proposal = await agent_service.propose_from_text(
                request, chat_id=ctx.chat_id or 0, actor=ctx.sender_id or 0
            )
        except (AgentUnavailable, ToolError) as exc:
            return await ctx.reply(ascii.warning("Agent unavailable", [str(exc)]))
        return await ctx.reply(_proposal_panel(proposal))

    if action == "call":
        hint = require("ai_agent")
        if hint:
            return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
        if len(ctx.args) < 3:
            return await ctx.reply_usage('Example: .agent call memory.save {"content": "note"}')
        tool = ctx.args[1]
        raw = " ".join(ctx.args[2:])
        try:
            args = json.loads(raw)
        except ValueError as exc:
            return await ctx.reply(ascii.warning("Invalid JSON", [str(exc)]))
        if not isinstance(args, dict):
            return await ctx.reply(ascii.warning("Invalid arguments", ["Tool arguments must be a JSON object."]))
        try:
            proposal = await agent_service.propose_direct(
                tool, args, chat_id=ctx.chat_id or 0, actor=ctx.sender_id or 0
            )
        except (AgentUnavailable, ToolError) as exc:
            return await ctx.reply(ascii.warning("Proposal rejected", [str(exc)]))
        return await ctx.reply(_proposal_panel(proposal))

    if action == "pending":
        rows = tool_registry.pending(limit=10)
        if not rows:
            return await ctx.reply(ascii.info("No pending approvals", ["Nothing is waiting to run."]))
        lines = [
            f"#{row['id']} {row['tool']} · code {ascii.code(row['code'])} · expires {row['expires_at']}"
            for row in rows
        ]
        return await ctx.reply(ascii.section("Pending approvals", lines))

    if action == "approve":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .agent approve 123456")
        try:
            result = await tool_registry.approve(ctx.args[1], actor=ctx.sender_id or 0)
        except ToolError as exc:
            return await ctx.reply(ascii.warning("Approval failed", [str(exc)]))
        return await ctx.reply(
            ascii.success(
                "Tool executed",
                [f"Tool: {result['tool']}", f"Result: {str(result['result'])[:500]}"],
                footer="Recorded in the local audit log",
            )
        )

    if action in {"deny", "cancel"}:
        if len(ctx.args) < 2:
            return await ctx.reply_usage(f"Example: .agent {action} 123456")
        denied = tool_registry.deny(ctx.args[1], actor=ctx.sender_id or 0)
        if not denied:
            return await ctx.reply(ascii.warning("Not found", ["No pending approval with that code."]))
        return await ctx.reply(ascii.success("Proposal denied", [f"Code: {ctx.args[1]}"]))

    if action == "history":
        rows = tool_registry.history(limit=15)
        if not rows:
            return await ctx.reply(ascii.info("No history", ["No tool proposal has been made yet."]))
        lines = [
            f"#{row['id']} [{row['status']}] {row['tool']} · {row['created_at']}"
            for row in rows
        ]
        return await ctx.reply(ascii.section("AI tool audit", lines))

    if action == "budget":
        data = budget_snapshot()
        lines = [
            f"Used today: {data['used']}/{data['limit']}",
            f"Remaining: {data['remaining']}",
        ]
        for row in data["by_model"]:
            lines.append(
                f"{row['provider']}/{row['model']} · {row['kind']} · {row['calls']} calls"
            )
        return await ctx.reply(ascii.section("AI budget", lines))

    if action != "status":
        return await ctx.reply_usage("Subcommands: tools, run, call, pending, approve, deny, history, budget.")

    hint = require("ai_agent")
    lines = [
        f"Feature: {'ON' if not hint else 'OFF'}",
        f"Provider configured: {'yes' if agent_service.configured() else 'no'}",
        "Approval codes expire after " + str(APPROVAL_TTL_MINUTES) + " minutes.",
        "Tools: " + ", ".join(tool.name for tool in TOOLS.values()),
    ]
    if hint:
        lines.append(hint)
    return await ctx.reply(ascii.section("AI Agent", lines))


def _proposal_panel(proposal) -> str:
    return ascii.warning(
        "Approval required",
        [
            f"Tool: {proposal['tool']}",
            f"Arguments: {json.dumps(proposal.get('args') or {}, ensure_ascii=False)[:500]}",
            f"Code: {ascii.code(proposal['code'])} (expires {proposal['expires']} UTC)",
            f"Approve with: .agent approve {proposal['code']}",
            "Nothing has executed yet.",
        ],
    )


@router.register(
    name="council",
    category=CATEGORY,
    description="Ask several configured models and synthesize one answer.",
    usage=".council <question>",
    owner_only=True,
    cooldown=10,
    examples=[".council What are the tradeoffs of SQLite WAL mode?"],
)
async def council_cmd(ctx: CommandContext):
    hint = require("model_council")
    if hint:
        return await ctx.reply(ascii.warning("Feature is OFF", [hint]))
    question = ctx.args_text.strip()
    if not question:
        return await ctx.reply_usage("Example: .council What are the tradeoffs of WAL mode?")
    try:
        result = await council_service.ask(question)
    except CouncilUnavailable as exc:
        return await ctx.reply(ascii.warning("Council unavailable", [str(exc)]))
    lines = [result["synthesis"], "", f"Note: {result['note']}"]
    for answer in result["answers"]:
        lines.append(f"{answer['provider']}/{answer['model']}: {len(answer['text'])} chars")
    if result.get("errors"):
        lines.append("Errors: " + "; ".join(result["errors"]))
    return await ctx.reply(ascii.section("Model Council", lines))
