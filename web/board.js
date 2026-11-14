// Whiteboard: vector strokes on a logical canvas, plus draggable sticky notes.
// Input arrives through penDown/penMove/penUp in logical coordinates, so the mouse today and the
// IR-camera pen later share one code path.
//
// The logical "home" area is 1920x1080 with (0,0) at its top-left. When the window is wider than 16:9 the board
// grows equally to the left and right to fill it (x then runs from -pad to 1920+pad), so nothing is wasted and
// everything already drawn stays centred. In the page, a logical x sits at x + pad pixels from the board's left edge.

import { inkPalette } from './theme.js';

export const W = 1920;
export const H = 1080;
// The ink colours follow the chosen look; app.js refreshes these values in place when the look is switched, then redraws.
export const COLORS = { ...inkPalette() };

const STORE_KEY = 'jarvis.board.v1';                      // the first board; the others add their id (see storeKey)
const CURRENT_KEY = 'jarvis.board.current';               // which board was showing, so a reload opens on it at once
const MAIN_ID = 'main';
const MAX_W = 5120; // an ultra-wide window won't stretch the board past this
const NOTE_W = 260;
const MAX_UNDO = 100;

// JARVIS sees and edits the board in the coordinates of the 1280x720 snapshot it is sent.
export const AI_W = 1280;
export const AI_H = 720;
const K = W / AI_W; // AI units -> logical units

const mid = (a, b) => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

// Text items live in the same list as strokes ({kind: 'text', x, y, size, text}) so they undo and erase alike.
function textBounds(s) {
  const lines = s.text.split('\n');
  return {
    x: s.x, y: s.y,
    w: Math.max(...lines.map((l) => l.length)) * s.size * 0.55,
    h: lines.length * s.size * 1.2,
  };
}

function setStyle(ctx, s, k, glow) {
  const color = COLORS[s.color] || s.color;
  ctx.lineCap = ctx.lineJoin = 'round';
  ctx.strokeStyle = ctx.fillStyle = color;
  ctx.lineWidth = Math.max(1.5, s.w * k);
  ctx.shadowColor = glow ? color : 'transparent';
  ctx.shadowBlur = glow ? 14 * k : 0;
}

function drawStroke(ctx, s, k = 1, glow = true) {
  setStyle(ctx, { ...s, w: s.w ?? 4 }, k, glow);
  if (s.kind === 'text') {
    ctx.font = `${s.size * k}px "Segoe UI", sans-serif`;
    ctx.textBaseline = 'top';
    s.text.split('\n').forEach((line, i) => ctx.fillText(line, s.x * k, (s.y + i * s.size * 1.2) * k));
    return;
  }
  const p = s.pts;
  if (s.raw && p.length > 1) { // exact shapes from JARVIS: straight segments, no smoothing
    ctx.beginPath();
    ctx.moveTo(p[0][0] * k, p[0][1] * k);
    for (let i = 1; i < p.length; i++) ctx.lineTo(p[i][0] * k, p[i][1] * k);
    ctx.stroke();
    return;
  }
  if (p.length === 1) {
    ctx.beginPath();
    ctx.arc(p[0][0] * k, p[0][1] * k, Math.max(0.75, (s.w * k) / 2), 0, Math.PI * 2);
    ctx.fill();
    return;
  }
  ctx.beginPath();
  ctx.moveTo(p[0][0] * k, p[0][1] * k);
  for (let i = 1; i < p.length - 1; i++) {
    const m = mid(p[i], p[i + 1]);
    ctx.quadraticCurveTo(p[i][0] * k, p[i][1] * k, m[0] * k, m[1] * k);
  }
  const last = p[p.length - 1];
  ctx.lineTo(last[0] * k, last[1] * k);
  ctx.stroke();
}

function distToSegment(px, py, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 ? Math.max(0, Math.min(1, ((px - a[0]) * dx + (py - a[1]) * dy) / len2)) : 0;
  return Math.hypot(px - (a[0] + t * dx), py - (a[1] + t * dy));
}

function wrapText(ctx, text, maxWidth) {
  const lines = [];
  for (const para of String(text).split('\n')) {
    let line = '';
    for (const word of para.split(/\s+/)) {
      const test = line ? `${line} ${word}` : word;
      if (line && ctx.measureText(test).width > maxWidth) { lines.push(line); line = word; } else line = test;
    }
    lines.push(line);
  }
  return lines;
}

export class Board {
  constructor({ stage, boardEl, canvas, notesEl, dockEl = null }) {
    this.stage = stage;
    this.dockEl = dockEl; // bottom toolbar: the board is fitted into the space above it
    this.el = boardEl;
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.notesEl = notesEl;
    this.strokes = [];
    this.notes = [];
    this.undoStack = [];
    this.redoStack = [];
    this.tool = 'pen';
    this.color = 'cyan';
    this.size = 4;
    this.current = null;
    this.erased = null;
    this.drawing = false;
    this.nextId = 1;
    this.scale = 1;
    this.res = 1;
    this.w = W;     // the board's full width in logical units: W, or more when the window is wider than 16:9
    this.pad = 0;   // (w - W) / 2: the extra room on each side of the home area
    this.onLayout = null;
    this.saveTimer = null;
    // Several named whiteboards: the PC keeps them all and says which one is showing. This page holds the one being shown.
    this.id = MAIN_ID;
    try { this.id = localStorage.getItem(CURRENT_KEY) || MAIN_ID; } catch { /* the first board */ }
    this.boards = [{ id: this.id, name: this.id === MAIN_ID ? 'Main' : 'Board' }];      // replaced by the PC's list as soon as it answers
    this.onBoards = null;                                    // (list, currentId) => void: the list or the board that is showing changed
    this.onSwitched = null;                                  // ({id, name, remote}) => void: another board is now showing
    this.dirty = false;                                      // something changed that the PC has not got yet
    this.switching = false;

    this.load();
    this.bindPointer();
    this.watcher = new ResizeObserver(() => this.layout());
    this.watcher.observe(stage);
    if (dockEl) this.watcher.observe(dockEl); // the dock wraps to two rows on narrow windows
    this.layout();
    this.renderNotes();
    this.sync();
    window.addEventListener('focus', () => this.sync()); // pick up changes made from another browser or PC
  }

  // ---- layout ----------------------------------------------------------
  layout() {
    const r = this.stage.getBoundingClientRect();
    const dock = this.dockEl ? this.dockEl.offsetHeight + 24 : 0; // dock height plus its margins
    const availH = r.height - dock;
    if (r.width < 10 || availH < 10) return;
    // A window wider than 16:9 gets a wider board instead of black bars; a narrower one keeps 16:9 and letterboxes.
    const w = Math.min(MAX_W, Math.max(W, Math.round((H * r.width) / availH)));
    const s = Math.min(r.width / w, availH / H);
    const pad = (w - W) / 2;
    const changed = w !== this.w;
    this.scale = s;
    this.w = w;
    this.pad = pad;
    this.el.style.width = `${w}px`;
    this.el.style.height = `${H}px`;
    this.canvas.style.width = `${w}px`;
    this.canvas.style.height = `${H}px`;
    this.el.style.transform = `translate(${(r.width - w * s) / 2}px, ${(availH - H * s) / 2}px) scale(${s})`;
    this.res = Math.max(0.5, Math.min(2, s * (window.devicePixelRatio || 1)));
    this.canvas.width = Math.round(w * this.res);
    this.canvas.height = Math.round(H * this.res);
    if (changed) this.placeNotes();
    this.redraw();
    this.onLayout?.();
  }

  /** Swaps the bottom bar the board makes room for (the dock, or the on-screen keyboard). */
  setDock(el) {
    this.dockEl = el;
    this.watcher?.observe(el);
    this.layout();
  }

  // Board point <-> screen point, through the board's own scale and the projector corner-pin on #app.
  // The pen arrives in board coordinates but UI elements are found by screen position.
  screenMatrix() {
    const ma = new DOMMatrix(getComputedStyle(document.getElementById('app')).transform);
    return ma.multiply(new DOMMatrix(getComputedStyle(this.el).transform));
  }

  /** Where a logical board point is on the screen. */
  toScreen(x, y) {
    const p = this.screenMatrix().transformPoint(new DOMPoint(x + this.pad, y));
    return { x: p.x / p.w, y: p.y / p.w };
  }

  /** A screen point as a logical board point; with dom = true, as pixels from the board's left edge (widgets use that). */
  fromScreen(sx, sy, dom = false) {
    const p = this.screenMatrix().inverse().transformPoint(new DOMPoint(sx, sy));
    return { x: p.x / p.w - (dom ? 0 : this.pad), y: p.y / p.w };
  }

  // offsetX/Y are in the canvas's own coordinates, so they stay right when the whole page is
  // corner-pinned for the projector. Bounding-box maths would not, because a warped box is not a rectangle.
  toBoard(e) {
    return { x: e.offsetX - this.pad, y: e.offsetY };
  }

  redraw() {
    const { ctx } = this;
    ctx.setTransform(this.res, 0, 0, this.res, this.pad * this.res, 0);
    ctx.clearRect(-this.pad, 0, this.w, H);
    for (const s of this.strokes) drawStroke(ctx, s);
  }

  // ---- pointer input ---------------------------------------------------
  bindPointer() {
    const c = this.canvas;
    c.addEventListener('pointerdown', (e) => {
      if (e.button !== 0) return;
      c.setPointerCapture(e.pointerId);
      const p = this.toBoard(e);
      this.penDown(p.x, p.y);
    });
    c.addEventListener('pointermove', (e) => {
      if (!this.drawing) return;
      const events = e.getCoalescedEvents?.() || [];
      for (const ev of events.length ? events : [e]) {
        const p = this.toBoard(ev);
        this.penMove(p.x, p.y);
      }
    });
    const end = () => this.penUp();
    c.addEventListener('pointerup', end);
    c.addEventListener('pointercancel', end);
  }

  penDown(x, y) {
    this.drawing = true;
    if (this.tool === 'eraser') {
      this.erased = [];
      this.eraseAt(x, y);
      return;
    }
    this.current = { id: this.nextId++, color: this.color, w: this.size, pts: [[x, y]] };
    drawStroke(this.ctx, this.current);
  }

  penMove(x, y) {
    if (this.tool === 'eraser') return this.eraseAt(x, y);
    const s = this.current;
    if (!s) return;
    const last = s.pts[s.pts.length - 1];
    if (Math.hypot(x - last[0], y - last[1]) < 1.5) return;
    s.pts.push([x, y]);
    const n = s.pts.length;
    const { ctx } = this;
    setStyle(ctx, s, 1, true);
    ctx.beginPath();
    if (n === 2) {
      ctx.moveTo(...s.pts[0]);
      ctx.lineTo(...mid(s.pts[0], s.pts[1]));
    } else {
      ctx.moveTo(...mid(s.pts[n - 3], s.pts[n - 2]));
      const m = mid(s.pts[n - 2], s.pts[n - 1]);
      ctx.quadraticCurveTo(s.pts[n - 2][0], s.pts[n - 2][1], m[0], m[1]);
    }
    ctx.stroke();
  }

  penUp() {
    if (!this.drawing) return;
    this.drawing = false;
    if (this.tool === 'eraser') {
      if (this.erased?.length) this.pushUndo({ type: 'erase', strokes: this.erased });
      this.erased = null;
      return;
    }
    const s = this.current;
    this.current = null;
    if (!s) return;
    this.strokes.push(s);
    this.redraw();
    this.pushUndo({ type: 'add', strokes: [s] });
  }

  eraseAt(x, y) {
    const r = 28;
    const hit = this.strokes.filter((s) => {
      if (s.kind === 'text') {
        const b = textBounds(s);
        return x >= b.x - r && x <= b.x + b.w + r && y >= b.y - r && y <= b.y + b.h + r;
      }
      if (s.pts.length === 1) return Math.hypot(x - s.pts[0][0], y - s.pts[0][1]) <= r + s.w / 2;
      for (let i = 1; i < s.pts.length; i++) {
        if (distToSegment(x, y, s.pts[i - 1], s.pts[i]) <= r + s.w / 2) return true;
      }
      return false;
    });
    if (!hit.length) return;
    this.strokes = this.strokes.filter((s) => !hit.includes(s));
    this.erased.push(...hit);
    this.redraw();
    this.save();
  }

  // ---- history ---------------------------------------------------------
  pushUndo(action) {
    this.undoStack.push(action);
    if (this.undoStack.length > MAX_UNDO) this.undoStack.shift();
    this.redoStack = [];
    this.save();
  }

  addStrokes(list) {
    this.strokes.push(...list);
    this.strokes.sort((a, b) => a.id - b.id);
  }

  removeStrokes(list) {
    const ids = new Set(list.map((s) => s.id));
    this.strokes = this.strokes.filter((s) => !ids.has(s.id));
  }

  undo() {
    const a = this.undoStack.pop();
    if (!a) return;
    if (a.type === 'add') this.removeStrokes(a.strokes);
    else this.addStrokes(a.strokes);
    this.redoStack.push(a);
    this.redraw();
    this.save();
  }

  redo() {
    const a = this.redoStack.pop();
    if (!a) return;
    if (a.type === 'add') this.addStrokes(a.strokes);
    else this.removeStrokes(a.strokes);
    this.undoStack.push(a);
    this.redraw();
    this.save();
  }

  clearInk() {
    if (!this.strokes.length) return;
    this.pushUndo({ type: 'clear', strokes: this.strokes });
    this.strokes = [];
    this.redraw();
  }

  // ---- edits made by JARVIS (coordinates are in 1280x720 snapshot units) -----
  fromAi(v) { return v * K; }

  /** Applies one board_edit event from the server; returns a short description for the chat. */
  applyEdit(ev) {
    switch (ev.op) {
      case 'draw': {
        const n = this.drawShapes(ev.shapes || []);
        return n ? `Drew ${n} item${n === 1 ? '' : 's'}` : 'Nothing to draw';
      }
      case 'edit_note':
        return this.editNote(ev) ? `Updated note ${ev.id}` : `Note ${ev.id} not found`;
      case 'delete_note': {
        if (!this.notes.some((n) => n.id === ev.id)) return `Note ${ev.id} not found`;
        this.removeNote(ev.id);
        return `Deleted note ${ev.id}`;
      }
      case 'clear_ink':
        this.clearInk();
        return 'Cleared the ink';
      case 'undo':
        this.undo();
        return 'Undid the last change';
      default:
        return null;
    }
  }

  drawShapes(shapes) {
    const made = [];
    for (const sh of shapes) {
      const base = { id: this.nextId++, color: sh.color in COLORS ? sh.color : 'cyan', w: sh.width ?? 4 };
      const pts = (list) => list.map(([x, y]) => [x * K, y * K]);
      if (sh.type === 'text') {
        made.push({ ...base, kind: 'text', text: sh.text, x: sh.x * K, y: sh.y * K, size: (sh.size ?? 28) * K });
      } else if (sh.type === 'line') {
        made.push({ ...base, raw: true, pts: pts([[sh.x1, sh.y1], [sh.x2, sh.y2]]) });
      } else if (sh.type === 'arrow') {
        const a = Math.atan2(sh.y2 - sh.y1, sh.x2 - sh.x1);
        const len = Math.min(26, Math.hypot(sh.x2 - sh.x1, sh.y2 - sh.y1) * 0.4);
        const wing = (d) => [sh.x2 - len * Math.cos(a + d), sh.y2 - len * Math.sin(a + d)];
        made.push({ ...base, raw: true, pts: pts([[sh.x1, sh.y1], [sh.x2, sh.y2], wing(0.45), [sh.x2, sh.y2], wing(-0.45)]) });
      } else if (sh.type === 'rect') {
        const { x, y, w, h } = sh;
        made.push({ ...base, raw: true, pts: pts([[x, y], [x + w, y], [x + w, y + h], [x, y + h], [x, y]]) });
      } else if (sh.type === 'ellipse') {
        const cx = sh.x + sh.w / 2, cy = sh.y + sh.h / 2;
        const ring = Array.from({ length: 65 }, (_, i) => {
          const t = (i / 64) * Math.PI * 2;
          return [cx + (sh.w / 2) * Math.cos(t), cy + (sh.h / 2) * Math.sin(t)];
        });
        made.push({ ...base, raw: true, pts: pts(ring) });
      } else if (sh.type === 'arc') {
        // x, y, w, h box the full ellipse; angles run clockwise on screen from 3 o'clock (y points down).
        const cx = sh.x + sh.w / 2, cy = sh.y + sh.h / 2;
        const steps = Math.max(8, Math.ceil(Math.abs(sh.end - sh.start) / 4));
        const ring = Array.from({ length: steps + 1 }, (_, i) => {
          const a = ((sh.start + ((sh.end - sh.start) * i) / steps) * Math.PI) / 180;
          return [cx + (sh.w / 2) * Math.cos(a), cy + (sh.h / 2) * Math.sin(a)];
        });
        made.push({ ...base, raw: true, pts: pts(ring) });
      } else if (sh.type === 'polyline') {
        const flat = sh.points || [];
        const pairs = [];
        for (let i = 0; i + 1 < flat.length; i += 2) pairs.push([flat[i], flat[i + 1]]);
        if (pairs.length > 1) made.push({ ...base, raw: true, pts: pts(pairs) });
      }
    }
    if (!made.length) return 0;
    this.strokes.push(...made);
    this.redraw();
    this.pushUndo({ type: 'add', strokes: made }); // one undo removes the whole drawing
    return made.length;
  }

  editNote({ id, text, color, x, y }) {
    const note = this.notes.find((n) => n.id === id);
    if (!note) return false;
    if (typeof text === 'string') note.text = text;
    if (color in COLORS) note.color = color;
    if (x != null) note.x = clamp(x * K, -this.pad, W + this.pad - NOTE_W);
    if (y != null) note.y = clamp(y * K, 0, H - 60);
    this.renderNotes();
    this.save();
    return true;
  }

  // ---- sticky notes ----------------------------------------------------
  freeSlot() {
    for (let row = 0; row < 3; row++) {
      for (let col = 0; col < 5; col++) {
        const x = 150 + col * 300, y = 150 + row * 230;
        if (!this.notes.some((n) => Math.abs(n.x - x) < 60 && Math.abs(n.y - y) < 60)) return { x, y };
      }
    }
    return { x: 90 + Math.random() * 1200, y: 150 + Math.random() * 600 };
  }

  addNote({ text = '', color = 'cyan', x, y } = {}) {
    const pos = x == null || y == null
      ? this.freeSlot()
      : { x: clamp(x, -this.pad, W + this.pad - NOTE_W), y: clamp(y, 0, H - 60) };
    const note = { id: this.nextId++, text, color: color in COLORS ? color : 'cyan', x: pos.x, y: pos.y };
    this.notes.push(note);
    this.renderNotes();
    this.save();
    return note;
  }

  /** Moves a note by a board-coordinate offset (used when the pen drags a note). */
  nudgeNote(id, dx, dy) {
    const note = this.notes.find((n) => n.id === id);
    const el = this.notesEl.querySelector(`[data-note-id="${id}"]`);
    if (!note || !el) return;
    note.x = clamp(note.x + dx, -this.pad, W + this.pad - NOTE_W);
    note.y = clamp(note.y + dy, 0, H - 60);
    el.style.left = `${note.x + this.pad}px`;
    el.style.top = `${note.y}px`;
  }

  /** Puts the notes where they belong after the board's width (and so its padding) changed. */
  placeNotes() {
    for (const el of this.notesEl.querySelectorAll('[data-note-id]')) {
      const note = this.notes.find((n) => n.id === Number(el.dataset.noteId));
      if (note) el.style.left = `${note.x + this.pad}px`;
    }
  }

  removeNote(id) {
    this.notes = this.notes.filter((n) => n.id !== id);
    this.renderNotes();
    this.save();
  }

  renderNotes() {
    this.notesEl.replaceChildren();
    for (const n of this.notes) {
      const el = document.createElement('div');
      el.className = `note c-${n.color}${n.alertId ? ' alert' : ''}`;
      el.dataset.noteId = n.id;
      el.style.left = `${n.x + this.pad}px`;
      el.style.top = `${n.y}px`;
      el.innerHTML =
        '<div class="note-bar"><span>⠿</span><button class="note-x" title="Delete note">×</button></div>' +
        '<div class="note-text" contenteditable="plaintext-only" spellcheck="false"></div>';
      const text = el.querySelector('.note-text');
      text.textContent = n.text;
      text.addEventListener('input', () => { n.text = text.innerText; this.save(); });
      el.querySelector('.note-x').addEventListener('click', () => this.removeNote(n.id));
      this.makeDraggable(el, el.querySelector('.note-bar'), n);
      this.notesEl.append(el);
      if (n.fresh) { delete n.fresh; text.focus(); }
    }
  }

  makeDraggable(el, handle, note) {
    handle.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button')) return;
      handle.setPointerCapture(e.pointerId);
      // Offsets are measured inside the handle, which moves with the note: each move applies how far the
      // pointer sits from where it grabbed. Correct under scaling and under the projector corner-pin.
      const grabX = e.offsetX, grabY = e.offsetY;
      const move = (ev) => {
        note.x = Math.max(-this.pad, Math.min(W + this.pad - NOTE_W, note.x + (ev.offsetX - grabX)));
        note.y = Math.max(0, Math.min(H - 60, note.y + (ev.offsetY - grabY)));
        el.style.left = `${note.x + this.pad}px`;
        el.style.top = `${note.y}px`;
      };
      const up = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        this.save();
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', up);
    });
  }

  // ---- persistence -----------------------------------------------------
  // Two copies: the page keeps one in localStorage (instant, and works if the server is down) and the server keeps
  // the real one (data/board.json, with backups). When the page opens, whichever was changed last wins.
  payload() {
    return { strokes: this.strokes, notes: this.notes, nextId: this.nextId, savedAt: this.savedAt };
  }

  setSaveState(state) {
    this.saveState = state;
    if (state === 'saved') this.lastSaved = Date.now();
    this.onSaveState?.(state);
  }

  /** Where this page keeps its own copy of a board. */
  storeKey(id = this.id) { return id === MAIN_ID ? STORE_KEY : `${STORE_KEY}.${id}`; }

  get name() { return this.boards.find((b) => b.id === this.id)?.name || 'Board'; }

  save() {
    this.dirty = true;
    this.savedAt = Date.now();
    this.setSaveState('saving');
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.writeLocal(), 300);
    clearTimeout(this.pushTimer);
    this.pushTimer = setTimeout(() => this.push(), 1500);
  }

  writeLocal() {
    try {
      localStorage.setItem(this.storeKey(), JSON.stringify(this.payload()));
    } catch { /* storage unavailable: the server copy still holds it */ }
  }

  async push() {
    clearTimeout(this.pushTimer);
    const id = this.id;
    const sent = this.savedAt;
    try {
      const res = await fetch(`/api/board?id=${encodeURIComponent(id)}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(this.payload()) });
      if (res.status === 404) { this.dirty = false; this.sync(); return; }      // that board was deleted on another screen: show what is there now
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      if (this.id === id && this.savedAt === sent) this.dirty = false;
      this.setSaveState('saved');
    } catch {
      this.setSaveState('offline');
      this.pushTimer = setTimeout(() => this.push(), 8000); // keep trying until the server is back
    }
  }

  /** Asks the PC which boards there are and which one is showing; the page's list follows. Returns it, or null when the PC does not answer. */
  async refreshList() {
    try {
      const res = await fetch('/api/boards');
      if (!res.ok) return null;
      const index = await res.json();
      if (!Array.isArray(index.boards) || !index.boards.length) return null;
      this.boards = index.boards;
      this.onBoards?.(this.boards, this.id, index.current);
      return index;
    } catch {
      return null;
    }
  }

  /** Looks at the PC: switches to the board that is showing there (it may have been changed from the phone or another screen), then
   *  adopts the PC's copy of this board if it is the newer one, or uploads this page's copy if that is newer. */
  async sync() {
    if (this.drawing || this.switching) return;
    const index = await this.refreshList();
    if (index && index.current !== this.id) { await this.switchTo(index.current, { remote: true }); return; }
    await this.pull();
  }

  async pull() {
    const id = this.id;
    try {
      const res = await fetch(`/api/board?board=${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const { board } = await res.json();
      if (this.id !== id) return;                            // another board was chosen while this was loading
      if (board && (board.savedAt || 0) >= this.savedAt) {
        if (board.savedAt !== this.savedAt) this.applyData(board);
        this.dirty = false;
        this.setSaveState('saved');
      } else if (this.strokes.length || this.notes.length || this.savedAt) {
        await this.push();
      } else {
        this.setSaveState('saved');
      }
    } catch {
      this.setSaveState('offline');
    }
  }

  /** Shows another board. What is on this one is saved first. `remote`: the PC already says this is the board showing, so it is not told again. */
  async switchTo(key, { remote = false } = {}) {
    const target = this.boards.find((b) => b.id === key || b.name.toLowerCase() === String(key).toLowerCase());
    if (!target || target.id === this.id || this.switching) return false;
    this.switching = true;
    try {
      this.penUp();                                          // a stroke in progress belongs to this board
      clearTimeout(this.saveTimer);
      this.writeLocal();
      if (this.dirty) { clearTimeout(this.pushTimer); await this.push(); }
      if (!remote) {
        const res = await fetch('/api/boards/current', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: target.id }) });
        if (!res.ok) return false;
      }
      this.id = target.id;
      try { localStorage.setItem(CURRENT_KEY, this.id); } catch { /* a reload opens on the PC's choice */ }
      this.strokes = [];
      this.notes = [];
      this.nextId = 1;
      this.savedAt = 0;
      this.dirty = false;
      this.undoStack = [];
      this.redoStack = [];
      this.load();                                           // this board's copy in the page, shown at once
      this.redraw();
      this.renderNotes();
      this.onBoards?.(this.boards, this.id, this.id);
      this.onSwitched?.({ id: this.id, name: target.name, remote });
    } catch {
      return false;
    } finally {
      this.switching = false;
    }
    await this.pull();
    return true;
  }

  /** The next board in the list (step 1) or the previous one (step -1), wrapping round. */
  step(delta) {
    const i = this.boards.findIndex((b) => b.id === this.id);
    if (this.boards.length < 2 || i < 0) return Promise.resolve(false);
    return this.switchTo(this.boards[(i + delta + this.boards.length) % this.boards.length].id);
  }

  /** Replaces what is on the board with saved data (from the server, or a restored backup). */
  applyData(data) {
    this.strokes = data.strokes || [];
    this.notes = data.notes || [];
    this.nextId = data.nextId || 1;
    this.savedAt = data.savedAt || 0;
    this.undoStack = [];
    this.redoStack = [];
    this.redraw();
    this.renderNotes();
    this.writeLocal();
  }

  load() {
    this.savedAt = 0;
    try {
      const data = JSON.parse(localStorage.getItem(this.storeKey()) || 'null');
      if (!data) return;
      this.strokes = data.strokes || [];
      this.notes = data.notes || [];
      this.nextId = data.nextId || 1;
      this.savedAt = data.savedAt || 0;
    } catch { /* ignore corrupt saves */ }
  }

  // ---- export ------------------------------------------------------------
  /** The whole board (the side space too) as a PNG, on black like the wall. */
  exportPng() {
    const c = document.createElement('canvas');
    c.width = this.w;
    c.height = H;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.translate(this.pad, 0);
    for (const s of this.strokes) drawStroke(ctx, s, 1, true);
    ctx.font = '24px "Segoe UI", sans-serif';
    ctx.textBaseline = 'top';
    for (const n of this.notes) {
      const lines = wrapText(ctx, n.text, NOTE_W - 24);
      const h = Math.max(110, lines.length * 30 + 44);
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#001218';
      ctx.fillRect(n.x, n.y, NOTE_W, h);
      ctx.strokeStyle = COLORS[n.color] || COLORS.cyan;
      ctx.lineWidth = 2;
      ctx.strokeRect(n.x, n.y, NOTE_W, h);
      ctx.fillStyle = COLORS.white;
      lines.forEach((line, i) => ctx.fillText(line, n.x + 12, n.y + 34 + i * 30));
    }
    return new Promise((resolve) => c.toBlob(resolve, 'image/png'));
  }

  exportJson() {
    return new Blob([JSON.stringify(this.payload(), null, 1)], { type: 'application/json' });
  }

  // ---- snapshot for the AI ---------------------------------------------
  snapshot() {
    const k = 1280 / W;
    const c = document.createElement('canvas');
    c.width = 1280;
    c.height = Math.round(H * k);
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, c.width, c.height);
    for (const s of this.strokes) drawStroke(ctx, s, k, false);
    ctx.font = `${Math.round(18 * k * 1.3)}px "Segoe UI", sans-serif`;
    ctx.textBaseline = 'top';
    for (const n of this.notes) {
      const color = COLORS[n.color];
      const x = n.x * k, y = n.y * k, w = NOTE_W * k;
      const lines = wrapText(ctx, n.text, w - 12);
      const lh = 20 * k * 1.3;
      const h = Math.max(70 * k, lines.length * lh + 16);
      ctx.fillStyle = '#001218';
      ctx.fillRect(x, y, w, h);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.strokeRect(x, y, w, h);
      ctx.fillStyle = COLORS.white;
      lines.forEach((line, i) => ctx.fillText(line, x + 6, y + 8 + i * lh));
    }
    return {
      png: c.toDataURL('image/png').split(',')[1],
      name: this.name,
      notes: this.notes.map((n) => ({ id: n.id, text: n.text, x: Math.round(n.x / K), y: Math.round(n.y / K) })),
    };
  }
}
