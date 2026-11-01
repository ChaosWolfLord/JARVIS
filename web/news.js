// The news ticker: headlines scrolling along a thin card. They come from public RSS feeds read by the PC (/api/news), are shown
// as plain text only, and are refreshed every 15 minutes while the card is on the board.

const REFRESH_MS = 15 * 60 * 1000;
const SECONDS_PER_CHAR = 0.085;

export class News {
  constructor({ el }) {
    this.root = el;
    this.track = el.querySelector('#news-track');
    this.foot = el.querySelector('#news-foot');
    this.timer = null;
  }

  onShow() {
    this.refresh();
    this.timer = setInterval(() => this.refresh(), REFRESH_MS);
  }

  onHide() { clearInterval(this.timer); this.timer = null; }

  async refresh() {
    try {
      const res = await fetch('/api/news', { cache: 'no-store' });
      if (!res.ok) throw new Error(String(res.status));
      this.render(await res.json());
    } catch {
      this.foot.textContent = 'Can’t reach the server right now.';
    }
  }

  render({ items, error, updated }) {
    if (!items?.length) {
      this.track.replaceChildren(Object.assign(document.createElement('span'), { className: 'news-none', textContent: error ? `No headlines: ${error}` : 'No headlines right now.' }));
      this.track.style.animation = 'none';
      return;
    }
    const line = items.map((i) => `${i.source} ◆ ${i.title}`).join('      ◆      ');
    const make = () => Object.assign(document.createElement('span'), { className: 'news-run', textContent: `${line}      ◆      ` });
    this.track.replaceChildren(make(), make());                       // the text twice, so the loop has no gap
    this.track.style.animation = `news-scroll ${Math.max(30, Math.round(line.length * SECONDS_PER_CHAR))}s linear infinite`;
    this.foot.textContent = updated ? `Updated ${new Date(updated * 1000).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}` : '';
  }
}
