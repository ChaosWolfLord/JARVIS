// The picture card: a real photo on the wall. "Jarvis, show me a picture of a red panda" finds one (Openverse, with the author and
// licence under it), or a photo shared from the phone arrives here. The page only shows what the PC already checked and kept: the address
// is always /api/picture/<id> on this PC, never a web address, so nothing is loaded from the internet by the page itself.

const SAY = /^(?:please |can you |could you |hey )?(?:jarvis[ ,]*)?(?:show|pull up|bring up|put up|display|get|put)\b.{0,24}\b(?:picture|photo|image|pic|photograph)s?\b/i;

// The card takes the shape of the photo: the photo is scaled to fit inside a box 640 wide and 800 tall (in the wall's 1920 x 1080 pixels), so a
// landscape photo stays about the size it always was and a portrait one is much taller. Very long panoramas keep at least MIN pixels of height.
const BOX_W = 640;
const BOX_H = 800;
const MIN = 200;
const CHROME_W = 28;                                       // the card's padding either side of the photo

/** The size of the frame for a photo of this size: its own shape, as large as the box allows. */
export function frameSize(width, height) {
  if (!(width > 0) || !(height > 0)) return null;
  const scale = Math.min(BOX_W / width, BOX_H / height);
  return { w: Math.round(Math.max(MIN, width * scale)), h: Math.round(Math.max(MIN, height * scale)) };
}

export class Picture {
  /** el: the card. speak: says a line out loud. */
  constructor({ el, speak = () => {}, show = () => {} }) {
    this.el = el;
    this.frame = el.querySelector('#picture-frame');
    this.fit = null;                                       // () => void: keeps the resized card on the wall (set by the page)
    this.speak = speak;
    this.showCard = show;          // (ev) => put the card on the wall
    this.img = el.querySelector('#picture-img');
    this.title = el.querySelector('#picture-title');
    this.credit = el.querySelector('#picture-credit');
    this.fallback = null;          // (command) => void: asks the AI when the sentence was not a picture to show
    this.img?.addEventListener?.('load', () => this.resize());
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

  /** The photo has loaded: the frame and the card take its shape. */
  resize() {
    const size = frameSize(this.img.naturalWidth, this.img.naturalHeight);
    if (!size || !this.frame) return;
    this.frame.style.width = `${size.w}px`;
    this.frame.style.height = `${size.h}px`;
    this.el.style.width = `${size.w + CHROME_W}px`;
    this.fit?.();
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
