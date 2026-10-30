"""Language manager for REZE 3.0.

* English is the fallback catalog; a missing Persian key never breaks a
  response, it simply renders English.
* The selected language lives in the ``global_settings`` preference store, so
  switching languages survives restarts and migrations.
* Persian input is normalized before storage/search, and dates can be rendered
  with the Jalali calendar.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from reze.localization.jalali import format_date
from reze.localization.normalize import has_persian, normalize

LOCALE_DIR = Path(__file__).with_name("locales")
DEFAULT_LANGUAGE = "en"
LANGUAGES: Dict[str, str] = {"en": "English", "fa": "فارسی"}

#: Telegram direction override for right-to-left messages.
RTL_MARK = "\u200f"


class LanguageError(ValueError):
    """Raised for an unsupported language code."""


@lru_cache(maxsize=4)
def _catalog(language: str) -> Dict[str, str]:
    path = LOCALE_DIR / f"{language}.json"
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return {str(key): str(value) for key, value in data.items()}
    except (OSError, ValueError):
        return {}


def available_languages() -> Dict[str, str]:
    return dict(LANGUAGES)


def get_language() -> str:
    """Currently selected language code (never raises)."""
    try:
        from reze.config import settings
        from reze.preferences import get_pref

        value = (get_pref("language", settings.language) or DEFAULT_LANGUAGE).lower()
    except Exception:  # pragma: no cover - early boot or database unavailable
        return DEFAULT_LANGUAGE
    return value if value in LANGUAGES else DEFAULT_LANGUAGE


def set_language(language: str) -> str:
    """Persist a language choice. Returns the stored code."""
    code = (language or "").strip().lower()
    aliases = {"persian": "fa", "farsi": "fa", "فارسی": "fa", "english": "en", "en-us": "en", "en-gb": "en"}
    code = aliases.get(code, code)
    if code not in LANGUAGES:
        raise LanguageError(f"Unsupported language '{language}'. Use: en, fa")
    from reze.preferences import set_pref

    set_pref("language", code)
    return code


def t(key: str, default: str = "", **values: Any) -> str:
    """Translate *key* into the current language with English fallback."""
    language = get_language()
    text = _catalog(language).get(key)
    if text is None:
        text = _catalog(DEFAULT_LANGUAGE).get(key)
    if text is None:
        return default or key
    if values:
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def direction(language: str = "") -> str:
    return "rtl" if (language or get_language()).lower().startswith("fa") else "ltr"


def is_rtl(language: str = "") -> bool:
    return direction(language) == "rtl"


def rtl_wrap(text: str) -> str:
    """Prefix a right-to-left message with the RTL mark when appropriate."""
    if is_rtl() and text and not text.startswith(RTL_MARK):
        return RTL_MARK + text
    return text


def detect_language(text: str) -> str:
    """Best-effort language of a user message."""
    return "fa" if has_persian(normalize(text)) else "en"


def format_local_date(value, with_time: bool = False) -> str:
    return format_date(value, get_language(), with_time=with_time)


__all__ = [
    "LANGUAGES",
    "LanguageError",
    "available_languages",
    "detect_language",
    "direction",
    "format_date",
    "format_local_date",
    "get_language",
    "is_rtl",
    "normalize",
    "rtl_wrap",
    "set_language",
    "t",
]
