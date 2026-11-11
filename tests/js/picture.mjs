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
