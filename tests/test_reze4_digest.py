"""REZE 4.0: Channel Digest.

These tests use fake Telegram clients and fake AI responses. They verify the
logic: selection, checkpoints, scheduling, recovery, retries, splitting, and
privacy. They do not prove behaviour against a live Telegram account.
"""

import json
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import support  # noqa: F401  - prepares the database before reze imports

from reze.command_router import router
from reze.config import settings
from reze.database import db
from reze.digest import collect, schedule as sched, store, text as dtext
from reze.digest.models import ChannelBatch, SourceMessage
from reze.digest.service import DigestService, SAVED_MESSAGES
from reze.digest.summarize import AIVerificationError, build_prompt, parse_ai_json, verify_ai_output
from reze.features import features
from reze.commands import digest as digest_commands
from reze.migrations import v5

CH_A = -1001000000001
CH_B = -1001000000002
CH_C = -1001000000003  # never selected
ALL_TEST_CHATS = (CH_A, CH_B, CH_C)
OWNER = 4242
STRANGER = 999
T0 = datetime(2026, 11, 13, 20, 0)  # naive UTC; the 21:00 UTC slot is 60 minutes away


class FloodWaitError(Exception):
    """Same class name as Telethon's error; collect.flood_wait_seconds matches on the name."""

    def __init__(self, seconds):
        super().__init__(f"wait {seconds}")
        self.seconds = seconds


class FakeMessage(SimpleNamespace):
    pass


def post(message_id, text, when=None, forward=False):
    when = when or datetime(2026, 11, 13, 20, 30, tzinfo=timezone.utc)
    return FakeMessage(id=message_id, date=when, message=text, fwd_from=object() if forward else None, media=None)


class FakeClient:
    def __init__(self, posts):
        self.posts = posts
        self.sent = []
        self.fetches = []
        self.flood_chats = {}
        self.fail_chats = set()
        self.send_failures = 0
        self.entities = {}

    async def iter_messages(self, chat_id, min_id=0, limit=None, reverse=False):
        self.fetches.append(chat_id)
        if chat_id in self.flood_chats:
            raise FloodWaitError(self.flood_chats[chat_id])
        if chat_id in self.fail_chats:
            raise RuntimeError("channel is not accessible")
        found = sorted((m for m in self.posts.get(chat_id, []) if m.id > min_id), key=lambda m: m.id)
        for message in found[: limit or len(found)]:
            yield message

    async def get_messages(self, chat_id, limit=1):
        found = sorted(self.posts.get(chat_id, []), key=lambda m: m.id, reverse=True)
        return found[:limit]

    async def get_entity(self, target):
        return self.entities[target]

    async def send_message(self, target, text):
        if self.send_failures:
            self.send_failures -= 1
            raise RuntimeError("network is unreachable")
        self.sent.append((target, text))
        return SimpleNamespace(id=len(self.sent))


class Sleeps:
    def __init__(self):
        self.seconds = []

    async def __call__(self, value):
        self.seconds.append(value)


def _reset_digest_tables():
    placeholders = ",".join("?" for _ in ALL_TEST_CHATS)
    db.execute(f"DELETE FROM digest_channels WHERE chat_id IN ({placeholders})", ALL_TEST_CHATS)
    db.execute("DELETE FROM digest_runs")
    db.execute(
        "UPDATE digest_config SET enabled = 0, paused = 0, time_of_day = '21:00', timezone = 'UTC', "
        "schedule = 'daily', days = '0,1,2,3,4,5,6', max_messages = 200, max_chars = 12000, "
        "ai_enabled = 0, language = 'en' WHERE id = 1"
    )


class DigestCase(unittest.TestCase):
    def setUp(self):
        self._owner = settings.owner_id
        settings.owner_id = OWNER
        _reset_digest_tables()

    def tearDown(self):
        _reset_digest_tables()
        settings.owner_id = self._owner

    def configure(self, *, enabled=True, ai=False, language="en", max_messages=200, max_chars=12000):
        store.set_toggle("enabled", enabled)
        store.set_toggle("ai_enabled", ai)
        store.set_time("21:00")
        store.set_timezone("UTC")
        store.set_schedule("daily")
        store.set_language(language)
        store.set_limits(max_messages=max_messages, max_chars=max_chars)

    def select(self, chat_id, title, last_message_id=10, username=""):
        store.add_channel(chat_id, title, username, last_message_id, T0)

    def service(self, client, ai=None):
        sleeps = Sleeps()
        svc = DigestService(
            client_provider=lambda: client,
            ai_complete=ai,
            sleep=sleeps,
            clock=lambda: T0,
        )
        svc.channel_delay = 0
        svc.sleeps = sleeps
        return svc

    def at(self, hour, minute, day=13, month=11, year=2026):
        return datetime(year, month, day, hour, minute)

    def sent_text(self, client):
        return "\n".join(text for _, text in client.sent)


# ---------------------------------------------------------------- schedule
class ScheduleTests(unittest.TestCase):
    def test_time_of_day_must_be_24_hour(self):
        self.assertEqual(sched.parse_time_of_day("21:00"), (21, 0))
        self.assertEqual(sched.parse_time_of_day("9:05"), (9, 5))
        for bad in ("25:00", "21:60", "9pm", ""):
            with self.assertRaises(ValueError):
                sched.parse_time_of_day(bad)

    def test_timezone_must_be_a_real_iana_name(self):
        self.assertEqual(sched.load_timezone("Asia/Tehran").key, "Asia/Tehran")
        for bad in ("Mars/Olympus", "../etc/passwd", "", "UTC+3"):
            with self.assertRaises(ValueError):
                sched.load_timezone(bad)

    def test_schedule_validation(self):
        self.assertEqual(sched.parse_schedule("daily"), ("daily", "0,1,2,3,4,5,6"))
        self.assertEqual(sched.parse_schedule("weekly", "fri"), ("weekly", "4"))
        self.assertEqual(sched.parse_schedule("custom", "fri, mon"), ("custom", "0,4"))
        with self.assertRaises(ValueError):
            sched.parse_schedule("weekly", "mon,fri")
        with self.assertRaises(ValueError):
            sched.parse_schedule("custom", "funday")
        with self.assertRaises(ValueError):
            sched.parse_schedule("custom", "")

    def test_latest_due_slot_before_and_after_the_time(self):
        before = sched.latest_due_slot(datetime(2026, 11, 13, 20, 59), "21:00", "UTC", "daily", sched.ALL_DAYS)
        after = sched.latest_due_slot(datetime(2026, 11, 13, 21, 1), "21:00", "UTC", "daily", sched.ALL_DAYS)
        self.assertEqual(sched.slot_key(before), "2026-11-12T21:00@UTC")
        self.assertEqual(sched.slot_key(after), "2026-11-13T21:00@UTC")

    def test_timezone_conversion_uses_local_time(self):
        # 21:00 in Asia/Tehran (UTC+03:30 with no DST) is 17:30 UTC.
        slot = sched.latest_due_slot(datetime(2026, 11, 13, 17, 31), "21:00", "Asia/Tehran", "daily", sched.ALL_DAYS)
        self.assertEqual(slot.astimezone(timezone.utc).replace(tzinfo=None), datetime(2026, 11, 13, 17, 30))
        early = sched.latest_due_slot(datetime(2026, 11, 13, 17, 29), "21:00", "Asia/Tehran", "daily", sched.ALL_DAYS)
        self.assertEqual(sched.slot_key(early), "2026-11-12T21:00@Asia/Tehran")

    def test_selected_weekdays_only(self):
        # 2026-11-13 is a Friday (weekday 4). Only Monday (0) is allowed.
        slot = sched.latest_due_slot(datetime(2026, 11, 13, 22, 0), "21:00", "UTC", "custom", "0")
        self.assertEqual(slot.weekday(), 0)
        self.assertEqual(slot.date().isoformat(), "2026-11-09")

    def test_missed_slots_resolve_to_the_single_latest_one(self):
        slot = sched.latest_due_slot(datetime(2026, 11, 16, 10, 0), "21:00", "UTC", "daily", sched.ALL_DAYS)
        self.assertEqual(sched.slot_key(slot), "2026-11-15T21:00@UTC")

    def test_daylight_saving_gap_does_not_crash(self):
        # 2026-03-08 02:30 does not exist in America/New_York.
        slot = sched.latest_due_slot(datetime(2026, 3, 8, 12, 0), "02:30", "America/New_York", "daily", sched.ALL_DAYS)
        self.assertIsNotNone(slot)

    def test_next_slot_is_after_now(self):
        nxt = sched.next_slot(datetime(2026, 11, 13, 21, 1), "21:00", "UTC", "daily", sched.ALL_DAYS)
        self.assertEqual(sched.slot_key(nxt), "2026-11-14T21:00@UTC")


# -------------------------------------------------------------------- text
class TextTests(unittest.TestCase):
    def test_links_for_public_private_and_unknown_posts(self):
        self.assertEqual(dtext.message_link(-1001234567890, "news", 7), "https://t.me/news/7")
        self.assertEqual(dtext.message_link(-1001234567890, "", 42), "https://t.me/c/1234567890/42")
        self.assertIsNone(dtext.message_link(12, "", 1))
        self.assertIsNone(dtext.message_link(-1001234567890, "", 0))

    def test_split_loses_no_words_and_respects_telegram_limit(self):
        lines = [f"item {i:04d} " + "word " * 40 for i in range(120)]
        body = "\n".join(lines)
        chunks = dtext.split_for_telegram(body)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(dtext.utf16_len(chunk), 4096)
        rejoined = " ".join(" ".join(chunks).split())
        for i in range(120):
            self.assertIn(f"item {i:04d}", rejoined)

    def test_emoji_heavy_text_stays_under_the_utf16_limit(self):
        body = "🔥" * 6000
        chunks = dtext.split_for_telegram(body)
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertLessEqual(dtext.utf16_len(chunk), 4096)

    def test_empty_body_produces_no_message(self):
        self.assertEqual(dtext.split_for_telegram(""), [])
        self.assertEqual(dtext.split_for_telegram("   \n  "), [])

    def test_grounding_flags_numbers_not_in_the_source(self):
        self.assertEqual(dtext.unsupported_tokens("Price 120 USD", ["price 12 usd"]), ["120"])
        self.assertEqual(dtext.unsupported_tokens("Price 12 USD", ["price 12 usd"]), [])

    def test_grounding_normalizes_persian_digits(self):
        self.assertEqual(dtext.unsupported_tokens("۱۲۰ دلار", ["120 dollars"]), [])

    def test_grounding_checks_links_exactly(self):
        self.assertEqual(
            dtext.unsupported_tokens("see https://example.com/a", ["see https://example.com/a."]), []
        )
        self.assertEqual(
            dtext.unsupported_tokens("see https://evil.example/x", ["see https://example.com/a"]),
            ["https://evil.example/x"],
        )

    def test_keyword_filters(self):
        self.assertTrue(dtext.matches_keywords("Bitcoin rises", "bitcoin,rate", ""))
        self.assertFalse(dtext.matches_keywords("Ethereum rises", "bitcoin,rate", ""))
        self.assertFalse(dtext.matches_keywords("Bitcoin sale ad", "", "sale"))
        self.assertTrue(dtext.matches_keywords("anything", "", ""))

    def test_rendering_counts_every_bullet_it_cannot_fit(self):
        sections = [
            dtext.ChannelSection(title=f"Channel {i}", bullets=[f"update {i}-{j} " + "x" * 180 for j in range(30)])
            for i in range(5)
        ]
        out = dtext.render_digest(
            language="en",
            date_label="2026-11-13",
            period_label="09:00 — 21:00",
            overall=[],
            sections=sections,
            stats=dtext.RenderStats(5, 150, 12, "basic"),
            notes=[],
            max_chars=4000,
        )
        self.assertLessEqual(len(out), 4000)
        shown = sum(1 for line in out.splitlines() if line.startswith("- update "))
        self.assertIn(f"{150 - shown} more item(s) not shown", out)

    def test_persian_render_uses_right_to_left_mark(self):
        out = dtext.render_digest(
            language="fa",
            date_label="2026-11-13",
            period_label="x",
            overall=["نکته"],
            sections=[],
            stats=dtext.RenderStats(1, 1, 0, "basic"),
            notes=[],
            max_chars=4000,
        )
        self.assertTrue(out.startswith("\u200f"))


# ---------------------------------------------------------------------- AI
class AISummaryTests(unittest.TestCase):
    def _batch(self):
        message = SourceMessage(CH_A, "News", "", 1, 5, datetime(2026, 11, 13, 9), "Launch is 2026-11-20. Price 120 USD.")
        return [ChannelBatch(CH_A, "News", "", 1, [message], 5)]

    def test_parses_fenced_json(self):
        data = parse_ai_json('```json\n{"overall": ["a"], "channels": []}\n```')
        self.assertEqual(data["overall"], ["a"])

    def test_rejects_non_json_and_wrong_shapes(self):
        with self.assertRaises(ValueError):
            parse_ai_json("I cannot help with that.")
        with self.assertRaises(ValueError):
            parse_ai_json('{"overall": "not a list", "channels": []}')

    def test_removes_unsupported_statements_and_counts_them(self):
        parsed = parse_ai_json(
            json.dumps(
                {
                    "overall": ["Launch on 2026-11-20"],
                    "channels": [{"title": "News", "bullets": ["Price 120 USD", "Price 999 USD"]}],
                }
            )
        )
        verified, removed = verify_ai_output(parsed, self._batch())
        self.assertEqual(removed, 1)
        self.assertEqual(verified["channels"][0]["bullets"], ["Price 120 USD"])

    def test_unknown_channel_titles_are_dropped(self):
        parsed = parse_ai_json(json.dumps({"overall": [], "channels": [{"title": "Invented", "bullets": ["Launch 2026-11-20"]}]}))
        with self.assertRaises(AIVerificationError):
            verify_ai_output(parsed, self._batch())

    def test_nothing_verified_raises_so_the_caller_falls_back(self):
        parsed = parse_ai_json(json.dumps({"overall": ["Made up 77"], "channels": []}))
        with self.assertRaises(AIVerificationError):
            verify_ai_output(parsed, self._batch())

    def test_prompt_budget_counts_posts_it_leaves_out(self):
        batch = [
            ChannelBatch(
                CH_A,
                "News",
                "",
                1,
                [
                    SourceMessage(CH_A, "News", "", 1, i, datetime(2026, 11, 13, 9, i % 60), "post " + "y" * 300)
                    for i in range(1, 20)
                ],
                19,
            )
        ]
        _system, _prompt, included, omitted = build_prompt(batch, "en", budget_chars=1000)
        self.assertGreater(omitted, 0)
        self.assertEqual(len(included) + omitted, 19)


# ------------------------------------------------------------------- schema
class MigrationTests(unittest.TestCase):
    def test_migration_creates_tables_with_everything_off_and_keeps_old_data(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE search_index (id INTEGER PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO search_index (body) VALUES ('keep me')")
        v5.apply(conn)
        v5.apply(conn)  # idempotent
        row = conn.execute("SELECT * FROM digest_config WHERE id = 1").fetchone()
        self.assertEqual(row["enabled"], 0)
        self.assertEqual(row["paused"], 0)
        self.assertEqual(row["ai_enabled"], 0)
        self.assertEqual(conn.execute("SELECT body FROM search_index").fetchone()[0], "keep me")
        conn.close()


# -------------------------------------------------------------------- store
class StoreTests(DigestCase):
    def test_limits_and_times_are_validated(self):
        with self.assertRaises(ValueError):
            store.set_limits(max_messages=0)
        with self.assertRaises(ValueError):
            store.set_limits(max_chars=10)
        with self.assertRaises(ValueError):
            store.set_time("99:99")
        with self.assertRaises(ValueError):
            store.set_timezone("Nowhere/Land")
        with self.assertRaises(ValueError):
            store.set_schedule("weekly", "mon,fri")
        with self.assertRaises(ValueError):
            store.set_language("de")

    def test_channel_selection_add_remove_and_priority(self):
        self.assertTrue(store.add_channel(CH_A, "A", "a", 5, T0))
        self.assertFalse(store.add_channel(CH_A, "A", "a", 5, T0))  # already selected
        store.update_channel(CH_A, priority=2, include_keywords="rate")
        row = store.get_channel(CH_A)
        self.assertEqual(row["priority"], 2)
        self.assertEqual(row["include_keywords"], "rate")
        with self.assertRaises(ValueError):
            store.update_channel(CH_A, priority=11)
        self.assertTrue(store.remove_channel(CH_A))
        self.assertIsNone(store.get_channel(CH_A))

    def test_one_run_per_slot_is_enforced_by_the_database(self):
        first = store.create_run("2026-11-13T21:00@UTC", "scheduled", T0)
        second = store.create_run("2026-11-13T21:00@UTC", "scheduled", T0)
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_checkpoint_and_body_are_committed_together(self):
        self.select(CH_A, "A", last_message_id=10)
        run = store.create_run("k-atomic", "scheduled", T0)
        store.commit_collection(
            run,
            body="body",
            chunk_total=1,
            mode="basic",
            period_start=T0,
            period_end=T0,
            channel_count=1,
            message_count=3,
            important_count=0,
            checkpoints={CH_A: 13},
            now=T0,
        )
        self.assertEqual(store.get_channel(CH_A)["last_message_id"], 13)
        self.assertEqual(store.get_run(run)["status"], "pending_send")
        self.assertEqual(store.get_run(run)["body"], "body")

    def test_history_listing_never_includes_message_bodies(self):
        run = store.create_run("k-list", "scheduled", T0)
        store.commit_collection(
            run, body="SECRET POST TEXT", chunk_total=1, mode="basic", period_start=None, period_end=None,
            channel_count=0, message_count=0, important_count=0, checkpoints={}, now=T0,
        )
        for row in store.list_runs(limit=5):
            self.assertNotIn("body", row)
            self.assertNotIn("SECRET POST TEXT", json.dumps(row, default=str))

    def test_clear_history_removes_stored_bodies(self):
        run = store.create_run("k-clear", "scheduled", T0)
        store.commit_collection(
            run, body="private", chunk_total=1, mode="basic", period_start=None, period_end=None,
            channel_count=0, message_count=0, important_count=0, checkpoints={}, now=T0,
        )
        store.clear_history()
        self.assertIsNone(store.get_run(run))


# ------------------------------------------------------------------ service
class ServiceTests(DigestCase):
    def test_disabled_by_default_and_sends_nothing(self):
        client = FakeClient({CH_A: [post(11, "hello")]})
        self.select(CH_A, "Alpha", 10)
        result = asyncio_run(self.service(client).tick(self.at(21, 5)))
        self.assertEqual(result["status"], "disabled")
        self.assertEqual(client.sent, [])

    def test_first_digest_goes_to_saved_messages_and_checkpoints_move(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        self.select(CH_B, "Beta", 20)
        client = FakeClient({
            CH_A: [post(11, "Alpha rate 4.2% today"), post(12, "Alpha news"), post(13, "Alpha links https://t.me/alpha/9")],
            CH_B: [post(21, "Beta announcement on 2026-11-20")],
        })
        result = asyncio_run(self.service(client).tick(self.at(21, 5)))
        self.assertEqual(result["status"], "sent")
        self.assertTrue(client.sent)
        self.assertEqual({target for target, _ in client.sent}, {SAVED_MESSAGES})
        self.assertIn("Alpha", self.sent_text(client))
        self.assertIn("Beta announcement", self.sent_text(client))
        self.assertEqual(store.get_channel(CH_A)["last_message_id"], 13)
        self.assertEqual(store.get_channel(CH_B)["last_message_id"], 21)

    def test_repeated_ticks_in_the_same_slot_do_not_duplicate(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "one")]})
        svc = self.service(client)
        asyncio_run(svc.tick(self.at(21, 5)))
        asyncio_run(svc.tick(self.at(21, 10)))
        asyncio_run(svc.tick(self.at(21, 59)))
        self.assertEqual(len(client.sent), 1)
        self.assertEqual(store.list_runs(limit=10)[0]["status"], "sent")

    def test_missed_schedules_after_downtime_produce_one_catch_up_digest(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "day one")]})
        asyncio_run(self.service(client).tick(self.at(21, 5, day=13)))
        # Downtime: the 14th and 15th pass. Posts arrive meanwhile.
        client.posts[CH_A].extend([post(12, "day two"), post(13, "day three")])
        svc = self.service(client)
        result = asyncio_run(svc.tick(self.at(10, 0, day=16)))
        self.assertEqual(result["status"], "sent")
        self.assertEqual(len(store.list_runs(limit=50)), 2, "one run for the first slot, one catch-up")
        self.assertEqual(store.get_channel(CH_A)["last_message_id"], 13)
        self.assertIn("day two", self.sent_text(client))
        self.assertIn("day three", self.sent_text(client))
        asyncio_run(svc.tick(self.at(12, 0, day=16)))
        self.assertEqual(len(store.list_runs(limit=50)), 2, "no duplicate catch-up")

    def test_empty_window_sends_nothing_but_still_advances_checkpoints(self):
        self.configure()
        store.update_channel  # noqa: B018 - reference only
        self.select(CH_A, "Alpha", 10)
        store.update_channel(CH_A, exclude_keywords="spam")
        client = FakeClient({CH_A: [post(11, "spam offer"), post(12, "more spam")]})
        result = asyncio_run(self.service(client).tick(self.at(21, 5)))
        self.assertEqual(result["status"], "empty")
        self.assertEqual(client.sent, [])
        self.assertEqual(store.get_channel(CH_A)["last_message_id"], 12)

    def test_ai_failure_falls_back_to_basic_and_still_delivers(self):
        self.configure(ai=True)
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "Important: deadline 2026-11-20")]})

        async def broken_ai(prompt, system, max_tokens):
            raise RuntimeError("provider is down")

        result = asyncio_run(self.service(client, ai=broken_ai).tick(self.at(21, 5)))
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["mode"], "ai_fallback_basic")
        self.assertIn("Basic summary (AI was unavailable)", self.sent_text(client))
        self.assertIn("deadline 2026-11-20", self.sent_text(client))

    def test_unverified_ai_numbers_are_removed_and_reported(self):
        self.configure(ai=True)
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "Launch is on 2026-11-20 at the fair.")]})

        async def ai(prompt, system, max_tokens):
            payload = {
                "overall": ["Launch on 2026-11-20"],
                "channels": [{"title": "Alpha", "bullets": ["Launch on 2026-11-20", "Budget is 9999 dollars"]}],
            }
            return SimpleNamespace(text=json.dumps(payload))

        result = asyncio_run(self.service(client, ai=ai).tick(self.at(21, 5)))
        self.assertEqual(result["mode"], "ai")
        body = self.sent_text(client)
        self.assertIn("Launch on 2026-11-20", body)
        self.assertNotIn("9999", body)
        self.assertIn("AI statements removed", body)

    def test_delivery_failure_retries_later_and_clears_the_body_after_success(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "keep this")]})
        client.send_failures = 1
        svc = self.service(client)
        result = asyncio_run(svc.tick(self.at(21, 5)))
        self.assertEqual(result["status"], "pending")
        run = store.list_runs(limit=1)[0]
        self.assertEqual(run["status"], "pending_send")
        self.assertEqual(store.get_channel(CH_A)["last_message_id"], 11, "collected posts are safe, not lost")
        asyncio_run(svc.tick(self.at(21, 5, day=13)))  # still inside the backoff window
        self.assertEqual(client.sent, [])
        asyncio_run(svc.tick(datetime(2026, 11, 13, 21, 7)))
        self.assertEqual(len(client.sent), 1)
        self.assertEqual(store.get_run(run["id"])["body"], "")
        self.assertEqual(store.get_run(run["id"])["status"], "sent")

    def test_flood_wait_while_reading_is_honoured_then_retried(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "after the wait")]})
        client.flood_chats = {CH_A: 2}
        svc = self.service(client)
        original = client.iter_messages

        calls = {"n": 0}

        async def once_flooded(chat_id, min_id=0, limit=None, reverse=False):
            calls["n"] += 1
            if calls["n"] == 1:
                raise FloodWaitError(2)
            client.flood_chats = {}
            async for item in original(chat_id, min_id=min_id, limit=limit, reverse=reverse):
                yield item

        client.iter_messages = once_flooded
        result = asyncio_run(svc.tick(self.at(21, 5)))
        self.assertEqual(result["status"], "sent")
        self.assertIn(3, svc.sleeps.seconds, "waited the flood-wait time plus one second")

    def test_long_flood_wait_skips_only_that_channel(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        self.select(CH_B, "Beta", 20)
        client = FakeClient({CH_A: [post(11, "alpha text")], CH_B: [post(21, "beta text")]})
        client.flood_chats = {CH_A: 99999}
        result = asyncio_run(self.service(client).tick(self.at(21, 5)))
        self.assertEqual(result["status"], "sent")
        self.assertIn("beta text", self.sent_text(client))
        self.assertNotIn("alpha text", self.sent_text(client))
        self.assertEqual(store.get_channel(CH_A)["last_message_id"], 10, "skipped channel keeps its checkpoint")
        self.assertIn("could not be read", self.sent_text(client))

    def test_when_every_channel_fails_the_run_fails_and_checkpoints_hold(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "x")]})
        client.fail_chats = {CH_A}
        result = asyncio_run(self.service(client).tick(self.at(21, 5)))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(store.get_channel(CH_A)["last_message_id"], 10)
        self.assertEqual(client.sent, [])

    def test_long_digest_is_split_into_telegram_sized_messages(self):
        self.configure(max_chars=20000)
        for index, chat in enumerate((CH_A, CH_B)):
            self.select(chat, f"Channel {index}", 10)
        posts_a = [post(11 + i, f"alpha item {i:03d} " + "detail " * 30) for i in range(10)]
        posts_b = [post(100 + i, f"beta item {i:03d} " + "detail " * 30) for i in range(10)]
        client = FakeClient({CH_A: posts_a, CH_B: posts_b})
        asyncio_run(self.service(client).tick(self.at(21, 5)))
        self.assertGreater(len(client.sent), 1)
        for _, chunk in client.sent:
            self.assertLessEqual(dtext.utf16_len(chunk), 4096)
        joined = " ".join(text for _, text in client.sent)
        self.assertIn("alpha item 000", joined)
        self.assertIn("beta item 000", joined)

    def test_unselected_and_disabled_channels_are_never_read(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        self.select(CH_B, "Beta", 20)
        store.update_channel(CH_B, enabled=False)
        client = FakeClient({
            CH_A: [post(11, "a")],
            CH_B: [post(21, "b")],
            CH_C: [post(5, "never selected")],
        })
        asyncio_run(self.service(client).tick(self.at(21, 5)))
        self.assertIn(CH_A, client.fetches)
        self.assertNotIn(CH_B, client.fetches)
        self.assertNotIn(CH_C, client.fetches)
        self.assertNotIn("never selected", self.sent_text(client))

    def test_message_budget_never_loses_posts_between_digests(self):
        self.configure(max_messages=5)
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11 + i, f"post {i:02d}") for i in range(12)]})
        svc = self.service(client)
        asyncio_run(svc.tick(self.at(21, 5)))
        asyncio_run(svc.tick(datetime(2026, 11, 14, 21, 5)))
        asyncio_run(svc.tick(datetime(2026, 11, 15, 21, 5)))
        text = self.sent_text(client)
        for i in range(12):
            self.assertIn(f"post {i:02d}", text, f"post {i:02d} was lost")

    def test_restart_removes_interrupted_runs_and_resumes_partial_delivery(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        interrupted = store.create_run("k-interrupted", "scheduled", T0)
        self.assertIsNotNone(interrupted)
        body = "\n".join(f"line {i:04d} " + "z" * 80 for i in range(120))
        chunks = dtext.split_for_telegram(body)
        self.assertGreaterEqual(len(chunks), 3)
        pending = store.create_run("k-pending", "scheduled", T0)
        store.commit_collection(
            pending, body=body, chunk_total=len(chunks), mode="basic", period_start=None, period_end=None,
            channel_count=1, message_count=1, important_count=0, checkpoints={}, now=T0,
        )
        store.mark_chunk_sent(pending, 1, 555)
        client = FakeClient({})
        asyncio_run(self.service(client).tick(self.at(21, 5)))
        self.assertIsNone(store.get_run(interrupted), "a crashed collection is removed so its slot reruns")
        self.assertEqual(len(client.sent), len(chunks) - 1, "only the undelivered parts are sent")
        self.assertEqual(store.get_run(pending)["status"], "sent")

    def test_run_now_works_when_paused_and_is_refused_when_off(self):
        self.configure(enabled=False)
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "manual please")]})
        svc = self.service(client)
        self.assertEqual(asyncio_run(svc.run_now(self.at(9, 0)))["status"], "disabled")
        store.set_toggle("enabled", True)
        store.set_toggle("paused", True)
        result = asyncio_run(svc.run_now(self.at(9, 0)))
        self.assertEqual(result["status"], "sent")
        self.assertIn("manual please", self.sent_text(client))

    def test_offline_telegram_creates_no_run_so_the_slot_is_retried_later(self):
        self.configure()
        self.select(CH_A, "Alpha", 10)
        svc = DigestService(client_provider=lambda: None, sleep=Sleeps(), clock=lambda: T0)
        self.assertEqual(asyncio_run(svc.tick(self.at(21, 5)))["status"], "offline")
        self.assertEqual(store.list_runs(limit=5), [])

    def test_schedule_is_evaluated_in_the_configured_timezone(self):
        self.configure()
        store.set_timezone("Asia/Tehran")
        self.select(CH_A, "Alpha", 10)
        client = FakeClient({CH_A: [post(11, "tehran post")]})
        svc = self.service(client)
        # 17:29 UTC is 20:59 in Tehran: the 12th's 21:00 slot is the latest due one.
        first = asyncio_run(svc.tick(datetime(2026, 11, 13, 17, 29)))
        self.assertEqual(first["status"], "sent")
        self.assertEqual(store.list_runs(limit=5)[-1]["slot_key"], "2026-11-12T21:00@Asia/Tehran")
        # 17:31 UTC is 21:01 in Tehran: the 13th's slot is now due and is a new run.
        client.posts[CH_A].append(post(12, "second post"))
        self.assertEqual(asyncio_run(svc.tick(datetime(2026, 11, 13, 17, 31)))["status"], "sent")
        # Still before the next slot: no duplicate.
        self.assertEqual(asyncio_run(svc.tick(datetime(2026, 11, 13, 17, 45)))["status"], "up_to_date")


# ------------------------------------------------------------ telegram glue
class CollectTests(unittest.TestCase):
    def test_flood_wait_is_recognised_by_name(self):
        self.assertEqual(collect.flood_wait_seconds(FloodWaitError(30)), 30)
        self.assertIsNone(collect.flood_wait_seconds(RuntimeError("nope")))

    def test_channel_peer_id_matches_telegrams_marked_form(self):
        entity = SimpleNamespace(id=1234567890)
        self.assertEqual(collect.peer_id_for_channel(entity), -1001234567890)

    def test_media_without_caption_is_described_not_downloaded(self):
        media = type("MessageMediaPhoto", (), {})()
        raw = SimpleNamespace(id=9, date=datetime(2026, 11, 13, 9, tzinfo=timezone.utc), message="", media=media, fwd_from=None)
        source = collect.to_source(raw, {"chat_id": CH_A, "title": "A", "username": "a", "priority": 5})
        self.assertEqual(source.text, "[photo]")
        self.assertEqual(source.link, "https://t.me/a/9")
        self.assertEqual(source.date, datetime(2026, 11, 13, 9))


# ----------------------------------------------------------------- commands
def flat(text):
    """Visible words of a framed ascii reply: borders removed, whitespace collapsed, upper-cased."""
    cleaned = "".join(ch if ch not in "╔╗╚╝║═╠╣─│" else " " for ch in text)
    return " ".join(cleaned.upper().split())


class FakeCtx:
    def __init__(self, args, sender_id, client=None):
        self.args = args
        self.sender_id = sender_id
        self.client = client
        self.chat_id = None
        self.replies = []

    async def reply(self, text=""):
        self.replies.append(str(text))
        return str(text)

    async def reply_usage(self, note=""):
        self.replies.append("USAGE " + str(note))
        return note


class CommandTests(DigestCase):
    def setUp(self):
        super().setUp()
        self._feature_was_on = features.is_enabled("channel_digest")

    def tearDown(self):
        if features.is_enabled("channel_digest") and not self._feature_was_on:
            features.disable("channel_digest", actor=OWNER)
        super().tearDown()

    def test_command_registration_keeps_the_legacy_name_working(self):
        self.assertIn("chatdigest", router.commands)
        self.assertFalse(router.commands["digest"].owner_only, "non-owners keep the chat summary")

    def test_feature_off_is_reported_for_the_owner(self):
        if features.is_enabled("channel_digest"):
            features.disable("channel_digest", actor=OWNER)
        ctx = FakeCtx(["status"], OWNER)
        asyncio_run(digest_commands.digest_cmd(ctx))
        self.assertTrue(any("FEATURE IS OFF" in flat(reply) for reply in ctx.replies))

    def test_owner_only_management_refuses_strangers(self):
        ctx = FakeCtx(["status"], STRANGER)
        asyncio_run(digest_commands.digest_cmd(ctx))
        self.assertTrue(any("OWNER ONLY" in flat(reply) for reply in ctx.replies))

    def test_bare_digest_for_strangers_keeps_the_legacy_chat_summary(self):
        ctx = FakeCtx([], STRANGER, client=None)
        asyncio_run(digest_commands.digest_cmd(ctx))
        self.assertTrue(any("NEEDS AN ACTIVE TELEGRAM CLIENT" in flat(reply) for reply in ctx.replies))

    def test_numeric_digest_routes_to_the_chat_summary_for_the_owner(self):
        ctx = FakeCtx(["30"], OWNER, client=None)
        asyncio_run(digest_commands.digest_cmd(ctx))
        self.assertTrue(any("NEEDS AN ACTIVE TELEGRAM CLIENT" in flat(reply) for reply in ctx.replies))

    def test_add_then_remove_a_channel_with_a_resolved_entity(self):
        features.enable("channel_digest", actor=OWNER, confirmed=True)
        entity = SimpleNamespace(id=1000000001, broadcast=True, title="Alpha", username="alpha")
        client = FakeClient({CH_A: [post(77, "latest")]})
        client.entities = {"@alpha": entity}
        ctx = FakeCtx(["add", "@alpha"], OWNER, client=client)
        asyncio_run(digest_commands.digest_cmd(ctx))
        self.assertTrue(any("CHANNEL ADDED" in flat(reply) for reply in ctx.replies))
        self.assertIsNotNone(store.get_channel(CH_A))
        self.assertEqual(store.get_channel(CH_A)["last_message_id"], 77, "only posts after now are collected")
        ctx = FakeCtx(["remove", "@alpha"], OWNER)
        asyncio_run(digest_commands.digest_cmd(ctx))
        self.assertIsNone(store.get_channel(CH_A))

    def test_groups_are_refused_as_digest_sources(self):
        features.enable("channel_digest", actor=OWNER, confirmed=True)
        group = SimpleNamespace(id=5, broadcast=False, title="Group", username="grp")
        client = FakeClient({})
        client.entities = {"@grp": group}
        ctx = FakeCtx(["add", "@grp"], OWNER, client=client)
        asyncio_run(digest_commands.digest_cmd(ctx))
        self.assertTrue(any("ONLY BROADCAST CHANNELS" in flat(reply) for reply in ctx.replies))
        self.assertIsNone(store.get_channel(-1000000000005))

    def test_clear_requires_confirmation(self):
        features.enable("channel_digest", actor=OWNER, confirmed=True)
        ctx = FakeCtx(["clear"], OWNER)
        asyncio_run(digest_commands.digest_cmd(ctx))
        self.assertTrue(any("CONFIRMATION NEEDED" in flat(reply) for reply in ctx.replies))


# -------------------------------------------------------------------- utils
def asyncio_run(coro):
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


if __name__ == "__main__":
    unittest.main()
