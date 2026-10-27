"""
AntiFlood Module for Reze.
Monitors rapid messaging and executes automated mitigation (mute/warn/delete).
"""

import time
from collections import defaultdict
from typing import Dict, List, Tuple
from reze.database import db
from reze.logging_config import logger

class AntiFloodTracker:
    def __init__(self):
        # chat_id -> user_id -> list of message timestamps
        self.message_history: Dict[int, Dict[int, List[float]]] = defaultdict(lambda: defaultdict(list))

    def record_and_check(self, chat_id: int, user_id: int) -> Tuple[bool, str]:
        """
        Record a message and return True if flood threshold exceeded.
        """
        cfg = db.get_group_settings(chat_id)
        if not cfg.get("antiflood_enabled"):
            return False, ""

        limit = cfg.get("antiflood_limit", 5)
        window = cfg.get("antiflood_seconds", 5)
        action = cfg.get("antiflood_action", "mute")

        now = time.time()
        user_timestamps = self.message_history[chat_id][user_id]
        # Keep only timestamps within window
        user_timestamps = [t for t in user_timestamps if now - t <= window]
        user_timestamps.append(now)
        self.message_history[chat_id][user_id] = user_timestamps

        if len(user_timestamps) >= limit:
            # Clear history after trigger to avoid cascade triggers
            self.message_history[chat_id][user_id] = []
            return True, action

        return False, ""

antiflood_tracker = AntiFloodTracker()
