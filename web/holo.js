// The hologram card: a rotating 3D wireframe or an animated chart, drawn on a canvas in a glowing "projected" style. JARVIS
// fills it when asked to show something ("show me a torus", "chart these numbers"). There is no 3D library: the models are
// lists of points and edges that are rotated and projected here.

const TAU = Math.PI * 2;
import { canvasPalette, currentLook } from './theme.js';

// The colours follow the chosen look (theme.js); draw() refreshes them at the start of every frame, so switching the look repaints at once.
let CYAN = '0, 229, 255';
let BRIGHT = '190, 250, 255';
let PALE = '220, 252, 255';
let HEXB = '#8ff3ff';
let TEXT = 'rgba(160, 220, 235, 0.8)';
let WHITE = '#e8f4ff';
let SCAN = 'rgba(0, 20, 30, 0.22)';
let PALETTE = ['#00e5ff', '#4d8dff', '#5cff8a', '#ffb300', '#c77dff', '#ff6fb5', '#ff7a59', '#9be7ff'];
function refreshPalette() {
  const look = currentLook(), c = canvasPalette(look), classic = look === 'classic';
  CYAN = c.rgb; BRIGHT = classic ? '190, 250, 255' : c.bright; PALE = classic ? '220, 252, 255' : c.pale; HEXB = classic ? '#8ff3ff' : c.hexBright;
  TEXT = c.text; WHITE = classic ? '#e8f4ff' : '#f2f5fb'; SCAN = classic ? 'rgba(0, 20, 30, 0.22)' : 'rgba(10, 14, 26, 0.2)'; PALETTE = c.series;
}
const W = 520, H = 360;

// ---- models: { v: [[x,y,z]...], e: [[a,b]...] } within a unit sphere ---------------------------------------------

function grid(rings, around, point, wrapRings = false) {
  const v = [], e = [];
  for (let i = 0; i < rings; i++) for (let j = 0; j < around; j++) v.push(point(i, j));
  for (let i = 0; i < rings; i++) {
    for (let j = 0; j < around; j++) {
      e.push([i * around + j, i * around + ((j + 1) % around)]);
      if (i < rings - 1) e.push([i * around + j, (i + 1) * around + j]);
      else if (wrapRings) e.push([i * around + j, j]);
    }
  }
  return { v, e };
}

export const MODELS = {
  cube() {
    const s = 0.62, v = [];
    for (const x of [-s, s]) for (const y of [-s, s]) for (const z of [-s, s]) v.push([x, y, z]);
    const e = [];
    for (let a = 0; a < 8; a++) for (let b = a + 1; b < 8; b++) if ([a ^ b].some((d) => d === 1 || d === 2 || d === 4)) e.push([a, b]);
    return { v, e };
  },
  pyramid() {
    const v = [[-0.6, -0.5, -0.6], [0.6, -0.5, -0.6], [0.6, -0.5, 0.6], [-0.6, -0.5, 0.6], [0, 0.75, 0]];
    return { v, e: [[0, 1], [1, 2], [2, 3], [3, 0], [0, 4], [1, 4], [2, 4], [3, 4]] };
  },
  sphere() {
    return grid(9, 18, (i, j) => {
      const lat = -Math.PI / 2 + ((i + 0.5) / 9) * Math.PI, lon = (j / 18) * TAU;
      return [0.9 * Math.cos(lat) * Math.cos(lon), 0.9 * Math.sin(lat), 0.9 * Math.cos(lat) * Math.sin(lon)];
    });
  },
  torus() {
    return grid(24, 12, (i, j) => {
      const u = (i / 24) * TAU, w = (j / 12) * TAU, r = 0.28;
      return [(0.66 + r * Math.cos(w)) * Math.cos(u), r * Math.sin(w), (0.66 + r * Math.cos(w)) * Math.sin(u)];
    }, true);
  },
  icosahedron() {
    const p = (1 + Math.sqrt(5)) / 2, n = 0.5;
    const v = [];
    for (const a of [-1, 1]) for (const b of [-p, p]) { v.push([0, a * n, b * n], [a * n, b * n, 0], [b * n, 0, a * n]); }
    const e = [];
    for (let a = 0; a < v.length; a++) for (let b = a + 1; b < v.length; b++) {
      const d = Math.hypot(v[a][0] - v[b][0], v[a][1] - v[b][1], v[a][2] - v[b][2]);
      if (Math.abs(d - 2 * n) < 0.01) e.push([a, b]);
    }
    return { v, e };
  },
  helix() {
    const n = 44, v = [], e = [];
    for (let i = 0; i < n; i++) {
      const t = (i / (n - 1)) * 3.2 * Math.PI, y = (i / (n - 1)) * 1.7 - 0.85;
      v.push([0.5 * Math.cos(t), y, 0.5 * Math.sin(t)]);
    }
    for (let i = 0; i < n; i++) {
      const t = (i / (n - 1)) * 3.2 * Math.PI + Math.PI, y = (i / (n - 1)) * 1.7 - 0.85;
      v.push([0.5 * Math.cos(t), y, 0.5 * Math.sin(t)]);
    }
    for (let i = 0; i < n - 1; i++) e.push([i, i + 1], [n + i, n + i + 1]);
    for (let i = 0; i < n; i += 3) e.push([i, n + i]);
    return { v, e };
  },
  globe() {
    const m = MODELS.sphere();
    // a few bright "cities" along the surface, as short spikes
    const spots = [[0.5, 0.4], [-0.3, 1.9], [0.1, -1.2], [-0.6, 3.5], [0.7, 2.7], [0.0, 4.6]];
    spots.forEach(([lat, lon]) => {
      const a = m.v.length;
      m.v.push([Math.cos(lat) * Math.cos(lon) * 0.9, Math.sin(lat) * 0.9, Math.cos(lat) * Math.sin(lon) * 0.9],
        [Math.cos(lat) * Math.cos(lon) * 1.08, Math.sin(lat) * 1.08, Math.cos(lat) * Math.sin(lon) * 1.08]);
      m.e.push([a, a + 1]);
    });
    m.tilt = 0.41;
    return m;
  },
  reactor() {
    const v = [], e = [], rings = [[0.3, 0.1, 12], [0.62, 0, 24], [0.92, -0.1, 36]];
    const starts = [];
    for (const [r, z, n] of rings) {
      starts.push(v.length);
      for (let i = 0; i < n; i++) v.push([r * Math.cos((i / n) * TAU), r * Math.sin((i / n) * TAU), z]);
      for (let i = 0; i < n; i++) e.push([starts.at(-1) + i, starts.at(-1) + ((i + 1) % n)]);
    }
    for (let i = 0; i < 12; i++) e.push([starts[0] + i, starts[1] + i * 2], [starts[1] + i * 2, starts[2] + i * 3]);
    const core = v.length;
    v.push([0, 0, 0.12]);
    for (let i = 0; i < 12; i += 4) e.push([core, starts[0] + i]);
    return { v, e };
  },
};

/** The AI's own model: scale and centre it into the unit sphere. */
export function customModel(vertices, edges) {
  const v = [];
  for (let i = 0; i + 2 < vertices.length; i += 3) v.push([vertices[i], vertices[i + 1], vertices[i + 2]]);
  const c = [0, 1, 2].map((k) => (Math.max(...v.map((p) => p[k])) + Math.min(...v.map((p) => p[k]))) / 2);
  let r = 0;
  v.forEach((p) => { for (let k = 0; k < 3; k++) p[k] -= c[k]; r = Math.max(r, Math.hypot(...p)); });
  v.forEach((p) => { for (let k = 0; k < 3; k++) p[k] = (p[k] / (r || 1)) * 0.9; });
  const e = [];
  for (let i = 0; i + 1 < edges.length; i += 2) if (edges[i] < v.length && edges[i + 1] < v.length) e.push([edges[i], edges[i + 1]]);
  return { v, e };
}

const fmt = (n) => (Math.abs(n) >= 1e9 ? `${+(n / 1e9).toFixed(1)}B` : Math.abs(n) >= 1e6 ? `${+(n / 1e6).toFixed(1)}M` : Math.abs(n) >= 1e4 ? `${+(n / 1e3).toFixed(1)}k` : `${+n.toFixed(2)}`);
const ease = (x) => 1 - (1 - Math.min(1, Math.max(0, x))) ** 3;

export class Holo {
  constructor({ el }) {
    this.root = el;
    this.canvas = el.querySelector('#holo-canvas, .holo-canvas');
    this.caption = el.querySelector('#holo-caption, .holo-caption');
    this.title = el.querySelector('#holo-title, .holo-title');
    this.canvas.width = W * 2;
    this.canvas.height = H * 2;
    this.frame = 0;
    this.visible = false;
    this.state = { kind: 'model', shape: 'reactor', title: 'Arc reactor' };
    this.begin(this.state);
  }

  begin(state) {
    this.state = state;
    this.t0 = performance.now();
    this.model = state.kind === 'model' ? (state.shape === 'custom' ? customModel(state.vertices, state.edges) : MODELS[state.shape]()) : null;
    this.title.textContent = (state.title || '').toUpperCase();
    this.caption.textContent = state.kind === 'chart' ? `${state.chart} chart${state.unit ? ` · ${state.unit}` : ''}` : `${state.shape === 'custom' ? 'custom model' : state.shape}`;
  }

  /** The AI (or anything else) puts something on the card. */
  show(event) { this.begin(event); }

  onShow() {
    this.visible = true;
    const loop = (now) => {
      if (!this.visible) return;
      this.draw((now - this.t0) / 1000);
      this.frame = requestAnimationFrame(loop);
    };
    this.frame = requestAnimationFrame(loop);
  }

  onHide() { this.visible = false; cancelAnimationFrame(this.frame); }

  draw(t) {
    refreshPalette();
    const g = this.canvas.getContext('2d');
    g.setTransform(2, 0, 0, 2, 0, 0);
    g.clearRect(0, 0, W, H);
    const reveal = ease(t / 0.9);
    g.save();
    g.beginPath();
    g.rect(0, 0, W, H * reveal);                     // the picture is "printed" from the top down
    g.clip();
    if (this.state.kind === 'chart') this.drawChart(g, t); else this.drawModel(g, t);
    g.restore();
    if (reveal < 1) {                                // the bright scan line that does the printing
      g.fillStyle = `rgba(${CYAN}, 0.9)`;
      g.shadowColor = `rgba(${CYAN}, 1)`;
      g.shadowBlur = 12;
      g.fillRect(0, H * reveal - 1, W, 2);
      g.shadowBlur = 0;
    }
    // faint scan lines and flicker over everything
    g.fillStyle = SCAN;
    for (let y = ((t * 18) % 4) - 4; y < H; y += 4) g.fillRect(0, y, W, 1);
  }

  drawModel(g, t) {
    const m = this.model;
    if (!m) return;
    const yaw = t * 0.7, pitch = -0.38 + Math.sin(t * 0.5) * 0.08, tilt = m.tilt || 0;
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch), ct = Math.cos(tilt), st = Math.sin(tilt);
    const focal = 3.4, scale = Math.min(W, H) * 0.34, ox = W / 2, oy = H / 2 - 12;
    const pts = m.v.map(([x, y, z]) => {
      const x0 = x * ct - y * st, y0 = x * st + y * ct;                  // axial tilt (the globe)
      const x1 = x0 * cy + z * sy, z1 = -x0 * sy + z * cy;               // spin around the vertical axis
      const y2 = y0 * cp - z1 * sp, z2 = y0 * sp + z1 * cp;              // look slightly from above
      const k = focal / (focal + z2);
      return [ox + x1 * scale * k, oy - y2 * scale * k, z2];
    });
    // the glowing base ring the model "stands" on
    g.strokeStyle = `rgba(${CYAN}, ${0.35 + 0.15 * Math.sin(t * 2)})`;
    g.lineWidth = 1.2;
    for (const r of [1.5, 1.9]) {
      g.beginPath();
      g.ellipse(ox, oy + scale * 1.25, scale * r, scale * r * 0.22, 0, 0, TAU);
      g.stroke();
    }
    const flicker = 0.9 + 0.1 * Math.sin(t * 23) * Math.sin(t * 7.3);
    g.lineCap = 'round';
    for (const [a, b] of m.e) {
      const p = pts[a], q = pts[b], depth = (p[2] + q[2]) / 2;           // nearer edges are brighter
      const alpha = Math.max(0.12, Math.min(1, 0.62 - depth * 0.55)) * flicker;
      g.strokeStyle = `rgba(${CYAN}, ${alpha * 0.28})`;
      g.lineWidth = 4;
      g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke();
      g.strokeStyle = `rgba(${BRIGHT}, ${alpha})`;
      g.lineWidth = 1.1;
      g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(q[0], q[1]); g.stroke();
    }
    if (pts.length <= 90) {
      g.fillStyle = `rgba(${PALE}, ${0.8 * flicker})`;
      for (const p of pts) g.fillRect(p[0] - 1.5, p[1] - 1.5, 3, 3);
    }
  }

  drawChart(g, t) {
    const { chart, labels, values, unit } = this.state;
    const grow = ease(t / 1.1 - 0.15);
    const left = 56, right = W - 20, top = 24, bottom = H - 62, n = values.length;
    g.font = '12px "Segoe UI", system-ui, sans-serif';
    g.textBaseline = 'middle';
    if (chart === 'pie') return this.drawPie(g, t, grow);
    if (chart === 'radar') return this.drawRadar(g, grow);
    const lo = Math.min(0, ...values), hi = Math.max(0.0001, ...values), span = hi - lo || 1;
    const y = (v) => bottom - ((v - lo) / span) * (bottom - top);
    g.strokeStyle = `rgba(${CYAN}, 0.18)`;
    g.fillStyle = TEXT;
    g.lineWidth = 1;
    g.textAlign = 'right';
    for (let i = 0; i <= 4; i++) {
      const v = lo + (span * i) / 4, yy = y(v);
      g.beginPath(); g.moveTo(left, yy); g.lineTo(right, yy); g.stroke();
      g.fillText(fmt(v), left - 8, yy);
    }
    const step = (right - left) / n;
    g.textAlign = 'center';
    labels.forEach((label, i) => {
      if (n > 12 && i % 2) return;
      g.fillStyle = TEXT;
      g.fillText(label.length > 9 ? `${label.slice(0, 8)}…` : label, left + step * (i + 0.5), bottom + 16);
    });
    if (chart === 'bar') {
      values.forEach((v, i) => {
        const local = ease(grow * 1.4 - (i / n) * 0.4), x = left + step * i + step * 0.18, w = step * 0.64, top0 = y(Math.max(v, 0)), base = y(Math.min(v, 0));
        const h = (base - top0) * local, yy = v >= 0 ? base - h : base;
        const grad = g.createLinearGradient(0, yy, 0, yy + h);
        grad.addColorStop(0, `rgba(${CYAN}, 0.85)`); grad.addColorStop(1, `rgba(${CYAN}, 0.12)`);
        g.fillStyle = grad; g.fillRect(x, yy, w, h);
        g.strokeStyle = `rgba(${BRIGHT}, 0.9)`; g.strokeRect(x + 0.5, yy + 0.5, w - 1, h - 1);
        if (local > 0.9) { g.fillStyle = WHITE; g.textAlign = 'center'; g.fillText(fmt(v), x + w / 2, yy - 9); }
      });
    } else {
      const xs = values.map((_, i) => left + step * (i + 0.5)), ys = values.map(y);
      const upTo = grow * (n - 1);
      g.beginPath();
      for (let i = 0; i < n; i++) {
        if (i > upTo + 1) break;
        const f = Math.min(1, upTo - i + 1), px = i ? xs[i - 1] + (xs[i] - xs[i - 1]) * f : xs[0], py = i ? ys[i - 1] + (ys[i] - ys[i - 1]) * f : ys[0];
        if (i === 0) g.moveTo(xs[0], ys[0]); else g.lineTo(px, py);
      }
      g.shadowColor = `rgba(${CYAN}, 1)`; g.shadowBlur = 10;
      g.strokeStyle = HEXB; g.lineWidth = 2.2; g.stroke(); g.shadowBlur = 0;
      xs.forEach((x, i) => { if (i <= upTo + 0.2) { g.fillStyle = WHITE; g.beginPath(); g.arc(x, ys[i], 3.2, 0, TAU); g.fill(); if (n <= 12) { g.textAlign = 'center'; g.fillText(fmt(values[i]), x, ys[i] - 11); } } });
    }
    if (unit) { g.fillStyle = TEXT; g.textAlign = 'left'; g.fillText(unit, left, 10); }
  }

  drawPie(g, t, grow) {
    const { labels, values } = this.state, total = values.reduce((a, b) => a + b, 0) || 1;
    const cx = 160, cy = H / 2 - 4, R = 118, r = 62;
    let a0 = -Math.PI / 2;
    values.forEach((v, i) => {
      const sweep = (v / total) * TAU * grow, color = PALETTE[i % PALETTE.length];
      g.beginPath(); g.arc(cx, cy, R, a0, a0 + sweep); g.arc(cx, cy, r, a0 + sweep, a0, true); g.closePath();
      g.fillStyle = `${color}55`; g.fill(); g.strokeStyle = color; g.lineWidth = 1.5; g.stroke();
      a0 += sweep;
    });
    g.font = '13px "Segoe UI", system-ui, sans-serif'; g.textBaseline = 'middle'; g.textAlign = 'left';
    labels.slice(0, 12).forEach((label, i) => {
      const yy = 40 + i * 24;
      g.fillStyle = PALETTE[i % PALETTE.length]; g.fillRect(310, yy - 5, 10, 10);
      g.fillStyle = WHITE; g.fillText(`${label.length > 14 ? `${label.slice(0, 13)}…` : label}  ${Math.round((values[i] / total) * 100)}%`, 328, yy);
    });
    g.textAlign = 'center'; g.fillStyle = WHITE; g.font = '20px "Segoe UI", system-ui, sans-serif';
    g.fillText(fmt(total), cx, cy);
  }

  drawRadar(g, grow) {
    const { labels, values } = this.state, n = values.length, hi = Math.max(0.0001, ...values);
    const cx = W / 2, cy = H / 2 - 4, R = 118;
    g.strokeStyle = `rgba(${CYAN}, 0.2)`; g.lineWidth = 1;
    for (let ring = 1; ring <= 4; ring++) {
      g.beginPath();
      for (let i = 0; i < n; i++) { const a = (i / n) * TAU - Math.PI / 2; g.lineTo(cx + Math.cos(a) * R * (ring / 4), cy + Math.sin(a) * R * (ring / 4)); }
      g.closePath(); g.stroke();
    }
    g.font = '12px "Segoe UI", system-ui, sans-serif'; g.textBaseline = 'middle'; g.textAlign = 'center'; g.fillStyle = `rgba(${PALE}, 0.9)`;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * TAU - Math.PI / 2;
      g.beginPath(); g.moveTo(cx, cy); g.lineTo(cx + Math.cos(a) * R, cy + Math.sin(a) * R); g.stroke();
      g.fillText(labels[i].length > 11 ? `${labels[i].slice(0, 10)}…` : labels[i], cx + Math.cos(a) * (R + 22), cy + Math.sin(a) * (R + 14));
    }
    g.beginPath();
    values.forEach((v, i) => { const a = (i / n) * TAU - Math.PI / 2, d = (Math.max(0, v) / hi) * R * grow; g.lineTo(cx + Math.cos(a) * d, cy + Math.sin(a) * d); });
    g.closePath();
    g.fillStyle = `rgba(${CYAN}, 0.22)`; g.fill();
    g.shadowColor = `rgba(${CYAN}, 1)`; g.shadowBlur = 10; g.strokeStyle = HEXB; g.lineWidth = 2; g.stroke(); g.shadowBlur = 0;
  }
}
