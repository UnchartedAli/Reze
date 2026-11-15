// X4 channel autopilot in worker.js: drafts with media or forwards, copy on publish, and the channel note.
// Real SQL through node:sqlite behind the D1 API; Telegram is stubbed. Run:
//   node --test integrations/watchdog/test_autopilot.mjs
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { DatabaseSync } from 'node:sqlite';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const here = dirname(fileURLToPath(import.meta.url));
const dir = mkdtempSync(join(tmpdir(), 'reze-autopilot-'));
const workerSource = readFileSync(join(here, 'worker.js'), 'utf8');

const SECRET = 'w'.repeat(24);
const OWNER = 555;
const STRANGER = 999;
const CHAN = -1001000000777;

// ---- D1 on node:sqlite (only the calls the worker uses) ----
function makeD1() {
  const db = new DatabaseSync(':memory:');
  const clean = (args) => args.map((v) => (v === undefined ? null : v));
  return {
    _db: db,
    prepare(sql) {
      const state = { args: [] };
      const stmt = {
        bind(...args) { state.args = clean(args); return stmt; },
        async run() { const info = db.prepare(sql).run(...state.args); return { success: true, meta: { changes: info.changes } }; },
        async first() { return db.prepare(sql).get(...state.args) ?? null; },
        async all() { return { results: db.prepare(sql).all(...state.args) }; },
      };
      return stmt;
    },
    async batch(stmts) {
      const out = [];
      for (const s of stmts) out.push(await s.run());
      return out;
    },
  };
}

function memKV() {
  const m = new Map();
  return {
    _m: m,
    async get(k, type) { const v = m.get(k); if (v === undefined) return null; return type === 'json' ? JSON.parse(v) : v; },
    async put(k, v) { m.set(k, String(v)); },
    async delete(k) { m.delete(k); },
  };
}

// ---- Telegram stub ----
let calls = [];
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init = {}) => {
  const url = String(input);
  if (url.startsWith('https://api.telegram.org/')) {
    const method = url.split('/').pop();
    calls.push({ method, body: init.body ? JSON.parse(init.body) : {} });
    const result = method === 'getChat' ? { title: 'Market', username: 'market' } : method === 'getChatMemberCount' ? 10 : { message_id: 9001 };
    return new Response(JSON.stringify({ ok: true, result }), { headers: { 'content-type': 'application/json' } });
  }
  return realFetch(input, init);
};

let instance = 0;
let worker;
let env;
async function setup() {
  instance++;
  const path = join(dir, `worker-${instance}.mjs`);
  writeFileSync(path, workerSource);
  worker = (await import(pathToFileURL(path).href)).default;
  env = { WEBHOOK_SECRET: SECRET, BOT_TOKEN: '111:TEST', OWNER_ID: String(OWNER), TIMEZONE: 'Asia/Tehran', DB: makeD1(), KV: memKV() };
  calls = [];
  // first call creates the X4 and draft tables, exactly as the worker does on its own
  await callback(OWNER, 'xd:show:0');
  env.DB._db.exec(`INSERT INTO x4_chan (chan_id, title, uname, adder_id, created, active, plan, analyzed, last_gen, per_day)
    VALUES (${CHAN}, 'Market', 'market', ${OWNER}, ${Date.now()}, 0, '', 0, '', 2)`);
  calls = [];
}

let nextId = 1;
async function send(update) {
  const pending = [];
  const req = new Request('https://worker.test/webhook', {
    method: 'POST',
    headers: { 'X-Telegram-Bot-Api-Secret-Token': SECRET, 'content-type': 'application/json' },
    body: JSON.stringify({ update_id: nextId++, ...update }),
  });
  const res = await worker.fetch(req, env, { waitUntil: (p) => pending.push(p) });
  await Promise.all(pending.map((p) => Promise.resolve(p).catch(() => {})));
  return res.status;
}
async function callback(from, data) {
  return send({ callback_query: { id: String(nextId), from: { id: from, is_bot: false, first_name: 'U' }, message: { message_id: 5, date: 1, chat: { id: from, type: 'private' }, text: 'x' }, data } });
}
async function dm(from, fields, messageId = 70) {
  return send({ message: { message_id: messageId, date: 1, chat: { id: from, type: 'private' }, from: { id: from, is_bot: false, first_name: 'O' }, ...fields } });
}
const photo = { photo: [{ file_id: 'f', file_unique_id: 'u', width: 10, height: 10 }] };
const draftRow = (id) => env.DB._db.prepare('SELECT * FROM content_drafts WHERE id = ?').get(id);
function addDraft(body = 'old body') {
  env.DB._db.exec(`INSERT INTO content_drafts (chan_id, owner_id, body, status, publish_at, tries, created)
    VALUES (${CHAN}, ${OWNER}, '${body}', 'pending', 0, 0, ${Date.now()})`);
  return env.DB._db.prepare('SELECT MAX(id) AS id FROM content_drafts').get().id;
}
const methods = () => calls.map((c) => c.method);

test('media sent for an edit is copied to the channel without a forward header', async () => {
  await setup();
  const id = addDraft();
  await callback(OWNER, `xd:ed:${id}`);
  await dm(OWNER, { ...photo, caption: 'new caption' }, 77);
  assert.equal(draftRow(id).copy_from, `${OWNER}:77`);
  assert.equal(draftRow(id).body, 'new caption');
  calls = [];
  await callback(OWNER, `xd:now:${id}`);
  const copy = calls.find((c) => c.method === 'copyMessage');
  assert.ok(copy, 'published with copyMessage');
  assert.deepEqual(copy.body, { chat_id: CHAN, from_chat_id: OWNER, message_id: 77 });
  assert.equal(methods().includes('forwardMessage'), false, 'no forward header');
  assert.equal(draftRow(id).status, 'published');
});

test('a forwarded message is copied, not forwarded', async () => {
  await setup();
  const id = addDraft();
  await callback(OWNER, `xd:ed:${id}`);
  await dm(OWNER, { text: 'a post from elsewhere', forward_origin: { type: 'user', date: 1, sender_user: { id: 4, is_bot: false, first_name: 'X' } } }, 88);
  assert.equal(draftRow(id).copy_from, `${OWNER}:88`);
  calls = [];
  await callback(OWNER, `xd:now:${id}`);
  assert.equal(calls.find((c) => c.method === 'copyMessage').body.message_id, 88);
  assert.equal(methods().includes('forwardMessage'), false);
});

test('a plain text edit replaces the body and clears the copy source', async () => {
  await setup();
  const id = addDraft();
  await callback(OWNER, `xd:ed:${id}`);
  await dm(OWNER, { ...photo, caption: 'x' }, 90);
  assert.equal(draftRow(id).copy_from, `${OWNER}:90`);
  await callback(OWNER, `xd:ed:${id}`);
  await dm(OWNER, { text: 'plain new body' }, 91);
  assert.equal(draftRow(id).copy_from, null);
  assert.equal(draftRow(id).body, 'plain new body');
  calls = [];
  await callback(OWNER, `xd:now:${id}`);
  assert.equal(calls.find((c) => c.method === 'sendMessage' && c.body.chat_id === CHAN).body.text, 'plain new body');
});

test('someone else cannot edit the owner draft', async () => {
  await setup();
  const id = addDraft();
  await callback(STRANGER, `xd:ed:${id}`);
  await dm(STRANGER, { ...photo, caption: 'hijack' }, 92);
  assert.equal(draftRow(id).copy_from, null);
  assert.equal(draftRow(id).body, 'old body');
});

test('the channel note is saved, replaced, and cleared from the card button', async () => {
  await setup();
  await callback(OWNER, `xc:cd:${CHAN}`);
  await dm(OWNER, { text: 'We teach beginners how to read crypto charts.' }, 93);
  assert.equal(await env.KV.get(`x4:note:${CHAN}`), 'We teach beginners how to read crypto charts.');
  await callback(OWNER, `xc:cd:${CHAN}`);
  await dm(OWNER, { text: 'reset' }, 94);
  assert.equal(await env.KV.get(`x4:note:${CHAN}`), null);
});

test('the channel note button is refused for people who are not admins of the channel', async () => {
  await setup();
  await callback(STRANGER, `xc:cd:${CHAN}`);
  await dm(STRANGER, { text: 'sneaky note' }, 95);
  assert.equal(await env.KV.get(`x4:note:${CHAN}`), null);
});

test('the channel note is capped in length', async () => {
  await setup();
  await callback(OWNER, `xc:cd:${CHAN}`);
  await dm(OWNER, { text: 'n'.repeat(3000) }, 96);
  assert.equal((await env.KV.get(`x4:note:${CHAN}`)).length, 1500);
});
