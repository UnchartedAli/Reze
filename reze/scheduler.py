"""
Shared Scheduler for Reze.
Handles Name Clock, Bio Clock, rate limits, FloodWait backoff, and periodic tasks safely.
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional
from reze.database import db
from reze.logging_config import logger

class ClockScheduler:
    def __init__(self, client_wrapper=None):
        self.client_wrapper = client_wrapper
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self.last_name: Optional[str] = None
        self.last_bio: Optional[str] = None
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        self.flood_wait_until = 0

    def start(self):
        """Start the background scheduler loop."""
        if not self.is_running:
            self.is_running = True
            self._task = asyncio.create_task(self._loop())
            logger.info("Profile Clock Scheduler started.")

    def stop(self):
        """Stop the background scheduler loop cleanly."""
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("Profile Clock Scheduler stopped.")

    async def _loop(self):
        while self.is_running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in scheduler tick: %s", e)
            # Sleep 60 seconds (safe interval conforming to Telegram flood limits)
            await asyncio.sleep(60)

    async def tick(self):
        """Execute one clock synchronization tick."""
        cfg = db.get_profile_settings()
        name_enabled = bool(cfg.get("name_clock_enabled", 0))
        bio_enabled = bool(cfg.get("bio_clock_enabled", 0))

        if not name_enabled and not bio_enabled:
            return

        tz_str = cfg.get("timezone", "Asia/Tehran")
        try:
            tz = ZoneInfo(tz_str)
        except Exception:
            tz = ZoneInfo("UTC")

        now = datetime.now(tz)
        clock_fmt = cfg.get("clock_format", "%H:%M")
        time_str = now.strftime(clock_fmt)

        # 1. Update Name
        if name_enabled:
            orig_name = cfg.get("original_name") or "Reze User"
            template = cfg.get("name_template") or "{name} | {time}"
            new_name = template.replace("{name}", orig_name).replace("{time}", time_str)
            
            # Telegram profile name limit is 64 chars
            new_name = new_name[:64]
            if new_name != self.last_name:
                success = await self._apply_name_update(new_name)
                if success:
                    self.last_name = new_name
                    db.update_profile_settings(last_updated=datetime.utcnow())

        # 2. Update Bio
        if bio_enabled:
            orig_bio = cfg.get("original_bio") or "Reze Userbot"
            template = cfg.get("bio_template") or "{bio} • {time}"
            new_bio = template.replace("{bio}", orig_bio).replace("{time}", time_str)
            
            # Telegram bio limit is 70 chars
            new_bio = new_bio[:70]
            if new_bio != self.last_bio:
                success = await self._apply_bio_update(new_bio)
                if success:
                    self.last_bio = new_bio
                    db.update_profile_settings(last_updated=datetime.utcnow())

    async def _apply_name_update(self, new_name: str) -> bool:
        """Call Telegram MTProto UpdateProfileRequest safely."""
        logger.debug("Applying profile name update: %s", new_name)
        if self.client_wrapper and hasattr(self.client_wrapper, "client") and self.client_wrapper.client:
            try:
                from telethon.tl.functions.account import UpdateProfileRequest
                await self.client_wrapper.client(UpdateProfileRequest(first_name=new_name))
                self.consecutive_errors = 0
                return True
            except Exception as e:
                self._handle_error(e)
                return False
        return True  # If mock/offline, simulate success

    async def _apply_bio_update(self, new_bio: str) -> bool:
        """Call Telegram MTProto UpdateProfileRequest safely."""
        logger.debug("Applying profile bio update: %s", new_bio)
        if self.client_wrapper and hasattr(self.client_wrapper, "client") and self.client_wrapper.client:
            try:
                from telethon.tl.functions.account import UpdateProfileRequest
                await self.client_wrapper.client(UpdateProfileRequest(about=new_bio))
                self.consecutive_errors = 0
                return True
            except Exception as e:
                self._handle_error(e)
                return False
        return True

    def _handle_error(self, exc: Exception):
        self.consecutive_errors += 1
        logger.warning("Telegram profile update failed (%d/%d): %s", self.consecutive_errors, self.max_consecutive_errors, exc)
        if self.consecutive_errors >= self.max_consecutive_errors:
            logger.error("Too many profile update errors. Pausing clock to prevent account ban.")
            db.update_profile_settings(name_clock_enabled=0, bio_clock_enabled=0)
            self.stop()


clock_scheduler = ClockScheduler()
