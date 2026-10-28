"""Always-online presence: preference, service loop, request and command."""

import asyncio
import time
import unittest

import support

from reze.command_router import CommandRouter
from reze.commands.presence import setonlinepermanently_cmd
from reze.core.presence import PresenceService
from reze.preferences import get_pref, set_pref, get_bool_pref


class FakeFloodWait(Exception):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__(f"wait {seconds}s")


class PresencePreferenceTests(unittest.TestCase):
    def tearDown(self):
        set_pref("online_always", "0")

    def test_default_is_disabled(self):
        set_pref("online_always", "0")
        self.assertFalse(PresenceService().enabled())

    def test_set_enabled_roundtrip(self):
        PresenceService.set_enabled(True)
        self.assertEqual(get_pref("online_always"), "1")
        self.assertTrue(PresenceService.enabled())
        PresenceService.set_enabled(False)
        self.assertEqual(get_pref("online_always"), "0")
        self.assertFalse(get_bool_pref("online_always", True))

    def test_loose_values_are_normalised(self):
        set_pref("online_always", "yes")
        self.assertEqual(get_pref("online_always"), "1")
        set_pref("online_always", "perhaps")
        self.assertEqual(get_pref("online_always"), "0")


class PresenceServiceTests(unittest.TestCase):
    def setUp(self):
        set_pref("online_always", "0")

    def tearDown(self):
        set_pref("online_always", "0")

    def test_tick_does_nothing_when_disabled(self):
        client = support.DummyClient()
        service = PresenceService(client_provider=lambda: client)
        self.assertFalse(support.run(service.tick()))
        self.assertEqual(client.requests, [])
        self.assertEqual(service.applied_count, 0)

    def test_tick_sends_update_status_when_enabled(self):
        from telethon.tl.functions.account import UpdateStatusRequest

        client = support.DummyClient()
        service = PresenceService(client_provider=lambda: client)
        set_pref("online_always", "1")

        self.assertTrue(support.run(service.tick()))
        self.assertEqual(len(client.requests), 1)
        request = client.requests[0]
        self.assertIsInstance(request, UpdateStatusRequest)
        self.assertFalse(request.offline)
        self.assertEqual(service.applied_count, 1)
        self.assertGreater(service.last_applied, 0)
        self.assertGreater(service.status()["last_applied"], 0)

    def test_tick_without_client_reports_disconnected(self):
        service = PresenceService(client_provider=lambda: None)
        set_pref("online_always", "1")
        self.assertFalse(support.run(service.tick()))
        self.assertIn("not connected", service.last_error)

    def test_flood_wait_sets_a_cooldown(self):
        class FloodingClient:
            def __init__(self):
                self.calls = 0

            async def __call__(self, request):
                self.calls += 1
                raise FakeFloodWait(45)

        client = FloodingClient()
        service = PresenceService(client_provider=lambda: client)
        set_pref("online_always", "1")

        self.assertFalse(support.run(service.tick()))
        self.assertIn("FloodWait", service.last_error)
        self.assertGreater(service.status()["cooldown_remaining"], 0)

        # The cooldown must prevent a second request.
        self.assertFalse(support.run(service.tick()))
        self.assertEqual(client.calls, 1)

    def test_unexpected_error_is_captured(self):
        class BrokenClient:
            async def __call__(self, request):
                raise RuntimeError("socket closed")

        service = PresenceService(client_provider=lambda: BrokenClient())
        set_pref("online_always", "1")
        self.assertFalse(support.run(service.tick()))
        self.assertIn("socket closed", service.last_error)
        self.assertEqual(service.applied_count, 0)

    def test_apply_now_ignores_the_disabled_preference(self):
        client = support.DummyClient()
        service = PresenceService(client_provider=lambda: client)
        self.assertTrue(support.run(service.apply_now()))
        self.assertEqual(len(client.requests), 1)
        self.assertFalse(service.enabled())

    def test_loop_starts_and_stops(self):
        client = support.DummyClient()

        async def scenario():
            service = PresenceService(client_provider=lambda: client, interval=30)
            set_pref("online_always", "1")
            service.start()
            await asyncio.sleep(0.05)
            running = service._running
            service.stop()
            await asyncio.sleep(0.01)
            return running, service._running

        running, stopped = support.run(scenario())
        self.assertTrue(running)
        self.assertFalse(stopped)


class PresenceCommandTests(unittest.TestCase):
    def setUp(self):
        set_pref("online_always", "0")
        self.router = CommandRouter(default_prefix=".")

    def tearDown(self):
        set_pref("online_always", "0")

    def test_enable_applies_immediately(self):
        client = support.DummyClient()
        ctx = support.make_context(
            text=".setonlinepermanently on", args=["on"], client=client
        )
        support.run(setonlinepermanently_cmd(ctx))
        self.assertEqual(get_pref("online_always"), "1")
        self.assertIn("ENABLED", ctx.message.replies[0])
        self.assertEqual(len(client.requests), 1)

    def test_enable_without_connection_keeps_the_preference(self):
        ctx = support.make_context(text=".setonlinepermanently on", args=["on"], client=None)
        # make_context always provides a client; simulate a disconnected one instead.
        ctx.client = None
        support.run(setonlinepermanently_cmd(ctx))
        self.assertEqual(get_pref("online_always"), "1")
        self.assertIn("Saved.", ctx.message.replies[0])
        self.assertIn("Telegram is connected", ctx.message.replies[0])

    def test_disable(self):
        set_pref("online_always", "1")
        ctx = support.make_context(text=".setonlinepermanently off", args=["off"])
        support.run(setonlinepermanently_cmd(ctx))
        self.assertEqual(get_pref("online_always"), "0")
        self.assertIn("DISABLED", ctx.message.replies[0])

    def test_status_output(self):
        ctx = support.make_context(text=".setonlinepermanently", args=[])
        support.run(setonlinepermanently_cmd(ctx))
        body = ctx.message.replies[0]
        self.assertIn("ALWAYS ONLINE", body)
        self.assertIn("Refresh interval", body)
        self.assertIn("privacy", body.lower())

    def test_invalid_argument_returns_usage(self):
        ctx = support.make_context(text=".setonlinepermanently maybe", args=["maybe"])
        support.run(setonlinepermanently_cmd(ctx))
        self.assertIn("Usage", ctx.message.replies[0])

    def test_command_metadata_is_owner_only_with_aliases(self):
        from reze.commands.presence import setonlinepermanently_cmd as handler

        self.assertTrue(getattr(handler, "__name__", ""))
        # The command is registered on the global router when the module imports.
        from reze.command_router import router as global_router

        command = global_router.resolve("setonlinepermanently")
        self.assertIsNotNone(command)
        self.assertTrue(command.owner_only)
        self.assertIn("alwaysonline", command.aliases)
        self.assertIn("setonlinepermanently", global_router.commands)


class StatusIntegrationTests(unittest.TestCase):
    def test_system_status_reports_presence(self):
        from reze.commands.system import status_cmd

        set_pref("online_always", "1")
        try:
            ctx = support.make_context(text=".status", args=[])
            support.run(status_cmd(ctx))
            self.assertIn("Always online: enabled", ctx.message.replies[0])
        finally:
            set_pref("online_always", "0")


if __name__ == "__main__":
    unittest.main()
