// Checks the wall's file finder card: only file requests are taken by it, a result's name is shown as text (never as page code), and the buttons ask the PC.
import assert from 'node:assert/strict';

const made = [];
const node = (tag) => {
  const n = { tag, children: [], listeners: {}, textContent: '', className: '', title: '', disabled: false,
    append(...kids) { this.children.push(...kids); }, replaceChildren(...kids) { this.children = kids; },
    addEventListener(name, fn) { this.listeners[name] = fn; }, querySelector() { return null; } };
  made.push(n);
  return n;
};
globalThis.document = { createElement: (tag) => node(tag) };
const calls = [];
globalThis.fetch = async (url, opts = {}) => { calls.push([opts.method || 'GET', url, opts.body]); return { ok: true, json: async () => ({ handled: true, text: 'Opened it.' }) }; };

const parts = { '#files-list': node('ul'), '#files-title': node('b'), '#files-foot': node('footer') };
const { Files } = await import('../../web/files.js');
const card = new Files({ el: { querySelector: (q) => parts[q] } });
const ok = (name) => console.log(`ok   ${name}`);

const taken = [];
card.answer = (c) => taken.push(c);
for (const yes of ['find the doc I edited yesterday about the budget', 'Jarvis, find my pdfs from last week', 'where is the invoice spreadsheet', 'look for the presentation about the launch',
  'search for my screenshots from today', 'find the file called taxes']) {
  assert.equal(card.handleVoice(yes), true, yes);
}
for (const no of ['find my phone', 'where is my phone', 'show me a picture of a cat', 'find a picture of a red panda', 'find a restaurant nearby', 'where is the library', 'play music',
  'turn off the lights', 'open youtube.com']) {
  assert.equal(card.handleVoice(no), false, no);
}
assert.equal(taken.length, 6);
ok('only file requests are taken');

const evil = '<img src=x onerror=alert(1)>.pdf';
card.show({ title: 'budget', searched: 120, complete: true, items: [{ path: 'C:\\Docs\\a.pdf', name: evil, folder: 'C:\\Docs', when: 'today', size_text: '1 KB', openable: true, image: false }] });
const row = parts['#files-list'].children[0];
const text = JSON.stringify(row);
assert.ok(text.includes(evil), 'the name is shown');
assert.ok(!made.some((n) => 'innerHTML' in n), 'no innerHTML');
assert.equal(parts['#files-foot'].textContent, '120 files looked through');
ok('a file name is only ever text');

const [open, folder] = row.children[1].children;
assert.equal(open.textContent, 'Open');
assert.equal(folder.textContent, 'Folder');
assert.equal(row.children[1].children.length, 2, 'no Wall button for a document');
await open.listeners.click();
assert.equal(calls[0][0], 'POST');
assert.equal(calls[0][1], '/api/finder/open');
assert.deepEqual(JSON.parse(calls[0][2]), { path: 'C:\\Docs\\a.pdf', how: 'open' });
ok('the buttons ask the PC, with the file path and what to do');

card.show({ title: 'x', items: [{ path: 'C:\\P\\a.png', name: 'a.png', folder: 'C:\\P', when: 'today', size_text: '1 KB', openable: true, image: true }] });
assert.equal(parts['#files-list'].children[0].children[1].children.length, 3);
card.show({ title: 'none', items: [], complete: false });
assert.ok(JSON.stringify(parts['#files-list'].children[0]).includes('Nothing matched'));
assert.ok(parts['#files-foot'].textContent.includes('ran out of time'));
assert.equal(card.show(null), false);
ok('pictures get a Wall button, empty and unfinished searches say so');
