// The memory window: everything JARVIS remembers about you, searchable. Tap a line to edit it, the pin to keep it
// always in mind, the kind to re-file it, × to forget it. JARVIS itself only gets the pinned facts and the ones that
// match what you say, so a long list doesn't slow it down; this window shows all of it.

const KINDS = ['fact', 'preference', 'person', 'project', 'event'];
const json = { 'Content-Type': 'application/json' };

export class MemoryPanel {
  constructor({ modal, list, search, count, form, input, kind, toast }) {
    this.modal = modal;
    this.list = list;
    this.search = search;
    this.count = count;
    this.input = input;
    this.kind = kind;
    this.toast = toast;
    this.timer = null;

    modal.addEventListener('click', (e) => { if (e.target === modal) this.close(); });
    search.addEventListener('input', () => { clearTimeout(this.timer); this.timer = setTimeout(() => this.load(), 200); });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const fact = input.value.trim();
      if (!fact) return;
      await fetch('/api/memory', { method: 'POST', headers: json, body: JSON.stringify({ fact, kind: kind.value }) });
      input.value = '';
      this.load();
    });
  }

  open() {
    this.modal.hidden = false;
    this.search.value = '';
    this.load();
    this.input.focus();
  }

  close() { this.modal.hidden = true; }

  async send(id, body) {
    const res = await fetch(`/api/memory/${id}`, { method: 'PUT', headers: json, body: JSON.stringify(body) });
    if (!res.ok) this.toast('Couldn’t save that change.');
    this.load();
  }

  async load() {
    const q = this.search.value.trim();
    const mine = (this.seq = (this.seq || 0) + 1);      // only the newest request may draw: an older, slower one must not overwrite it
    let facts = [];
    try {
      facts = await (await fetch(`/api/memory${q ? `?q=${encodeURIComponent(q)}` : ''}`)).json();
    } catch {
      this.count.textContent = 'Couldn’t reach the server.';
      return;
    }
    if (mine !== this.seq) return;
    this.count.textContent = q ? `${facts.length} match${facts.length === 1 ? '' : 'es'} for “${q}”` : `${facts.length} thing${facts.length === 1 ? '' : 's'} remembered`;
    if (!facts.length) {
      this.list.replaceChildren(Object.assign(document.createElement('li'), {
        className: 'empty', textContent: q ? 'Nothing matches that.' : 'Nothing yet. Tell JARVIS to remember something, or add a fact below.',
      }));
      return;
    }
    this.list.replaceChildren(...facts.map((f) => this.row(f)));
  }

  row(f) {
    const li = document.createElement('li');
    li.className = f.pinned ? 'pinned' : '';

    const pin = Object.assign(document.createElement('button'), { type: 'button', className: 'mem-pin', textContent: f.pinned ? '★' : '☆',
      title: f.pinned ? 'Pinned: always in mind. Tap to unpin' : 'Pin: keep this always in mind' });
    pin.addEventListener('click', () => this.send(f.id, { pinned: !f.pinned }));

    const kind = document.createElement('select');
    kind.className = 'mem-kind';
    kind.title = 'What kind of memory';
    for (const k of KINDS) kind.append(Object.assign(document.createElement('option'), { value: k, textContent: k, selected: k === f.kind }));
    kind.addEventListener('change', () => this.send(f.id, { kind: kind.value }));

    const text = Object.assign(document.createElement('span'), { className: 'mem-text', textContent: f.fact, title: 'Tap to edit' });
    text.addEventListener('click', () => this.edit(li, text, f));

    const used = Object.assign(document.createElement('small'), {
      textContent: f.uses ? `used ${f.uses}×` : '', title: f.last_used ? `Last used ${new Date(f.last_used).toLocaleString()}` : '',
    });

    const del = Object.assign(document.createElement('button'), { type: 'button', className: 'mem-del', textContent: '×', title: 'Forget this' });
    del.addEventListener('click', async () => { await fetch(`/api/memory/${f.id}`, { method: 'DELETE' }); this.load(); });

    li.append(pin, kind, text, used, del);
    return li;
  }

  edit(li, text, f) {
    const box = Object.assign(document.createElement('input'), { type: 'text', className: 'mem-edit', value: f.fact, maxLength: 300 });
    text.replaceWith(box);
    box.focus();
    box.select();
    let done = false;
    const finish = (save) => {
      if (done) return;
      done = true;
      const value = box.value.trim();
      if (save && value && value !== f.fact) this.send(f.id, { fact: value });
      else this.load();
    };
    box.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') finish(true);
      else if (e.key === 'Escape') finish(false);
    });
    box.addEventListener('blur', () => finish(true));
  }
}
