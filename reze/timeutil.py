"""UTC helpers for REZE.

Timestamps in the SQLite database are stored as naive UTC strings (REZE 3.0
convention). ``utcnow()`` keeps that format without the deprecated stdlib call.
"""

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime, matching the values already stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


__all__ = ["utcnow"]
