"""AFK mode, mention/keyword alerts, and the archive search/export commands."""

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from datetime import datetime

import support
from reze.modules.afk import AfkService, parse_duration, human_duration
from reze.modules.alerts import AlertService, message_link
from reze.modules.msglog import MessageLogger


def run(coro):
    return asyncio.run(coro)


class Sender:
    def __init__(self, uid=7, first="Sara", username=None, bot=False):
        self.id, self.first_name, self.last_name, self.username, self.bot = uid, first, None, username, bot


class Chat:
    def __init__(self, title="Team", username=None):
        self.title, self.username, self.first_name, self.last_name, self.id = title, username, None, None, 1


class Msg:
    def __init__(self, text="hi", out=False, mentioned=False, mid=1):
        self.raw_text, self.message, self.out, self.mentioned, self.id = text, text, out, mentioned, mid
        self.action, self.media, self.date = None, None, datetime(2026, 10, 30, 10, 0, 0)


class Client:
    def __init__(self, own_id=1):
        self.sent, self.files, self.own_id = [], [], own_id

    async def send_message(self, entity, text, **kwargs):
        self.sent.append((entity, text, kwargs))

    async def send_file(self, entity, file, **kwargs):
        self.files.append((entity, file, kwargs))

    async def get_peer_id(self, who):
        return self.own_id


class Event:
    def __init__(self, msg, chat_id=500, private=True, group=False, sender=None, chat=None, sender_id=None, client=None):
        self.message, self.chat_id, self.is_private, self.is_group = msg, chat_id, private, group
        self._sender, self._chat, self.client = sender or Sender(), chat or Chat(), client
        self.sender_id = sender_id if sender_id is not None else self._sender.id

    async def get_sender(self):
        return self._sender

    async def get_chat(self):
        return self._chat


class Env(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="reze-afk-")
        self.db = os.path.join(self.dir, "x.db")
        self.settings = {}
        self.now = [1_800_000_000.0]
        self.client = Client()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def conn(self):
        c = sqlite3.connect(self.db)
        c.row_factory = sqlite3.Row
        return c

    def store(self):
        return dict(get_setting=lambda k, d=None: self.settings.get(k, d), set_setting=self.settings.__setitem__)


class AfkTests(Env):
    def setUp(self):
        super().setUp()
        self.afk = AfkService(connect=self.conn, clock=lambda: self.now[0], **self.store())

    def private(self, text="hello", **kw):
        run(self.afk.on_new_message(Event(Msg(text), client=self.client, **kw)))

    def test_duration_parsing(self):
        self.assertEqual((parse_duration("30m"), parse_duration("2h"), parse_duration("1d")), (1800, 7200, 86400))
        self.assertIsNone(parse_duration("soon"))
        self.assertIsNone(parse_duration("0x"))
        self.assertEqual(human_duration(5400), "1h 30m")

    def test_inactive_does_nothing(self):
        self.private()
        self.assertEqual(self.client.sent, [])

    def test_one_reply_per_person_per_cooldown(self):
        self.afk.enable("in a meeting")
        self.private(sender=Sender(7))
        self.private("again", sender=Sender(7))
        self.private("other person", sender=Sender(8, "Ali"), chat_id=501)
        replies = [s for s in self.client.sent if s[0] in (500, 501)]
        self.assertEqual([r[0] for r in replies], [500, 501])  # not twice for the same person
        self.assertIn("in a meeting", replies[0][1])
        self.assertIsNone(replies[0][2]["parse_mode"])
        self.now[0] += 7 * 3600  # cooldown over -> a fresh reply is allowed
        self.private("later", sender=Sender(7))
        self.assertEqual(len([s for s in self.client.sent if s[0] == 500]), 2)

    def test_bots_groups_and_own_messages_get_no_reply(self):
        self.afk.enable()
        self.private(sender=Sender(9, bot=True))
        run(self.afk.on_new_message(Event(Msg("x"), private=False, group=True, client=self.client)))
        run(self.afk.on_new_message(Event(Msg("mine", out=True), client=self.client)))
        self.assertEqual(self.client.sent, [])

    def test_custom_text_and_default_text(self):
        self.afk.enable("lunch")
        self.assertIn("(lunch)", self.afk.reply_text())
        self.afk.set_text("Back at 5!")
        self.private()
        self.assertEqual(self.client.sent[0][1], "Back at 5!")

    def test_missed_log_summary_and_back(self):
        self.afk.enable()
        self.private("hey", sender=Sender(7, "Sara"))
        self.private("you there?", sender=Sender(7, "Sara"))
        self.private("hi", sender=Sender(8, "Ali"), chat_id=501)
        run(self.afk.on_new_message(Event(Msg("@me look at this", mentioned=True), chat_id=-100, private=False,
                                          group=True, chat=Chat("Dev Group"), client=self.client)))
        run(self.afk.on_new_message(Event(Msg("no mention"), chat_id=-100, private=False, group=True, client=self.client)))
        self.now[0] += 3 * 3600
        summary = self.afk.disable()
        self.assertEqual(summary["away_for"], "3h 0m")
        self.assertEqual([(p["name"], p["count"]) for p in summary["people"]], [("Sara", 2), ("Ali", 1)])
        self.assertEqual(len(summary["mentions"]), 1)
        text = self.afk.format_summary(summary)
        self.assertIn("Sara: 2", text)
        self.assertIn("Dev Group", text)
        self.assertFalse(self.afk.active)
        self.assertEqual(self.afk.summary()["total"], 0)  # log cleared

    def test_timer_expiry_disables_and_sends_the_summary_to_saved_messages(self):
        self.afk.enable("quick", seconds=1800)
        self.private("one", sender=Sender(7, "Sara"))
        self.now[0] += 3600
        self.private("two", sender=Sender(8, "Ali"), chat_id=501)  # first event after the timer ends it
        self.assertFalse(self.afk.active)
        entity, text, _ = self.client.sent[-1]
        self.assertEqual(entity, "me")
        self.assertIn("WELCOME BACK", text)
        self.assertEqual(len([s for s in self.client.sent if s[0] == 501]), 0)  # no reply after expiry

    def test_state_survives_a_restart(self):
        self.afk.enable("away", seconds=600)
        again = AfkService(connect=self.conn, clock=lambda: self.now[0], **self.store())
        self.assertTrue(again.active)
        self.assertEqual(again.state["reason"], "away")

    def test_auto_off_ignores_commands_saved_messages_and_empty(self):
        self.afk.enable()
        self.afk.set_auto_off(True)
        for msg, chat in ((Msg(".ping", out=True), 500), (Msg("note", out=True), 1), (Msg("  ", out=True), 500)):
            run(self.afk.on_outgoing(Event(msg, chat_id=chat, client=self.client)))
        self.assertTrue(self.afk.active)
        run(self.afk.on_outgoing(Event(Msg("I'm back, hi!", out=True), chat_id=500, client=self.client)))
        self.assertFalse(self.afk.active)
        self.assertEqual(self.client.sent[-1][0], "me")

    def test_auto_off_is_opt_in(self):
        self.afk.enable()
        run(self.afk.on_outgoing(Event(Msg("hello", out=True), chat_id=500, client=self.client)))
        self.assertTrue(self.afk.active)


class AlertTests(Env):
    def setUp(self):
        super().setUp()
        self.alerts = AlertService(clock=lambda: self.now[0], **self.store())
        self.alerts.update(enabled=True)

    def group(self, text, mentioned=False, mid=1, chat_id=-1001234567890, **kw):
        kw.setdefault("chat", Chat("Dev Group", "devgroup"))
        run(self.alerts.on_new_message(Event(Msg(text, mentioned=mentioned, mid=mid), chat_id=chat_id,
                                             private=False, group=True, client=self.client, **kw)))

    def test_disabled_and_irrelevant_messages_are_ignored(self):
        self.alerts.update(enabled=False)
        self.group("x", mentioned=True)
        self.alerts.update(enabled=True)
        self.group("just chatting")
        self.assertEqual(self.client.sent, [])

    def test_mention_alert_has_context_and_link(self):
        self.group("hey @me can you check?", mentioned=True, mid=42)
        entity, text, kwargs = self.client.sent[0]
        self.assertEqual(entity, "me")
        self.assertIn("ALERT", text)
        self.assertIn("Why : mention", text)
        self.assertIn("Dev Group", text)
        self.assertIn("hey @me can you check?", text)
        self.assertTrue(text.rstrip().endswith("https://t.me/devgroup/42"))
        self.assertIsNone(kwargs["parse_mode"])

    def test_keywords_are_case_insensitive_and_work_for_persian(self):
        self.alerts.add_keyword("Deploy")
        self.alerts.add_keyword("\u0633\u0644\u0627\u0645")
        self.group("we should DEPLOY tonight", mid=1)
        self.group("\u0647\u0645\u06af\u06cc \u0633\u0644\u0627\u0645 \u062f\u0648\u0633\u062a\u0627\u0646", mid=2)
        self.assertEqual(len(self.client.sent), 2)
        self.assertIn("keyword: Deploy", self.client.sent[0][1])

    def test_mentions_switch_ignore_list_dedupe_and_outgoing(self):
        self.alerts.update(mentions=False)
        self.group("hi", mentioned=True)
        self.assertEqual(self.client.sent, [])
        self.alerts.update(mentions=True)
        self.alerts.toggle_ignore(-100777, True)
        self.group("hi", mentioned=True, chat_id=-100777)
        self.assertEqual(self.client.sent, [])
        self.group("one", mentioned=True, mid=5)
        self.group("one", mentioned=True, mid=5)  # the same message twice -> one alert
        self.assertEqual(len(self.client.sent), 1)
        run(self.alerts.on_new_message(Event(Msg("mine", out=True, mentioned=True), private=False, group=True, client=self.client)))
        run(self.alerts.on_new_message(Event(Msg("dm", mentioned=True), private=True, group=False, client=self.client)))
        self.assertEqual(len(self.client.sent), 1)

    def test_rate_limit_protects_saved_messages(self):
        for i in range(30):
            self.group("ping", mentioned=True, mid=100 + i)
        self.assertEqual(len(self.client.sent), 20)
        self.assertEqual(self.alerts.stats["skipped"], 10)
        self.now[0] += 61
        self.group("ping", mentioned=True, mid=999)
        self.assertEqual(len(self.client.sent), 21)

    def test_keyword_management_and_persistence(self):
        self.assertTrue(self.alerts.add_keyword("Deploy"))
        self.assertFalse(self.alerts.add_keyword("deploy"))
        with self.assertRaises(ValueError):
            self.alerts.add_keyword("x" * 61)
        reloaded = AlertService(**self.store())
        self.assertEqual(reloaded.config["keywords"], ["Deploy"])
        self.assertTrue(reloaded.remove_keyword("DEPLOY"))
        self.assertFalse(reloaded.remove_keyword("deploy"))

    def test_links(self):
        self.assertEqual(message_link(Chat(username="pub"), -100123, 9), "https://t.me/pub/9")
        self.assertEqual(message_link(Chat(), -1001234567890, 9), "https://t.me/c/1234567890/9")
        self.assertIsNone(message_link(Chat(), -555, 9))  # basic groups have no link

    def test_custom_destination(self):
        self.alerts.update(dest="-100999")
        self.group("x", mentioned=True)
        self.assertEqual(self.client.sent[0][0], -100999)


class ArchiveToolsTests(Env):
    def setUp(self):
        super().setUp()
        self.guard = MessageLogger(connect=self.conn, cache_dir=os.path.join(self.dir, "c"), clock=lambda: self.now[0],
                                   **self.store())
        media = os.path.join(self.dir, "photo.jpg")
        open(media, "wb").write(b"jpegdata")
        self.guard._archive({"text": "Meeting moved to 18:30", "sender_name": "Sara (@sara)", "chat_title": "Team",
                             "chat_kind": "group", "sender_id": 7, "media_kind": None, "media_path": None,
                             "sent_at": self.now[0]}, "deleted", "a")
        self.guard._archive({"text": "100% real_deal", "sender_name": "Ali", "chat_title": "DM", "chat_kind": "private",
                             "sender_id": 8, "media_kind": "photo", "media_path": media, "sent_at": self.now[0]},
                            "timed", "b")

    def test_search_matches_text_sender_and_chat_and_escapes_wildcards(self):
        self.assertEqual(len(self.guard.search_archive("")), 2)
        self.assertEqual([r["sender_name"] for r in self.guard.search_archive("meeting")], ["Sara (@sara)"])
        self.assertEqual(len(self.guard.search_archive("ali")), 1)
        self.assertEqual(len(self.guard.search_archive("team")), 1)
        self.assertEqual(len(self.guard.search_archive("100%")), 1)   # % is literal, not a wildcard
        self.assertEqual(len(self.guard.search_archive("real_deal")), 1)
        self.assertEqual(len(self.guard.search_archive("%")), 1)
        self.assertEqual(self.guard.search_archive("nothing like this"), [])
        self.assertEqual(len(self.guard.search_archive("", kind="timed")), 1)
        self.assertEqual(self.guard.search_archive("x'; DROP TABLE msglog_archive;--"), [])
        self.assertEqual(self.guard.archive_stats()[0], 2)

    def test_show_resends_text_or_media(self):
        ids = {r["kind"]: r["id"] for r in self.guard.search_archive("")}
        self.assertTrue(run(self.guard.send_archived(self.client, ids["deleted"])))
        self.assertTrue(run(self.guard.send_archived(self.client, ids["timed"])))
        self.assertFalse(run(self.guard.send_archived(self.client, 999)))
        self.assertIn("Meeting moved", self.client.sent[0][1])
        self.assertTrue(self.client.files[0][1].endswith(".jpg"))
        self.assertIn("ARCHIVED MESSAGE", self.client.files[0][2]["caption"])

    def test_exports(self):
        out = os.path.join(self.dir, "out")
        data = json.load(open(self.guard.export_archive(out, "json"), encoding="utf-8"))
        self.assertEqual(len(data), 2)
        self.assertIn("sent_at_iso", data[0])
        csv_path = self.guard.export_archive(out, "csv")
        self.assertIn("Meeting moved to 18:30", open(csv_path, encoding="utf-8").read())
        with zipfile.ZipFile(self.guard.export_archive(out, "zip")) as archive:
            names = archive.namelist()
            self.assertIn("index.json", names)
            self.assertTrue(any(n.startswith("media/") for n in names))
        with self.assertRaises(ValueError):
            self.guard.export_archive(out, "exe")

    def test_export_of_an_empty_archive_is_refused(self):
        self.guard.clear_archive()
        with self.assertRaises(ValueError):
            self.guard.export_archive(os.path.join(self.dir, "o"), "json")


# --------------------------------------------------------------------- commands
def ctx_for(text, client=None, chat_id=-100200, sender_id=4242):
    return support.make_context(text=text, args=text.split()[1:], client=client or Client(), chat_id=chat_id,
                                sender_id=sender_id)


def output(ctx):
    return "\n".join(str(r) for r in ctx.message.replies)


class CommandTests(Env):
    def setUp(self):
        super().setUp()
        from reze.commands import afk as afk_cmds, alerts as alert_cmds, watch as watch_cmds
        self.afk_cmds, self.alert_cmds, self.watch_cmds = afk_cmds, alert_cmds, watch_cmds
        self.afk = afk_cmds.afk
        self.alerts = alert_cmds.alerts
        self.guard = watch_cmds.guard
        self.afk._connect, self.afk._clock = self.conn, lambda: self.now[0]
        self.afk._get, self.afk._set = self.store()["get_setting"], self.store()["set_setting"]
        self.afk._state, self.afk._ready = None, False
        self.alerts._get, self.alerts._set, self.alerts._cfg = self.store()["get_setting"], self.store()["set_setting"], None
        self.guard._connect = self.conn
        self.guard._get_setting, self.guard._set_setting = self.store()["get_setting"], self.store()["set_setting"]
        self.guard._cache_dir, self.guard._cfg, self.guard._ready = os.path.join(self.dir, "c"), None, False

    def tearDown(self):
        super().tearDown()
        # These singletons are shared with other test modules; drop the
        # temporary database wiring so later tests use the real one.
        self.guard._connect = None
        self.guard._get_setting = None
        self.guard._set_setting = None
        self.guard._cache_dir = None
        self.guard._cfg = None
        self.guard._ready = False

    def call(self, handler, text, client=None):
        ctx = ctx_for(text, client)
        run(handler(ctx))
        return output(ctx)

    def test_afk_flow(self):
        self.assertIn("AFK: OFF".upper(), self.call(self.afk_cmds.afk_cmd, ".afk status").upper())
        text = self.call(self.afk_cmds.afk_cmd, ".afk 2h at the gym")
        self.assertIn("YOU ARE AFK", text.upper())
        self.assertIn("2h", text)
        self.assertTrue(self.afk.active)
        self.assertEqual(self.afk.state["reason"], "at the gym")
        self.assertIn("Back at 5".upper(), self.call(self.afk_cmds.afk_cmd, ".afk text Back at 5!").upper())
        self.assertEqual(self.afk.reply_text(), "Back at 5!")
        self.assertIn("ON".upper(), self.call(self.afk_cmds.afk_cmd, ".afk autooff on").upper())
        self.assertIn("Invalid arguments".upper(), self.call(self.afk_cmds.afk_cmd, ".afk autooff maybe").upper())
        self.assertIn("WELCOME BACK".upper(), self.call(self.afk_cmds.back_cmd, ".back").upper().upper())
        self.assertFalse(self.afk.active)
        self.assertIn("Not away".upper(), self.call(self.afk_cmds.back_cmd, ".back").replace("NOT AWAY", "Not away").upper())
    def test_alerts_flow(self):
        self.assertIn("Alerts: OFF".upper(), self.call(self.alert_cmds.alerts_cmd, ".alerts status").upper())
        self.call(self.alert_cmds.alerts_cmd, ".alerts on")
        self.call(self.alert_cmds.alerts_cmd, ".alerts add production down")
        self.assertEqual(self.alerts.config["keywords"], ["production down"])
        self.assertTrue(self.alerts.config["enabled"])
        self.call(self.alert_cmds.alerts_cmd, ".alerts ignore")
        self.assertEqual(self.alerts.config["ignore"], [-100200])
        self.call(self.alert_cmds.alerts_cmd, ".alerts unignore")
        self.assertEqual(self.alerts.config["ignore"], [])
        self.call(self.alert_cmds.alerts_cmd, ".alerts mentions off")
        self.assertFalse(self.alerts.config["mentions"])
        self.call(self.alert_cmds.alerts_cmd, ".alerts dest here")
        self.assertEqual(self.alerts.destination(), -100200)
        self.assertIn("production down".upper(), self.call(self.alert_cmds.alerts_cmd, ".alerts list").upper())
        self.call(self.alert_cmds.alerts_cmd, ".alerts del Production Down")
        self.assertEqual(self.alerts.config["keywords"], [])

    def test_watch_find_show_export(self):
        self.guard._archive({"text": "the secret plan", "sender_name": "Sara", "chat_title": "Team", "chat_kind": "group",
                             "sender_id": 7, "media_kind": None, "media_path": None, "sent_at": self.now[0]}, "deleted", "z")
        client = Client()
        found = self.call(self.watch_cmds.watch_cmd, ".watch find secret", client)
        self.assertIn("the secret plan", found)
        item_id = self.guard.search_archive("secret")[0]["id"]
        self.assertIn("Sent".upper(), self.call(self.watch_cmds.watch_cmd, f".watch show {item_id}", client).upper())
        self.assertIn("the secret plan", client.sent[-1][1])
        self.assertIn("Not found".upper(), self.call(self.watch_cmds.watch_cmd, ".watch show 999", client).replace("NOT FOUND", "Not found").upper())
        self.assertIn("No matches".upper(), self.call(self.watch_cmds.watch_cmd, ".watch find zzz", client).replace("NO MATCHES", "No matches").upper())
        self.assertIn("EXPORT SENT".upper(), self.call(self.watch_cmds.watch_cmd, ".watch export csv", client).upper().upper())
        self.assertTrue(client.files[-1][1].endswith(".csv"))
        self.assertIn("Invalid arguments".upper(), self.call(self.watch_cmds.watch_cmd, ".watch show abc", client).upper())
    def test_new_commands_are_owner_only(self):
        from reze.command_router import router

        for name in ("afk", "back", "alerts"):
            self.assertTrue(router.commands[name].owner_only, name)


if __name__ == "__main__":
    unittest.main()
