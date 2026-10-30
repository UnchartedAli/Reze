"""Timeline: one chronological stream of what happened inside REZE."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.search import universal


class TimelineService:
    def append(
        self,
        kind: str,
        title: str,
        body: str = "",
        ref_type: str = "",
        ref_id: Any = "",
        tags: str = "",
        chat_id: int = 0,
        source: str = "reze",
    ) -> int:
        event_id = db.execute(
            "INSERT INTO timeline_events (kind, title, body, ref_type, ref_id, tags, chat_id, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                (kind or "event")[:40],
                (title or "")[:200],
                (body or "")[:4000],
                (ref_type or "")[:40],
                str(ref_id or "")[:80],
                (tags or "")[:200],
                int(chat_id or 0),
                (source or "reze")[:40],
            ),
        )
        universal.index("timeline", event_id, title[:80], f"{title} {body}", tags)
        return event_id

    def recent(
        self,
        limit: int = 20,
        kind: Optional[str] = None,
        days: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM timeline_events WHERE 1=1"
        params: List[Any] = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if days:
            cutoff = (datetime.utcnow() - timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
            sql += " AND created_at >= ?"
            params.append(cutoff)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        return db.query(sql, params)

    def count(self, days: Optional[int] = None) -> int:
        if days:
            cutoff = (datetime.utcnow() - timedelta(days=int(days))).strftime("%Y-%m-%d %H:%M:%S")
            row = db.query_one("SELECT COUNT(*) AS total FROM timeline_events WHERE created_at >= ?", (cutoff,))
        else:
            row = db.query_one("SELECT COUNT(*) AS total FROM timeline_events")
        return int((row or {}).get("total") or 0)


timeline_service = TimelineService()

__all__ = ["TimelineService", "timeline_service"]
