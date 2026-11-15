"""REZE 4.0: the real Reze client talks to the real Watchdog worker over HTTP.

The worker (integrations/watchdog/worker.js) runs under Node in a small HTTP server. Telegram is
stubbed, because this test must not reach the network. Skipped when Node is not installed.
"""

import asyncio
import json
import os
import shutil
import socket
import subprocess
import tempfile
import time
import unittest

import support  # noqa: F401  - prepares the shared database before reze imports

from reze.config import settings
from reze.integrations import watchdog
from reze.storage import secret_store

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(HERE, "..", "integrations", "watchdog", "worker.js")
BRIDGE = "e" * 40
SERVER_JS = r"""
import http from 'node:http';
import { writeFileSync, readFileSync } from 'node:fs';
const [workerPath, port, outPath, bridge] = process.argv.slice(2);
const { default: worker } = await import(workerPath);
const telegram = [];
globalThis.fetch = async (input, init = {}) => {
  const url = String(input);
  if (url.startsWith('https://api.telegram.org/')) {
    if (url.endsWith('/sendMessage')) telegram.push(JSON.parse(init.body));
    return new Response(JSON.stringify({ ok: true, result: {} }), { headers: { 'content-type': 'application/json' } });
  }
  if (url.endsWith('/chat/completions')) {
    // Stand-in for the AI provider: one supported line and one with a number the posts do not contain.
    return new Response(JSON.stringify({ choices: [{ message: { content: '• Launch on 2026-11-20\n• Price 999 USD' } }] }), { headers: { 'content-type': 'application/json' } });
  }
  return new Response('', { status: 404 });
};
const kv = new Map();
const KV = {
  async get(k, t) { const v = kv.get(k); return v === undefined ? null : (t === 'json' ? JSON.parse(v) : v); },
  async put(k, v) { kv.set(k, String(v)); },
  async delete(k) { kv.delete(k); },
};
const env = { WEBHOOK_SECRET: 'w'.repeat(20), BOT_TOKEN: '111:TEST', OWNER_ID: '555', REZE_BRIDGE_SECRET: bridge, AI_GATEWAY_API_KEY: 'k'.repeat(12), KV };
http.createServer(async (req, res) => {
  let body = '';
  for await (const chunk of req) body += chunk;
  const request = new Request('http://127.0.0.1' + req.url, { method: req.method, headers: req.headers, body: body || undefined });
  const response = await worker.fetch(request, env, { waitUntil() {} });
  writeFileSync(outPath, JSON.stringify(telegram));
  res.writeHead(response.status, { 'content-type': 'text/plain' });
  res.end(await response.text());
}).listen(Number(port), '127.0.0.1');
"""


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class WatchdogEndToEnd(unittest.TestCase):
    def setUp(self):
        self._vault = settings.vault_key
        settings.vault_key = "e2e-vault-key-for-tests-0123456789abcdef"
        self._url = os.environ.pop("REZE_WATCHDOG_URL", None)
        self.dir = tempfile.mkdtemp(prefix="reze-watchdog-e2e-")
        self.out = os.path.join(self.dir, "telegram.json")
        script = os.path.join(self.dir, "server.mjs")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(SERVER_JS)
        self.port = _free_port()
        worker_copy = os.path.join(self.dir, "worker.mjs")
        with open(WORKER, encoding="utf-8") as src, open(worker_copy, "w", encoding="utf-8") as dst:
            dst.write(src.read())
        self.proc = subprocess.Popen(
            ["node", script, "file://" + worker_copy, str(self.port), self.out, BRIDGE],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        os.environ["REZE_WATCHDOG_URL"] = f"http://127.0.0.1:{self.port}"
        secret_store.store(watchdog.BRIDGE_SECRET, BRIDGE)
        self._wait_ready()

    def tearDown(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)
        secret_store.forget(watchdog.BRIDGE_SECRET)
        os.environ.pop("REZE_WATCHDOG_URL", None)
        if self._url is not None:
            os.environ["REZE_WATCHDOG_URL"] = self._url
        settings.vault_key = self._vault
        shutil.rmtree(self.dir, ignore_errors=True)

    def _wait_ready(self):
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.2)
        self.fail("the worker server did not start: " + self.proc.stderr.read().decode("utf-8", "replace")[:300])

    def test_a_signed_event_is_accepted_and_forwarded_to_the_owner(self):
        self.assertTrue(watchdog.send_event_blocking("started", "Reze test run."))
        with open(self.out, encoding="utf-8") as handle:
            messages = json.load(handle)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["chat_id"], "555")
        self.assertIn("Reze · started", messages[0]["text"])
        self.assertIn("Reze test run.", messages[0]["text"])

    def test_a_summary_goes_through_the_real_worker_and_is_checked(self):
        from reze import consent
        from reze.integrations import watchdog as wd
        consent.grant("watchdog.channel_posts")
        try:
            posts = [{"channel": "News", "date": "2026-11-13 09:00", "text": "Launch on 2026-11-20 at the fair."}]
            result = asyncio.run(wd.summarize_posts(posts))
        finally:
            consent.revoke("watchdog.channel_posts")
        self.assertIn("2026-11-20", result["summary"])
        self.assertNotIn("999", result["summary"])
        self.assertEqual(result["removed"], 1)
        with open(self.out, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), [], "the worker sent nothing to Telegram for a summary")

    def test_a_wrong_bridge_secret_is_refused_by_the_worker(self):
        secret_store.store(watchdog.BRIDGE_SECRET, "f" * 40)
        self.assertFalse(watchdog.send_event_blocking("started", "should not arrive"))
        self.assertFalse(os.path.exists(self.out) and "should not arrive" in open(self.out, encoding="utf-8").read())


if __name__ == "__main__":
    unittest.main()
