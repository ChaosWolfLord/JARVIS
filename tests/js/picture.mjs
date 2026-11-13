// Checks the wall's picture card: it shows only the PC's own pictures, and only "show me a picture of ..." is sent to the picture finder.
import assert from 'node:assert/strict';
import { Picture } from '../../web/picture.js';

const node = () => ({ textContent: '', alt: '', src: '', removeAttribute(n) { if (n === 'src') this.src = ''; } });
const parts = { '#picture-img': node(), '#picture-title': node(), '#picture-credit': node() };
const card = new Picture({ el: { querySelector: (q) => parts[q] } });
const ok = (name) => console.log(`ok   ${name}`);

const id = 'a'.repeat(24);
assert.equal(card.show({ src: `/api/picture/${id}`, title: 'Red panda', credit: 'Jane · CC BY-SA' }), true);
assert.equal(parts['#picture-img'].src, `/api/picture/${id}`);
assert.equal(parts['#picture-title'].textContent, 'RED PANDA');
assert.equal(parts['#picture-credit'].textContent, 'Jane · CC BY-SA');
ok('a picture from this PC is shown');

for (const bad of ['https://evil.example/a.jpg', '//evil.example/a.jpg', '/api/picture/../../.env', `/api/picture/${id}.jpg`, `/api/picture/${'A'.repeat(24)}`, `/api/picture/${'a'.repeat(23)}`, 'javascript:alert(1)', 'data:image/png;base64,AAAA', '', null]) {
  parts['#picture-img'].src = '';
  assert.equal(card.show({ src: bad, title: 'x' }), false, String(bad));
  assert.equal(parts['#picture-img'].src, '', String(bad));
}
ok('no other address is ever loaded');

let asked = [];
card.answer = (c) => asked.push(c);
for (const yes of ['show me a picture of a red panda', 'Jarvis, show me a photo of the Eiffel Tower', 'pull up an image of Mount Fuji', 'put a picture of a dog on the wall', 'display a photo of saturn']) {
  assert.equal(card.handleVoice(yes), true, yes);
}
for (const no of ['show off', 'show me a hologram of a cat', 'what is a picture', 'turn on the lights', 'open youtube.com', 'take a picture', 'play music']) {
  assert.equal(card.handleVoice(no), false, no);
}
assert.equal(asked.length, 5);
ok('only picture requests go to the picture finder');

card.onHide();
assert.equal(parts['#picture-img'].src, '');
ok('a hidden card keeps no picture');

// ---- the card takes the shape of the photo ----
const { frameSize } = await import('../../web/picture.js');
assert.deepEqual(frameSize(3000, 2000), { w: 640, h: 427 });            // landscape: about the size it always was
assert.deepEqual(frameSize(2000, 3000), { w: 533, h: 800 });            // portrait: taller
assert.deepEqual(frameSize(1000, 1000), { w: 640, h: 640 });
assert.deepEqual(frameSize(100, 150), { w: 533, h: 800 });              // a small photo is scaled up to fill the box
assert.equal(frameSize(10000, 1000).h, 200);                            // a panorama keeps a sensible height
assert.equal(frameSize(0, 0), null);
assert.equal(frameSize(NaN, 5), null);
for (const [w, h] of [[4000, 3000], [3000, 4000], [1200, 1200], [9000, 1500]]) {
  const f = frameSize(w, h);
  assert.ok(Math.abs(f.w / f.h - w / h) < 0.02 || f.h === 200 || f.w === 200, `${w}x${h} keeps its shape`);
  assert.ok(f.w <= 640 && f.h <= 800);
}
ok('the frame has the shape of the photo, as large as the box allows');

const frameNode = { style: {} };
const cardNode = { style: {} };
const img = { ...node(), naturalWidth: 2000, naturalHeight: 3000, addEventListener(e, fn) { this.onload = fn; } };
let fitted = 0;
const shaped = new Picture({ el: { ...cardNode, querySelector: (q) => ({ '#picture-img': img, '#picture-frame': frameNode, '#picture-title': node(), '#picture-credit': node() })[q] } });
shaped.el = cardNode;
shaped.fit = () => { fitted += 1; };
img.onload();
assert.equal(frameNode.style.width, '533px');
assert.equal(frameNode.style.height, '800px');
assert.equal(cardNode.style.width, '561px');
assert.equal(fitted, 1);
img.naturalWidth = 3000; img.naturalHeight = 2000;
img.onload();
assert.equal(frameNode.style.width, '640px');
assert.equal(cardNode.style.width, '668px');
ok('when the photo loads, the card is resized to its shape and kept on the wall');
