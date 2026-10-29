"""Pure-logic tests for the owner suite, downloaders, games and helpers (no Telegram, no network)."""

import asyncio
import os
import shutil
import sys
import tempfile
import types
import unittest

from reze.core import envfile, http, shell
from reze.games.tictactoe import TicTacToeManager, best_move, is_full, winner
from reze.media import downloaders as dl
from reze.exceptions import MediaError, MissingDependencyError


def run(coro):
    return asyncio.run(coro)


class EnvFileTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, ".env")
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("# comment\nREZE_THEME=CYBER\nREZE_AI_API_KEY=sk-secret-12345678\nOTHER=keep\n")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_only_reze_names_are_accepted(self):
        for bad in ("PATH", "LD_PRELOAD", "reze_x", "REZE_", "REZE_A B", "REZE_A=1"):
            with self.assertRaises(envfile.EnvFileError, msg=bad):
                envfile.valid_key(bad)
        self.assertEqual(envfile.valid_key("reze_theme"), "REZE_THEME")

    def test_set_replaces_adds_and_preserves_everything_else(self):
        self.assertEqual(envfile.set_value(self.path, "REZE_THEME", "GHOST"), ("REZE_THEME", True))
        self.assertEqual(envfile.set_value(self.path, "REZE_LOG_LEVEL", "DEBUG"), ("REZE_LOG_LEVEL", False))
        text = open(self.path, encoding="utf-8").read()
        self.assertIn("# comment", text)
        self.assertIn("OTHER=keep", text)
        self.assertEqual(envfile.read(self.path)["REZE_THEME"], "GHOST")
        self.assertEqual(text.count("REZE_THEME="), 1)

    def test_quoting_round_trip(self):
        envfile.set_value(self.path, "REZE_PANEL_USERNAME", 'a b "c" #d')
        self.assertEqual(envfile.read(self.path)["REZE_PANEL_USERNAME"], 'a b "c" #d')

    def test_values_cannot_inject_new_lines(self):
        with self.assertRaises(envfile.EnvFileError):
            envfile.set_value(self.path, "REZE_THEME", "X\nREZE_OWNER_ID=1")
        self.assertNotIn("REZE_OWNER_ID", open(self.path).read())

    def test_delete(self):
        self.assertTrue(envfile.delete_value(self.path, "REZE_THEME"))
        self.assertFalse(envfile.delete_value(self.path, "REZE_THEME"))
        self.assertNotIn("REZE_THEME", envfile.read(self.path))
        self.assertIn("OTHER=keep", open(self.path).read())

    def test_secrets_are_masked_in_listings(self):
        shown = dict(envfile.listing(self.path))
        self.assertEqual(shown["REZE_THEME"], "CYBER")
        self.assertNotIn("secret", shown["REZE_AI_API_KEY"])
        self.assertTrue(shown["REZE_AI_API_KEY"].endswith("5678"))
        self.assertEqual(envfile.mask("short"), "*" * 8)

    def test_file_permissions_are_private(self):
        envfile.set_value(self.path, "REZE_THEME", "X")
        if os.name != "nt":
            self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)


class ShellTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX shell")
    def test_runs_and_captures_output_and_exit_code(self):
        result = run(shell.run("echo hi; echo err 1>&2; exit 3", timeout=10))
        self.assertEqual(result.code, 3)
        self.assertIn("hi", result.output)
        self.assertIn("err", result.output)

    @unittest.skipIf(os.name == "nt", "POSIX shell")
    def test_timeout_kills_the_command(self):
        result = run(shell.run("sleep 30", timeout=0.5))
        self.assertTrue(result.timed_out)
        self.assertIsNone(result.code)
        self.assertLess(result.elapsed, 10)

    @unittest.skipIf(os.name == "nt", "POSIX shell")
    def test_secrets_never_reach_the_child_environment(self):
        os.environ["REZE_API_HASH"] = "topsecret-hash"
        os.environ["REZE_SESSION_STRING"] = "topsecret-session"
        os.environ["REZE_THEME"] = "visible"
        try:
            result = run(shell.run("env", timeout=10))
        finally:
            for key in ("REZE_API_HASH", "REZE_SESSION_STRING", "REZE_THEME"):
                os.environ.pop(key, None)
        self.assertNotIn("topsecret", result.output)
        self.assertIn("REZE_THEME=visible", result.output)

    def test_output_is_truncated(self):
        text = shell.truncate("x" * 10000, 1000)
        self.assertLess(len(text), 1100)
        self.assertIn("omitted", text)


class HttpTests(unittest.TestCase):
    def test_only_https_and_allowed_hosts(self):
        self.assertTrue(http.host_allowed("https://api.github.com/x", ["api.github.com"]))
        self.assertTrue(http.host_allowed("https://www.mediafire.com/f", ["mediafire.com"]))
        self.assertFalse(http.host_allowed("http://api.github.com/x", ["api.github.com"]))
        self.assertFalse(http.host_allowed("https://evil.com/?u=api.github.com", ["api.github.com"]))
        self.assertFalse(http.host_allowed("https://api.github.com.evil.com/", ["api.github.com"]))
        self.assertFalse(http.host_allowed("https://127.0.0.1/", ["api.github.com"]))
        self.assertFalse(http.host_allowed("file:///etc/passwd", None))

    def test_refuses_disallowed_urls_before_any_network_call(self):
        with self.assertRaises(http.HttpError):
            run(http.get_text("https://example.com/", allowed=["github.com"]))

    def test_multipart_body(self):
        body, ctype = http.multipart({"reqtype": "fileupload"}, "fileToUpload", 'a"b.png', b"BYTES")
        boundary = ctype.split("boundary=")[1]
        self.assertIn(f"--{boundary}".encode(), body)
        self.assertIn(b'name="reqtype"', body)
        self.assertIn(b"BYTES", body)
        self.assertNotIn(b'a"b', body)  # quotes are stripped from the filename
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))


class DownloaderHelperTests(unittest.TestCase):
    def test_url_extraction_and_site_checks(self):
        url = dl.extract_url("look: http://youtu.be/abc123, nice")
        self.assertEqual(url, "https://youtu.be/abc123")
        self.assertIsNone(dl.extract_url("no link here"))
        self.assertEqual(dl.require_site("https://www.instagram.com/reel/x/", "instagram"), "https://www.instagram.com/reel/x/")
        for bad in ("https://evil.com/instagram.com", "https://instagram.com.evil.com/x", "http://instagram.com/x", None):
            with self.assertRaises(MediaError, msg=str(bad)):
                dl.require_site(bad, "instagram")
        self.assertTrue(dl.host_in("https://vm.tiktok.com/ZM1/", dl.SITES["tiktok"]))
        self.assertTrue(dl.host_in("https://fb.watch/abc", dl.SITES["facebook"]))

    def test_quality_prefix(self):
        self.assertEqual(dl.split_quality(["480", "cats", "video"]), (480, ["cats", "video"]))
        self.assertEqual(dl.split_quality(["2024", "recap"]), (720, ["2024", "recap"]))
        self.assertEqual(dl.split_quality([]), (720, []))

    def test_ytdlp_options(self):
        video = dl.build_ytdlp_options("/tmp/x", mode="video", quality=480, max_mb=48, max_seconds=3600)
        self.assertIn("height<=480", video["format"])
        self.assertEqual(video["max_filesize"], 48 * 1024 * 1024)
        self.assertTrue(video["noplaylist"])
        self.assertEqual(video["outtmpl"], os.path.join("/tmp/x", "%(id)s.%(ext)s"))  # no user-controlled path
        audio = dl.build_ytdlp_options("/tmp/x", mode="audio", quality=720, max_mb=48, max_seconds=0)
        self.assertEqual(audio["postprocessors"][0]["preferredcodec"], "mp3")
        self.assertNotIn("match_filter", audio)

    def test_ytdlp_missing_dependency_message(self):
        saved = sys.modules.get("yt_dlp")
        sys.modules["yt_dlp"] = None  # makes `import yt_dlp` raise ImportError
        try:
            with self.assertRaises(MissingDependencyError):
                dl.ytdlp_fetch("lofi", tempfile.gettempdir())
        finally:
            if saved is None:
                sys.modules.pop("yt_dlp", None)
            else:
                sys.modules["yt_dlp"] = saved

    def test_ytdlp_fetch_with_a_fake_module(self):
        """Search phrases become ytsearch1:, URLs stay untouched, result metadata is mapped."""
        seen = {}
        directory = tempfile.mkdtemp()

        class FakeYDL:
            def __init__(self, options):
                seen["options"] = options

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def extract_info(self, query, download=True):
                seen["query"] = query
                path = os.path.join(directory, "abc.mp3")
                with open(path, "wb") as handle:
                    handle.write(b"audio")
                return {"entries": [{"title": "Song", "uploader": "Band", "duration": 200,
                                     "requested_downloads": [{"filepath": path}]}]}

        fake = types.ModuleType("yt_dlp")
        fake.YoutubeDL = FakeYDL
        utils = types.ModuleType("yt_dlp.utils")
        utils.match_filter_func = lambda text: ("filter", text)
        fake.utils = utils
        saved = {k: sys.modules.get(k) for k in ("yt_dlp", "yt_dlp.utils")}
        sys.modules["yt_dlp"], sys.modules["yt_dlp.utils"] = fake, utils
        try:
            result = dl.ytdlp_fetch("Artist: Song name", directory, mode="audio")
            self.assertEqual(seen["query"], "ytsearch1:Artist: Song name")
            self.assertEqual((result.title, result.uploader, result.duration, result.kind), ("Song", "Band", 200, "audio"))
            dl.ytdlp_fetch("https://youtu.be/abc", directory, mode="video")
            self.assertEqual(seen["query"], "https://youtu.be/abc")
            self.assertEqual(seen["options"]["match_filter"], ("filter", "duration <=? 3600"))
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value
            shutil.rmtree(directory, ignore_errors=True)

    def test_error_messages_are_friendly(self):
        self.assertIn("cookies", dl.clean_ytdlp_error("ERROR: [instagram] login required"))
        self.assertIn("unavailable", dl.clean_ytdlp_error("ERROR: Video unavailable"))
        self.assertIn("not supported", dl.clean_ytdlp_error("ERROR: Unsupported URL: https://x"))

    def test_pinterest_meta_parsing(self):
        page = ('<meta property="og:image" content="https://i.pinimg.com/736x/ab/cd/x.jpg">'
                '<meta content="https://v1.pinimg.com/videos/x.mp4" property="og:video">'
                '<meta name="twitter:image" content="https://evil.com/x.jpg">')
        meta = dl.parse_og(page)
        self.assertEqual(dl.pick_pinterest_media(meta), ("https://v1.pinimg.com/videos/x.mp4", "video"))
        only_image = {"og:image": "https://i.pinimg.com/736x/ab/cd/x.jpg"}
        self.assertEqual(dl.pick_pinterest_media(only_image), ("https://i.pinimg.com/originals/ab/cd/x.jpg", "image"))
        self.assertEqual(dl.pick_pinterest_media({"og:image": "https://evil.com/x.jpg"}), (None, ""))

    def test_mediafire_parsing(self):
        import base64

        direct = "https://download1234.mediafire.com/abc/file.zip"
        scrambled = base64.b64encode(direct.encode()).decode()
        self.assertEqual(dl.parse_mediafire(f'<a id="downloadButton" data-scrambled-url="{scrambled}" href="#">'), direct)
        self.assertEqual(dl.parse_mediafire(f'<a class="input" href="{direct}?x=1&amp;y=2">Download</a>'),
                         direct + "?x=1&y=2")
        evil = base64.b64encode(b"https://evil.com/x").decode()
        self.assertIsNone(dl.parse_mediafire(f'<a data-scrambled-url="{evil}">'))
        self.assertIsNone(dl.parse_mediafire("<html>nothing</html>"))


class TicTacToeTests(unittest.TestCase):
    def test_ai_never_loses_against_any_opponent(self):
        results = []

        def explore(board, turn):
            won = winner(board)
            if won or is_full(board):
                results.append(won)
                return
            if turn == "X":
                for i in range(9):
                    if not board[i]:
                        board[i] = "X"
                        explore(board, "O")
                        board[i] = ""
            else:
                move = best_move(board, "O")
                board[move] = "O"
                explore(board, "X")
                board[move] = ""

        explore([""] * 9, "X")
        self.assertGreater(len(results), 100)
        self.assertNotIn("X", results)

    def test_manager_flow_with_a_human_opponent(self):
        class Msg:
            def __init__(self, text, sender):
                self.text, self.sender_id, self.deleted = text, sender, False

            async def delete(self):
                self.deleted = True

        class Event:
            def __init__(self, text, sender, chat=5):
                self.message, self.sender_id, self.chat_id = Msg(text, sender), sender, chat

        class Board:
            def __init__(self):
                self.edits = []

            async def edit(self, text):
                self.edits.append(text)

        async def scenario():
            manager = TicTacToeManager()
            game = manager.start(5, 1, "Ali", 2, "Sara")
            game.message = Board()
            # X:1, occupied cell ignored, stranger ignored, O:5, chatter ignored, X:2, O:9, X:3 -> X wins
            for text, sender in [("1", 1), ("1", 2), ("5", 3), ("5", 2), ("hello", 1), ("2", 1), ("9", 2), ("3", 1)]:
                await manager.on_message(Event(text, sender))
            return manager, game

        manager, game = run(scenario())
        self.assertIn("Ali (X) wins", game.message.edits[-1])
        self.assertIsNone(manager.get(5))
        with self.assertRaises(ValueError):
            manager.start(5, 1, "A", None, "")
            manager.start(5, 1, "A", None, "")


class FunAndToolHelperTests(unittest.TestCase):
    """The command modules import the router (needs pydantic); skip cleanly when unavailable."""

    @classmethod
    def setUpClass(cls):
        try:
            import support  # noqa: F401  (sets the isolated test environment)
            from reze.commands import fun, groupadmin, tools
        except Exception as exc:  # pragma: no cover
            raise unittest.SkipTest(f"command modules unavailable: {exc}")
        cls.fun, cls.groupadmin, cls.tools = fun, groupadmin, tools

    def test_ship_is_symmetric_and_bounded(self):
        a = self.fun.ship_percent("Ali", "Sara")
        self.assertEqual(a, self.fun.ship_percent("sara", " ALI "))
        self.assertTrue(0 <= a <= 100)
        self.assertEqual(self.fun.ship_percent("x", "y"), self.fun.ship_percent("x", "y"))

    def test_content_lists_are_usable(self):
        for pool in (self.fun.QUOTES, self.fun.JOKES, self.fun.ROASTS, self.fun.TRUTHS, self.fun.DARES):
            self.assertGreaterEqual(len(pool), 10)
        self.assertTrue(all("{n}" in r for r in self.fun.ROASTS))

    def test_join_link_parsing(self):
        parse = self.groupadmin.parse_join_target
        self.assertEqual(parse("https://t.me/+AbCdEfGh123"), ("hash", "AbCdEfGh123"))
        self.assertEqual(parse("t.me/joinchat/AbCdEfGh123"), ("hash", "AbCdEfGh123"))
        self.assertEqual(parse("https://t.me/pythonchat"), ("username", "pythonchat"))
        self.assertEqual(parse("@pythonchat"), ("username", "pythonchat"))
        self.assertIsNone(parse("hello"))
        self.assertIsNone(parse("https://evil.com/+AbCdEfGh123"))

    def test_hidden_mentions_escape_markdown(self):
        text = self.groupadmin.build_hidden_mentions([1, 2], "a_b *c*")
        self.assertIn("tg://user?id=1", text)
        self.assertIn("\u200b", text)
        self.assertNotIn("a_b *c*", text)

    def test_weather_and_github_and_tts_parsing(self):
        self.assertEqual(self.tools.describe_weather(61), "Light rain")
        self.assertEqual(self.tools.parse_github("https://github.com/UnchartedAli/Reze"), ("UnchartedAli", "Reze"))
        self.assertEqual(self.tools.parse_github("torvalds"), ("torvalds", None))
        self.assertIsNone(self.tools.parse_github("../../etc/passwd"))
        self.assertEqual(self.tools.split_tts_args(["fa", "salam", "dost"]), ("fa", "salam dost"))
        self.assertEqual(self.tools.split_tts_args(["hello", "there"]), ("en", "hello there"))


if __name__ == "__main__":
    unittest.main()
