"""
Automation rule management.

Syntax (pipe-separated segments, ``key=value`` pairs):

. automation create <name> | trigger=schedule at=18:30 | action=notify text=Daily review
. automation create <name> | trigger=keyword text=deploy | action=save
. automation create <name> | trigger=interval minutes=60 | action=remind text=Check the queue

Rules are created disabled; enabling is a separate, validated step. Outbound
actions (notify, command) only run for rules created by the account owner.
"""

import re

from reze.automation.engine import (
    ACTION_TYPES,
    COMMAND_ALLOWLIST,
    TRIGGER_TYPES,
    AutomationError,
    automation_engine,
)
from reze.command_router import CommandContext, router
from reze.ui import ascii

CATEGORY = "Automation"


def _parse_segments(raw: str):
    """Split ``trigger=... | action=...`` into typed dictionaries."""
    segments = [part.strip() for part in raw.split("|") if part.strip()]
    parsed = []
    for segment in segments:
        tokens = re.split(r"\s+(?=[A-Za-z_]+=)", segment)
        head = tokens[0]
        key, _, value = head.partition("=")
        data = {key.strip().lower(): value.strip()}
        for token in tokens[1:]:
            extra_key, _, extra_value = token.partition("=")
            data[extra_key.strip().lower()] = extra_value.strip()
        parsed.append(data)
    return parsed


def _build_rule(raw: str):
    name, _, rest = raw.partition("|")
    name = name.strip().lower()
    if not name:
        raise AutomationError("A rule name is required before the first '|'.")
    segments = _parse_segments(rest.replace("\n", " "))

    trigger_type = ""
    trigger_config = {}
    actions = []
    for segment in segments:
        if "trigger" in segment:
            trigger_type = segment.get("trigger", "")
            params = {k: v for k, v in segment.items() if k != "trigger"}
            if trigger_type == "schedule":
                trigger_config = {"at": params.get("at", "")}
            elif trigger_type == "interval":
                try:
                    trigger_config = {"minutes": int(params.get("minutes", "60"))}
                except ValueError as exc:
                    raise AutomationError("minutes must be a whole number.") from exc
            elif trigger_type == "keyword":
                trigger_config = {"text": params.get("text", "")}
            elif trigger_type == "task_failed":
                trigger_config = {}
            else:
                raise AutomationError("trigger must be one of: " + ", ".join(TRIGGER_TYPES))
        elif "action" in segment:
            action_type = segment.get("action", "")
            payload = {k: v for k, v in segment.items() if k != "action"}
            action = {"type": action_type, **payload}
            actions.append(action)

    if not trigger_type:
        raise AutomationError("A trigger segment is required, for example: trigger=schedule at=18:30")
    if not actions:
        raise AutomationError("At least one action segment is required.")
    return name, trigger_type, trigger_config, actions


@router.register(
    name="automation",
    category=CATEGORY,
    description="Create and manage trigger → condition → action rules.",
    usage=".automation <list|show|create|enable|disable|delete> ...",
    owner_only=True,
    aliases=["auto"],
)
async def automation_cmd(ctx: CommandContext):
    action = ctx.args[0].lower() if ctx.args else "list"

    if action == "list":
        rules = automation_engine.rules()
        if not rules:
            return await ctx.reply(
                ascii.info(
                    "No automation rules",
                    ["Create one with .automation create <name> | trigger=... | action=..."],
                )
            )
        rows = [
            [
                rule.name,
                "on" if rule.enabled else "off",
                rule.trigger_type,
                ", ".join(entry.get("type", "?") for entry in rule.actions),
                str(rule.run_count),
            ]
            for rule in rules
        ]
        return await ctx.reply(
            ascii.section(
                "Automation rules",
                [
                    ascii.table(["RULE", "STATE", "TRIGGER", "ACTIONS", "RUNS"], rows),
                    "",
                    "Actions: " + ", ".join(ACTION_TYPES),
                    "Allowed commands: " + ", ".join(sorted(COMMAND_ALLOWLIST)),
                ],
            )
        )

    if action == "show":
        if len(ctx.args) < 2:
            return await ctx.reply_usage("Example: .automation show daily-review")
        rule = next((r for r in automation_engine.rules() if r.name == ctx.args[1].lower()), None)
        if rule is None:
            return await ctx.reply(ascii.warning("Unknown rule", [ctx.args[1]]))
        lines = [
            f"State: {'enabled' if rule.enabled else 'disabled'}",
            f"Trigger: {rule.trigger_type} {rule.trigger_config}",
            f"Cooldown: {rule.cooldown_seconds}s",
            f"Runs: {rule.run_count}",
        ]
        if rule.conditions:
            lines.append(f"Conditions: {rule.conditions}")
        lines.append("Actions:")
        for entry in rule.actions:
            lines.append(f"  {entry}")
        if rule.last_error:
            lines.append(f"Last error: {rule.last_error}")
        return await ctx.reply(ascii.frame(f"Rule: {rule.name}", lines))

    if action == "create":
        raw = ctx.raw_text.split(" ", 2)[2] if len(ctx.raw_text.split(" ", 2)) > 2 else ""
        if not raw.strip():
            return await ctx.reply_usage(
                "Example: .automation create daily | trigger=schedule at=18:30 | action=notify text=Review the day"
            )
        try:
            name, trigger_type, trigger_config, actions = _build_rule(raw)
            rule = automation_engine.create(
                name=name,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                actions=actions,
                created_by=ctx.sender_id or 0,
            )
        except AutomationError as exc:
            return await ctx.reply(ascii.error("Rule rejected", [str(exc)]))
        return await ctx.reply(
            ascii.success(
                "Rule created (disabled)",
                [
                    f"Name: {rule.name}",
                    f"Trigger: {rule.trigger_type} {rule.trigger_config}",
                    f"Enable it with: .automation enable {rule.name}",
                ],
            )
        )

    if action in {"enable", "disable", "delete"}:
        if len(ctx.args) < 2:
            return await ctx.reply_usage(f"Example: .automation {action} daily")
        name = ctx.args[1].lower()
        try:
            if action == "enable":
                automation_engine.enable(name)
                return await ctx.reply(ascii.success("Rule enabled", [name]))
            if action == "disable":
                automation_engine.disable(name)
                return await ctx.reply(ascii.info("Rule disabled", [name]))
            deleted = automation_engine.delete(name)
            return await ctx.reply(
                ascii.info("Automation", ["Rule deleted." if deleted else "No such rule."])
            )
        except AutomationError as exc:
            return await ctx.reply(ascii.error("Automation failed", [str(exc)]))

    return await ctx.reply_usage("Actions: list, show, create, enable, disable, delete")
