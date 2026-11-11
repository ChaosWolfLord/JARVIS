// The file finder on the page: the "Files" card on the wall that lists what JARVIS found ("find the doc I edited yesterday about the budget"), and
// the status-menu part where you choose which folders it may look in. The card is built with text only (a file name is never treated as page
// code), and the buttons go back to this PC, which only ever opens files inside the folders you chose and never launches a program or script.

const ASK = /^(?:please |can you |could you |would you |hey )?(?:jarvis[ ,]*)?(?:find|search for|search my files for|look for|locate|dig up|get me|where(?:'s| is| are| did i put| did i save))\b/i;
const FILEISH = /\b(files?|documents?|docs?|pdfs?|spreadsheets?|sheets?|excel|presentations?|slides|powerpoint|screenshots?|photos?|pictures?|images?|videos?|recordings?|downloads?|report|essay|invoice|receipt|notes?|folder|csv|word|deck)\b/i;
const WEB_PICTURE = /\b(?:a |an |some |the )?(?:picture|photo|image|pic)s? (?:of|for|showing) /i;

const el = (tag, text, cls) => Object.assign(document.createElement(tag), text == null ? {} : { textContent: text }, cls ? { className: cls } : {});

export class Files {
  /** root: the card. speak: says a line out loud. show: puts the card on the wall. */
  constructor({ el: card, speak = () => {}, show = () => {}, showPicture = () => {} }) {
    this.card = card;
    this.speak = speak;
    this.showCard = show;
    this.showPicture = showPicture;
    this.list = card.querySelector('#files-list');
    this.title = card.querySelector('#files-title');
    this.foot = card.querySelector('#files-foot');
    this.fallback = null;          // (command) => void: asks the AI when the sentence was not a file request
  }

  /** The "files" event from the PC: {title, items:[{path, name, folder, when, size_text, kind, openable, image}], searched, complete}. */
  show(ev) {
    if (!ev || !Array.isArray(ev.items)) return false;
    this.title.textContent = `FILES · ${String(ev.title || '').slice(0, 40).toUpperCase()}`;
    this.list.replaceChildren();
    if (!ev.items.length) this.list.append(el('li', 'Nothing matched in the folders you chose.', 'files-none'));
    for (const item of ev.items.slice(0, 10)) {
      const row = el('li');
      const info = el('div', null, 'files-info');
      info.append(el('b', String(item.name || '')), el('small', `${String(item.folder || '')}  ·  ${String(item.when || '')}  ·  ${String(item.size_text || '')}`));
      const buttons = el('div', null, 'files-buttons');
      const add = (label, how, title) => {
        const b = el('button', label);
        b.type = 'button';
        b.title = title;
        b.addEventListener('click', () => this.act(item, how, b));
        buttons.append(b);
      };
      if (item.openable) add('Open', 'open', 'Open it with its usual program');
      add('Folder', 'folder', 'Show it in its folder');
      if (item.image) add('Wall', 'wall', 'Put this picture on the wall');
      row.append(info, buttons);
      this.list.append(row);
    }
    this.foot.textContent = ev.complete === false ? 'The search ran out of time, so some files were not checked.' : `${ev.searched ?? 0} files looked through`;
    return true;
  }

  async act(item, how, button) {
    const old = button.textContent;
    button.disabled = true;
    try {
      const res = await fetch('/api/finder/open', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: item.path, how }) });
      const out = await res.json();
      if (!res.ok) { this.foot.textContent = out.detail || 'That did not work.'; return; }
      if (out.event) this.showPicture(out.event);
      this.foot.textContent = out.text || '';
    } catch {
      this.foot.textContent = 'Could not reach JARVIS.';
    } finally {
      button.disabled = false;
      button.textContent = old;
    }
  }

  /** True means: don't send this to the AI (the PC is looking, or will hand the sentence back). */
  handleVoice(command) {
    const text = command.trim().replace(/[^\w' -]/g, ' ').replace(/\s+/g, ' ');
    if (!ASK.test(text) || !FILEISH.test(text) || WEB_PICTURE.test(text)) return false;
    this.answer(command);
    return true;
  }

  async answer(command) {
    try {
      const res = await fetch('/api/finder/voice', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: command }) });
      const out = await res.json();
      if (!res.ok || !out.handled) return this.fallback?.(command);
      if (out.event) this.showCard(out.event);
      this.speak(out.text);
    } catch {
      this.fallback?.(command);
    }
    return undefined;
  }
}

/** The status-menu part: which folders JARVIS may search. Nothing is searched until you add one. */
export class FinderFolders {
  constructor({ root }) {
    this.list = root.querySelector('#finder-folders');
    this.suggest = root.querySelector('#finder-suggest');
    this.input = root.querySelector('#finder-path');
    this.note = root.querySelector('#finder-note');
    this.folders = [];
    root.querySelector('#finder-form').addEventListener('submit', (e) => { e.preventDefault(); this.add(this.input.value); });
  }

  async refresh() {
    try {
      const d = await (await fetch('/api/finder', { cache: 'no-store' })).json();
      this.folders = d.folders || [];
      this.suggestions = d.suggestions || [];
      this.draw();
    } catch {
      this.note.textContent = 'Could not read the file finder settings.';
    }
  }

  draw() {
    this.list.replaceChildren();
    if (!this.folders.length) this.list.append(el('li', 'No folders yet, so nothing is searched.', 'files-none'));
    for (const folder of this.folders) {
      const row = el('li');
      const remove = el('button', 'Remove');
      remove.type = 'button';
      remove.addEventListener('click', () => this.save(this.folders.filter((f) => f !== folder)));
      row.append(el('span', folder, 'files-folder'), remove);
      this.list.append(row);
    }
    this.suggest.replaceChildren();
    for (const s of (this.suggestions || []).filter((x) => !this.folders.some((f) => f.toLowerCase() === x.toLowerCase()))) {
      const b = el('button', `Add ${/onedrive/i.test(s) ? 'OneDrive ' : ''}${s.split(/[\\/]/).pop()}`);
      b.type = 'button';
      b.title = s;
      b.addEventListener('click', () => this.add(s));
      this.suggest.append(b);
    }
  }

  async add(path) {
    const text = String(path || '').trim();
    if (!text) { this.note.textContent = 'Type or paste a folder.'; return; }
    await this.save([...this.folders, text]);
    if (!this.note.dataset.failed) this.input.value = '';
  }

  async save(folders) {
    delete this.note.dataset.failed;
    try {
      const res = await fetch('/api/finder', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ folders }) });
      const d = await res.json();
      if (!res.ok) { this.note.textContent = d.detail || 'That folder was not accepted.'; this.note.dataset.failed = '1'; return; }
      this.folders = d.folders;
      this.note.textContent = d.folders.length ? 'Saved. JARVIS searches only these folders (and what is inside them).' : 'No folders: the finder searches nothing.';
      this.draw();
    } catch {
      this.note.textContent = 'Could not reach JARVIS.';
      this.note.dataset.failed = '1';
    }
  }
}
