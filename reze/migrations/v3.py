"""REZE 3.0 schema, migration 3: services, features and personal OS tables."""

from __future__ import annotations

import sqlite3

from reze.core.migrations import execute_all

STATEMENTS = [
    # ---------------------------------------------------------------- governance
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS feature_state (
        key TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_by INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        actor INTEGER DEFAULT 0,
        action TEXT NOT NULL,
        target TEXT DEFAULT '',
        detail TEXT DEFAULT '',
        outcome TEXT DEFAULT 'ok'
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action)",
    # --------------------------------------------------------------------- memory
    """
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        source TEXT NOT NULL DEFAULT 'manual',
        source_ref TEXT DEFAULT '',
        tags TEXT DEFAULT '',
        importance INTEGER NOT NULL DEFAULT 3,
        pinned INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_memories_archived ON memories(archived)",
    # ------------------------------------------------------------------- timeline
    """
    CREATE TABLE IF NOT EXISTS timeline_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        kind TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        body TEXT DEFAULT '',
        ref_type TEXT DEFAULT '',
        ref_id TEXT DEFAULT '',
        source TEXT DEFAULT 'reze',
        tags TEXT DEFAULT '',
        chat_id INTEGER DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_timeline_created ON timeline_events(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_timeline_kind ON timeline_events(kind)",
    # ------------------------------------------------------------------ life graph
    """
    CREATE TABLE IF NOT EXISTS life_entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        notes TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(kind, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS life_relations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        from_id INTEGER NOT NULL REFERENCES life_entities(id) ON DELETE CASCADE,
        to_id INTEGER NOT NULL REFERENCES life_entities(id) ON DELETE CASCADE,
        relation TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(from_id, to_id, relation)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_relations_from ON life_relations(from_id)",
    "CREATE INDEX IF NOT EXISTS idx_relations_to ON life_relations(to_id)",
    # ------------------------------------------------------------------------ CRM
    """
    CREATE TABLE IF NOT EXISTS crm_contacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        username TEXT DEFAULT '',
        telegram_id INTEGER DEFAULT 0,
        tags TEXT DEFAULT '',
        notes TEXT DEFAULT '',
        birthday TEXT DEFAULT '',
        last_contact_at TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(name)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_contacts_name ON crm_contacts(name)",
    """
    CREATE TABLE IF NOT EXISTS crm_interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contact_id INTEGER NOT NULL REFERENCES crm_contacts(id) ON DELETE CASCADE,
        kind TEXT NOT NULL DEFAULT 'note',
        summary TEXT NOT NULL,
        occurred_at TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_interactions_contact ON crm_interactions(contact_id)",
    # ------------------------------------------------------------------- decisions
    """
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        options TEXT DEFAULT '',
        expected TEXT DEFAULT '',
        decision TEXT DEFAULT '',
        outcome TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        review_at TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        decided_at TEXT DEFAULT '',
        reviewed_at TEXT DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_decisions_status ON decisions(status)",
    "CREATE INDEX IF NOT EXISTS idx_decisions_review ON decisions(review_at)",
    # ------------------------------------------------------------------ focus mode
    """
    CREATE TABLE IF NOT EXISTS focus_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        label TEXT DEFAULT '',
        started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        ended_at TEXT DEFAULT '',
        minutes INTEGER NOT NULL DEFAULT 25,
        completed INTEGER NOT NULL DEFAULT 0,
        interrupted INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_focus_started ON focus_sessions(started_at)",
    # ----------------------------------------------------------------- writing DNA
    """
    CREATE TABLE IF NOT EXISTS writing_samples (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        content TEXT NOT NULL,
        source TEXT DEFAULT 'manual',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # -------------------------------------------------------------------- projects
    """
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        status TEXT NOT NULL DEFAULT 'active',
        due_at TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'todo',
        priority INTEGER NOT NULL DEFAULT 3,
        due_at TEXT DEFAULT '',
        tags TEXT DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        completed_at TEXT DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)",
    # -------------------------------------------------------------------- expenses
    """
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        amount REAL NOT NULL,
        currency TEXT NOT NULL DEFAULT 'IRT',
        category TEXT DEFAULT 'general',
        note TEXT DEFAULT '',
        spent_on TEXT NOT NULL DEFAULT CURRENT_DATE,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_expenses_spent ON expenses(spent_on)",
    # ------------------------------------------------------------------ smart inbox
    """
    CREATE TABLE IF NOT EXISTS inbox_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL DEFAULT 0,
        message_id INTEGER NOT NULL DEFAULT 0,
        sender_id INTEGER NOT NULL DEFAULT 0,
        sender_name TEXT DEFAULT '',
        text TEXT DEFAULT '',
        classification TEXT DEFAULT 'unclassified',
        priority INTEGER NOT NULL DEFAULT 3,
        status TEXT NOT NULL DEFAULT 'new',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        read_at TEXT DEFAULT '',
        UNIQUE(chat_id, message_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_inbox_status ON inbox_items(status)",
    "CREATE INDEX IF NOT EXISTS idx_inbox_created ON inbox_items(created_at)",
    """
    CREATE TABLE IF NOT EXISTS inbox_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        kind TEXT NOT NULL,
        pattern TEXT NOT NULL,
        action TEXT NOT NULL DEFAULT 'priority',
        value TEXT DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(kind, pattern, action)
    )
    """,
    # ------------------------------------------------------------------------ vault
    """
    CREATE TABLE IF NOT EXISTS vault_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL DEFAULT 'secret',
        filename TEXT DEFAULT '',
        mime TEXT DEFAULT '',
        size INTEGER NOT NULL DEFAULT 0,
        nonce BLOB NOT NULL,
        ciphertext BLOB NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        accessed_at TEXT DEFAULT '',
        access_count INTEGER NOT NULL DEFAULT 0
    )
    """,
    # -------------------------------------------------------------------- workflows
    """
    CREATE TABLE IF NOT EXISTS workflows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 0,
        trigger_type TEXT NOT NULL DEFAULT 'manual',
        trigger_config TEXT NOT NULL DEFAULT '{}',
        steps TEXT NOT NULL DEFAULT '[]',
        cooldown_seconds INTEGER NOT NULL DEFAULT 60,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        last_run TEXT DEFAULT '',
        run_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
        status TEXT NOT NULL DEFAULT 'pending',
        idempotency_key TEXT NOT NULL UNIQUE,
        context TEXT NOT NULL DEFAULT '{}',
        attempts INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        started_at TEXT DEFAULT '',
        finished_at TEXT DEFAULT '',
        error TEXT DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_runs_workflow ON workflow_runs(workflow_id)",
    "CREATE INDEX IF NOT EXISTS idx_runs_status ON workflow_runs(status)",
    """
    CREATE TABLE IF NOT EXISTS workflow_steps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
        step_index INTEGER NOT NULL,
        action TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        output TEXT DEFAULT '',
        error TEXT DEFAULT '',
        started_at TEXT DEFAULT '',
        finished_at TEXT DEFAULT '',
        UNIQUE(run_id, step_index)
    )
    """,
    # ------------------------------------------------------------- AI tool calling
    """
    CREATE TABLE IF NOT EXISTS ai_tool_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        request_id TEXT DEFAULT '',
        tool TEXT NOT NULL,
        args TEXT DEFAULT '{}',
        status TEXT NOT NULL,
        actor INTEGER DEFAULT 0,
        approval_id INTEGER,
        result TEXT DEFAULT '',
        error TEXT DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_tool_audit_created ON ai_tool_audit(created_at)",
    """
    CREATE TABLE IF NOT EXISTS ai_approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL UNIQUE,
        tool TEXT NOT NULL,
        args TEXT NOT NULL DEFAULT '{}',
        chat_id INTEGER NOT NULL DEFAULT 0,
        user_id INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        result TEXT DEFAULT ''
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_approvals_status ON ai_approvals(status)",
    """
    CREATE TABLE IF NOT EXISTS ai_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        day TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'chat',
        calls INTEGER NOT NULL DEFAULT 0,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        total_tokens INTEGER NOT NULL DEFAULT 0,
        UNIQUE(day, provider, model, kind)
    )
    """,
    # ------------------------------------------------------------------- sentinel
    """
    CREATE TABLE IF NOT EXISTS sentinel_findings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        check_name TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'info',
        title TEXT NOT NULL,
        detail TEXT NOT NULL DEFAULT '',
        resolved INTEGER NOT NULL DEFAULT 0,
        resolved_at TEXT DEFAULT ''
    )
    """,
    # --------------------------------------------------------- document ingestion
    """
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        name TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'text',
        chars INTEGER NOT NULL DEFAULT 0,
        summary TEXT DEFAULT '',
        memory_id INTEGER,
        content_hash TEXT DEFAULT '',
        source TEXT DEFAULT 'reply'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS voice_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        duration_seconds INTEGER NOT NULL DEFAULT 0,
        transcript TEXT NOT NULL DEFAULT '',
        memory_id INTEGER,
        chat_id INTEGER DEFAULT 0,
        message_id INTEGER DEFAULT 0
    )
    """,
    # ---------------------------------------------------- maintenance and backups
    """
    CREATE TABLE IF NOT EXISTS maintenance_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        action TEXT NOT NULL,
        status TEXT NOT NULL,
        detail TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        path TEXT NOT NULL,
        size_bytes INTEGER NOT NULL DEFAULT 0,
        kind TEXT NOT NULL DEFAULT 'manual',
        status TEXT NOT NULL DEFAULT 'ok',
        detail TEXT DEFAULT ''
    )
    """,
]


def apply(conn: sqlite3.Connection) -> None:
    execute_all(conn, STATEMENTS)
