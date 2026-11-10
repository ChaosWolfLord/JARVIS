// The status panel (on the left; it can be open next to the chat): one plain answer at the top ("Everything is working" or what needs a
// look), the checks below it grouped as needs attention / working / not in use, each with what to do about it, and the settings in
// sections you open when you want them. Also the board's export and backup tools, and the banner that shows when the server stops.


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

    this.phone = null;   // what /api/phone said last, read while the panel is open
    this.expanded = new Set();   // which of the quieter groups (Working, Not in use) are opened; what needs attention is always shown
    button.addEventListener('click', () => this.toggle());
    menu.querySelector('#status-close').addEventListener('click', () => this.toggle(false));
    menu.querySelectorAll('[data-do]').forEach((b) => b.addEventListener('click', () => this.quick(b.dataset.do)));
    // It is a panel like the chat, not a pop-up: it stays open while you draw or talk, and closes with its button, its ×, S or Esc.
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !this.menu.hidden && !e.target.closest('input, textarea, select')) this.toggle(false); });
    board.onSaveState = () => this.render();
    this.poll();
    setInterval(() => this.poll(), POLL_MS);
    setInterval(() => { if (!this.menu.hidden) this.render(); }, 1000);
    setInterval(() => { if (!this.menu.hidden) this.loadPhone(); }, 15000);
  }

  async loadPhone() {
    try { this.phone = await (await fetch('/api/phone', { cache: 'no-store' })).json(); } catch { this.phone = null; }
    this.render();
  }

  /** The three quick actions at the top of the panel. */
  quick(what) {
    if (what === 'lock') document.getElementById('privacy-lock').click();
    else if (what === 'picture') document.getElementById('export-png').click();
    else if (what === 'pair') this.openPair();
  }

  openPair() {
    const section = this.menu.querySelector('#sec-phone');
    section.open = true;
    document.getElementById('phone-show').click();
    section.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
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
    this.button.setAttribute('aria-expanded', String(open));
    document.body.classList.toggle('status-open', open);
    if (open) { this.backups = null; this.render(); this.loadPhone(); this.onOpen?.(); }
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
    const rows = this.checks();
    this.renderSummary(rows);
    this.renderRows(rows);
    this.renderMcp();
    this.renderBackups();
  }

  /** Every check as {name, text, state: ok|warn|down|idle, hint, act}. */
  checks() {
    const i = this.info || {};
    const up = this.up;
    const rows = [];
    const since = i.started ? new Date(i.started * 1000).toLocaleTimeString([], TIMES) : '';
    rows.push({ name: 'JARVIS', state: up === false ? 'down' : up ? 'ok' : 'warn', text: up === false ? 'Not running' : up ? `Running${since ? ` since ${since}` : ''}` : 'Checking…',
      hint: up === false ? 'Start it with JARVIS.bat on the PC. Your drawing is safe in this browser until it is back.' : '' });

    const left = i.openrouter ? Math.max(0, i.openrouter.limit - i.openrouter.used_today) : null;
    rows.push({ name: 'AI', state: !up ? 'warn' : i.key_set ? 'ok' : 'warn',
      text: !up ? 'Waiting for JARVIS' : !i.key_set ? 'No API key' : `${i.model || 'Ready'} · ${left != null ? `about ${left} free requests left today` : `${i.requests_today} requests today`}`,
      hint: up && !i.key_set ? `Add ${i.key_env || 'an API key'} to the .env file, then restart JARVIS.` : '' });

    if (!this.voice.supported) rows.push({ name: 'Voice', state: 'warn', text: 'Needs Chrome or Edge', hint: 'Open JARVIS in Chrome or Edge to talk to it. You can still type.' });
    else if (this.voice.enabled) rows.push({ name: 'Voice', state: 'ok', text: 'Listening for “Jarvis”' });
    else rows.push({ name: 'Voice', state: 'idle', text: 'Off', act: { label: 'Turn on', run: () => this.voice.toggle() } });

    const w = i.wake || {};
    if (w.running) rows.push({ name: 'Wake word', state: 'ok', text: `Hears “Jarvis” on this PC${w.device ? ` · ${w.device.trim().replace(/\s*\($/, '')}` : ''}` });
    else if (w.error) rows.push({ name: 'Wake word', state: 'warn', text: 'Not running', hint: w.error });

    const ph = this.phone;
    if (ph?.running) rows.push({ name: 'Phone', state: 'ok', text: ph.paired.length ? `${ph.paired.length} paired` : 'Ready, none paired yet', act: { label: 'Pair a phone', run: () => this.openPair() } });
    else if (ph) rows.push({ name: 'Phone', state: 'idle', text: 'Off', hint: ph.error || '' });

    if (i.lights) rows.push({ name: 'Lights', state: 'ok', text: `${i.lights} set up` });
    if (i.speakers) rows.push({ name: 'Speakers', state: 'ok', text: `${i.speakers} found` });

    rows.push({ name: 'Pen tracker', state: this.pen.trackerUp ? 'ok' : 'idle', text: this.pen.trackerUp ? `Connected${this.pen.camera ? ` (${this.pen.camera})` : ''}` : 'Not running',
      hint: this.pen.trackerUp ? '' : 'Start run_tracker.bat to draw with the pen on the wall.' });
    rows.push({ name: 'This PC', state: !up ? 'idle' : i.alerts ? 'warn' : 'ok', text: !up ? '—' : i.alerts ? `${i.alerts} problem${i.alerts > 1 ? 's' : ''} found` : 'No problems found',
      hint: i.alerts ? 'The red notes on the board say what.' : '' });

    const saved = { saving: 'Saving…', offline: 'Not saved to the PC (server offline)' }[this.board.saveState]
      || (this.board.lastSaved ? `Saved ${new Date(this.board.lastSaved).toLocaleTimeString([], TIMES)}` : 'Nothing to save yet');
    rows.push({ name: 'Board', state: this.board.saveState === 'offline' ? 'warn' : 'ok', text: saved, hint: this.board.saveState === 'offline' ? 'It is kept in this browser and is saved to the PC as soon as JARVIS is back.' : '' });
    return rows;
  }

  /** The headline: one sentence that answers "is everything OK?". */
  renderSummary(rows) {
    const bad = rows.filter((r) => r.state === 'warn' || r.state === 'down');
    const box = this.menu.querySelector('#sd-summary');
    const i = this.info || {};
    let level = 'ok', headline, sub;
    if (this.up === false) { level = 'down'; headline = 'JARVIS isn’t running'; sub = 'Start it with JARVIS.bat. Your drawing is safe.'; }
    else if (this.up === null) { level = 'warn'; headline = 'Checking…'; sub = ''; }
    else if (bad.length) { level = 'warn'; headline = bad.length === 1 ? '1 thing to look at' : `${bad.length} things to look at`; sub = bad.map((r) => r.name).join(', '); }
    else { headline = 'Everything is working'; sub = i.model ? `${i.model} · ${i.requests_today} requests today` : ''; }
    box.dataset.level = level;
    this.menu.querySelector('#sd-headline').textContent = headline;
    this.menu.querySelector('#sd-sub').textContent = sub;
  }

  renderRows(rows) {
    const groups = [['Needs attention', rows.filter((r) => r.state === 'warn' || r.state === 'down')],
      ['Working', rows.filter((r) => r.state === 'ok')], ['Not in use', rows.filter((r) => r.state === 'idle')]];
    const list = this.menu.querySelector('#status-rows');
    const items = [];
    for (const [title, group] of groups) {
      if (!group.length) continue;
      const quiet = title !== 'Needs attention';
      const open = !quiet || this.expanded.has(title);
      const head = Object.assign(document.createElement(quiet ? 'li' : 'li'), { className: `sd-group${quiet ? ' toggle' : ''}`, textContent: quiet ? `${title} · ${group.length}` : title });
      if (quiet) {
        head.tabIndex = 0;
        head.setAttribute('role', 'button');
        head.setAttribute('aria-expanded', String(open));
        const flip = () => { if (this.expanded.has(title)) this.expanded.delete(title); else this.expanded.add(title); this.render(); };
        head.addEventListener('click', flip);
        head.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); } });
      }
      items.push(head);
      if (!open) continue;
      for (const r of group) {
        const li = document.createElement('li');
        li.dataset.state = r.state;
        const text = document.createElement('div');
        text.append(Object.assign(document.createElement('b'), { textContent: r.name }), Object.assign(document.createElement('span'), { textContent: r.text }));
        if (r.hint) text.append(Object.assign(document.createElement('em'), { textContent: r.hint }));
        li.append(document.createElement('i'), text);
        if (r.act) {
          const btn = Object.assign(document.createElement('button'), { type: 'button', textContent: r.act.label, className: 'sd-act' });
          btn.addEventListener('click', r.act.run);
          li.append(btn);
        }
        items.push(li);
      }
    }
    list.replaceChildren(...items);
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
