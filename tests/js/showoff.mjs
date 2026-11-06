// Checks the pieces of show-off mode (web/showoff.js) that can be tested without a screen: which phrases switch it on and off, that every
// random hologram is valid, and that the random code is well-formed. Run by tests/test_js_voice.py with the other browser-side checks.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';
import * as await_fs from 'node:fs';

globalThis.window = globalThis;                      // holo.js and showoff.js only define things at load time
const { parseShowOff, randomModel, CodeWriter, highlight } = await import(pathToFileURL(path.resolve('web/showoff.js')).href);
const { customModel } = await import(pathToFileURL(path.resolve('web/holo.js')).href);

function seeded(seed) {                              // a repeatable random source
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) >>> 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}

const checks = {
  'the phrases that toggle show-off mode'() {
    for (const text of ['show off', 'Show off', 'jarvis show off', 'Jarvis, show off.', 'show-off', 'showoff', 'show off mode', 'please show off', 'hey jarvis, show off!', 'jarvis show of', 'Jarvis, showoff.', 'jarvis shoe off', 'jarvis, show off mode']) {
      assert.equal(parseShowOff(text), 'toggle', text);
    }
  },
  'explicit on and off phrases'() {
    for (const text of ['start show off', 'enter show off mode', 'go into show off mode', 'activate show-off']) assert.equal(parseShowOff(text), 'on', text);
    for (const text of ['stop showing off', 'stop show off', 'end show-off mode', 'exit show off', 'stop the show off', 'cancel show off']) assert.equal(parseShowOff(text), 'off', text);
  },
  'other sentences are left alone'() {
    for (const text of ['show me a torus', 'show off the weather', 'what is show off', 'show the weather', 'show', 'off', 'turn the lights off', 'stop', 'show off my notes please',
      'chart this', 'start a timer', 'play show tunes', '']) {
      assert.equal(parseShowOff(text), null, text);
    }
  },
  'every random hologram is valid for the renderer, many times over'() {
    const rand = seeded(12345);
    const titles = new Set();
    for (let i = 0; i < 400; i++) {
      const m = randomModel(rand);
      assert.equal(m.type, 'holo');
      assert.equal(m.kind, 'model');
      assert.ok(m.title && m.title.length < 40, m.title);
      titles.add(m.title);
      if (m.shape === 'custom') {
        assert.ok(m.vertices.length % 3 === 0 && m.vertices.length / 3 <= 300, `${m.title}: ${m.vertices.length / 3} vertices`);
        assert.ok(m.edges.length % 2 === 0 && m.edges.length / 2 <= 600, `${m.title}: ${m.edges.length / 2} edges`);
        assert.ok(m.vertices.every(Number.isFinite), `${m.title}: non-finite vertex`);
        const count = m.vertices.length / 3;
        assert.ok(m.edges.every((e) => Number.isInteger(e) && e >= 0 && e < count), `${m.title}: edge out of range`);
        const built = customModel(m.vertices, m.edges);               // what the card actually draws
        assert.equal(built.v.length, count);
        assert.equal(built.e.length, m.edges.length / 2);
        assert.ok(built.v.every((p) => Math.hypot(...p) <= 1.0001), `${m.title}: outside the unit sphere after fitting`);
      } else {
        assert.ok(['cube', 'pyramid', 'sphere', 'torus', 'icosahedron', 'helix', 'globe', 'reactor'].includes(m.shape), m.shape);
      }
    }
    assert.ok(titles.size >= 8, `only ${titles.size} different holograms in 400 tries`);
  },
  'the random code is well-formed and varied'() {
    const writer = new CodeWriter(seeded(777));
    const lines = Array.from({ length: 300 }, () => writer.block()).flat();
    assert.ok(lines.length > 600);
    assert.ok(lines.every((l) => typeof l === 'string' && l.length <= 100), 'a line was too long');
    assert.ok(new Set(lines).size > 300, 'the code repeats too much');
    for (const needle of ['def ', 'const ', 'fn ', 'static inline', '0x', 'mov rax']) assert.ok(lines.some((l) => l.includes(needle)), `no ${needle} lines`);
    assert.ok(!lines.some((l) => /undefined|NaN|\[object/.test(l)), 'an unfilled template slipped through');
  },
  'colouring never changes the text'() {
    const writer = new CodeWriter(seeded(4242));
    for (let i = 0; i < 200; i++) {
      for (const line of writer.block()) {
        const parts = highlight(line);
        assert.equal(parts.map((p) => p.text).join(''), line);
        assert.ok(parts.every((p) => ['', 'c', 's', 'n', 'k', 'f'].includes(p.cls)));
      }
    }
    const kinds = new Set(highlight('def solve_beam(x, y=3.5):  # go "now" 0x1f').map((p) => p.cls));
    for (const cls of ['k', 'f', 'n', 'c']) assert.ok(kinds.has(cls), `no ${cls} token`);
    assert.ok(new Set(highlight('const a = "text";').map((p) => p.cls)).has('s'));
  },
  'the generated code is only ever put on screen as text, never as HTML'() {
    const { readFileSync } = await_fs;
    const source = readFileSync('web/showoff.js', 'utf8');
    for (const banned of ['innerHTML', 'insertAdjacentHTML', 'outerHTML', 'document.write', 'eval(', 'new Function']) assert.equal(source.includes(banned), false, banned);
    assert.ok(source.includes('textContent'), 'code is set with textContent');
  },
};

let failed = 0;
for (const [name, run] of Object.entries(checks)) {
  try { run(); console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
