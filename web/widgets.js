// Widgets: small cards on the board (usage, weather, timers...). This keeps track of which ones are on and where
// they sit, lets each be dragged by its title bar and resized by the corner grip (resizing scales the whole card, so
// text and charts stay sharp and in proportion), remembers all that between visits, and runs the widgets menu where
// each one can be added or removed.
//
// Each card remembers its distance from the left or the right edge of the board, whichever is nearer, so it stays
// in view when the window gets wider or narrower.

import { fitMenu } from './menufit.js';

const LAYOUT_KEY = 'jarvis.widget.layout2';
const MIN_SCALE = 0.5;
const MAX_SCALE = 3;
const GAP = 18;

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

export class Widgets {
  constructor({ board, button, menu, list, reset }) {
    this.board = board;
    this.button = button;
    this.menu = menu;
    this.list = list;
    this.items = new Map();
    this.shown = new Set();
    this.layout = {};          // id -> { a: 'l' | 'r', x, y, s }: x is the gap from the board's left (or right) edge, y from the top, s the scale
    this.gesture = null;
    this.top = 10;
    try { this.layout = JSON.parse(localStorage.getItem(LAYOUT_KEY)) || {}; } catch { this.layout = {}; }

    button.addEventListener('click', () => this.toggleMenu());
    reset?.addEventListener('click', () => this.resetLayout());
    // Tapping anywhere else closes the menu, like a normal pop-up.
    document.addEventListener('click', (e) => {
      if (!this.menu.hidden && !this.menu.contains(e.target) && !this.button.contains(e.target)) this.toggleMenu(false);
    });
    // Every card's × removes it from the board (it can be added back from the menu).
    document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => this.set(b.dataset.close, false)));
    board.onLayout = () => this.reposition();
  }

  /** item: { id, title, blurb, icon, el, onShow?, onHide? } */
  register(item) {
    this.items.set(item.id, item);
    item.el.hidden = true;
    item.el.dataset.widget = item.id;
    const grip = Object.assign(document.createElement('span'), { className: 'w-grip', title: 'Drag to resize' });
    item.el.append(grip);
    this.bindMouse(item, item.el.querySelector('header'), 'move');
    this.bindMouse(item, grip, 'size');
    item.el.addEventListener('pointerdown', () => this.raise(item.el), true);
    this.renderMenu();
  }

  /** Puts back the widgets that were on last time. Call after every widget is registered. */
  restore() {
    let saved = null;
    try {
      saved = JSON.parse(localStorage.getItem('jarvis.widgets'));
      if (!Array.isArray(saved)) saved = localStorage.getItem('jarvis.usage') === '1' ? ['usage'] : [];
    } catch { saved = []; }
    for (const id of this.items.keys()) this.set(id, saved.includes(id), false);
  }

  visible(id) { return this.shown.has(id); }

  toggle(id) { return this.set(id, !this.visible(id)); }

  set(id, show, remember = true) {
    const item = this.items.get(id);
    if (!item) return false;
    const was = this.shown.has(id);
    item.el.hidden = !show;
    if (show) this.shown.add(id); else this.shown.delete(id);
    if (show && !was) {
      if (!this.layout[id]) this.place(id);
      this.apply(id);
      this.raise(item.el);
      item.onShow?.();
    }
    if (!show && was) item.onHide?.();
    if (remember && show !== was) this.onToggle?.(id, show);        // for the interface sounds (not when the page restores what was on)
    this.renderMenu();
    if (remember) {
      try { localStorage.setItem('jarvis.widgets', JSON.stringify([...this.shown])); } catch { /* not remembered */ }
    }
    return true;
  }

  // ---- position and size ---------------------------------------------------
  raise(el) { el.style.zIndex = String(++this.top); }

  saveLayout() {
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(this.layout)); } catch { /* not remembered */ }
  }

  /** The card's box in page pixels from the board's left edge: { left, top, width, height }. */
  box(id) {
    const el = this.items.get(id).el;
    const l = this.layout[id] || { a: 'l', x: 0, y: 0, s: 1 };
    const width = el.offsetWidth * l.s;
    const left = l.a === 'r' ? this.board.w - l.x - width : l.x;
    return { left: clamp(left, 60 - width, this.board.w - 60), top: clamp(l.y, 0, 1080 - 40), width, height: el.offsetHeight * l.s };
  }

  /** Remembers a card's position (page px from the board's left edge) against the nearer side edge. */
  remember(id, left, top, s) {
    const width = this.items.get(id).el.offsetWidth * s;
    const right = left + width / 2 > this.board.w / 2;
    this.layout[id] = { a: right ? 'r' : 'l', x: Math.round(right ? this.board.w - left - width : left), y: Math.round(top), s: Math.round(s * 100) / 100 };
  }

  /** Shows the card where it is saved, kept inside the board (a corner of it always stays within reach). */
  apply(id) {
    const el = this.items.get(id)?.el;
    const l = this.layout[id];
    if (!el || !l) return;
    const box = this.box(id);
    el.style.left = `${box.left}px`;
    el.style.top = `${box.top}px`;
    el.style.transform = l.s === 1 ? '' : `scale(${l.s})`;
  }

  /** The board's width changed: cards keep their distance from the nearer side edge. */
  reposition() {
    for (const id of this.shown) this.apply(id);
  }

  /** The first free spot, scanning left to right and top to bottom, clear of other cards and of the clock. */
  place(id) {
    const el = this.items.get(id).el;
    const width = el.offsetWidth, height = el.offsetHeight;
    const taken = [...this.shown].filter((o) => o !== id && this.layout[o]).map((o) => this.box(o));
    taken.push({ left: this.board.w - 440, top: 0, width: 420, height: 120 }); // the clock
    const free = (x, y) => taken.every((b) => x + width + GAP <= b.left || b.left + b.width + GAP <= x || y + height + GAP <= b.top || b.top + b.height + GAP <= y);
    let spot = { x: 36, y: 24 };
    search: for (let y = 24; y < 1080 - 60; y += 16) {
      for (let x = 36; x + width < this.board.w - 20; x += 16) {
        if (free(x, y)) { spot = { x, y }; break search; }
      }
    }
    this.remember(id, spot.x, spot.y, 1);
    this.saveLayout();
  }

  /** Puts every card back at its natural size in the first free spots. */
  resetLayout() {
    this.layout = {};
    for (const id of this.shown) { this.place(id); this.apply(id); }
    this.saveLayout();
  }

  // ---- dragging and resizing ----------------------------------------------
  // A gesture works in page pixels from the board's left edge, so the same code serves the mouse, touch and the
  // IR pen (which arrives in board coordinates and adds board.pad).
  start(id, kind, px, py) {
    const l = this.layout[id];
    if (!l) return;
    const box = this.box(id);
    this.gesture = { id, kind, px0: px, py0: py, left0: box.left, top0: box.top, s0: l.s, width0: box.width };
    this.raise(this.items.get(id).el);
  }

  move(px, py) {
    const g = this.gesture;
    if (!g) return;
    if (g.kind === 'move') this.remember(g.id, g.left0 + (px - g.px0), g.top0 + (py - g.py0), g.s0);
    else this.remember(g.id, g.left0, g.top0, clamp(g.s0 * ((g.width0 + (px - g.px0)) / g.width0), MIN_SCALE, MAX_SCALE));
    this.apply(g.id);
  }

  end() {
    if (!this.gesture) return;
    this.gesture = null;
    this.saveLayout();
  }

  bindMouse(item, handle, kind) {
    handle.addEventListener('pointerdown', (e) => {
      if (e.button !== 0 || e.target.closest('button, input, select, textarea')) return;
      e.preventDefault();
      handle.setPointerCapture(e.pointerId);
      const at = (ev) => this.board.fromScreen(ev.clientX, ev.clientY, true);
      const p = at(e);
      this.start(item.id, kind, p.x, p.y);
      const move = (ev) => { const q = at(ev); this.move(q.x, q.y); };
      const up = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', up);
        this.end();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
      handle.addEventListener('pointercancel', up);
    });
  }

  // ---- the menu ------------------------------------------------------------
  toggleMenu(open = this.menu.hidden) {
    this.menu.hidden = !open;
    this.button.classList.toggle('active', open);
    if (open) fitMenu(this.menu);
  }

  renderMenu() {
    this.list.replaceChildren(...[...this.items.values()].map((item) => {
      const on = this.shown.has(item.id);
      const li = document.createElement('li');
      const icon = Object.assign(document.createElement('span'), { className: 'wm-icon', textContent: item.icon });
      const text = document.createElement('div');
      text.append(Object.assign(document.createElement('b'), { textContent: item.title }),
        Object.assign(document.createElement('small'), { textContent: item.blurb }));
      const btn = Object.assign(document.createElement('button'), {
        type: 'button', className: on ? 'wm-toggle on' : 'wm-toggle', textContent: on ? 'Remove' : 'Add',
      });
      btn.setAttribute('aria-pressed', String(on));
      btn.addEventListener('click', () => this.set(item.id, !on));
      li.append(icon, text, btn);
      return li;
    }));
  }
}
