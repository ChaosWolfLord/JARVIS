// Several whiteboards, each with a name. The Boards button on the bar (and the name tag on the wall) opens a list: tap one to show it, or add, rename and
// delete boards. You can also say "go to the work board", "next board", "new board called Recipes", "rename this board to Plans", "what boards do I have?"
// (typing the same into the chat works too), or press [ and ] for the previous and next board. The PC keeps every board (see server/store.py); this
// page only shows one at a time. Deleting is only done from the menu, with a second tap to confirm, never by voice.

const NUMBERS = { zero: '0', one: '1', two: '2', three: '3', four: '4', five: '5', six: '6', seven: '7', eight: '8', nine: '9', ten: '10' };
const NOUN = String.raw`(?:white ?boards?|boards?|screens?)`;
const LEAD = /^(?:(?:hey|ok|okay|please) )*(?:jarvis )?(?:(?:please|can you|could you|will you) )*/;

/** Lower case words only, spoken numbers as digits: "Board Two!" -> "board 2". */
export function normalize(text) {
  return String(text || '').toLowerCase().replace(/['’]/g, '').replace(/[^a-z0-9]+/g, ' ').trim().split(' ').map((w) => NUMBERS[w] || w).join(' ');
}

/** Which board a spoken name means: the exact name, or a name it is the first words of when only one board fits. */
export function findByName(spoken, names) {
  const want = normalize(spoken);
  if (!want) return null;
  const exact = names.filter((n) => normalize(n) === want);
  if (exact.length === 1) return exact[0];
  const starts = names.filter((n) => normalize(n).startsWith(`${want} `));
  return starts.length === 1 ? starts[0] : null;
}

/** A spoken name as a board name: "pizza night" -> "Pizza Night". */
function titleCase(text) {
  return String(text || '').trim().replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

/** What a sentence asks of the boards, or null when it is about something else. `names` are the boards' names. */
export function parseBoardCommand(text, names = []) {
  const t = normalize(text).replace(LEAD, '').trim();
  if (!t) return null;
  let m;
  if (new RegExp(`^(?:what|which) ${NOUN} (?:do i have|are there|have i got)$`).test(t)
    || /^(?:list|show) (?:me )?(?:my |all |the )?(?:white ?boards|boards|screens)$/.test(t)) return { op: 'list' };
  if (new RegExp(`^(?:what|which) ${NOUN} (?:is this|am i on|am i looking at|is showing|is this one)$`).test(t) || /^(?:what|which) is this (?:white ?board|board|screen)$/.test(t)
    || /^what(?:s| is) this (?:white ?board|board|screen) called$/.test(t)) return { op: 'which' };
  if ((m = new RegExp(`^(?:go to |switch to |show |open |change to |move to )?(?:the )?(next|previous|prior|last) ${NOUN}$`).exec(t))) return { op: m[1] === 'next' ? 'next' : 'previous' };
  if ((m = new RegExp(`^(?:create|make|add|start|open|begin) (?:me )?(?:a |another |one )?new ${NOUN}(?: (?:called|named|for|about|titled) (.+))?$`).exec(t))
    || (m = new RegExp(`^new ${NOUN}(?: (?:called|named|for|about|titled) (.+))?$`).exec(t))) return { op: 'new', name: titleCase(m[1]) };
  if ((m = new RegExp(`^(?:rename|call|name) (?:this|the current|the|my) ${NOUN} (?:to |as |called )?(.+)$`).exec(t))) return { op: 'rename', name: titleCase(m[1]) };
  if ((m = /^(?:switch|go|change|move|jump|flip|take me)(?: back)?(?: over)? to (?:the |my )?(.+)$/.exec(t)) || (m = /^(?:open|show me|show|bring up|pull up|load) (?:the |my )?(.+)$/.exec(t))) {
    const opening = /^(?:open|show|bring|pull|load)/.test(t);
    let name = m[1];
    const hadNoun = new RegExp(`(?:^| )${NOUN}$`).test(name) || new RegExp(`^${NOUN} `).test(name);
    name = name.replace(new RegExp(`(?: ${NOUN})$`), '').replace(new RegExp(`^${NOUN} `), '').trim();
    if (!name || new RegExp(`^${NOUN}$`).test(name)) return null;
    const found = findByName(name, names) || findByName(m[1], names);
    if (found && (hadNoun || !opening)) return { op: 'switch', name: found };
    if (hadNoun) return { op: 'missing', name };
  }
  return null;
}

const el = (tag, text, cls) => Object.assign(document.createElement(tag), text == null ? {} : { textContent: text }, cls ? { className: cls } : {});

export class Boards {
  /** board: the Board. button/menu: the bar's button and its menu. pill: the name on the wall; bar, prev and next: its frame and its two arrows. speak/show: say a line / put it in the bubble. */
  constructor({ board, button, menu, pill, bar = null, prev = null, next = null, speak = () => {}, show = () => {} }) {
    this.board = board;
    this.button = button;
    this.menu = menu;
    this.pill = pill;
    this.bar = bar || pill;
    this.speak = speak;
    this.show = show;
    this.confirming = false;
    this.note = '';
    this.build();
    board.onBoards = () => this.render();
    board.onSwitched = ({ name, remote }) => { this.show(`Board: ${name}`); this.confirming = false; if (remote) this.render(); };
    prev?.addEventListener('click', (e) => { e.stopPropagation(); this.board.step(-1); });         // the arrows beside the name
    next?.addEventListener('click', (e) => { e.stopPropagation(); this.board.step(1); });
    pill?.addEventListener('click', (e) => { e.stopPropagation(); button.click(); });      // not on to the page, whose "click outside" would close the menu again
    this.render();
  }

  build() {
    this.title = el('h3', 'Whiteboards');
    this.list = el('ul', null, 'boards-list');
    this.input = Object.assign(document.createElement('input'), { type: 'text', maxLength: 40, placeholder: 'A name, for example Work', autocomplete: 'off' });
    this.input.setAttribute('aria-label', 'Board name');
    this.addBtn = Object.assign(el('button', 'New board'), { type: 'button' });
    this.renameBtn = Object.assign(el('button', 'Rename this one'), { type: 'button' });
    this.deleteBtn = Object.assign(el('button', 'Delete this board', 'danger'), { type: 'button' });
    this.animate = Object.assign(document.createElement('input'), { type: 'checkbox' });
    this.animate.checked = this.board.flip ? this.board.flip.enabled : false;
    this.animate.addEventListener('change', () => { if (this.board.flip) this.board.flip.enabled = this.animate.checked; });
    const animLabel = el('label', null, 'boards-anim');
    animLabel.append(this.animate, document.createTextNode(' Animate switching between boards'));
    animLabel.hidden = !this.board.flip;
    this.status = el('p', '', 'wm-hint');
    this.status.setAttribute('role', 'status');
    const form = el('div', null, 'boards-form');
    const actions = el('div', null, 'boards-actions');
    actions.append(this.addBtn, this.renameBtn, this.deleteBtn);
    form.append(this.input, actions);
    this.menu.replaceChildren(this.title, this.list, form, animLabel, this.status);
    this.input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); this.create(); } });
    this.addBtn.addEventListener('click', () => this.create());
    this.renameBtn.addEventListener('click', () => this.rename());
    this.deleteBtn.addEventListener('click', () => this.remove());
  }

  say(text) { this.status.textContent = text || ''; }

  render() {
    const { boards, id } = this.board;
    this.list.replaceChildren(...boards.map((b) => {
      const li = el('li');
      const btn = Object.assign(el('button', null, `menu-row board-row${b.id === id ? ' active' : ''}`), { type: 'button' });
      btn.append(el('b', b.name), el('em', 'Showing', 'state'));
      btn.addEventListener('click', () => this.board.switchTo(b.id));
      li.append(btn);
      return li;
    }));
    this.deleteBtn.textContent = this.confirming ? `Really delete “${this.board.name}”?` : 'Delete this board';
    this.deleteBtn.disabled = boards.length < 2;
    if (this.pill) {
      this.bar.hidden = boards.length < 2;                   // with one board there is nothing to tell apart or to step between
      this.pill.textContent = this.board.name;
    }
    this.button.title = `Whiteboards: ${this.board.name}. Switch, add or rename (or say “next board”; [ and ] on the keyboard)`;
    const small = this.button.querySelector('small');
    if (small) small.textContent = boards.length < 2 ? 'Make another whiteboard, each with its own name. You have one.' : `Showing ${this.board.name}. Switch to another, or make one (or say “next board”).`;
  }

  async call(url, method, body) {
    try {
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
      const data = await res.json().catch(() => ({}));
      if (res.ok) return { ok: true, data };
      // The page files are always the newest, but the PC's program only changes when JARVIS is restarted: an older one answers "Method Not Allowed" / "Not Found".
      if ((res.status === 405 || res.status === 404) && /^(?:method not allowed|not found)$/i.test(data.detail || '')) {
        return { ok: false, error: 'This PC is still running an older JARVIS that has no whiteboards. Restart it (run JARVIS_stop.bat, then JARVIS.bat) and try again.' };
      }
      return { ok: false, error: data.detail || 'That did not work.' };
    } catch {
      return { ok: false, error: 'JARVIS is not reachable right now.' };
    }
  }

  /** Makes a new, empty board and shows it. With no name it is called "Board 2", "Board 3"... */
  async create(name = this.input.value, spoken = false) {
    let wanted = String(name || '').trim();
    if (!wanted) {
      const have = new Set(this.board.boards.map((b) => b.name.toLowerCase()));
      let n = this.board.boards.length + 1;
      while (have.has(`board ${n}`)) n += 1;
      wanted = `Board ${n}`;
    }
    const out = await this.call('/api/boards', 'POST', { name: wanted, switch: true });
    if (!out.ok) { this.say(out.error); if (spoken) this.speak(out.error); return false; }
    this.input.value = '';
    this.say('');
    await this.board.refreshList();
    await this.board.switchTo(out.data.created, { remote: true });
    if (spoken) this.speak(`Made a new board called ${wanted}.`);
    return true;
  }

  async rename(name = this.input.value, spoken = false) {
    const wanted = String(name || '').trim();
    if (!wanted) { this.say('Type the new name first.'); return false; }
    const out = await this.call(`/api/boards/${encodeURIComponent(this.board.id)}/rename`, 'POST', { name: wanted });
    if (!out.ok) { this.say(out.error); if (spoken) this.speak(out.error); return false; }
    this.input.value = '';
    this.say('');
    await this.board.refreshList();
    if (spoken) this.speak(`This board is now called ${wanted}.`);
    return true;
  }

  /** Deletes the board that is showing, after a second tap. The PC keeps a last backup of it. */
  async remove() {
    if (this.board.boards.length < 2) return;
    if (!this.confirming) {
      this.confirming = true;
      this.render();
      setTimeout(() => { if (this.confirming) { this.confirming = false; this.render(); } }, 5000);
      return;
    }
    this.confirming = false;
    const id = this.board.id;
    const out = await this.call(`/api/boards/${encodeURIComponent(id)}`, 'DELETE');
    if (!out.ok) { this.say(out.error); this.render(); return; }
    try { localStorage.removeItem(this.board.storeKey(id)); } catch { /* nothing kept */ }
    this.board.dirty = false;
    await this.board.sync();                                 // the PC chose the board to show instead
    this.say('Deleted.');
  }

  names() { return this.board.boards.map((b) => b.name); }

  /** True means: this sentence was about the boards, so don't send it to the AI. */
  handleVoice(command) {
    const cmd = parseBoardCommand(command, this.names());
    if (!cmd) return false;
    this.run(cmd);
    return true;
  }

  async run(cmd) {
    const names = this.names();
    const here = this.board.name;
    switch (cmd.op) {
      case 'switch': {
        if (normalize(cmd.name) === normalize(here)) { this.speak(`You are already on ${here}.`); break; }
        this.speak((await this.board.switchTo(cmd.name)) ? `Switched to ${cmd.name}.` : 'I could not switch just now.');
        break;
      }
      case 'missing': this.speak(`I don't have a board called ${cmd.name}. Your boards are ${list(names)}.`); break;
      case 'next':
      case 'previous': {
        if (names.length < 2) { this.speak('There is only one board. Say new board to make another.'); break; }
        await this.board.step(cmd.op === 'next' ? 1 : -1);
        this.speak(`${this.board.name}.`);
        break;
      }
      case 'list': this.speak(`You have ${names.length === 1 ? 'one board' : `${names.length} boards`}: ${list(names)}. You are on ${here}.`); break;
      case 'which': this.speak(`You are on ${here}.`); break;
      case 'new': await this.create(cmd.name, true); break;
      case 'rename': await this.rename(cmd.name, true); break;
      default: break;
    }
  }
}

function list(names) {
  return names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`;
}
