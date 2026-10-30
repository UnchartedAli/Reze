"""
Service registry and event bus for the REZE 3 modular monolith.

Every subsystem (memory, CRM, vault, workflows, ...) exposes one service object
that registers itself here. That gives the application a single place to start
and stop background work, to answer ``.status``/``.doctor`` questions and to
publish domain events without importing every other module.

Design rules:

* registration is explicit and idempotent — importing a module must never start
  background work on its own;
* ``start_all`` only starts services whose optional feature is enabled, so the
  global "everything optional is OFF" policy holds at one choke point;
* a failing service is isolated: it is marked ``failed`` and the rest keeps
  running;
* event handlers are isolated too, and the bus keeps a bounded history for
  diagnostics (no payloads that could contain secrets).
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, Iterable, List, Optional

from reze.logging_config import logger


class Service:
    """Base class for a REZE subsystem."""

    #: Stable identifier used by the registry, the panel and health output.
    name: str = "service"
    #: Feature flag that must be ON for ``start_all`` to start this service.
    #: ``None`` means the service has no optional background behaviour.
    feature: Optional[str] = None
    #: One-line description shown by ``.doctor``.
    description: str = ""

    def __init__(self) -> None:
        self.status = "registered"  # registered | running | stopped | failed | disabled
        self.error = ""
        self.started_at = 0.0
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------ lifecycle
    def feature_enabled(self) -> bool:
        if not self.feature:
            return True
        try:
            from reze.features import features

            return features.is_enabled(self.feature)
        except Exception:  # pragma: no cover - feature store unavailable early
            return False

    async def start(self) -> None:
        """Start background work. Override in subclasses that need a loop."""
        self.status = "running"
        self.started_at = time.time()

    async def stop(self) -> None:
        """Stop background work and release resources."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
        self.status = "stopped"

    def health(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "feature": self.feature or "-",
            "enabled": self.feature_enabled(),
            "error": self.error,
            "uptime": round(time.time() - self.started_at, 1) if self.started_at else 0.0,
        }

    # --------------------------------------------------------------- task helper
    def _spawn(self, coro, name: str) -> asyncio.Task:
        self._task = asyncio.create_task(coro, name=f"reze-{name}")
        return self._task


class ServiceRegistry:
    def __init__(self) -> None:
        self._services: Dict[str, Service] = {}
        self.started: List[str] = []
        self.failures: Dict[str, str] = {}

    def register(self, service: Service, *, replace: bool = False) -> Service:
        if service.name in self._services and not replace:
            return self._services[service.name]
        self._services[service.name] = service
        return service

    def get(self, name: str) -> Optional[Service]:
        return self._services.get(name)

    def all(self) -> List[Service]:
        return sorted(self._services.values(), key=lambda service: service.name)

    def names(self) -> List[str]:
        return [service.name for service in self.all()]

    async def start_all(self) -> List[str]:
        """Start every service whose optional feature is enabled."""
        started: List[str] = []
        for service in self.all():
            if service.status == "running":
                continue
            if not service.feature_enabled():
                service.status = "disabled"
                continue
            try:
                await service.start()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - isolate one broken service
                service.status = "failed"
                service.error = f"{type(exc).__name__}: {exc}"[:300]
                self.failures[service.name] = service.error
                logger.error("Service '%s' failed to start: %s", service.name, exc)
                continue
            started.append(service.name)
            self.started.append(service.name)
            logger.info("Service '%s' started.", service.name)
        return started

    async def stop_all(self) -> None:
        for service in reversed(self.all()):
            if service.status != "running":
                continue
            try:
                await service.stop()
            except Exception as exc:  # noqa: BLE001 - shutdown must continue
                logger.warning("Service '%s' failed to stop cleanly: %s", service.name, exc)
        self.started.clear()

    async def restart(self, name: str) -> bool:
        service = self.get(name)
        if service is None:
            return False
        try:
            await service.stop()
            await service.start()
            service.status = "running"
            return True
        except Exception as exc:  # noqa: BLE001
            service.status = "failed"
            service.error = str(exc)[:300]
            return False

    def health(self) -> List[Dict[str, Any]]:
        return [service.health() for service in self.all()]

    def summary(self) -> Dict[str, Any]:
        running = sum(1 for service in self.all() if service.status == "running")
        disabled = sum(1 for service in self.all() if service.status == "disabled")
        failed = sum(1 for service in self.all() if service.status == "failed")
        return {
            "total": len(self._services),
            "running": running,
            "disabled": disabled,
            "failed": failed,
            "services": self.health(),
            "failures": dict(self.failures),
        }


registry = ServiceRegistry()


@dataclass
class Event:
    name: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


class EventBus:
    """Tiny in-process pub/sub used to decouple REZE services."""

    KNOWN_EVENTS = (
        "memory.saved",
        "memory.forgotten",
        "crm.contact_saved",
        "decision.logged",
        "focus.started",
        "focus.stopped",
        "timeline.appended",
        "task.completed",
        "workflow.finished",
        "vault.saved",
        "inbox.captured",
        "sentinel.finding",
        "backup.created",
    )

    def __init__(self, history: int = 50) -> None:
        self._handlers: Dict[str, List[Callable]] = {}
        self._history: Deque[Event] = deque(maxlen=max(10, history))
        self.emitted = 0
        self.delivered = 0
        self.failures = 0

    def on(self, event: str, handler: Callable) -> Callable:
        """Subscribe a sync or async handler; usable as a decorator."""
        self._handlers.setdefault(event, []).append(handler)
        return handler

    def off(self, event: str, handler: Callable) -> None:
        if handler in self._handlers.get(event, []):
            self._handlers[event].remove(handler)

    def subscribers(self, event: str) -> int:
        return len(self._handlers.get(event, []))

    async def emit(self, event: str, **payload: Any) -> int:
        """Publish an event. Handler failures are isolated and never propagate."""
        self.emitted += 1
        self._history.append(Event(name=event, payload=dict(payload)))
        delivered = 0
        for handler in list(self._handlers.get(event, [])):
            try:
                result = handler(dict(payload))
                if asyncio.iscoroutine(result):
                    await result
                delivered += 1
                self.delivered += 1
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - one subscriber cannot break the bus
                self.failures += 1
                logger.warning("Event handler for '%s' failed: %s", event, exc)
        return delivered

    def recent(self, limit: int = 20) -> List[Dict[str, Any]]:
        return [
            {"name": event.name, "created_at": event.created_at, "keys": sorted(event.payload)}
            for event in list(self._history)[-max(1, limit):]
        ]


bus = EventBus()


def register_service(service: Service) -> Service:
    return registry.register(service)


__all__ = [
    "Event",
    "EventBus",
    "Service",
    "ServiceRegistry",
    "bus",
    "register_service",
    "registry",
]
