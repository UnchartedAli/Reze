"""Dry-run simulator for persistent workflows.

The simulator validates a workflow definition and renders every step with the
provided context, without sending messages, writing rows or calling the AI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

MAX_STEPS = 20
MAX_TEXT = 4000

ALLOWED_ACTIONS = {
    "send_message": {"chat_id", "text"},
    "notify_owner": {"text"},
    "save_memory": {"content", "tags"},
    "add_timeline": {"kind", "title", "body"},
    "add_task": {"title", "project", "priority"},
    "add_reminder": {"text", "minutes"},
    "log": {"message"},
    "wait": {"seconds"},
}

REQUIRED_FIELDS = {
    "send_message": {"chat_id", "text"},
    "notify_owner": {"text"},
    "save_memory": {"content"},
    "add_timeline": {"title"},
    "add_task": {"title"},
    "add_reminder": {"text", "minutes"},
    "log": {"message"},
    "wait": {"seconds"},
}


class SimulationError(ValueError):
    """A workflow step is invalid."""


@dataclass
class StepReport:
    index: int
    action: str
    status: str
    detail: str


@dataclass
class SimulationReport:
    valid: bool
    steps: List[StepReport] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def lines(self) -> List[str]:
        rows = [f"{step.index}. {step.action} [{step.status}] {step.detail}" for step in self.steps]
        if self.errors:
            rows.append("")
            rows.extend(f"! {error}" for error in self.errors)
        rows.append("")
        rows.append("Dry run: no message was sent and no row was written.")
        return rows


class _SafeDict(dict):
    def __missing__(self, key):  # noqa: D105 - template placeholder kept visible
        return "{" + key + "}"


def render(template: str, context: Mapping[str, Any]) -> str:
    text = "" if template is None else str(template)
    try:
        return text.format_map(_SafeDict(context or {}))[:MAX_TEXT]
    except (ValueError, IndexError):
        return text[:MAX_TEXT]


def parse_steps(raw: Any) -> List[Dict[str, Any]]:
    """Accept a JSON string or a list and return normalized steps."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "[]")
        except ValueError as exc:
            raise SimulationError(f"Steps are not valid JSON: {exc}") from exc
    if not isinstance(raw, list):
        raise SimulationError("Steps must be a list.")
    if len(raw) > MAX_STEPS:
        raise SimulationError(f"A workflow can have at most {MAX_STEPS} steps.")
    steps = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise SimulationError(f"Step {index} must be an object.")
        action = str(item.get("action") or "").strip().lower()
        if action not in ALLOWED_ACTIONS:
            raise SimulationError(
                f"Step {index}: unknown action '{action}'. Allowed: {', '.join(sorted(ALLOWED_ACTIONS))}"
            )
        unknown = set(item) - ALLOWED_ACTIONS[action] - {"action"}
        if unknown:
            raise SimulationError(f"Step {index}: unknown fields: {', '.join(sorted(unknown))}")
        missing = REQUIRED_FIELDS[action] - set(item)
        if missing:
            raise SimulationError(f"Step {index}: missing fields: {', '.join(sorted(missing))}")
        steps.append({"action": action, **{key: value for key, value in item.items() if key != "action"}})
    return steps


def simulate(raw_steps: Any, context: Dict[str, Any] | None = None) -> SimulationReport:
    context = context or {}
    report = SimulationReport(valid=True)
    try:
        steps = parse_steps(raw_steps)
    except SimulationError as exc:
        return SimulationReport(valid=False, errors=[str(exc)])
    if not steps:
        return SimulationReport(valid=False, errors=["A workflow needs at least one step."])

    for index, step in enumerate(steps, start=1):
        action = step["action"]
        try:
            if action == "send_message":
                text = render(step.get("text", ""), context)
                chat = step.get("chat_id")
                if not text.strip():
                    raise SimulationError("empty text")
                report.steps.append(StepReport(index, action, "ok", f"would send {len(text)} chars to {chat}"))
            elif action == "notify_owner":
                text = render(step.get("text", ""), context)
                report.steps.append(StepReport(index, action, "ok", f"would notify the owner ({len(text)} chars)"))
            elif action == "save_memory":
                text = render(step.get("content", ""), context)
                report.steps.append(StepReport(index, action, "ok", f"would save a {len(text)}-char memory"))
            elif action == "add_timeline":
                title = render(step.get("title", ""), context)
                report.steps.append(StepReport(index, action, "ok", f"would append timeline event '{title[:40]}'"))
            elif action == "add_task":
                title = render(step.get("title", ""), context)
                report.steps.append(StepReport(index, action, "ok", f"would add task '{title[:40]}'"))
            elif action == "add_reminder":
                text = render(step.get("text", ""), context)
                minutes = int(step.get("minutes") or 0)
                if minutes <= 0 or minutes > 525600:
                    raise SimulationError("minutes must be between 1 and 525600")
                report.steps.append(StepReport(index, action, "ok", f"would remind in {minutes} min: {text[:40]}"))
            elif action == "log":
                message = render(step.get("message", ""), context)
                report.steps.append(StepReport(index, action, "ok", f"would log: {message[:60]}"))
            elif action == "wait":
                seconds = int(step.get("seconds") or 0)
                if seconds < 0 or seconds > 60:
                    raise SimulationError("wait is limited to 0-60 seconds")
                report.steps.append(StepReport(index, action, "ok", f"would wait {seconds}s"))
        except (TypeError, ValueError, SimulationError) as exc:
            report.valid = False
            report.errors.append(f"Step {index}: {exc}")
            report.steps.append(StepReport(index, action, "invalid", str(exc)))
    return report


__all__ = [
    "ALLOWED_ACTIONS",
    "MAX_STEPS",
    "SimulationError",
    "SimulationReport",
    "StepReport",
    "parse_steps",
    "render",
    "simulate",
]
