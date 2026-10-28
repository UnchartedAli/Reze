"""
Preference store for Reze.

User preferences (theme, prefix, AI defaults, media defaults) live in the
SQLite ``global_settings`` table so they survive restarts and can be edited from
both Telegram and the web panel. Environment configuration is the fallback, so
an existing deployment keeps working without touching the database.
"""

from typing import Any, Dict

from reze.config import settings
from reze.database import db

# Preferences that may be written through ``set_pref`` and the web panel.
PREFERENCE_KEYS = (
    "theme",
    "compact",
    "prefix",
    "ai_provider",
    "ai_model",
    "ai_vision",
    "media_quality",
    "media_max_input_mb",
    "log_level",
    "online_always",
)


def _defaults() -> Dict[str, str]:
    return {
        "theme": settings.theme,
        "compact": "1" if settings.compact_mode else "0",
        "prefix": settings.default_prefix,
        "ai_provider": settings.ai_provider,
        "ai_model": settings.ai_model,
        "ai_vision": settings.ai_vision,
        "media_quality": str(settings.media_quality),
        "media_max_input_mb": str(settings.media_max_input_mb),
        "log_level": settings.log_level,
        "online_always": "0",
    }


def get_pref(key: str, default: Any = None) -> str:
    """Return the stored preference, the environment default, or *default*."""
    if key not in PREFERENCE_KEYS:
        raise KeyError(f"Unknown preference: {key}")
    stored = db.get_setting(f"pref:{key}")
    if stored is not None:
        return stored
    fallback = _defaults().get(key, "")
    return fallback if fallback != "" else ("" if default is None else str(default))


def get_bool_pref(key: str, default: bool = False) -> bool:
    value = get_pref(key, "1" if default else "0")
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_int_pref(key: str, default: int = 0) -> int:
    try:
        return int(get_pref(key, str(default)))
    except (TypeError, ValueError):
        return default


def set_pref(key: str, value: Any) -> None:
    """Validate and persist a preference. Raises ``ValueError`` when invalid."""
    if key not in PREFERENCE_KEYS:
        raise KeyError(f"Unknown preference: {key}")

    text = str(value).strip()

    if key == "theme":
        from reze.ui.themes import THEMES

        if text.upper() not in THEMES:
            raise ValueError(f"Unknown theme '{text}'. Available: {', '.join(sorted(THEMES))}")
        text = text.upper()
    elif key in {"compact", "online_always"}:
        text = "1" if text.lower() in {"1", "true", "yes", "on"} else "0"
    elif key == "prefix":
        if not 1 <= len(text) <= 2 or text.isspace():
            raise ValueError("The command prefix must be 1-2 non-space characters.")
    elif key == "media_quality":
        quality = int(text)
        if not 1 <= quality <= 100:
            raise ValueError("Media quality must be between 1 and 100.")
        text = str(quality)
    elif key == "media_max_input_mb":
        megabytes = int(text)
        if not 1 <= megabytes <= 200:
            raise ValueError("The media input limit must be between 1 and 200 MB.")
        text = str(megabytes)
    elif key == "ai_vision":
        if text.lower() not in {"auto", "on", "off"}:
            raise ValueError("AI vision must be one of: auto, on, off.")
        text = text.lower()
    elif key == "log_level":
        if text.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid log level.")
        text = text.upper()

    db.set_setting(f"pref:{key}", text)


def all_prefs() -> Dict[str, str]:
    """Effective preference values (stored values layered over defaults)."""
    return {key: get_pref(key) for key in PREFERENCE_KEYS}


def reset_pref(key: str) -> bool:
    return db.delete_setting(f"pref:{key}")
