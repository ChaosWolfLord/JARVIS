// The JARVIS orb: a glowing ring with the name inside, drawn on a canvas. Around the ring is a circle of bars
// that is also the voice visualizer: while the microphone is on they move with your voice (the volume sets how
// tall they are and the pitch sets which bars move). The button's data-state decides the rest:
//   idle      voice off: the ring breathes slowly
//   ready     listening for "Jarvis": same, with the bars awake
//   listening it heard its name and is waiting for the command: brighter ring
//   thinking  waiting for the AI: the white arcs spin fast and the ring throbs
//   speaking  JARVIS is talking: the bars dance by themselves and ripples leave the ring

const TAU = Math.PI * 2;
const BARS = 72;
const HALF = BARS / 2;
const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

export class Orb {
  /** follow: another Orb whose microphone this one shares (the big calm-mode orb follows the one in the dock). */
  constructor({ canvas, button, follow = null }) {
    this.canvas = canvas;
    this.button = button;
    this.follow = follow;
    this.ctx = canvas.getContext('2d');
    this.bars = new Float32Array(BARS); // smoothed bar heights, 0..1
    this.level = 0;                      // smoothed overall volume, 0..1
    this._mic = null;
    this.micPending = false;
    this.spinA = 0;
    this.spinB = 2;
    this.last = performance.now();
    this.size = 0;
    this.resize();
    new ResizeObserver(() => this.resize()).observe(canvas);
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
      an.smoothingTimeConstant = 0.55;
      ctx.createMediaStreamSource(stream).connect(an);
      this.mic = { stream, ctx, an, freq: new Uint8Array(an.frequencyBinCount), wave: new Uint8Array(an.fftSize) };
    } catch {
      this.micFailed = true; // blocked or no microphone: the ring still animates, just not from your voice
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

  /** Where each bar should be right now, 0..1, from the voice, the state, or a gentle idle breath. */
  targets(t) {
    const out = new Float32Array(BARS);
    const state = this.state;
    const m = this.mic;
    if (m && state !== 'speaking' && state !== 'thinking') {
      m.an.getByteFrequencyData(m.freq);
      m.an.getByteTimeDomainData(m.wave);
      let sum = 0;
      for (let i = 0; i < m.wave.length; i++) { const v = (m.wave[i] - 128) / 128; sum += v * v; }
      this.levelTarget = Math.min(1, Math.sqrt(sum / m.wave.length) * 7);
      for (let i = 0; i < BARS; i++) {
        const idx = i < HALF ? i : BARS - 1 - i;            // mirrored, so it looks balanced
        const bin = 1 + Math.floor(Math.pow(idx / (HALF - 1), 1.35) * 42); // speech lives in the lowest ~45 bins
        const v = Math.max(0, (m.freq[bin] / 255 - 0.12) / 0.88);
        out[i] = Math.min(1, Math.pow(v, 1.15) * 1.25);
      }
    } else if (state === 'speaking') {
      this.levelTarget = 0.55 + 0.25 * Math.sin(t * 7);
      for (let i = 0; i < BARS; i++) {
        const idx = i < HALF ? i : BARS - 1 - i;
        out[i] = 0.22 + 0.5 * Math.abs(Math.sin(t * 5.5 + idx * 0.55) * Math.sin(t * 2.3 + idx * 0.17));
      }
    } else if (state === 'thinking') {
      this.levelTarget = 0.25;
      for (let i = 0; i < BARS; i++) out[i] = 0.12 + 0.1 * Math.sin(t * 6 - i * 0.35);
    } else {
      this.levelTarget = 0;
    }
    const breath = state === 'idle' ? 0.04 : 0.07;
    for (let i = 0; i < BARS; i++) out[i] = Math.max(out[i], breath + 0.03 * Math.sin(t * 1.4 + i * 0.5));
    return out;
  }

  // ---- drawing ---------------------------------------------------------------
  frame(now) {
    requestAnimationFrame((t) => this.frame(t));
    if (document.hidden || !this.size) return;
    // Calm mode swaps which orb is on show: the one that can't be seen isn't redrawn.
    if (this.follow && !document.body.classList.contains('ambient')) return;
    const dt = Math.min(0.1, (now - this.last) / 1000);
    this.last = now;
    const t = now / 1000;
    const state = this.state;

    const target = this.targets(t);
    for (let i = 0; i < BARS; i++) this.bars[i] += (target[i] - this.bars[i]) * (target[i] > this.bars[i] ? 0.55 : 0.14);
    this.level += ((this.levelTarget || 0) - this.level) * 0.25;

    const spin = reduceMotion ? 0.05 : state === 'thinking' ? 3.4 : state === 'listening' ? 0.9 : 0.35;
    this.spinA += spin * dt;
    this.spinB -= spin * 0.55 * dt;
    this.draw(t, state);
  }

  draw(t, state) {
    const { ctx, size: S, dpr } = this;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, S, S);
    const c = S / 2;
    const breathe = state === 'idle' ? 0.5 + 0.5 * Math.sin(t * 1.1) : 0.5 + 0.5 * Math.sin(t * (state === 'thinking' ? 4.5 : 2));
    const lift = Math.min(1, this.level * 0.9 + (state === 'listening' ? 0.35 : 0) + (state === 'thinking' ? 0.2 * breathe : 0));
    const R = S * 0.285 * (1 + this.level * 0.025);

    // The faint outer circle and the ring of dots on it.
    ctx.lineWidth = 1;
    ctx.strokeStyle = 'rgba(150, 215, 255, 0.26)';
    ctx.beginPath(); ctx.arc(c, c, S * 0.468, 0, TAU); ctx.stroke();
    ctx.fillStyle = 'rgba(190, 230, 255, 0.5)';
    for (let i = 0; i < 90; i++) {
      const a = (i / 90) * TAU;
      ctx.beginPath(); ctx.arc(c + Math.cos(a) * S * 0.452, c + Math.sin(a) * S * 0.452, S * 0.0035, 0, TAU); ctx.fill();
    }

    // Speaking: ripples leave the ring.
    if (state === 'speaking') {
      for (let k = 0; k < 2; k++) {
        const p = (t * 0.8 + k * 0.5) % 1;
        ctx.strokeStyle = `rgba(110, 205, 255, ${0.5 * (1 - p)})`;
        ctx.lineWidth = S * 0.006;
        ctx.beginPath(); ctx.arc(c, c, R + p * S * 0.16, 0, TAU); ctx.stroke();
      }
    }

    // The voice bars.
    ctx.lineCap = 'round';
    ctx.lineWidth = S * 0.0105;
    const r0 = S * 0.345;
    for (let i = 0; i < BARS; i++) {
      const v = this.bars[i];
      const a = -Math.PI / 2 + (i / BARS) * TAU;
      const len = S * (0.01 + v * 0.088);
      ctx.strokeStyle = `rgba(${150 + 90 * v}, ${215 + 30 * v}, 255, ${0.35 + 0.65 * Math.min(1, v * 1.4)})`;
      ctx.beginPath();
      ctx.moveTo(c + Math.cos(a) * r0, c + Math.sin(a) * r0);
      ctx.lineTo(c + Math.cos(a) * (r0 + len), c + Math.sin(a) * (r0 + len));
      ctx.stroke();
    }

    // The two white arcs that circle the ring.
    ctx.lineWidth = S * 0.0075;
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.92)';
    ctx.beginPath(); ctx.arc(c, c, S * 0.322, this.spinA, this.spinA + 0.95); ctx.stroke();
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.55)';
    ctx.beginPath(); ctx.arc(c, c, S * 0.322, this.spinB, this.spinB + 0.34); ctx.stroke();

    // The dark centre, then the glowing blue ring around it.
    ctx.fillStyle = 'rgba(1, 5, 11, 0.97)';
    ctx.beginPath(); ctx.arc(c, c, R - S * 0.012, 0, TAU); ctx.fill();

    const grad = ctx.createLinearGradient(c - R, c - R, c + R, c + R);
    grad.addColorStop(0, '#8fe0ff');
    grad.addColorStop(0.5, '#2e9bff');
    grad.addColorStop(1, '#1b63ff');
    ctx.lineWidth = S * (0.046 + lift * 0.014);
    ctx.strokeStyle = grad;
    ctx.shadowColor = `rgba(50, 165, 255, ${0.65 + 0.3 * lift})`;
    ctx.shadowBlur = S * (0.07 + 0.07 * lift + 0.02 * breathe);
    ctx.beginPath(); ctx.arc(c, c, R, 0, TAU); ctx.stroke();
    ctx.shadowBlur = S * 0.025;
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.lineWidth = Math.max(1, S * 0.006);
    ctx.strokeStyle = 'rgba(215, 245, 255, 0.85)';
    ctx.beginPath(); ctx.arc(c, c, R - S * 0.032, 0, TAU); ctx.stroke();

    // The name.
    ctx.fillStyle = '#fff';
    ctx.font = `300 ${S * 0.092}px "Segoe UI", "Helvetica Neue", sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    const gap = S * 0.011;
    if ('letterSpacing' in ctx) ctx.letterSpacing = `${gap}px`;
    ctx.shadowColor = 'rgba(120, 200, 255, 0.55)';
    ctx.shadowBlur = S * 0.03;
    ctx.fillText('JARVIS', c + gap / 2, c + S * 0.004);
    ctx.shadowBlur = 0;
  }
}
