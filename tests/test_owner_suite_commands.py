"""Command-level tests: owner gate, owner suite, group admin, fun, tools and downloads."""

import asyncio
import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import support


def _ensure_telethon():
    """Real Telethon is a runtime dependency; only fake the bits used here when it is not installed."""
    try:
        import telethon  # noqa: F401
        return
    except ImportError:
        pass

    def module(name, **attrs):
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        sys.modules[name] = mod
        return mod

    class FloodWaitError(Exception):
        def __init__(self, request=None, capture=0):
            super().__init__(f"wait {capture}")
            self.seconds = capture

    class Req:
        def __init__(self, *args, **kwargs):
            self.args, self.kwargs = args, kwargs

    def ns(**names):
        return types.SimpleNamespace(**names)

    functions = ns(
        contacts=ns(BlockRequest=type("BlockRequest", (Req,), {}), UnblockRequest=type("UnblockRequest", (Req,), {})),
        messages=ns(EditChatAboutRequest=type("EditChatAboutRequest", (Req,), {}),
                    EditChatTitleRequest=type("EditChatTitleRequest", (Req,), {}),
                    ExportChatInviteRequest=type("ExportChatInviteRequest", (Req,), {}),
                    ImportChatInviteRequest=type("ImportChatInviteRequest", (Req,), {})),
        channels=ns(EditTitleRequest=type("EditTitleRequest", (Req,), {}),
                    JoinChannelRequest=type("JoinChannelRequest", (Req,), {})),
    )
    types_mod = module("telethon.tl.types",
                       Channel=type("Channel", (), {}),
                       DocumentAttributeSticker=type("DocumentAttributeSticker", (Req,), {}),
                       InputStickerSetEmpty=type("InputStickerSetEmpty", (Req,), {}),
                       DocumentAttributeAudio=type("DocumentAttributeAudio", (Req,), {}),
                       DocumentAttributeVideo=type("DocumentAttributeVideo", (Req,), {}))
    tl = module("telethon.tl", functions=functions, types=types_mod)
    module("telethon", errors=module("telethon.errors", FloodWaitError=FloodWaitError), tl=tl)
    sys.modules["telethon.tl.functions"] = functions


_ensure_telethon()

from reze.commands import downloads, fun, groupadmin, owner, tools  # noqa: E402
from reze.command_router import CommandRouter  # noqa: E402
from reze.exceptions import MediaError  # noqa: E402
from reze.games.tictactoe import tictactoe_manager  # noqa: E402
from reze.media import downloaders as dl  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class FakeUser:
    def __init__(self, uid, first="Sara", bot=False, deleted=False):
        self.id, self.first_name, self.last_name, self.username = uid, first, None, None
        self.bot, self.deleted = bot, deleted


class FakeDialog:
    def __init__(self, did, kind, entity=None):
        self.id, self.entity = did, entity
        self.is_user, self.is_group, self.is_channel = kind == "user", kind == "group", kind == "channel"


class FakeClient(support.DummyClient):
    """DummyClient plus the Telethon calls used by the new commands."""

    def __init__(self, dialogs=(), members=()):
        super().__init__()
        self.dialogs, self.members = list(dialogs), list(members)
        self.admin_calls, self.send_log = [], []

    async def iter_dialogs(self, limit=None):
        for dialog in self.dialogs[:limit]:
            yield dialog

    async def get_participants(self, chat_id, limit=None):
        return self.members[:limit]

    async def edit_admin(self, chat, user, **kwargs):
        self.admin_calls.append((chat, user, kwargs))

    async def send_message(self, chat_id, text, **kwargs):
        self.send_log.append((chat_id, text, kwargs))
        return await super().send_message(chat_id, text, **kwargs)

    async def get_messages(self, chat_id, ids=None):
        return support.DummyMessage(text="copied text", message_id=ids)

    async def delete_dialog(self, chat_id):
        self.requests.append(("leave", chat_id))

    async def __call__(self, request):
        self.requests.append(request)
        return types.SimpleNamespace(link="https://t.me/+NewLink12345")


def ctx_for(text, client=None, reply=None, chat_id=-100200, sender_id=4242):
    args = text.split()[1:]
    ctx = support.make_context(text=text, args=args, client=client or FakeClient(), reply=reply,
                               chat_id=chat_id, sender_id=sender_id)
    return ctx


def output(ctx):
    return "\n".join(str(r) for r in ctx.message.replies)


class OwnerGateTests(unittest.TestCase):
    """Strangers typing '.something' must get no reaction at all."""

    def setUp(self):
        self.router = CommandRouter(default_prefix=".")
        self.calls = []

        @self.router.register(name="ping")
        async def ping(ctx):
            self.calls.append(ctx.sender_id)
            await ctx.reply("pong")

    def dispatch(self, text, **kwargs):
        message = support.DummyMessage(text=text, **kwargs)
        run(self.router.handle_message(message, support.DummyClient()))
        return message

    def test_stranger_gets_nothing_for_known_unknown_and_owner_commands(self):
        for text in (".ping", ".nonsense", ".help", ".", ".   ", ".exec rm -rf /"):
            message = self.dispatch(text, sender_id=777)
            self.assertEqual(message.replies, [], text)
        self.assertEqual(self.calls, [])

    def test_owner_by_id_and_outgoing_messages_work(self):
        self.assertEqual(self.dispatch(".ping", sender_id=4242).replies, ["pong"])
        self.assertEqual(self.dispatch(".ping", sender_id=0, out=True).replies, ["pong"])
        self.assertIn("unknown command", self.dispatch(".nonsense", sender_id=4242).replies[0].lower())

    def test_public_commands_flag_restores_old_behaviour(self):
        with patch.dict(os.environ, {"REZE_PUBLIC_COMMANDS": "true"}):
            self.assertEqual(self.dispatch(".ping", sender_id=777).replies, ["pong"])

    def test_is_authorized_helper(self):
        stranger = support.DummyMessage(text=".x", sender_id=5)
        self.assertFalse(self.router.is_authorized(stranger))
        self.assertTrue(self.router.is_authorized(support.DummyMessage(text=".x", sender_id=4242)))


class OwnerSuiteTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.env_path = os.path.join(self.dir, ".env")
        open(self.env_path, "w").write("REZE_THEME=CYBER\n")
        self.patch = patch.dict(os.environ, {"REZE_ENV_FILE": self.env_path})
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        for key in ("REZE_ENABLE_EXEC", "REZE_TEST_SECRET_KEY", "REZE_THEME", "REZE_AI_API_KEY"):
            os.environ.pop(key, None)
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_setvar_getvar_delvar(self):
        ctx = ctx_for(".setvar REZE_THEME GHOST")
        run(owner.setvar_cmd(ctx))
        self.assertIn("REZE_THEME = GHOST".lower(), output(ctx).lower())
        self.assertIn("REZE_THEME=GHOST", open(self.env_path).read())
        self.assertEqual(os.environ["REZE_THEME"], "GHOST")

        ctx = ctx_for(".getvar REZE_THEME")
        run(owner.getvar_cmd(ctx))
        self.assertIn("GHOST".lower(), output(ctx).lower())

        ctx = ctx_for(".delvar REZE_THEME")
        run(owner.delvar_cmd(ctx))
        self.assertNotIn("REZE_THEME", open(self.env_path).read())

    def test_secret_values_are_masked_and_the_command_message_is_deleted(self):
        ctx = ctx_for(".setvar REZE_AI_API_KEY sk-very-secret-value-1234")
        run(owner.setvar_cmd(ctx))
        self.assertTrue(ctx.message.deleted)
        self.assertNotIn("very-secret".lower(), output(ctx).lower())
        ctx = ctx_for(".getvar REZE_AI_API_KEY")
        run(owner.getvar_cmd(ctx))
        self.assertNotIn("very-secret".lower(), output(ctx).lower())
        self.assertIn("1234".lower(), output(ctx).lower())
        ctx = ctx_for(".getvar")
        run(owner.getvar_cmd(ctx))
        self.assertNotIn("very-secret".lower(), output(ctx).lower())

    def test_non_reze_variables_are_rejected(self):
        ctx = ctx_for(".setvar PATH /tmp")
        run(owner.setvar_cmd(ctx))
        self.assertIn("Invalid variable".lower(), output(ctx).lower())
        self.assertNotIn("PATH", open(self.env_path).read())

    @unittest.skipIf(os.name == "nt", "POSIX shell")
    def test_exec_is_disabled_by_default_and_runs_when_enabled(self):
        ctx = ctx_for(".exec echo hello-from-exec")
        run(owner.exec_cmd(ctx))
        self.assertIn("disabled".lower(), output(ctx).lower())
        self.assertNotIn("hello-from-exec", output(ctx).replace("echo hello-from-exec", ""))

        os.environ["REZE_ENABLE_EXEC"] = "true"
        ctx = ctx_for(".exec echo hello-from-exec && exit 2")
        run(owner.exec_cmd(ctx))
        text = output(ctx)
        self.assertIn("hello-from-exec", text)
        self.assertIn("exit 2", text)

    def test_block_and_unblock(self):
        client = FakeClient()
        ctx = ctx_for(".block 555", client=client)
        run(owner.block_cmd(ctx))
        self.assertIn("blocked", output(ctx).lower())
        self.assertEqual(type(client.requests[-1]).__name__, "BlockRequest")
        ctx = ctx_for(".unblock 555", client=client)
        run(owner.unblock_cmd(ctx))
        self.assertEqual(type(client.requests[-1]).__name__, "UnblockRequest")

    def test_broadcast_needs_a_confirmation_and_skips_bots_channels_and_self(self):
        dialogs = [
            FakeDialog(4242, "user", FakeUser(4242)),              # Saved Messages (self)
            FakeDialog(11, "user", FakeUser(11)),
            FakeDialog(12, "user", FakeUser(12, bot=True)),         # bot
            FakeDialog(13, "user", FakeUser(13, deleted=True)),     # deleted account
            FakeDialog(-100, "group"),
            FakeDialog(-200, "channel"),                            # broadcast channel
        ]
        client = FakeClient(dialogs=dialogs)

        async def scenario():
            ctx = ctx_for(".broadcast groups Maintenance tonight", client=client)
            await owner.broadcast_cmd(ctx)
            first = output(ctx)
            self.assertIn("Recipients: 1", first)
            self.assertEqual(client.send_log, [])  # nothing is sent before confirmation
            token = first.split("confirm ")[-1].split()[0]
            confirm = ctx_for(f".broadcast confirm {token}", client=client)
            with patch.object(owner, "_sleep", lambda *_a, **_k: asyncio.sleep(0)):
                await owner.broadcast_cmd(confirm)
            return output(confirm), token

        text, token = run(scenario())
        sent = [entry for entry in client.send_log if entry[0] == -100]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][1], "Maintenance tonight")
        self.assertIn("Sent: 1", text)
        # the code is single use
        again = ctx_for(f".broadcast confirm {token}", client=client)
        run(owner.broadcast_cmd(again))
        self.assertIn("Not confirmed".lower(), output(again).lower())

    def test_broadcast_users_scope_and_wrong_user_code(self):
        client = FakeClient(dialogs=[FakeDialog(11, "user", FakeUser(11)), FakeDialog(12, "user", FakeUser(12, bot=True))])
        ctx = ctx_for(".bc users hi", client=client)
        run(owner.broadcast_cmd(ctx))
        token = output(ctx).split("confirm ")[-1].split()[0]
        stranger = ctx_for(f".bc confirm {token}", client=client, sender_id=9)
        run(owner.broadcast_cmd(stranger))
        self.assertIn("Not confirmed".lower(), output(stranger).lower())
        self.assertEqual(client.send_log, [])

    def test_broadcast_validation(self):
        ctx = ctx_for(".broadcast everyone hello")
        run(owner.broadcast_cmd(ctx))
        self.assertIn("Invalid arguments".lower(), output(ctx).lower())
        ctx = ctx_for(".broadcast groups " + "x" * 500)
        run(owner.broadcast_cmd(ctx))
        self.assertIn("too long", output(ctx).lower())

    def test_update_outside_a_git_checkout(self):
        with patch.object(owner, "REPO_ROOT", self.dir):
            ctx = ctx_for(".update")
            run(owner.update_cmd(ctx))
        self.assertIn("Not a git checkout".lower(), output(ctx).lower())

    def test_botinfo_and_owner_render(self):
        for handler, text in ((owner.botinfo_cmd, ".botinfo"), (owner.owner_cmd, ".owner")):
            ctx = ctx_for(text)
            run(handler(ctx))
            self.assertTrue(output(ctx))
        ctx = ctx_for(".botinfo")
        run(owner.botinfo_cmd(ctx))
        self.assertIn(".exec: disabled".lower(), output(ctx).lower())


class GroupAdminTests(unittest.TestCase):
    def test_promote_demote(self):
        client = FakeClient()
        ctx = ctx_for(".promote 555 Moderator", client=client)
        run(groupadmin.promote_cmd(ctx))
        chat, user, kwargs = client.admin_calls[-1]
        self.assertEqual((chat, user), (-100200, 555))
        self.assertTrue(kwargs["is_admin"] and kwargs["ban_users"])
        self.assertFalse(kwargs["add_admins"])
        self.assertEqual(kwargs["title"], "Moderator")

        ctx = ctx_for(".promote 555 full", client=client)
        run(groupadmin.promote_cmd(ctx))
        self.assertTrue(client.admin_calls[-1][2]["add_admins"])

        ctx = ctx_for(".demote 555", client=client)
        run(groupadmin.demote_cmd(ctx))
        self.assertFalse(client.admin_calls[-1][2]["is_admin"])

    def test_hidetag_sends_hidden_mentions_in_chunks_and_skips_bots(self):
        members = [FakeUser(i) for i in range(1, 31)] + [FakeUser(99, bot=True)]
        client = FakeClient(members=members)
        ctx = ctx_for(".hidetag Meeting now", client=client)
        run(groupadmin.hidetag_cmd(ctx))
        self.assertTrue(ctx.message.deleted)
        self.assertEqual(len(client.send_log), 2)  # 30 humans -> chunks of 25 + 5
        self.assertTrue(all("Meeting now" in entry[1] for entry in client.send_log))
        self.assertNotIn("id=99)", "".join(entry[1] for entry in client.send_log))
        self.assertEqual(client.send_log[0][2]["parse_mode"], "md")

    def test_setdesc_validation_and_invite(self):
        client = FakeClient()
        ctx = ctx_for(".setdesc " + "x" * 300, client=client)
        run(groupadmin.setdesc_cmd(ctx))
        self.assertIn("Too long".lower(), output(ctx).lower())
        ctx = ctx_for(".invite", client=client)
        run(groupadmin.invite_cmd(ctx))
        self.assertIn("https://t.me/+NewLink12345".lower(), output(ctx).lower())

    def test_join_and_leave_confirmation(self):
        client = FakeClient()
        ctx = ctx_for(".join https://t.me/+AbCdEfGh123", client=client)
        run(groupadmin.join_cmd(ctx))
        self.assertEqual(type(client.requests[-1]).__name__, "ImportChatInviteRequest")
        ctx = ctx_for(".join nonsense", client=client)
        run(groupadmin.join_cmd(ctx))
        self.assertIn("Invalid arguments".lower(), output(ctx).lower())

        ctx = ctx_for(".leave", client=client)
        run(groupadmin.leave_cmd(ctx))
        self.assertNotIn(("leave", -100200), client.requests)  # not before confirmation
        token = output(ctx).split("confirm ")[-1].split()[0]
        ctx = ctx_for(f".leave confirm {token}", client=client)
        run(groupadmin.leave_cmd(ctx))
        self.assertIn(("leave", -100200), client.requests)
        private = ctx_for(".leave", client=client, chat_id=123)
        run(groupadmin.leave_cmd(private))
        self.assertIn("Groups only".lower(), output(private).lower())


class FunAndToolsTests(unittest.TestCase):
    def test_fun_commands_render(self):
        for handler, text in ((fun.quote_cmd, ".quote"), (fun.joke_cmd, ".joke"),
                              (fun.truth_cmd, ".truth"), (fun.dare_cmd, ".dare")):
            ctx = ctx_for(text)
            run(handler(ctx))
            self.assertIn("║".lower(), output(ctx).lower())

    def test_ship_and_roast(self):
        ctx = ctx_for(".ship Ali Sara")
        run(fun.ship_cmd(ctx))
        percent = fun.ship_percent("Ali", "Sara")
        self.assertIn(f"{percent}%".lower(), output(ctx).lower())
        ctx = ctx_for(".ship Ali")
        run(fun.ship_cmd(ctx))
        self.assertIn("Invalid arguments".lower(), output(ctx).lower())
        ctx = ctx_for(".roast Bob")
        run(fun.roast_cmd(ctx))
        self.assertIn("Bob".lower(), output(ctx).lower())

    def test_tictactoe_command_starts_and_stops(self):
        tictactoe_manager.games.clear()
        ctx = ctx_for(".tictactoe")
        run(fun.tictactoe_cmd(ctx))
        game = tictactoe_manager.get(-100200)
        self.assertIsNotNone(game)
        self.assertTrue(game.vs_ai)
        again = ctx_for(".tictactoe")
        run(fun.tictactoe_cmd(again))
        self.assertIn("already running".lower(), output(again).lower())
        stop = ctx_for(".tictactoe stop")
        run(fun.tictactoe_cmd(stop))
        self.assertIsNone(tictactoe_manager.get(-100200))

    def test_weather_with_mocked_network(self):
        async def fake_get_json(url, params=None, **kwargs):
            if "geocoding" in url:
                return {"results": [{"name": "Tehran", "admin1": "Tehran", "country": "Iran",
                                     "latitude": 35.7, "longitude": 51.4}]}
            return {"current": {"temperature_2m": 18.5, "apparent_temperature": 17, "relative_humidity_2m": 40,
                                "wind_speed_10m": 9, "weather_code": 2},
                    "daily": {"temperature_2m_max": [24], "temperature_2m_min": [12], "precipitation_probability_max": [10]}}

        with patch.object(tools.http, "get_json", fake_get_json):
            ctx = ctx_for(".weather Tehran")
            run(tools.weather_cmd(ctx))
        text = output(ctx)
        self.assertIn("Partly cloudy", text)
        self.assertIn("18.5", text)

        async def empty(url, params=None, **kwargs):
            return {}

        with patch.object(tools.http, "get_json", empty):
            ctx = ctx_for(".weather Nowhereville")
            run(tools.weather_cmd(ctx))
        self.assertIn("City not found".lower(), output(ctx).lower())

    def test_github_with_mocked_network(self):
        async def fake(url, params=None, **kwargs):
            return {"full_name": "UnchartedAli/Reze", "description": "Userbot", "stargazers_count": 7,
                    "forks_count": 1, "open_issues_count": 0, "language": "Python",
                    "license": {"spdx_id": "MIT"}, "pushed_at": "2026-10-28T10:00:00Z",
                    "html_url": "https://github.com/UnchartedAli/Reze"}

        with patch.object(tools.http, "get_json", fake):
            ctx = ctx_for(".github UnchartedAli/Reze")
            run(tools.github_cmd(ctx))
        self.assertIn("Stars: 7".lower(), output(ctx).lower())
        ctx = ctx_for(".github ../etc/passwd")
        run(tools.github_cmd(ctx))
        self.assertIn("Invalid arguments".lower(), output(ctx).lower())


class DownloadCommandTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def fake_fetch(self, kind="video"):
        async def fetch(workspace, target, mode, quality=720):
            self.seen = (target, mode, quality)
            path = os.path.join(workspace.directory, "out.mp4" if kind == "video" else "out.mp3")
            with open(path, "wb") as handle:
                handle.write(b"data")
            return dl.Fetched(path=path, kind=kind, title="Title", uploader="Band", duration=125, width=640, height=360)
        return fetch

    def test_yt_sends_video_with_metadata(self):
        client = FakeClient()
        with patch.object(downloads, "_fetch_ytdlp", self.fake_fetch("video")):
            ctx = ctx_for(".yt lofi hip hop", client=client)
            run(downloads.yt_cmd(ctx))
        self.assertEqual(self.seen, ("lofi hip hop", "video", 720))
        sent = client.sent_files[-1]
        self.assertTrue(sent["file"].endswith(".mp4"))
        self.assertIn("Title - Band", sent["caption"])
        self.assertIn("[2:05]", sent["caption"])
        self.assertTrue(sent["supports_streaming"])

    def test_quality_audio_and_song(self):
        client = FakeClient()
        with patch.object(downloads, "_fetch_ytdlp", self.fake_fetch("video")):
            run(downloads.ytv_cmd(ctx_for(".ytv 360 cats", client=client)))
        self.assertEqual(self.seen, ("cats", "video", 360))
        with patch.object(downloads, "_fetch_ytdlp", self.fake_fetch("audio")):
            run(downloads.yta_cmd(ctx_for(".yta daft punk", client=client)))
            self.assertEqual(self.seen[1], "audio")
            run(downloads.song_cmd(ctx_for(".song Bohemian Rhapsody", client=client)))
            self.assertEqual(self.seen[0], "Bohemian Rhapsody")
        self.assertFalse(client.sent_files[-1]["supports_streaming"])

    def test_wrong_site_links_are_refused_without_downloading(self):
        client = FakeClient()
        called = []

        async def never(*args, **kwargs):
            called.append(1)

        with patch.object(downloads, "_fetch_ytdlp", never):
            for handler, text in ((downloads.yt_cmd, ".yt https://evil.com/watch?v=1"),
                                  (downloads.instagram_cmd, ".ig https://youtube.com/watch?v=1"),
                                  (downloads.tiktok_cmd, ".tt https://tiktok.com.evil.com/x"),
                                  (downloads.facebook_cmd, ".fb file:///etc/passwd"),
                                  (downloads.mediafire_cmd, ".mediafire https://example.com/file"),
                                  (downloads.pinterest_cmd, ".pinterest https://example.com/pin")):
                ctx = ctx_for(text, client=client)
                run(handler(ctx))
                self.assertTrue(output(ctx), text)
        self.assertEqual(called, [])
        self.assertEqual(client.sent_files, [])

    def test_failures_are_reported_in_the_progress_message(self):
        async def broken(workspace, target, mode, quality=720):
            raise MediaError("The video is unavailable (deleted, private or region-locked).")

        with patch.object(downloads, "_fetch_ytdlp", broken):
            ctx = ctx_for(".yt https://youtu.be/abc")
            run(downloads.yt_cmd(ctx))
        edited = " ".join(ctx.message.edits) + output(ctx)
        self.assertIn("unavailable", edited)


class StickerVideoTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_video_sticker_meets_telegram_limits(self):
        import subprocess
        from reze.media import ffmpeg

        directory = tempfile.mkdtemp()
        try:
            source = os.path.join(directory, "in.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                            "testsrc=duration=6:size=640x360:rate=30", "-pix_fmt", "yuv420p", source], check=True)
            out = os.path.join(directory, "sticker.webm")
            ffmpeg.to_video_sticker(source, out)
            self.assertLessEqual(os.path.getsize(out), 256 * 1024)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                 "stream=codec_name,width,height:format=duration", "-of", "default=nw=1", out],
                capture_output=True, text=True, check=True).stdout
            self.assertIn("codec_name=vp9", probe)
            self.assertIn("width=512", probe)
            duration = float([l for l in probe.splitlines() if l.startswith("duration=")][0].split("=")[1])
            self.assertLessEqual(duration, 3.05)
        finally:
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
