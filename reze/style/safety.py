"""Auto-reply gate. Pure functions: every decision is testable without Telegram.

An automatic reply is sent only if ALL checks pass. The first failing check is
returned as the reason, so the owner can see why nothing was sent.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional, Tuple

#: Messages that need a decision or personal data are never answered automatically.
_SENSITIVE = re.compile(
    r"(?i)\b(pay|payment|transfer|bank|card|iban|password|passcode|otp|verification|login|"
    r"address|location|where are you|urgent|emergency|hospital|doctor|medicine|lawyer|court|"
    r"police|money|loan|price|invoice|contract|meet|meeting|appointment|deadline|sign)\b"
    r"|پول|انتقال|حساب|کارت|رمز|کد|آدرس|کجایی|فوری|اورژانس|بیمارستان|دکتر|دارو|وکیل|دادگاه|"
    r"پلیس|قرض|قیمت|فاکتور|قرارداد|قرار|جلسه|ملاقات|مهلت|تومان|واریز"
)
_LONG_NUMBER = re.compile(r"\d{9,}")

REASONS = {
    "not_allowed": "This chat is not on the auto-reply allow list.",
    "not_private": "Auto-replies are only sent in private chats.",
    "bot": "Bots never receive automatic replies.",
    "empty": "The message has no text.",
    "sensitive": "The message looks like it needs your decision or personal data.",
    "quiet_hours": "Quiet hours are active.",
    "owner_active": "You were recently active in this chat.",
    "cooldown": "This chat received an automatic reply recently.",
    "hourly_cap": "The hourly limit for automatic replies is reached.",
}


def is_sensitive(text: str) -> bool:
    return bool(_SENSITIVE.search(text or "") or _LONG_NUMBER.search(text or ""))


def in_quiet_hours(local_hm: str, start: str, end: str) -> bool:
    """True when local time falls in [start, end). Windows may cross midnight."""
    if not start or not end or start == end:
        return False
    if start < end:
        return start <= local_hm < end
    return local_hm >= start or local_hm < end


def decide(
    *,
    text: str,
    is_private: bool,
    is_bot: bool,
    chat_allowed: bool,
    local_hm: str,
    quiet_start: str,
    quiet_end: str,
    owner_last_active: Optional[datetime],
    now: datetime,
    owner_active_minutes: int,
    last_reply_at: Optional[datetime],
    cooldown_hours: int,
    replies_last_hour: int,
    hourly_cap: int,
) -> Tuple[bool, str]:
    """Return ``(send, reason)``. ``reason`` is ``"ok"`` when the reply may be sent."""
    if not chat_allowed:
        return False, "not_allowed"
    if not is_private:
        return False, "not_private"
    if is_bot:
        return False, "bot"
    if not (text or "").strip():
        return False, "empty"
    if is_sensitive(text):
        return False, "sensitive"
    if in_quiet_hours(local_hm, quiet_start, quiet_end):
        return False, "quiet_hours"
    if owner_last_active and now - owner_last_active < timedelta(minutes=owner_active_minutes):
        return False, "owner_active"
    if last_reply_at and now - last_reply_at < timedelta(hours=cooldown_hours):
        return False, "cooldown"
    if replies_last_hour >= hourly_cap:
        return False, "hourly_cap"
    return True, "ok"


__all__ = ["REASONS", "decide", "in_quiet_hours", "is_sensitive"]
