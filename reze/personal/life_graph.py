"""Life Graph: people, projects, places and topics linked by typed relations."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from reze.database import db
from reze.search import universal

ENTITY_KINDS = ("person", "project", "place", "topic", "thing", "event", "entity")


class LifeGraphService:
    def add_entity(self, kind: str, name: str, notes: str = "") -> int:
        cleaned = " ".join((name or "").split())
        if not cleaned:
            raise ValueError("An entity needs a name.")
        kind = (kind or "entity").lower()
        if kind not in ENTITY_KINDS:
            kind = "entity"
        db.execute(
            "INSERT INTO life_entities (kind, name, notes) VALUES (?, ?, ?) "
            "ON CONFLICT(kind, name) DO UPDATE SET notes = excluded.notes",
            (kind, cleaned[:120], (notes or "")[:2000]),
        )
        row = self.find(kind, cleaned)
        if row:
            universal.index("life", row["id"], row["name"], f"{row['kind']} {row['notes']}", row["kind"])
        return int(row["id"]) if row else 0

    def find(self, kind: str, name: str) -> Optional[Dict[str, Any]]:
        return db.query_one(
            "SELECT * FROM life_entities WHERE kind = ? AND lower(name) = lower(?)",
            ((kind or "entity").lower(), (name or "").strip()),
        )

    def ensure(self, name: str) -> Dict[str, Any]:
        """Find an entity by name across kinds, creating a generic one if needed."""
        row = db.query_one("SELECT * FROM life_entities WHERE lower(name) = lower(?) LIMIT 1", ((name or "").strip(),))
        if row:
            return row
        entity_id = self.add_entity("entity", name)
        return db.query_one("SELECT * FROM life_entities WHERE id = ?", (entity_id,)) or {}

    def link(self, source: str, relation: str, target: str) -> int:
        if not (source or "").strip() or not (target or "").strip():
            raise ValueError("Both sides of a relation are required.")
        relation = " ".join((relation or "related to").split())[:60]
        left = self.ensure(source)
        right = self.ensure(target)
        db.execute(
            "INSERT INTO life_relations (from_id, to_id, relation) VALUES (?, ?, ?) "
            "ON CONFLICT(from_id, to_id, relation) DO NOTHING",
            (left["id"], right["id"], relation),
        )
        row = db.query_one(
            "SELECT id FROM life_relations WHERE from_id = ? AND to_id = ? AND relation = ?",
            (left["id"], right["id"], relation),
        )
        return int((row or {}).get("id") or 0)

    def neighbors(self, name: str) -> List[Dict[str, Any]]:
        entity = db.query_one("SELECT * FROM life_entities WHERE lower(name) = lower(?) LIMIT 1", ((name or "").strip(),))
        if entity is None:
            return []
        return db.query(
            "SELECT r.relation, e.id, e.name, e.kind, 'out' AS direction "
            "FROM life_relations r JOIN life_entities e ON e.id = r.to_id WHERE r.from_id = ? "
            "UNION ALL "
            "SELECT r.relation, e.id, e.name, e.kind, 'in' AS direction "
            "FROM life_relations r JOIN life_entities e ON e.id = r.from_id WHERE r.to_id = ?",
            (entity["id"], entity["id"]),
        )

    def entities(self, kind: str = "", limit: int = 30) -> List[Dict[str, Any]]:
        if kind:
            return db.query(
                "SELECT * FROM life_entities WHERE kind = ? ORDER BY name LIMIT ?",
                (kind, max(1, min(int(limit), 100))),
            )
        return db.query("SELECT * FROM life_entities ORDER BY kind, name LIMIT ?", (max(1, min(int(limit), 100)),))

    def count(self) -> Dict[str, int]:
        entities = db.query_one("SELECT COUNT(*) AS total FROM life_entities")
        relations = db.query_one("SELECT COUNT(*) AS total FROM life_relations")
        return {
            "entities": int((entities or {}).get("total") or 0),
            "relations": int((relations or {}).get("total") or 0),
        }


life_graph = LifeGraphService()

__all__ = ["ENTITY_KINDS", "LifeGraphService", "life_graph"]
