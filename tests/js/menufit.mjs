// Checks fitMenu (web/menufit.js): a pop-up menu is never taller than the room above the dock. Runs under Node with a stand-in page;
// tests/test_js_voice.py runs it with the other browser-side checks.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const listeners = [];
globalThis.window = { addEventListener: (type, fn) => listeners.push([type, fn]) };
globalThis.document = { querySelectorAll: () => menus };
const { fitMenu } = await import(pathToFileURL(path.resolve('web/menufit.js')).href);

const menuAt = (top, height = 100, offsetHeight = 100, hidden = false) => ({
  hidden, style: {}, offsetParent: { getBoundingClientRect: () => ({ top, height }), offsetHeight },
});
let menus = [];
const checks = {
  'the limit is the room above the dock minus the gap and a little air'() {
    const m = menuAt(600);
    fitMenu(m);
    assert.equal(m.style.maxHeight, `${600 - 14 - 12}px`);
  },
  'a scaled page (fit to wall) is measured in the page\'s own pixels'() {
    const m = menuAt(300, 50, 100);                      // drawn at half size: 300 screen px is 600 page px
    fitMenu(m);
    assert.equal(m.style.maxHeight, `${600 - 26}px`);
  },
  'a tiny window still leaves a usable menu'() {
    const m = menuAt(40);
    fitMenu(m);
    assert.equal(m.style.maxHeight, '160px');
  },
  'a hidden menu or one with no anchor is left alone'() {
    const hidden = menuAt(600, 100, 100, true);
    fitMenu(hidden);
    assert.equal(hidden.style.maxHeight, undefined);
    assert.doesNotThrow(() => fitMenu({ hidden: false, offsetParent: null, style: {} }));
    assert.doesNotThrow(() => fitMenu(null));
  },
  'resizing the window re-fits the menus that are open'() {
    const open = menuAt(500), closed = menuAt(500, 100, 100, true);
    menus = [open, closed];
    const [, onResize] = listeners.find(([type]) => type === 'resize');
    onResize();
    assert.equal(open.style.maxHeight, `${500 - 26}px`);
    assert.equal(closed.style.maxHeight, undefined);
  },
};

let failed = 0;
for (const [name, run] of Object.entries(checks)) {
  try { run(); console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
