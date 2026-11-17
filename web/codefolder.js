// The "Code folder" section of the status menu: choose the folder that holds your projects and switch reading on or off. The AI can then list, read and
// search the text files in it (read-only; see server/codefolder.py for everything it will not read). The PC keeps the setting; this only shows and changes it.

const post = (body) => fetch('/api/code', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  .then(async (res) => { const data = await res.json().catch(() => ({})); if (!res.ok) throw new Error(data.detail || 'That did not work.'); return data; });

export class CodeFolder {
  constructor({ root }) {
    const q = (id) => root?.querySelector(id);
    this.input = q('#code-root');
    this.stateEl = q('#code-state');
    this.noteEl = q('#code-note');
    this.toggle = q('#code-toggle');
    this.suggest = q('#code-suggest');
    this.suggestion = '';
    this.on = false;
    if (!this.input) return;
    q('#code-save').addEventListener('click', () => this.change({ root: this.input.value }, 'Folder saved.'));
    this.input.addEventListener('keydown', (e) => { e.stopPropagation(); if (e.key === 'Enter') { e.preventDefault(); this.change({ root: this.input.value }, 'Folder saved.'); } });
    this.toggle.addEventListener('click', () => this.change({ enabled: !this.on }, this.on ? 'Reading is off.' : 'Reading is on.'));
    this.suggest.addEventListener('click', () => { this.input.value = this.suggestion; this.change({ root: this.suggestion }, 'Folder saved.'); });
  }

  say(text) { if (this.noteEl) this.noteEl.textContent = text || ''; }

  fill(s) {
    if (!this.input || !s) return;
    this.on = Boolean(s.on);
    this.suggestion = s.suggestion || '';
    if (document.activeElement !== this.input) this.input.value = s.root || '';
    this.suggest.hidden = !this.suggestion || this.suggestion === s.root;
    this.toggle.textContent = this.on ? 'Turn off' : 'Turn on';
    this.stateEl.textContent = this.on ? `On: JARVIS can read (not change) ${s.root}`
      : s.enabled && s.note ? `Off: ${s.note}` : s.root ? 'Off. Press Turn on when you are ready.' : 'Off. Choose a folder first.';
  }

  async change(body, done) {
    try { this.fill(await post(body)); this.say(done); } catch (e) { this.say(e.message); }
  }

  refresh() { return fetch('/api/code').then((r) => r.json()).then((s) => this.fill(s)).catch(() => {}); }
}
