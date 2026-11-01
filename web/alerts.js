// System alerts on the board. When the PC's monitor finds a problem (a full drive, no internet, a stopped wake-word
// listener...) the server tells the page, and the page puts a red sticky note on the board and says it out loud.
//
// - Each alert becomes one note, tagged with the alert's id, so it is never added twice.
// - A problem that is fixed makes its note go away by itself. Delete a note yourself and that same problem is not
//   put back (until it clears and comes back later).
// - A page that was closed or reconnecting is told which alerts are active when it connects, and quietly catches up.

const SEEN_KEY = 'jarvis.alerts.seen';
const MAX_SEEN = 100;

export class Alerts {
  constructor({ board, speak, show, poke, chime }) {
    this.board = board;
    this.speak = speak;
    this.show = show;          // (html, ms) -> shows the speech bubble
    this.poke = poke;          // wakes the screen from calm mode
    this.chime = chime;        // the alert sound
    this.speakAlerts = true;
    this.seen = new Set();
    try { this.seen = new Set(JSON.parse(localStorage.getItem(SEEN_KEY)) || []); } catch { /* none yet */ }
  }

  /** One WebSocket message: {type:'alert', state:'new'|'resolved', ...} or {type:'alerts', alerts:[...]}. */
  handle(m) {
    if (m.type === 'alerts') return this.reconcile(m.alerts || []);
    if (m.state === 'resolved') return this.clear(m.id);
    return this.raise(m, true);
  }

  key(a) { return `${a.id}@${Math.round(a.since || 0)}`; }

  noteFor(id) { return this.board.notes.find((n) => n.alertId === id); }

  /** Puts the red note up (and says it) unless this occurrence was already shown on this browser. */
  raise(a, loud) {
    const k = this.key(a);
    if (this.seen.has(k)) return;
    this.seen.add(k);
    this.remember();
    if (!this.noteFor(a.id)) {
      const note = this.board.addNote({ text: `⚠ ${a.title}\n${a.text}`, color: 'red' });
      note.alertId = a.id;
      this.board.save();
    }
    this.poke?.();
    if (loud) this.chime?.();
    this.show?.(`<p>⚠ <b>${escape(a.title)}</b></p><p>${escape(a.text)}</p>`, 20_000);
    if (loud && this.speakAlerts && a.speak) this.speak(a.speak);
  }

  /** Takes the server's list of active alerts as the truth: adds the missing ones, removes notes whose problem is gone. */
  reconcile(active) {
    const ids = new Set(active.map((a) => a.id));
    for (const n of [...this.board.notes]) if (n.alertId && !ids.has(n.alertId)) this.board.removeNote(n.id);
    for (const a of active) this.raise(a, true);
  }

  clear(id) {
    const note = this.noteFor(id);
    if (note) this.board.removeNote(note.id);
  }

  remember() {
    const keep = [...this.seen].slice(-MAX_SEEN);
    this.seen = new Set(keep);
    try { localStorage.setItem(SEEN_KEY, JSON.stringify(keep)); } catch { /* not remembered */ }
  }
}

const escape = (s) => Object.assign(document.createElement('div'), { textContent: String(s ?? '') }).innerHTML;
