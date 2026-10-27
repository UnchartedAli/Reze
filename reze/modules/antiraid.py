"""
AntiRaid Module for Reze.
Monitors mass-join events within short timeframes.
"""

import time
from collections import defaultdict
from typing import Dict, List
from reze.database import db

class AntiRaidTracker:
    def __init__(self):
        # chat_id -> list of join timestamps
        self.join_history: Dict[int, List[float]] = defaultdict(list)

    def record_join(self, chat_id: int) -> bool:
        """Return True if join raid detected."""
        cfg = db.get_group_settings(chat_id)
        if not cfg.get("antiraid_enabled"):
            return False

        limit = cfg.get("antiraid_limit", 10)
        window = cfg.get("antiraid_seconds", 60)
        now = time.time()

        joins = [t for t in self.join_history[chat_id] if now - t <= window]
        joins.append(now)
        self.join_history[chat_id] = joins

        return len(joins) >= limit

antiraid_tracker = AntiRaidTracker()
