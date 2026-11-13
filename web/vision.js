// It sees (the PC's webcam): "Jarvis, what is this?", "what am I holding?", "read this", "what do you see?". Only when you ask: the camera is opened for
// about a second, one picture is taken, the camera is closed again, and the picture goes to the PC (which asks an AI model that can see) and is not
// saved. Which camera, and whether looking is allowed at all, are in the status menu under Vision.

const KEY = 'jarvis.vision';
const FRAME_WIDTH = 1280;
const WARM_UP_MS = 700;                                    // a webcam needs a moment to settle its exposure

const START = String.raw`^(?:please |can you |could you |hey )?(?:jarvis[ ,]*)?`;
const NOT_THESE = String.raw`(?! (?:song|music|track|album|artist|movie|show|word|place|time|date|day|page|called|about|mean|means|for|doing))`;
const LOOKS = [
  String.raw`what(?:'s| is| are)(?: this| that| these| those)\b${NOT_THESE}`,
  String.raw`what (?:am i|are you) (?:holding|looking at|seeing|wearing)`,
  String.raw`what(?:'s| is) (?:in my hand|in front of me|on my desk)`,
  String.raw`what do you see`,
  String.raw`(?:can|could) you see (?:this|that|me|it)`,
  String.raw`look at (?:this|that|it|these|me)`,
  String.raw`take a look`,
  String.raw`read (?:this|that|it|me this)`,
  String.raw`what does (?:this|that|it) say`,
  String.raw`what colou?r is (?:this|that|it)`,
  String.raw`how many [a-z ]{1,30} (?:do you see|can you see|am i holding)`,
  String.raw`(?:describe|identify|translate) (?:this|that|what you see|what i(?:'m| am) holding)`,
  String.raw`tell me about (?:this|that) (?:thing|object|plant|bug|item)`,
].map((p) => new RegExp(`${START}${p}`, 'i'));

/** Is this sentence asking JARVIS to look through the camera? */
export function isLookRequest(text) {
  const t = String(text || '').trim().replace(/[^\w' ?]/g, ' ').replace(/\s+/g, ' ');
  return LOOKS.some((re) => re.test(t));
}

/** What went wrong with the camera, in words you can act on. */
export function cameraProblem(error) {
  const name = error?.name || '';
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'The camera is blocked. Allow it in the browser’s address bar, then ask again.';
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return 'I can’t find that camera. Choose another one in the status menu, under Vision.';
  if (name === 'NotReadableError' || name === 'AbortError') return 'That camera is busy (the pen tracker may be using it). Choose another camera in the status menu, under Vision.';
  return 'I couldn’t use the camera.';
}

export class Vision {
  /** root: the status menu. speak: says a line. show: puts text in the speech bubble. */
  constructor({ root, speak = () => {}, show = () => {}, busy = () => false }) {
    this.speak = speak;
    this.show = show;
    this.busy = busy;
    this.settings = { on: true, device: '' };
    try { Object.assign(this.settings, JSON.parse(localStorage.getItem(KEY)) || {}); } catch { /* the defaults */ }
    this.working = false;
    this.fallback = null;                                  // (command) => void: asks the AI when the sentence was not about the camera
    this.on = root?.querySelector('#vision-on');
    this.pick = root?.querySelector('#vision-device');
    this.note = root?.querySelector('#vision-note');
    if (this.on) {
      this.on.checked = this.settings.on;
      this.on.addEventListener('change', () => this.save({ on: this.on.checked }));
      this.pick.addEventListener('change', () => this.save({ device: this.pick.value }));
      root.querySelector('#vision-test').addEventListener('click', () => this.look('What do you see? Describe it in a sentence or two.'));
      root.querySelector('#vision-find').addEventListener('click', () => this.cameras(true));
    }
  }

  save(changes) {
    Object.assign(this.settings, changes);
    try { localStorage.setItem(KEY, JSON.stringify(this.settings)); } catch { /* not remembered */ }
  }

  say(text) { if (this.note) this.note.textContent = text; }

  /** Fills the camera list. Names only appear once the browser has allowed the camera, so "Find cameras" asks for it once. */
  async cameras(ask = false) {
    if (!this.pick || !navigator.mediaDevices?.enumerateDevices) return;
    try {
      if (ask) (await navigator.mediaDevices.getUserMedia({ video: true })).getTracks().forEach((t) => t.stop());
      const found = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'videoinput');
      this.pick.replaceChildren(Object.assign(document.createElement('option'), { value: '', textContent: 'The browser’s default camera' }));
      found.forEach((d, i) => this.pick.append(Object.assign(document.createElement('option'), { value: d.deviceId, textContent: d.label || `Camera ${i + 1}` })));
      this.pick.value = found.some((d) => d.deviceId === this.settings.device) ? this.settings.device : '';
      this.say(found.length ? `${found.length} camera${found.length === 1 ? '' : 's'} found.` : 'No camera found on this PC.');
    } catch (e) {
      this.say(cameraProblem(e));
    }
  }

  /** One picture from the chosen camera, as a JPEG. The camera is closed again straight away. */
  async frame() {
    if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error('no camera API'), { name: 'NotFoundError' });
    const video = { width: { ideal: FRAME_WIDTH }, height: { ideal: 720 } };
    if (this.settings.device) video.deviceId = { exact: this.settings.device };
    const stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    try {
      const v = document.createElement('video');
      v.muted = true;
      v.playsInline = true;
      v.srcObject = stream;
      await v.play();
      await new Promise((r) => setTimeout(r, WARM_UP_MS));
      if (!v.videoWidth) throw Object.assign(new Error('no picture'), { name: 'NotReadableError' });
      const scale = Math.min(1, FRAME_WIDTH / v.videoWidth);
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(v.videoWidth * scale);
      canvas.height = Math.round(v.videoHeight * scale);
      canvas.getContext('2d').drawImage(v, 0, 0, canvas.width, canvas.height);
      return await new Promise((res, rej) => canvas.toBlob((b) => (b ? res(b) : rej(new Error('no picture'))), 'image/jpeg', 0.85));
    } finally {
      stream.getTracks().forEach((t) => t.stop());                // the camera light goes off
    }
  }

  /** Looks and answers: the answer is spoken and shown. Never more than one look at a time. */
  async look(question) {
    if (this.working) return;
    if (!this.settings.on) { this.tell('Looking through the camera is switched off. You can turn it on in the status menu, under Vision.'); return; }
    this.working = true;
    this.show('Looking…');
    try {
      const picture = await this.frame();
      const res = await fetch(`/api/look?question=${encodeURIComponent(String(question || '').slice(0, 300))}`, { method: 'POST', headers: { 'Content-Type': 'image/jpeg' }, body: picture });
      const out = await res.json().catch(() => ({}));
      if (!res.ok) { this.tell(out.detail || 'I couldn’t look just now.'); return; }
      this.tell(out.text);
      this.cameras();                                             // the names are known now
    } catch (e) {
      this.tell(cameraProblem(e));
    } finally {
      this.working = false;
    }
  }

  tell(text) {
    this.show(text);
    this.speak(text);
    this.say(text);
  }

  /** True means: don't send this to the AI (JARVIS is looking). */
  handleVoice(command) {
    if (!isLookRequest(command)) return false;
    this.look(command);
    return true;
  }
}
