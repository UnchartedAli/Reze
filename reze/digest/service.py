"""Channel Digest service: schedule, collect, summarize, deliver, and recover.

Reliability model
* One run per schedule slot. ``digest_runs.slot_key`` is UNIQUE, so a re-tick
  never creates a second digest for the same slot.
* The digest body is stored, and channel checkpoints advance, in one transaction
  before anything is sent. A crash or flood wait therefore cannot lose posts
  (they are behind the checkpoint only once their body is stored) and cannot
  re-collect and resend them.
* Runs left in ``collecting`` at shutdown stored nothing. They are deleted on
  the next start, so their slot reruns.
* Delivery is per chunk, with progress saved after each chunk. Delivery is
  at-least-once: a crash between a successful send and saving progress can repeat
  that one chunk. This is the only duplication case, and it is documented.
* A failed channel is skipped and counted. Its checkpoint does not move, so its
  posts are collected next time. The run fails only when every channel fails.
* Missed slots after downtime produce one catch-up digest, because collection
  is driven by checkpoints, not by slot count.

Privacy: post text is never written to logs. Errors are stored as exception
class names, or as short messages written by this module.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from reze.config import settings
from reze.digest import collect, store
from reze.digest import text as dtext
from reze.digest.models import ChannelBatch, ChannelSection
from reze.digest.schedule import latest_due_slot, next_slot, slot_key
from reze.digest.summarize import AIVerificationError, build_prompt, parse_ai_json, verify_ai_output
from reze.logging_config import logger
from reze.timeutil import utcnow as _utcnow

SAVED_MESSAGES = "me"
IMPORTANT_PRIORITY = 3
MAX_FLOOD_WAIT_SECONDS = 300


async def _default_ai_complete(prompt: str, system: str, max_tokens: int) -> Any:
    from reze.ai.gateway import ai_gateway

    return await ai_gateway.complete(prompt, system=system, max_tokens=max_tokens)


def _naive_utc(value: Optional[datetime]) -> datetime:
    if value is None:
        return _utcnow()
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _describe(exc: BaseException) -> str:
    if isinstance(exc, RuntimeError):
        return str(exc)[:200]
    return type(exc).__name__


class DigestService:
    channel_delay = 0.5
    retry_base_seconds = 60
    retry_cap_seconds = 3600
    max_flood_wait = MAX_FLOOD_WAIT_SECONDS
    ai_max_tokens = 900

    def __init__(
        self,
        client_provider: Optional[Callable[[], Any]] = None,
        ai_complete: Optional[Callable[..., Awaitable[Any]]] = None,
        interval: int = 60,
        sleep: Optional[Callable[[float], Awaitable[Any]]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ) -> None:
        self.client_provider = client_provider
        self.ai_complete = ai_complete or _default_ai_complete
        self.interval = max(5, int(interval))
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or _utcnow
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._recovered = False
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="reze-digest")
        logger.info("Channel Digest service started (interval %ds).", self.interval)

    def stop(self) -> None:
        self._running = False
        if self._task is not None and not self._task.done():
            self._task.cancel()
            logger.info("Channel Digest service stopped.")

    async def _loop(self) -> None:
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # pragma: no cover - defensive; never kill the loop
                logger.error("Channel Digest loop error: %s", type(exc).__name__)
            await asyncio.sleep(self.interval)

    def _client(self) -> Any:
        return self.client_provider() if self.client_provider else None

    def _local_date(self, instant: datetime, tz_name: str) -> str:
        return instant.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")

    # ---------------------------------------------------------- public API
    async def tick(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Run one scheduling pass. Safe to call at any time and as often as needed."""
        instant = _naive_utc(now or self._clock())
        cfg = store.get_config()
        if not cfg["enabled"]:
            return {"status": "disabled"}
        client = self._client()
        if client is None:
            return {"status": "offline"}
        async with self._lock:
            if not self._recovered:
                removed = store.delete_interrupted_runs()
                self._recovered = True
                if removed:
                    logger.info("Channel Digest: removed %d interrupted run(s); they will rerun.", removed)
            delivered = await self._deliver_pending(instant, client)
            if store.take_run_request():
                # A manual request from the web panel. It works even while scheduling is paused.
                manual_key = f"manual@{instant:%Y-%m-%dT%H:%M:%S.%f}"
                result = await self._execute(manual_key, "manual", cfg, instant, client)
                result["delivered"] = delivered
                return result
            if cfg["paused"]:
                return {"status": "paused", "delivered": delivered}
            try:
                slot = latest_due_slot(instant, cfg["time_of_day"], cfg["timezone"], cfg["schedule"], cfg["days"])
            except ValueError:
                return {"status": "misconfigured", "delivered": delivered}
            if slot is None:
                return {"status": "waiting", "delivered": delivered}
            key = slot_key(slot)
            if store.run_exists(key):
                return {"status": "up_to_date", "delivered": delivered}
            result = await self._execute(key, "scheduled", cfg, instant, client)
            result["delivered"] = delivered
            return result

    async def run_now(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        """Manual digest. Works even when scheduled digests are paused."""
        instant = _naive_utc(now or self._clock())
        cfg = store.get_config()
        if not cfg["enabled"]:
            return {"status": "disabled"}
        client = self._client()
        if client is None:
            return {"status": "offline"}
        async with self._lock:
            key = f"manual@{instant:%Y-%m-%dT%H:%M:%S.%f}"
            return await self._execute(key, "manual", cfg, instant, client)

    def snapshot(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        instant = _naive_utc(now or self._clock())
        cfg = store.get_config()
        upcoming = None
        try:
            slot = next_slot(instant, cfg["time_of_day"], cfg["timezone"], cfg["schedule"], cfg["days"])
            upcoming = slot.strftime("%Y-%m-%d %H:%M") + f" ({cfg['timezone']})" if slot else None
        except ValueError:
            upcoming = None
        runs = store.list_runs(limit=1)
        return {
            "config": cfg,
            "next_slot": upcoming,
            "last_run": runs[0] if runs else None,
            "pending": store.pending_count(),
            "running": self._lock.locked(),
        }

    # ------------------------------------------------------------ pipeline
    async def _execute(
        self,
        key: str,
        kind: str,
        cfg: Dict[str, Any],
        now: datetime,
        client: Any,
    ) -> Dict[str, Any]:
        run_id = store.create_run(key, kind, now)
        if run_id is None:
            return {"status": "duplicate"}
        try:
            batches, stats = await self._collect(cfg, client)
        except Exception as exc:
            logger.warning("Channel Digest collection failed: %s", _describe(exc))
            store.finish_run(run_id, "failed", _describe(exc), now)
            return {"status": "failed", "error": _describe(exc)}

        if stats["messages"] == 0:
            store.finish_empty(run_id, stats["checkpoints"], now)
            return {"status": "empty", "channels": stats["channels"], "skipped": stats["skipped"]}

        mode, overall, sections, notes = await self._summarize(batches, cfg)
        start, end = stats["period"]
        local_date = self._local_date(now, cfg["timezone"])
        body = dtext.render_digest(
            language=cfg["language"],
            date_label=local_date,
            period_label=dtext.period_label(start, end, cfg["timezone"]),
            overall=overall,
            sections=sections,
            stats=dtext.RenderStats(
                channels_checked=stats["channels"],
                messages_processed=stats["messages"],
                important_messages=stats["important"],
                mode=mode,
            ),
            notes=notes + stats["notes"],
            max_chars=int(cfg["max_chars"]),
        )
        chunks = dtext.split_for_telegram(body)
        store.commit_collection(
            run_id,
            body=body,
            chunk_total=len(chunks),
            mode=mode,
            period_start=start,
            period_end=end,
            channel_count=stats["channels"],
            message_count=stats["messages"],
            important_count=stats["important"],
            checkpoints=stats["checkpoints"],
            now=now,
        )
        result = await self._deliver(run_id, now, client)
        result.update({"messages": stats["messages"], "mode": mode, "channels": stats["channels"]})
        return result

    async def _fetch(self, client: Any, channel: Dict[str, Any], limit: int) -> List[Any]:
        waits = 0
        while True:
            try:
                return await collect.fetch_new(client, channel["chat_id"], int(channel["last_message_id"]), limit)
            except Exception as exc:
                seconds = collect.flood_wait_seconds(exc)
                if seconds is None:
                    raise
                waits += 1
                if seconds > self.max_flood_wait or waits > 2:
                    raise RuntimeError(f"Telegram asked to wait {seconds} seconds while reading channels.")
                logger.info("Channel Digest: Telegram flood wait %d s while reading.", seconds)
                await self._sleep(seconds + 1)

    async def _collect(self, cfg: Dict[str, Any], client: Any) -> Tuple[List[ChannelBatch], Dict[str, Any]]:
        channels = store.enabled_channels()
        budget = int(cfg["max_messages"])
        batches: List[ChannelBatch] = []
        checkpoints: Dict[int, int] = {}
        starts: List[datetime] = []
        ends: List[datetime] = []
        checked = 0
        skipped = 0
        total = 0
        important = 0
        for index, row in enumerate(channels):
            if budget <= 0:
                break
            checked += 1
            try:
                raw = await self._fetch(client, row, budget)
            except Exception as exc:
                skipped += 1
                logger.warning("Channel Digest: skipped one channel (%s).", _describe(exc))
                continue
            if raw:
                checkpoints[int(row["chat_id"])] = max(int(m.id) for m in raw)
            budget -= len(raw)
            messages = []
            for item in raw:
                source = collect.to_source(item, row)
                if dtext.matches_keywords(source.text, row["include_keywords"], row["exclude_keywords"]):
                    messages.append(source)
            if messages:
                starts.append(min(m.date for m in messages))
                ends.append(max(m.date for m in messages))
            total += len(messages)
            if int(row["priority"]) <= IMPORTANT_PRIORITY:
                important += len(messages)
            batches.append(
                ChannelBatch(
                    chat_id=int(row["chat_id"]),
                    title=row["title"],
                    username=row["username"],
                    priority=int(row["priority"]),
                    messages=messages,
                    checkpoint=checkpoints.get(int(row["chat_id"]), int(row["last_message_id"])),
                )
            )
            if budget > 0 and index + 1 < len(channels):
                await self._sleep(self.channel_delay)

        if checked and skipped == checked:
            raise RuntimeError("None of the selected channels could be read.")
        notes = []
        if skipped:
            notes.append(f"{skipped} channel(s) could not be read this time and will be retried")
        stats = {
            "channels": checked,
            "skipped": skipped,
            "messages": total,
            "important": important,
            "checkpoints": checkpoints,
            "period": (min(starts) if starts else None, max(ends) if ends else None),
            "notes": notes,
        }
        return batches, stats

    async def _summarize(
        self,
        batches: List[ChannelBatch],
        cfg: Dict[str, Any],
    ) -> Tuple[str, List[str], List[ChannelSection], List[str]]:
        labels = dtext.LABELS.get(cfg["language"], dtext.LABELS["en"])
        if not cfg["ai_enabled"]:
            overall, sections, notes = self._basic(batches, labels)
            return "basic", overall, sections, notes
        notes: List[str] = []
        try:
            system, prompt, _included, omitted = build_prompt(
                batches, cfg["language"], int(settings.ai_max_input_chars)
            )
            if omitted:
                notes.append(f"{omitted} {labels['ai_limit']}")
            result = await self.ai_complete(prompt=prompt, system=system, max_tokens=self.ai_max_tokens)
            raw_text = getattr(result, "text", result)
            verified, removed = verify_ai_output(parse_ai_json(str(raw_text)), batches)
            if removed:
                notes.append(f"{removed} {labels['dropped']}")
            by_title = {batch.title: batch for batch in batches}
            sections = []
            for item in verified["channels"]:
                batch = by_title[item["title"]]
                links = [m.link for m in sorted(batch.messages, key=lambda m: m.message_id, reverse=True) if m.link]
                sections.append(ChannelSection(title=item["title"], bullets=item["bullets"], links=links[:3]))
            return "ai", verified["overall"], sections, notes
        except AIVerificationError:
            logger.warning("Channel Digest: AI output could not be verified; using the basic digest.")
        except Exception as exc:
            logger.warning("Channel Digest: AI summary unavailable (%s); using the basic digest.", _describe(exc))
        overall, sections, notes = self._basic(batches, labels)
        return "ai_fallback_basic", overall, sections, notes

    @staticmethod
    def _basic(batches: List[ChannelBatch], labels: Dict[str, str]) -> Tuple[List[str], List[ChannelSection], List[str]]:
        """Basic digest plus a count of posts it does not show, so nothing is hidden silently."""
        overall, sections = dtext.basic_sections(batches)
        eligible = sum(1 for batch in batches for m in batch.messages if (m.text or "").strip())
        shown = sum(len(section.bullets) for section in sections)
        notes = [f"{eligible - shown} {labels['basic_omitted']}"] if eligible > shown else []
        return overall, sections, notes

    async def _send(self, client: Any, text: str) -> int:
        waits = 0
        while True:
            try:
                sent = await client.send_message(SAVED_MESSAGES, text)
                return int(getattr(sent, "id", 0) or 0)
            except Exception as exc:
                seconds = collect.flood_wait_seconds(exc)
                if seconds is None:
                    raise
                waits += 1
                if seconds > self.max_flood_wait or waits > 2:
                    raise RuntimeError(f"Telegram asked to wait {seconds} seconds before sending.") from exc
                logger.info("Channel Digest: Telegram flood wait %d s while sending.", seconds)
                await self._sleep(seconds + 1)

    async def _deliver(self, run_id: int, now: datetime, client: Any) -> Dict[str, Any]:
        run = store.get_run(run_id)
        if run is None or run["status"] != "pending_send":
            return {"status": "nothing_to_send"}
        chunks = dtext.split_for_telegram(run["body"])
        for index in range(int(run["delivered_chunks"]), len(chunks)):
            try:
                message_id = await self._send(client, chunks[index])
            except Exception as exc:
                attempts = int(run["attempts"]) + 1
                delay = min(self.retry_cap_seconds, self.retry_base_seconds * (2 ** min(attempts - 1, 10)))
                next_at = now + timedelta(seconds=delay)
                store.schedule_retry(run_id, attempts, next_at, _describe(exc), now)
                logger.warning("Channel Digest: delivery failed (%s); retry in %d s.", _describe(exc), delay)
                return {"status": "pending", "error": _describe(exc), "retry_in": delay}
            store.mark_chunk_sent(run_id, index + 1, message_id)
        store.mark_sent(run_id, now)
        return {"status": "sent", "parts": len(chunks)}

    async def _deliver_pending(self, now: datetime, client: Any) -> List[Dict[str, Any]]:
        results = []
        for run_id in store.pending_run_ids(now):
            results.append(await self._deliver(run_id, now, client))
        return results


digest_service = DigestService(client_provider=None)

__all__ = ["DigestService", "IMPORTANT_PRIORITY", "SAVED_MESSAGES", "digest_service"]
