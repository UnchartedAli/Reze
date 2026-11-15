// X4 reactions in worker.js: channel posts (allowed emoji), groups (chance), private chats (random).
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

// ---- Telegram stub: records calls; getChat returns the allowed reactions set per test ----
let calls = [];
let allowedFor = null; // null = the chat lists no restriction; an array = exactly these emoji
const realFetch = globalThis.fetch;
globalThis.fetch = async (input, init = {}) => {
  const url = String(input);
  if (url.startsWith('https://api.telegram.org/')) {
    const method = url.split('/').pop();
    const body = init.body ? JSON.parse(init.body) : {};
    calls.push({ method, body });
    let result = { message_id: 9001 };
    if (method === 'getChat') {
      result = { id: body.chat_id, type: 'channel', title: 'Chan' };
      if (allowedFor) result.available_reactions = allowedFor.map((emoji) => ({ type: 'emoji', emoji }));
    }
    if (method === 'getMe') result = { id: 1, is_bot: true, first_name: 'W', username: 'watchdogappbot' };
    return new Response(JSON.stringify({ ok: true, result }), { headers: { 'content-type': 'application/json' } });
  }
  return realFetch(input, init);
};

const FRIEND = 777;
const GROUP = -1001000000654;
const CHAN_TYPE = 'channel';

let instance = 0;
let worker;
let env;
async function setup() {
  instance++;
  const path = join(dir, `react-${instance}.mjs`);
  writeFileSync(path, workerSource);
  worker = (await import(pathToFileURL(path).href)).default;
  env = { WEBHOOK_SECRET: SECRET, BOT_TOKEN: '111:TEST', OWNER_ID: String(OWNER), TIMEZONE: 'Asia/Tehran', DB: makeD1(), KV: memKV(), REZE_SECRET_KEY: 'react-test-secret-key' };
  calls = [];
  allowedFor = null;
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
  await Promise.all(pending.map((p) => Promise.resolve(p).catch(() => {})));
  return res.status;
}
const reactions = () => calls.filter((c) => c.method === 'setMessageReaction');
const say = (from, text, messageId = 40) => send({ message: { message_id: messageId, date: 1, chat: { id: from, type: 'private' }, from: { id: from, is_bot: false, first_name: 'U' }, text } });
const channelPost = (messageId = 91, chat = CHAN) => send({ channel_post: { message_id: messageId, date: 1, chat: { id: chat, type: CHAN_TYPE, title: 'Chan' }, text: 'post' } });
const groupMessage = (messageId = 92, from = FRIEND, chat = GROUP) => send({ message: { message_id: messageId, date: 1, chat: { id: chat, type: 'supergroup', title: 'G' }, from: { id: from, is_bot: false, first_name: 'F' }, text: 'hello group' } });

test('channel post gets the one emoji the channel allows', async () => {
  await setup();
  await say(OWNER, '/react channel on', 2);
  allowedFor = ['🔥'];
  calls = [];
  await channelPost(91);
  const r = reactions();
  assert.equal(r.length, 1);
  assert.deepEqual(r[0].body.reaction, [{ type: 'emoji', emoji: '🔥' }]);
  assert.equal(r[0].body.message_id, 91);
  assert.equal(r[0].body.chat_id, CHAN);
});

test('channel reactions are off until the owner turns them on', async () => {
  await setup();
  allowedFor = ['🔥'];
  calls = [];
  await channelPost(91);
  assert.equal(reactions().length, 0);
});

test('a channel that allows no emoji gets no reaction', async () => {
  await setup();
  await say(OWNER, '/react channel on', 2);
  allowedFor = [];
  calls = [];
  await channelPost(91);
  assert.equal(reactions().length, 0);
});

test('group messages get a reaction when the chance comes up', async () => {
  await setup();
  await say(OWNER, '/react group on 100', 2);
  allowedFor = ['😎'];
  calls = [];
  await groupMessage(92);
  const r = reactions();
  assert.equal(r.length, 1);
  assert.deepEqual(r[0].body.reaction, [{ type: 'emoji', emoji: '😎' }]);
});

test('group chance 0 means no reactions in groups', async () => {
  await setup();
  await say(OWNER, '/react group on 0', 2);
  calls = [];
  await groupMessage(92);
  assert.equal(reactions().length, 0);
});

test('private messages get a random standard reaction', async () => {
  await setup();
  await say(OWNER, '/react private on', 2);
  calls = [];
  await say(FRIEND, 'hi there', 50);
  const r = reactions();
  assert.equal(r.length, 1);
  assert.equal(r[0].body.chat_id, FRIEND);
  assert.equal(r[0].body.message_id, 50);
  assert.equal(r[0].body.reaction[0].type, 'emoji');
});

test('private reactions are off until the owner turns them on', async () => {
  await setup();
  calls = [];
  await say(FRIEND, 'hi there', 50);
  assert.equal(reactions().length, 0);
});

test('the owner does not get reactions to their own commands', async () => {
  await setup();
  await say(OWNER, '/react private on', 2);
  calls = [];
  await say(OWNER, 'hello me', 51);
  assert.equal(reactions().length, 0);
});

test('someone who is not the owner cannot switch reactions on', async () => {
  await setup();
  await say(FRIEND, '/react channel on', 60);
  allowedFor = ['🔥'];
  calls = [];
  await channelPost(91);
  assert.equal(reactions().length, 0);
});

test('the status command shows the three switches', async () => {
  await setup();
  await say(OWNER, '/react status', 2);
  const text = calls.find((c) => c.method === 'sendMessage' && /Channel|کانال/.test(c.body.text || ''));
  assert.ok(text, 'status message sent');
  assert.match(text.body.text, /off|خاموش/);
});

const buttonsOf = (msg) => (msg.body.reply_markup && msg.body.reply_markup.inline_keyboard || []).flat();
const pressRx = (from, data) => send({ callback_query: { id: String(nextId), from: { id: from, is_bot: false, first_name: 'U' }, message: { message_id: 77, date: 1, chat: { id: from, type: 'private' }, text: 'x' }, data } });
const answers = () => calls.filter((c) => c.method === 'answerCallbackQuery');

test('/react with no arguments shows the switch buttons', async () => {
  await setup();
  calls = [];
  await say(OWNER, '/react', 2);
  const panel = calls.find((c) => c.method === 'sendMessage' && c.body.reply_markup);
  assert.ok(panel, 'a panel with buttons is sent');
  const data = buttonsOf(panel).map((b) => b.callback_data);
  assert.ok(data.includes('rx:c:1') && data.includes('rx:g:1') && data.includes('rx:v:1'));
  assert.ok(data.includes('rx:p:25'));
});

test('pressing the channel button turns channel reactions on', async () => {
  await setup();
  calls = [];
  await pressRx(OWNER, 'rx:c:1');
  allowedFor = ['🔥'];
  calls = [];
  await channelPost(91);
  assert.equal(reactions().length, 1, 'the channel now gets a reaction');
});

test('pressing the group chance button sets the percentage shown in the panel', async () => {
  await setup();
  await pressRx(OWNER, 'rx:g:1');
  calls = [];
  await pressRx(OWNER, 'rx:p:25');
  const edited = calls.find((c) => c.method === 'editMessageText');
  assert.ok(edited, 'the panel is updated');
  assert.match(edited.body.text, /25/);
});

test('someone else pressing the reaction buttons changes nothing', async () => {
  await setup();
  calls = [];
  await pressRx(FRIEND, 'rx:c:1');
  assert.ok(answers().some((c) => /Owner only|فقط مالک/.test(c.body.text || '')));
  allowedFor = ['🔥'];
  calls = [];
  await channelPost(91);
  assert.equal(reactions().length, 0);
});
