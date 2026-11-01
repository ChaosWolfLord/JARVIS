// The Lights widget and spoken light commands. Lights are Govee lights found on the home network (or through Govee's
// cloud, if there is a key). "Jarvis, lights off", "make the desk lights blue" and "set the lights to 40 percent" are
// handled on the PC without asking the AI, so they are instant and use none of the free request allowance.

const LIGHT_TALK = /\b(lights?|lamps?|leds?|lighting)\b|\b(relax|movie|night|reading|focus) (mode|lighting|scene)\b/i;
const QUESTION = /^(what|which|how|why|who|when|where|are|is|do|does|did|has|have)\b/i;
const SWATCHES = [['red', '#ff2a2a'], ['orange', '#ff8a00'], ['yellow', '#ffd400'], ['green', '#22e060'], ['cyan', '#00dcff'], ['blue', '#2a5cff'],
  ['purple', '#9a2aff'], ['pink', '#ff3d9a'], ['white', '#f4f8ff']];

const el = (tag, cls, text) => Object.assign(document.createElement(tag), { className: cls || '', textContent: text ?? '' });

export class Lights {
  constructor({ el: root, speak, toast }) {
    this.root = root;
    this.body = root.querySelector('#lights-body');
    this.foot = root.querySelector('#lights-foot');
    this.speak = speak;
    this.toast = toast;
    this.data = null;
    this.timer = null;
    this.fallback = null;       // (command) => void: asks the AI when a "light" sentence wasn't a light command
    root.querySelector('#lights-scan').addEventListener('click', () => this.scan());
  }

  onShow() {
    this.refresh();
    this.timer = setInterval(() => this.refresh(), 15_000);
  }

  onHide() { clearInterval(this.timer); this.timer = null; }

  async call(path, body) {
    const res = await fetch(path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : { cache: 'no-store' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
    return data;
  }

  async refresh() {
    try { this.data = await this.call('/api/lights/refresh', {}); this.render(); } catch { this.foot.textContent = 'Can’t reach the server right now.'; }
  }

  async scan() {
    this.foot.textContent = 'Looking for lights on the network… (about 10 seconds)';
    try { this.data = await this.call('/api/lights/scan', {}); this.render(); } catch (e) { this.foot.textContent = `Search failed: ${e.message}`; }
  }

  async send(command) {
    try {
      const out = await this.call('/api/lights/command', command);
      this.data = out;
      this.render();
      if (!out.ok) this.toast(out.text.replace(/^Error: /, ''));
    } catch (e) { this.toast(e.message); }
  }

  render() {
    const d = this.data;
    if (!d) return;
    const rows = [];
    if (!d.lights.length) {
      const help = el('div', 'lt-help');
      help.append(
        el('p', '', 'No lights found yet.'),
        el('p', 'lt-small', 'In the Govee Home app: open the light, tap the gear, and switch on “LAN Control” (only some models have it). Then press Find lights. Or add a Govee API key to .env as GOVEE_API_KEY. The README has the steps.'),
      );
      if (d.error) help.append(el('p', 'lt-error', d.error));
      rows.push(help);
    } else {
      const all = el('div', 'lt-all');
      all.append(el('b', '', 'All'));
      const on = el('button', '', 'On'); on.type = 'button';
      on.addEventListener('click', () => this.send({ power: true }));
      const off = el('button', '', 'Off'); off.type = 'button';
      off.addEventListener('click', () => this.send({ power: false }));
      all.append(on, off);
      const sw = el('div', 'lt-swatches');
      for (const [name, color] of SWATCHES) {
        const b = el('button', 'lt-swatch'); b.type = 'button'; b.title = name; b.style.background = color;
        b.addEventListener('click', () => this.send({ color: name }));
        sw.append(b);
      }
      for (const [name, k] of [['warm', 2700], ['cool', 6500]]) {
        const b = el('button', 'lt-white', name); b.type = 'button';
        b.addEventListener('click', () => this.send({ kelvin: k }));
        sw.append(b);
      }
      rows.push(all, sw);
      for (const l of d.lights) {
        const row = el('div', `lt-row${l.state.reachable === false ? ' lost' : ''}`);
        const name = el('span', 'lt-name', l.name);
        name.title = `${l.sku || 'light'} · ${l.via}${l.state.reachable === false ? ' · not answering' : ''}`;
        name.addEventListener('dblclick', async () => {
          const next = window.prompt('Name this light (what you will say):', l.name);
          if (!next || !next.trim()) return;
          try { this.data = await this.call('/api/lights/rename', { id: l.id, name: next.trim() }); this.render(); } catch (e) { this.toast(e.message); }
        });
        const power = el('button', `lt-power${l.state.on ? ' on' : ''}`, l.state.on ? 'On' : 'Off'); power.type = 'button';
        power.addEventListener('click', () => this.send({ target: l.name, power: !l.state.on }));
        const slider = Object.assign(document.createElement('input'), { type: 'range', min: 1, max: 100, value: l.state.brightness ?? 50 });
        slider.title = 'Brightness';
        slider.addEventListener('change', () => this.send({ target: l.name, brightness: Number(slider.value) }));
        row.append(name, power, slider);
        rows.push(row);
      }
    }
    this.body.replaceChildren(...rows);
    this.foot.textContent = d.lights.length ? `${d.lights.length} light${d.lights.length > 1 ? 's' : ''}${d.cloud ? ' · Govee cloud on' : ''}` : '';
  }

  /** "Jarvis, lights off". True means: don't send this to the AI (it was, or may be, a light command). */
  handleVoice(command) {
    const text = command.trim().replace(/^jarvis\b\W*/i, '');
    if (!LIGHT_TALK.test(text) || QUESTION.test(text)) return false;
    this.answer(command);
    return true;
  }

  async answer(command) {
    try {
      const out = await this.call('/api/lights/voice', { text: command });
      if (!out.handled) return this.fallback?.(command);
      if (this.data) this.refresh();
      this.speak(out.text);
    } catch {
      this.speak('I can’t reach the lights right now.');
    }
    return undefined;
  }
}
