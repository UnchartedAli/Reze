"""
Bound, single-use confirmations for risky operations.

A confirmation token is bound to one action, one chat and one user, expires
after a short window, and can be consumed exactly once. Tokens are never reused
for an unrelated action, which is what makes interactive confirmation safe for
operations that change state (deleting data, running an external provider,
enabling an automation that sends messages).
"""

import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from reze.exceptions import ConfirmationError

DEFAULT_TTL_SECONDS = 120


@dataclass
class Confirmation:
    token: str
    action: str
    chat_id: int
    user_id: int
    payload: str = ""
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    used: bool = False

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    def to_dict(self) -> Dict[str, str]:
        return {"token": self.token, "action": self.action, "payload": self.payload}


class ConfirmationStore:
    def __init__(self, ttl: int = DEFAULT_TTL_SECONDS, max_pending: int = 200):
        self.ttl = max(15, int(ttl))
        self.max_pending = max(10, int(max_pending))
        self._pending: Dict[str, Confirmation] = {}

    def _purge(self) -> None:
        now = time.time()
        for token in [t for t, c in self._pending.items() if c.expired or c.used]:
            self._pending.pop(token, None)
        if len(self._pending) > self.max_pending:
            oldest = sorted(self._pending.values(), key=lambda c: c.created_at)
            for confirmation in oldest[: len(self._pending) - self.max_pending]:
                self._pending.pop(confirmation.token, None)

    def issue(
        self,
        action: str,
        chat_id: int,
        user_id: int,
        payload: str = "",
        ttl: Optional[int] = None,
    ) -> str:
        """Create a confirmation token valid for *ttl* seconds."""
        self._purge()
        token = secrets.token_hex(4).upper()  # 8 hex chars, easy to type
        confirmation = Confirmation(
            token=token,
            action=str(action),
            chat_id=int(chat_id or 0),
            user_id=int(user_id or 0),
            payload=str(payload)[:500],
            expires_at=time.time() + (self.ttl if ttl is None else max(15, int(ttl))),
        )
        self._pending[token] = confirmation
        return token

    def consume(self, token: str, action: str, chat_id: int, user_id: int) -> Confirmation:
        """
        Validate and burn a token.

        Raises :class:`ConfirmationError` for unknown, expired, mismatched or
        already-used tokens; the token is never partially consumed.
        """
        self._purge()
        normalized = (token or "").strip().upper()
        confirmation = self._pending.get(normalized)
        if confirmation is None:
            raise ConfirmationError("This confirmation code is unknown or was already used.")
        if confirmation.expired:
            self._pending.pop(normalized, None)
            raise ConfirmationError("This confirmation code has expired. Start the action again.")
        if confirmation.action != str(action):
            raise ConfirmationError("This confirmation code belongs to a different action.")
        if confirmation.chat_id != int(chat_id or 0) or confirmation.user_id != int(user_id or 0):
            raise ConfirmationError("This confirmation code was issued to a different user or chat.")

        confirmation.used = True
        self._pending.pop(normalized, None)
        return confirmation

    def peek(self, token: str) -> Optional[Confirmation]:
        confirmation = self._pending.get((token or "").strip().upper())
        if confirmation and not confirmation.expired and not confirmation.used:
            return confirmation
        return None

    def pending(self) -> List[Confirmation]:
        self._purge()
        return list(self._pending.values())

    def clear(self) -> None:
        self._pending.clear()


confirmations = ConfirmationStore()
