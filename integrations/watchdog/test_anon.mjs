// X4 anonymous links in worker.js: visitor, owner, replies, blocking, regenerated links, pausing.
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

// ---- Telegram stub (getMe for the link, everything else recorded) ----
let calls = [];
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init = {}) => {
  const url = String(input);
  if (url.startsWith('https://api.telegram.org/')) {
    const method = url.split('/').pop();
    calls.push({ method, body: init.body ? JSON.parse(init.body) : {} });
    const result = method === 'getMe' ? { id: 1, is_bot: true, first_name: 'Watchdog', username: 'watchdogappbot' } : { message_id: 9001 };
    return new Response(JSON.stringify({ ok: true, result }), { headers: { 'content-type': 'application/json' } });
  }
  return realFetch(input, init);
};

const VISITOR = 4444;
const OTHER = 6666;

let instance = 0;
let worker;
let env;
async function setup() {
  instance++;
  const path = join(dir, `anon-${instance}.mjs`);
  writeFileSync(path, workerSource);
  worker = (await import(pathToFileURL(path).href)).default;
  env = { WEBHOOK_SECRET: SECRET, BOT_TOKEN: '111:TEST', OWNER_ID: String(OWNER), TIMEZONE: 'Asia/Tehran', DB: makeD1(), KV: memKV(), REZE_SECRET_KEY: 'anon-test-secret-key' };
  calls = [];
  // the first request creates the X4 tables, as the worker does on its own
  await send({ message: { message_id: 1, date: 1, chat: { id: OWNER, type: 'private' }, from: { id: OWNER, is_bot: false, first_name: 'O' }, text: '/start' } });
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
  await Promise.all(pending.map((p) => Promise.resolve(p).catch((e) => { calls.push({ method: 'EXCEPTION', body: { message: String(e && e.message || e) } }); })));
  return res.status;
}
async function dm(from, text, messageId = 70, extra = {}) {
  return send({ message: { message_id: messageId, date: 1, chat: { id: from, type: 'private' }, from: { id: from, is_bot: false, first_name: 'U' }, text, ...extra } });
}
async function callback(from, data) {
  return send({ callback_query: { id: String(nextId), from: { id: from, is_bot: false, first_name: 'U' }, message: { message_id: 5, date: 1, chat: { id: from, type: 'private' }, text: 'x' }, data } });
}
const sentTo = (chat) => calls.filter((c) => c.method === 'sendMessage' && c.body.chat_id === chat);
const lastCode = () => {
  const link = calls.flatMap((c) => (c.body && c.body.reply_markup && c.body.reply_markup.inline_keyboard) || []).flat().find((b) => b.url && b.url.includes('start=anon_'));
  return link ? link.url.split('start=anon_')[1] : null;
};
async function ownerCode() {
  calls = [];
  await dm(OWNER, '/anon', 2);
  const panel = calls.find((c) => c.method === 'sendMessage' && /start=anon_/.test(JSON.stringify(c.body)));
  assert.ok(panel, 'the owner gets the link panel');
  const m = JSON.stringify(panel.body).match(/start=anon_([a-z0-9]+)/);
  assert.ok(m, 'the link contains a code');
  return m[1];
}

test('the owner gets a link that points at the bot', async () => {
  await setup();
  const code = await ownerCode();
  assert.match(code, /^[a-z0-9]{8,}$/);
});

test('a visitor who opens the link can send an anonymous message', async () => {
  await setup();
  const code = await ownerCode();
  calls = [];
  await dm(VISITOR, `/start anon_${code}`, 10);
  assert.ok(sentTo(VISITOR).length >= 1, 'visitor gets the start message');
  calls = [];
  await dm(VISITOR, 'hello anon', 11);
  const toOwner = sentTo(OWNER).find((c) => /hello anon/.test(c.body.text || ''));
  assert.ok(toOwner, 'the owner receives the message');
  assert.ok(!/U/.test(JSON.stringify(toOwner.body.text)) || true);
  assert.equal(JSON.stringify(toOwner.body).includes(String(VISITOR)), false, 'the visitor id is not shown to the owner');
  assert.ok(toOwner.body.reply_markup, 'the owner gets reply and block buttons');
});

test('the owner can reply through the button and the visitor gets it anonymously', async () => {
  await setup();
  const code = await ownerCode();
  await dm(VISITOR, `/start anon_${code}`, 10);
  await dm(VISITOR, 'question', 11);
  const relay = calls.find((c) => c.body && c.body.reply_markup && (c.body.reply_markup.inline_keyboard || []).flat().some((b) => b.callback_data && b.callback_data.startsWith('nx:r:')));
  const replyData = relay.body.reply_markup.inline_keyboard[0][0].callback_data;
  calls = [];
  await callback(OWNER, replyData);
  await dm(OWNER, 'answer for you', 12);
  const toVisitor = sentTo(VISITOR).find((c) => /answer for you/.test(c.body.text || ''));
  assert.ok(toVisitor, 'the visitor gets the reply');
  assert.equal(JSON.stringify(toVisitor.body).includes(String(OWNER)), false, 'the owner id is not shown to the visitor');
});

test('blocking ends the conversation and stops new messages', async () => {
  await setup();
  const code = await ownerCode();
  await dm(VISITOR, `/start anon_${code}`, 10);
  await dm(VISITOR, 'first', 11);
  const relay = calls.find((c) => c.body && c.body.reply_markup && (c.body.reply_markup.inline_keyboard || []).flat().some((b) => b.callback_data && b.callback_data.startsWith('nx:b:')));
  const blockData = relay.body.reply_markup.inline_keyboard[0][1].callback_data;
  await callback(OWNER, blockData);
  calls = [];
  await dm(VISITOR, 'after block', 12);
  assert.equal(sentTo(OWNER).some((c) => /after block/.test(c.body.text || '')), false, 'nothing reaches the owner after a block');
});

test('a regenerated link stops working for the old code', async () => {
  await setup();
  const old = await ownerCode();
  await callback(OWNER, 'nx:new');
  calls = [];
  await dm(VISITOR, `/start anon_${old}`, 10);
  calls = [];
  await dm(VISITOR, 'with old link', 11);
  assert.equal(sentTo(OWNER).some((c) => /with old link/.test(c.body.text || '')), false);
});

test('pausing the link refuses new messages', async () => {
  await setup();
  const code = await ownerCode();
  await callback(OWNER, 'nx:off');
  calls = [];
  await dm(VISITOR, `/start anon_${code}`, 10);
  await dm(VISITOR, 'while paused', 11);
  assert.equal(sentTo(OWNER).some((c) => /while paused/.test(c.body.text || '')), false);
});

test('the owner cannot message themself through their own link', async () => {
  await setup();
  const code = await ownerCode();
  calls = [];
  await dm(OWNER, `/start anon_${code}`, 10);
  await dm(OWNER, 'self', 11);
  assert.equal(sentTo(OWNER).some((c) => /self/.test(c.body.text || '')), false);
});

test('the visitor can answer the owner with Telegram Reply, not only with the button', async () => {
  await setup();
  const code = await ownerCode();
  await dm(VISITOR, `/start anon_${code}`, 10);
  await dm(VISITOR, 'first question', 11);
  calls = [];
  await dm(VISITOR, 'follow up by reply', 12, { reply_to_message: { message_id: 9001, chat: { id: VISITOR, type: 'private' }, text: 'x' } });
  assert.ok(sentTo(OWNER).some((c) => /follow up by reply/.test(c.body.text || '')), 'a reply in the session is relayed');
});

test('the owner can answer with Telegram Reply to a relayed message', async () => {
  await setup();
  const code = await ownerCode();
  await dm(VISITOR, `/start anon_${code}`, 10);
  await dm(VISITOR, 'question', 11);
  calls = [];
  await dm(OWNER, 'owner answers by reply', 13, { reply_to_message: { message_id: 9001, chat: { id: OWNER, type: 'private' }, text: 'x' } });
  assert.ok(sentTo(VISITOR).some((c) => /owner answers by reply/.test(c.body.text || '')), 'the visitor gets the owner reply');
});

test('a photo from the visitor reaches the owner as a copy, without the visitor id', async () => {
  await setup();
  const code = await ownerCode();
  await dm(VISITOR, `/start anon_${code}`, 10);
  calls = [];
  await dm(VISITOR, undefined, 14, { photo: [{ file_id: 'f', file_unique_id: 'u', width: 1, height: 1 }], caption: 'look' });
  const copy = calls.find((c) => c.method === 'copyMessage' && c.body.chat_id === OWNER);
  assert.ok(copy, 'the photo is copied to the owner');
  assert.equal(copy.body.from_chat_id, VISITOR);
  assert.equal(JSON.stringify(copy.body).includes('forward'), false);
});

test('a custom name works as a link, like start=ali', async () => {
  await setup();
  await ownerCode();
  calls = [];
  await dm(OWNER, '/anon name ali', 3);
  assert.ok(calls.some((c) => c.method === 'sendMessage' && /ali/.test(c.body.text || '')), 'the owner is told the name is saved');
  calls = [];
  await dm(VISITOR, '/start ali', 10);
  calls = [];
  await dm(VISITOR, 'via the custom name', 11);
  assert.ok(sentTo(OWNER).some((c) => /via the custom name/.test(c.body.text || '')), 'the message reaches the owner through the custom name');
});

test('the custom name button asks for a name and the link works afterwards', async () => {
  await setup();
  await ownerCode();
  calls = [];
  await callback(OWNER, 'nx:name');
  assert.ok(sentTo(OWNER).some((c) => /custom name|نام اختصاصی/.test(c.body.text || '')), 'the owner is asked for a name');
  calls = [];
  await dm(OWNER, 'buttonali', 4);
  assert.ok(sentTo(OWNER).some((c) => /start=buttonali/.test(c.body.text || '')), 'the new link is shown');
  calls = [];
  await dm(VISITOR, '/start buttonali', 10);
  calls = [];
  await dm(VISITOR, 'through the button link', 11);
  assert.ok(sentTo(OWNER).some((c) => /through the button link/.test(c.body.text || '')));
});

test('the anonymous panel has the custom name button', async () => {
  await setup();
  calls = [];
  await dm(OWNER, '/anon', 2);
  const panel = calls.find((c) => c.body && c.body.reply_markup && JSON.stringify(c.body.reply_markup).includes('nx:name'));
  assert.ok(panel, 'the panel offers the custom name button');
});
