"""Persistent workflows with retries, idempotency, cancellation and recovery.

Definitions and runs live in SQLite, so a restart never loses history. A run
that was interrupted by a restart is marked ``interrupted`` and can be resumed
explicitly with ``.workflow resume <run_id>``; nothing resumes silently.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from reze.automation.simulator import SimulationError, parse_steps, render, simulate
from reze.config import settings
from reze.core.registry import Service, bus
from reze.database import db
from reze.features import features
from reze.logging_config import logger

MAX_ATTEMPTS = 3


class WorkflowUnavailable(Exception):
    """Raised when the optional workflows feature is OFF."""


class WorkflowError(Exception):
    """Raised for invalid workflow operations."""


def _stamp(moment: Optional[datetime] = None) -> str:
    return (moment or datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S")


class WorkflowService(Service):
    name = "workflows"
    feature = "workflows"
    description = "Persistent multi-step workflows and their scheduler."

    def __init__(self) -> None:
        super().__init__()
        self.client_provider = None
        self._cancelled: set = set()
        self.interval = 60

    # ------------------------------------------------------------------ feature
    @staticmethod
    def available() -> bool:
        return features.is_enabled("workflows")

    def _require(self) -> None:
        if not self.available():
            raise WorkflowUnavailable(
                "Persistent workflows are OFF. Enable them with: .features enable workflows confirm"
            )

    # --------------------------------------------------------------- definitions
    def create(
        self,
        name: str,
        steps: Any,
        description: str = "",
        trigger_type: str = "manual",
        trigger_config: Optional[Dict[str, Any]] = None,
        cooldown_seconds: int = 60,
    ) -> int:
        self._require()
        cleaned = " ".join((name or "").split()).lower()
        if not cleaned:
            raise WorkflowError("A workflow needs a name.")
        normalized = parse_steps(steps)
        report = simulate(normalized)
        if not report.valid:
            raise WorkflowError("; ".join(report.errors))
        trigger_type = (trigger_type or "manual").lower()
        if trigger_type not in {"manual", "interval", "daily"}:
            raise WorkflowError("Trigger must be manual, interval or daily.")
        config = trigger_config or {}
        if trigger_type == "interval":
            seconds = int(config.get("seconds") or 0)
            if seconds < 60 or seconds > 30 * 86400:
                raise WorkflowError("An interval trigger needs 60-2592000 seconds.")
            config = {"seconds": seconds}
        elif trigger_type == "daily":
            at = str(config.get("at") or "")
            try:
                datetime.strptime(at, "%H:%M")
            except ValueError as exc:
                raise WorkflowError("A daily trigger needs {\"at\": \"HH:MM\"} in UTC.") from exc
            config = {"at": at}
        else:
            config = {}
        db.execute(
            "INSERT INTO workflows (name, description, enabled, trigger_type, trigger_config, steps, cooldown_seconds) "
            "VALUES (?, ?, 0, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET description = excluded.description, "
            "trigger_type = excluded.trigger_type, trigger_config = excluded.trigger_config, "
            "steps = excluded.steps, cooldown_seconds = excluded.cooldown_seconds, "
            "updated_at = CURRENT_TIMESTAMP",
            (
                cleaned[:80],
                (description or "")[:1000],
                trigger_type,
                json.dumps(config),
                json.dumps(normalized),
                max(0, min(int(cooldown_seconds or 0), 86400)),
            ),
        )
        row = self.get(cleaned)
        return int(row["id"]) if row else 0

    def get(self, identifier: Any) -> Optional[Dict[str, Any]]:
        text = str(identifier or "").strip()
        if text.isdigit():
            row = db.query_one("SELECT * FROM workflows WHERE id = ?", (int(text),))
            if row:
                return row
        return db.query_one("SELECT * FROM workflows WHERE name = ?", (text.lower(),))

    def list(self, limit: int = 30) -> List[Dict[str, Any]]:
        rows = db.query("SELECT * FROM workflows ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),))
        for row in rows:
            row["step_count"] = len(self._steps(row))
        return rows

    def set_enabled(self, identifier: Any, enabled: bool) -> bool:
        self._require()
        row = self.get(identifier)
        if row is None:
            return False
        db.execute(
            "UPDATE workflows SET enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (1 if enabled else 0, row["id"]),
        )
        return True

    def delete(self, identifier: Any) -> bool:
        row = self.get(identifier)
        if row is None:
            return False
        db.execute("DELETE FROM workflows WHERE id = ?", (row["id"],))
        return True

    @staticmethod
    def _steps(row: Dict[str, Any]) -> List[Dict[str, Any]]:
        try:
            return json.loads(row.get("steps") or "[]")
        except ValueError:
            return []

    def history(self, identifier: Any = "", limit: int = 20) -> List[Dict[str, Any]]:
        if identifier:
            row = self.get(identifier)
            if row is None:
                return []
            return db.query(
                "SELECT * FROM workflow_runs WHERE workflow_id = ? ORDER BY id DESC LIMIT ?",
                (row["id"], max(1, min(int(limit), 100))),
            )
        return db.query("SELECT * FROM workflow_runs ORDER BY id DESC LIMIT ?", (max(1, min(int(limit), 100)),))

    # ---------------------------------------------------------------------- run
    async def run(
        self,
        identifier: Any,
        context: Optional[Dict[str, Any]] = None,
        idempotency_key: str = "",
        manual: bool = False,
        run_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        self._require()
        workflow = self.get(identifier)
        if workflow is None:
            raise WorkflowError("Unknown workflow.")
        if not int(workflow.get("enabled") or 0) and not manual:
            raise WorkflowError("This workflow is disabled.")

        context = dict(context or {})
        context.setdefault("date", datetime.utcnow().strftime("%Y-%m-%d"))
        context.setdefault("owner_id", settings.owner_id)

        if run_id is None:
            key = idempotency_key or f"{workflow['id']}:{uuid.uuid4().hex}"
            try:
                run_id = db.execute(
                    "INSERT INTO workflow_runs (workflow_id, status, idempotency_key, context) "
                    "VALUES (?, 'pending', ?, ?)",
                    (workflow["id"], key[:120], json.dumps(context)[:4000]),
                )
            except Exception as exc:  # unique idempotency key
                existing = db.query_one("SELECT * FROM workflow_runs WHERE idempotency_key = ?", (key[:120],))
                if existing:
                    return {"status": "duplicate", "run": existing, "workflow": workflow["name"]}
                raise WorkflowError(f"Could not create the run: {exc}") from exc

        db.execute(
            "UPDATE workflow_runs SET status = 'running', attempts = attempts + 1, started_at = ? WHERE id = ?",
            (_stamp(), run_id),
        )
        run = db.query_one("SELECT * FROM workflow_runs WHERE id = ?", (run_id,))
        try:
            run_context = json.loads((run or {}).get("context") or "{}")
        except ValueError:
            run_context = context

        steps = self._steps(workflow)
        failure = ""
        for index, step in enumerate(steps, start=1):
            if run_id in self._cancelled:
                self._finish(run_id, "cancelled", "Cancelled by the owner")
                self._cancelled.discard(run_id)
                return {"status": "cancelled", "run": db.query_one("SELECT * FROM workflow_runs WHERE id = ?", (run_id,))}
            existing = db.query_one(
                "SELECT * FROM workflow_steps WHERE run_id = ? AND step_index = ?", (run_id, index)
            )
            if existing and existing.get("status") == "done":
                continue
            db.execute(
                "INSERT OR IGNORE INTO workflow_steps (run_id, step_index, action, status) "
                "VALUES (?, ?, ?, 'pending')",
                (run_id, index, str(step.get("action") or "")[:40]),
            )
            attempt = 0
            while attempt < MAX_ATTEMPTS:
                attempt += 1
                try:
                    output = await self._execute_step(step, run_context, workflow)
                    db.execute(
                        "UPDATE workflow_steps SET status = 'done', attempts = ?, output = ?, "
                        "finished_at = ? WHERE run_id = ? AND step_index = ?",
                        (attempt, str(output)[:2000], _stamp(), run_id, index),
                    )
                    failure = ""
                    break
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - retry safe steps only
                    failure = f"Step {index} ({step.get('action')}): {exc}"[:500]
                    db.execute(
                        "UPDATE workflow_steps SET status = 'failed', attempts = ?, error = ?, "
                        "finished_at = ? WHERE run_id = ? AND step_index = ?",
                        (attempt, str(exc)[:1000], _stamp(), run_id, index),
                    )
                    if attempt >= MAX_ATTEMPTS or not self._retryable(exc):
                        break
                    await asyncio.sleep(min(2 ** (attempt - 1), 4))
            else:  # pragma: no cover - loop always breaks
                pass
            if failure and (existing is None or existing.get("status") != "done"):
                step_row = db.query_one(
                    "SELECT status FROM workflow_steps WHERE run_id = ? AND step_index = ?", (run_id, index)
                )
                if not step_row or step_row.get("status") != "done":
                    break

        status = "done"
        if failure:
            step_row = db.query_one(
                "SELECT status, error FROM workflow_steps WHERE run_id = ? ORDER BY step_index DESC LIMIT 1",
                (run_id,),
            )
            if step_row and step_row.get("status") == "failed":
                status = "failed"
                failure = step_row.get("error") or failure
        self._finish(run_id, status, "" if status == "done" else failure)
        db.execute(
            "UPDATE workflows SET last_run = ?, run_count = run_count + 1, last_error = ? WHERE id = ?",
            (_stamp(), "" if status == "done" else failure[:500], workflow["id"]),
        )
        await bus.emit("workflow.finished", run_id=run_id, workflow=workflow["name"], status=status)
        return {
            "status": status,
            "run": db.query_one("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)),
            "workflow": workflow["name"],
            "error": failure,
        }

    def _finish(self, run_id: int, status: str, error: str) -> None:
        db.execute(
            "UPDATE workflow_runs SET status = ?, finished_at = ?, error = ? WHERE id = ?",
            (status, _stamp(), error[:1000], run_id),
        )

    def cancel(self, run_id: int) -> bool:
        self._cancelled.add(int(run_id))
        run = db.query_one("SELECT * FROM workflow_runs WHERE id = ? AND status IN ('pending','running')", (int(run_id),))
        if run is None:
            return False
        self._finish(int(run_id), "cancelled", "Cancelled by the owner")
        return True

    async def resume(self, run_id: int) -> Dict[str, Any]:
        run = db.query_one("SELECT * FROM workflow_runs WHERE id = ?", (int(run_id),))
        if run is None:
            raise WorkflowError("Unknown run.")
        if run.get("status") not in {"interrupted", "failed", "cancelled"}:
            raise WorkflowError("Only interrupted, failed or cancelled runs can be resumed.")
        if int(run.get("attempts") or 0) >= MAX_ATTEMPTS:
            raise WorkflowError("This run reached the retry limit; start a new run instead.")
        return await self.run(
            run["workflow_id"], context={}, manual=True, run_id=int(run_id)
        )

    # ----------------------------------------------------------------- step work
    @staticmethod
    def _retryable(exc: Exception) -> bool:
        text = str(exc).lower()
        return not any(
            marker in text
            for marker in ("invalid", "missing", "unknown", "disabled", "off.", "requires", "not found")
        )

    async def _execute_step(
        self, step: Dict[str, Any], context: Dict[str, Any], workflow: Dict[str, Any]
    ) -> str:
        action = str(step.get("action") or "")
        if action == "send_message":
            client = self.client_provider() if self.client_provider else None
            if client is None:
                raise WorkflowError("No Telegram client is connected.")
            chat = step.get("chat_id")
            if str(chat).lower() in {"owner", "me", "self"}:
                chat = settings.owner_id
            if not chat:
                raise WorkflowError("A chat id is required.")
            text = render(step.get("text", ""), context)
            await client.send_message(int(chat), text)
            return f"sent {len(text)} chars"
        if action == "notify_owner":
            client = self.client_provider() if self.client_provider else None
            if client is None:
                raise WorkflowError("No Telegram client is connected.")
            if not settings.owner_id:
                raise WorkflowError("REZE_OWNER_ID is not configured.")
            text = render(step.get("text", ""), context)
            await client.send_message(int(settings.owner_id), text)
            return f"notified owner ({len(text)} chars)"
        if action == "save_memory":
            from reze.personal.memory import memory_service

            if not features.is_enabled("memory"):
                raise WorkflowError("The memory feature is disabled.")
            content = render(step.get("content", ""), context)
            memory_id = memory_service.save(content, source=f"workflow:{workflow['name']}")
            return f"memory #{memory_id}"
        if action == "add_timeline":
            from reze.personal.timeline import timeline_service

            if not features.is_enabled("timeline"):
                raise WorkflowError("The timeline feature is disabled.")
            event_id = timeline_service.append(
                str(step.get("kind") or "workflow"),
                render(step.get("title", ""), context),
                render(step.get("body", ""), context),
                source="workflow",
            )
            return f"timeline #{event_id}"
        if action == "add_task":
            from reze.personal.projects import project_service

            if not features.is_enabled("projects"):
                raise WorkflowError("The projects feature is disabled.")
            task_id = project_service.add_task(
                render(step.get("title", ""), context),
                project=str(step.get("project") or ""),
                priority=int(step.get("priority") or 3),
            )
            return f"task #{task_id}"
        if action == "add_reminder":
            if not settings.owner_id:
                raise WorkflowError("REZE_OWNER_ID is not configured.")
            minutes = int(step.get("minutes") or 0)
            if minutes <= 0:
                raise WorkflowError("minutes must be positive.")
            due = datetime.utcnow() + timedelta(minutes=minutes)
            reminder_id = db.add_reminder(
                int(settings.owner_id), int(settings.owner_id), render(step.get("text", ""), context), due
            )
            return f"reminder #{reminder_id}"
        if action == "log":
            logger.info("Workflow '%s': %s", workflow.get("name"), render(step.get("message", ""), context)[:200])
            return "logged"
        if action == "wait":
            seconds = max(0, min(int(step.get("seconds") or 0), 60))
            await asyncio.sleep(seconds)
            return f"waited {seconds}s"
        raise WorkflowError(f"Unsupported action '{action}'.")

    # ---------------------------------------------------------------- scheduler
    async def tick(self, now: Optional[datetime] = None) -> List[str]:
        if not self.available():
            return []
        now = now or datetime.utcnow()
        started = []
        for row in db.query("SELECT * FROM workflows WHERE enabled = 1"):
            trigger = str(row.get("trigger_type") or "manual")
            if trigger not in {"interval", "daily"}:
                continue
            try:
                config = json.loads(row.get("trigger_config") or "{}")
            except ValueError:
                continue
            last = self._parse(row.get("last_run"))
            cooldown = int(row.get("cooldown_seconds") or 0)
            due = False
            if trigger == "interval":
                seconds = int(config.get("seconds") or 0)
                due = bool(seconds) and (last is None or (now - last).total_seconds() >= seconds)
            elif trigger == "daily":
                at = str(config.get("at") or "")
                try:
                    hour, minute = [int(part) for part in at.split(":")]
                except ValueError:
                    continue
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                due = now >= target and (last is None or last < target)
            if due and (last is None or (now - last).total_seconds() >= cooldown):
                try:
                    result = await self.run(row["name"])
                    started.append(f"{row['name']}:{result.get('status')}")
                except Exception as exc:  # noqa: BLE001 - one workflow cannot stop the scheduler
                    logger.warning("Scheduled workflow '%s' failed: %s", row["name"], exc)
        return started

    @staticmethod
    def _parse(value: Any) -> Optional[datetime]:
        try:
            return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None

    async def recover(self) -> int:
        """Mark interrupted runs explicitly; they are never resumed silently."""
        count = db.execute(
            "UPDATE workflow_runs SET status = 'interrupted', error = 'Interrupted by a restart' "
            "WHERE status IN ('pending','running')"
        )
        if count:
            logger.warning("Marked %d interrupted workflow run(s); resume them explicitly.", count)
        return int(count or 0)

    async def start(self) -> None:
        await super().start()
        await self.recover()
        self._spawn(self._loop(), "workflows")

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.error("Workflow scheduler error: %s", exc)
            await asyncio.sleep(self.interval)


workflow_service = WorkflowService()

__all__ = [
    "MAX_ATTEMPTS",
    "SimulationError",
    "WorkflowError",
    "WorkflowService",
    "WorkflowUnavailable",
    "simulate",
    "workflow_service",
]
