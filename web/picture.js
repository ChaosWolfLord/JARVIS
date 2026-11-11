// The picture card: a real photo on the wall. "Jarvis, show me a picture of a red panda" finds one (Openverse, with the author and
// licence under it), or a photo shared from the phone arrives here. The page only shows what the PC already checked and kept: the address
// is always /api/picture/<id> on this PC, never a web address, so nothing is loaded from the internet by the page itself.

const SAY = /^(?:please |can you |could you |hey )?(?:jarvis[ ,]*)?(?:show|pull up|bring up|put up|display|get|put)\b.{0,24}\b(?:picture|photo|image|pic|photograph)s?\b/i;

export class Picture {
  /** el: the card. speak: says a line out loud. */
  constructor({ el, speak = () => {}, show = () => {} }) {
    this.el = el;
    this.speak = speak;
    this.showCard = show;          // (ev) => put the card on the wall
    this.img = el.querySelector('#picture-img');
    this.title = el.querySelector('#picture-title');
    this.credit = el.querySelector('#picture-credit');
    this.fallback = null;          // (command) => void: asks the AI when the sentence was not a picture to show
  }

  /** The picture event from the PC: {id, src, title, credit}. Only an address of the PC's own picture folder is accepted. */
  show(ev) {
    if (!ev || !/^\/api\/picture\/[0-9a-f]{24}$/.test(String(ev.src || ''))) return false;
    this.img.src = ev.src;
    this.img.alt = String(ev.title || 'Picture');
    this.title.textContent = String(ev.title || 'Picture').toUpperCase();
    this.credit.textContent = String(ev.credit || '');
    return true;
  }

  onShow() {}

  onHide() { this.img.removeAttribute('src'); }        // a hidden card keeps no picture in memory

  /** True means: don't send this to the AI (the PC is looking for the picture, or will hand the sentence back). */
  handleVoice(command) {
    if (!SAY.test(command.trim())) return false;
    this.answer(command);
    return true;
  }

  async answer(command) {
    this.speak('One moment, looking for a picture.');          // a new search can take about ten seconds
    try {
      const res = await fetch('/api/picture/voice', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: command }) });
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
