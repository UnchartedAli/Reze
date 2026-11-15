"""REZE 4.0: the .isolated command. Starts real worker processes for the load and unload paths."""

import asyncio
import os
import shutil
import tempfile
import unittest
import uuid
from unittest import mock

import support  # noqa: F401  - prepares the database before reze imports

from reze.command_router import router
from reze.config import settings
from reze.database import db
from reze.commands import isolated as isolated_commands
from reze.features import features
from reze.sandbox import service
from reze.sandbox.isolation import Limits

OWNER = 4242
PLUGIN = '''
from reze_sdk import command

MANIFEST = {{
    "id": "{name}", "name": "Test {name}", "description": "Command test plugin.", "version": "1.0.0",
    "permissions": ["telegram.message"], "commands": ["{cmd}"],
}}

@command("{cmd}")
def {cmd}(ctx):
    return "ok"
'''

_loop = None


def run(coro):
    return _loop.run_until_complete(coro)


class FakeCtx:
    def __init__(self, args=None, sender_id=OWNER):
        self.args = args or []
        self.sender_id = sender_id
        self.text = ""
        self.replies = []

    async def reply(self, text=""):
        self.replies.append(str(text))
        return str(text)

    async def reply_usage(self, note=""):
        self.replies.append("USAGE " + str(note))
        return note


def flat(text):
    cleaned = "".join(ch if ch not in "╔╗╚╝║═╠╣─│" else " " for ch in text)
    return " ".join(cleaned.upper().split())


class IsolatedCommandCase(unittest.TestCase):
    def setUp(self):
        global _loop
        _loop = asyncio.new_event_loop()
        self.data = tempfile.mkdtemp(prefix="reze-isolated-cmd-")
        self._data_dir = settings.data_dir
        settings.data_dir = self.data
        os.makedirs(service.isolated_dir(), exist_ok=True)
        self._was_on = features.is_enabled("isolated_plugins")
        features.enable("isolated_plugins", actor=OWNER, confirmed=True)
        self.names = []

    def tearDown(self):
        global _loop
        run(service.isolated_host.shutdown())
        _loop.close()
        _loop = None
        for name in self.names:
            db.delete_setting("plugin.isolated.sha256." + name)
        if not self._was_on and features.is_enabled("isolated_plugins"):
            features.disable("isolated_plugins", actor=OWNER)
        settings.data_dir = self._data_dir
        shutil.rmtree(self.data, ignore_errors=True)

    def plugin_file(self, name=None):
        name = name or ("pl" + uuid.uuid4().hex[:6])
        cmd = "c" + uuid.uuid4().hex[:6]
        self.names.append(name)
        path = os.path.join(service.isolated_dir(), name + ".py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(PLUGIN.format(name=name, cmd=cmd))
        return name, cmd, path

    def command(self, args, sender=OWNER):
        ctx = FakeCtx(args, sender)
        run(isolated_commands.isolated_cmd(ctx))
        return ctx


class GateTests(IsolatedCommandCase):
    def test_feature_off_refuses_everything(self):
        features.disable("isolated_plugins", actor=OWNER)
        ctx = self.command(["list"])
        self.assertTrue(any("FEATURE IS OFF" in flat(r) for r in ctx.replies))

    def test_strangers_are_refused(self):
        ctx = self.command(["list"], sender=999)
        self.assertTrue(any("OWNER ONLY" in flat(r) for r in ctx.replies))

    def test_the_command_is_owner_only_in_the_router(self):
        self.assertTrue(router.commands["isolated"].owner_only)


class NameAndPathTests(IsolatedCommandCase):
    def test_names_that_could_escape_the_folder_are_refused(self):
        for bad in ["../evil", "a/b", "..", "", "UPPER", "with space", "x" * 40, "dot.py"]:
            with self.subTest(name=bad):
                with self.assertRaises(ValueError):
                    service.resolve_plugin_path(bad)

    def test_a_missing_file_is_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "No file named"):
            service.resolve_plugin_path("nothere")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks not available")
    def test_a_symlink_that_points_outside_the_folder_is_refused(self):
        outside = os.path.join(self.data, "outside_secret.py")
        with open(outside, "w", encoding="utf-8") as handle:
            handle.write("MANIFEST = {}\n")
        link = os.path.join(service.isolated_dir(), "sneaky.py")
        try:
            os.symlink(outside, link)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlinks here")
        self.names.append("sneaky")
        with self.assertRaisesRegex(ValueError, "outside"):
            service.resolve_plugin_path("sneaky")

    def test_only_valid_names_are_listed(self):
        name, _, _ = self.plugin_file()
        with open(os.path.join(service.isolated_dir(), "Bad-Name.py"), "w") as handle:
            handle.write("")
        self.assertEqual(service.list_plugin_names(), [name])


class LoadUnloadTests(IsolatedCommandCase):
    def test_load_then_unload_through_chat(self):
        name, cmd, _ = self.plugin_file()
        ctx = self.command(["load", name])
        self.assertTrue(any("PLUGIN LOADED" in flat(r) for r in ctx.replies), ctx.replies)
        self.assertIn(cmd, router.commands)
        self.assertEqual(service.plugin_status(name), "loaded")
        ctx = self.command(["unload", name])
        self.assertTrue(any("PLUGIN UNLOADED" in flat(r) for r in ctx.replies))
        self.assertNotIn(cmd, router.commands)

    def test_list_reports_each_file_status(self):
        name, _, _ = self.plugin_file()
        self.assertEqual(service.plugin_status(name), "not approved")
        ctx = self.command(["list"])
        self.assertTrue(any(f"{name}: not approved" in r for r in ctx.replies), ctx.replies)

    def test_changed_files_are_refused_until_approved_again(self):
        name, cmd, path = self.plugin_file()
        self.command(["load", name])
        self.command(["unload", name])
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n# edited on disk\n")
        self.assertEqual(service.plugin_status(name), "changed")
        ctx = self.command(["load", name])
        self.assertTrue(any("APPROVE" in flat(r) for r in ctx.replies), ctx.replies)
        self.assertNotIn(cmd, router.commands)
        self.command(["approve", name])
        self.command(["load", name])
        self.assertIn(cmd, router.commands)

    def test_unknown_subcommand_shows_help(self):
        ctx = self.command(["explode"])
        self.assertTrue(any("ISOLATED PLUGIN COMMANDS" in flat(r) for r in ctx.replies))


if __name__ == "__main__":
    unittest.main()
