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
  }

  async refresh() {
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
