// The status light and its menu: is the server up, is the AI reachable, is voice on, is the pen tracker connected,
// is the board saved. Also the board's export and backup tools, and the banner that shows when the server stops.

import { fitMenu } from './menufit.js';

const POLL_MS = 4000;
const TIMES = { hour: 'numeric', minute: '2-digit' };

function download(blob, name) {
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
}

const stamp = () => new Date().toISOString().slice(0, 16).replace('T', '-').replace(':', '');

export class Status {
  constructor({ button, menu, banner, board, voice, pen, toast }) {
    this.button = button;
    this.menu = menu;
    this.banner = banner;
    this.board = board;
    this.voice = voice;
    this.pen = pen;
    this.toast = toast;
    this.info = null;
    this.up = null;      // null until the first answer
    this.fails = 0;
    this.backups = null;

    button.addEventListener('click', () => this.toggle());
    document.addEventListener('click', (e) => {
      if (!this.menu.hidden && !this.menu.contains(e.target) && !this.button.contains(e.target)) this.toggle(false);
    });
    board.onSaveState = () => this.render();
    this.poll();
    setInterval(() => this.poll(), POLL_MS);
    setInterval(() => { if (!this.menu.hidden) this.render(); }, 1000);
  }

  async poll() {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), 3000);
    try {
      const res = await fetch('/api/status', { signal: ctl.signal, cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      this.info = await res.json();
      this.onInfo?.(this.info);
      const wasDown = this.up === false;
      this.up = true;
      this.fails = 0;
      if (wasDown) { this.board.sync(); this.toast('JARVIS is back.'); }
    } catch {
      this.fails += 1;
      if (this.fails >= 2) this.up = false; // one missed answer isn't an outage
    } finally {
      clearTimeout(timer);
    }
    this.render();
  }

  toggle(open = this.menu.hidden) {
    this.menu.hidden = !open;
    this.button.classList.toggle('active', open);
    if (open) { this.backups = null; this.render(); fitMenu(this.menu); }
  }

  /** 'ok', 'warn' or 'down' for the light on the dock. */
  level() {
    if (this.up === false) return 'down';
    if (this.up === null) return 'warn';
    const i = this.info || {};
    if (!i.key_set || this.board.saveState === 'offline' || i.alerts > 0) return 'warn';
    return 'ok';
  }

  render() {
    const level = this.level();
    this.button.dataset.level = level;
    this.banner.hidden = this.up !== false;
    if (this.menu.hidden) return;

    const i = this.info || {};
    const saved = { saving: 'Saving…', offline: 'Not saved to the PC (server offline). Kept in this browser for now.' }[this.board.saveState]
      || (this.board.lastSaved ? `Saved ${new Date(this.board.lastSaved).toLocaleTimeString([], TIMES)}` : 'Not changed yet');
    const left = i.openrouter ? Math.max(0, i.openrouter.limit - i.openrouter.used_today) : null;
    const rows = [
      ['Server', this.up === false ? 'Not running' : this.up ? 'Running' : 'Checking…', this.up ? 'ok' : this.up === false ? 'down' : 'warn'],
      ['AI', !this.up ? '—' : !i.key_set ? `No API key (add ${i.key_env || 'a key'} to .env)` : `${i.model || 'ready'}${left != null ? ` · about ${left} free requests left today` : ` · ${i.requests_today} requests today`}`,
        !this.up ? 'warn' : i.key_set ? 'ok' : 'warn'],
      ['Voice', !this.voice.supported ? 'Needs Chrome or Edge' : this.voice.enabled ? 'Listening for “Jarvis”' : 'Off (press M)', this.voice.enabled ? 'ok' : 'idle'],
      ['Pen tracker', this.pen.trackerUp ? `Connected${this.pen.camera ? ` (${this.pen.camera})` : ''}` : 'Not running', this.pen.trackerUp ? 'ok' : 'idle'],
      ['System', !this.up ? '—' : i.alerts ? `${i.alerts} problem${i.alerts > 1 ? 's' : ''} found: see the red notes` : 'No problems found', i.alerts ? 'warn' : 'ok'],
      ['Board', saved, this.board.saveState === 'offline' ? 'warn' : 'ok'],
    ];
    const list = this.menu.querySelector('#status-rows');
    list.replaceChildren(...rows.map(([name, text, state]) => {
      const li = document.createElement('li');
      li.dataset.state = state;
      li.append(Object.assign(document.createElement('i'), {}), Object.assign(document.createElement('b'), { textContent: name }),
        Object.assign(document.createElement('span'), { textContent: text }));
      return li;
    }));
    this.renderMcp();
    this.renderBackups();
  }

  renderMcp() {
    const box = this.menu.querySelector('#mcp-rows');
    const servers = this.info?.mcp?.servers || [];
    if (!servers.length) {
      box.replaceChildren(Object.assign(document.createElement('p'), {
        className: 'wm-hint', textContent: 'None connected. Add apps in data/mcp.json (see the README), then press Reload.',
      }));
      return;
    }
    box.replaceChildren(...servers.map((s) => {
      const li = document.createElement('p');
      li.className = `mcp-row ${s.state}`;
      li.textContent = s.state === 'ready' ? `${s.name}: ${s.tools} tools` : s.state === 'starting' ? `${s.name}: starting…` : `${s.name}: ${s.error || 'not working'}`;
      return li;
    }));
  }

  async reloadMcp() {
    try {
      await fetch('/api/mcp/reload', { method: 'POST' });
      this.toast('Reconnecting tools…');
      setTimeout(() => this.poll(), 2500);
    } catch {
      this.toast('Couldn’t reach the server.');
    }
  }

  renderBackups() {
    const box = this.menu.querySelector('#status-backups');
    if (this.backups === null) { box.hidden = true; return; }
    box.hidden = false;
    if (!this.backups.length) { box.replaceChildren(Object.assign(document.createElement('p'), { textContent: 'No backups yet. One is taken every ten minutes while you draw.' })); return; }
    if (box.dataset.shown === String(this.backups.length) && box.children.length) return; // don't rebuild under a finger
    box.dataset.shown = String(this.backups.length);
    box.replaceChildren(...this.backups.map((b) => {
      const row = document.createElement('div');
      const when = new Date(b.time);
      const label = Object.assign(document.createElement('span'), {
        textContent: `${when.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${when.toLocaleTimeString([], TIMES)} · ${b.kb} KB`,
      });
      const btn = Object.assign(document.createElement('button'), { type: 'button', textContent: 'Restore' });
      btn.addEventListener('click', () => {
        if (btn.dataset.sure !== '1') { btn.dataset.sure = '1'; btn.textContent = 'Sure?'; setTimeout(() => { btn.dataset.sure = ''; btn.textContent = 'Restore'; }, 4000); return; }
        this.restore(b.name);
      });
      row.append(label, btn);
      return row;
    }));
  }

  async showBackups() {
    try {
      this.backups = await (await fetch('/api/board/backups')).json();
    } catch {
      this.toast('Couldn’t reach the server for the backups.');
      return;
    }
    this.menu.querySelector('#status-backups').dataset.shown = '';
    this.render();
  }

  async restore(name) {
    try {
      const res = await fetch('/api/board/restore', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
      if (!res.ok) throw new Error(String(res.status));
      this.board.applyData((await res.json()).board);
      this.board.setSaveState('saved');
      this.toast('Backup restored. What was there is saved as a backup too.');
      this.toggle(false);
    } catch {
      this.toast('Couldn’t restore that backup.');
    }
  }

  async showActivity() {
    const modal = document.getElementById('activity-modal');
    const list = document.getElementById('activity-list');
    let rows = [];
    try {
      rows = await (await fetch('/api/activity?limit=150')).json();
    } catch {
      this.toast('Couldn’t reach the server for the log.');
      return;
    }
    list.replaceChildren(...(rows.length ? rows.map((r) => {
      const li = document.createElement('li');
      li.dataset.outcome = r.outcome;
      const when = new Date(r.t);
      li.append(
        Object.assign(document.createElement('time'), { textContent: when.toLocaleTimeString([], TIMES), title: when.toLocaleString() }),
        Object.assign(document.createElement('i'), { textContent: r.private ? '🔒' : '', title: r.private ? 'Private data involved' : '' }),
        Object.assign(document.createElement('b'), { textContent: r.outcome === 'ok' ? r.kind : `${r.kind} (${r.outcome})` }),
        Object.assign(document.createElement('span'), { textContent: r.what }),
      );
      return li;
    }) : [Object.assign(document.createElement('li'), { className: 'empty', textContent: 'Nothing yet. Tools JARVIS uses will appear here.' })]));
    this.toggle(false);
    modal.hidden = false;
  }

  async exportPng() { download(await this.board.exportPng(), `jarvis-board-${stamp()}.png`); }

  exportJson() { download(this.board.exportJson(), `jarvis-board-${stamp()}.json`); }
}
