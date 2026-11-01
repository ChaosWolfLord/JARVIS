// Sound design: short synthesised sounds for the interface (no sound files). Quiet by design: a soft blip when a card opens or
// closes, a ping when JARVIS hears its name, a two-tone warning for alerts, a sweep when a hologram appears, and the start-up
// flourish. Switch them off in the status menu (Display).

const KEY = 'jarvis.sounds';
const MASTER = 0.5;

export class Sounds {
  constructor() {
    this.ctx = null;
    try { this.enabled = localStorage.getItem(KEY) !== '0'; } catch { this.enabled = true; }
  }

  setEnabled(on) {
    this.enabled = Boolean(on);
    try { localStorage.setItem(KEY, on ? '1' : '0'); } catch { /* not remembered */ }
  }

  context() {
    if (!this.ctx) {
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        this.ctx = new Ctx();
        this.out = this.ctx.createGain();
        this.out.gain.value = MASTER;
        this.out.connect(this.ctx.destination);
      } catch { return null; }
    }
    if (this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
    return this.ctx;
  }

  /** One note: frequency (gliding to `to`), shape, loudness and timing, with a quick fade in and a smooth fade out. */
  tone({ freq, to = freq, at = 0, dur = 0.12, type = 'sine', gain = 0.12, lowpass = 0 }) {
    const c = this.ctx, t = c.currentTime + at;
    const osc = c.createOscillator(), amp = c.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t);
    if (to !== freq) osc.frequency.exponentialRampToValueAtTime(to, t + dur);
    amp.gain.setValueAtTime(0.0001, t);
    amp.gain.exponentialRampToValueAtTime(gain, t + 0.012);
    amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    let node = osc;
    if (lowpass) {
      const f = c.createBiquadFilter();
      f.type = 'lowpass';
      f.frequency.value = lowpass;
      osc.connect(f);
      node = f;
    }
    node.connect(amp).connect(this.out);
    osc.start(t);
    osc.stop(t + dur + 0.05);
  }

  /** A burst of filtered noise that sweeps from one frequency to another (shimmer, whoosh). */
  sweep({ from, to, at = 0, dur = 0.5, gain = 0.06, q = 4 }) {
    const c = this.ctx, t = c.currentTime + at, len = Math.ceil(c.sampleRate * dur);
    const buffer = c.createBuffer(1, len, c.sampleRate), data = buffer.getChannelData(0);
    for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
    const src = c.createBufferSource(), band = c.createBiquadFilter(), amp = c.createGain();
    src.buffer = buffer;
    band.type = 'bandpass';
    band.Q.value = q;
    band.frequency.setValueAtTime(from, t);
    band.frequency.exponentialRampToValueAtTime(to, t + dur);
    amp.gain.setValueAtTime(0.0001, t);
    amp.gain.exponentialRampToValueAtTime(gain, t + dur * 0.4);
    amp.gain.exponentialRampToValueAtTime(0.0001, t + dur);
    src.connect(band).connect(amp).connect(this.out);
    src.start(t);
  }

  play(name) {
    if (!this.enabled) return;
    const c = this.context();
    if (!c) return;
    try { RECIPES[name]?.(this); } catch { /* a sound must never break the page */ }
  }
}

const RECIPES = {
  open: (s) => { s.tone({ freq: 520, to: 780, dur: 0.09, type: 'triangle', gain: 0.08 }); s.tone({ freq: 780, to: 1040, at: 0.07, dur: 0.1, type: 'triangle', gain: 0.07 }); },
  close: (s) => { s.tone({ freq: 780, to: 520, dur: 0.08, type: 'triangle', gain: 0.07 }); s.tone({ freq: 520, to: 390, at: 0.07, dur: 0.1, type: 'triangle', gain: 0.06 }); },
  listen: (s) => { s.tone({ freq: 880, dur: 0.09, type: 'sine', gain: 0.1 }); s.tone({ freq: 1320, at: 0.07, dur: 0.14, type: 'sine', gain: 0.08 }); },
  ok: (s) => s.tone({ freq: 660, to: 740, dur: 0.12, type: 'sine', gain: 0.09 }),
  alert: (s) => {
    for (const at of [0, 0.5]) {
      s.tone({ freq: 440, dur: 0.17, type: 'square', gain: 0.05, lowpass: 900, at });
      s.tone({ freq: 330, dur: 0.22, type: 'square', gain: 0.05, lowpass: 900, at: at + 0.2 });
    }
  },
  holo: (s) => {
    s.sweep({ from: 400, to: 3200, dur: 0.55, gain: 0.07 });
    s.tone({ freq: 1200, to: 1800, at: 0.35, dur: 0.14, type: 'sine', gain: 0.07 });
  },
  boot: (s) => {
    s.tone({ freq: 70, to: 240, dur: 1.9, type: 'sawtooth', gain: 0.09, lowpass: 420 });
    s.sweep({ from: 300, to: 4200, at: 0.2, dur: 1.7, gain: 0.05, q: 2 });
    [[220, 0.9], [329.6, 1.15], [440, 1.4], [554.4, 1.7]].forEach(([freq, at]) => s.tone({ freq, at, dur: 0.5, type: 'triangle', gain: 0.07 }));
    s.tone({ freq: 659.3, at: 2.0, dur: 1.2, type: 'sine', gain: 0.08 });
    s.tone({ freq: 329.6, at: 2.0, dur: 1.4, type: 'sine', gain: 0.05 });
  },
};
