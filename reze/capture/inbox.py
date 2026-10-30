"""Smart Inbox: local prioritization of incoming messages.

The inbox never replies, never forwards and never contacts anyone. It only
classifies messages the account already received, and only while the optional
``smart_inbox`` feature is explicitly enabled.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.localization.manager import normalize

URGENT = ("urgent", "asap", "immediately", "deadline", "فوری", "فورا", "اضطراری", "فقط امروز")
ACTION = ("please", "need", "can you", "todo", "action", "لطفا", "لطفاً", "انجام بده", "نیاز دارم")
WAITING = ("waiting", "follow up", "منتظر", "پیگیری")
FYI = ("fyi", "for your information", "اطلاع", "بدانید")


def classify(text: str, sender_name: str = "") -> Dict[str, Any]:
    """Return ``{"classification", "priority"}`` for one message (local only)."""
    body = normalize(text or "").lower()
    priority = 3
    label = "fyi"
    if any(word in body for word in URGENT):
        label, priority = "urgent", 5
    elif any(word in body for word in ACTION):
        label, priority = "action", 4
    elif any(word in body for word in WAITING):
        label, priority = "waiting", 3
    elif "?" in body or "؟" in body:
        label, priority = "question", 3
    elif any(word in body for word in FYI):
        label, priority = "fyi", 2

    for rule in _rules():
        if not int(rule.get("enabled") or 0):
            continue
        pattern = str(rule.get("pattern") or "").strip()
        if not pattern:
            continue
        try:
            if rule.get("kind") == "regex":
                if re.search(pattern, text or "", re.IGNORECASE):
                    label, priority = _apply_action(rule, label, priority)
            elif pattern.lower() in body:
                label, priority = _apply_action(rule, label, priority)
        except re.error:
            continue
    return {"classification": label, "priority": priority}


def _apply_action(rule: Dict[str, Any], label: str, priority: int) -> tuple:
    action = rule.get("action")
    value = str(rule.get("value") or "")
    if action == "priority":
        try:
            priority = max(1, min(int(value), 5))
        except ValueError:
            pass
    elif action == "classify" and value:
        label = value[:30]
    return label, priority


def _rules() -> List[Dict[str, Any]]:
    try:
        return db.query("SELECT * FROM inbox_rules WHERE enabled = 1")
    except Exception:  # pragma: no cover
        return []


class InboxService:
    def capture(
        self,
        chat_id: int,
        message_id: int,
        sender_id: int = 0,
        sender_name: str = "",
        text: str = "",
    ) -> Optional[Dict[str, Any]]:
        if not (text or "").strip():
            return None
        verdict = classify(text, sender_name)
        inserted = db.execute(
            "INSERT OR IGNORE INTO inbox_items "
            "(chat_id, message_id, sender_id, sender_name, text, classification, priority) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(chat_id or 0),
                int(message_id or 0),
                int(sender_id or 0),
                (sender_name or "")[:120],
                text[:4000],
                verdict["classification"],
                verdict["priority"],
            ),
        )
        if not inserted:
            return None
        return {
            "chat_id": int(chat_id or 0),
            "message_id": int(message_id or 0),
            "classification": verdict["classification"],
            "priority": verdict["priority"],
        }

    def list(self, status: str = "new", limit: int = 20) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM inbox_items"
        params: List[Any] = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY priority DESC, id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        return db.query(sql, params)

    def mark_read(self, item_id: int) -> bool:
        db.execute(
            "UPDATE inbox_items SET status = 'read', read_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(item_id),),
        )
        return True

    def stats(self) -> Dict[str, Any]:
        rows = db.query(
            "SELECT classification, COUNT(*) AS total FROM inbox_items "
            "WHERE status = 'new' GROUP BY classification ORDER BY total DESC"
        )
        total = db.query_one("SELECT COUNT(*) AS total FROM inbox_items WHERE status = 'new'")
        return {"unread": int((total or {}).get("total") or 0), "by_class": rows}

    def add_rule(self, kind: str, pattern: str, action: str = "priority", value: str = "") -> int:
        kind = kind if kind in {"keyword", "regex"} else "keyword"
        pattern = (pattern or "").strip()
        if not pattern:
            raise ValueError("A rule needs a pattern.")
        if kind == "regex":
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid regular expression: {exc}") from exc
        return db.execute(
            "INSERT INTO inbox_rules (kind, pattern, action, value, enabled) VALUES (?, ?, ?, ?, 1) "
            "ON CONFLICT(kind, pattern, action) DO UPDATE SET value = excluded.value, enabled = 1",
            (kind, pattern[:200], action[:30], value[:100]),
        )

    def rules(self) -> List[Dict[str, Any]]:
        return db.query("SELECT * FROM inbox_rules ORDER BY id DESC")

    def delete_rule(self, rule_id: int) -> bool:
        db.execute("DELETE FROM inbox_rules WHERE id = ?", (int(rule_id),))
        return True


inbox_service = InboxService()

__all__ = ["InboxService", "classify", "inbox_service"]
