"""
Greetings & Clean Service Messages Module.
Handles new members welcome, goodbye messages, and service cleanup.
"""

from typing import Optional
from reze.database import db

def format_welcome_message(chat_id: int, user_first_name: str, user_id: int, chat_title: str) -> Optional[str]:
    cfg = db.get_group_settings(chat_id)
    if not cfg.get("welcome_enabled"):
        return None
    tmpl = cfg.get("welcome_text") or "Welcome {mention} to {title}!"
    mention = f"[{user_first_name}](tg://user?id={user_id})"
    return tmpl.replace("{mention}", mention).replace("{name}", user_first_name).replace("{title}", chat_title)

def format_goodbye_message(chat_id: int, user_first_name: str) -> Optional[str]:
    cfg = db.get_group_settings(chat_id)
    if not cfg.get("goodbye_enabled"):
        return None
    tmpl = cfg.get("goodbye_text") or "Goodbye {name}!"
    return tmpl.replace("{name}", user_first_name)
