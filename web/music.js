// The Music widget and spoken music commands. Songs come from YouTube Music and play on your Google Home / Nest speakers
// (over Cast). "Jarvis, play bohemian rhapsody", "pause", "next song", "volume down" are handled on the PC without asking
// the AI, so they are instant and use none of the free request allowance.

const MUSIC_TALK = /^(?:please |can you |could you |hey )?(?:jarvis[ ,]*)?(?:play\b|pause\b|resume\b|unpause\b|continue\b|skip\b|next\b|previous\b|go back\b|louder\b|quieter\b|softer\b|volume\b|turn (?:it|the music|the volume) (?:up|down|off)|stop (?:the )?(?:music|song|playing|playback)|music off|what(?:'s| is) (?:currently |now )?playing|what song is (?:this|that|playing))/i;

export class Music {
  constructor({ el: root, speak, toast }) {
    this.root = root;
    this.now = root.querySelector('#music-now');
    this.foot = root.querySelector('#music-foot');
    this.speak = speak;
    this.toast = toast;
    root.querySelector('#music-form').addEventListener('submit', (e) => {
      e.preventDefault();
      const q = root.querySelector('#music-q');
      if (q.value.trim()) { this.send({ action: 'play', query: q.value.trim() }); q.value = ''; }
    });
    root.querySelectorAll('[data-do]').forEach((b) => b.addEventListener('click', () => this.send({ action: b.dataset.do })));
    root.querySelectorAll('[data-vol]').forEach((b) => b.addEventListener('click', () => this.send({ action: 'volume', direction: b.dataset.vol })));
  }

  onShow() { this.refresh(); }

  onHide() {}

  async call(path, body) {
    const res = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { cache: 'no-store' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail?.[0]?.msg || data.detail || `HTTP ${res.status}`);
    return data;
  }

  async refresh() {
    try { this.render(await this.call('/api/music')); } catch { this.foot.textContent = 'Can’t reach the server right now.'; }
  }

  render(d) {
    const n = d.now || {};
    this.now.textContent = n.title ? `♪ ${n.title}${n.artist ? ` · ${n.artist}` : ''} (${n.device})` : 'Nothing playing yet.';
    this.foot.textContent = d.error || (d.devices?.length ? `Speakers: ${d.devices.map((x) => x.name).join(', ')}` : '');
  }

  async send(command) {
    this.foot.textContent = command.action === 'play' ? 'Finding it…' : '…';
    try {
      const out = await this.call('/api/music/command', command);
      this.render(out);
      if (out.text) this.foot.textContent = out.text;
      if (!out.ok) this.toast(out.text);
    } catch (e) { this.toast(e.message); }
  }

  /** "Jarvis, play …". True means: don't send this to the AI (it was a music command). */
  handleVoice(command) {
    if (!MUSIC_TALK.test(command.trim())) return false;
    this.answer(command);
    return true;
  }

  async answer(command) {
    try {
      const out = await this.call('/api/music/voice', { text: command });
      if (!out.handled) return;
      this.speak(out.text);
      if (!this.root.hidden) this.refresh();
    } catch {
      this.speak('I can’t reach the speakers right now.');
    }
  }
}
