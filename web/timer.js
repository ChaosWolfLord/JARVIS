// Countdown timers. They keep running when the widget is hidden or the page is reloaded (each one stores the
// moment it ends), ring with three beeps when they finish, and tell the app so JARVIS can say it out loud.

const MAX_TIMERS = 6;
const MAX_SECONDS = 24 * 3600;
const KEY = 'jarvis.timers';

export function formatTime(ms) {
  const s = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

export class Timers {
  constructor({ el, onDone }) {
    this.el = el;
    this.listEl = el.querySelector('#timer-list');
    this.onDone = onDone;
    this.timers = [];
    this.rows = new Map();
    this.load();

    el.querySelectorAll('[data-min]').forEach((b) => b.addEventListener('click', () => this.add(Number(b.dataset.min) * 60)));
    el.querySelector('#timer-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const min = Number(el.querySelector('#timer-min').value);
      if (min > 0) this.add(min * 60, el.querySelector('#timer-label').value.trim());
      el.querySelector('#timer-min').value = '';
      el.querySelector('#timer-label').value = '';
    });
    this.render();
    setInterval(() => this.tick(), 250);
  }

  load() {
    try {
      const saved = JSON.parse(localStorage.getItem(KEY));
      if (Array.isArray(saved)) this.timers = saved.slice(0, MAX_TIMERS);
    } catch { /* start empty */ }
    const now = Date.now();
    for (const t of this.timers) {
      if (!t.paused && !t.done && t.endsAt <= now) { t.done = true; t.rang = 99; } // finished while the page was closed: no ringing
    }
  }

  save() {
    try { localStorage.setItem(KEY, JSON.stringify(this.timers)); } catch { /* not remembered */ }
  }

  /** Starts a countdown. Returns the timer, or null if there are already too many. */
  add(seconds, label = '') {
    seconds = Math.max(1, Math.min(MAX_SECONDS, Math.round(seconds)));
    if (this.timers.length >= MAX_TIMERS) return null;
    const t = { id: `${Date.now()}${Math.floor(Math.random() * 1000)}`, label: label.slice(0, 30), total: seconds * 1000,
      endsAt: Date.now() + seconds * 1000, paused: false, left: 0, done: false, rang: 0 };
    this.timers.push(t);
    this.save();
    this.render();
    return t;
  }

  /** Removes the timers whose label contains `label` (or all of them when it is empty). Returns how many went. */
  cancel(label = '') {
    const needle = label.trim().toLowerCase();
    const keep = this.timers.filter((t) => needle && !t.label.toLowerCase().includes(needle));
    const removed = this.timers.length - keep.length;
    this.timers = keep;
    this.save();
    this.render();
    return removed;
  }

  remove(id) {
    this.timers = this.timers.filter((t) => t.id !== id);
    this.save();
    this.render();
  }

  togglePause(t) {
    if (t.done) return;
    if (t.paused) { t.endsAt = Date.now() + t.left; t.paused = false; } else { t.left = Math.max(0, t.endsAt - Date.now()); t.paused = true; }
    this.save();
    this.update();
  }

  remaining(t) {
    if (t.done) return 0;
    return t.paused ? t.left : Math.max(0, t.endsAt - Date.now());
  }

  tick() {
    const now = Date.now();
    let changed = false;
    for (const t of this.timers) {
      if (!t.paused && !t.done && t.endsAt <= now) {
        t.done = true;
        t.rang = 0;
        changed = true;
        this.onDone?.(t);
      }
      if (t.done && t.rang < 3 && now - (t.lastBeep || 0) > 2500) { // three rounds of beeps, then quiet until dismissed
        t.lastBeep = now;
        t.rang += 1;
        this.beep();
      }
    }
    if (changed) this.save();
    this.update();
  }

  beep() {
    try {
      this.audio ??= new AudioContext();
      const ctx = this.audio;
      ctx.resume?.();
      [0, 0.28, 0.56].forEach((at, i) => {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = i === 2 ? 1175 : 880;
        gain.gain.setValueAtTime(0.0001, ctx.currentTime + at);
        gain.gain.exponentialRampToValueAtTime(0.18, ctx.currentTime + at + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + at + 0.22);
        osc.connect(gain).connect(ctx.destination);
        osc.start(ctx.currentTime + at);
        osc.stop(ctx.currentTime + at + 0.25);
      });
    } catch { /* no audio: the card still flashes */ }
  }

  /** Rebuilds the rows when timers come or go. Between those, update() only changes text, so a tap is never lost. */
  render() {
    this.rows.clear();
    if (!this.timers.length) {
      this.listEl.replaceChildren(Object.assign(document.createElement('p'), { className: 'timer-empty', textContent: 'No timers running.' }));
      return;
    }
    this.listEl.replaceChildren(...this.timers.map((t) => {
      const row = document.createElement('div');
      row.className = 'timer-row';
      const name = Object.assign(document.createElement('span'), { className: 'timer-name' });
      const time = Object.assign(document.createElement('span'), { className: 'timer-time' });
      const bar = Object.assign(document.createElement('i'), { className: 'timer-bar' });
      const pause = Object.assign(document.createElement('button'), { type: 'button', className: 'timer-pause' });
      pause.addEventListener('click', () => this.togglePause(t));
      const del = Object.assign(document.createElement('button'), { type: 'button', className: 'timer-del', textContent: '×', title: 'Remove this timer' });
      del.addEventListener('click', () => this.remove(t.id));
      row.append(name, time, pause, del, bar);
      this.rows.set(t.id, { row, name, time, bar, pause });
      return row;
    }));
    this.update();
  }

  update() {
    for (const t of this.timers) {
      const r = this.rows.get(t.id);
      if (!r) { this.render(); return; }
      const left = this.remaining(t);
      r.name.textContent = t.label || `${Math.round(t.total / 60000)} min timer`;
      r.time.textContent = t.done ? 'Done' : formatTime(left);
      r.bar.style.width = `${t.done ? 100 : Math.max(0, 100 - (left / t.total) * 100)}%`;
      r.pause.textContent = t.done ? '' : t.paused ? '▶' : '❚❚';
      r.pause.hidden = t.done;
      r.pause.title = t.paused ? 'Resume' : 'Pause';
      r.row.classList.toggle('done', t.done);
      r.row.classList.toggle('paused', t.paused);
    }
  }
}
