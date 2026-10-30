"""
Mention & keyword alerts: forward group messages that matter to Saved Messages.

A message triggers an alert when it mentions you (or replies to you) or contains one
of your keywords. Chats you muted with ``.alerts ignore`` are skipped; alerts are
rate-limited and de-duplicated so a busy group cannot flood Saved Messages.
"""

import json
import time
from collections import OrderedDict, deque
from typing import Any, Callable, Deque, Dict, List, Optional

from reze.logging_config import logger

CONFIG_KEY = "alerts:config"
DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "mentions": True,      # @mention or reply to one of your messages
    "keywords": [],        # case-insensitive, substring match (works for Persian too)
    "ignore": [],          # chat ids that never alert
    "dest": "me",
}
MAX_KEYWORDS = 50
MAX_ALERTS_PER_MINUTE = 20
SNIPPET = 300


def _name(entity: Any) -> str:
    if entity is None:
        return "Unknown"
    first = getattr(entity, "first_name", None)
    if first is not None or getattr(entity, "last_name", None) is not None:
        value = " ".join(p for p in (first, getattr(entity, "last_name", None)) if p)
    else:
        value = getattr(entity, "title", "") or ""
    user = getattr(entity, "username", None)
    return (f"{value} (@{user})" if user else value) or str(getattr(entity, "id", "Unknown"))


def message_link(chat: Any, chat_id: int, msg_id: int) -> Optional[str]:
    """Deep link to the message (public username, or the private c/ form of a supergroup)."""
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{msg_id}"
    text = str(chat_id)
    if text.startswith("-100"):
        return f"https://t.me/c/{text[4:]}/{msg_id}"
    return None


class AlertService:
    def __init__(self, get_setting=None, set_setting=None, clock: Callable[[], float] = time.time):
        self._get, self._set, self._clock = get_setting, set_setting, clock
        self._cfg: Optional[Dict[str, Any]] = None
        self._seen: "OrderedDict[tuple, bool]" = OrderedDict()
        self._times: Deque[float] = deque()
        self.client_provider: Callable[[], Any] = lambda: None
        self.stats = {"sent": 0, "skipped": 0}

    # ------------------------------------------------------------------ config
    @property
    def config(self) -> Dict[str, Any]:
        if self._cfg is None:
            cfg = dict(DEFAULT_CONFIG)
            try:
                raw = self._get(CONFIG_KEY, None) if self._get else self._db_get()
                stored = json.loads(raw or "{}")
                if isinstance(stored, dict):
                    cfg.update({k: v for k, v in stored.items() if k in DEFAULT_CONFIG})
            except (ValueError, TypeError):
                logger.warning("Alerts: ignoring a corrupt stored configuration.")
            cfg["keywords"] = [str(k) for k in cfg["keywords"]]
            cfg["ignore"] = [int(c) for c in cfg["ignore"]]
            self._cfg = cfg
        return self._cfg

    def _db_get(self):
        from reze.database import db

        return db.get_setting(CONFIG_KEY)

    def update(self, **changes: Any) -> Dict[str, Any]:
        for key, value in changes.items():
            if key not in DEFAULT_CONFIG:
                raise KeyError(key)
            self.config[key] = value
        raw = json.dumps(self.config)
        if self._set:
            self._set(CONFIG_KEY, raw)
        else:
            from reze.database import db

            db.set_setting(CONFIG_KEY, raw)
        return self.config

    def add_keyword(self, word: str) -> bool:
        word = word.strip()
        if not word or len(word) > 60:
            raise ValueError("Keywords must be 1-60 characters.")
        keywords = list(self.config["keywords"])
        if word.casefold() in (k.casefold() for k in keywords):
            return False
        if len(keywords) >= MAX_KEYWORDS:
            raise ValueError(f"At most {MAX_KEYWORDS} keywords.")
        keywords.append(word)
        self.update(keywords=keywords)
        return True

    def remove_keyword(self, word: str) -> bool:
        keywords = [k for k in self.config["keywords"] if k.casefold() != word.strip().casefold()]
        if len(keywords) == len(self.config["keywords"]):
            return False
        self.update(keywords=keywords)
        return True

    def toggle_ignore(self, chat_id: int, ignored: bool) -> bool:
        chats = list(self.config["ignore"])
        if ignored and chat_id not in chats:
            chats.append(chat_id)
        elif not ignored and chat_id in chats:
            chats.remove(chat_id)
        else:
            return False
        self.update(ignore=chats)
        return True

    def destination(self) -> Any:
        dest = self.config["dest"]
        return int(dest) if isinstance(dest, str) and dest.lstrip("-").isdigit() else (dest or "me")

    # ------------------------------------------------------------------ matching
    def matches(self, text: str, mentioned: bool) -> List[str]:
        """Reasons this message should alert (``['mention']``, ``['keyword: deploy']``...)."""
        reasons = []
        cfg = self.config
        if mentioned and cfg["mentions"]:
            reasons.append("mention")
        folded = (text or "").casefold()
        for word in cfg["keywords"]:
            if word.casefold() in folded:
                reasons.append(f"keyword: {word}")
        return reasons

    def _allow_rate(self) -> bool:
        now = self._clock()
        while self._times and now - self._times[0] > 60:
            self._times.popleft()
        if len(self._times) >= MAX_ALERTS_PER_MINUTE:
            return False
        self._times.append(now)
        return True

    # -------------------------------------------------------------------- events
    async def on_new_message(self, event: Any) -> None:
        cfg = self.config
        if not cfg["enabled"]:
            return
        message = event.message
        if getattr(message, "out", False) or not getattr(event, "is_group", False):
            return
        chat_id = event.chat_id
        if chat_id in cfg["ignore"]:
            return
        text = getattr(message, "raw_text", None) or getattr(message, "message", "") or ""
        reasons = self.matches(text, bool(getattr(message, "mentioned", False)))
        if not reasons:
            return
        key = (chat_id, message.id)
        if key in self._seen:
            return
        self._seen[key] = True
        while len(self._seen) > 500:
            self._seen.popitem(last=False)
        if not self._allow_rate():
            self.stats["skipped"] += 1
            return

        client = getattr(event, "client", None) or self.client_provider()
        if not client:
            return
        sender = chat = None
        try:
            sender = await event.get_sender()
        except Exception:  # noqa: BLE001
            pass
        try:
            chat = await event.get_chat()
        except Exception:  # noqa: BLE001
            pass
        from reze.ui import ascii

        lines = [f"Why : {', '.join(reasons)}", f"Chat: {_name(chat)}", f"From: {_name(sender)}", "", text[:SNIPPET] or "(no text)"]
        body = ascii.frame("Alert", lines)
        link = message_link(chat, chat_id, message.id)
        try:
            await client.send_message(self.destination(), f"{body}\n{link}" if link else body, parse_mode=None)
            self.stats["sent"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alerts: could not deliver: %s", exc)


alert_service = AlertService()
