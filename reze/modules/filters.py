"""
Filters & Blacklists message interception logic.
"""

import re
from typing import Optional, Tuple
from reze.database import db

def check_message_filters(chat_id: int, text: str) -> Optional[str]:
    """Check if message matches any configured group auto-response filter."""
    if not text:
        return None
    flist = db.get_filters(chat_id)
    text_lower = text.lower()
    for f in flist:
        if f["keyword"] in text_lower:
            return f["reply_text"]
    return None

def check_blacklists(chat_id: int, text: str) -> Optional[Tuple[str, str]]:
    """Check if message triggers a blacklist rule. Returns (trigger_word, action)."""
    if not text:
        return None
    blist = db.get_blacklists(chat_id)
    text_lower = text.lower()
    for b in blist:
        if b["trigger"] in text_lower:
            return b["trigger"], b["action"]
    return None

def contains_link(text: str) -> bool:
    """Detect if text contains URLs or telegram t.me links."""
    link_pattern = re.compile(r'(https?://[^\s]+|t\.me/[^\s]+|telegram\.me/[^\s]+)', re.IGNORECASE)
    return bool(link_pattern.search(text))
