"""REZE 4.0: isolated plugins. These tests start real worker processes.

They check what the isolation promises: a separate process, a clean environment,
reply-only authority gated by a declared permission, timeouts, crash containment,
clipped output, and approval by file hash. They do not prove a sandbox against
hostile code, which the design does not claim.
"""

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
import uuid
from types import SimpleNamespace

import support  # noqa: F401  - prepares the database before reze imports

from reze.command_router import router
from reze.database import db
from reze.sandbox.isolation import IsolatedPluginHost, IsolationError, Limits, file_sha256

PLUGIN_TEMPLATE = '''
from reze_sdk import command

MANIFEST = {{
    "id": "{ident}",
    "name": "Test plugin {ident}",
    "description": "Isolation test plugin.",
    "version": "1.0.0",
    "permissions": {permissions},
    "commands": {commands},
}}

{body}
'''


_loop = None


def run(coro):
    """Run on the test case's single event loop. Worker pipes belong to the loop that created them."""
    return _loop.run_until_complete(coro)


class FakeCtx:
    def __init__(self, args=None, sender_id=1):
        self.args = args or []
        self.text = ""
        self.sender_id = sender_id
        self.replies = []

    async def reply(self, text=""):
        self.replies.append(str(text))
        return str(text)


class IsolationCase(unittest.TestCase):
    def setUp(self):
        global _loop
        _loop = asyncio.new_event_loop()
        self.dir = tempfile.mkdtemp(prefix="reze-iso-test-")
        self.host = IsolatedPluginHost(Limits(call_timeout=3.0, start_timeout=5.0))
        self.names = []

    def tearDown(self):
        global _loop
        run(self.host.shutdown())
        _loop.close()
        _loop = None
        for name in self.names:
            db.delete_setting("plugin.isolated.sha256." + name)
        shutil.rmtree(self.dir, ignore_errors=True)

    def write_plugin(self, body, permissions=("telegram.message",), commands=("hi",), name=None):
        name = name or ("p" + uuid.uuid4().hex[:8])
        self.names.append(name)
        path = os.path.join(self.dir, f"{name}.py")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(PLUGIN_TEMPLATE.format(
                ident=name, permissions=list(permissions), commands=list(commands), body=body))
        return name, path

    def load(self, name, path):
        return run(self.host.load(name, path))

    def invoke(self, name, command, ctx=None):
        return run(self.host.invoke(name, command, ctx or FakeCtx()))


class ProcessBoundaryTests(IsolationCase):
    def test_the_plugin_runs_in_its_own_process(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    import os
    return str(os.getpid())
''')
        self.load(name, path)
        pid = int(self.invoke(name, "hi"))
        self.assertNotEqual(pid, os.getpid())

    def test_secrets_in_the_bot_environment_do_not_reach_the_plugin(self):
        os.environ["REZE_TEST_SECRET"] = "s3cret-value-for-test"
        try:
            name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    import os
    return " ".join(sorted(os.environ))
''')
            self.load(name, path)
            seen = self.invoke(name, "hi")
            self.assertNotIn("REZE_TEST_SECRET", seen)
            self.assertNotIn("s3cret", seen)
        finally:
            os.environ.pop("REZE_TEST_SECRET", None)

    def test_the_plugin_cannot_import_the_bot(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    try:
        import reze.database  # noqa: F401
        return "imported"
    except ImportError:
        return "blocked"
''')
        self.load(name, path)
        self.assertEqual(self.invoke(name, "hi"), "blocked")

    def test_printing_does_not_corrupt_the_protocol(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    print("this must not break the channel")
    return "still fine"
''')
        self.load(name, path)
        self.assertEqual(self.invoke(name, "hi"), "still fine")


class PermissionTests(IsolationCase):
    def test_reply_is_delivered_only_with_the_declared_permission(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    ctx.reply("hello from the worker")
    return ""
''', permissions=("telegram.message",))
        self.load(name, path)
        ctx = FakeCtx()
        self.invoke(name, "hi", ctx)
        self.assertEqual(ctx.replies, ["hello from the worker"])

    def test_reply_without_the_permission_is_refused(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    try:
        ctx.reply("should not arrive")
        return "sent"
    except RuntimeError as exc:
        return "denied: " + str(exc)
''', permissions=())
        self.load(name, path)
        ctx = FakeCtx()
        result = self.invoke(name, "hi", ctx)
        self.assertEqual(ctx.replies, [], "nothing reached the chat")
        self.assertIn("denied", result)

    def test_commands_must_match_the_manifest(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    return "x"

@command("sneaky")
def sneaky(ctx):
    return "y"
''', commands=("hi",))
        with self.assertRaisesRegex(IsolationError, "does not declare"):
            self.load(name, path)
        self.assertNotIn("sneaky", router.commands)


class FailureContainmentTests(IsolationCase):
    def test_a_hang_stops_only_that_plugin(self):
        name, path = self.write_plugin('''
import time

@command("hang")
def hang(ctx):
    time.sleep(30)
    return "never"

@command("hi")
def hi(ctx):
    return "alive"
''', commands=("hang", "hi"))
        self.load(name, path)
        with self.assertRaisesRegex(IsolationError, "too long"):
            self.invoke(name, "hang")
        self.assertEqual(self.invoke(name, "hi"), "alive", "the host restarts the worker for the next call")

    def test_a_crash_is_reported_and_the_host_keeps_running(self):
        name, path = self.write_plugin('''
import os

@command("boom")
def boom(ctx):
    os._exit(3)

@command("hi")
def hi(ctx):
    return "alive"
''', commands=("boom", "hi"))
        self.load(name, path)
        with self.assertRaisesRegex(IsolationError, "exited"):
            self.invoke(name, "boom")
        self.assertEqual(self.invoke(name, "hi"), "alive")

    def test_a_plugin_exception_is_an_error_not_a_crash(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    raise ValueError("bad input")
''')
        self.load(name, path)
        with self.assertRaisesRegex(IsolationError, "ValueError"):
            self.invoke(name, "hi")
        self.assertTrue(self.host.plugins[name].running, "a plugin exception keeps the worker alive")

    def test_repeated_crashes_stop_the_plugin(self):
        name, path = self.write_plugin('''
import os

@command("boom")
def boom(ctx):
    os._exit(1)
''', commands=("boom",))
        self.load(name, path)
        for _ in range(6):
            with self.assertRaises(IsolationError):
                self.invoke(name, "boom")
        with self.assertRaisesRegex(IsolationError, "crashed too often"):
            self.invoke(name, "boom")

    def test_long_output_is_clipped(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    return "x" * 20000
''')
        self.load(name, path)
        result = self.invoke(name, "hi")
        self.assertLessEqual(len(result), Limits().max_output)

    def test_unknown_command_is_an_error(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    return "x"
''')
        self.load(name, path)
        with self.assertRaisesRegex(IsolationError, "unknown command"):
            run(self.host.plugins[name].call("nope", {}, lambda op, p: None))


@unittest.skipUnless(os.name == "posix", "resource limits are applied on POSIX systems only")
class ResourceLimitTests(IsolationCase):
    def test_memory_and_cpu_limits_are_set_in_the_worker(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    import resource
    soft, _ = resource.getrlimit(resource.RLIMIT_AS)
    cpu, _ = resource.getrlimit(resource.RLIMIT_CPU)
    return f"{soft}:{cpu}"
''')
        self.load(name, path)
        soft, cpu = self.invoke(name, "hi").split(":")
        self.assertEqual(int(soft), Limits().memory_mb * 1024 * 1024)
        self.assertEqual(int(cpu), Limits().cpu_seconds)


class ApprovalTests(IsolationCase):
    def test_first_load_is_approved_and_later_changes_need_approval_again(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    return "v1"
''')
        self.load(name, path)
        run(self.host.unload(name))
        self.assertEqual(self.host.approved_hash(name), file_sha256(path))

        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n# changed after approval\n")
        with self.assertRaisesRegex(IsolationError, "changed since it was approved"):
            self.load(name, path)

        self.host.approve(name, path)
        self.load(name, path)
        self.assertEqual(self.invoke(name, "hi"), "v1")

    def test_a_plugin_that_fails_validation_is_not_approved(self):
        name, path = self.write_plugin('''
@command("hi")
def hi(ctx):
    return "x"
''', commands=("other",))
        with self.assertRaises(IsolationError):
            self.load(name, path)
        self.assertIsNone(self.host.approved_hash(name))


class RegistrationTests(IsolationCase):
    def test_commands_are_registered_with_the_plugin_name_and_removed_on_unload(self):
        command = "iso_" + uuid.uuid4().hex[:6]
        name, path = self.write_plugin(f'''
@command("{command}")
def f(ctx):
    return "x"
''', commands=(command,))
        self.load(name, path)
        self.assertIn(command, router.commands)
        self.assertEqual(router.commands[command].plugin, name)
        run(self.host.unload(name))
        self.assertNotIn(command, router.commands)

    def test_a_command_name_already_in_use_is_refused(self):
        taken = "taken_" + uuid.uuid4().hex[:6]
        first, first_path = self.write_plugin(f'''
@command("{taken}")
def f(ctx):
    return "x"
''', commands=(taken,))
        self.load(first, first_path)
        second, second_path = self.write_plugin(f'''
@command("{taken}")
def g(ctx):
    return "y"
''', commands=(taken,))
        with self.assertRaisesRegex(IsolationError, "already in use"):
            self.load(second, second_path)


if __name__ == "__main__":
    unittest.main()


class ShippedExampleTests(IsolationCase):
    """The example in docs/ must keep working; it is the template people will copy."""

    def test_the_documented_example_loads_and_replies(self):
        example = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "examples", "isolated_plugin_example.py")
        name = "word_count"
        self.names.append(name)
        db.delete_setting("plugin.isolated.sha256." + name)
        commands = run(self.host.load(name, example))
        self.assertEqual(commands, ["words"])
        ctx = FakeCtx(args=["one", "two", "three"])
        self.invoke(name, "words", ctx)
        self.assertEqual(ctx.replies, ["3 word(s)."])
        run(self.host.unload(name))


class PluginFolderHygieneTests(unittest.TestCase):
    """Regression: isolation code once lived in reze/plugins/ and the loader tried to load it as a plugin."""

    def test_the_plugin_loader_does_not_see_sandbox_files(self):
        from reze.plugin_manager import PluginManager
        folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "reze", "plugins")
        names = PluginManager(plugins_dir=folder).discover()
        self.assertNotIn("isolation", names)
        self.assertNotIn("worker", names)
        self.assertNotIn("sandbox", names)
