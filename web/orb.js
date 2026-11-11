// The JARVIS orb: a small 3D sphere made of dots that turns slowly and moves with what the microphone hears.
// Each dot belongs to a band of the sound (low notes around the equator, high ones toward the poles): when you speak the dots in
// those bands push outward, so the whole sphere ripples with your voice, and it swells a little with the overall volume.
// The button's data-state decides the rest:
//   idle      voice off: dim, breathing slowly
//   ready     listening for "Jarvis": brighter, it shimmers with the room
//   listening it heard its name and is waiting for the command: bright and open
//   thinking  waiting for the AI: spins fast and a wave runs through it, in the second colour
//   speaking  JARVIS is talking: it pulses by itself
// Nothing is recorded or sent: the microphone is only analysed here, to move the dots.

import { orbPalette } from './theme.js';

const TAU = Math.PI * 2;
const DOTS = 760;
const BANDS = 26;
const STEPS = 14;                    // colour steps between quiet and loud; dots of one step are drawn in a single pass
const FRAME_IDLE_MS = 1000 / 24, FRAME_ACTIVE_MS = 1000 / 45;      // how often the sphere is redrawn (it used to be on every screen refresh)
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Points spread evenly over a sphere (a Fibonacci spiral), each with the band of sound it answers to and a private phase.
const X = new Float32Array(DOTS), Y = new Float32Array(DOTS), Z = new Float32Array(DOTS);
const BAND = new Uint8Array(DOTS), PHASE = new Float32Array(DOTS), SIZE = new Float32Array(DOTS);
(() => {
  const golden = Math.PI * (3 - Math.sqrt(5));
  let seed = 7;
  const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < DOTS; i++) {
    const y = 1 - (2 * (i + 0.5)) / DOTS;
    const r = Math.sqrt(1 - y * y);
    X[i] = Math.cos(golden * i) * r; Y[i] = y; Z[i] = Math.sin(golden * i) * r;
    BAND[i] = Math.min(BANDS - 1, Math.floor(Math.abs(y) * BANDS));
    PHASE[i] = rand() * TAU;
    SIZE[i] = 0.75 + rand() * 0.5;
  }
})();

const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

export class Orb {
  /** follow: another Orb whose microphone this one shares (the big calm-mode orb follows the one in the dock). */
  constructor({ canvas, button, follow = null }) {
    this.canvas = canvas;
    this.button = button;
    this.follow = follow;
    this.ctx = canvas.getContext('2d');
    this.bands = new Float32Array(BANDS);      // smoothed loudness of each band, 0..1
    this.level = 0;                            // smoothed overall volume, 0..1
    this._mic = null;
    this.micPending = false;
    this.yaw = Math.random() * TAU;
    this.last = performance.now();
    this.size = 0;
    this.ramp = null;
    this.resize();
    new ResizeObserver(() => this.resize()).observe(canvas);
    window.addEventListener('jarvis-look', () => { this.palette = null; this.ramp = null; });   // the look was switched: new colours on the next frame
    requestAnimationFrame((t) => this.frame(t));
  }

  get state() { return this.button.dataset.state || 'idle'; }

  get mic() { return this.follow ? this.follow.mic : this._mic; }

  set mic(value) { if (this.follow) this.follow.mic = value; else this._mic = value; }

  resize() {
    const size = this.canvas.clientWidth;
    if (!size || size === this.size) return;
    this.size = size;
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    this.canvas.width = this.canvas.height = Math.round(size * dpr);
    this.dpr = dpr;
  }

  // ---- microphone ------------------------------------------------------------
  /** Starts listening to the microphone for the visualizer only: nothing is recorded or sent anywhere. */
  async startMic() {
    if (this.follow || this.mic || this.micPending || this.micFailed) return;
    this.micPending = true;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const ctx = new AudioContext();
      ctx.resume?.();
      const an = ctx.createAnalyser();
      an.fftSize = 512;
      an.smoothingTimeConstant = 0.5;
      ctx.createMediaStreamSource(stream).connect(an);
      this.mic = { stream, ctx, an, freq: new Uint8Array(an.frequencyBinCount), wave: new Uint8Array(an.fftSize) };
    } catch {
      this.micFailed = true; // blocked or no microphone: the sphere still moves, just not from your voice
    } finally {
      this.micPending = false;
    }
  }

  stopMic() {
    if (this.follow || !this.mic) return;
    this.mic.stream.getTracks().forEach((t) => t.stop());
    this.mic.ctx.close?.();
    this.mic = null;
  }

  /** How loud each band should be right now, 0..1: from the voice, from the state, or silence. Also sets levelTarget. */
  targets(t) {
    const out = new Float32Array(BANDS);
    const state = this.state;
    const m = this.mic;
    if (m && state !== 'speaking' && state !== 'thinking') {
      m.an.getByteFrequencyData(m.freq);
      m.an.getByteTimeDomainData(m.wave);
      let sum = 0;
      for (let i = 0; i < m.wave.length; i++) { const v = (m.wave[i] - 128) / 128; sum += v * v; }
      this.levelTarget = Math.min(1, Math.sqrt(sum / m.wave.length) * 7);
      for (let b = 0; b < BANDS; b++) {
        const bin = 1 + Math.floor(Math.pow(b / (BANDS - 1), 1.35) * 56);   // speech lives in the lowest ~60 bins
        const v = Math.max(0, (m.freq[bin] / 255 - 0.1) / 0.9);
        out[b] = Math.min(1, Math.pow(v, 1.1) * 1.3);
      }
    } else if (state === 'speaking') {
      this.levelTarget = 0.5 + 0.25 * Math.sin(t * 7);
      for (let b = 0; b < BANDS; b++) out[b] = 0.2 + 0.55 * Math.abs(Math.sin(t * 5.2 + b * 0.5) * Math.sin(t * 2.1 + b * 0.19));
    } else if (state === 'thinking') {
      this.levelTarget = 0.22;
      for (let b = 0; b < BANDS; b++) out[b] = 0.1 + 0.16 * (0.5 + 0.5 * Math.sin(t * 6 - b * 0.45));
    } else {
      this.levelTarget = 0;
    }
    return out;
  }

  // ---- drawing ---------------------------------------------------------------
  frame(now) {
    requestAnimationFrame((t) => this.frame(t));
    if (document.hidden || !this.size) return;
    // Calm mode swaps which orb is on show: the one that can't be seen isn't redrawn.
    if (this.follow && !document.body.classList.contains('ambient')) return;
    // Not every screen refresh: a dim, idle sphere moves gently at 24 frames a second, and one that is listening or speaking at 45. A 144 Hz
    // monitor used to make this redraw 144 times a second for nothing.
    const state = this.state;
    const gap = state === 'idle' || state === 'ready' ? FRAME_IDLE_MS : FRAME_ACTIVE_MS;
    if (now - this.last < gap - 2) return;
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    const t = now / 1000;

    const target = this.targets(t);
    const steps = Math.max(1, dt * 60);                                       // the smoothing below was tuned for 60 frames a second
    const rise = 1 - Math.pow(1 - 0.6, steps), fall = 1 - Math.pow(1 - 0.12, steps), follow = 1 - Math.pow(1 - 0.25, steps);
    for (let b = 0; b < BANDS; b++) this.bands[b] += (target[b] - this.bands[b]) * (target[b] > this.bands[b] ? rise : fall);
    this.level += ((this.levelTarget || 0) - this.level) * follow;

    const spin = reduceMotion ? 0.04 : state === 'thinking' ? 1.7 : state === 'listening' ? 0.5 : state === 'idle' ? 0.12 : 0.28;
    this.yaw += spin * dt;
    this.draw(t, state);
  }

  colours() {
    const P = this.palette || (this.palette = orbPalette());
    const quiet = P.bar0, loud = P.bar1, other = hexToRgb(P.ring[2]);
    this.ramp = {
      calm: Array.from({ length: STEPS }, (_, k) => `rgb(${mix(quiet, loud, k / (STEPS - 1)).join(',')})`),
      busy: Array.from({ length: STEPS }, (_, k) => `rgb(${mix(mix(quiet, other, 0.6), loud, k / (STEPS - 1)).join(',')})`),
      glow: P.glow,
    };
    return this.ramp;
  }

  draw(t, state) {
    const { ctx, size: S, dpr } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, S, S);
    const c = S / 2;
    const m = c - S * 0.07;                                                  // the sphere sits a little above the middle, clear of the label under it
    const ramp = this.ramp || this.colours();
    const colours = state === 'thinking' ? ramp.busy : ramp.calm;

    const awake = state === 'idle' ? 0.5 : state === 'ready' ? 0.72 : 1;       // how bright the dots are
    const breathe = 0.5 + 0.5 * Math.sin(t * (state === 'idle' ? 1.1 : state === 'thinking' ? 4.5 : 1.8));
    const swell = 1 + this.level * 0.14 + (state === 'listening' ? 0.05 : 0) + 0.025 * breathe;
    const R = S * 0.25 * swell;          // the loudest the dots can get still stays inside the canvas (about 0.41 of its width from the middle)

    // A soft glow behind the dots that follows the volume.
    const glow = ctx.createRadialGradient(c, m, 0, c, m, S * 0.5);
    glow.addColorStop(0, `rgba(${ramp.glow}, ${0.07 + 0.2 * this.level + 0.05 * awake})`);
    glow.addColorStop(1, `rgba(${ramp.glow}, 0)`);
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, S, S);

    const tilt = 0.42 + 0.06 * Math.sin(t * 0.4);
    const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw), ct = Math.cos(tilt), st = Math.sin(tilt);
    const dotR = S * 0.0062;
    const paths = [[], []];                                                    // [back, front] x STEPS paths, filled once each
    for (let p = 0; p < 2; p++) for (let k = 0; k < STEPS; k++) paths[p].push(new Path2D());

    for (let i = 0; i < DOTS; i++) {
      const x1 = X[i] * cy + Z[i] * sy, z1 = -X[i] * sy + Z[i] * cy;
      const y2 = Y[i] * ct - z1 * st, z2 = Y[i] * st + z1 * ct;                // z2 > 0 is toward the viewer
      let amp = this.bands[BAND[i]] * (0.65 + 0.35 * Math.sin(PHASE[i] + t * 2.4));
      if (state === 'thinking') amp += 0.3 * (0.5 + 0.5 * Math.sin(t * 5.5 - Y[i] * 4.5 + PHASE[i] * 0.2));
      else if (state === 'idle' || state === 'ready') amp += 0.06 * (0.5 + 0.5 * Math.sin(t * 0.9 + Y[i] * 3 + PHASE[i]));
      amp = Math.min(1, amp);
      const out = 1 + amp * 0.36;
      const persp = 1 / (1 - z2 * 0.3);
      const px = c + x1 * R * out * persp, py = m + y2 * R * out * persp;
      const depth = (z2 + 1) / 2;                                              // 0 at the back, 1 at the front
      const r = dotR * SIZE[i] * (0.6 + 0.6 * depth) * (1 + amp * 0.9);
      const step = Math.min(STEPS - 1, Math.round((amp * 0.8 + depth * 0.3) * (STEPS - 1)));
      const path = paths[z2 >= 0 ? 1 : 0][step];
      path.moveTo(px + r, py);
      path.arc(px, py, r, 0, TAU);
    }
    for (let p = 0; p < 2; p++) {
      ctx.globalAlpha = (p ? 0.95 : 0.4) * awake;
      for (let k = 0; k < STEPS; k++) { ctx.fillStyle = colours[k]; ctx.fill(paths[p][k]); }
    }
    ctx.globalAlpha = 1;

    // Speaking: a thin ripple leaves the sphere.
    if (state === 'speaking') {
      for (let k = 0; k < 2; k++) {
        const pr = (t * 0.7 + k * 0.5) % 1;
        ctx.strokeStyle = `rgba(${ramp.glow}, ${0.35 * (1 - pr)})`;
        ctx.lineWidth = S * 0.004;
        ctx.beginPath(); ctx.arc(c, m, R * (1.15 + pr * 0.55), 0, TAU); ctx.stroke();
      }
    }
  }
}
