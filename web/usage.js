// The token-usage widget: how many AI tokens JARVIS has used, with averages per day over weeks, months and years.
// The numbers come from /api/usage, which counts every model call JARVIS makes (from the provider's own counts
// where it gives them, otherwise estimated at about 4 characters a token).

const fmt = (n) => {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e5 ? 0 : 1)}k`;
  return String(n);
};
const RANGES = { daily: 'Last 30 days', weekly: 'Last 12 weeks', monthly: 'Last 12 months', yearly: 'By year' };
const NS = 'http://www.w3.org/2000/svg';

export class Usage {
  constructor({ el }) {
    this.el = el;
    this.range = 'daily';
    this.source = 'claude';  // 'claude' (Claude Code's own logs) or 'jarvis' (this app's AI calls)
    this.measure = 'all';    // Claude Code only: count cache re-reads ('all') or not ('fresh')
    this.data = null;
    this.timer = null;
    try {
      this.source = localStorage.getItem('jarvis.usage.source') === 'jarvis' ? 'jarvis' : 'claude';
      this.measure = localStorage.getItem('jarvis.usage.measure') === 'fresh' ? 'fresh' : 'all';
    } catch { /* not remembered */ }
    el.querySelectorAll('[data-range]').forEach((b) => b.addEventListener('click', () => this.setRange(b.dataset.range)));
    el.querySelectorAll('[data-source]').forEach((b) => b.addEventListener('click', () => this.pick('source', b.dataset.source)));
    el.querySelectorAll('[data-measure]').forEach((b) => b.addEventListener('click', () => this.pick('measure', b.dataset.measure)));
    this.syncButtons();
  }

  // Called by the widgets menu when the card is added or removed.
  onShow() {
    this.refresh();
    this.timer = setInterval(() => this.refresh(), 30_000);
  }

  onHide() {
    clearInterval(this.timer);
    clearTimeout(this.soon);
  }

  pick(what, value) {
    this[what] = value;
    try { localStorage.setItem(`jarvis.usage.${what}`, value); } catch { /* not remembered */ }
    this.syncButtons();
    this.data = null;
    this.refresh();
  }

  syncButtons() {
    this.el.querySelectorAll('[data-source]').forEach((b) => b.classList.toggle('on', b.dataset.source === this.source));
    this.el.querySelectorAll('[data-measure]').forEach((b) => b.classList.toggle('on', b.dataset.measure === this.measure));
    this.el.querySelector('.usage-sources').dataset.source = this.source;
  }

  get visible() { return !this.el.hidden; }

  setRange(range) {
    this.range = range;
    this.el.querySelectorAll('[data-range]').forEach((b) => b.classList.toggle('on', b.dataset.range === range));
    if (this.data) this.render();
  }

  async refresh() {
    const asked = `${this.source}/${this.measure}`;
    try {
      const url = this.source === 'claude' ? `/api/claude-usage?measure=${this.measure}` : '/api/usage';
      const data = await (await fetch(url)).json();
      if (asked !== `${this.source}/${this.measure}`) return; // the tab was switched while this loaded
      this.data = data;
      this.render();
      // The first read of Claude Code's history takes a few seconds: look again soon, then settle back to 30 s.
      clearTimeout(this.soon);
      if (data.scanning && this.visible) this.soon = setTimeout(() => this.refresh(), 3000);
    } catch {
      this.el.querySelector('#usage-foot').textContent = 'Usage numbers unavailable: is the server running?';
    }
  }

  render() {
    const d = this.data;
    const $ = (id) => this.el.querySelector(id);
    // The big number follows the selected tab: today, this week, this month or this year (not all time: that's the last box).
    const now = new Date();
    const dayOfYear = Math.floor((now - new Date(now.getFullYear(), 0, 0)) / 86_400_000);
    const period = {
      daily: { name: 'today', row: d.today, elapsed: 1 },
      weekly: { name: 'this week', row: d.weekly[d.weekly.length - 1], elapsed: ((now.getDay() + 6) % 7) + 1 },
      monthly: { name: 'this month', row: d.monthly[d.monthly.length - 1], elapsed: now.getDate() },
      yearly: { name: 'this year', row: d.yearly[d.yearly.length - 1], elapsed: dayOfYear },
    }[this.range];
    // Don't average over days before the history starts.
    const sinceDays = d.all.since ? Math.floor((now - new Date(`${d.all.since}T00:00:00`)) / 86_400_000) + 1 : 1;
    const days = Math.max(1, Math.min(period.elapsed, sinceDays));
    const noun = this.source === 'claude' ? ['reply', 'replies'] : ['request', 'requests'];
    $('#usage-today').textContent = fmt(period.row.tokens);
    $('#usage-today-sub').textContent = `tokens ${period.name} · ${period.row.requests.toLocaleString()} ${period.row.requests === 1 ? noun[0] : noun[1]}` +
      (this.range === 'daily' ? '' : ` · ${fmt(Math.round(period.row.tokens / days))}/day`);
    $('#avg-all').querySelector('b').textContent = fmt(d.all.tokens);
    $('#avg-all').querySelector('small:last-child').textContent = `${d.all.requests.toLocaleString()} ${noun[1]}`;
    for (const [id, key] of [['#avg-week', 'week'], ['#avg-month', 'month'], ['#avg-year', 'year']]) {
      $(id).querySelector('b').textContent = fmt(d[key].avg_per_day);
      $(id).querySelector('small:last-child').textContent = `per day · ${fmt(d[key].tokens)} total`;
    }
    this.drawChart(d[this.range]);
    $('#usage-range').textContent = RANGES[this.range];
    const top = d.models[0];
    const foot = $('#usage-foot');
    if (this.source === 'claude') {
      foot.textContent = d.scanning && !d.all.requests
        ? 'Reading your Claude Code history for the first time…'
        : d.all.requests
          ? `Claude Code since ${d.all.since}: ${fmt(d.all.tokens)} tokens in ${d.all.requests.toLocaleString()} replies${top ? ` · most used: ${top.name}` : ''}. ` +
            'Not included: claude.ai chats and plan limits.'
          : 'No Claude Code history found on this PC.';
      return;
    }
    const est = d.estimated_share ? ` · about ${Math.round(d.estimated_share * 100)}% of requests estimated` : '';
    foot.textContent = d.all.requests
      ? `JARVIS since ${d.all.since}: ${fmt(d.all.tokens)} tokens in ${d.all.requests} requests${top ? ` · most used: ${top.name.split(':').pop()}` : ''}${est}`
      : 'Nothing counted yet. Ask JARVIS something and the numbers start here.';
  }

  drawChart(series) {
    const host = this.el.querySelector('#usage-chart');
    const W = 560, H = 150, padL = 4, padB = 20, padT = 8;
    const max = Math.max(1, ...series.map((s) => s.tokens));
    const gap = 3;
    const bw = (W - padL) / series.length - gap;
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    series.forEach((s, i) => {
      const h = Math.max(s.tokens ? 2 : 0, ((H - padB - padT) * s.tokens) / max);
      const rect = document.createElementNS(NS, 'rect');
      rect.setAttribute('x', String(padL + i * (bw + gap)));
      rect.setAttribute('y', String(H - padB - h));
      rect.setAttribute('width', String(bw));
      rect.setAttribute('height', String(h));
      rect.setAttribute('rx', '2');
      rect.setAttribute('class', i === series.length - 1 ? 'bar now' : 'bar');
      const tip = document.createElementNS(NS, 'title');
      tip.textContent = `${s.label}: ${s.tokens.toLocaleString()} tokens, ${s.requests} requests`;
      rect.append(tip);
      svg.append(rect);
    });
    const label = (text, x, anchor) => {
      const t = document.createElementNS(NS, 'text');
      t.setAttribute('x', String(x));
      t.setAttribute('y', String(H - 4));
      t.setAttribute('text-anchor', anchor);
      t.textContent = text;
      svg.append(t);
    };
    label(series[0].label, padL, 'start');
    if (series.length > 4) label(series[Math.floor(series.length / 2)].label, W / 2, 'middle');
    label(series[series.length - 1].label, W, 'end');
    const peak = document.createElementNS(NS, 'text');
    peak.setAttribute('x', String(W));
    peak.setAttribute('y', '10');
    peak.setAttribute('text-anchor', 'end');
    peak.textContent = `peak ${fmt(max)}`;
    svg.append(peak);
    host.replaceChildren(svg);
  }
}
