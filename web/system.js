// The System widget: how the PC and JARVIS are doing. Numbers come from /api/system, which the server refreshes every few
// seconds in the background; while the card is on the board this asks for them every 5 seconds.
//
// Also "Jarvis, how's the system?": answered on the page from the same numbers, so it costs no AI request.

const REFRESH_MS = 5000;
const ASK = /^(?:(?:how(?:'s| is| are)|what(?:'s| is)) (?:the |my |our )?(?:system|computer|pc|machine)(?: doing| status| health| looking| running)?|(?:is|are) (?:the |my )?(?:system|computer|pc) (?:ok|okay|fine|healthy|alright)|(?:system|computer|pc) (?:status|check|health|diagnostics?)|(?:run|do) (?:a |the )?(?:system )?(?:check|diagnostics?|health check))\??$/i;

const el = (tag, cls, text) => Object.assign(document.createElement(tag), { className: cls || '', textContent: text ?? '' });

function spark(points, key, color) {
  const w = 220, h = 34;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
  svg.setAttribute('class', 'sys-spark');
  if (points.length < 2) return svg;
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  path.setAttribute('points', points.map((p, i) => `${(i / (points.length - 1) * w).toFixed(1)},${(h - 2 - (Math.min(100, p[key]) / 100) * (h - 4)).toFixed(1)}`).join(' '));
  path.setAttribute('fill', 'none');
  path.setAttribute('stroke', color);
  path.setAttribute('stroke-width', '1.5');
  svg.append(path);
  return svg;
}

function meter(label, pct, detail, history, key) {
  const row = el('div', 'sys-meter');
  const level = pct >= 90 ? 'hot' : pct >= 75 ? 'warm' : '';
  const bar = el('i', `sys-bar ${level}`);
  bar.style.setProperty('--p', `${Math.max(0, Math.min(100, pct))}%`);
  row.append(el('b', '', label), bar, el('span', '', detail));
  if (history) row.append(spark(history, key, level === 'hot' ? 'var(--red)' : level === 'warm' ? 'var(--amber)' : 'var(--cyan)'));
  return row;
}

export class System {
  constructor({ el: root, speak, show }) {
    this.root = root;
    this.body = root.querySelector('#system-body');
    this.foot = root.querySelector('#system-foot');
    this.speak = speak;
    this.show = show;
    this.timer = null;
    this.latest = null;
  }

  onShow() {
    this.refresh();
    this.timer = setInterval(() => this.refresh(), REFRESH_MS);
  }

  onHide() { clearInterval(this.timer); this.timer = null; }

  async fetchSnapshot() {
    const res = await fetch('/api/system', { cache: 'no-store' });
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  }

  async refresh() {
    try {
      this.latest = await this.fetchSnapshot();
      this.render(this.latest);
    } catch {
      this.foot.textContent = 'Can’t reach the server right now.';
    }
  }

  render(s) {
    if (s.cpu == null) { this.body.replaceChildren(el('p', 'sys-note', 'Taking the first measurements…')); return; }
    const rows = [];
    const alerts = s.alerts || [];
    rows.push(alerts.length
      ? el('p', 'sys-alerts', alerts.map((a) => `⚠ ${a.title}`).join('  ·  '))
      : el('p', 'sys-ok', '● All systems normal'));
    rows.push(meter('CPU', s.cpu, `${Math.round(s.cpu)}%`, s.history, 'cpu'));
    const m = s.mem || {};
    rows.push(meter('RAM', m.pct || 0, `${m.used_gb ?? '?'} / ${m.total_gb ?? '?'} GB`, s.history, 'mem'));
    for (const d of s.disks || []) rows.push(meter(d.drive, 100 - d.free_pct, `${Math.round(d.free_gb)} GB free`));
    const n = s.net;
    if (n) {
      rows.push(el('p', 'sys-line', `${n.internet ? `Internet up · ${n.ms} ms` : 'Internet DOWN'}${n.dns ? '' : ' · DNS failing'}${n.wifi ? ` · Wi-Fi ${n.wifi.signal}% (${n.wifi.ssid})` : ''}`));
    }
    const j = s.jarvis || {};
    const bits = [];
    if (j.wake_configured) bits.push(j.wake_running ? 'wake word on' : 'wake word OFF');
    if (j.free_requests != null) bits.push(`${j.free_requests} free AI requests left`);
    if (j.tracker_expected) bits.push(j.tracker_connected ? 'tracker connected' : 'tracker OFF');
    rows.push(el('p', 'sys-line', `JARVIS · ${bits.join(' · ') || 'running'}`));
    const sec = s.slow;
    if (sec?.defender) rows.push(el('p', 'sys-line', `Security · antivirus ${sec.defender.realtime ? 'on' : 'OFF'} · ${sec.errors_24h?.count ?? 0} Windows errors today`));
    this.body.replaceChildren(...rows);
    this.foot.textContent = s.uptime_h != null ? `PC on for ${s.uptime_h < 48 ? `${Math.round(s.uptime_h)} hours` : `${Math.round(s.uptime_h / 24)} days`}` : '';
  }

  /** "Jarvis, how's the system?" Returns true when the command was one of these (so the AI isn't asked). */
  handleVoice(command) {
    if (!ASK.test(command.trim().replace(/^jarvis\b\W*/i, '').replace(/[.!]+$/, ''))) return false;
    this.answer();
    return true;
  }

  async answer() {
    try {
      const res = await fetch('/api/system/summary', { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      const { text } = await res.json();
      this.show(`<p>${Object.assign(document.createElement('div'), { textContent: text }).innerHTML}</p>`, 25_000);
      this.speak(text);
    } catch {
      this.speak('I can’t reach my system monitor right now.');
    }
  }
}
