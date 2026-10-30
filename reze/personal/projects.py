"""Local projects and tasks (no cloud account required)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.search import universal

STATUSES = ("todo", "doing", "done", "blocked")
PRIORITIES = {1: "low", 2: "normal", 3: "high", 4: "critical", 5: "urgent"}


class ProjectService:
    def create(self, name: str, description: str = "", due_at: str = "") -> int:
        cleaned = " ".join((name or "").split())
        if not cleaned:
            raise ValueError("A project needs a name.")
        db.execute(
            "INSERT INTO projects (name, description, due_at) VALUES (?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET description = excluded.description, "
            "due_at = excluded.due_at, updated_at = CURRENT_TIMESTAMP",
            (cleaned[:120], (description or "")[:2000], (due_at or "")[:10]),
        )
        row = self.get(cleaned)
        if row:
            universal.index("project", row["id"], row["name"], row["description"], row["status"])
        return int(row["id"]) if row else 0

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        return db.query_one("SELECT * FROM projects WHERE lower(name) = lower(?)", ((name or "").strip(),))

    def list(self, status: str = "active", limit: int = 30) -> List[Dict[str, Any]]:
        sql = "SELECT p.*, (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id AND t.status != 'done') AS open_tasks, (SELECT COUNT(*) FROM tasks t WHERE t.project_id = p.id) AS total_tasks FROM projects p"
        params: List[Any] = []
        if status:
            sql += " WHERE p.status = ?"
            params.append(status)
        sql += " ORDER BY p.id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        return db.query(sql, params)

    def close(self, name: str) -> bool:
        row = self.get(name)
        if not row:
            return False
        db.execute("UPDATE projects SET status = 'closed', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (row["id"],))
        return True

    def add_task(
        self,
        title: str,
        project: str = "",
        priority: int = 3,
        due_at: str = "",
        tags: str = "",
    ) -> int:
        cleaned = " ".join((title or "").split())
        if not cleaned:
            raise ValueError("A task needs a title.")
        project_id = None
        if project:
            row = self.get(project)
            if row is None:
                project_id = self.create(project)
            else:
                project_id = int(row["id"])
        task_id = db.execute(
            "INSERT INTO tasks (project_id, title, priority, due_at, tags) VALUES (?, ?, ?, ?, ?)",
            (
                project_id,
                cleaned[:300],
                max(1, min(int(priority or 3), 5)),
                (due_at or "")[:10],
                (tags or "")[:200],
            ),
        )
        universal.index("task", task_id, cleaned[:80], f"{cleaned} {tags}", "todo")
        return task_id

    def tasks(self, status: str = "", project: str = "", limit: int = 30) -> List[Dict[str, Any]]:
        sql = (
            "SELECT t.*, p.name AS project_name FROM tasks t "
            "LEFT JOIN projects p ON p.id = t.project_id WHERE 1=1"
        )
        params: List[Any] = []
        if status:
            sql += " AND t.status = ?"
            params.append(status)
        if project:
            sql += " AND p.name = ?"
            params.append(project)
        sql += " ORDER BY t.status = 'done', t.priority DESC, t.id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 100)))
        return db.query(sql, params)

    def complete(self, task_id: int) -> bool:
        row = db.query_one("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
        if row is None:
            return False
        db.execute(
            "UPDATE tasks SET status = 'done', completed_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(task_id),),
        )
        universal.unindex("task", task_id)
        return True

    def summary(self) -> Dict[str, Any]:
        open_row = db.query_one("SELECT COUNT(*) AS total FROM tasks WHERE status != 'done'")
        done_row = db.query_one("SELECT COUNT(*) AS total FROM tasks WHERE status = 'done'")
        overdue_row = db.query_one(
            "SELECT COUNT(*) AS total FROM tasks WHERE status != 'done' AND due_at != '' AND due_at < ?",
            (datetime.utcnow().strftime("%Y-%m-%d"),),
        )
        return {
            "open": int((open_row or {}).get("total") or 0),
            "done": int((done_row or {}).get("total") or 0),
            "overdue": int((overdue_row or {}).get("total") or 0),
        }


project_service = ProjectService()

__all__ = ["PRIORITIES", "ProjectService", "STATUSES", "project_service"]
