"""Save a verified copy of the database before an upgrade changes it.

Runs before any write during startup. It does nothing for a new database, for a
database that is already at the current version, or when no migration is pending.

If the copy cannot be made and checked, startup stops and the database is left
unchanged. Set ``REZE_SKIP_UPGRADE_BACKUP=1`` only if you accept upgrading with no
copy at all.
"""

from __future__ import annotations

import glob
import os
import sqlite3
from typing import List, Optional, Sequence

from reze.logging_config import logger
from reze.timeutil import utcnow

BASELINE_VERSION = 2
PREFIX = "pre-upgrade-"
KEEP = 5
SKIP_ENV = "REZE_SKIP_UPGRADE_BACKUP"


class UpgradeBackupError(RuntimeError):
    """The pre-upgrade copy could not be made or verified. Startup must stop."""


def _pending(path: str, migration_versions: Sequence[int]) -> Optional[List[int]]:
    """Return the pending migration versions for an existing, non-empty database, else None."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        tables = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
    finally:
        conn.close()
    if tables == 0:
        return None  # a new database has nothing to lose
    pending = [v for v in migration_versions if v > max(version, BASELINE_VERSION)]
    return pending or None


def prune(directory: str, keep: int = KEEP) -> int:
    """Keep the newest *keep* pre-upgrade copies. Returns how many were removed."""
    files = sorted(glob.glob(os.path.join(directory, PREFIX + "*.db")), key=os.path.getmtime, reverse=True)
    removed = 0
    for old in files[keep:]:
        try:
            os.remove(old)
            removed += 1
        except OSError as exc:
            logger.warning("Could not remove an old pre-upgrade copy: %s", type(exc).__name__)
    return removed


def backup_before_upgrade(path: str, migration_versions: Sequence[int]) -> Optional[str]:
    """Copy and verify the database when an upgrade is pending. Returns the copy's path, or None."""
    if os.environ.get(SKIP_ENV, "").strip().lower() in ("1", "true", "yes"):
        logger.warning("Upgrade backup skipped because %s is set.", SKIP_ENV)
        return None
    if not os.path.isfile(path):
        return None
    pending = _pending(path, migration_versions)
    if not pending:
        return None

    directory = os.path.join(os.path.dirname(os.path.abspath(path)), "backups")
    try:
        os.makedirs(directory, exist_ok=True)
        stamp = utcnow().strftime("%Y%m%d-%H%M%S-%f")
        target = os.path.join(directory, f"{PREFIX}v{pending[0]}-{stamp}.db")
        source = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
            source_version = source.execute("PRAGMA user_version").fetchone()[0]
        finally:
            destination.close()
            source.close()

        check = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        try:
            integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            copy_version = check.execute("PRAGMA user_version").fetchone()[0]
        finally:
            check.close()
        if integrity != "ok" or copy_version != source_version:
            raise UpgradeBackupError(f"copy failed verification (integrity={integrity})")
    except (OSError, sqlite3.Error, UpgradeBackupError) as exc:
        raise UpgradeBackupError(
            f"Could not save a copy of the database before upgrading ({type(exc).__name__}). "
            f"Startup stopped and the database was not changed. Check that {directory} is writable, "
            f"or set {SKIP_ENV}=1 to upgrade without a copy."
        ) from exc

    prune(directory)
    logger.info("Saved a verified copy before upgrading to version %d: %s", pending[0], os.path.basename(target))
    return target


__all__ = ["KEEP", "PREFIX", "SKIP_ENV", "UpgradeBackupError", "backup_before_upgrade", "prune"]
