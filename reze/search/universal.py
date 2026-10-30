"""Universal search: one FTS5 index (with a LIKE fallback) across REZE data."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from reze.database import db
from reze.localization.manager import normalize
from reze.logging_config import logger

INDEX_KINDS = (
    "memory",
    "note",
    "archive",
    "contact",
    "decision",
    "task",
    "project",
    "document",
    "timeline",
    "life",
    "expense",
    "vault",
)

_TOKEN_RE = re.compile(r"[^\w\u0600-\u06ff]+", re.UNICODE)
_MAX_QUERY_CHARS = 200


def _fts_enabled() -> bool:
    try:
        return db.get_setting("search.fts5", "0") == "1"
    except Exception:  # pragma: no cover - database unavailable
        return False


def _tokens(query: str) -> List[str]:
    text = normalize(query or "")[:_MAX_QUERY_CHARS]
    tokens = [token for token in _TOKEN_RE.split(text) if len(token) > 1]
    return tokens[:8]


def index(kind: str, ref_id: Any, title: str = "", body: str = "", tags: str = "") -> int:
    """Upsert one record into the search index. Never raises."""
    kind = (kind or "").strip().lower()
    if kind not in INDEX_KINDS:
        logger.debug("Refusing to index unknown kind '%s'", kind)
        return 0
    title_n = normalize(title or "")[:400]
    body_n = normalize(body or "")[:20000]
    tags_n = normalize(tags or "")[:400]
    try:
        db.execute(
            "INSERT INTO search_index (kind, ref_id, title, body, tags, updated_at) "
            "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP) "
            "ON CONFLICT(kind, ref_id) DO UPDATE SET title = excluded.title, "
            "body = excluded.body, tags = excluded.tags, updated_at = CURRENT_TIMESTAMP",
            (kind, str(ref_id), title_n, body_n, tags_n),
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - indexing must not block the write
        logger.debug("Could not index %s:%s (%s)", kind, ref_id, exc)
        return 0


def unindex(kind: str, ref_id: Any) -> bool:
    try:
        db.execute(
            "DELETE FROM search_index WHERE kind = ? AND ref_id = ?",
            ((kind or "").lower(), str(ref_id)),
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def search(
    query: str,
    kinds: Optional[Iterable[str]] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search the local index. FTS5 is used when available, LIKE otherwise."""
    tokens = _tokens(query)
    if not tokens:
        return []
    limit = max(1, min(int(limit or 20), 50))
    allowed = [kind for kind in (kinds or []) if kind in INDEX_KINDS]
    rows: List[Dict[str, Any]] = []

    if _fts_enabled():
        fts_query = " AND ".join(f'"{token}"*' for token in tokens)
        sql = (
            "SELECT s.id, s.kind, s.ref_id, s.title, s.body, s.tags, s.updated_at "
            "FROM search_fts f JOIN search_index s ON s.id = f.rowid "
            "WHERE search_fts MATCH ?"
        )
        params: List[Any] = [fts_query]
        if allowed:
            sql += " AND s.kind IN (" + ",".join("?" for _ in allowed) + ")"
            params.extend(allowed)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)
        try:
            rows = db.query(sql, params)
        except Exception as exc:  # noqa: BLE001 - FTS syntax/build problems
            logger.debug("FTS search failed (%s); falling back to LIKE.", exc)
            rows = []

    if not rows:
        like = "%" + "%".join(tokens) + "%"
        sql = "SELECT * FROM search_index WHERE (title LIKE ? OR body LIKE ? OR tags LIKE ?)"
        params = [like, like, like]
        if allowed:
            sql += " AND kind IN (" + ",".join("?" for _ in allowed) + ")"
            params.extend(allowed)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        try:
            rows = db.query(sql, params)
        except Exception as exc:  # pragma: no cover
            logger.debug("LIKE search failed: %s", exc)
            return []
    return rows


def stats() -> Dict[str, Any]:
    try:
        total = db.query_one("SELECT COUNT(*) AS total FROM search_index")
        by_kind = db.query(
            "SELECT kind, COUNT(*) AS count FROM search_index GROUP BY kind ORDER BY count DESC"
        )
    except Exception:  # pragma: no cover
        return {"total": 0, "kinds": [], "fts5": False}
    return {
        "total": int((total or {}).get("total") or 0),
        "kinds": by_kind,
        "fts5": _fts_enabled(),
    }


def rebuild() -> Dict[str, int]:
    """Rebuild the index from the source tables. Returns per-kind counts."""
    counts: Dict[str, int] = {}
    try:
        db.execute("DELETE FROM search_index")
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not clear the search index: %s", exc)
        return counts

    sources = (
        ("memory", "SELECT id, content, source, tags FROM memories"),
        ("note", "SELECT id, name, content, '' FROM personal_notes"),
        ("archive", "SELECT id, title, content, tags FROM archive"),
        ("contact", "SELECT id, name, notes, tags FROM crm_contacts"),
        (
            "decision",
            "SELECT id, title, options || ' ' || expected || ' ' || decision AS body, status "
            "FROM decisions",
        ),
        ("task", "SELECT id, title, status, tags FROM tasks"),
        ("project", "SELECT id, name, description, status FROM projects"),
        ("document", "SELECT id, name, summary, kind FROM documents"),
        ("timeline", "SELECT id, title, body, tags FROM timeline_events"),
        ("life", "SELECT id, name, notes, kind FROM life_entities"),
        ("expense", "SELECT id, category, note, currency FROM expenses"),
    )
    for kind, sql in sources:
        try:
            rows = db.query(sql)
        except Exception as exc:  # noqa: BLE001 - table may not exist yet
            logger.debug("Skipping index rebuild for %s: %s", kind, exc)
            continue
        for row in rows:
            values = list(row.values())
            index(kind, values[0], values[1], values[2], values[3])
        counts[kind] = len(rows)
    return counts


__all__ = ["INDEX_KINDS", "index", "rebuild", "search", "stats", "unindex"]
