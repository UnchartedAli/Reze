"""Focus Mode: timed sessions with a do-not-disturb window and statistics."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from reze.core.registry import Service
from reze.database import db
from reze.logging_config import logger

MAX_MINUTES = 240


def _now() -> datetime:
    return datetime.utcnow()


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%d %H:%M:%S")


class FocusService(Service):
    name = "focus"
    feature = "focus"
    description = "Closes focus sessions whose timer expired."

    def start_session(self, label: str = "", minutes: int = 25) -> Dict[str, Any]:
        active = self.active()
        if active:
            return {"session": active, "started": False}
        minutes = max(1, min(int(minutes or 25), MAX_MINUTES))
        session_id = db.execute(
            "INSERT INTO focus_sessions (label, started_at, minutes) VALUES (?, ?, ?)",
            ((label or "")[:200], _stamp(_now()), minutes),
        )
        return {"session": db.query_one("SELECT * FROM focus_sessions WHERE id = ?", (session_id,)), "started": True}

    def active(self) -> Optional[Dict[str, Any]]:
        return db.query_one("SELECT * FROM focus_sessions WHERE ended_at = '' ORDER BY id DESC LIMIT 1")

    def stop_session(self, completed: Optional[bool] = None) -> Optional[Dict[str, Any]]:
        active = self.active()
        if not active:
            return None
        started = self._parse(active["started_at"])
        elapsed_minutes = max(0.0, (_now() - started).total_seconds() / 60) if started else 0.0
        if completed is None:
            completed = elapsed_minutes >= float(active.get("minutes") or 0)
        db.execute(
            "UPDATE focus_sessions SET ended_at = ?, completed = ?, interrupted = ? WHERE id = ?",
            (
                _stamp(_now()),
                1 if completed else 0,
                0 if completed else 1,
                active["id"],
            ),
        )
        updated = db.query_one("SELECT * FROM focus_sessions WHERE id = ?", (active["id"],))
        if updated:
            updated["elapsed_minutes"] = round(elapsed_minutes, 1)
        return updated

    async def tick(self) -> int:
        """Auto-complete sessions whose timer expired. No messages are sent."""
        active = self.active()
        if not active:
            return 0
        started = self._parse(active["started_at"])
        if started is None:
            return 0
        due = started + timedelta(minutes=float(active.get("minutes") or 0))
        if _now() < due:
            return 0
        db.execute(
            "UPDATE focus_sessions SET ended_at = ?, completed = 1, interrupted = 0 WHERE id = ?",
            (_stamp(due), active["id"]),
        )
        logger.info("Focus session #%s completed automatically.", active["id"])
        return 1

    async def start(self) -> None:
        await super().start()
        self._spawn(self._loop(), "focus")

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001 - one bad row cannot kill the loop
                logger.debug("Focus tick failed: %s", exc)
            await asyncio.sleep(30)

    def stats(self, days: int = 7) -> Dict[str, Any]:
        cutoff = _stamp(_now() - timedelta(days=max(1, int(days))))
        rows: List[Dict[str, Any]] = db.query(
            "SELECT * FROM focus_sessions WHERE started_at >= ? ORDER BY id DESC", (cutoff,)
        )
        completed = sum(1 for row in rows if row.get("completed"))
        minutes = sum(float(row.get("minutes") or 0) for row in rows if row.get("completed"))
        return {
            "days": days,
            "sessions": len(rows),
            "completed": completed,
            "completion_rate": round(completed / len(rows) * 100, 1) if rows else 0.0,
            "minutes": int(minutes),
            "hours": round(minutes / 60, 1),
            "recent": rows[:10],
        }

    @staticmethod
    def _parse(value: str) -> Optional[datetime]:
        try:
            return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            return None


focus_service = FocusService()

__all__ = ["FocusService", "focus_service"]
