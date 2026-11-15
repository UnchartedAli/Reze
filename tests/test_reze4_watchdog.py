"""REZE 4.0: encrypted secrets, the Watchdog bridge, and the sticker bot's default identity."""

import asyncio
import os
import unittest
import urllib.error
from unittest import mock

import support  # noqa: F401  - prepares the shared database before reze imports

from reze.config import settings
from reze.database import db
from reze.integrations import watchdog
from reze.media import stickerbot
from reze.storage import secret_store

VAULT = "vault-key-for-watchdog-tests-0123456789"
BRIDGE = "b" * 40
STICKER_TOKEN = "123456:SECRET-STICKER-TOKEN-VALUE-FOR-TESTS"
ENV_KEYS = ("REZE_STICKER_BOT_TOKEN", "REZE_STICKER_BOT_USERNAME", "REZE_WATCHDOG_BRIDGE_SECRET", "REZE_WATCHDOG_URL")


class Base(unittest.TestCase):
    def setUp(self):
        self._vault = settings.vault_key
        self._env = {key: os.environ.pop(key, None) for key in ENV_KEYS}
        settings.vault_key = VAULT
        self._clean()

    def tearDown(self):
        settings.vault_key = self._vault
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._clean()

    def _clean(self):
        secret_store.forget(stickerbot.STICKER_SECRET)
        secret_store.forget(watchdog.BRIDGE_SECRET)
        stickerbot._username_cache.clear()


class SecretStoreTests(Base):
    def test_nothing_is_stored_without_a_vault_key(self):
        settings.vault_key = ""
        with self.assertRaisesRegex(secret_store.SecretStoreError, "REZE_VAULT_KEY"):
            secret_store.store("test_secret", "value")
        self.assertFalse(secret_store.is_stored("test_secret"))

    def test_round_trip_and_nothing_readable_on_disk(self):
        secret_store.store("test_secret", "plain-value-xyz")
        self.assertEqual(secret_store.read("test_secret"), "plain-value-xyz")
        raw = db.get_setting("secret.test_secret", None)
        self.assertTrue(raw.startswith("v1:"))
        self.assertNotIn("plain-value-xyz", raw)
        secret_store.forget("test_secret")
        self.assertIsNone(secret_store.read("test_secret"))

    def test_a_different_vault_key_cannot_open_it(self):
        secret_store.store("test_secret", "guarded")
        settings.vault_key = "another-vault-key-0123456789abcdefgh"
        with self.assertRaisesRegex(secret_store.SecretStoreError, "cannot be opened"):
            secret_store.read("test_secret")
        secret_store.forget("test_secret")

    def test_environment_value_moves_into_the_store_once(self):
        os.environ["REZE_STICKER_BOT_TOKEN"] = STICKER_TOKEN
        self.assertTrue(secret_store.import_from_env(stickerbot.STICKER_SECRET, "REZE_STICKER_BOT_TOKEN"))
        self.assertFalse(secret_store.import_from_env(stickerbot.STICKER_SECRET, "REZE_STICKER_BOT_TOKEN"))
        os.environ.pop("REZE_STICKER_BOT_TOKEN")
        self.assertEqual(stickerbot.token(), STICKER_TOKEN, "still available after the variable is removed")

    def test_without_a_vault_key_the_environment_keeps_working_unencrypted(self):
        settings.vault_key = ""
        os.environ["REZE_STICKER_BOT_TOKEN"] = STICKER_TOKEN
        self.assertEqual(stickerbot.token(), STICKER_TOKEN)
        self.assertFalse(secret_store.is_stored(stickerbot.STICKER_SECRET))


class StickerBotIdentityTests(Base):
    def test_default_sticker_bot_is_the_watchdog(self):
        self.assertEqual(stickerbot.expected_username(), "watchdogappbot")

    def test_the_default_can_be_overridden(self):
        os.environ["REZE_STICKER_BOT_USERNAME"] = "@otherbot"
        self.assertEqual(stickerbot.expected_username(), "otherbot")

    def test_a_token_for_another_bot_is_refused(self):
        async def fake_api(token, method, fields=None, *a, **kw):
            return {"username": "someonelse_bot"}

        with mock.patch.object(stickerbot, "api", side_effect=fake_api):
            with self.assertRaisesRegex(stickerbot.StickerBotError, "belongs to @someonelse_bot"):
                asyncio.run(stickerbot.bot_username("999:TOKEN"))

    def test_the_watchdog_token_is_accepted_and_cached(self):
        calls = []

        async def fake_api(token, method, fields=None, *a, **kw):
            calls.append(method)
            return {"username": "WatchdogAppBot"}

        with mock.patch.object(stickerbot, "api", side_effect=fake_api):
            self.assertEqual(asyncio.run(stickerbot.bot_username("999:TOKEN")), "WatchdogAppBot")
            self.assertEqual(asyncio.run(stickerbot.bot_username("999:TOKEN")), "WatchdogAppBot")
        self.assertEqual(calls, ["getMe"], "checked once per token")


class WatchdogClientTests(Base):
    def test_default_url_is_the_watchdog_worker(self):
        self.assertEqual(watchdog.url(), "https://amo.alimmazza043.workers.dev")

    def test_a_plain_http_url_is_refused(self):
        os.environ["REZE_WATCHDOG_URL"] = "http://example.com"
        with self.assertRaisesRegex(watchdog.WatchdogError, "https"):
            watchdog.url()

    def test_the_signature_is_hmac_over_timestamp_and_body(self):
        body, headers = watchdog.build_request(BRIDGE, "test", "hi", now=1700000000)
        self.assertEqual(body, b'{"kind": "test", "text": "hi"}')
        self.assertEqual(headers["X-Reze-Timestamp"], "1700000000")
        self.assertEqual(
            headers["X-Reze-Signature"],
            "9bf0e7726f8ce7867983805f8fd1f8293056a97e604afc5ac33f866e2a218b50",
            "the same value is verified by integrations/watchdog/test_bridge.mjs",
        )

    def test_text_is_flattened_and_capped(self):
        body, _ = watchdog.build_request(BRIDGE, "x", "line one\n\nline   two " + "z" * 900, now=1)
        self.assertNotIn(b"\n", body)
        self.assertLessEqual(len(body), 600)

    def test_no_stored_secret_means_no_event_is_sent(self):
        with mock.patch("urllib.request.urlopen") as opened:
            self.assertFalse(watchdog.send_event_blocking("test", "hi"))
            opened.assert_not_called()

    def test_a_delivered_event_returns_true_with_the_expected_request(self):
        secret_store.store(watchdog.BRIDGE_SECRET, BRIDGE)
        response = mock.MagicMock(status=200)
        response.__enter__.return_value = response
        with mock.patch("urllib.request.urlopen", return_value=response) as opened:
            self.assertTrue(watchdog.send_event_blocking("test", "hello"))
        request = opened.call_args[0][0]
        self.assertEqual(request.full_url, "https://amo.alimmazza043.workers.dev/reze/event")
        self.assertEqual(request.get_method(), "POST")
        headers = {k.lower(): v for k, v in request.header_items()}
        self.assertIn("x-reze-signature", headers)
        self.assertIn("x-reze-timestamp", headers)
        self.assertEqual(len(headers["x-reze-signature"]), 64)

    def test_network_failures_return_false_and_never_leak_the_secret(self):
        secret_store.store(watchdog.BRIDGE_SECRET, BRIDGE)
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
            with self.assertLogs("reze", level="WARNING") as logged:
                self.assertFalse(watchdog.send_event_blocking("test", "hello"))
        self.assertNotIn(BRIDGE, " ".join(logged.output))

    def test_a_short_bridge_secret_is_not_used(self):
        secret_store.store(watchdog.BRIDGE_SECRET, "too-short")
        self.assertIsNone(watchdog.bridge_secret())


if __name__ == "__main__":
    unittest.main()
