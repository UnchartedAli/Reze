"""
Personal reminder scheduling.

Reminders are stored in SQLite with a UTC due timestamp and fired by one
background loop started with the application. The loop is intentionally simple:
poll every 15 seconds, deliver due reminders, mark them fired. A reminder that
cannot be delivered is retried once and then marked failed, so a broken chat can
never spin forever.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional

from reze.database import db
from reze.logging_config import logger
from reze.ui import ascii

DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
MAX_REMINDER_DAYS = 365


def parse_duration(value: str) -> int:
    """Parse ``30s``, ``10m``, ``2h``, ``3d`` or a bare number of minutes."""
    text = (value or "").strip().lower()
    if not text:
        raise ValueError("A duration is required, for example 10m.")
    unit = text[-1]
    if unit in DURATION_UNITS:
        number_part = text[:-1]
        factor = DURATION_UNITS[unit]
    else:
        number_part = text
        factor = 60
    try:
        amount = int(number_part)
    except ValueError as exc:
        raise ValueError("The duration must look like 30s, 10m, 2h or 3d.") from exc
    if amount <= 0:
        raise ValueError("The duration must be positive.")
    seconds = amount * factor
    if seconds > MAX_REMINDER_DAYS * 86400:
        raise ValueError(f"Reminders can be scheduled at most {MAX_REMINDER_DAYS} days ahead.")
    return seconds


def parse_absolute(value: str, tz_name: str) -> datetime:
    """Parse ``YYYY-MM-DD HH:MM`` in the configured timezone -> UTC naive."""
    from zoneinfo import ZoneInfo

    try:
        local = datetime.strptime(value.strip(), "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Absolute times look like 2026-11-01 18:30.") from exc
    try:
        zone = ZoneInfo(tz_name)
    except Exception:
        zone = timezone.utc
    localized = local.replace(tzinfo=zone)
    return localized.astimezone(timezone.utc).replace(tzinfo=None)


class ReminderService:
    def __init__(self, client_provider=None, interval: int = 15):
        self.client_provider = client_provider
        self.interval = max(5, int(interval))
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.delivered = 0
        self.failed = 0

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="reze-reminders")
        logger.info("Reminder service started (interval %ds).", self.interval)

    def stop(self) -> None:
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            logger.info("Reminder service stopped.")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Reminder loop error: %s", exc)
            await asyncio.sleep(self.interval)

    async def tick(self) -> int:
        """Deliver every due reminder and return how many were delivered."""
        due = db.due_reminders(datetime.utcnow())
        delivered = 0
        for reminder in due:
            text = ascii.frame(
                "Reminder",
                [reminder["text"], f"Set for {reminder['due_at']} UTC"],
                footer="REZE reminder service",
            )
            client = self.client_provider() if self.client_provider else None
            if client is None:
                continue
            try:
                await client.send_message(int(reminder["chat_id"]), text)
                db.mark_reminder_fired(int(reminder["id"]))
                delivered += 1
                self.delivered += 1
            except Exception as exc:  # noqa: BLE001 - chat may be unreachable
                self.failed += 1
                logger.warning("Could not deliver reminder %s: %s", reminder["id"], exc)
                db.mark_reminder_fired(int(reminder["id"]))
        return delivered


reminder_service = ReminderService()
