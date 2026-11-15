// Summary route in worker.js. Run:  node --test integrations/watchdog/test_summarize.mjs
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createHmac } from 'node:crypto';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), 'reze-summary-'));
const copy = join(dir, 'worker.mjs');
writeFileSync(copy, readFileSync(join(here, 'worker.js'), 'utf8'));
const worker = (await import(pathToFileURL(copy).href)).default;

const SECRET = 's'.repeat(40);
const KEY = 'sk-or-test-key-not-real';
const ctx = { waitUntil() {} };

const telegram = [];
const ai = { status: 200, reply: '• Launch on 2026-11-20 at 12:00\n• Price is 120 USD', calls: [] };
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init = {}) => {
  const url = String(input);
  if (url.startsWith('https://api.telegram.org/')) {
    telegram.push(url);
    return new Response(JSON.stringify({ ok: true, result: {} }), { headers: { 'content-type': 'application/json' } });
  }
  if (url.endsWith('/chat/completions')) {
    ai.calls.push({ url, headers: init.headers, body: JSON.parse(init.body) });
    if (ai.status !== 200) return new Response('upstream down', { status: ai.status });
    return new Response(JSON.stringify({ choices: [{ message: { content: ai.reply } }] }), { headers: { 'content-type': 'application/json' } });
  }
  return realFetch(input, init);
};

function memKV() {
  const m = new Map();
  return {
    _m: m,
    async get(k) { return m.has(k) ? m.get(k) : null; },
    async put(k, v) { m.set(k, String(v)); },
    async delete(k) { m.delete(k); },
  };
}

function env(overrides = {}) {
  return { WEBHOOK_SECRET: 'w'.repeat(24), BOT_TOKEN: '1:T', OWNER_ID: '555', REZE_BRIDGE_SECRET: SECRET, AI_GATEWAY_API_KEY: KEY, KV: memKV(), ...overrides };
}

function signed(bodyText, { ts = Math.floor(Date.now() / 1000), sig, secret = SECRET } = {}) {
  const signature = sig ?? createHmac('sha256', secret).update(`${ts}.${bodyText}`).digest('hex');
  return new Request('https://worker.test/reze/summarize', {
    method: 'POST',
    headers: { 'x-reze-timestamp': String(ts), 'x-reze-signature': signature, 'content-type': 'application/json' },
    body: bodyText,
  });
}

const post = (i, text) => ({ channel: 'Market News', date: '2026-11-13 09:00', text: `${text} ${i}` });
const bodyOf = (posts) => JSON.stringify({ posts });

function reset() { telegram.length = 0; ai.status = 200; ai.calls.length = 0; ai.reply = '• Launch on 2026-11-20 at 12:00\n• Price is 120 USD'; }

test('a signed request returns a summary and calls the model once', async () => {
  reset();
  const e = env();
  const r = await worker.fetch(signed(bodyOf([post(1, 'Launch on 2026-11-20 at 12:00'), post(2, 'Price is 120 USD')])), e, ctx);
  assert.equal(r.status, 200);
  const json = await r.json();
  assert.equal(json.ok, true);
  assert.match(json.summary, /2026-11-20/);
  assert.equal(json.posts, 2);
  assert.equal(ai.calls.length, 1);
  assert.equal(ai.calls[0].headers.authorization, `Bearer ${KEY}`);
  assert.match(ai.calls[0].body.messages[0].content, /untrusted/);
  assert.match(ai.calls[0].body.messages[1].content, /Launch on 2026-11-20/);
});

test('more than 40 posts is refused, not silently cut', async () => {
  reset();
  const posts = Array.from({ length: 41 }, (_, i) => post(i, 'x'));
  const r = await worker.fetch(signed(bodyOf(posts)), env(), ctx);
  assert.equal(r.status, 400);
  assert.equal((await r.json()).error, 'too_many_posts');
  assert.equal(ai.calls.length, 0);
});

test('an empty list of posts is refused', async () => {
  reset();
  const r = await worker.fetch(signed(bodyOf([])), env(), ctx);
  assert.equal(r.status, 400);
});

test('without an AI key the route says so and does not call the model', async () => {
  reset();
  const r = await worker.fetch(signed(bodyOf([post(1, 'hi')])), env({ AI_GATEWAY_API_KEY: '' }), ctx);
  assert.equal(r.status, 503);
  assert.equal((await r.json()).error, 'ai_not_configured');
  assert.equal(ai.calls.length, 0);
});

test('a model error becomes a clear error, not a fake summary', async () => {
  reset();
  ai.status = 500;
  const r = await worker.fetch(signed(bodyOf([post(1, 'hi')])), env(), ctx);
  assert.equal(r.status, 502);
  assert.equal((await r.json()).error, 'ai_failed');
});

test('an oversized body is refused before any work', async () => {
  reset();
  const big = bodyOf([{ channel: 'c', date: 'd', text: 'a'.repeat(70000) }]);
  const r = await worker.fetch(signed(big), env(), ctx);
  assert.equal(r.status, 413);
  assert.equal(ai.calls.length, 0);
});

test('a wrong signature and a replayed request are both refused', async () => {
  reset();
  const e = env();
  const bad = await worker.fetch(signed(bodyOf([post(1, 'hi')]), { secret: 'z'.repeat(40) }), e, ctx);
  assert.equal(bad.status, 401);
  const body = bodyOf([post(2, 'once')]);
  const ts = Math.floor(Date.now() / 1000);
  const sig = createHmac('sha256', SECRET).update(`${ts}.${body}`).digest('hex');
  assert.equal((await worker.fetch(signed(body, { ts, sig }), e, ctx)).status, 200);
  assert.equal((await worker.fetch(signed(body, { ts, sig }), e, ctx)).status, 409);
});

test('privacy: no post text is stored, and nothing is sent to Telegram', async () => {
  reset();
  const e = env();
  const secretPhrase = 'THE-OWNERS-PRIVATE-CHANNEL-TEXT-42';
  await worker.fetch(signed(bodyOf([post(1, secretPhrase)])), e, ctx);
  assert.equal(telegram.length, 0, 'nothing sent to Telegram');
  for (const [key, value] of e.KV._m) {
    assert.ok(key.startsWith('reze:seen:'), `only replay keys are written, saw ${key}`);
    assert.equal(String(value).includes(secretPhrase), false);
  }
});
