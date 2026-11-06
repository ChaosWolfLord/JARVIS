// Checks the look switch (web/theme.js): the two palettes are complete, switching changes what the canvases draw with and flips the
// class on <html>, a missing or blocked browser store falls back to the modern look, and the files that make the look work are wired up.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const store = new Map();
const classes = new Set();
let events = 0;
globalThis.window = globalThis;
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => { store.set(k, String(v)); } };
globalThis.document = { documentElement: { classList: { toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); } } } };
globalThis.addEventListener = () => {};
globalThis.dispatchEvent = () => { events += 1; return true; };
const theme = await import(pathToFileURL(path.resolve('web/theme.js')).href);

const checks = {
  'the modern look is the default'() {
    assert.equal(theme.currentLook(), 'modern');
    assert.equal(theme.isModern(), true);
  },
  'switching changes the class, the stored value and tells the canvases'() {
    const before = events;
    assert.equal(theme.applyLook('classic'), 'classic');
    assert.equal(store.get('jarvis.look'), 'classic');
    assert.equal(classes.has('modern'), false);
    assert.ok(events > before, 'no event for the canvases');
    assert.equal(theme.applyLook('modern'), 'modern');
    assert.equal(classes.has('modern'), true);
  },
  'an unknown value is ignored'() {
    theme.applyLook('modern');
    theme.applyLook('neon-pink');
    assert.equal(store.get('jarvis.look'), 'modern');
  },
  'blocked browser storage falls back to modern'() {
    const saved = globalThis.localStorage;
    globalThis.localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
    assert.equal(theme.currentLook(), 'modern');
    assert.doesNotThrow(() => theme.applyLook('classic'));
    globalThis.localStorage = saved;
  },
  'both palettes are complete and different'() {
    for (const key of ['cyan', 'white', 'amber', 'green', 'red']) {
      for (const look of theme.LOOKS) assert.match(theme.inkPalette(look)[key], /^#[0-9a-f]{6}$/, `${look} ${key}`);
      assert.notEqual(theme.inkPalette('classic')[key], theme.inkPalette('modern')[key], key);
    }
    for (const look of theme.LOOKS) {
      const orb = theme.orbPalette(look);
      assert.equal(orb.ring.length, 3);
      assert.equal(orb.bar0.length, 3);
      assert.equal(orb.bar1.length, 3);
      const canvas = theme.canvasPalette(look);
      assert.equal(canvas.series.length, 8);
      for (const value of [canvas.rgb, canvas.bright, canvas.pale, canvas.arc]) assert.match(value, /^\d+, \d+, \d+$/, `${look}: ${value}`);
    }
    assert.equal(theme.orbPalette('classic').modern, false);
    assert.equal(theme.orbPalette('modern').modern, true);
  },
  'the classic palettes are exactly the original neon colours'() {
    assert.deepEqual(theme.accent('classic'), [0, 229, 255]);
    assert.equal(theme.inkPalette('classic').cyan, '#00e5ff');
    assert.deepEqual(theme.orbPalette('classic').ring, ['#8fe0ff', '#2e9bff', '#1b63ff']);
  },
  'the files that make the look work are wired up'() {
    const html = readFileSync('web/index.html', 'utf8');
    assert.ok(html.indexOf('look.js') < html.indexOf('style.css'), 'look.js has to run before the styles so nothing flashes');
    assert.ok(html.indexOf('style.css') < html.indexOf('modern.css'), 'modern.css must come after style.css');
    assert.ok(html.includes('id="opt-look"'), 'no Look setting in the menu');
    const lookJs = readFileSync('web/look.js', 'utf8');
    assert.ok(lookJs.includes("'jarvis.look'") && lookJs.includes('modern'));
    const modern = readFileSync('web/modern.css', 'utf8');
    assert.ok(/^html\.modern \{/m.test(modern), 'the modern rules are scoped to html.modern');
    const css = readFileSync('web/style.css', 'utf8');
    assert.equal(/0,\s*229,\s*255/.test(css.replace(/--accent-rgb:[^;]*;/, '')), false, 'a hard-coded neon colour is back in style.css; use var(--accent-rgb)');
  },
  'the side lights: two washes that cycle the whole hue circle, and the old border aura is gone'() {
    const html = readFileSync('web/index.html', 'utf8');
    assert.ok(html.includes('id="sidelight"') && html.includes('class="l"') && html.includes('class="r"'), 'the two side washes are missing');
    assert.ok(html.indexOf('id="sidelight"') < html.indexOf('id="board"'), 'the light has to sit behind the board');
    assert.equal(html.includes('class="glow'), false, 'the old border aura is back');
    const css = readFileSync('web/style.css', 'utf8');
    assert.ok(/@property --hue/.test(css) && /@keyframes sidelight-cycle \{ from \{ --hue: 0; \} to \{ --hue: 360; \} \}/.test(css), 'the hue does not go all the way round');
    assert.ok(/body\.no-lights #sidelight \{ opacity: 0; \}/.test(css), 'the light button cannot switch it off');
    assert.equal(/\.glow/.test(css + readFileSync('web/modern.css', 'utf8')), false, 'leftover border-aura styles');
  },
};

let failed = 0;
for (const [name, run] of Object.entries(checks)) {
  try { run(); console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
