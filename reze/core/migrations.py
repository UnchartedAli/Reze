"""
Versioned, incremental SQLite migrations.

The REZE 2 schema was created with ``CREATE TABLE IF NOT EXISTS`` and a hard
coded ``PRAGMA user_version = 2``. REZE 3 keeps that baseline untouched and
applies numbered migrations on top of it:

* the current version lives in ``PRAGMA user_version`` and in the
  ``schema_migrations`` table (so the applied history is inspectable);
* every migration runs inside one transaction; a failure rolls the whole
  migration back and leaves the database at its previous version;
* migrations are append-only, idempotent and never drop or recreate user data.

Typical use::

    from reze.core.migrations import run_migrations
    applied = run_migrations(conn, MIGRATIONS, baseline=2)
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable, Iterable, List, Sequence

from reze.logging_config import logger

#: The REZE 2 schema version is the migration baseline.
BASELINE_VERSION = 2


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def applied_versions(conn: sqlite3.Connection) -> List[int]:
    try:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    except sqlite3.Error:
        return []
    return [int(row[0]) for row in rows]


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    # PRAGMA statements cannot be parameterised; the value is an int from our
    # own migration table, never user input.
    conn.execute(f"PRAGMA user_version = {int(version)}")


def run_migrations(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration],
    baseline: int = BASELINE_VERSION,
) -> List[int]:
    """Apply every migration newer than the stored version. Returns applied versions."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY,"
        "name TEXT NOT NULL,"
        "applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    version = current_version(conn)
    if version < baseline:
        # A pre-versioning database already has the REZE 2 tables; record the
        # baseline without touching data.
        _set_version(conn, baseline)
        version = baseline
    conn.commit()

    already = set(applied_versions(conn))
    applied: List[int] = []
    for migration in sorted(migrations, key=lambda item: item.version):
        if migration.version <= version:
            continue
        if migration.version in already:
            # Bookkeeping drift: trust the table and move the counter forward.
            _set_version(conn, migration.version)
            version = migration.version
            continue
        logger.info("Applying database migration %d (%s)", migration.version, migration.name)
        try:
            migration.apply(conn)
            conn.execute(
                "INSERT OR REPLACE INTO schema_migrations (version, name) VALUES (?, ?)",
                (migration.version, migration.name),
            )
            _set_version(conn, migration.version)
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - roll back and surface the reason
            conn.rollback()
            logger.error(
                "Migration %d (%s) failed: %s. The database was left at version %d.",
                migration.version,
                migration.name,
                exc,
                version,
            )
            raise
        version = migration.version
        applied.append(migration.version)
    return applied


def execute_all(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    """Execute a list of DDL statements inside the current transaction."""
    for statement in statements:
        sql = statement.strip()
        if sql:
            conn.execute(sql)


__all__ = [
    "BASELINE_VERSION",
    "Migration",
    "applied_versions",
    "current_version",
    "execute_all",
    "run_migrations",
]
