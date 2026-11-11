// Checks that the orbs are not redrawn on every screen refresh: a 144 Hz monitor must not make a dim, idle sphere redraw 144 times a second.
import assert from 'node:assert/strict';

globalThis.matchMedia = () => ({ matches: false });
globalThis.ResizeObserver = class { observe() {} };
globalThis.requestAnimationFrame = () => 0;                       // the test calls frame() itself
globalThis.window = { addEventListener() {}, devicePixelRatio: 1 };
globalThis.document = { hidden: false, body: { classList: { contains: () => false } }, documentElement: {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
const ctx = new Proxy({}, { get: () => () => ({ addColorStop() {} }), set: () => true });
const canvas = { clientWidth: 300, width: 0, height: 0, getContext: () => ctx, offsetParent: {} };
const ok = (name) => console.log(`ok   ${name}`);

function rate(frame, state, hz) {
  const orb = frame();
  if (orb.button) orb.button.dataset.state = state; else orb.state = state;       // the PC orb reads its button, the phone orb has a field
  let draws = 0;
  orb.draw = () => { draws += 1; };
  orb.last = 0;
  const step = 1000 / hz;
  for (let now = step; now <= 10_000; now += step) orb.frame(now);        // ten seconds of screen refreshes
  return draws / 10;
}

const { Orb } = await import('../../web/orb.js');
const pc = () => new Orb({ canvas, button: { dataset: { state: 'idle' } } });
for (const hz of [60, 144]) {
  const idle = rate(pc, 'idle', hz), active = rate(pc, 'listening', hz);
  assert.ok(idle >= 18 && idle <= 26, `PC idle at ${hz} Hz drew ${idle}/s`);
  assert.ok(active >= 28 && active <= 50, `PC listening at ${hz} Hz drew ${active}/s`);
}
ok('the PC orb draws about 24 frames a second idle and 30 to 45 when active, on 60 and 144 Hz screens');

// the phone's orb is a plain script that puts PhoneOrb on window
globalThis.window = globalThis;
globalThis.window.matchMedia = globalThis.matchMedia;
await import('../../web/phone/orb.js');
const phone = () => new globalThis.PhoneOrb(canvas);
for (const hz of [60, 120]) {
  const idle = rate(phone, 'idle', hz), active = rate(phone, 'thinking', hz);
  assert.ok(idle >= 16 && idle <= 24, `phone idle at ${hz} Hz drew ${idle}/s`);
  assert.ok(active >= 28 && active <= 46, `phone thinking at ${hz} Hz drew ${active}/s`);
}
ok('the phone orb draws about 20 frames a second idle and 30 to 40 when active, on 60 and 120 Hz screens');

document.hidden = true;
const hiddenOrb = phone();
let drawn = 0;
hiddenOrb.draw = () => { drawn += 1; };
for (let now = 100; now < 3000; now += 16) hiddenOrb.frame(now);
assert.equal(drawn, 0);
ok('a hidden page draws nothing');
