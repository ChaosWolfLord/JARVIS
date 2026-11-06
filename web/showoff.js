// Show-off mode: say "Jarvis, show off" and a random 3D hologram appears on the left while code is typed out on the right; say it
// again to put it away. It is pure decoration: the code is generated nonsense that merely looks real, and nothing in it touches your
// files, the AI or the network. The command is handled on the PC, so it is instant.

import { Holo, MODELS } from './holo.js';

const TAU = Math.PI * 2;
const pick = (rand, list) => list[Math.floor(rand() * list.length)];
const int = (rand, lo, hi) => lo + Math.floor(rand() * (hi - lo + 1));
const hex = (rand, digits) => Array.from({ length: digits }, () => '0123456789abcdef'[Math.floor(rand() * 16)]).join('');

// ---- "Jarvis, show off" ------------------------------------------------------------------------------------------

/** 'toggle', 'on' or 'off' for show-off commands, null for anything else. */
export function parseShowOff(text) {
  const t = String(text).toLowerCase().replace(/[^a-z\- ]/g, ' ').replace(/\s+/g, ' ').trim().replace(/^(?:hey )?jarvis /, '');
  let m = t.match(/^(?:please )?(?:(stop|end|exit|quit|cancel|disable|leave)(?: the)?|(start|begin|enter|go into|activate|enable)(?: the)?)? ?(?:show|shoe)(?:ing)?[- ]?(?:off|of|offs)(?: mode)?$/);
  if (!m) m = t.match(/^(?:please )?(stop|end|cancel) showing off$/);
  if (!m) return null;
  return m[1] ? 'off' : m[2] ? 'on' : 'toggle';
}

// ---- random hologram models (flat vertex and edge lists, the same form the AI uses) ------------------------------------

function curve(points, closed = true) {
  const edges = [];
  for (let i = 0; i < points.length - (closed ? 0 : 1); i++) edges.push(i, (i + 1) % points.length);
  return { vertices: points.flat(), edges };
}

function knot(rand) {
  const [p, q] = pick(rand, [[2, 3], [3, 2], [3, 4], [2, 5], [3, 5], [4, 3]]);
  const pts = Array.from({ length: 160 }, (_, i) => {
    const t = (i / 160) * TAU, r = 2 + Math.cos(q * t);
    return [r * Math.cos(p * t) * 0.3, r * Math.sin(p * t) * 0.3, Math.sin(q * t) * 0.3];
  });
  return { title: `TORUS KNOT ${p}:${q}`, ...curve(pts) };
}

function lissajous(rand) {
  const [a, b, c] = [1, 2, 3, 4, 5].sort(() => rand() - 0.5).slice(0, 3);
  const f1 = rand() * TAU, f2 = rand() * TAU;
  const pts = Array.from({ length: 180 }, (_, i) => {
    const t = (i / 180) * TAU;
    return [Math.sin(a * t + f1), Math.sin(b * t), Math.sin(c * t + f2)];
  });
  return { title: `LISSAJOUS ${a}:${b}:${c}`, ...curve(pts) };
}

function crystal(rand) {
  const n = int(rand, 12, 21);
  const pts = Array.from({ length: n }, () => {
    const u = rand() * 2 - 1, a = rand() * TAU, s = Math.sqrt(1 - u * u), r = 0.6 + rand() * 0.4;
    return [r * s * Math.cos(a), r * u, r * s * Math.sin(a)];
  });
  const links = new Set();
  pts.forEach((p, i) => {
    pts.map((q, j) => [j, Math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])]).filter(([j]) => j !== i).sort((x, y) => x[1] - y[1]).slice(0, 3)
      .forEach(([j]) => links.add(i < j ? `${i},${j}` : `${j},${i}`));
  });
  return { title: 'CRYSTAL LATTICE', vertices: pts.flat(), edges: [...links].flatMap((s) => s.split(',').map(Number)) };
}

function gyroscope(rand) {
  const rings = int(rand, 3, 5), vertices = [], edges = [];
  for (let r = 0; r < rings; r++) {
    const ax = rand() * Math.PI, ay = rand() * Math.PI, rad = 1 - r * 0.17, base = r * 32;
    for (let i = 0; i < 32; i++) {
      const t = (i / 32) * TAU;
      let [x, y, z] = [rad * Math.cos(t), rad * Math.sin(t), 0];
      [y, z] = [y * Math.cos(ax) - z * Math.sin(ax), y * Math.sin(ax) + z * Math.cos(ax)];
      [x, z] = [x * Math.cos(ay) + z * Math.sin(ay), -x * Math.sin(ay) + z * Math.cos(ay)];
      vertices.push(x, y, z);
      edges.push(base + i, base + ((i + 1) % 32));
    }
  }
  return { title: 'GYROSCOPE', vertices, edges };
}

function nautilus() {
  const n = 96, vertices = [], edges = [];
  for (let i = 0; i < n; i++) {
    const t = (i / n) * 3.2 * TAU, r = 0.12 * Math.exp(0.2 * t);
    vertices.push(r * Math.cos(t), r * Math.sin(t) * 0.55, (i / n) * 1.2 - 0.6);
    if (i) edges.push(i - 1, i);
  }
  for (let k = 0; k < 16; k++) {                       // spokes to an axis down the middle
    const axis = n + k;
    vertices.push(0, 0, (k * 6 / n) * 1.2 - 0.6);
    edges.push(axis, Math.min(n - 1, k * 6));
  }
  return { title: 'NAUTILUS SHELL', vertices, edges };
}

const GENERATED = [knot, lissajous, crystal, gyroscope, nautilus];

/** A new random hologram event for Holo.show: either one of the ready-made shapes or a freshly generated one. */
export function randomModel(rand = Math.random) {
  if (rand() < 0.4) {
    const shape = pick(rand, Object.keys(MODELS));
    return { type: 'holo', kind: 'model', shape, title: shape.toUpperCase() };
  }
  const made = pick(rand, GENERATED)(rand);
  return { type: 'holo', kind: 'model', shape: 'custom', title: made.title, vertices: made.vertices, edges: made.edges };
}

// ---- random "code" (looks real, means nothing) -------------------------------------------------------------------------

const VERBS = ['render', 'solve', 'compute', 'project', 'calibrate', 'align', 'resample', 'reduce', 'compile', 'trace', 'fuse', 'decode', 'stabilise', 'integrate'];
const NOUNS = ['mesh', 'orbit', 'spectrum', 'lattice', 'plasma', 'vector', 'signal', 'shield', 'quaternion', 'gradient', 'array', 'kernel', 'flux', 'tensor', 'beam'];
const VARS = ['a', 'b', 'x', 'y', 'n', 'k', 'phi', 'delta', 'gain', 'rate', 'mass', 'bias', 'scale', 'theta'];
const MODULES = ['reactor_core', 'repulsor_array', 'flight_control', 'sensor_fusion', 'thermal_model', 'arc_driver', 'nav_stack', 'hud_render'];

const snake = (rand) => `${pick(rand, VERBS)}_${pick(rand, NOUNS)}`;
const camel = (rand) => `${pick(rand, VERBS)}${pick(rand, NOUNS).replace(/^./, (c) => c.toUpperCase())}`;
const num = (rand) => (rand() < 0.5 ? String(int(rand, 2, 99)) : (rand() * 9 + 0.1).toFixed(2));

const TEMPLATES = [
  (r) => { const f = snake(r), [a, b, c] = [pick(r, VARS), pick(r, VARS), pick(r, VARS)]; return [
    `def ${f}(${a}, ${b}=${num(r)}):`, `    ${c} = ${a} * ${num(r)} + ${b}`, `    for i in range(${int(r, 4, 64)}):`,
    `        ${c} += ${snake(r)}(i) ** 2 - ${num(r)}`, `    return ${c} / max(1, ${a})`]; },
  (r) => { const f = camel(r), [a, b, c] = [pick(r, VARS), pick(r, VARS), pick(r, VARS)]; return [
    `const ${f} = async (${a}, ${b}) => {`, `  const ${c} = await ${pick(r, NOUNS)}.${camel(r)}(${a}, { ${pick(r, VARS)}: ${num(r)} });`,
    `  return ${c}.map((x) => x * ${num(r)}).filter(Boolean);`, '};']; },
  (r) => { const f = snake(r), [a, b, c] = [pick(r, VARS), pick(r, VARS), pick(r, VARS)]; return [
    `static inline float ${f}(float ${a}, float ${b}) {`, `    float ${c} = ${a} * ${b} + ${int(r, 1, 9)}.0f;`,
    `    return ${c} > ${int(r, 1, 9)}.0f ? ${c} : -${c};`, '}']; },
  (r) => { const f = snake(r), a = pick(r, VARS), c = pick(r, VARS); return [
    `fn ${f}(buf: &mut [u8], ${a}: usize) -> Result<usize, Error> {`,
    `    let ${c} = buf.iter().take(${a}).fold(0u32, |acc, b| acc.wrapping_mul(${int(r, 3, 31)}) ^ *b as u32);`, `    Ok(${c} as usize)`, '}']; },
  (r) => [`# ${pick(r, MODULES)}: ${pick(r, VERBS)} pass ${int(r, 1, 9)}`, `${snake(r)}(${pick(r, VARS)}=${num(r)}, ${pick(r, VARS)}=${num(r)})`],
  (r) => Array.from({ length: int(r, 3, 6) }, () => `0x${hex(r, 4)}:  ${Array.from({ length: 8 }, () => hex(r, 2)).join(' ')}`),
  (r) => [`mov rax, 0x${hex(r, 8)}`, `xor rbx, rbx`, `call ${snake(r)}`, `cmp rax, ${int(r, 0, 255)}`, `jne .${pick(r, NOUNS)}_${int(r, 1, 9)}`],
];

const LOGS = [
  (r) => `// [ OK ] linking ${pick(r, MODULES)} @ 0x${hex(r, 8)}`,
  (r) => `// [ OK ] ${pick(r, NOUNS)} test ${int(r, 1, 48)}/48 passed`,
  (r) => `// build ${hex(r, 6)} ${pick(r, MODULES)} ${(rand01(r) * 4 + 0.2).toFixed(2)}s`,
  (r) => `// warning: ${pick(r, NOUNS)} drift ${(rand01(r) * 0.09).toFixed(4)} within tolerance`,
];
const rand01 = (r) => r();

export class CodeWriter {
  constructor(rand = Math.random) { this.rand = rand; }

  /** One block of lines (a function, a few log lines, a hex dump...), each at most about 100 characters. */
  block() {
    const lines = pick(this.rand, TEMPLATES)(this.rand).slice();
    if (this.rand() < 0.45) lines.push('', pick(this.rand, LOGS)(this.rand));
    lines.push('');
    return lines.map((l) => l.slice(0, 100));
  }
}

const TOKEN = /(#.*|\/\/.*)|("[^"]*"|'[^']*')|\b(0x[0-9a-fA-F]+|\d+(?:\.\d+)?f?)\b|\b(def|return|for|in|if|else|const|let|async|await|fn|static|inline|float|int|mut|pub|use|Ok|Err|None|True|False|while|import|from|class|struct|impl|void|u8|u32|usize|mov|xor|call|cmp|jne)\b|\b([A-Za-z_][A-Za-z0-9_]*)(?=\()/g;
const CLASSES = ['', 'c', 's', 'n', 'k', 'f'];

/** Splits a line into [{text, cls}] so it can be coloured. Joining the texts gives back exactly the line. */
export function highlight(line) {
  const out = [];
  let last = 0;
  for (const m of line.matchAll(TOKEN)) {
    if (m.index > last) out.push({ text: line.slice(last, m.index), cls: '' });
    const group = m.findIndex((v, i) => i > 0 && v !== undefined);
    out.push({ text: m[0], cls: CLASSES[group] });
    last = m.index + m[0].length;
  }
  if (last < line.length) out.push({ text: line.slice(last), cls: '' });
  return out;
}

// ---- the mode itself --------------------------------------------------------------------------------------------------

const MAX_LINES = 30;

export class ShowOff {
  constructor({ root, sounds, speak, getLine }) {
    this.root = root;
    this.sounds = sounds;
    this.speak = speak;
    this.getLine = getLine;               // (on) => Promise<string>: what JARVIS says, in its current mood
    this.on = false;
    this.holo = new Holo({ el: root.querySelector('.so-left') });
    this.codeEl = root.querySelector('.so-code');
    this.countEl = root.querySelector('.so-count');
    this.writer = new CodeWriter();
    this.timers = [];
    this.reset();
  }

  reset() {
    this.rows = [];
    this.pending = [];
    this.typing = null;
    this.total = 0;
    this.codeEl.replaceChildren();
  }

  /** "Jarvis, show off" / "stop showing off". True means: it was a show-off command, nothing else should handle it. */
  handleVoice(command) {
    const action = parseShowOff(command);
    if (!action) return false;
    const wantOn = action === 'on' || (action === 'toggle' && !this.on);
    if (wantOn === this.on) return true;                    // "show off" when already on (via "start"), or "stop" when off: nothing to do
    if (wantOn) this.start(); else this.stop();
    this.getLine?.(wantOn).then((text) => this.speak?.(text), () => {});
    return true;
  }

  start() {
    if (this.on) return;
    this.on = true;
    this.reset();
    this.root.hidden = false;
    requestAnimationFrame(() => this.root.classList.add('on'));
    this.sounds?.play('holo');
    this.holo.onShow();
    this.nextModel();
    this.timers.push(setInterval(() => this.tick(), 45));
  }

  stop() {
    if (!this.on) return;
    this.on = false;
    this.timers.forEach((t) => { clearInterval(t); clearTimeout(t); });
    this.timers = [];
    this.root.classList.remove('on');
    this.sounds?.play('close');
    this.holo.onHide();
    setTimeout(() => { if (!this.on) this.root.hidden = true; }, 700);
  }

  toggle() { if (this.on) this.stop(); else this.start(); }

  nextModel() {
    if (!this.on) return;
    this.holo.show(randomModel());
    this.timers.push(setTimeout(() => this.nextModel(), 9000 + Math.random() * 5000));
  }

  /** Types a few characters; at the end of a line starts the next, and keeps only the last lines on screen. */
  tick() {
    if (!this.typing) {
      if (!this.pending.length) this.pending = this.writer.block();
      const text = this.pending.shift();
      const el = Object.assign(document.createElement('div'), { className: 'so-line' });
      this.codeEl.append(el);
      this.rows.push(el);
      while (this.rows.length > MAX_LINES) this.rows.shift().remove();
      this.typing = { text, shown: 0, el, pause: text ? 0 : 4 };
      this.total += 1;
      if (this.countEl) this.countEl.textContent = `LINES ${this.total.toLocaleString()}`;
    }
    const t = this.typing;
    if (t.pause > 0) { t.pause -= 1; if (!t.pause) this.typing = null; return; }
    t.shown = Math.min(t.text.length, t.shown + 2 + Math.floor(Math.random() * 3));
    const spans = highlight(t.text.slice(0, t.shown)).map(({ text, cls }) => Object.assign(document.createElement('span'), { className: cls, textContent: text }));
    if (t.shown < t.text.length) spans.push(Object.assign(document.createElement('span'), { className: 'so-cursor', textContent: '▌' }));
    t.el.replaceChildren(...spans);
    if (t.shown >= t.text.length) t.pause = t.text ? 3 : 4;
  }
}
