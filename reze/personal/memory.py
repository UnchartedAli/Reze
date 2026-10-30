"""AI Brain persistent memory: local notes the assistant can recall."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from reze.database import db
from reze.logging_config import logger
from reze.search import universal

MAX_CONTENT = 8000


class MemoryService:
    """Persistent, searchable memories. Nothing leaves the machine."""

    def save(
        self,
        content: str,
        source: str = "manual",
        source_ref: str = "",
        tags: str = "",
        importance: int = 3,
    ) -> int:
        text = (content or "").strip()
        if not text:
            raise ValueError("A memory needs some text.")
        text = text[:MAX_CONTENT]
        importance = max(1, min(int(importance or 3), 5))
        memory_id = db.execute(
            "INSERT INTO memories (content, source, source_ref, tags, importance) "
            "VALUES (?, ?, ?, ?, ?)",
            (text, (source or "manual")[:40], str(source_ref or "")[:200], (tags or "")[:200], importance),
        )
        universal.index("memory", memory_id, text[:80], text, tags)
        logger.info("Memory #%s saved (source=%s, %d chars)", memory_id, source, len(text))
        return memory_id

    def get(self, memory_id: int) -> Optional[Dict[str, Any]]:
        return db.query_one("SELECT * FROM memories WHERE id = ?", (int(memory_id),))

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        rows = universal.search(query, kinds=["memory"], limit=limit)
        if not rows:
            return []
        ids = [int(row["ref_id"]) for row in rows if str(row.get("ref_id", "")).isdigit()]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        records = db.query(
            f"SELECT * FROM memories WHERE id IN ({placeholders}) AND archived = 0",
            ids,
        )
        order = {memory_id: index for index, memory_id in enumerate(ids)}
        return sorted(records, key=lambda row: order.get(int(row["id"]), 999))

    def recent(self, limit: int = 10, include_archived: bool = False) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM memories"
        if not include_archived:
            sql += " WHERE archived = 0"
        sql += " ORDER BY pinned DESC, id DESC LIMIT ?"
        return db.query(sql, (max(1, min(int(limit), 100)),))

    def forget(self, memory_id: int) -> bool:
        row = self.get(memory_id)
        if not row:
            return False
        db.execute("DELETE FROM memories WHERE id = ?", (int(memory_id),))
        universal.unindex("memory", memory_id)
        return True

    def pin(self, memory_id: int, pinned: bool = True) -> bool:
        count = db.execute(
            "UPDATE memories SET pinned = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (1 if pinned else 0, int(memory_id)),
        )
        return bool(count)

    def archive(self, memory_id: int, archived: bool = True) -> bool:
        db.execute("UPDATE memories SET archived = ? WHERE id = ?", (1 if archived else 0, int(memory_id)))
        if archived:
            universal.unindex("memory", memory_id)
        else:
            row = self.get(memory_id)
            if row:
                universal.index("memory", memory_id, row["content"][:80], row["content"], row["tags"])
        return True

    def count(self) -> int:
        row = db.query_one("SELECT COUNT(*) AS total FROM memories WHERE archived = 0")
        return int((row or {}).get("total") or 0)


memory_service = MemoryService()

__all__ = ["MemoryService", "memory_service"]
