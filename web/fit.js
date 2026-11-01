// Fit to wall: a test pattern plus corner-pin ("keystone") correction for the whole interface.
// Drag four corner dots onto the corners of the patch of wall you want to use, and the page is warped
// to fit it. The setting is saved as fractions of the window, so it survives resizing and fullscreen.

const KEY = 'jarvis.warp.v1';
const IDENTITY = [[0, 0], [1, 0], [1, 1], [0, 1]]; // top-left, top-right, bottom-right, bottom-left
const NAMES = ['TL', 'TR', 'BR', 'BL'];

// ---- math ----------------------------------------------------------------

/** Solves A x = b by Gaussian elimination with partial pivoting. */
function solve(A, b) {
  const n = b.length;
  const M = A.map((row, i) => [...row, b[i]]);
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]];
    for (let r = c + 1; r < n; r++) {
      const f = M[r][c] / M[c][c];
      for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k];
    }
  }
  const x = new Array(n);
  for (let r = n - 1; r >= 0; r--) {
    let s = M[r][n];
    for (let k = r + 1; k < n; k++) s -= M[r][k] * x[k];
    x[r] = s / M[r][r];
  }
  return x;
}

/** Homography [h11,h12,h13,h21,h22,h23,h31,h32] (h33 = 1) sending the w x h rectangle onto quad (TL,TR,BR,BL). */
export function homography(w, h, quad) {
  const src = [[0, 0], [w, 0], [w, h], [0, h]];
  const A = [], b = [];
  src.forEach(([x, y], i) => {
    const [X, Y] = quad[i];
    A.push([x, y, 1, 0, 0, 0, -X * x, -X * y]); b.push(X);
    A.push([0, 0, 0, x, y, 1, -Y * x, -Y * y]); b.push(Y);
  });
  return solve(A, b);
}

export function applyHomography(H, x, y) {
  const [h11, h12, h13, h21, h22, h23, h31, h32] = H;
  const d = h31 * x + h32 * y + 1;
  return [(h11 * x + h12 * y + h13) / d, (h21 * x + h22 * y + h23) / d];
}

/** CSS matrix3d() for a homography (CSS wants it column by column). */
export function toMatrix3d(H) {
  const [h11, h12, h13, h21, h22, h23, h31, h32] = H;
  return `matrix3d(${h11},${h21},0,${h31},${h12},${h22},0,${h32},0,0,1,0,${h13},${h23},0,1)`;
}

const isIdentity = (q) => q.every(([x, y], i) => Math.abs(x - IDENTITY[i][0]) < 1e-4 && Math.abs(y - IDENTITY[i][1]) < 1e-4);
const clamp01 = (v) => Math.max(0, Math.min(1, v));

// ---- test pattern ----------------------------------------------------------

function drawPattern(canvas) {
  const w = window.innerWidth, h = window.innerHeight, dpr = window.devicePixelRatio || 1;
  if (w < 100 || h < 100) return; // nothing sensible to draw (and the grid loops below would never end at 0)
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  const c = canvas.getContext('2d');
  c.setTransform(dpr, 0, 0, dpr, 0, 0);
  c.fillStyle = '#000';
  c.fillRect(0, 0, w, h);

  const cell = h / 10; // square cells, so a stretched or tilted image is easy to spot
  c.lineWidth = 1;
  for (let i = 0, n = Math.ceil(w / cell); i <= n; i++) {
    c.strokeStyle = i % 5 === 0 ? 'rgba(0,229,255,0.75)' : 'rgba(0,229,255,0.28)';
    c.beginPath(); c.moveTo(i * cell, 0); c.lineTo(i * cell, h); c.stroke();
  }
  for (let j = 0; j <= 10; j++) {
    c.strokeStyle = j % 5 === 0 ? 'rgba(0,229,255,0.75)' : 'rgba(0,229,255,0.28)';
    c.beginPath(); c.moveTo(0, j * cell); c.lineTo(w, j * cell); c.stroke();
  }

  c.strokeStyle = 'rgba(255,255,255,0.35)';
  c.beginPath(); c.moveTo(0, 0); c.lineTo(w, h); c.moveTo(w, 0); c.lineTo(0, h); c.stroke();

  // Circles: round on the wall means the shape is right. One in the middle, one in each corner.
  c.strokeStyle = '#ffb300'; c.lineWidth = 3;
  const r = h * 0.3;
  c.beginPath(); c.arc(w / 2, h / 2, r, 0, Math.PI * 2); c.stroke();
  c.strokeStyle = '#5cff8a';
  const cr = h * 0.07;
  for (const [x, y] of [[cr + 6, cr + 6], [w - cr - 6, cr + 6], [w - cr - 6, h - cr - 6], [cr + 6, h - cr - 6]]) {
    c.beginPath(); c.arc(x, y, cr, 0, Math.PI * 2); c.stroke();
  }

  c.strokeStyle = '#fff'; c.lineWidth = 4;
  c.strokeRect(2, 2, w - 4, h - 4); // the edge: if any of this is cut off, the picture is overscanned

  c.font = '700 22px "Segoe UI", sans-serif';
  c.fillStyle = '#fff';
  c.textBaseline = 'top';
  c.fillText('TL', cr * 2 + 20, 14);
  c.textAlign = 'right'; c.fillText('TR', w - cr * 2 - 20, 14);
  c.textBaseline = 'bottom'; c.fillText('BR', w - cr * 2 - 20, h - 14);
  c.textAlign = 'left'; c.fillText('BL', cr * 2 + 20, h - 14);

  // Focus and legibility: small text should be crisp, with no coloured fringes.
  c.fillStyle = '#fff'; c.textBaseline = 'top';
  let y = h * 0.62;
  for (const size of [10, 12, 14, 18, 24]) {
    c.font = `${size}px "Segoe UI", sans-serif`;
    c.fillText(`${size}px  JARVIS 0123456789 The quick brown fox jumps over the lazy dog`, w * 0.06, y);
    y += size * 1.5;
  }

  // Brightness steps and colour bars along the bottom.
  const barH = h * 0.06, top = h * 0.88;
  for (let i = 0; i < 8; i++) {
    const v = Math.round((i / 7) * 255);
    c.fillStyle = `rgb(${v},${v},${v})`;
    c.fillRect(w * 0.1 + (i * w * 0.8) / 16, top, (w * 0.8) / 16, barH);
  }
  ['#ff0000', '#00ff00', '#0000ff', '#00ffff', '#ff00ff', '#ffff00', '#ffffff', '#202020'].forEach((col, i) => {
    c.fillStyle = col;
    c.fillRect(w * 0.5 + (i * w * 0.4) / 8, top, (w * 0.4) / 8, barH);
  });

  c.textAlign = 'center'; c.textBaseline = 'middle';
  c.fillStyle = '#00e5ff'; c.font = `700 ${Math.max(18, h * 0.04)}px "Segoe UI", sans-serif`;
  c.fillText('FIT TO WALL', w / 2, h * 0.055);
  c.fillStyle = '#cfeff7'; c.font = `${Math.max(14, h * 0.022)}px "Segoe UI", sans-serif`;
  c.fillText(`${w} x ${h} px, grid squares ${Math.round(cell)} px`, w / 2, h * 0.1);
  c.fillText('Round circles and square cells on the wall mean the shape is right.', w / 2, h * 0.135);
}

// ---- the tool --------------------------------------------------------------

export class Fit {
  /** app: the element that gets warped. pattern: the test-pattern wrapper (inside app). ui: dots + panel (outside app). */
  constructor({ app, pattern, ui }) {
    this.app = app;
    this.pattern = pattern;
    this.canvas = pattern.querySelector('canvas');
    this.ui = ui;
    this.handles = [...ui.querySelectorAll('.fit-handle')];
    this.selected = 0;
    this.isOpen = false;
    this.corners = this.load();

    this.handles.forEach((el, i) => this.bindHandle(el, i));
    ui.querySelector('#fit-reset').addEventListener('click', () => this.reset());
    ui.querySelector('#fit-done').addEventListener('click', () => this.close());
    // Clicking the panel's title folds it away so the middle of the test pattern is visible.
    ui.querySelector('#fit-panel h2').addEventListener('click', () => ui.querySelector('#fit-panel').classList.toggle('folded'));
    ui.querySelector('#fit-pattern').addEventListener('change', (e) => { this.pattern.hidden = !e.target.checked; });
    window.addEventListener('resize', () => { this.apply(); if (this.isOpen) this.redrawPattern(); });
    window.addEventListener('keydown', (e) => this.onKey(e), true);
    this.apply();
  }

  load() {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) || 'null');
      if (Array.isArray(saved) && saved.length === 4 && saved.every((p) => Array.isArray(p) && p.length === 2)) return saved;
    } catch { /* fall through to no warp */ }
    return IDENTITY.map((p) => [...p]);
  }

  save() {
    try { localStorage.setItem(KEY, JSON.stringify(this.corners)); } catch { /* not saved, fine */ }
  }

  /** Warps the page to the current corners and moves the dots. */
  apply() {
    const w = window.innerWidth, h = window.innerHeight;
    if (w < 100 || h < 100) return; // no real window to fit (e.g. a hidden tab): keep whatever is applied now
    const quad = this.corners.map(([x, y]) => [x * w, y * h]);
    this.handles.forEach((el, i) => {
      el.style.left = `${quad[i][0]}px`;
      el.style.top = `${quad[i][1]}px`;
    });
    if (isIdentity(this.corners)) {
      this.app.style.transform = '';
      return;
    }
    this.app.style.transformOrigin = '0 0';
    this.app.style.transform = toMatrix3d(homography(w, h, quad));
  }

  bindHandle(el, i) {
    el.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      el.setPointerCapture(e.pointerId);
      this.select(i);
      const move = (ev) => {
        this.corners[i] = [clamp01(ev.clientX / window.innerWidth), clamp01(ev.clientY / window.innerHeight)];
        this.apply();
      };
      const up = () => {
        el.removeEventListener('pointermove', move);
        el.removeEventListener('pointerup', up);
        this.save();
      };
      el.addEventListener('pointermove', move);
      el.addEventListener('pointerup', up);
    });
  }

  select(i) {
    this.selected = i;
    this.handles.forEach((el, k) => el.classList.toggle('sel', k === i));
  }

  nudge(dx, dy) {
    const [x, y] = this.corners[this.selected];
    this.corners[this.selected] = [clamp01(x + dx / window.innerWidth), clamp01(y + dy / window.innerHeight)];
    this.apply();
    this.save();
  }

  onKey(e) {
    if (!this.isOpen || e.ctrlKey || e.altKey || e.metaKey) return;
    const step = e.shiftKey ? 10 : 1;
    const arrows = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
    if (arrows[e.key]) this.nudge(...arrows[e.key]);
    else if (e.key === 'Escape' || e.key === 'Enter') this.close();
    else if (e.key.toLowerCase() === 'r') this.reset();
    else if (['1', '2', '3', '4'].includes(e.key)) this.select(Number(e.key) - 1);
    else return;
    e.preventDefault();
    e.stopImmediatePropagation();
  }

  reset() {
    this.corners = IDENTITY.map((p) => [...p]);
    this.apply();
    this.save();
  }

  redrawPattern() { drawPattern(this.canvas); }

  open() {
    // With no warp yet the dots would sit exactly on the window corners, half off-screen and hard to grab.
    // Start slightly inside; drag outward (or press Reset) to get the full window back.
    if (isIdentity(this.corners)) {
      const m = 0.03;
      this.corners = [[m, m], [1 - m, m], [1 - m, 1 - m], [m, 1 - m]];
      this.save();
    }
    this.isOpen = true;
    this.ui.hidden = false;
    this.pattern.hidden = !this.ui.querySelector('#fit-pattern').checked;
    this.select(this.selected);
    this.redrawPattern();
    this.apply();
  }

  close() {
    this.isOpen = false;
    this.ui.hidden = true;
    this.pattern.hidden = true;
  }

  toggle() { this.isOpen ? this.close() : this.open(); }
}

export { NAMES };
