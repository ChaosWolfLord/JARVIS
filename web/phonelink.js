// The "Phone" part of the status menu: where to open JARVIS on your phone (address and QR code), a pairing code that is shown only here,
// which phones are paired, and a button to forget them. The phone page itself is web/phone/ and is served on its own port.

export class PhoneLink {
  constructor({ root, fit }) {
    this.root = root;
    this.fit = fit || (() => {});
    this.info = root.querySelector('#phone-info');
    this.pairBox = root.querySelector('#phone-pair');
    this.qr = root.querySelector('#phone-qr');
    this.code = root.querySelector('#phone-code');
    this.timer = null;
    root.querySelector('#phone-show').addEventListener('click', () => this.showCode());
    root.querySelector('#phone-forget').addEventListener('click', () => this.forget());
    this.extra = root.querySelector('#phone-extra');
    this.findBtn = root.querySelector('#phone-find');
    this.remoteBtn = root.querySelector('#phone-remote');
    this.finding = false;
    this.findBtn.addEventListener('click', () => this.find(!this.finding));
    this.remoteBtn.addEventListener('click', () => this.remote(this.armed ? 'off' : 'on'));
    this.armed = false;
    this.left = 0;
    setInterval(() => this.tick(), 1000);
  }

  say(text) { this.extra.textContent = text; }

  /** "Find my phone": every paired phone that is listening rings (it stays silent if the phone is on silent, unless its owner allowed more). */
  async find(on = true) {
    try {
      const res = await fetch('/api/phone/find', { method: on ? 'POST' : 'DELETE' });
      const d = await res.json();
      this.finding = on && d.sent > 0;
      this.findBtn.textContent = this.finding ? 'Stop ringing' : 'Find my phone';
      if (on) this.say(d.sent ? 'Your phone is ringing. It rings for two minutes or until you stop it here or on the phone.' : 'No phone is listening. On the phone turn on "Alerts when the app is closed" (or open the JARVIS page) and try again.');
      else this.say('');
      return d.sent > 0 ? 'Ringing your phone.' : 'No phone is listening right now. Open JARVIS on it, or turn on alerts when the app is closed.';
    } catch {
      this.say('Could not reach the phone door.');
      return 'I could not reach the phone door.';
    }
  }

  /** The phone as a touchpad, slide clicker and media remote: off until switched on here, for 30 minutes at a time. */
  async remote(what) {
    try {
      const res = await fetch('/api/phone/remote', what === 'on' ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ minutes: 30 }) } : { method: 'DELETE' });
      const d = await res.json();
      if (!res.ok) { this.say(d.detail || 'Could not switch the remote on.'); return; }
      this.armed = d.armed;
      this.left = d.seconds_left;
      this.count = d.commands || 0;
      this.drawRemote();
    } catch {
      this.say('Could not reach JARVIS.');
    }
  }

  tick() {
    if (!this.armed) return;
    this.left = Math.max(0, this.left - 1);
    if (!this.left) this.armed = false;
    if (this.left % 10 === 0) this.recount();
    this.drawRemote();
  }

  /** How many commands the phone has sent since the remote was switched on (so you can see it is being used). */
  async recount() {
    try { this.count = (await (await fetch('/api/phone/remote', { cache: 'no-store' })).json()).commands || 0; } catch { /* keep the old number */ }
  }

  drawRemote() {
    this.remoteBtn.textContent = this.armed ? 'Switch the phone remote off' : 'Let my phone be a remote';
    this.say(this.armed ? `The phone remote is on for ${Math.floor(this.left / 60)}:${String(this.left % 60).padStart(2, '0')} more (the phone has sent ${this.count || 0} commands). On the phone: menu, Remote. It also lets the phone click anywhere on this screen: switch it off when you hand your phone to someone.` : '');
  }

  /** "Jarvis, find my phone": True means the PC is dealing with it (no AI request). */
  handleVoice(command, speak = () => {}) {
    if (!/\b(find|ring|ringing|locate|found|where(?:'s| is| are))\s+(?:my\s+)?(?:phone|mobile)\b/i.test(command)) return false;
    if (/\b(stop|cancel|found)\b/i.test(command)) this.find(false).then(() => speak('Okay, I stopped ringing your phone.'));
    else this.find(true).then((line) => speak(line));
    return true;
  }

  async refresh() {
    try {
      const r = await (await fetch('/api/phone/remote', { cache: 'no-store' })).json();
      this.armed = r.armed;
      this.left = r.seconds_left;
      this.count = r.commands || 0;
      this.drawRemote();
    } catch { /* the phone status below says what is wrong */ }
    try {
      const d = await (await fetch('/api/phone', { cache: 'no-store' })).json();
      this.state = d;
      if (!d.running) {
        this.info.textContent = d.error ? `The phone door isn't running: ${d.error}` : 'The phone door is off (JARVIS_PHONE=0 in .env).';
        this.pairBox.hidden = true;
        return;
      }
      const phones = d.paired.length ? `${d.paired.length} paired: ${d.paired.join(', ')}.` : 'No phone is paired yet.';
      const print = d.fingerprint ? ` The app asks you to compare this fingerprint: ${d.fingerprint}.` : '';
      const app = d.app ? ' The Android app is ready (the phone page offers it while a pairing code is showing).' : ' The Android app has not been built yet (android\\build.bat).';
      this.info.textContent = `On your phone (same Wi-Fi) open ${d.url}. ${phones}${print}${app}`;
    } catch {
      this.info.textContent = 'Could not read the phone status.';
    }
    this.fit();
  }

  async showCode() {
    try {
      const res = await fetch('/api/phone/code', { method: 'POST' });
      const d = await res.json();
      if (!res.ok) { this.info.textContent = d.detail || 'Could not make a code.'; return; }
      this.code.textContent = d.code;
      this.qr.src = `/api/phone/qr.svg?${Date.now()}`;
      this.pairBox.hidden = false;
      clearTimeout(this.timer);
      this.timer = setTimeout(() => { this.pairBox.hidden = true; this.code.textContent = ''; }, d.expires_in * 1000);   // the code is not left on the screen
      this.fit();
    } catch {
      this.info.textContent = 'Could not make a code.';
    }
  }

  async forget() {
    try { await fetch('/api/phone', { method: 'DELETE' }); } catch { /* shown by the refresh below */ }
    this.pairBox.hidden = true;
    this.code.textContent = '';
    this.refresh();
  }
}
