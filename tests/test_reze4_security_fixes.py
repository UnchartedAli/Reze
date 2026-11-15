"""REZE 4.0 Milestone 1: client address resolution for login rate limiting."""

import unittest

import support  # noqa: F401  - prepares the database before reze imports

from reze.config import settings
from reze.web.app import RezePanelHandler


class _FakeRequest:
    """Minimal stand-in for the handler: only headers and client_address are used."""

    def __init__(self, headers, peer="198.51.100.7"):
        self.headers = headers
        self.client_address = (peer, 40000)


class ClientAddressTests(unittest.TestCase):
    def setUp(self):
        self._original_trust = settings.web_trust_proxy

    def tearDown(self):
        settings.web_trust_proxy = self._original_trust

    def _ip(self, headers, peer="198.51.100.7"):
        return RezePanelHandler.client_ip(_FakeRequest(headers, peer))

    def test_forwarding_headers_ignored_without_trusted_proxy(self):
        settings.web_trust_proxy = False
        headers = {"X-Forwarded-For": "203.0.113.9", "CF-Connecting-IP": "203.0.113.10"}
        self.assertEqual(self._ip(headers), "198.51.100.7")

    def test_forwarded_for_uses_last_entry_not_client_controlled_first(self):
        settings.web_trust_proxy = True
        self.assertEqual(self._ip({"X-Forwarded-For": "1.1.1.1, 2.2.2.2"}), "2.2.2.2")

    def test_rotating_spoofed_first_entry_does_not_change_the_address(self):
        settings.web_trust_proxy = True
        addresses = {
            self._ip({"X-Forwarded-For": f"10.0.{n}.1, 192.0.2.44"}) for n in range(50)
        }
        self.assertEqual(addresses, {"192.0.2.44"})

    def test_proxy_set_single_value_headers_are_preferred(self):
        settings.web_trust_proxy = True
        headers = {"CF-Connecting-IP": "192.0.2.50", "X-Forwarded-For": "1.1.1.1, 2.2.2.2"}
        self.assertEqual(self._ip(headers), "192.0.2.50")
        self.assertEqual(self._ip({"X-Real-IP": "192.0.2.60"}), "192.0.2.60")

    def test_falls_back_to_socket_peer_when_headers_are_empty(self):
        settings.web_trust_proxy = True
        self.assertEqual(self._ip({}, peer="198.51.100.9"), "198.51.100.9")


if __name__ == "__main__":
    unittest.main()
