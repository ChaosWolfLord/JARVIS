// The Camera card: a live view on the wall from this PC's webcam or from your phone's camera.
//   "Jarvis, show the webcam" / "show my camera"      this PC's camera, opened by this page (the picture never leaves it)
//   "Jarvis, show the phone camera"                   the phone's camera. Only the phone can start it: you tap "Show my camera on the wall" in the app
//                                                     (the PC sends the phone a notification to tap); the card then fills with the live picture
//   "Jarvis, stop the camera"                         closes whichever is showing (the phone is told to shut its camera)
// Nothing is recorded or saved, and nothing goes to an AI: a live view is only shown. The privacy screen closes it. See server/livecam.py.

import { cameraProblem } from './vision.js';

const VISION_KEY = 'jarvis.vision';                      // the camera chosen in the Vision section is used here too
const POLL_SECONDS = 2;
const GONE_AFTER_MS = 6000;

const normalize = (text) => String(text || '').toLowerCase().replace(/['’]/g, '').replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();
const LEAD = /^(?:(?:please|hey|ok|okay) )*(?:jarvis )?(?:(?:please|can you|could you) )*/;
const NOUN = String.raw`(?:camera feed|live feed|live view|web ?cam|camera|cam|feed|view|video)`;
const WHICH = String.raw`(?:(pc|phone|phones|computer|laptop|desk|room|web) )?`;

/** What a sentence asks of the live camera: {op: 'pc' | 'phone' | 'stop'} or null when it is about something else ("what do you see" is Vision, "open camera" is the app). */
export function parseCameraCommand(text) {
  const t = normalize(text).replace(LEAD, '').trim();
  let m = new RegExp(`^(?:stop|close|hide|turn off|switch off|end|shut)(?: the| my)? ?(?:live )?${WHICH}${NOUN}(?: feed| view)?$`).exec(t);
  if (m) return { op: 'stop' };
  m = new RegExp(`^(show me|show|open|turn on|start|bring up|pull up|put up|display|let me see|can i see)(?: the| my| a)? ?(live )?${WHICH}(${NOUN})(?: feed| view)?(?: of (?:the |my )?(?:room|desk))?$`).exec(t);
  if (!m) return null;
  const [, verb, live, which, noun] = m;
  if (/^(?:open|start|turn on)$/.test(verb) && noun === 'camera' && !live && !which) return null;      // plain "open camera" is the Windows Camera app
  return { op: /^phones?$/.test(which || '') ? 'phone' : 'pc' };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class LiveCamera {
  /** el: the card. open/close: put the card on the wall or take it off. speak: says a line. */
  constructor({ el, open = () => {}, close = () => {}, speak = () => {} }) {
    this.el = el;
    this.open = open;
    this.close = close;
    this.speak = speak;
    this.video = el.querySelector('#camera-video');
    this.img = el.querySelector('#camera-phone');
    this.empty = el.querySelector('#camera-empty');
    this.foot = el.querySelector('#camera-foot');
    this.source = '';
    this.stream = null;
    this.token = 0;                                         // which showing is current: an old one that is still finishing must not touch the card
    this.frameUrl = '';
    this.lastFrame = 0;
    el.querySelectorAll?.('[data-cam]').forEach((b) => b.addEventListener('click', () => {
      const what = b.dataset.cam;
      if (what === 'pc') this.showPC(); else if (what === 'phone') this.showPhone(); else this.stop();
    }));
  }

  say(text) { if (this.foot) this.foot.textContent = text || ''; }

  message(text) {
    if (!this.empty) return;
    this.empty.textContent = text || '';
    this.empty.hidden = !text;
  }

  get locked() { return Boolean(globalThis.jarvis?.privacy?.locked); }

  settings() {
    try { return JSON.parse(localStorage.getItem(VISION_KEY)) || {}; } catch { return {}; }
  }

  /** Lets go of whatever is showing (the PC's camera light goes off) without closing the card. */
  release() {
    this.token += 1;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    if (this.video) { this.video.srcObject = null; this.video.hidden = true; }
    if (this.img) { this.img.hidden = true; this.img.removeAttribute('src'); }
    if (this.frameUrl) { URL.revokeObjectURL(this.frameUrl); this.frameUrl = ''; }
    this.lastFrame = 0;
  }

  /** This PC's camera, live. */
  async showPC() {
    if (this.locked) return;
    const was = this.source;
    this.release();
    if (was === 'phone') fetch('/api/camera/stop', { method: 'POST' }).catch(() => {});
    this.source = 'pc';
    const mine = this.token;
    this.open();
    this.message('Opening the camera…');
    this.say('');
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw Object.assign(new Error('no camera API'), { name: 'NotFoundError' });
      const video = { width: { ideal: 1280 }, height: { ideal: 720 } };
      const device = this.settings().device;
      if (device) video.deviceId = { exact: device };
      const stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
      if (mine !== this.token) { stream.getTracks().forEach((t) => t.stop()); return; }          // something else was chosen while this was opening
      this.stream = stream;
      this.video.srcObject = stream;
      this.video.hidden = false;
      this.video.play().catch(() => {});                       // not waited for: it only finishes once the first picture arrives
      this.message('');
      this.say('This PC’s camera: live. Nothing is recorded.');
    } catch (e) {
      if (mine !== this.token) return;
      this.message(cameraProblem(e));
    }
  }

  /** The phone's live camera. The PC cannot start it, so this waits for the phone (and sends it a notification to tap). */
  async showPhone(asked = true) {
    if (this.locked) return;
    const was = this.source;
    this.release();
    this.source = 'phone';
    const mine = this.token;
    this.open();
    this.img.hidden = false;
    this.message('Waiting for your phone. Open JARVIS on it and tap “Show my camera on the wall”.');
    this.say('');
    if (asked) fetch('/api/camera/ask', { method: 'POST' }).catch(() => {});
    let after = 0;
    let had = false;
    while (mine === this.token) {
      if (this.locked) { this.stop(); return; }
      try {
        const res = await fetch(`/api/camera/frame?after=${after}&wait=${POLL_SECONDS}`, { cache: 'no-store' });
        if (mine !== this.token) return;
        if (res.status === 423) { this.stop(); return; }
        after = Number(res.headers.get('X-Seq')) || after;
        if (res.status === 200) {
          const url = URL.createObjectURL(await res.blob());
          if (mine !== this.token) { URL.revokeObjectURL(url); return; }
          this.img.src = url;
          if (this.frameUrl) URL.revokeObjectURL(this.frameUrl);
          this.frameUrl = url;
          this.lastFrame = Date.now();
          if (!had) { had = true; this.message(''); this.say('Phone camera: live. Nothing is recorded.'); }
        } else {
          await sleep(200);                                      // nothing yet: the PC waits a couple of seconds, but never spin if it answers at once
          if (had && Date.now() - this.lastFrame > GONE_AFTER_MS) {
            had = false;
            this.message('The phone camera stopped. Tap Phone to wait for it again.');
            this.say('');
          }
        }
      } catch {
        await sleep(1000);
      }
    }
  }

  /** Closes the card and whatever it shows. The phone is told to shut its camera. */
  stop() {
    const was = this.source;
    this.release();
    this.source = '';
    this.message('');
    this.say('');
    if (was === 'phone') fetch('/api/camera/stop', { method: 'POST' }).catch(() => {});
    this.close();
  }

  /** The PC says the phone started or stopped showing its camera: show it as soon as it starts. */
  onEvent(ev) {
    if (!ev || ev.source !== 'phone') return;
    if (ev.state === 'on' && this.source !== 'phone' && !this.locked) this.showPhone(false);
    if (ev.state === 'off' && this.source === 'phone') {
      this.release();
      this.img.hidden = true;
      this.message('The phone camera stopped.');
      setTimeout(() => { if (this.source === 'phone' && !this.lastFrame) this.stop(); }, 4000);
    }
  }

  /** True means: this sentence was about the live camera. */
  handleVoice(command) {
    const cmd = parseCameraCommand(command);
    if (!cmd) return false;
    if (this.locked) return true;
    if (cmd.op === 'stop') {
      if (this.source) { this.stop(); this.speak('Camera closed.'); } else this.speak('The camera isn’t showing.');
    } else if (cmd.op === 'phone') {
      this.showPhone(true);
      this.speak('Waiting for your phone. Tap Show my camera on the wall in the app.');
    } else {
      this.showPC();
    }
    return true;
  }
}
