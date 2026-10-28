"""
Bounded background task manager.

Long-running work (media conversion, AI requests, automation jobs) runs through
this single manager so that Reze can report progress, cancel work, cap
concurrency and never let one command starve the Telethon event loop.

The implementation is intentionally in-process: one asyncio semaphore, one
bounded queue and a small ring of finished records. It is not a distributed
queue and does not survive a process restart — completed work is mirrored to the
``task_log`` SQLite table for the web panel.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

from reze.config import settings
from reze.exceptions import TaskNotFound, TaskQueueFull
from reze.logging_config import logger


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


ACTIVE_STATUSES = {TaskStatus.QUEUED, TaskStatus.RUNNING}
TERMINAL_STATUSES = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.TIMEOUT}


@dataclass
class TaskRecord:
    """Everything Reze knows about one unit of background work."""

    id: str
    kind: str
    command: str = ""
    status: TaskStatus = TaskStatus.QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    progress: float = 0.0
    detail: str = ""
    error: str = ""
    result_summary: str = ""
    cancel_requested: bool = False
    value: Any = None
    _future: Optional[asyncio.Future] = field(default=None, repr=False)
    _asyncio_task: Optional[asyncio.Task] = field(default=None, repr=False)

    # ------------------------------------------------------------------ helpers
    @property
    def elapsed(self) -> float:
        end = self.finished_at or time.time()
        start = self.started_at or self.created_at
        return max(0.0, end - start)

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    def update(self, progress: Optional[float] = None, detail: Optional[str] = None) -> None:
        """Called by the worker to publish progress (clamped to 0-100)."""
        if progress is not None:
            self.progress = max(0.0, min(100.0, float(progress)))
        if detail is not None:
            self.detail = str(detail)[:200]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "command": self.command,
            "status": self.status.value,
            "progress": round(self.progress, 1),
            "detail": self.detail,
            "error": self.error,
            "result": self.result_summary,
            "elapsed": round(self.elapsed, 2),
            "created_at": self.created_at,
            "cancel_requested": self.cancel_requested,
        }


class TaskManager:
    """Bounded, cancellable asyncio task runner."""

    def __init__(
        self,
        concurrency: Optional[int] = None,
        queue_limit: Optional[int] = None,
        default_timeout: Optional[float] = None,
        history: int = 50,
    ):
        self.concurrency = max(1, int(concurrency or settings.task_concurrency))
        self.queue_limit = max(1, int(queue_limit or settings.task_queue_limit))
        self.default_timeout = float(default_timeout or settings.task_timeout_seconds)
        self.history = max(10, int(history))

        self._active: Dict[str, TaskRecord] = {}
        self._queued: List[TaskRecord] = []
        self._finished: List[TaskRecord] = []
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._lock: Optional[asyncio.Lock] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------ runtime
    def _get_semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._loop is not loop:
            self._semaphore = asyncio.Semaphore(self.concurrency)
            self._lock = asyncio.Lock()
            self._loop = loop
        return self._semaphore

    @property
    def lock(self) -> asyncio.Lock:
        self._get_semaphore()
        assert self._lock is not None
        return self._lock

    def _prune(self) -> None:
        if len(self._finished) > self.history:
            del self._finished[: len(self._finished) - self.history]

    # -------------------------------------------------------------------- submit
    async def submit(
        self,
        kind: str,
        factory: Callable[[TaskRecord], Awaitable[Any]],
        command: str = "",
        timeout: Optional[float] = None,
    ) -> TaskRecord:
        """
        Queue a coroutine factory and return its record immediately.

        ``factory`` receives the record so it can publish progress. The record's
        ``value`` holds whatever the factory returns. Raises
        :class:`TaskQueueFull` when the queue is saturated.
        """
        if len(self._queued) >= self.queue_limit:
            raise TaskQueueFull(
                f"Task queue limit reached ({self.queue_limit}). Wait for a task to finish or cancel one."
            )

        record = TaskRecord(
            id=uuid.uuid4().hex[:8],
            kind=kind,
            command=command,
            created_at=time.time(),
        )
        record._future = asyncio.get_running_loop().create_future()
        self._queued.append(record)
        record._asyncio_task = asyncio.create_task(self._run(record, factory, timeout))
        return record

    async def _run(self, record: TaskRecord, factory, timeout: Optional[float]) -> None:
        try:
            async with self._get_semaphore():
                async with self.lock:
                    if record.cancel_requested:
                        self._finish(record, TaskStatus.CANCELLED)
                        return
                    if record in self._queued:
                        self._queued.remove(record)
                    self._active[record.id] = record
                record.status = TaskStatus.RUNNING
                record.started_at = time.time()
                record.detail = "started"
                logger.info("Task %s (%s) started", record.id, record.kind)

                limit = float(timeout or self.default_timeout)
                try:
                    value = await asyncio.wait_for(factory(record), timeout=limit)
                    record.value = value
                    if not record.result_summary:
                        record.result_summary = str(value)[:400] if value is not None else ""
                    self._finish(record, TaskStatus.COMPLETED)
                except asyncio.TimeoutError:
                    record.error = f"Task exceeded the {int(limit)}s timeout."
                    self._finish(record, TaskStatus.TIMEOUT)
                except asyncio.CancelledError:
                    record.error = "Cancelled by user."
                    self._finish(record, TaskStatus.CANCELLED)
                    raise
                except Exception as exc:  # noqa: BLE001 - surfaced to the user
                    record.error = _safe_error(exc)
                    self._finish(record, TaskStatus.FAILED)
                    logger.error("Task %s (%s) failed: %s", record.id, record.kind, record.error)
        except asyncio.CancelledError:
            if record.status not in TERMINAL_STATUSES:
                record.error = "Cancelled by user."
                self._finish(record, TaskStatus.CANCELLED)
            raise
        finally:
            async with self._lock:
                self._active.pop(record.id, None)
                if record in self._queued:
                    self._queued.remove(record)
            if record._future is not None and not record._future.done():
                record._future.set_result(record)

    def _finish(self, record: TaskRecord, status: TaskStatus) -> None:
        record.status = status
        record.finished_at = time.time()
        if status == TaskStatus.COMPLETED:
            record.progress = 100.0
        self._finished.append(record)
        self._prune()
        try:
            from reze.database import db

            db.log_task(
                task_id=record.id,
                kind=record.kind,
                command=record.command,
                status=status.value,
                duration_seconds=record.elapsed,
                error=record.error,
            )
        except Exception:  # pragma: no cover - never break a task on logging
            pass
        logger.info(
            "Task %s (%s) %s in %.2fs",
            record.id,
            record.kind,
            status.value,
            record.elapsed,
        )

    # ------------------------------------------------------------------ retrieval
    def get(self, task_id: str) -> Optional[TaskRecord]:
        for record in self._active.values():
            if record.id == task_id:
                return record
        for record in self._queued:
            if record.id == task_id:
                return record
        for record in reversed(self._finished):
            if record.id == task_id:
                return record
        return None

    def active(self) -> List[TaskRecord]:
        return list(self._active.values())

    def queued(self) -> List[TaskRecord]:
        return list(self._queued)

    def finished(self, limit: int = 10) -> List[TaskRecord]:
        return list(reversed(self._finished))[: max(1, limit)]

    def snapshot(self) -> Dict[str, Any]:
        return {
            "concurrency": self.concurrency,
            "queue_limit": self.queue_limit,
            "active": [record.to_dict() for record in self.active()],
            "queued": [record.to_dict() for record in self.queued()],
            "finished": [record.to_dict() for record in self.finished()],
        }

    async def wait(self, task_id: str, timeout: Optional[float] = None) -> TaskRecord:
        """Wait for a task to settle and return its record."""
        record = self.get(task_id)
        if record is None:
            raise TaskNotFound(f"Unknown task id: {task_id}")
        if record._future is None:
            return record
        return await asyncio.wait_for(asyncio.shield(record._future), timeout=timeout)

    # ------------------------------------------------------------------ control
    async def cancel(self, task_id: str) -> bool:
        """Request cancellation. Returns False when the task already finished."""
        record = self.get(task_id)
        if record is None:
            raise TaskNotFound(f"Unknown task id: {task_id}")
        if record.status in TERMINAL_STATUSES:
            return False

        record.cancel_requested = True
        if record.status == TaskStatus.QUEUED:
            if record in self._queued:
                self._queued.remove(record)
            record.error = "Cancelled before start."
            self._finish(record, TaskStatus.CANCELLED)
            if record._future is not None and not record._future.done():
                record._future.set_result(record)
            return True

        if record._asyncio_task is not None and not record._asyncio_task.done():
            record._asyncio_task.cancel()
        return True

    async def cancel_all(self) -> int:
        cancelled = 0
        for record in list(self.active()) + list(self.queued()):
            try:
                if await self.cancel(record.id):
                    cancelled += 1
            except TaskNotFound:
                continue
        return cancelled

    async def shutdown(self) -> None:
        """Cancel everything; used on process shutdown."""
        await self.cancel_all()


def _safe_error(exc: BaseException) -> str:
    """Short, secret-free description of a task failure."""
    message = str(exc).strip() or exc.__class__.__name__
    for marker in ("api_hash", "session", "token", "password", "api_key"):
        if marker in message.lower():
            return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message}"[:400]


task_manager = TaskManager()
