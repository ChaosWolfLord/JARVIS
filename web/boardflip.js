// The animation when you switch whiteboards (designed as a prototype in Claude Design, then built here): the board you are on pulls back into a
// showcase of all your boards, the showcase slides to the one you chose, and that one flies forward and comes to a smooth stop, filling the wall.
//
// Three phases, each a CSS transition on the cards (so the graphics card does the work):
//   back     the current board shrinks and tilts back into a row of boards (ease-out)
//   showcase the row slides until the board you chose is in the middle (ease-in-out)
//   fly      that board comes forward to full size; a long ease-out makes it settle gently, the others sink away
// The cards are pictures of the boards drawn by the Board (board.paintPreview). The real board is hidden while this plays and the switch happens
// underneath it, so the card that lands is the board itself. It is skipped (the switch is instant) when the page is in the background, when the
// person asked for reduced motion, or when "Animate switching" is switched off in the Whiteboards menu.

export const TIMING = { back: 520, hold: 60, slide: 440, pause: 80, fly: 680, label: 320, fade: 140 };
const EASE = { back: 'cubic-bezier(0.32, 0.72, 0, 1)', slide: 'cubic-bezier(0.45, 0, 0.2, 1)', fly: 'cubic-bezier(0.16, 1, 0.3, 1)', sink: 'cubic-bezier(0.4, 0, 0.6, 1)' };
const KEY = 'jarvis.boardAnim';

/** Where a card is in each phase. Pure: x spacing follows the board's width, depth follows its height (the design was drawn at 1280 x 720). */
export function cardPose({ phase, i, focus, current, target, w = 1920, h = 1080 }) {
  const kx = w / 1280, kz = h / 720;
  const d = i - focus;
  if (phase === 'idle') {
    const here = i === current;
    return { x: here ? 0 : d * 450 * kx, z: here ? 0 : -400 * kz, r: 0, s: here ? 1 : 0.5, o: here ? 1 : 0, label: 0, flat: here, ease: EASE.back, ms: 0, lift: here ? 5 : 1 };
  }
  if (phase === 'back' || phase === 'showcase') {
    const mid = d === 0;
    return {
      x: d * 450 * kx, z: (mid ? -40 : -190) * kz, r: mid ? 0 : (d > 0 ? -30 : 30), s: mid ? 0.46 : 0.4,
      o: mid ? 1 : (Math.abs(d) > 2 ? 0 : 0.62), label: mid ? 1 : 0.9, flat: false,
      ease: phase === 'back' ? EASE.back : EASE.slide, ms: phase === 'back' ? TIMING.back : TIMING.slide, lift: mid ? 5 : 3,
    };
  }
  const chosen = i === target;                                   // fly
  return {
    x: chosen ? 0 : d * 450 * kx, z: chosen ? 0 : -520 * kz, r: chosen ? 0 : (d > 0 ? -34 : 34), s: chosen ? 1 : 0.34,
    o: chosen ? 1 : 0, label: 0, flat: chosen, ease: chosen ? EASE.fly : EASE.sink, ms: chosen ? TIMING.fly : TIMING.slide, lift: chosen ? 9 : 2,
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Flight {
  constructor({ board, boards, from, to, host, anchor }) {
    this.board = board;
    this.from = from;
    this.to = to;
    this.boards = boards;
    this.w = board.w;
    this.h = 1080;
    this.layer = document.createElement('div');
    this.layer.className = 'bf-layer';
    this.layer.style.perspective = `${Math.round(1500 * (this.h / 720))}px`;
    this.cards = boards.map((b, i) => this.makeCard(b, i));
    this.layer.append(...this.cards.map((c) => c.el));
    host.classList.add('board-flipping');
    host.insertBefore(this.layer, anchor || null);              // above the ink and notes, below the clock and cards (widgets)
    this.host = host;
    this.landing = new Promise((resolve) => { this.land = resolve; });
    this.done = this.run();
    this.timeout = setTimeout(() => this.land(this.from), 8000);       // never stuck: if nobody says where to land, go back
  }

  makeCard(b, i) {
    const el = document.createElement('div');
    el.className = 'bf-card';
    el.style.width = `${this.w}px`;
    el.style.height = `${this.h}px`;
    el.style.margin = `${-this.h / 2}px 0 0 ${-this.w / 2}px`;
    const face = document.createElement('div');
    face.className = 'bf-face';
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(this.w * 0.6);
    canvas.height = Math.round(this.h * 0.6);
    const name = document.createElement('div');
    name.className = 'bf-name';
    name.textContent = b.name;
    face.append(canvas, name);
    el.append(face);
    const card = { el, face, name, canvas, id: b.id };
    const own = i === this.from;
    this.board.paintPreview(canvas, own ? null : this.board.localCopy(b.id));
    if (!own && (Math.abs(i - this.from) <= 2 || Math.abs(i - this.to) <= 2)) {
      this.board.fetchCopy(b.id).then((data) => { if (data && !this.finished) this.board.paintPreview(canvas, data); });
    }
    this.pose(card, i, { phase: 'idle', focus: this.from, current: this.from, target: this.to }, true);
    return card;
  }

  pose(card, i, state, instant = false) {
    const p = cardPose({ ...state, i, w: this.w, h: this.h });
    const t = instant ? 'none' : `transform ${p.ms}ms ${p.ease}, opacity ${TIMING.label + 60}ms ease`;
    card.el.style.transition = t;
    card.el.style.transform = `translate3d(${p.x}px, 0, ${p.z}px) rotateY(${p.r}deg) scale(${p.s})`;
    card.el.style.opacity = String(p.o);
    card.el.style.zIndex = String(p.lift);
    card.name.style.transition = instant ? 'none' : `opacity ${TIMING.label}ms ease`;
    card.name.style.opacity = String(p.label);
    card.face.classList.toggle('bf-flat', p.flat && state.phase === 'fly');      // the landing card loses its frame, so it is the board itself
    card.face.style.transition = instant ? 'none' : `border-radius ${p.ms}ms ${p.ease}, border-color ${p.ms}ms ${p.ease}, box-shadow ${p.ms}ms ${p.ease}`;
  }

  set(phase, focus, current = this.from, target = this.to) {
    this.cards.forEach((c, i) => this.pose(c, i, { phase, focus, current, target }));
  }

  async run() {
    void this.layer.offsetWidth;                               // the cards are laid out at rest first (a forced style flush, not a frame callback), so the pull-back has somewhere to start from
    await sleep(30);
    this.set('back', this.from);
    await sleep(TIMING.back + TIMING.hold);
    this.set('showcase', this.to);
    await sleep(TIMING.slide + TIMING.pause);
    const landed = await this.landing;
    clearTimeout(this.timeout);
    if (landed !== this.to) { this.set('showcase', landed); await sleep(TIMING.slide); }
    this.board.paintPreview(this.cards[landed].canvas, null);   // the board underneath now shows the board it switched to: land with exactly that picture
    this.set('fly', landed, this.from, landed);
    await sleep(TIMING.fly);
    this.layer.style.transition = `opacity ${TIMING.fade}ms ease`;
    this.layer.style.opacity = '0';
    await sleep(TIMING.fade);
    this.finish();
  }

  finish() {
    this.finished = true;
    clearTimeout(this.timeout);
    this.layer.remove();
    this.host.classList.remove('board-flipping');
  }

  /** Says which board to land on (the one chosen, or the one it came from when the switch failed). Resolves when the animation is over. */
  arrive(index) {
    this.land(index);
    return this.done;
  }
}

export class BoardFlip {
  /** board: the Board (its size, its pictures of boards). */
  constructor({ board }) {
    this.board = board;
  }

  get enabled() {
    try { return localStorage.getItem(KEY) !== 'off'; } catch { return true; }
  }

  set enabled(on) {
    try { localStorage.setItem(KEY, on ? 'on' : 'off'); } catch { /* not remembered */ }
  }

  /** Will a switch be animated right now? */
  canPlay() {
    if (!this.enabled || document.hidden) return false;
    try { if (matchMedia('(prefers-reduced-motion: reduce)').matches) return false; } catch { /* no media queries */ }
    return Boolean(this.board.el?.isConnected);
  }

  start({ boards, from, to }) {
    const anchor = document.getElementById('hud');
    return new Flight({ board: this.board, boards, from, to, host: this.board.el, anchor: anchor?.parentNode === this.board.el ? anchor : null });
  }
}
