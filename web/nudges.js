// JARVIS speaks first: the "Speaks first" section of the status menu, and what the wall does when the PC sends a heads-up (a calendar event about to
// start, new important mail). The PC decides what to say and when (server/nudges.py); this page shows it in the speech bubble and says it out loud when
// nothing else is being said. Settings live on the PC.

const PREFILTER = /\b(?:interrupt\w*|nudg\w*|heads ?ups?|disturb\w*)\b|\b(?:quiet|silent)\b.*\b(?:hours?|hrs?|minutes?|mins?|today|tonight)\b/i;   // a bare \"be quiet\" is left alone
const WAIT_MS = 3000;
const GIVE_UP_MS = 2 * 60 * 1000;

const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined }).then((r) => r.json());

export class Nudges {
  /** root: the status menu. busy: is JARVIS talking or thinking? speak/show: say it / put it in the bubble. */
  constructor({ root, busy = () => false, speak = () => {}, show = () => {} }) {
    this.busy = busy;
    this.speak = speak;
    this.show = show;
    this.fallback = null;                                    // (command) => void: asks the AI when the sentence was not about heads-ups
    const q = (id) => root?.querySelector(id);
    this.f = { enabled: q('#nudge-on'), calendar: q('#nudge-calendar'), minutes: q('#nudge-minutes'), mail: q('#nudge-mail'), speak: q('#nudge-speak'),
      phone: q('#nudge-phone'), quiet_from: q('#nudge-from'), quiet_to: q('#nudge-to') };
    this.note = q('#nudge-note');
    if (!this.f.enabled) return;
    for (const [key, input] of Object.entries(this.f)) {
      input.addEventListener('change', () => {
        const value = input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
        if (input.type !== 'checkbox' && !input.value) return;
        post('/api/nudges', { [key]: value }).then((s) => this.fill(s)).catch(() => this.say('Could not save that.'));
      });
    }
    q('#nudge-hour').addEventListener('click', () => post('/api/nudges/snooze?minutes=60').then((s) => this.fill(s)).catch(() => {}));
    q('#nudge-resume').addEventListener('click', () => post('/api/nudges/snooze?minutes=0').then((s) => this.fill(s)).catch(() => {}));
  }

  say(text) { if (this.note) this.note.textContent = text; }

  fill(s) {
    if (!this.f.enabled || !s) return;
    for (const [key, input] of Object.entries(this.f)) {
      if (input.type === 'checkbox') input.checked = Boolean(s[key]);
      else input.value = s[key];
    }
    const until = s.snoozed ? new Date(s.snooze_until * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    this.say(!s.google ? 'Google is not connected, so there is nothing to look at yet.' : s.snoozed ? `Quiet until ${until}.` : s.error ? `Last check failed: ${s.error}` : '');
  }

  refresh() { return fetch('/api/nudges').then((r) => r.json()).then((s) => this.fill(s)).catch(() => {}); }

  /** The PC has something to say: show it now, and say it as soon as JARVIS is not already talking (but never wait more than two minutes). */
  deliver(m) {
    const text = String(m?.text || '').slice(0, 300);
    if (!text) return;
    this.show(text);
    if (!m.speak) return;
    const started = Date.now();
    const tryToSpeak = () => {
      if (!this.busy()) { this.speak(text); return; }
      if (Date.now() - started < GIVE_UP_MS) setTimeout(tryToSpeak, WAIT_MS);
    };
    tryToSpeak();
  }

  /** "Don't interrupt me for an hour": the PC decides whether that is what it was. True means: handled here. */
  handleVoice(command) {
    if (!PREFILTER.test(command) || !/^\W*(?:(?:please|hey|ok|okay|jarvis)\W+)*(?:be|stay|quiet|silent|keep|don'?t|do not|stop|no|mute|hold|pause)\b/i.test(command)) return false;
    post(`/api/nudges/voice?text=${encodeURIComponent(String(command).slice(0, 300))}`).then((out) => {
      if (out.handled) { this.show(out.text); this.speak(out.text); this.refresh(); } else this.fallback?.(command);
    }).catch(() => this.fallback?.(command));
    return true;
  }
}
