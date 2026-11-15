// Premium emoji packs in worker.js, driven through the real webhook.
// Run:  node --test integrations/watchdog/test_premium.mjs
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), 'reze-premium-'));
const copy = join(dir, 'worker.mjs');
writeFileSync(copy, readFileSync(join(here, 'worker.js'), 'utf8'));
const workerSource = readFileSync(join(here, 'worker.js'), 'utf8');
let instanceNo = 0;
// Each test loads its own copy of the worker, so module state cannot leak between tests.
async function setup() {
  instanceNo++;
  const path = join(dir, `worker-${instanceNo}.mjs`);
  writeFileSync(path, workerSource);
  const loaded = await import(pathToFileURL(path).href);
  worker = loaded.default;
  pureHelpers = { __premiumEmojiBody: loaded.__premiumEmojiBody, __premiumMergePacks: loaded.__premiumMergePacks };
  kv = memKV();
  env = { WEBHOOK_SECRET: SECRET, BOT_TOKEN: '111:TEST', OWNER_ID: String(OWNER), KV: kv };
  sent.length = 0;
}
let worker;
let pureHelpers;
const { __premiumMergePacks } = await import(pathToFileURL(copy).href);

const SECRET = 'w'.repeat(24);
const OWNER = 555;
const STRANGER = 999;

// Telegram stub: records sendMessage; answers getStickerSet from a table of packs.
const sent = [];
const packs = {
  packA: { title: 'Pack A', sticker_type: 'custom_emoji', stickers: [{ emoji: '🔥', custom_emoji_id: '1' }, { emoji: '🐕‍🦺', custom_emoji_id: '2' }] },
  packB: { title: 'Pack B', sticker_type: 'custom_emoji', stickers: [{ emoji: '🐕‍🦺', custom_emoji_id: '3' }, { emoji: '😎', custom_emoji_id: '4' }] },
  packC: { title: 'Pack C', sticker_type: 'custom_emoji', stickers: [{ emoji: '🌟', custom_emoji_id: '5' }] },
};
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init = {}) => {
  const url = String(input);
  if (url.startsWith('https://api.telegram.org/')) {
    const method = url.split('/').pop();
    if (method === 'sendMessage') sent.push(JSON.parse(init.body));
    if (method === 'getStickerSet') {
      const name = JSON.parse(init.body).name;
      const set = packs[name];
      return new Response(JSON.stringify(set ? { ok: true, result: set } : { ok: false, description: 'not found' }), { headers: { 'content-type': 'application/json' } });
    }
    return new Response(JSON.stringify({ ok: true, result: { message_id: 1 } }), { headers: { 'content-type': 'application/json' } });
  }
  return realFetch(input, init);
};

function memKV() {
  const m = new Map();
  return {
    _m: m,
    async get(k, type) { const v = m.get(k); if (v === undefined) return null; return type === 'json' ? JSON.parse(v) : v; },
    async put(k, v) { m.set(k, String(v)); },
    async delete(k) { m.delete(k); },
  };
}

let kv;
let env;

let updateId = 1;
async function say(text, from = OWNER) {
  const body = {
    update_id: updateId++,
    message: { message_id: updateId, date: Math.floor(Date.now() / 1000), chat: { id: from, type: 'private' }, from: { id: from, is_bot: false, first_name: 'Owner' }, text },
  };
  const req = new Request('https://worker.test/webhook', {
    method: 'POST',
    headers: { 'X-Telegram-Bot-Api-Secret-Token': SECRET, 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  const pending = [];
  const res = await worker.fetch(req, env, { waitUntil: (p) => pending.push(p) });
  await Promise.all(pending.map((p) => Promise.resolve(p).catch(() => {})));
  return res.status;
}

const savedPacks = () => JSON.parse(kv._m.get('cfg:premium_emoji_packs') || 'null');

test('the merge keeps every pack and joins ids for a shared emoji', () => {
  const merged = __premiumMergePacks({
    a: { map: { '🐕‍🦺': ['2'], '🔥': ['1'] } },
    b: { map: { '🐕‍🦺': ['3'], '😎': ['4'] } },
  });
  assert.deepEqual(merged['🐕‍🦺'].sort(), ['2', '3']);
  assert.deepEqual(merged['🔥'], ['1']);
  assert.deepEqual(merged['😎'], ['4']);
});

test('the merge accepts the old single-id format too', () => {
  const merged = __premiumMergePacks({ old: { map: { '🌟': '9' } } });
  assert.deepEqual(merged['🌟'], ['9']);
});

test('importing a second pack keeps the first', async () => {
  await setup();
  assert.equal(await say('/emojipack https://t.me/addemoji/packA'), 200);
  assert.equal(await say('/emojipack https://t.me/addemoji/packB'), 200);
  const stored = savedPacks();
  assert.deepEqual(Object.keys(stored).sort(), ['packA', 'packB']);
  assert.match(sent.at(-1).text, /2 پک فعال/);
});

test('/emojipack list shows each pack', async () => {
  await setup();
  await say('/emojipack https://t.me/addemoji/packA');
  await say('/emojipack https://t.me/addemoji/packB');
  sent.length = 0;
  await say('/emojipack list');
  assert.match(sent.at(-1).text, /Pack A/);
  assert.match(sent.at(-1).text, /Pack B/);
});

test('/emojipack remove deletes only that pack', async () => {
  await setup();
  await say('/emojipack https://t.me/addemoji/packA');
  await say('/emojipack https://t.me/addemoji/packB');
  await say('/emojipack remove packA');
  assert.deepEqual(Object.keys(savedPacks()), ['packB']);
  await say('/emojipack remove missing');
  assert.match(sent.at(-1).text, /پیدا نشد/);
});

test('an older single map is kept as a pack when a new one is imported', async () => {
  await setup();
  kv._m.set('cfg:premium_emoji_map', JSON.stringify({ '🌟': ['9'] }));
  await say('/emojipack https://t.me/addemoji/packA');
  const stored = savedPacks();
  assert.ok(stored.legacy, 'legacy map migrated into a pack');
  assert.ok(stored.packA, 'new pack added');
  assert.equal(kv._m.has('cfg:premium_emoji_map'), false, 'old key removed after migration');
});

test('a non-owner cannot change the packs', async () => {
  await setup();
  await say('/emojipack https://t.me/addemoji/packA', STRANGER);
  assert.equal(savedPacks(), null);
});

test('outgoing text uses the emoji of every imported pack', async () => {
  await setup();
  await say('/emojipack https://t.me/addemoji/packA');
  await say('/emojipack https://t.me/addemoji/packB');
  // The cache now holds both packs, as it does after a real import.
  const out = pureHelpers.__premiumEmojiBody(env, 'sendMessage', { chat_id: 1, text: 'hi 🔥 and 😎 and 🐕‍🦺' });
  const byEmoji = Object.fromEntries(out.entities.map((e) => [e.custom_emoji_id, true]));
  assert.ok(byEmoji['1'], 'fire from pack A');
  assert.ok(byEmoji['4'], 'sunglasses from pack B');
  assert.ok(byEmoji['2'] || byEmoji['3'], 'the dog from A or B (both packs have it)');
});
