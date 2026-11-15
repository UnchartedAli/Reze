"""Pure scheduling rules for Channel Digest. No I/O and no clock access.

Times are local to the configured IANA timezone. Stored timestamps elsewhere in
REZE are naive UTC; this module converts at the edges.

Missed schedules: :func:`latest_due_slot` returns only the most recent due slot.
After downtime, the service sends one catch-up digest, not one per missed slot.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional, Set, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SCHEDULES = ("daily", "weekly", "custom")
DAY_TOKENS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
ALL_DAYS = ",".join(str(i) for i in range(7))


def parse_time_of_day(text: str) -> Tuple[int, int]:
    match = _TIME_RE.match((text or "").strip())
    if not match:
        raise ValueError("Use the 24-hour format HH:MM, for example 21:00.")
    return int(match.group(1)), int(match.group(2))


def format_time(hour: int, minute: int) -> str:
    return f"{hour:02d}:{minute:02d}"


def load_timezone(name: str) -> ZoneInfo:
    value = (name or "").strip()
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError, OSError) as exc:
        raise ValueError(
            f"Unknown timezone '{value}'. Use an IANA name such as Asia/Tehran or Europe/Berlin."
        ) from exc


def parse_schedule(schedule: str, days_text: str = "") -> Tuple[str, str]:
    """Return ``(schedule, days_csv)`` with weekday numbers 0 (Mon) to 6 (Sun)."""
    kind = (schedule or "").strip().lower()
    if kind not in SCHEDULES:
        raise ValueError("Schedule must be daily, weekly or custom.")
    if kind == "daily":
        return kind, ALL_DAYS
    tokens = [token for token in re.split(r"[,\s]+", (days_text or "").strip().lower()) if token]
    if not tokens:
        raise ValueError("Name at least one day, for example: mon,fri")
    numbers: Set[int] = set()
    for token in tokens:
        if token not in DAY_TOKENS:
            raise ValueError(f"Unknown day '{token}'. Use mon, tue, wed, thu, fri, sat or sun.")
        numbers.add(DAY_TOKENS[token])
    if kind == "weekly" and len(numbers) != 1:
        raise ValueError("A weekly schedule takes exactly one day. Use custom for several days.")
    return kind, ",".join(str(number) for number in sorted(numbers))


def allowed_weekdays(schedule: str, days_csv: str) -> Set[int]:
    if schedule == "daily":
        return set(range(7))
    return {int(part) for part in days_csv.split(",") if part.strip() != ""}


def describe_days(schedule: str, days_csv: str) -> str:
    if schedule == "daily":
        return "every day"
    return ", ".join(_DAY_NAMES[int(part)] for part in days_csv.split(",") if part.strip() != "")


def _as_utc(now: datetime) -> datetime:
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def slot_for(day: date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """Local slot as an aware datetime. Times skipped by DST resolve deterministically (fold=0)."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def slot_key(slot: datetime) -> str:
    zone = getattr(slot.tzinfo, "key", None) or "UTC"
    return f"{slot.strftime('%Y-%m-%dT%H:%M')}@{zone}"


def latest_due_slot(
    now: datetime,
    time_of_day: str,
    tz_name: str,
    schedule: str,
    days_csv: str,
) -> Optional[datetime]:
    """The most recent scheduled slot at or before *now*, or None."""
    tz = load_timezone(tz_name)
    hour, minute = parse_time_of_day(time_of_day)
    instant = _as_utc(now)
    allowed = allowed_weekdays(schedule, days_csv)
    today = instant.astimezone(tz).date()
    for back in range(0, 9):
        day = today - timedelta(days=back)
        if day.weekday() not in allowed:
            continue
        slot = slot_for(day, hour, minute, tz)
        if slot.astimezone(timezone.utc) <= instant:
            return slot
    return None


def next_slot(
    now: datetime,
    time_of_day: str,
    tz_name: str,
    schedule: str,
    days_csv: str,
) -> Optional[datetime]:
    """The first scheduled slot strictly after *now*, or None."""
    tz = load_timezone(tz_name)
    hour, minute = parse_time_of_day(time_of_day)
    instant = _as_utc(now)
    allowed = allowed_weekdays(schedule, days_csv)
    today = instant.astimezone(tz).date()
    for forward in range(0, 9):
        day = today + timedelta(days=forward)
        if day.weekday() not in allowed:
            continue
        slot = slot_for(day, hour, minute, tz)
        if slot.astimezone(timezone.utc) > instant:
            return slot
    return None


__all__ = [
    "ALL_DAYS",
    "DAY_TOKENS",
    "SCHEDULES",
    "allowed_weekdays",
    "describe_days",
    "format_time",
    "latest_due_slot",
    "load_timezone",
    "next_slot",
    "parse_schedule",
    "parse_time_of_day",
    "slot_for",
    "slot_key",
]
