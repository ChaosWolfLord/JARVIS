// Checks the page side of "JARVIS speaks first": a heads-up is shown at once and spoken only when JARVIS is not already talking, only the right sentences
// are sent to the snooze command, and a bare "be quiet" is left alone.
import assert from 'node:assert/strict';

const calls = [];
globalThis.fetch = async (url, opts = {}) => { calls.push([url, opts.method]); return { ok: true, json: async () => ({ handled: /hour/.test(decodeURIComponent(url)), text: 'All right, no heads-ups for an hour.' }) }; };
const { Nudges } = await import('../../web/nudges.js');
const ok = (name) => console.log(`ok   ${name}`);

let talking = true;
const said = [], shown = [];
const n = new Nudges({ root: null, busy: () => talking, speak: (t) => said.push(t), show: (t) => shown.push(t) });

n.deliver({ text: 'Dentist starts in 8 minutes.', speak: true });
assert.deepEqual(shown, ['Dentist starts in 8 minutes.']);
assert.deepEqual(said, []);                       // JARVIS is talking: wait
talking = false;
await new Promise((r) => setTimeout(r, 3200));
assert.deepEqual(said, ['Dentist starts in 8 minutes.']);
ok('a heads-up shows at once and is spoken when JARVIS is quiet');

n.deliver({ text: 'Quiet one.', speak: false });
assert.equal(shown.at(-1), 'Quiet one.');
assert.deepEqual(said, ['Dentist starts in 8 minutes.']);
n.deliver({ text: '', speak: true });
assert.equal(shown.length, 2);
ok('with speaking off only the bubble shows, and empty heads-ups are ignored');

for (const no of ['be quiet', 'quiet please', 'what time is it', 'play some jazz', 'what is a nudge']) assert.equal(n.handleVoice(no), false, no);
assert.deepEqual(calls, []);
ok('a bare "be quiet" and other sentences are left alone');

let fellBack = '';
n.fallback = (c) => { fellBack = c; };
assert.equal(n.handleVoice("don't interrupt me for an hour"), true);
await new Promise((r) => setTimeout(r, 20));
assert.match(calls[0][0], /^\/api\/nudges\/voice\?text=/);
assert.equal(said.at(-1), 'All right, no heads-ups for an hour.');
assert.equal(fellBack, '');
assert.equal(n.handleVoice("don't disturb the neighbours"), true);
await new Promise((r) => setTimeout(r, 20));
assert.equal(fellBack, "don't disturb the neighbours");
ok('snooze sentences go to the PC, and anything it does not recognise goes to the AI');
