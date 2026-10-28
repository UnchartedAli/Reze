"""
Small, safe automation engine: trigger → conditions → actions.

Design constraints that are enforced in code:

* rules are validated before they can be enabled;
* time rules run at most once per period, keyword rules at most once per
  cooldown, and every rule has an hourly run cap;
* recursion is bounded: actions that dispatch a command cannot re-enter the
  engine more than two levels deep;
* outbound messages (``notify``) and command dispatch require a rule created by
  the account owner;
* there is no shell execution and no arbitrary Python: the ``command`` action
  dispatches a fixed allowlist of safe internal commands through the router.

The engine is deliberately not a general workflow system.
"""

import asyncio
import contextvars
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from reze.command_router import router
from reze.config import settings
from reze.database import db
from reze.exceptions import AIError, RezeException
from reze.logging_config import logger
from reze.ui import ascii

TRIGGER_TYPES = ("schedule", "interval", "keyword", "task_failed")
ACTION_TYPES = ("remind", "save", "notify", "ai_summary", "command")
COMMAND_ALLOWLIST = {"remind", "save", "notes", "qr", "ping", "aiinfo", "id", "version"}
MAX_DEPTH = 2

_DEPTH: contextvars.ContextVar[int] = contextvars.ContextVar("reze_automation_depth", default=0)


class AutomationError(RezeException):
    """Raised when a rule is invalid or cannot run."""


@dataclass
class Rule:
    name: str
    enabled: bool
    trigger_type: str
    trigger_config: Dict[str, Any] = field(default_factory=dict)
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    actions: List[Dict[str, Any]] = field(default_factory=list)
    cooldown_seconds: int = 60
    created_by: int = 0
    run_count: int = 0
    last_run: Optional[str] = None
    last_error: str = ""

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Rule":
        return cls(
            name=row["name"],
            enabled=bool(row.get("enabled")),
            trigger_type=row.get("trigger_type", ""),
            trigger_config=json.loads(row.get("trigger_config") or "{}"),
            conditions=json.loads(row.get("conditions") or "[]"),
            actions=json.loads(row.get("actions") or "[]"),
            cooldown_seconds=int(row.get("cooldown_seconds") or 60),
            created_by=int(row.get("created_by") or 0),
            run_count=int(row.get("run_count") or 0),
            last_run=row.get("last_run"),
            last_error=row.get("last_error") or "",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "trigger_type": self.trigger_type,
            "trigger_config": self.trigger_config,
            "conditions": self.conditions,
            "actions": self.actions,
            "cooldown_seconds": self.cooldown_seconds,
            "run_count": self.run_count,
            "last_run": self.last_run,
            "last_error": self.last_error,
        }


def validate_rule(
    name: str,
    trigger_type: str,
    trigger_config: Dict[str, Any],
    conditions: List[Dict[str, Any]],
    actions: List[Dict[str, Any]],
    cooldown_seconds: int = 60,
) -> List[str]:
    """Return a list of human-readable problems; empty means valid."""
    problems: List[str] = []
    if not name or not name.strip():
        problems.append("A rule name is required.")
    elif len(name) > 40:
        problems.append("Rule names are limited to 40 characters.")

    if trigger_type not in TRIGGER_TYPES:
        problems.append("Trigger must be one of: " + ", ".join(TRIGGER_TYPES))

    if trigger_type == "schedule":
        at = str(trigger_config.get("at", ""))
        try:
            hour, minute = [int(part) for part in at.split(":")]
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except (ValueError, TypeError):
            problems.append("Schedule triggers need at='HH:MM' (24-hour clock).")
    elif trigger_type == "interval":
        try:
            minutes = int(trigger_config.get("minutes", 0))
            if not 1 <= minutes <= 1440:
                raise ValueError
        except (TypeError, ValueError):
            problems.append("Interval triggers need minutes between 1 and 1440.")
    elif trigger_type == "keyword":
        text = str(trigger_config.get("text", "")).strip()
        if not 2 <= len(text) <= 80:
            problems.append("Keyword triggers need text between 2 and 80 characters.")

    if not actions:
        problems.append("At least one action is required.")
    for index, action in enumerate(actions or [], start=1):
        kind = action.get("type")
        if kind not in ACTION_TYPES:
            problems.append(f"Action {index}: type must be one of " + ", ".join(ACTION_TYPES) + ".")
            continue
        if kind in {"remind", "save", "notify", "ai_summary"}:
            if not str(action.get("text", "")).strip():
                problems.append(f"Action {index} ({kind}) needs non-empty text.")
        if kind == "command":
            command = str(action.get("name", "")).strip().lower()
            if command not in COMMAND_ALLOWLIST:
                problems.append(
                    f"Action {index}: command must be on the automation allowlist ("
                    + ", ".join(sorted(COMMAND_ALLOWLIST))
                    + ")."
                )

    for index, condition in enumerate(conditions or [], start=1):
        kind = condition.get("type")
        if kind not in {"contains", "chat_id", "media"}:
            problems.append(f"Condition {index}: type must be contains, chat_id or media.")

    if cooldown_seconds < 5 or cooldown_seconds > 86400:
        problems.append("Cooldown must be between 5 and 86400 seconds.")
    return problems


class AutomationEngine:
    def __init__(self, client_provider=None):
        self.client_provider = client_provider
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._last_fire: Dict[str, float] = {}
        self._schedule_marker: Dict[str, str] = {}
        self._hourly: Dict[str, List[float]] = {}
        self._task_cursor: float = time.time()
        self.executions = 0
        self.failures = 0

    # --------------------------------------------------------------------- setup
    def start(self) -> None:
        if not settings.automation_enabled:
            logger.info("Automation engine disabled by configuration.")
            return
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="reze-automation")
        logger.info("Automation engine started.")

    def stop(self) -> None:
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Automation tick failed: %s", exc)
            await asyncio.sleep(20)

    # -------------------------------------------------------------------- rules
    def rules(self, enabled_only: bool = False) -> List[Rule]:
        rows = db.list_automations(limit=200)
        rules = [Rule.from_row(row) for row in rows]
        return [rule for rule in rules if rule.enabled] if enabled_only else rules

    def create(self, name: str, trigger_type: str, trigger_config, actions, conditions=None, cooldown=60, created_by=0) -> Rule:
        name = (name or "").strip().lower()
        problems = validate_rule(name, trigger_type, trigger_config, conditions or [], actions, cooldown)
        if problems:
            raise AutomationError("; ".join(problems))
        if len(self.rules()) >= settings.automation_max_rules:
            raise AutomationError(
                f"Rule limit reached ({settings.automation_max_rules}). Delete a rule first."
            )
        if db.get_automation(name) is not None:
            raise AutomationError(f"A rule named '{name}' already exists.")
        db.create_automation(
            name=name,
            trigger_type=trigger_type,
            trigger_config=json.dumps(trigger_config),
            conditions=json.dumps(conditions or []),
            actions=json.dumps(actions),
            cooldown_seconds=int(cooldown),
            created_by=int(created_by),
            enabled=False,
        )
        rule = db.get_automation(name)
        assert rule is not None
        return Rule.from_row(rule)

    def enable(self, name: str) -> None:
        row = db.get_automation(name)
        if row is None:
            raise AutomationError(f"Unknown rule: {name}")
        rule = Rule.from_row(row)
        problems = validate_rule(
            rule.name, rule.trigger_type, rule.trigger_config, rule.conditions, rule.actions, rule.cooldown_seconds
        )
        if problems:
            raise AutomationError("Cannot enable: " + "; ".join(problems))
        db.set_automation_enabled(name, True)

    def disable(self, name: str) -> None:
        db.set_automation_enabled(name, False)

    def delete(self, name: str) -> bool:
        return db.delete_automation(name)

    # --------------------------------------------------------------- rate limits
    def _allowed(self, rule: Rule, now: float) -> bool:
        last = self._last_fire.get(rule.name, 0.0)
        if now - last < max(5, rule.cooldown_seconds):
            return False
        window = self._hourly.setdefault(rule.name, [])
        window[:] = [stamp for stamp in window if now - stamp < 3600]
        return len(window) < max(1, settings.automation_runs_per_hour)

    def _mark(self, rule: Rule, now: float) -> None:
        self._last_fire[rule.name] = now
        self._hourly.setdefault(rule.name, []).append(now)

    # -------------------------------------------------------------------- timing
    async def tick(self) -> int:
        """Evaluate time-based triggers. Returns how many rules ran."""
        if not settings.automation_enabled:
            return 0
        now = time.time()
        ran = 0
        try:
            zone = ZoneInfo(settings.timezone)
        except Exception:
            zone = ZoneInfo("UTC")
        local_now = datetime.now(zone)

        for rule in self.rules(enabled_only=True):
            try:
                if rule.trigger_type == "schedule":
                    at = str(rule.trigger_config.get("at", ""))
                    marker = f"{local_now.date().isoformat()} {at}"
                    if local_now.strftime("%H:%M") == at and self._schedule_marker.get(rule.name) != marker:
                        self._schedule_marker[rule.name] = marker
                        if await self._execute(rule, {"text": "", "chat_id": 0}, now):
                            ran += 1
                elif rule.trigger_type == "interval":
                    minutes = int(rule.trigger_config.get("minutes", 60))
                    last = self._last_fire.get(rule.name, 0.0) or self._task_cursor
                    if now - last >= minutes * 60 and await self._execute(rule, {"text": "", "chat_id": 0}, now):
                        ran += 1
                elif rule.trigger_type == "task_failed":
                    failed = _recent_failed_tasks(self._task_cursor)
                    if failed and await self._execute(
                        rule,
                        {"text": str(failed[0].get("error", "")), "chat_id": 0},
                        now,
                    ):
                        ran += 1
            except Exception as exc:  # noqa: BLE001 - one rule cannot stop the loop
                logger.error("Automation rule '%s' failed to evaluate: %s", rule.name, exc)
                db.record_automation_run(rule.name, str(exc)[:300])
        self._task_cursor = now
        return ran

    # ------------------------------------------------------------------ messages
    async def on_message(self, message: Any, chat_id: int, sender_id: int, text: str) -> int:
        """Evaluate keyword triggers for one incoming message."""
        if not settings.automation_enabled or not (text or "").strip():
            return 0
        if getattr(message, "out", False):
            return 0
        now = time.time()
        ran = 0
        lower = text.lower()
        payload = {
            "text": text,
            "chat_id": chat_id,
            "sender_id": sender_id,
            "has_media": bool(getattr(message, "media", None)),
        }
        for rule in self.rules(enabled_only=True):
            if rule.trigger_type != "keyword":
                continue
            needle = str(rule.trigger_config.get("text", "")).lower()
            if not needle or needle not in lower:
                continue
            if not self._conditions_match(rule, payload):
                continue
            if await self._execute(rule, payload, now):
                ran += 1
        return ran

    @staticmethod
    def _conditions_match(rule: Rule, payload: Dict[str, Any]) -> bool:
        for condition in rule.conditions:
            kind = condition.get("type")
            value = condition.get("value")
            if kind == "contains" and str(value).lower() not in str(payload.get("text", "")).lower():
                return False
            if kind == "chat_id" and int(payload.get("chat_id") or 0) != int(value or 0):
                return False
            if kind == "media" and bool(payload.get("has_media")) != bool(value):
                return False
        return True

    # ----------------------------------------------------------------- execution
    async def _execute(self, rule: Rule, payload: Dict[str, Any], now: float) -> bool:
        if not self._allowed(rule, now):
            return False
        self._mark(rule, now)
        depth = _DEPTH.get()
        if depth >= MAX_DEPTH:
            logger.warning("Automation recursion guard stopped rule '%s'.", rule.name)
            db.record_automation_run(rule.name, "recursion guard")
            return False

        token = _DEPTH.set(depth + 1)
        try:
            errors = []
            for action in rule.actions:
                try:
                    await self._run_action(rule, action, payload)
                except Exception as exc:  # noqa: BLE001 - record and continue
                    errors.append(f"{action.get('type')}: {exc}")
                    self.failures += 1
                    logger.warning("Automation action failed for '%s': %s", rule.name, exc)
            self.executions += 1
            db.record_automation_run(rule.name, "; ".join(errors)[:300])
            return True
        finally:
            _DEPTH.reset(token)

    async def _run_action(self, rule: Rule, action: Dict[str, Any], payload: Dict[str, Any]) -> None:
        kind = action.get("type")
        text = str(action.get("text", ""))
        text = _expand(text, payload)
        client = self.client_provider() if self.client_provider else None
        target = int(payload.get("chat_id") or 0) or int(settings.owner_id or 0)

        if kind == "remind":
            from datetime import timedelta

            db.add_reminder(
                chat_id=target or 0,
                user_id=int(settings.owner_id or 0),
                text=text or "(reminder)",
                due_at=datetime.utcnow() + timedelta(minutes=1),
            )
            return

        if kind == "save":
            db.add_archive(kind="note", title=f"automation:{rule.name}", content=text)
            return

        if kind == "notify":
            if not self._outbound_authorized(rule):
                raise AutomationError("Outbound notifications require an owner-created rule.")
            if client is None:
                raise AutomationError("No Telegram client is connected.")
            await client.send_message(target or int(settings.owner_id or 0), ascii.frame("Automation", [f"{rule.name}: {text}"]))
            return

        if kind == "ai_summary":
            from reze.ai.gateway import ai_gateway

            source = text or str(payload.get("text", ""))[:2000]
            if not source.strip():
                raise AutomationError("Nothing to summarize.")
            result = await ai_gateway.complete(
                "Summarize the following content in at most 5 bullet points:\n\n" + source
            )
            db.add_archive(kind="note", title=f"digest:{rule.name}", content=result.text)
            return

        if kind == "command":
            name = str(action.get("name", "")).lower()
            if name not in COMMAND_ALLOWLIST:
                raise AutomationError(f"Command '{name}' is not on the automation allowlist.")
            if not self._outbound_authorized(rule):
                raise AutomationError("Command automation requires an owner-created rule.")
            if client is None:
                raise AutomationError("No Telegram client is connected.")
            synthetic = _SyntheticMessage(
                client,
                target,
                int(settings.owner_id or 0),
                text=f".{name} {str(action.get('args', '')).strip()}".strip(),
            )
            await router.handle_message(synthetic, client)
            return

        raise AutomationError(f"Unsupported action: {kind}")

    @staticmethod
    def _outbound_authorized(rule: Rule) -> bool:
        return not settings.owner_id or int(rule.created_by) == int(settings.owner_id)


def _expand(text: str, payload: Dict[str, Any]) -> str:
    """Substitute a tiny, safe set of placeholders."""
    return (
        text.replace("{chat_id}", str(payload.get("chat_id", "")))
        .replace("{sender_id}", str(payload.get("sender_id", "")))
        .replace("{text}", str(payload.get("text", "")))
    )


def _recent_failed_tasks(since: float) -> List[Dict[str, Any]]:
    """Failed background tasks that settled after *since* (bounded lookup)."""
    try:
        from reze.core.tasks import TaskStatus, task_manager

        return [
            {"error": record.error, "kind": record.kind, "id": record.id}
            for record in task_manager.finished(limit=20)
            if record.status in {TaskStatus.FAILED, TaskStatus.TIMEOUT}
            and (record.finished_at or 0) > since
        ][:1]
    except Exception:  # pragma: no cover - task manager unavailable
        return []


class _SyntheticMessage:
    """Minimal message facade used for approved internal command dispatch."""

    def __init__(self, client: Any, chat_id: int, sender_id: int, text: str = ""):
        self.client = client
        self.chat_id = chat_id
        self.sender_id = sender_id
        self.text = text
        self.message = text
        self.out = True
        self.media = None
        self.reply_to_msg_id = None
        self.is_group = bool(chat_id and chat_id < 0)

    async def reply(self, text: str):
        return await self.client.send_message(self.chat_id, text)


automation_engine = AutomationEngine()
