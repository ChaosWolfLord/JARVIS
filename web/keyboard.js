// On-screen keyboard for typing with the pen (or a finger). It types into whichever text field was last
// focused: the chat box, a sticky note, the memory box. Keys are plain buttons, so a pen tap (which becomes a
// click) and a mouse click both work, and they never take focus away from the field being typed into.

const L = (k, label, w = 1) => ({ k, label, w });

const PAGES = {
  letters: [
    ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0', L('backspace', '⌫', 1.7)],
    ['q', 'w', 'e', 'r', 't', 'y', 'u', 'i', 'o', 'p'],
    ['a', 's', 'd', 'f', 'g', 'h', 'j', 'k', 'l', L('enter', '↵', 1.9)],
    [L('shift', '⇧', 1.7), 'z', 'x', 'c', 'v', 'b', 'n', 'm', ',', '.', '?'],
    [L('symbols', '?123', 1.5), '/', '-', "'", L(' ', 'space', 4.2), L('left', '←'), L('right', '→'), L('hide', '▾', 1.4)],
  ],
  symbols: [
    ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')', L('backspace', '⌫', 1.7)],
    ['~', '`', '|', '\\', '{', '}', '[', ']', '<', '>'],
    ['+', '=', '_', '-', ':', ';', '"', "'", '/', L('enter', '↵', 1.9)],
    [L('shift', '⇧', 1.7), '€', '£', '¥', '©', '°', '…', '–', ',', '.', '?'],
    [L('letters', 'abc', 1.5), '%', '&', '+', L(' ', 'space', 4.2), L('left', '←'), L('right', '→'), L('hide', '▾', 1.4)],
  ],
};

const TEXT_FIELD = 'input:not([type]), input[type="text"], input[type="search"], textarea, [contenteditable]';
const isField = (el) => el instanceof Element && el.matches(TEXT_FIELD) && !el.closest('#keyboard');

export class Keyboard {
  constructor({ el, board, dock, toast }) {
    this.el = el;
    this.board = board;
    this.dock = dock;
    this.toast = toast;
    this.page = 'letters';
    this.shift = 'off'; // off | once | lock
    this.lastShiftTap = 0;
    this.target = null;
    this.audio = null;

    document.addEventListener('focusin', (e) => { if (isField(e.target)) this.target = e.target; });
    // Mouse and touch presses on a key must not pull focus out of the text field.
    el.addEventListener('pointerdown', (e) => e.preventDefault());
    el.addEventListener('click', (e) => {
      const key = e.target.closest('.kb-key');
      if (key) this.press(key.dataset.key, key);
    });
    this.render();
  }

  get isOpen() { return !this.el.hidden; }

  show() {
    if (this.isOpen) return;
    this.el.hidden = false;
    document.body.classList.add('kb-open');
    this.board.setDock(this.el);
  }

  hide() {
    if (!this.isOpen) return;
    this.el.hidden = true;
    document.body.classList.remove('kb-open');
    this.board.setDock(this.dock);
  }

  toggle() { this.isOpen ? this.hide() : this.show(); }

  // ---- drawing the keys ------------------------------------------------
  render() {
    this.el.replaceChildren();
    for (const row of PAGES[this.page]) {
      const div = Object.assign(document.createElement('div'), { className: 'kb-row' });
      for (const key of row) {
        const spec = typeof key === 'string' ? L(key, key) : key;
        const b = Object.assign(document.createElement('button'), { type: 'button', className: 'kb-key', tabIndex: -1 });
        b.dataset.key = spec.k;
        b.style.setProperty('--w', spec.w);
        b.textContent = this.shown(spec);
        if (spec.k === 'shift') b.classList.toggle('on', this.shift !== 'off');
        if (spec.k === 'shift' && this.shift === 'lock') b.classList.add('lock');
        if (spec.k === 'enter') b.classList.add('accent');
        div.append(b);
      }
      this.el.append(div);
    }
  }

  shown(spec) {
    return this.shift !== 'off' && /^[a-z]$/.test(spec.k) ? spec.label.toUpperCase() : spec.label;
  }

  // ---- key presses -----------------------------------------------------
  press(key, button) {
    this.flash(button);
    this.tick();
    switch (key) {
      case 'shift': return this.pressShift();
      case 'symbols': this.page = 'symbols'; return this.render();
      case 'letters': this.page = 'letters'; return this.render();
      case 'hide': return this.hide();
      case 'backspace': return this.backspace();
      case 'enter': return this.enter();
      case 'left': return this.move(-1);
      case 'right': return this.move(1);
      default: {
        const ch = this.shift !== 'off' && /^[a-z]$/.test(key) ? key.toUpperCase() : key;
        this.insert(ch);
        if (this.shift === 'once') { this.shift = 'off'; this.render(); }
      }
    }
  }

  pressShift() {
    const now = Date.now();
    if (this.shift === 'once' && now - this.lastShiftTap < 450) this.shift = 'lock'; // double tap: caps lock
    else this.shift = this.shift === 'off' ? 'once' : 'off';
    this.lastShiftTap = now;
    this.render();
  }

  field() {
    const active = document.activeElement;
    if (isField(active)) return active;
    if (this.target?.isConnected) {
      this.target.focus();
      return this.target;
    }
    this.toast('Tap a text box first, then type');
    return null;
  }

  insert(text) {
    const f = this.field();
    if (!f) return;
    if (f.isContentEditable) {
      document.execCommand('insertText', false, text);
    } else {
      f.setRangeText(text, f.selectionStart, f.selectionEnd, 'end');
      f.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  backspace() {
    const f = this.field();
    if (!f) return;
    if (f.isContentEditable) {
      document.execCommand('delete');
    } else {
      const { selectionStart: a, selectionEnd: b } = f;
      if (a === b && a > 0) f.setRangeText('', a - 1, a, 'end');
      else f.setRangeText('', a, b, 'end');
      f.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  enter() {
    const f = this.field();
    if (!f) return;
    if (f.isContentEditable) {
      document.execCommand('insertLineBreak');
      return;
    }
    // Let the field's own Enter handling run (the chat box sends); plain text areas get a new line instead.
    const ev = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    const notHandled = f.dispatchEvent(ev);
    if (notHandled && f.tagName === 'TEXTAREA') this.insert('\n');
  }

  move(dir) {
    const f = this.field();
    if (!f) return;
    if (f.isContentEditable) {
      getSelection().modify('move', dir < 0 ? 'backward' : 'forward', 'character');
    } else {
      const pos = Math.max(0, Math.min(f.value.length, (dir < 0 ? f.selectionStart : f.selectionEnd) + dir));
      f.setSelectionRange(pos, pos);
    }
  }

  // ---- feedback --------------------------------------------------------
  flash(button) {
    if (!button) return;
    button.classList.add('hit');
    setTimeout(() => button.classList.remove('hit'), 140);
  }

  tick() {
    try {
      this.audio ??= new AudioContext();
      const osc = this.audio.createOscillator();
      const gain = this.audio.createGain();
      osc.frequency.value = 1500;
      gain.gain.setValueAtTime(0.05, this.audio.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.0001, this.audio.currentTime + 0.03);
      osc.connect(gain).connect(this.audio.destination);
      osc.start();
      osc.stop(this.audio.currentTime + 0.035);
    } catch { /* no audio: the key flash is enough */ }
  }
}
