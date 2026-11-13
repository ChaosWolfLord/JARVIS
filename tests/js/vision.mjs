// Checks the page's camera requests: only looking-at-something sentences open the camera, a look sends one picture and speaks the answer, and a camera problem
// is explained. No real camera: frame() is replaced.
import assert from 'node:assert/strict';

globalThis.localStorage = { getItem: () => null, setItem() {} };
const calls = [];
globalThis.fetch = async (url, opts = {}) => { calls.push([url, opts.method, opts.headers?.['Content-Type'], opts.body]); return { ok: true, json: async () => ({ text: 'A red mug on a desk.' }) }; };
const { Vision, isLookRequest, cameraProblem } = await import('../../web/vision.js');
const ok = (name) => console.log(`ok   ${name}`);

for (const yes of ['what is this', "what's this?", 'Jarvis, what is this thing', 'what am I holding', 'what do you see', 'can you see this', 'look at this', 'take a look', 'read this', 'what does this say',
  'what colour is this', 'how many fingers am I holding', 'describe what you see', 'hey jarvis what are these', "what's in my hand", 'identify this']) assert.equal(isLookRequest(yes), true, yes);
for (const no of ['what is this song', "what's this music called", 'what is the weather', 'what time is it', 'play some jazz', 'what is a camera', 'turn on the lights', 'show me a picture of a cat',
  'find the doc about the budget', 'look up the weather', 'what is this about', 'whats the date', '', 'what is this word', 'what is happening in the news']) assert.equal(isLookRequest(no), false, no);
ok('only sentences about looking at something open the camera');

const said = [], shown = [];
const v = new Vision({ root: null, speak: (t) => said.push(t), show: (t) => shown.push(t) });
v.cameras = async () => {};
v.frame = async () => new Blob([new Uint8Array([0xff, 0xd8, 0xff])], { type: 'image/jpeg' });
assert.equal(v.handleVoice('what is this'), true);
assert.equal(v.handleVoice('what is the weather'), false);
await new Promise((r) => setTimeout(r, 20));
assert.equal(calls.length, 1);
assert.equal(calls[0][0], '/api/look?question=what%20is%20this');
assert.equal(calls[0][1], 'POST');
assert.equal(calls[0][2], 'image/jpeg');
assert.deepEqual(said, ['A red mug on a desk.']);
assert.equal(shown[0], 'Looking…');
assert.equal(shown.at(-1), 'A red mug on a desk.');
ok('a look sends one picture with the question and speaks the answer');

calls.length = 0;
v.save({ on: false });
v.handleVoice('what is this');
await new Promise((r) => setTimeout(r, 10));
assert.deepEqual(calls, []);
assert.match(said.at(-1), /switched off/);
ok('with looking switched off nothing is taken');

v.save({ on: true });
v.frame = async () => { throw Object.assign(new Error('x'), { name: 'NotAllowedError' }); };
v.handleVoice('what is this');
await new Promise((r) => setTimeout(r, 10));
assert.match(said.at(-1), /camera is blocked/);
assert.match(cameraProblem({ name: 'NotReadableError' }), /busy/);
assert.match(cameraProblem({ name: 'NotFoundError' }), /can’t find/);
ok('a camera problem is explained');

let release;
v.frame = () => new Promise((r) => { release = r; });
calls.length = 0;
v.look('one');
v.look('two');
release(new Blob([new Uint8Array([0xff, 0xd8, 0xff])]));
await new Promise((r) => setTimeout(r, 20));
assert.equal(calls.length, 1, 'a second request while it is looking is ignored');
ok('never two looks at once');
