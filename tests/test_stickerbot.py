"""Real-sticker backend (Bot API) and the `.sticker` delivery paths."""

import asyncio
import json
import os
import re
import tempfile
import types
import unittest
from unittest.mock import patch

import support
from test_owner_suite_commands import FakeClient, _ensure_telethon, ctx_for, output

_ensure_telethon()

from reze.commands import media as media_cmds  # noqa: E402
from reze.core import http  # noqa: E402
from reze.media import stickerbot  # noqa: E402

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def run(coro):
    return asyncio.run(coro)


class FakeBotApi:
    """Stands in for api.telegram.org: remembers sets and enforces the 'full' rule."""

    def __init__(self, capacity=120, started=True):
        self.sets, self.calls, self.capacity, self.started = {}, [], capacity, started

    async def __call__(self, bot_token, method, fields=None, files=None):
        fields = fields or {}
        self.calls.append((method, fields, files))
        if method == "getMe":
            return {"username": "MyStickerBot"}
        if not self.started and method in ("createNewStickerSet", "addStickerToSet"):
            raise stickerbot.StickerBotError(stickerbot.friendly("Bad Request: user not found"))
        if method == "getStickerSet":
            if fields["name"] not in self.sets:
                raise stickerbot.StickerBotError("Bad Request: STICKERSET_INVALID")
            return {"name": fields["name"]}
        if method == "createNewStickerSet":
            self.sets[fields["name"]] = 1
            return True
        if method == "addStickerToSet":
            if self.sets[fields["name"]] >= self.capacity:
                raise stickerbot.StickerBotError(stickerbot.friendly("Bad Request: STICKERS_TOO_MUCH"))
            self.sets[fields["name"]] += 1
            return True
        raise AssertionError(method)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.file = tempfile.NamedTemporaryFile(suffix=".webp", delete=False)
        self.file.write(b"RIFFwebp")
        self.file.close()
        self.index = {"s": 1, "v": 1}
        self.patches = [
            patch.dict(os.environ, {"REZE_STICKER_BOT_TOKEN": "123:secret-token"}),
            patch.object(stickerbot, "_get_index", lambda video: self.index["v" if video else "s"]),
            patch.object(stickerbot, "_set_index", lambda video, i: self.index.__setitem__("v" if video else "s", i)),
        ]
        for p in self.patches:
            p.start()
        stickerbot._username_cache.clear()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        os.unlink(self.file.name)

    def test_set_names_are_valid_for_telegram(self):
        name = stickerbot.short_name(4242, False, 1, "My_Sticker_Bot")
        self.assertRegex(name, NAME_RE)
        self.assertTrue(name.endswith("_by_my_sticker_bot"))
        self.assertNotIn("__", name)
        self.assertLessEqual(len(stickerbot.short_name(10**15, True, 99, "a" * 40)), 64)
        self.assertNotEqual(stickerbot.short_name(1, False, 1, "b"), stickerbot.short_name(1, True, 1, "b"))

    def test_first_sticker_creates_the_pack_and_later_ones_are_added(self):
        api = FakeBotApi()
        with patch.object(stickerbot, "api", api):
            first = run(stickerbot.add_to_personal_pack(4242, self.file.name, "\U0001F338", False))
            second = run(stickerbot.add_to_personal_pack(4242, self.file.name, "\U0001F338", False))
        self.assertEqual(first, second)
        self.assertTrue(first.endswith("_by_mystickerbot"))
        methods = [c[0] for c in api.calls]
        self.assertEqual(methods.count("createNewStickerSet"), 1)
        self.assertEqual(methods.count("addStickerToSet"), 1)
        create = next(c for c in api.calls if c[0] == "createNewStickerSet")
        self.assertEqual(create[1]["user_id"], "4242")
        sticker = json.loads(create[1]["stickers"])[0]
        self.assertEqual((sticker["format"], sticker["sticker"]), ("static", "attach://file"))
        self.assertEqual(create[2]["file"][2], "image/webp")
        self.assertEqual(api.sets[first], 2)

    def test_video_stickers_use_a_separate_set_and_format(self):
        api = FakeBotApi()
        with patch.object(stickerbot, "api", api):
            image = run(stickerbot.add_to_personal_pack(4242, self.file.name, "x", False))
            video = run(stickerbot.add_to_personal_pack(4242, self.file.name, "x", True))
        self.assertNotEqual(image, video)
        create_video = [c for c in api.calls if c[0] == "createNewStickerSet"][1]
        self.assertEqual(json.loads(create_video[1]["stickers"])[0]["format"], "video")
        self.assertEqual(create_video[2]["file"][2], "video/webm")

    def test_full_set_rolls_over_to_the_next_one(self):
        api = FakeBotApi(capacity=1)
        with patch.object(stickerbot, "api", api):
            first = run(stickerbot.add_to_personal_pack(4242, self.file.name, "x", False))
            second = run(stickerbot.add_to_personal_pack(4242, self.file.name, "x", False))
        self.assertNotEqual(first, second)
        self.assertIn("_s2_", second)
        self.assertEqual(self.index["s"], 2)  # remembered for the next sticker

    def test_bot_not_started_gives_an_actionable_message(self):
        with patch.object(stickerbot, "api", FakeBotApi(started=False)):
            with self.assertRaises(stickerbot.StickerBotError) as caught:
                run(stickerbot.add_to_personal_pack(4242, self.file.name, "x", False))
        self.assertIn("press Start", str(caught.exception))

    def test_missing_token(self):
        with patch.dict(os.environ, {"REZE_STICKER_BOT_TOKEN": ""}):
            with self.assertRaises(stickerbot.StickerBotError):
                run(stickerbot.add_to_personal_pack(4242, self.file.name, "x", False))

    def test_named_pack_helpers(self):
        api = FakeBotApi()
        with patch.object(stickerbot, "api", api):
            created = run(stickerbot.create_named_pack(4242, "My Pack", self.file.name, "x"))
            self.assertRegex(created, NAME_RE)
            added = run(stickerbot.add_to_named_pack(4242, created.replace("_by_mystickerbot", ""), self.file.name, "x"))
        self.assertEqual(added, created)
        self.assertEqual(api.sets[created], 2)

    def test_token_never_appears_in_error_text(self):
        self.assertNotIn("secret-token", stickerbot.friendly("Unauthorized"))

    def test_multipart_with_files(self):
        body, ctype = http.multipart_files({"name": "x"}, {"file": ('a"b.webp', b"BYTES", "image/webp")})
        self.assertIn(b'name="name"', body)
        self.assertIn(b"Content-Type: image/webp", body)
        self.assertIn(b"BYTES", body)
        self.assertNotIn(b'a"b', body)
        self.assertIn(ctype.split("boundary=")[1].encode(), body)

    def test_api_host_is_locked(self):
        with self.assertRaises(http.HttpError):
            run(http.post_form("https://evil.com/bot123/getMe", {}, allowed=["api.telegram.org"]))


class StickerCommandDeliveryTests(unittest.TestCase):
    """Run `.sticker`'s delivery step without converting anything."""

    def capture_deliver(self):
        captured = {}

        async def fake_run_job(ctx, kind, worker, **kwargs):
            captured.update(kwargs)
            captured["worker"] = worker

        client = FakeClient()
        client.get_me = lambda: _async(types.SimpleNamespace(id=4242))
        ctx = ctx_for(".sticker \U0001F600", client=client)
        with patch.object(media_cmds, "_run_job", fake_run_job):
            run(media_cmds.sticker_cmd(ctx))
        return captured["deliver"], ctx, client

    def test_with_a_bot_the_real_sticker_document_is_sent(self):
        deliver, ctx, client = self.capture_deliver()
        document = object()

        async def fake_add(owner_id, path, emoji, video):
            self.seen = (owner_id, path, emoji, video)
            return "reze_4242_s1_by_mystickerbot"

        async def fake_fetch(client_, name):
            return document

        with patch.dict(os.environ, {"REZE_STICKER_BOT_TOKEN": "1:x"}), \
                patch.object(stickerbot, "add_to_personal_pack", fake_add), \
                patch.object(stickerbot, "fetch_last_sticker", fake_fetch):
            run(deliver(ctx, "/tmp/sticker.webm"))
        self.assertEqual(self.seen, (4242, "/tmp/sticker.webm", "\U0001F600", True))
        self.assertIs(client.sent_files[-1]["file"], document)  # a Telegram document, not a local file
        self.assertIn("https://t.me/addstickers/reze_4242_s1_by_mystickerbot", ctx.message.replies)
        self.assertIn("sticker added", output(ctx).lower())

    def test_bot_errors_are_reported(self):
        deliver, ctx, client = self.capture_deliver()

        async def failing(owner_id, path, emoji, video):
            raise stickerbot.StickerBotError("Open your sticker bot in Telegram and press Start once, then try again.")

        with patch.dict(os.environ, {"REZE_STICKER_BOT_TOKEN": "1:x"}), \
                patch.object(stickerbot, "add_to_personal_pack", failing):
            run(deliver(ctx, "/tmp/sticker.webp"))
        self.assertEqual(client.sent_files, [])
        self.assertIn("press start", output(ctx).lower())

    def test_without_a_bot_the_fallback_sets_sticker_attributes_and_explains(self):
        deliver, ctx, client = self.capture_deliver()
        with patch.dict(os.environ, {"REZE_STICKER_BOT_TOKEN": ""}):
            run(deliver(ctx, "/tmp/sticker.webp"))
        sent = client.sent_files[-1]
        self.assertEqual(sent["file"], "/tmp/sticker.webp")
        self.assertFalse(sent["force_document"])
        kinds = [type(a).__name__ for a in sent["attributes"]]
        self.assertIn("DocumentAttributeSticker", kinds)
        self.assertEqual(sent["mime_type"], "image/webp")
        self.assertIn("REZE_STICKER_BOT_TOKEN".lower(), output(ctx).lower())


async def _async(value):
    return value


if __name__ == "__main__":
    unittest.main()
