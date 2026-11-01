// The privacy screen. "Jarvis, privacy" (or the H key, or Lock now in the status menu) covers the whole wall with a plain
// black screen, and the server stops answering questions or showing data until the unlock code is given: by voice
// ("Jarvis, privacy unlock five one four seven"), on the on-screen keypad (touch the screen), or on the keyboard.
// It is a curtain for casual eyes, not a lock against someone who can use the PC. See server/privacy.py.

const WORDS = { zero: 0, oh: 0, o: 0, one: 1, two: 2, to: 2, too: 2, three: 3, four: 4, for: 4, five: 5, six: 6, seven: 7, eight: 8, ate: 8, nine: 9 };

/** Digits from what was said: "five one four seven", "5147" and "51 47" all come out as 5147. */
export function spokenDigits(text) {
  return String(text).toLowerCase().split(/[\s,.\-]+/).map((w) => (/^\d+$/.test(w) ? w : (w in WORDS ? String(WORDS[w]) : ''))).join('');
}

const LOCK = /^\W*(?:privacy(?:\W+(?:on|mode|screen|please|now))?|lock(?:\W+(?:the\W+)?(?:screen|board|wall|jarvis))?)\W*$/;
const UNLOCK = /^\W*(?:privacy\W+)?unlock\b\W*(.*)$/;

export class Privacy {
  constructor({ overlay, onLocked, onUnlocked, toast }) {
    this.overlay = overlay;
    this.onLocked = onLocked;
    this.onUnlocked = onUnlocked;
    this.toast = toast;
    this.locked = false;
    this.hasCode = false;
    this.entry = '';
    this.wait = 0;
    this.padOpen = false;
    this.build();
    // If the page is reloaded while the screen is down, cover it at once instead of after the first answer from the server.
    try { if (localStorage.getItem('jarvis.locked') === '1') { this.locked = true; this.render(); } } catch { /* nothing remembered */ }
    window.addEventListener('keydown', (e) => this.key(e), true);
    this.refresh();
    setInterval(() => { if (this.locked) this.refresh(); }, 5000);
  }

  build() {
    const o = this.overlay;
    o.innerHTML = `
      <div class="pv-main" role="button" tabindex="0" aria-label="Privacy screen. Touch to enter the code">
        <svg class="pv-lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/></svg>
        <div class="pv-time"></div>
        <div class="pv-hint"></div>
      </div>
      <div class="pv-pad" hidden>
        <div class="pv-dots" aria-live="polite"></div>
        <div class="pv-msg"></div>
        <div class="pv-keys"></div>
      </div>`;
    this.timeEl = o.querySelector('.pv-time');
    this.hintEl = o.querySelector('.pv-hint');
    this.pad = o.querySelector('.pv-pad');
    this.dots = o.querySelector('.pv-dots');
    this.msg = o.querySelector('.pv-msg');
    const keys = o.querySelector('.pv-keys');
    for (const k of ['1', '2', '3', '4', '5', '6', '7', '8', '9', '⌫', '0', 'OK']) {
      const b = Object.assign(document.createElement('button'), { type: 'button', textContent: k, className: k === 'OK' ? 'ok' : '' });
      b.addEventListener('click', () => this.press(k));
      keys.append(b);
    }
    o.querySelector('.pv-main').addEventListener('click', () => this.openPad());
    setInterval(() => { this.timeEl.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }, 1000);
  }

  render() {
    this.overlay.hidden = !this.locked;
    this.pad.hidden = !(this.locked && this.padOpen && this.hasCode);
    this.dots.textContent = '●'.repeat(this.entry.length) || '';
    this.hintEl.textContent = !this.hasCode ? 'Touch the screen to unlock' : this.padOpen ? '' : 'Touch the screen, or say “Jarvis, privacy unlock” and the code';
    this.msg.textContent = this.wait > 0 ? `Too many wrong tries. Wait ${this.wait} seconds.` : this.msg.dataset.text || '';
    this.timeEl.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  set(state) {
    const was = this.locked;
    this.locked = Boolean(state.locked);
    this.hasCode = Boolean(state.has_code);
    this.wait = state.wait || 0;
    try { localStorage.setItem('jarvis.locked', this.locked ? '1' : '0'); } catch { /* not remembered */ }
    if (this.locked && !was) { this.entry = ''; this.padOpen = false; this.msg.dataset.text = ''; this.onLocked?.(); }
    if (!this.locked && was) { this.padOpen = false; this.entry = ''; this.onUnlocked?.(); }
    this.render();
  }

  async refresh() {
    try {
      this.set(await (await fetch('/api/privacy', { cache: 'no-store' })).json());
    } catch { /* server down: keep the screen as it is */ }
  }

  async post(path, body) {
    const res = await fetch(`/api/privacy/${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
    return res.json();
  }

  async lock() {
    if (this.locked) return;
    this.set(await this.post('lock'));
  }

  async unlock(code) {
    const r = await this.post('unlock', { code });
    this.set(r);
    if (!r.ok) {
      this.msg.dataset.text = r.wait ? '' : 'That code is wrong.';
      this.entry = '';
      this.render();
    }
    return r.ok;
  }

  openPad() {
    if (!this.hasCode) { this.unlock(''); return; }      // no code set: it is just a curtain
    this.padOpen = true;
    this.render();
  }

  press(k) {
    if (this.wait > 0) return;
    this.msg.dataset.text = '';
    if (k === '⌫') this.entry = this.entry.slice(0, -1);
    else if (k === 'OK') { if (this.entry) this.unlock(this.entry); return; }
    else if (this.entry.length < 8) this.entry += k;
    this.render();
  }

  key(e) {
    if (!this.locked) return;
    e.stopPropagation();                                  // nothing else on the page reacts while the screen is down
    if (/^\d$/.test(e.key)) { this.padOpen = this.hasCode ? true : this.padOpen; this.press(e.key); }
    else if (e.key === 'Backspace') this.press('⌫');
    else if (e.key === 'Enter') { if (this.hasCode) this.press('OK'); else this.unlock(''); }
    if (/^(\d|Backspace|Enter|Tab| )$/.test(e.key) || e.key.length > 1) e.preventDefault();
  }

  /** Voice commands about the screen. Returns true if the command was handled (and so mustn't go to the AI). */
  handleVoice(text) {
    const t = String(text).toLowerCase().trim().replace(/^jarvis\b\W*/, '');
    if (this.locked) {
      const m = t.match(UNLOCK);
      if (m) {
        const digits = spokenDigits(m[1]);
        if (digits) this.unlock(digits);
        else this.openPad();
      }
      return true;                                         // while the screen is down, nothing else is acted on or spoken
    }
    if (LOCK.test(t)) { this.lock(); return true; }
    return false;
  }
}
