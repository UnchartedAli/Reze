"""Plugin lifecycle, manifest validation and the media toolkit."""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import support

from reze.config import settings
from reze.database import db
from reze.exceptions import ManifestError, MediaError, MissingDependencyError, PluginError
from reze.media import ffmpeg, images
from reze.media.workspace import MediaWorkspace, download_reply_media, ensure_size, safe_filename
from reze.plugin_manager import PluginManager, PluginSettings
from reze.plugins.manifest import build_manifest

PLUGIN_SOURCE = '''
from reze.command_router import CommandContext, router

MANIFEST = {manifest}

@router.register(name="{command}", category="Plugins", description="Test command")
async def handler(ctx: CommandContext):
    return await ctx.reply("plugin ran")
'''


def write_plugin(directory, name, command, manifest_commands=None, body=""):
    manifest = (
        "{'name': 'Test Plugin %s', 'id': '%s', 'version': '1.0.0', "
        "'description': 'A plugin used by the test suite.', 'commands': %r}"
        % (name, name, manifest_commands if manifest_commands is not None else [command])
    )
    path = os.path.join(directory, f"{name}.py")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(PLUGIN_SOURCE.format(manifest=manifest, command=command))
        handle.write(body)
    return path


class ManifestTests(unittest.TestCase):
    def test_valid_manifest(self):
        manifest = build_manifest(
            {
                "name": "My Plugin",
                "id": "my_plugin",
                "version": "1.2.0",
                "description": "Does something useful.",
                "commands": ["alpha"],
                "permissions": ["telegram.message"],
                "config": {"limit": {"type": "int", "default": 5}},
            },
            fallback_id="my_plugin",
        )
        self.assertEqual(manifest.id, "my_plugin")
        self.assertEqual(manifest.permissions, ["telegram.message"])

    def test_unknown_capability_rejected(self):
        with self.assertRaises(ManifestError) as context:
            build_manifest(
                {
                    "name": "Bad",
                    "id": "bad",
                    "description": "Requests an unknown capability.",
                    "permissions": ["root.everything"],
                }
            )
        self.assertIn("unknown capability", str(context.exception))

    def test_invalid_command_name_rejected(self):
        with self.assertRaises(ManifestError):
            build_manifest(
                {
                    "name": "Bad",
                    "id": "bad",
                    "description": "Registers an invalid command.",
                    "commands": ["Not Valid"],
                }
            )

    def test_incompatible_minimum_version(self):
        with self.assertRaises(ManifestError) as context:
            build_manifest(
                {
                    "name": "Future",
                    "id": "future",
                    "description": "Needs a newer Reze.",
                    "min_reze_version": "99.0.0",
                }
            )
        self.assertIn("requires Reze", str(context.exception))

    def test_missing_manifest_rejected(self):
        with self.assertRaises(ManifestError):
            build_manifest(None)

    def test_config_type_validation(self):
        with self.assertRaises(ManifestError):
            build_manifest(
                {
                    "name": "Bad config",
                    "id": "badcfg",
                    "description": "Uses an unsupported config type.",
                    "config": {"mode": {"type": "quantum"}},
                }
            )


class PluginManagerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="reze-plugins-")
        self.manager = PluginManager(plugins_dir=self.directory)

    def tearDown(self):
        shutil.rmtree(self.directory, ignore_errors=True)

    def test_discovery_is_sorted_and_skips_private_files(self):
        write_plugin(self.directory, "bbb", "cmdbbb")
        write_plugin(self.directory, "aaa", "cmdaaa")
        with open(os.path.join(self.directory, "_hidden.py"), "w", encoding="utf-8") as handle:
            handle.write("raise RuntimeError('should not load')")
        self.assertEqual(self.manager.discover(), ["aaa", "bbb"])

    def test_load_registers_commands(self):
        write_plugin(self.directory, "alphaplugin", "alpha")
        state = self.manager.load("alphaplugin")
        self.assertEqual(state.status, "loaded")
        self.assertEqual(state.commands, ["alpha"])
        self.assertTrue(self.manager.is_enabled("alphaplugin"))

    def test_duplicate_command_is_rejected(self):
        write_plugin(self.directory, "first", "shared_cmd")
        write_plugin(self.directory, "second", "shared_cmd")
        self.manager.load("first")
        with self.assertRaises(PluginError) as context:
            self.manager.load("second")
        self.assertIn("already registered", str(context.exception))
        self.assertEqual(self.manager.get("second").status, "failed")

    def test_manifest_mismatch_is_rejected_and_rolled_back(self):
        write_plugin(self.directory, "mismatch", "declared_missing", manifest_commands=["other"])
        with self.assertRaises(PluginError):
            self.manager.load("mismatch")
        from reze.command_router import router

        self.assertNotIn("declared_missing", router.commands)
        self.assertIn("mismatch", self.manager.failures)

    def test_failure_isolation(self):
        write_plugin(self.directory, "broken", "broken_cmd", body="\nraise RuntimeError('boom')\n")
        write_plugin(self.directory, "healthy", "healthy_cmd")
        self.manager.load_all()
        self.assertEqual(self.manager.get("broken").status, "failed")
        self.assertEqual(self.manager.get("healthy").status, "loaded")

    def test_disable_persists_and_blocks_loading(self):
        write_plugin(self.directory, "toggle", "toggle_cmd")
        self.manager.load("toggle")
        self.manager.disable("toggle")
        self.assertFalse(self.manager.is_enabled("toggle"))
        self.assertEqual(db.get_plugin_enabled("toggle"), False)
        with self.assertRaises(PluginError):
            self.manager.load("toggle")

    def test_missing_dependency_is_reported(self):
        path = os.path.join(self.directory, "needs.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "MANIFEST = {'name': 'Needs', 'id': 'needs', 'version': '1.0.0',"
                " 'description': 'Needs a module.', 'commands': ['needs_cmd'],"
                " 'requires': ['module_that_does_not_exist_12345']}\n"
            )
        with self.assertRaises(PluginError) as context:
            self.manager.load("needs")
        self.assertIn("Missing required dependencies", str(context.exception))

    def test_builtin_example_plugin_loads(self):
        manager = PluginManager(plugins_dir="reze/plugins")
        state = manager.load("example")
        self.assertEqual(state.status, "loaded")
        self.assertIn("hello", state.commands)
        self.assertIn("calc", state.commands)
        manifest = state.manifest
        self.assertEqual(manifest.id, "example")

    def test_plugin_settings_are_typed(self):
        settings_store = PluginSettings(
            "demo",
            {
                "mode": {"type": "choice", "choices": ["fast", "slow"], "default": "fast"},
                "limit": {"type": "int", "default": 3},
                "token": {"type": "secret", "default": ""},
            },
        )
        self.assertEqual(settings_store.get("mode"), "fast")
        settings_store.set("mode", "slow")
        self.assertEqual(settings_store.get("mode"), "slow")
        with self.assertRaises(ValueError):
            settings_store.set("mode", "turbo")
        settings_store.set("limit", 9)
        self.assertEqual(settings_store.get("limit"), 9)
        with self.assertRaises(ValueError):
            settings_store.set("limit", "many")
        settings_store.set("token", "supersecret")
        self.assertEqual(settings_store.public()["token"], "********")


class WorkspaceTests(unittest.TestCase):
    def test_safe_filename_strips_paths(self):
        for candidate in ("../../etc/passwd", "C:\\Windows\\system32", "..\\..\\x.png"):
            cleaned = safe_filename(candidate)
            self.assertNotIn("..", cleaned)
            self.assertNotIn("/", cleaned)
            self.assertNotIn("\\", cleaned)

    def test_child_cannot_escape_workspace(self):
        workspace = MediaWorkspace("test")
        try:
            target = workspace.child("../../escape.png")
            self.assertTrue(target.startswith(workspace.directory))
        finally:
            workspace.cleanup()
        self.assertFalse(os.path.exists(workspace.directory))

    def test_ensure_size_rejects_missing_and_large(self):
        workspace = MediaWorkspace("size")
        try:
            with self.assertRaises(MediaError):
                ensure_size(os.path.join(workspace.directory, "missing.bin"))
            small = os.path.join(workspace.directory, "small.bin")
            with open(small, "wb") as handle:
                handle.write(b"x" * 1024)
            self.assertEqual(ensure_size(small, limit_mb=1), 1024)
            with self.assertRaises(MediaError):
                ensure_size(small, limit_mb=0)
        finally:
            workspace.cleanup()

    def test_download_requires_reply(self):
        ctx = support.make_context()
        workspace = MediaWorkspace("download")
        try:
            with self.assertRaises(MediaError):
                support.run(download_reply_media(ctx, workspace))
        finally:
            workspace.cleanup()


@unittest.skipUnless(images.available(), "Pillow is not installed")
class ImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image, ImageDraw

        cls.directory = tempfile.mkdtemp(prefix="reze-images-")
        cls.source = os.path.join(cls.directory, "source.png")
        image = Image.new("RGB", (800, 600), (20, 40, 80))
        draw = ImageDraw.Draw(image)
        draw.rectangle((50, 50, 400, 300), fill=(240, 200, 60))
        draw.ellipse((450, 100, 700, 400), fill=(20, 200, 160))
        image.save(cls.source)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def path(self, name):
        return os.path.join(self.directory, name)

    def test_probe(self):
        info = images.probe(self.source)
        self.assertEqual((info["width"], info["height"]), (800, 600))
        self.assertEqual(info["format"], "PNG")

    def test_resize_keeps_aspect(self):
        target = self.path("resized.png")
        images.resize(self.source, target, width=400)
        info = images.probe(target)
        self.assertEqual(info["width"], 400)
        self.assertEqual(info["height"], 300)

    def test_resize_rejects_bad_arguments(self):
        with self.assertRaises(MediaError):
            images.resize(self.source, self.path("x.png"))
        with self.assertRaises(MediaError):
            images.resize(self.source, self.path("x.png"), width=2)

    def test_compress_respects_max_bytes(self):
        target = self.path("compressed.jpg")
        images.compress(self.source, target, quality=60, max_bytes=200_000)
        self.assertLessEqual(os.path.getsize(target), 200_000)
        self.assertEqual(images.probe(target)["format"], "JPEG")

    def test_caption_and_meme(self):
        captioned = self.path("captioned.png")
        images.add_caption(self.source, captioned, "Release 2.0", position="bottom")
        self.assertEqual(images.probe(captioned)["width"], 800)
        meme = self.path("meme.png")
        images.make_meme(self.source, meme, top="WHEN IT WORKS", bottom="ON THE FIRST TRY")
        self.assertTrue(os.path.getsize(meme) > 0)
        with self.assertRaises(MediaError):
            images.add_caption(self.source, self.path("empty.png"), "   ")

    def test_thumbnail_is_square(self):
        target = self.path("thumb.jpg")
        images.thumbnail(self.source, target, size=200)
        info = images.probe(target)
        self.assertEqual((info["width"], info["height"]), (200, 200))

    def test_sticker_is_512_webp(self):
        target = self.path("sticker.webp")
        images.make_sticker(self.source, target)
        info = images.probe(target)
        self.assertEqual(info["format"], "WEBP")
        self.assertEqual((info["width"], info["height"]), (512, 512))
        self.assertLessEqual(os.path.getsize(target), 512 * 1024)

    def test_invalid_image_is_rejected(self):
        broken = self.path("broken.png")
        with open(broken, "wb") as handle:
            handle.write(b"not an image")
        with self.assertRaises(MediaError):
            images.open_image(broken)


@unittest.skipUnless(images.available(), "Pillow is not installed")
class StickerSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PIL import Image

        cls.directory = tempfile.mkdtemp(prefix="reze-sticker-")
        cls.source = os.path.join(cls.directory, "source.png")
        Image.new("RGBA", (300, 300), (255, 0, 0, 255)).save(cls.source)
        cls.sticker = os.path.join(cls.directory, "sticker.webp")
        images.make_sticker(cls.source, cls.sticker)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.directory, ignore_errors=True)

    def test_short_name_validation(self):
        from reze.media.stickers import generate_short_name, validate_short_name

        name = generate_short_name("reze")
        self.assertEqual(validate_short_name(name), name)
        self.assertRegex(name, r"^[A-Za-z][A-Za-z0-9_]+$")
        with self.assertRaises(ValueError):
            validate_short_name("1nope")
        with self.assertRaises(ValueError):
            validate_short_name("bad-name")

    def test_create_sticker_set_builds_real_request(self):
        from reze.media.stickers import create_sticker_set

        client = support.DummyClient()
        result = support.run(
            create_sticker_set(client, "Reze Pack", "reze_test_pack", self.sticker, "🙂")
        )
        self.assertEqual(result["url"], "https://t.me/addstickers/reze_test_pack")
        self.assertEqual(len(client.requests), 1)
        request = client.requests[0]
        self.assertEqual(request.title, "Reze Pack")
        self.assertEqual(request.short_name, "reze_test_pack")
        self.assertEqual(len(request.stickers), 1)
        self.assertEqual(request.stickers[0].emoji, "🙂")
        self.assertEqual(client.uploaded, self.sticker)

    def test_add_sticker_uses_input_set(self):
        from reze.media.stickers import add_sticker_to_set

        client = support.DummyClient()
        result = support.run(add_sticker_to_set(client, "reze_test_pack", self.sticker, "🔥"))
        self.assertEqual(result["url"], "https://t.me/addstickers/reze_test_pack")
        request = client.requests[0]
        self.assertEqual(request.stickerset.short_name, "reze_test_pack")
        self.assertEqual(request.sticker.emoji, "🔥")

    def test_invalid_asset_rejected(self):
        from reze.media.stickers import create_sticker_set

        with self.assertRaises(MediaError):
            support.run(
                create_sticker_set(support.DummyClient(), "Pack", "reze_pack", self.source)
            )


class FfmpegTests(unittest.TestCase):
    def test_timestamp_parsing(self):
        self.assertEqual(ffmpeg.parse_timestamp("90"), 90)
        self.assertEqual(ffmpeg.parse_timestamp("1:30"), 90)
        self.assertEqual(ffmpeg.parse_timestamp("1:00:00"), 3600)
        with self.assertRaises(MediaError):
            ffmpeg.parse_timestamp("abc")
        with self.assertRaises(MediaError):
            ffmpeg.parse_timestamp("-5")

    def test_missing_ffmpeg_reports_actionable_error(self):
        with patch.object(ffmpeg.shutil, "which", return_value=None), patch.object(
            settings, "ffmpeg_path", ""
        ):
            self.assertFalse(ffmpeg.available())
            with self.assertRaises(MissingDependencyError) as context:
                ffmpeg.require_ffmpeg()
            self.assertIn("FFmpeg is not installed", str(context.exception))

    def test_run_uses_argument_array_without_shell(self):
        captured = {}

        class Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return Completed()

        with patch.object(ffmpeg, "require_ffmpeg", return_value="ffmpeg"), patch.object(
            ffmpeg.subprocess, "run", side_effect=fake_run
        ):
            ffmpeg.run(["-y", "-i", "input.mp4", "output.mp4"])

        self.assertEqual(captured["command"][0], "ffmpeg")
        self.assertIn("-nostdin", captured["command"])
        self.assertIn("input.mp4", captured["command"])
        self.assertNotIn("shell", captured["kwargs"])
        self.assertGreater(captured["kwargs"]["timeout"], 0)

    def test_failed_conversion_raises_media_error(self):
        class Failed:
            returncode = 1
            stdout = ""
            stderr = "Invalid data found when processing input"

        with patch.object(ffmpeg, "require_ffmpeg", return_value="ffmpeg"), patch.object(
            ffmpeg.subprocess, "run", return_value=Failed()
        ):
            with self.assertRaises(MediaError) as context:
                ffmpeg.run(["-i", "bad.mp4", "out.mp4"])
        self.assertIn("FFmpeg failed", str(context.exception))

    def test_invalid_speed_factor(self):
        with patch.object(ffmpeg, "require_ffmpeg", return_value="ffmpeg"):
            with self.assertRaises(MediaError):
                ffmpeg.change_speed("in.mp4", "out.mp4", 9.0)


if __name__ == "__main__":
    unittest.main()
