"""Localization for REZE 3.0 (English and Persian).

Public helpers live in :mod:`reze.localization.manager`; this package only
re-exports them so commands can ``from reze.localization import t``.
"""

from reze.localization.jalali import format_date, to_jalali
from reze.localization.manager import (
    LANGUAGES,
    LanguageError,
    direction,
    get_language,
    is_rtl,
    normalize,
    set_language,
    t,
)

__all__ = [
    "LANGUAGES",
    "LanguageError",
    "direction",
    "format_date",
    "get_language",
    "is_rtl",
    "normalize",
    "set_language",
    "t",
    "to_jalali",
]
