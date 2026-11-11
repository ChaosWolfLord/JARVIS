// Checks the PC page's "find my phone" voice command and the remote switch: only those words are taken, and nothing is asked of the PC otherwise.
import assert from 'node:assert/strict';

const calls = [];
globalThis.setInterval = () => 0;
globalThis.fetch = async (url, opts = {}) => { calls.push(`${opts.method || 'GET'} ${url}`); return { ok: true, json: async () => ({ sent: 1, armed: true, seconds_left: 1800 }) }; };
const stub = () => ({ addEventListener() {}, textContent: '', hidden: false });
const root = { querySelector: () => stub() };
const { PhoneLink } = await import('../../web/phonelink.js');
const link = new PhoneLink({ root });
const ok = (name) => console.log(`ok   ${name}`);

const said = [];
for (const yes of ['find my phone', 'Jarvis, find my phone', 'where is my phone', "where's my phone", 'ring my phone', 'locate my mobile']) {
  calls.length = 0;
  assert.equal(link.handleVoice(yes, (t) => said.push(t)), true, yes);
  await new Promise((r) => setTimeout(r, 5));
  assert.deepEqual(calls, ['POST /api/phone/find'], yes);
}
ok('find my phone is understood');

for (const no of ['find a restaurant', 'where is the library', 'call my phone provider', 'my phone is broken', 'play music', 'show off', 'what is a phone']) {
  calls.length = 0;
  assert.equal(link.handleVoice(no), false, no);
  assert.deepEqual(calls, [], no);
}
ok('other sentences are left alone');

calls.length = 0;
assert.equal(link.handleVoice('stop ringing my phone', (t) => said.push(t)), true);
await new Promise((r) => setTimeout(r, 5));
assert.deepEqual(calls, ['DELETE /api/phone/find']);
ok('stopping works');

calls.length = 0;
await link.remote('on');
assert.deepEqual(calls, ['POST /api/phone/remote']);
assert.equal(link.armed, true);
ok('the remote is switched on only by the PC page, for 30 minutes');
