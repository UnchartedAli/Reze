"""
Always-online presence.

Telegram derives "online" from the account's active sessions: a session looks
online while it recently sent ``account.updateStatus(offline=False)``. When the
``online_always`` preference is enabled, Reze repeats that request on a fixed
interval so the account keeps appearing online.

Honest limits (also stated in the command output):

* it works only while the Reze process is running and the client is authorized;
* account privacy settings still decide who may *see* "online";
* Telegram's own idle rules can mark a session offline at any time, and Reze
  never tries to bypass that — it only refreshes the status;
* one request per interval by default, with FloodWait cooldowns respected.
"""

import asyncio
import time
from typing import Any, Callable, Dict, Optional

from reze.config import settings
from reze.logging_config import logger
from reze.preferences import get_bool_pref, set_pref

PRESENCE_TAG = "presence"


class PresenceService:
    """Keeps the account online by refreshing its status periodically."""

    def __init__(self, client_provider: Optional[Callable[[], Any]] = None, interval: Optional[int] = None):
        self.client_provider = client_provider
        self.interval = max(30, int(interval or settings.presence_interval_seconds))
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.last_applied: float = 0.0
        self.applied_count: int = 0
        self.last_error: str = ""
        self._cooldown_until: float = 0.0

    # --------------------------------------------------------------------- state
    @staticmethod
    def enabled() -> bool:
        return get_bool_pref("online_always", False)

    @staticmethod
    def set_enabled(value: bool) -> None:
        set_pref("online_always", "1" if value else "0")

    def status(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled(),
            "running": self._running,
            "interval": self.interval,
            "applied_count": self.applied_count,
            "last_applied": self.last_applied,
            "last_error": self.last_error,
            "cooldown_remaining": max(0, int(self._cooldown_until - time.time())),
        }

    # --------------------------------------------------------------------- loop
    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="reze-presence")
        logger.info("Presence service started (interval %ds).", self.interval)

    def stop(self) -> None:
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
        logger.info("Presence service stopped.")

    async def _loop(self) -> None:
        while self._running:
            try:
                if self.enabled():
                    await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Presence loop error: %s", exc)
            await asyncio.sleep(self.interval)

    # ------------------------------------------------------------------- request
    async def tick(self, force: bool = False, client: Any = None) -> bool:
        """Send one online-status refresh. Returns True when Telegram accepted it."""
        if not force and not self.enabled():
            return False
        if time.time() < self._cooldown_until:
            return False
        if client is None:
            client = self.client_provider() if self.client_provider else None
        if client is None:
            self.last_error = "Telegram is not connected."
            return False

        try:
            from telethon.tl.functions.account import UpdateStatusRequest

            await client(UpdateStatusRequest(offline=False))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - FloodWait, network, auth errors
            name = type(exc).__name__
            seconds = int(getattr(exc, "seconds", 0) or 0)
            if "FloodWait" in name and seconds:
                self._cooldown_until = time.time() + seconds
                self.last_error = f"FloodWait: retry in {seconds}s."
            else:
                self.last_error = f"{name}: {str(exc)[:160]}"
            logger.warning("Could not refresh the online status: %s", self.last_error)
            return False

        self.last_applied = time.time()
        self.applied_count += 1
        self.last_error = ""
        logger.debug("Online status refreshed (count: %d).", self.applied_count)
        return True

    async def apply_now(self, client: Any = None) -> bool:
        """Apply the preference immediately (used by the command and at login)."""
        return await self.tick(force=True, client=client)


presence_service = PresenceService()
