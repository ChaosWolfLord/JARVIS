// Checks which spoken sentences ask for the live camera, and that the Windows Camera app, "what do you see?" and everything else are left alone.
import assert from 'node:assert/strict';

globalThis.localStorage = { getItem: () => null, setItem() {} };
const { parseCameraCommand, LiveCamera } = await import('../../web/camera.js');
const ok = (name) => console.log(`ok   ${name}`);

for (const [say, op] of [
  ['show the webcam', 'pc'], ['Jarvis, show me the webcam', 'pc'], ['show my camera', 'pc'], ['show the camera', 'pc'], ['turn on the webcam', 'pc'], ['show the live feed', 'pc'],
  ['show me the pc camera', 'pc'], ['show the computer camera', 'pc'], ['let me see the webcam', 'pc'], ['show the room camera', 'pc'], ['bring up the camera feed', 'pc'], ['open the webcam', 'pc'],
  ['show the phone camera', 'phone'], ['show me my phone camera', 'phone'], ['please show the phone cam', 'phone'], ['display the phone camera feed', 'phone'], ['start the phone camera', 'phone'],
  ['stop the camera', 'stop'], ['close the webcam', 'stop'], ['turn off the camera', 'stop'], ['hide the phone camera', 'stop'], ['Jarvis, stop the live feed', 'stop'], ['switch off the webcam', 'stop'],
]) assert.deepEqual(parseCameraCommand(say), { op }, say);
ok('sentences about the live camera are understood');

for (const no of ['open camera', 'open the camera', 'start camera', 'what do you see', 'look at this', 'what is this', 'show me a picture of a cat', 'show off', 'turn off the lights',
  'take a picture', 'play some music', 'show the board', 'show me the weather', 'next board', 'stop the music', 'stop', 'show', 'camera', 'what is a camera', 'who is on the phone', '']) {
  assert.equal(parseCameraCommand(no), null, no);
}
ok('the Windows Camera app, Vision, pictures and everything else are left alone');

// the card: it never starts the phone's camera, only waits for it, and the privacy screen closes it
const calls = [];
globalThis.fetch = async (url, opts = {}) => { calls.push([String(url), opts.method || 'GET']); return { status: 204, headers: { get: () => null }, blob: async () => new Blob() }; };
const node = () => ({ hidden: false, textContent: '', style: {}, removeAttribute() {}, querySelectorAll: () => [], addEventListener() {}, srcObject: null });
const parts = { '#camera-video': node(), '#camera-phone': node(), '#camera-empty': node(), '#camera-foot': node() };
let opened = 0, closed = 0;
const card = new LiveCamera({ el: { querySelector: (q) => parts[q], querySelectorAll: () => [] }, open: () => { opened += 1; }, close: () => { closed += 1; }, speak() {} });

globalThis.jarvis = { privacy: { locked: true } };
assert.equal(card.handleVoice('show the webcam'), true);
assert.equal(card.source, '');
assert.equal(opened, 0);
globalThis.jarvis = { privacy: { locked: false } };
ok('while the privacy screen is up nothing opens');

card.handleVoice('show the phone camera');
await new Promise((r) => setTimeout(r, 30));
assert.equal(card.source, 'phone');
assert.equal(opened, 1);
assert.ok(calls.some((c) => c[0] === '/api/camera/ask' && c[1] === 'POST'), 'it asks the phone with a notification');
assert.ok(calls.some((c) => c[0].startsWith('/api/camera/frame?after=0')), 'and waits for frames');
assert.match(parts['#camera-empty'].textContent, /Waiting for your phone/);
ok('the phone camera is waited for (and the phone is sent a notification), never started from here');

card.stop();
assert.equal(card.source, '');
assert.equal(closed, 1);
assert.ok(calls.some((c) => c[0] === '/api/camera/stop' && c[1] === 'POST'), 'stopping tells the phone to shut its camera');
ok('stopping closes the card and tells the phone');

card.onEvent({ state: 'on', source: 'phone' });
await new Promise((r) => setTimeout(r, 30));
assert.equal(card.source, 'phone');
card.onEvent({ state: 'on', source: 'pc' });
assert.equal(card.source, 'phone');
globalThis.jarvis = { privacy: { locked: true } };
card.stop();
card.onEvent({ state: 'on', source: 'phone' });
assert.equal(card.source, '', 'a phone that starts while the screen is locked is not shown');
ok('the card opens by itself when the phone starts, but not while locked');
