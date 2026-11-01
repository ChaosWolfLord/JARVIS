// The start-up sequence: a ring assembles, system checks read out one by one (from the real state of JARVIS, not a fake script),
// the name appears, and JARVIS says it is online. It plays once each time the JARVIS server starts (not on every page reload),
// can be skipped with a touch or key, and can be switched off in the status menu.

const TAU = Math.PI * 2;
const LINE_MS = 380;
const el = (tag, cls, text) => Object.assign(document.createElement(tag), { className: cls || '', textContent: text ?? '' });

/** The checks to show, from /api/status: [label, value, state]. */
export function checks(info, voiceSupported = true) {
  const wake = info.wake || {};
  const ready = (info.chain || []).length;
  const rows = [
    ['CORE', 'ONLINE', 'ok'],
    ['LANGUAGE MODELS', info.key_set ? `${ready} READY` : 'NO KEY', info.key_set ? 'ok' : 'warn'],
    ['VOICE', wake.running ? 'WAKE WORD ARMED' : voiceSupported ? 'LISTENING' : 'UNAVAILABLE', wake.running || voiceSupported ? 'ok' : 'warn'],
    ['SMART LIGHTS', info.lights ? `${info.lights} FOUND` : 'NONE FOUND', info.lights ? 'ok' : 'dim'],
    ['SPEAKERS', info.speakers ? `${info.speakers} FOUND` : 'NONE FOUND', info.speakers ? 'ok' : 'dim'],
    ['SYSTEM HEALTH', info.alerts ? `${info.alerts} ALERT${info.alerts > 1 ? 'S' : ''}` : 'NOMINAL', info.alerts ? 'warn' : 'ok'],
  ];
  return rows;
}

export class Boot {
  constructor({ overlay, sounds, speak, getGreeting }) {
    this.overlay = overlay;
    this.canvas = overlay.querySelector('#boot-canvas');
    this.list = overlay.querySelector('#boot-lines');
    this.title = overlay.querySelector('#boot-title');
    this.sub = overlay.querySelector('#boot-sub');
    this.sounds = sounds;
    this.speak = speak;
    this.getGreeting = getGreeting;
    this.running = false;
  }

  /** Plays the sequence; resolves when it has finished (or was skipped). */
  run(info, voiceSupported) {
    if (this.running) return Promise.resolve();
    this.running = true;
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const rows = checks(info, voiceSupported);
    this.list.replaceChildren();
    this.title.classList.remove('show');
    this.sub.classList.remove('show');
    this.overlay.classList.remove('leaving');
    this.overlay.hidden = false;
    this.sounds.play('boot');
    const start = performance.now();
    const total = reduced ? 1600 : LINE_MS * rows.length + 2600;
    let frame = 0, finished = false;

    return new Promise((resolve) => {
      const finish = (skipped) => {
        if (finished) return;
        finished = true;
        cancelAnimationFrame(frame);
        window.removeEventListener('keydown', onKey, true);
        this.overlay.removeEventListener('pointerdown', onSkip);
        this.overlay.classList.add('leaving');
        setTimeout(() => { this.overlay.hidden = true; this.running = false; }, 700);
        if (!skipped) this.getGreeting().then((text) => this.speak(text)).catch(() => {});
        resolve();
      };
      const onSkip = () => finish(true);
      const onKey = (e) => { e.stopPropagation(); e.preventDefault(); finish(true); };
      this.overlay.addEventListener('pointerdown', onSkip);
      window.addEventListener('keydown', onKey, true);

      rows.forEach(([label, value, state], i) => setTimeout(() => {
        if (finished) return;
        const row = el('div', `boot-row ${state}`);
        row.append(el('span', 'boot-label', label), el('i', 'boot-dots'), el('span', 'boot-value', value));
        this.list.append(row);
      }, reduced ? 0 : 500 + i * LINE_MS));
      setTimeout(() => { if (!finished) { this.title.classList.add('show'); this.sub.classList.add('show'); } }, reduced ? 200 : LINE_MS * rows.length + 900);
      setTimeout(() => finish(false), total);

      const draw = (now) => {
        if (finished) return;
        this.draw((now - start) / total);
        frame = requestAnimationFrame(draw);
      };
      frame = requestAnimationFrame(draw);
    });
  }

  /** The ring: arcs sweep in and spin up while tick marks assemble, then it settles. p runs 0 to 1. */
  draw(p) {
    const c = this.canvas, dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (c.width !== Math.round(w * dpr)) { c.width = Math.round(w * dpr); c.height = Math.round(h * dpr); }
    const g = c.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const cx = w / 2, cy = h * 0.42, R = Math.min(w, h) * 0.2;
    const ease = (x) => 1 - (1 - Math.min(1, Math.max(0, x))) ** 3;
    const t = p * 6;
    g.lineCap = 'round';
    g.shadowColor = 'rgba(0, 229, 255, 0.9)';
    g.shadowBlur = 14;
    // outer ring that draws itself
    g.strokeStyle = 'rgba(0, 229, 255, 0.85)';
    g.lineWidth = 2.5;
    g.beginPath();
    g.arc(cx, cy, R, -Math.PI / 2, -Math.PI / 2 + TAU * ease(p * 2.2));
    g.stroke();
    // three spinning arc segments
    [[0.8, 1.0, 1.4], [0.64, -1.6, 1.0], [0.48, 2.2, 0.8]].forEach(([k, speed, span], i) => {
      g.strokeStyle = `rgba(0, 190, 255, ${0.35 + 0.15 * i})`;
      g.lineWidth = 3 - i * 0.6;
      const a = t * speed * ease(p * 1.6) + i;
      g.beginPath();
      g.arc(cx, cy, R * k, a, a + span * ease(p * 3));
      g.stroke();
    });
    // tick marks that appear around the ring
    g.shadowBlur = 6;
    g.strokeStyle = 'rgba(160, 240, 255, 0.7)';
    g.lineWidth = 1.5;
    const ticks = 60, shown = Math.floor(ticks * ease(p * 2.6));
    for (let i = 0; i < shown; i++) {
      const a = (i / ticks) * TAU - Math.PI / 2, long = i % 5 === 0;
      g.beginPath();
      g.moveTo(cx + Math.cos(a) * (R * 1.08), cy + Math.sin(a) * (R * 1.08));
      g.lineTo(cx + Math.cos(a) * (R * (long ? 1.2 : 1.14)), cy + Math.sin(a) * (R * (long ? 1.2 : 1.14)));
      g.stroke();
    }
    // the core brightens at the end
    const core = ease((p - 0.55) * 2.2);
    const grad = g.createRadialGradient(cx, cy, 0, cx, cy, R * 0.4);
    grad.addColorStop(0, `rgba(210, 250, 255, ${0.9 * core})`);
    grad.addColorStop(1, 'rgba(0, 229, 255, 0)');
    g.shadowBlur = 0;
    g.fillStyle = grad;
    g.beginPath();
    g.arc(cx, cy, R * 0.4, 0, TAU);
    g.fill();
  }
}
