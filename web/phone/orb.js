// JARVIS's orb on the phone: a small 3D sphere of dots, the same one the PC shows. It turns slowly and the dots push outward with the sound:
// in the Android app the phone's own recognizer reports how loud you are (window.__speech('rms', ...)), so the sphere moves with your voice while
// you talk to it; otherwise it moves by itself. States: idle (dim, breathing), ready (awake), listening (open, follows your voice), thinking
// (spins, a wave runs through it), speaking (pulses), offline (very dim). Nothing here records or sends anything.

(() => {
  const TAU = Math.PI * 2;
  const DOTS = 520;
  const BANDS = 20;
  const STEPS = 12;
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const X = new Float32Array(DOTS), Y = new Float32Array(DOTS), Z = new Float32Array(DOTS);
  const BAND = new Uint8Array(DOTS), PHASE = new Float32Array(DOTS), SIZE = new Float32Array(DOTS);
  const golden = Math.PI * (3 - Math.sqrt(5));
  let seed = 11;
  const rand = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
  for (let i = 0; i < DOTS; i++) {
    const y = 1 - (2 * (i + 0.5)) / DOTS, r = Math.sqrt(1 - y * y);
    X[i] = Math.cos(golden * i) * r; Y[i] = y; Z[i] = Math.sin(golden * i) * r;
    BAND[i] = Math.min(BANDS - 1, Math.floor(Math.abs(y) * BANDS));
    PHASE[i] = rand() * TAU;
    SIZE[i] = 0.75 + rand() * 0.5;
  }

  const rgb = (text, fallback) => {
    const v = String(text || '').split(',').map((n) => parseInt(n, 10));
    return v.length === 3 && v.every(Number.isFinite) ? v : fallback;
  };
  const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));

  class PhoneOrb {
    constructor(canvas, state = 'idle') {
      this.canvas = canvas;
      canvas.orb = this;                   // so a test (or the console) can reach it
      this.ctx = canvas.getContext('2d');
      this.state = state;
      this.level = 0;                      // 0..1, what the recognizer last said (smoothed below)
      this.levelAt = 0;
      this.smooth = 0;
      this.bands = new Float32Array(BANDS);
      this.yaw = rand() * TAU;
      this.size = 0;
      this.last = performance.now();
      this.ramp = null;
      this.resize();
      if (window.ResizeObserver) new ResizeObserver(() => this.resize()).observe(canvas);
      requestAnimationFrame((t) => this.frame(t));
    }

    resize() {
      const size = this.canvas.clientWidth;
      if (!size || size === this.size) return;
      this.size = size;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      this.canvas.width = this.canvas.height = Math.round(size * dpr);
      this.dpr = dpr;
    }

    /** The loudness the phone's recognizer just reported (0 to 1). */
    hear(level) {
      this.level = Math.max(0, Math.min(1, Number(level) || 0));
      this.levelAt = performance.now();
    }

    colours() {
      const css = getComputedStyle(document.documentElement);
      const a = rgb(css.getPropertyValue('--accent'), [122, 190, 255]), b = rgb(css.getPropertyValue('--accent2'), [176, 142, 255]);
      const loud = mix(a, [255, 255, 255], 0.75);
      this.ramp = {
        calm: Array.from({ length: STEPS }, (_, k) => `rgb(${mix(mix(a, [255, 255, 255], 0.1), loud, k / (STEPS - 1)).join(',')})`),
        busy: Array.from({ length: STEPS }, (_, k) => `rgb(${mix(mix(a, b, 0.6), loud, k / (STEPS - 1)).join(',')})`),
        glow: a.join(', '),
      };
      return this.ramp;
    }

    targets(t) {
      const out = new Float32Array(BANDS);
      const fresh = performance.now() - this.levelAt < 400;               // the phone's recognizer is reporting a level
      if (this.state === 'listening' && fresh) {
        for (let b = 0; b < BANDS; b++) out[b] = Math.min(1, this.level * (0.55 + 0.7 * Math.abs(Math.sin(t * 7 + b * 0.9) * Math.sin(t * 3.1 + b * 0.31))));
        this.target = this.level;
      } else if (this.state === 'listening') {
        for (let b = 0; b < BANDS; b++) out[b] = 0.18 + 0.45 * Math.abs(Math.sin(t * 4.2 + b * 0.6) * Math.sin(t * 1.7 + b * 0.21));
        this.target = 0.35;
      } else if (this.state === 'speaking') {
        for (let b = 0; b < BANDS; b++) out[b] = 0.2 + 0.55 * Math.abs(Math.sin(t * 5.2 + b * 0.5) * Math.sin(t * 2.1 + b * 0.19));
        this.target = 0.5 + 0.25 * Math.sin(t * 7);
      } else if (this.state === 'thinking') {
        for (let b = 0; b < BANDS; b++) out[b] = 0.1 + 0.16 * (0.5 + 0.5 * Math.sin(t * 6 - b * 0.45));
        this.target = 0.22;
      } else {
        this.target = 0;
      }
      return out;
    }

    frame(now) {
      requestAnimationFrame((t) => this.frame(t));
      if (document.hidden || !this.size || this.canvas.offsetParent === null) return;
      const dt = Math.min(0.1, (now - this.last) / 1000);
      this.last = now;
      const t = now / 1000;
      const goal = this.targets(t);
      for (let b = 0; b < BANDS; b++) this.bands[b] += (goal[b] - this.bands[b]) * (goal[b] > this.bands[b] ? 0.6 : 0.12);
      this.smooth += ((this.target || 0) - this.smooth) * 0.25;
      this.yaw += (reduceMotion ? 0.04 : this.state === 'thinking' ? 1.6 : this.state === 'listening' ? 0.5 : this.state === 'idle' || this.state === 'offline' ? 0.12 : 0.28) * dt;
      this.draw(t);
    }

    draw(t) {
      const { ctx, size: S, dpr, state } = this;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, S, S);
      const ramp = this.ramp || this.colours();
      const colours = state === 'thinking' ? ramp.busy : ramp.calm;
      const awake = state === 'offline' ? 0.3 : state === 'idle' ? 0.55 : state === 'ready' ? 0.75 : 1;
      const breathe = 0.5 + 0.5 * Math.sin(t * (state === 'idle' ? 1.1 : state === 'thinking' ? 4.5 : 1.8));
      const R = S * 0.33 * (1 + this.smooth * 0.14 + (state === 'listening' ? 0.05 : 0) + 0.025 * breathe);   // the loudest the dots get stays inside the canvas
      const c = S / 2;
      const glow = ctx.createRadialGradient(c, c, 0, c, c, S * 0.5);
      glow.addColorStop(0, `rgba(${ramp.glow}, ${0.08 + 0.2 * this.smooth + 0.05 * awake})`);
      glow.addColorStop(1, `rgba(${ramp.glow}, 0)`);
      ctx.fillStyle = glow;
      ctx.fillRect(0, 0, S, S);

      const tilt = 0.42 + 0.06 * Math.sin(t * 0.4);
      const cy = Math.cos(this.yaw), sy = Math.sin(this.yaw), ct = Math.cos(tilt), st = Math.sin(tilt);
      const dotR = S * 0.0075;
      const paths = [[], []];
      for (let p = 0; p < 2; p++) for (let k = 0; k < STEPS; k++) paths[p].push(new Path2D());
      for (let i = 0; i < DOTS; i++) {
        const x1 = X[i] * cy + Z[i] * sy, z1 = -X[i] * sy + Z[i] * cy;
        const y2 = Y[i] * ct - z1 * st, z2 = Y[i] * st + z1 * ct;
        let amp = this.bands[BAND[i]] * (0.65 + 0.35 * Math.sin(PHASE[i] + t * 2.4));
        if (state === 'thinking') amp += 0.3 * (0.5 + 0.5 * Math.sin(t * 5.5 - Y[i] * 4.5 + PHASE[i] * 0.2));
        else if (state === 'idle' || state === 'ready' || state === 'offline') amp += 0.06 * (0.5 + 0.5 * Math.sin(t * 0.9 + Y[i] * 3 + PHASE[i]));
        amp = Math.min(1, amp);
        const out = 1 + amp * 0.36, persp = 1 / (1 - z2 * 0.3);
        const px = c + x1 * R * out * persp, py = c + y2 * R * out * persp;
        const depth = (z2 + 1) / 2;
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
    }
  }

  window.PhoneOrb = PhoneOrb;
})();
