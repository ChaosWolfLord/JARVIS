// Ambient mode: when nobody has touched, spoken to or drawn on JARVIS for a while, the wall calms down. The dock
// fades away, the drawing dims, the side lights fade, widgets that aren't marked for it fade out, and the clock grows.
// The orb stays. Any touch, key, pen movement, spoken command or finished timer brings everything straight back.
// (The first touch only wakes it: it doesn't also press whatever was underneath.)

const KEY = 'jarvis.ambient';
const OPTIONS = [0, 1, 2, 5, 10]; // minutes of quiet before it starts; 0 = never
const DEFAULT_MINUTES = 2;

export class Ambient {
  /** busy(): true while something is going on that must not be hidden (a menu, the keyboard, calibration, typing...). */
  constructor({ select, busy = () => false }) {
    this.select = select;
    this.busy = busy;
    this.on = false;
    this.last = Date.now();
    this.swallow = false;
    this.enteredAt = 0;
    this.minutes = DEFAULT_MINUTES;
    try {
      const saved = Number(localStorage.getItem(KEY));
      if (OPTIONS.includes(saved) && localStorage.getItem(KEY) !== null) this.minutes = saved;
    } catch { /* default */ }

    if (select) {
      select.value = String(this.minutes);
      select.addEventListener('change', () => this.setMinutes(Number(select.value)));
    }
    // Capture phase, on the window: this runs before anything else sees the event, so the waking touch can be swallowed.
    for (const type of ['pointerdown', 'keydown']) window.addEventListener(type, (e) => this.input(e), true);
    for (const type of ['pointermove', 'wheel', 'touchstart']) window.addEventListener(type, (e) => this.input(e), { capture: true, passive: true });
    window.addEventListener('click', (e) => {
      if (this.swallow) { this.swallow = false; e.stopPropagation(); e.preventDefault(); }
    }, true);
    setInterval(() => this.tick(), 1000);
  }

  setMinutes(minutes) {
    this.minutes = minutes;
    try { localStorage.setItem(KEY, String(minutes)); } catch { /* not remembered */ }
    if (this.select) this.select.value = String(minutes);
    if (!minutes) this.exit();
    this.poke();
  }

  /** Something happened: restart the quiet timer, and wake up if asleep. */
  poke() {
    this.last = Date.now();
    if (this.on) this.exit();
  }

  input(e) {
    if (this.on) {
      if (Date.now() - this.enteredAt < 700) return;            // the movement of pressing "A" itself
      if (e.type === 'pointermove' && e.pointerType === 'mouse' && !e.movementX && !e.movementY) return;
      if (e.type === 'pointerdown' || e.type === 'keydown') {
        this.swallow = e.type === 'pointerdown';
        if (e.type === 'keydown') { e.stopPropagation(); e.preventDefault(); }
      }
      this.poke();
      return;
    }
    this.last = Date.now();
  }

  tick() {
    if (this.busy()) { this.poke(); return; }   // something is happening (an answer, speech, a menu): stay awake, or wake up
    if (!this.on && this.minutes && Date.now() - this.last >= this.minutes * 60_000) this.enter();
  }

  enter() {
    if (this.on) return;
    this.on = true;
    this.enteredAt = Date.now();
    document.body.classList.add('ambient');
  }

  exit() {
    if (!this.on) return;
    this.on = false;
    document.body.classList.remove('ambient');
  }

  toggle() { if (this.on) this.poke(); else this.enter(); }
}
