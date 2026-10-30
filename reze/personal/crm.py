"""Personal CRM: contacts, interaction history and relationship reminders."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.search import universal


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


class CRMService:
    def save(
        self,
        name: str,
        username: str = "",
        telegram_id: int = 0,
        tags: str = "",
        notes: str = "",
        birthday: str = "",
    ) -> int:
        cleaned = " ".join((name or "").split())
        if not cleaned:
            raise ValueError("A contact needs a name.")
        db.execute(
            "INSERT INTO crm_contacts (name, username, telegram_id, tags, notes, birthday) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET username = excluded.username, "
            "telegram_id = excluded.telegram_id, tags = excluded.tags, "
            "notes = excluded.notes, birthday = excluded.birthday, updated_at = CURRENT_TIMESTAMP",
            (
                cleaned[:120],
                (username or "").lstrip("@")[:64],
                int(telegram_id or 0),
                (tags or "")[:200],
                (notes or "")[:4000],
                (birthday or "")[:10],
            ),
        )
        row = self.get(cleaned)
        if row:
            universal.index("contact", row["id"], row["name"], f"{row['notes']} {row['tags']}", row["tags"])
        return int(row["id"]) if row else 0

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return db.query_one("SELECT * FROM crm_contacts WHERE lower(name) = lower(?)", ((name or "").strip(),))

    def list(self, limit: int = 30, tag: str = "") -> List[Dict[str, Any]]:
        sql = "SELECT * FROM crm_contacts"
        params: List[Any] = []
        if tag:
            sql += " WHERE tags LIKE ?"
            params.append(f"%{tag}%")
        sql += " ORDER BY last_contact_at DESC, name ASC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        return db.query(sql, params)

    def delete(self, name: str) -> bool:
        row = self.get(name)
        if not row:
            return False
        db.execute("DELETE FROM crm_contacts WHERE id = ?", (row["id"],))
        universal.unindex("contact", row["id"])
        return True

    def log_interaction(self, contact: str, kind: str, summary: str, occurred_at: str = "") -> int:
        row = self.get(contact)
        if row is None:
            raise ValueError(f"No contact named '{contact}'. Add one with .crm add.")
        interaction_id = db.execute(
            "INSERT INTO crm_interactions (contact_id, kind, summary, occurred_at) "
            "VALUES (?, ?, ?, ?)",
            (row["id"], (kind or "note")[:30], (summary or "")[:2000], (occurred_at or _now())[:19]),
        )
        db.execute(
            "UPDATE crm_contacts SET last_contact_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ((occurred_at or _now())[:19], row["id"]),
        )
        return interaction_id

    def interactions(self, contact: str, limit: int = 20) -> List[Dict[str, Any]]:
        row = self.get(contact)
        if row is None:
            return []
        return db.query(
            "SELECT * FROM crm_interactions WHERE contact_id = ? ORDER BY id DESC LIMIT ?",
            (row["id"], max(1, min(int(limit), 100))),
        )

    def upcoming_birthdays(self, days: int = 30, today: Optional[date] = None) -> List[Dict[str, Any]]:
        today = today or date.today()
        horizon = today + timedelta(days=max(1, int(days)))
        result = []
        for row in db.query("SELECT * FROM crm_contacts WHERE birthday != ''"):
            parsed = self._birthday(row.get("birthday", ""), today.year)
            if parsed is None:
                continue
            if parsed < today:
                parsed = self._birthday(row.get("birthday", ""), today.year + 1)
            if parsed and today <= parsed <= horizon:
                row = dict(row)
                row["next_birthday"] = parsed.isoformat()
                row["in_days"] = (parsed - today).days
                result.append(row)
        return sorted(result, key=lambda item: item["next_birthday"])

    @staticmethod
    def _birthday(value: str, year: int) -> Optional[date]:
        text = (value or "").strip()
        try:
            if len(text) >= 10:
                parts = text.split("-")
                return date(year, int(parts[1]), int(parts[2]))
            if len(text) == 5:
                month, day = text.split("-")
                return date(year, int(month), int(day))
        except (ValueError, IndexError):
            return None
        return None

    def stale(self, days: int = 30, limit: int = 20) -> List[Dict[str, Any]]:
        cutoff = (datetime.utcnow() - timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")
        return db.query(
            "SELECT * FROM crm_contacts WHERE last_contact_at = '' OR last_contact_at < ? "
            "ORDER BY last_contact_at ASC LIMIT ?",
            (cutoff, max(1, min(int(limit), 100))),
        )

    def count(self) -> int:
        row = db.query_one("SELECT COUNT(*) AS total FROM crm_contacts")
        return int((row or {}).get("total") or 0)


crm_service = CRMService()

__all__ = ["CRMService", "crm_service"]
