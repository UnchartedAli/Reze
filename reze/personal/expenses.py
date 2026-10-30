"""Local expense tracking with monthly summaries."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from reze.database import db
from reze.search import universal


def _month(value: str = "") -> str:
    return (value or date.today().strftime("%Y-%m"))[:7]


class ExpenseService:
    def add(
        self,
        amount: float,
        category: str = "general",
        note: str = "",
        currency: str = "IRT",
        spent_on: str = "",
    ) -> int:
        try:
            value = float(amount)
        except (TypeError, ValueError) as exc:
            raise ValueError("The amount must be a number.") from exc
        if value <= 0:
            raise ValueError("The amount must be positive.")
        expense_id = db.execute(
            "INSERT INTO expenses (amount, currency, category, note, spent_on) VALUES (?, ?, ?, ?, ?)",
            (
                value,
                (currency or "IRT").upper()[:8],
                (category or "general")[:40],
                (note or "")[:500],
                (spent_on or date.today().isoformat())[:10],
            ),
        )
        universal.index("expense", expense_id, f"{category} {value:g}", note, category)
        return expense_id

    def list(self, month: str = "", limit: int = 30) -> List[Dict[str, Any]]:
        month = _month(month)
        return db.query(
            "SELECT * FROM expenses WHERE spent_on LIKE ? ORDER BY spent_on DESC, id DESC LIMIT ?",
            (f"{month}-%", max(1, min(int(limit), 100))),
        )

    def summary(self, month: str = "") -> Dict[str, Any]:
        month = _month(month)
        rows = db.query(
            "SELECT category, currency, SUM(amount) AS total, COUNT(*) AS count FROM expenses "
            "WHERE spent_on LIKE ? GROUP BY category, currency ORDER BY total DESC",
            (f"{month}-%",),
        )
        totals: Dict[str, float] = {}
        for row in rows:
            currency = row.get("currency") or "IRT"
            totals[currency] = totals.get(currency, 0.0) + float(row.get("total") or 0)
        return {
            "month": month,
            "by_category": rows,
            "totals": totals,
            "count": sum(int(row.get("count") or 0) for row in rows),
        }

    def delete(self, expense_id: int) -> bool:
        row = db.query_one("SELECT id FROM expenses WHERE id = ?", (int(expense_id),))
        if row is None:
            return False
        db.execute("DELETE FROM expenses WHERE id = ?", (int(expense_id),))
        universal.unindex("expense", expense_id)
        return True


expense_service = ExpenseService()

__all__ = ["ExpenseService", "expense_service"]
