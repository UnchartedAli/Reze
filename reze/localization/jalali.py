"""Small, dependency-free Gregorian -> Jalali (Solar Hijri) conversion.

The algorithm is the classic arithmetic conversion used by the ``jdate`` /
``jalali`` libraries; it is exact for the years 1800-2256, which covers every
date REZE stores. Only display is converted: storage stays ISO-8601 UTC.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Tuple

MONTHS_FA = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)

_MONTH_DAYS = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)


def to_jalali(value) -> Tuple[int, int, int]:
    """Convert a ``date``/``datetime``/ISO string to ``(year, month, day)``."""
    if isinstance(value, datetime):
        gy, gm, gd = value.year, value.month, value.day
    elif isinstance(value, date):
        gy, gm, gd = value.year, value.month, value.day
    else:
        text = str(value or "").strip()
        if not text:
            raise ValueError("A date is required.")
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00").split("+")[0])
        gy, gm, gd = parsed.year, parsed.month, parsed.day

    if not (1800 <= gy <= 2256):
        raise ValueError("Jalali conversion supports years 1800-2256.")

    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621

    gy2 = gy + 1 if gm > 2 else gy
    days = (
        365 * gy
        + (gy2 + 3) // 4
        - (gy2 + 99) // 100
        + (gy2 + 399) // 400
        - 80
        + gd
        + _MONTH_DAYS[gm - 1]
    )

    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return int(jy), int(jm), int(jd)


def format_date(value, language: str = "fa", with_time: bool = False) -> str:
    """Format a date for display. Persian uses the Jalali calendar."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return value
    if value is None:
        return "—"
    if (language or "en").lower().startswith("fa"):
        year, month, day = to_jalali(value)
        stamp = f"{day} {MONTHS_FA[month - 1]} {year}"
        if with_time and isinstance(value, datetime):
            stamp += f" · {value.hour:02d}:{value.minute:02d}"
        return stamp
    if with_time and isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return value.strftime("%Y-%m-%d")


__all__ = ["MONTHS_FA", "format_date", "to_jalali"]
