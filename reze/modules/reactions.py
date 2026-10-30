"""
Random reactions (optional, OFF by default).

This is not an auto-reply and not a campaign tool. It adds an emoji reaction to
a small, bounded share of messages in chats the owner explicitly lists. It never
sends messages, never reacts to its own messages and never contacts anyone.
"""

from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, List

from reze.core.registry import Service
from reze.database import db
from reze.features import features
from reze.logging_config import logger

DEFAULT_EMOJI = ["👍", "🔥", "✨"]
MAX_PROBABILITY = 0.25
MIN_INTERVAL_SECONDS = 120
HOURLY_CAP = 20


def _load() -> Dict[str, Any]:
    try:
        raw = db.get_setting("reactions.config", "") or ""
        data = json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001 - a broken setting means "no chats"
        data = {}
    return {
        "chats": {str(key): float(value) for key, value in (data.get("chats") or {}).items()},
        "emoji": [str(item) for item in (data.get("emoji") or DEFAULT_EMOJI)][:8],
    }


def _save(data: Dict[str, Any]) -> None:
    db.set_setting("reactions.config", json.dumps(data, ensure_ascii=False))


class RandomReactionService(Service):
    name = "random_reactions"
    feature = "random_reactions"
    description = "Reacts to a small share of messages in explicitly listed chats."

    def __init__(self) -> None:
        super().__init__()
        self.client_provider = None
        self._last: Dict[int, float] = {}
        self._hour: Dict[int, List[float]] = {}

    async def start(self) -> None:
        await super().start()

    def status_report(self) -> Dict[str, Any]:
        data = _load()
        return {
            "enabled": features.is_enabled("random_reactions"),
            "chats": data["chats"],
            "emoji": data["emoji"],
            "limits": f"max {int(MAX_PROBABILITY * 100)}% · {MIN_INTERVAL_SECONDS}s cooldown · {HOURLY_CAP}/hour",
        }

    def add_chat(self, chat_id: int, probability: float = 0.1) -> float:
        value = max(0.01, min(float(probability), MAX_PROBABILITY))
        data = _load()
        data["chats"][str(int(chat_id))] = value
        _save(data)
        return value

    def remove_chat(self, chat_id: int) -> bool:
        data = _load()
        removed = data["chats"].pop(str(int(chat_id)), None) is not None
        _save(data)
        return removed

    def set_emoji(self, emoji: List[str]) -> List[str]:
        cleaned = [item.strip() for item in emoji if item.strip()][:8] or list(DEFAULT_EMOJI)
        data = _load()
        data["emoji"] = cleaned
        _save(data)
        return cleaned

    def clear(self) -> int:
        data = _load()
        count = len(data["chats"])
        data["chats"] = {}
        _save(data)
        return count

    # --------------------------------------------------------------------- hook
    async def on_new_message(self, event: Any) -> bool:
        """React at most rarely. Returns True when a reaction was sent."""
        if not features.is_enabled("random_reactions"):
            return False
        message = getattr(event, "message", None)
        if message is None or getattr(message, "out", False):
            return False
        chat_id = int(getattr(event, "chat_id", 0) or 0)
        if not chat_id:
            return False
        data = _load()
        probability = data["chats"].get(str(chat_id))
        if probability is None:
            return False
        now = time.time()
        if now - self._last.get(chat_id, 0) < MIN_INTERVAL_SECONDS:
            return False
        recent = [stamp for stamp in self._hour.get(chat_id, []) if now - stamp < 3600]
        self._hour[chat_id] = recent
        if len(recent) >= HOURLY_CAP:
            return False
        if random.random() > probability:
            return False
        client = self.client_provider() if self.client_provider else None
        if client is None:
            return False
        emoji = random.choice(data["emoji"] or DEFAULT_EMOJI)
        try:
            from telethon.tl.functions.messages import SendReactionRequest
            from telethon.tl.types import ReactionEmoji

            await client(
                SendReactionRequest(
                    peer=chat_id,
                    msg_id=int(getattr(message, "id", 0) or 0),
                    reaction=[ReactionEmoji(emoticon=emoji)],
                )
            )
        except Exception as exc:  # noqa: BLE001 - reactions are best-effort
            logger.debug("Random reaction failed in %s: %s", chat_id, exc)
            return False
        self._last[chat_id] = now
        self._hour.setdefault(chat_id, []).append(now)
        logger.info("Random reaction sent in chat %s.", chat_id)
        return True


random_reaction_service = RandomReactionService()

__all__ = ["DEFAULT_EMOJI", "RandomReactionService", "random_reaction_service"]
