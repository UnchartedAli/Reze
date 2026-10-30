"""Decision journal: record a decision, its expectation and a later review."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.search import universal


def _stamp(days_ahead: Optional[int] = None) -> str:
    moment = datetime.utcnow() + timedelta(days=int(days_ahead or 0))
    return moment.strftime("%Y-%m-%d %H:%M:%S")


class DecisionService:
    def log(
        self,
        title: str,
        options: str = "",
        expected: str = "",
        review_in_days: int = 0,
        review_at: str = "",
    ) -> int:
        cleaned = " ".join((title or "").split())
        if not cleaned:
            raise ValueError("A decision needs a title.")
        when = review_at or (_stamp(review_in_days) if review_in_days else "")
        decision_id = db.execute(
            "INSERT INTO decisions (title, options, expected, review_at, status) "
            "VALUES (?, ?, ?, ?, 'open')",
            (cleaned[:200], (options or "")[:2000], (expected or "")[:2000], when),
        )
        universal.index(
            "decision",
            decision_id,
            cleaned[:80],
            f"{options} {expected}",
            "open",
        )
        return decision_id

    def get(self, decision_id: int) -> Optional[Dict[str, Any]]:
        return db.query_one("SELECT * FROM decisions WHERE id = ?", (int(decision_id),))

    def list(self, status: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM decisions"
        params: List[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        return db.query(sql, params)

    def decide(self, decision_id: int, decision: str) -> bool:
        """Record the actual choice and move the entry to 'decided'."""
        row = self.get(decision_id)
        if row is None:
            return False
        db.execute(
            "UPDATE decisions SET decision = ?, status = 'decided', decided_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            ((decision or "")[:2000], int(decision_id)),
        )
        universal.index(
            "decision",
            decision_id,
            row["title"],
            f"{row['options']} {row['expected']} {decision}",
            "decided",
        )
        return True

    def review(self, decision_id: int, outcome: str) -> bool:
        row = self.get(decision_id)
        if row is None:
            return False
        db.execute(
            "UPDATE decisions SET outcome = ?, status = 'reviewed', reviewed_at = CURRENT_TIMESTAMP "
            "WHERE id = ?",
            ((outcome or "")[:2000], int(decision_id)),
        )
        return True

    def due_reviews(self, limit: int = 20) -> List[Dict[str, Any]]:
        now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        return db.query(
            "SELECT * FROM decisions WHERE status IN ('open', 'decided') "
            "AND review_at != '' AND review_at <= ? ORDER BY review_at ASC LIMIT ?",
            (now, max(1, min(int(limit), 100))),
        )

    def count(self) -> int:
        row = db.query_one("SELECT COUNT(*) AS total FROM decisions")
        return int((row or {}).get("total") or 0)


decision_service = DecisionService()

__all__ = ["DecisionService", "decision_service"]
