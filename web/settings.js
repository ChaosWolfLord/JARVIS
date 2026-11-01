// Keeps the page's own settings (widget layout, the weather place, voice choice, the projector fit, ...) on the PC as well as in
// the browser. Browser storage alone is fragile: a different browser, a new profile, cleared site data, or a window that is
// closed a moment after a change all lose it. Here each change is also sent to the PC (data folder, not the browser), and when
// the page opens it takes the PC's copy first, so settings survive all of that.
//
// Only the keys listed here are kept; the board itself is saved separately by board.js.

export const SYNCED = [
  'jarvis.weather', 'jarvis.widgets', 'jarvis.widget.layout2', 'jarvis.voice', 'jarvis.warp.v1', 'jarvis.ambient', 'jarvis.timers',
  'jarvis.panel', 'jarvis.touch', 'jarvis.lights', 'jarvis.usage', 'jarvis.usage.measure', 'jarvis.usage.source', 'jarvis.alerts.seen',
  'jarvis.sounds', 'jarvis.boot', 'jarvis.voice.on',
];
const DELAY_MS = 400;

let pending = {};
let timer = null;
let syncing = false;

async function flush(keepalive = false) {
  clearTimeout(timer);
  timer = null;
  const values = pending;
  pending = {};
  if (!Object.keys(values).length) return;
  try {
    await fetch('/api/ui-settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ values }), keepalive });
  } catch {
    Object.assign(pending, values, pending);        // the PC wasn't reachable: try again with the next change
  }
}

function queue(key, value) {
  if (syncing || !SYNCED.includes(key)) return;
  pending[key] = value;
  clearTimeout(timer);
  timer = setTimeout(() => flush(), DELAY_MS);
}

/** Call once, before anything reads its settings: takes the PC's copy, sends up whatever only this browser has, then keeps them in step. */
export async function syncSettings() {
  try {
    const ctl = new AbortController();
    const abort = setTimeout(() => ctl.abort(), 3000);
    const res = await fetch('/api/ui-settings', { cache: 'no-store', signal: ctl.signal });
    clearTimeout(abort);
    if (res.ok) {
      const { values } = await res.json();
      syncing = true;
      for (const [key, value] of Object.entries(values || {})) {
        if (SYNCED.includes(key) && typeof value === 'string') localStorage.setItem(key, value);
      }
      syncing = false;
      for (const key of SYNCED) {                    // set here but not yet on the PC (first run after this was added)
        const local = localStorage.getItem(key);
        if (local !== null && !(key in (values || {}))) pending[key] = local;
      }
      await flush();
    }
  } catch { /* the PC isn't answering: carry on with this browser's own copy */ }
  syncing = false;
}

// Every later change to one of those keys is also sent to the PC.
try {
  const set = Storage.prototype.setItem;
  const remove = Storage.prototype.removeItem;
  Storage.prototype.setItem = function (key, value) {
    set.call(this, key, value);
    if (this === window.localStorage) queue(key, String(value));
  };
  Storage.prototype.removeItem = function (key) {
    remove.call(this, key);
    if (this === window.localStorage) queue(key, null);
  };
  window.addEventListener('pagehide', () => flush(true));
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') flush(true); });
} catch { /* an unusual browser: the page still works, settings just stay in the browser */ }
