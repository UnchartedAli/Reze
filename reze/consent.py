"""Consent for sharing data with other services. Off until the owner grants it, and revocable.

Every scope is listed here. Code that shares data calls ``require(scope)`` first, so a
missing or revoked consent stops the share before anything leaves Reze.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from reze.database import db
from reze.timeutil import utcnow

SCOPES: Dict[str, Dict[str, str]] = {
    "watchdog.channel_posts": {
        "label_en": "Send channel posts to the Watchdog bot for summaries",
        "label_fa": "ارسال پست‌های کانال به سگ نگهبان برای خلاصه",
        "detail_en": "Only the posts you choose with .watchdog summarize are sent. Nothing is stored by Watchdog.",
        "detail_fa": "فقط پست‌هایی که با .watchdog summarize انتخاب می‌کنی فرستاده می‌شوند. سگ چیزی ذخیره نمی‌کند.",
    },
}


class ConsentError(RuntimeError):
    """An unknown scope was named."""


class ConsentRequired(PermissionError):
    """The owner has not granted this consent (or has revoked it). The message says what to do."""


def _key(scope: str) -> str:
    return "consent." + scope


def _check_scope(scope: str) -> None:
    if scope not in SCOPES:
        raise ConsentError("Unknown consent scope.")


def _read(scope: str) -> Dict[str, Any]:
    raw = db.get_setting(_key(scope), None)
    if not raw:
        return {"granted": False, "at": None}
    try:
        data = json.loads(raw)
    except ValueError:
        return {"granted": False, "at": None}
    return {"granted": bool(data.get("granted")), "at": data.get("at")}


def is_granted(scope: str) -> bool:
    _check_scope(scope)
    return _read(scope)["granted"]


def grant(scope: str, now: Optional[datetime] = None) -> None:
    _check_scope(scope)
    stamp = (now or utcnow()).strftime("%Y-%m-%d %H:%M:%S")
    db.set_setting(_key(scope), json.dumps({"granted": True, "at": stamp}))


def revoke(scope: str, now: Optional[datetime] = None) -> None:
    _check_scope(scope)
    stamp = (now or utcnow()).strftime("%Y-%m-%d %H:%M:%S")
    db.set_setting(_key(scope), json.dumps({"granted": False, "at": stamp}))


def require(scope: str) -> None:
    if not is_granted(scope):
        meta = SCOPES[scope]
        raise ConsentRequired(
            f"This needs your consent: {meta['label_en']}. "
            f"Grant it in the Reze panel (Consent) or with .consent grant {scope}."
        )


def status() -> List[Dict[str, Any]]:
    rows = []
    for scope, meta in SCOPES.items():
        state = _read(scope)
        rows.append({"scope": scope, "granted": state["granted"], "at": state["at"], **meta})
    return rows


__all__ = ["SCOPES", "ConsentError", "ConsentRequired", "grant", "is_granted", "require", "revoke", "status"]
