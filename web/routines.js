// Routines on the PC's page: the list and editor in the status menu ("Routines"), and saying a routine's name ("movie night", "start the movie night
// routine") runs it. A routine is a name, other phrases that start it, and steps written as plain sentences (see server/routines.py); the PC does the
// work, this page only edits the list and starts one. The matching rule is the same as the PC's (normalize below and routines.normalize), so both agree.

const LEAD = /^(?:(?:hey|ok|okay) )?(?:jarvis )?(?:please )?(?:(?:run|start|activate|begin|launch|do|trigger|enable|engage|initiate|go to|switch to|its time for|time for|lets have|lets do|lets|its) )?(?:the |my )?/;
const TAIL = /(?: (?:routine|mode|scene|please))+$/;

const POLITE_LEAD = /^(?:(?:hey|ok|okay) )?(?:jarvis )?(?:please )?/;
const POLITE_TAIL = /(?: (?:please|jarvis))+$/;
const words = (text) => String(text || '').toLowerCase().replace(/['’]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();

/** The words as said, without punctuation, capitals or a polite "Jarvis," / "please": an extra phrase must be said as written to start its routine. */
export function plain(text) {
  return words(text).replace(POLITE_LEAD, '').replace(POLITE_TAIL, '').trim();
}

/** "Jarvis, start the Movie Night routine please" -> "movie night". Used for a routine's NAME, which can be asked for in many ways. */
export function normalize(text) {
  return words(text).replace(LEAD, '').replace(TAIL, '').trim();
}

export function matchRoutine(text, routines) {
  const flexible = normalize(text);
  const exact = plain(text);
  if (!flexible && !exact) return null;
  return (routines || []).find((r) => (flexible && flexible === normalize(r.name)) || exact === plain(r.name) || (r.phrases || []).some((p) => plain(p) === exact)) || null;
}

const el = (tag, text, cls) => Object.assign(document.createElement(tag), text == null ? {} : { textContent: text }, cls ? { className: cls } : {});

export class Routines {
  constructor({ root, speak = () => {} }) {
    this.speak = speak;
    this.routines = [];
    this.editing = null;                       // the id being edited, '' for a new one, null when the form is closed
    this.list = root.querySelector('#routine-list');
    this.form = root.querySelector('#routine-form');
    this.name = root.querySelector('#routine-name');
    this.phrases = root.querySelector('#routine-phrases');
    this.steps = root.querySelector('#routine-steps');
    this.note = root.querySelector('#routine-note');
    root.querySelector('#routine-new').addEventListener('click', () => this.edit(null));
    root.querySelector('#routine-cancel').addEventListener('click', () => this.close());
    root.querySelector('#routine-test').addEventListener('click', () => this.save(true));
    this.form.addEventListener('submit', (e) => { e.preventDefault(); this.save(false); });
  }

  async refresh() {
    try {
      this.routines = (await (await fetch('/api/routines', { cache: 'no-store' })).json()).routines || [];
      this.draw();
    } catch {
      this.say('Could not read the routines.');
    }
  }

  say(text) { this.note.textContent = text; }

  /** True means: don't send this to the AI (a routine of yours was named, and the PC is running it). */
  handleVoice(command) {
    const r = matchRoutine(command, this.routines);
    if (!r) return false;
    this.run(r.id);
    return true;
  }

  async run(id) {
    const r = this.routines.find((x) => x.id === id);
    this.say(`Running ${r ? r.name : 'the routine'}…`);
    try {
      const res = await fetch('/api/routines/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id }) });
      const out = await res.json();
      const text = res.ok ? out.text : out.detail || 'That did not work.';
      this.say(text);
      this.speak(text);
    } catch {
      this.say('Could not reach JARVIS.');
    }
  }

  draw() {
    this.list.replaceChildren();
    if (!this.routines.length) this.list.append(el('li', 'No routines yet. Make one with “New routine”.', 'files-none'));
    for (const r of this.routines) {
      const row = el('li');
      const info = el('div', null, 'files-info');
      info.append(el('b', r.name), el('small', `${[r.name, ...(r.phrases || [])].map((p) => `“${p.toLowerCase()}”`).join(', ')} · ${r.steps.length} step${r.steps.length === 1 ? '' : 's'}`));
      const buttons = el('div', null, 'files-buttons');
      for (const [label, fn] of [['Run', () => this.run(r.id)], ['Edit', () => this.edit(r)], ['Delete', () => this.remove(r)]]) {
        const b = el('button', label);
        b.type = 'button';
        b.addEventListener('click', fn);
        buttons.append(b);
      }
      row.append(info, buttons);
      this.list.append(row);
    }
  }

  edit(r) {
    this.editing = r ? r.id : '';
    this.name.value = r ? r.name : '';
    this.phrases.value = r ? (r.phrases || []).join(', ') : '';
    this.steps.value = r ? r.steps.join('\n') : '';
    this.form.hidden = false;
    this.say('');
    this.name.focus();
  }

  close() {
    this.editing = null;
    this.form.hidden = true;
  }

  async remove(r) {
    await this.put(this.routines.filter((x) => x.id !== r.id), `Deleted ${r.name}.`);
  }

  /** Saves the form; with `run` the routine is also started once, to try it. */
  async save(run) {
    const entry = {
      id: this.editing || undefined,
      name: this.name.value.trim(),
      phrases: this.phrases.value.split(/[,\n]/).map((p) => p.trim()).filter(Boolean),
      steps: this.steps.value.split('\n').map((s) => s.trim()).filter(Boolean),
    };
    const next = this.editing ? this.routines.map((r) => (r.id === this.editing ? entry : r)) : [...this.routines, entry];
    const saved = await this.put(next, `Saved ${entry.name || 'the routine'}.`);
    if (!saved) return;
    this.close();
    if (run) {
      const made = this.routines.find((r) => r.name.toLowerCase() === entry.name.toLowerCase());
      if (made) this.run(made.id);
    }
  }

  async put(routines, okText) {
    try {
      const res = await fetch('/api/routines', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ routines }) });
      const out = await res.json();
      if (!res.ok) { this.say(out.detail || 'That was not accepted.'); return false; }
      this.routines = out.routines;
      this.draw();
      this.say(okText);
      return true;
    } catch {
      this.say('Could not reach JARVIS.');
      return false;
    }
  }
}
