// JARVIS on your phone: pair once with the code from the PC, then talk or type. Everything goes to the PC over your home Wi-Fi;
// the answer comes back here (and, if you like, on the wall or the PC speakers). Nothing in this page is sent anywhere else.
const $ = (id) => document.getElementById(id);
const TOKEN_KEY = 'jarvis.phone.token';
const PREF_KEY = 'jarvis.phone.prefs';

// Inside the JARVIS Android app, window.JarvisApp exists: the app keeps the pairing token, listens for speech and keeps the screen on.
const app = window.JarvisApp || null;
const LOCAL = location.protocol === 'file:';          // the copy of this page that is bundled in the app: the standalone assistant, no PC

const store = {
  get(key) {
    if (app && key === TOKEN_KEY) return app.getToken() || null;
    try { return localStorage.getItem(key); } catch { return null; }
  },
  set(key, value) {
    if (app && key === TOKEN_KEY) { app.setToken(value); return; }
    try { localStorage.setItem(key, value); } catch { /* private window: it just won't be remembered */ }
  },
  del(key) {
    if (app && key === TOKEN_KEY) { app.clearToken(); return; }
    try { localStorage.removeItem(key); } catch { /* nothing to remove */ }
  },
};

let token = store.get(TOKEN_KEY);
let history = [];
let privateTouched = false;
let busy = false;
let speaking = false;               // this phone is reading an answer aloud
let online = true;                  // the PC answered the last time it was asked
let controller = null;
let prefs = { wall: true, speak: false, read: false, auto: true, awake: false };
try { prefs = { ...prefs, ...JSON.parse(store.get(PREF_KEY) || '{}') }; } catch { /* use the defaults */ }

// ---- the orb: JARVIS's face at the top of the screen. It listens, thinks and speaks with you; tapping it talks, or stops what is going on. ----
const orb = typeof PhoneOrb === 'undefined' ? null : new PhoneOrb($('orb-canvas'));
if (typeof PhoneOrb !== 'undefined') new PhoneOrb($('pair-orb'));

function orbState() {
  return listening ? 'listening' : busy ? 'thinking' : speaking ? 'speaking' : !online && !LOCAL ? 'offline' : 'idle';
}

function refreshOrb() {
  const state = orbState();
  if (orb) orb.state = state;
  $('stage').dataset.state = state;
  const canTalk = Boolean(app || (typeof Recognition !== 'undefined' && Recognition));
  $('orb-label').textContent = { listening: 'Listening… tap to stop', thinking: 'Thinking… tap to stop', speaking: 'Speaking… tap to stop', offline: 'Can’t reach your PC',
    idle: canTalk ? 'Tap to talk' : 'Type to JARVIS' }[state];
}

$('orb').addEventListener('click', () => {
  if (listening) stopListening();
  else if (busy) controller?.abort();
  else if (speaking) { speechSynthesis.cancel(); speaking = false; refreshOrb(); }
  else if (!$('mic').disabled) $('mic').click();
});
$('input').addEventListener('focus', () => document.body.classList.add('typing'));
$('input').addEventListener('blur', () => document.body.classList.remove('typing'));

function show(view) {
  $('pair').hidden = view !== 'pair';
  $('chat').hidden = view !== 'chat';
}

function setState(text, level) {
  const el = $('state');
  el.textContent = text;
  el.className = level || '';
  online = level !== 'bad';
  refreshOrb();
}

function add(kind, text) {
  const el = document.createElement('div');
  el.className = `m ${kind}`;
  el.textContent = text;
  $('log').append(el);
  scrollDown();
  return el;
}

function scrollDown() { const log = $('log'); log.scrollTop = log.scrollHeight; }

function unpair(message) {
  token = null;
  alertAbort?.abort();
  store.del(TOKEN_KEY);
  history = [];
  $('log').textContent = '';
  $('pair-msg').textContent = message || '';
  show('pair');
}

async function api(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  return fetch(path, { ...options, headers });
}

// ---- pairing -------------------------------------------------------------------------------------------------------
function deviceName() {
  if (app) return 'JARVIS app';
  const ua = navigator.userAgent || '';
  const model = /;\s*([^;)]+?)\s+Build\//.exec(ua) || /Android[^;]*;\s*([^;)]+)\)/.exec(ua);
  return (model ? model[1] : /Android/.test(ua) ? 'Android phone' : 'phone').slice(0, 30);
}

$('pair-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const code = $('code').value.trim();
  $('pair-msg').textContent = '';
  if (!/^\d{6}$/.test(code)) { $('pair-msg').textContent = 'The code is six digits.'; return; }
  try {
    const res = await fetch('/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, name: deviceName() }) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { $('pair-msg').textContent = data.detail || `Pairing failed (${res.status}).`; return; }
    token = data.token;
    store.set(TOKEN_KEY, token);
    $('code').value = '';
    start();
  } catch {
    $('pair-msg').textContent = 'Could not reach JARVIS. Is the PC on and on the same Wi-Fi?';
  }
});

// ---- chat ----------------------------------------------------------------------------------------------------------
async function checkConnection() {
  try {
    const res = await api('/ping');
    if (res.status === 401) { unpair('This phone was forgotten on the PC. Pair it again.'); return false; }
    const data = await res.json();
    setState(data.locked ? 'Privacy screen is on' : 'Connected to your PC', data.locked ? 'bad' : 'ok');
    return true;
  } catch {
    setState('Can’t reach your PC', 'bad');
    return false;
  }
}

function showUpdates() {                                    // only the app has updates, and only newer apps know how to ask
  if (!app || typeof app.updatesOn !== 'function') return;
  $('set-app').hidden = false;
  $('opt-upd').checked = app.updatesOn();
  $('upd-ver').textContent = `This is version ${app.version()}.`;
}

function start() {
  show('chat');
  $('opt-wall').checked = prefs.wall;
  $('opt-speak').checked = prefs.speak;
  $('opt-read').checked = prefs.read;
  $('opt-auto').checked = prefs.auto;
  if (!$('log').childElementCount) add('note', 'Tap the orb and talk, or type below.');
  $('opt-awake').checked = prefs.awake;
  checkConnection();
  setupVoice();
  listenForAlerts();
  keepAwake();
  if (app) {
    $('bg-row').hidden = false;
    $('opt-bg').checked = app.backgroundAlerts();
    showCalls();
  }
  showUpdates();
  syncReminders();
  checkShare();
  if (app && typeof Brain !== 'undefined') Brain.sync((path, body) => api(path, { method: 'POST', body: JSON.stringify(body) }).then((r) => (r.ok ? r.json() : null)).catch(() => null));
}

function setBusy(on) {
  busy = on;
  refreshOrb();
  $('send').textContent = on ? 'Stop' : 'Send';
  $('send').classList.toggle('stop', on);
}

async function send(text) {
  text = (text || '').trim();
  if (!text || busy) return;
  stopListening();
  $('input').value = '';
  autosize();
  add('user', text);
  const reply = add('bot', 'Thinking');
  reply.classList.add('dots');
  let full = '';
  let failed = false;
  setBusy(true);
  controller = new AbortController();
  try {
    const handle = (ev) => {
      if (ev.type === 'text') {
        if (reply.classList.contains('dots')) { reply.classList.remove('dots'); reply.textContent = ''; }
        full += ev.delta;
        reply.textContent = full;
      } else if (ev.type === 'step') {
        if (reply.classList.contains('dots')) reply.textContent = ev.text;
        else add('did', ev.text);
      } else if (ev.type === 'did') {
        add('did', ev.text);
      } else if (ev.type === 'notice') {
        add('note', ev.text);
      } else if (ev.type === 'memory') {
        add('did', ev.action === 'saved' ? `Remembered: ${ev.fact}` : 'Forgot a fact');
      } else if (ev.type === 'private') {
        privateTouched = true;
      } else if (ev.type === 'error') {
        failed = true;
        add('err', ev.message);
      } else if (ev.type === 'summary' && !full) {
        full = ev.text;
        reply.classList.remove('dots');
        reply.textContent = full;
      }
      scrollDown();
    };
    if (LOCAL) {
      app.busy(true);
      await Brain.run(text, history, handle, controller.signal);
      if (controller.signal.aborted) throw Object.assign(new Error('stopped'), { name: 'AbortError' });
    } else {
      const res = await api('/chat', {
        method: 'POST',
        body: JSON.stringify({ message: text, history: history.slice(-20), private: privateTouched, show: prefs.wall, speak: prefs.speak }),
        signal: controller.signal,
      });
      if (res.status === 401) { unpair('This phone was forgotten on the PC. Pair it again.'); return; }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `The PC answered ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (line.startsWith('data:')) { try { handle(JSON.parse(line.slice(5))); } catch { /* a damaged line: skip it */ } }
        }
      }
    }
  } catch (err) {
    failed = true;
    if (err.name === 'AbortError') add('note', 'Stopped.');
    else add('err', err.message || 'Connection problem.');
  } finally {
    if (reply.classList.contains('dots') || !reply.textContent) reply.remove();
    setBusy(false);
    controller = null;
    if (LOCAL) app.busy(false);
  }
  if (full.trim() && !failed) {
    history.push({ role: 'user', content: text }, { role: 'assistant', content: full.trim() });
    history = history.slice(-24);
    if (prefs.read && 'speechSynthesis' in window) {
      speechSynthesis.cancel();
      const said = new SpeechSynthesisUtterance(full.trim().slice(0, 600));
      said.onstart = () => { speaking = true; refreshOrb(); };
      said.onend = said.onerror = () => { speaking = false; refreshOrb(); };
      speechSynthesis.speak(said);
    }
  }
  if (!LOCAL) checkConnection();
}

$('composer').addEventListener('submit', (e) => {
  e.preventDefault();
  if (busy) controller?.abort();
  else send($('input').value);
});

function autosize() {
  const el = $('input');
  el.style.height = 'auto';
  el.style.height = `${Math.min(el.scrollHeight, 140)}px`;
}
$('input').addEventListener('input', autosize);
$('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('composer').requestSubmit(); }
});

// ---- settings menu -------------------------------------------------------------------------------------------------
$('menu-close').addEventListener('click', () => { $('menu').hidden = true; $('menu-btn').setAttribute('aria-expanded', 'false'); });
$('menu-btn').addEventListener('click', () => {
  const open = $('menu').hidden;
  $('menu').hidden = !open;
  $('menu-btn').setAttribute('aria-expanded', String(open));
});
for (const [id, key] of [['opt-wall', 'wall'], ['opt-speak', 'speak'], ['opt-read', 'read'], ['opt-auto', 'auto'], ['opt-awake', 'awake']]) {
  $(id).addEventListener('change', (e) => { prefs[key] = e.target.checked; store.set(PREF_KEY, JSON.stringify(prefs)); if (key === 'awake') keepAwake(); });
}
if (app) { $('change-pc').hidden = false; $('get-app').hidden = true; }
$('change-pc').addEventListener('click', () => app?.forgetServer());
$('forget').addEventListener('click', () => unpair('This phone was forgotten here. To use it again, pair it with a new code.'));

// ---- voice ---------------------------------------------------------------------------------------------------------
// In the app the phone's own speech recognition is used (through the app); in a browser, Chrome's.
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let listening = false;
let finalText = '';

function hint(text) {
  $('hint').textContent = text || '';
  $('hint').hidden = !text;
}

function setupVoice() {
  if (app) return;
  if (!Recognition) {
    $('mic').disabled = true;
    $('mic').style.opacity = '0.4';
    hint('Voice needs Chrome on Android, or the JARVIS app. Typing works everywhere.');
    return;
  }
  if (!window.isSecureContext) {
    hint('The microphone only works on a secure (https) page. Open the address that starts with https:// and accept the one-time warning.');
  }
}

function micState(on) {
  listening = on;
  refreshOrb();
  $('mic').classList.toggle('on', on);
  $('input').placeholder = on ? 'Listening…' : 'Ask JARVIS…';
}

function micError(code) {
  if (code === 'not-allowed' || code === 'service-not-allowed') hint(app ? 'The microphone is blocked. Allow it for JARVIS in the phone settings (Apps, JARVIS, Permissions).' : 'The microphone was blocked. Allow it in Chrome (the lock icon next to the address), then try again.');
  else if (code === 'network') hint('Speech recognition needs the phone’s internet connection (it uses Google).');
  else if (code === 'no-speech') hint('I didn’t hear anything. Try again a little closer.');
  else if (code === 'busy') hint('The speech recognizer is busy. Try again in a moment.');
}

function micEnded() {
  micState(false);
  if (prefs.auto && finalText.trim()) send(finalText);
  finalText = '';
}

function stopListening() {
  if (!listening) return;
  if (app) app.stopListening();
  else if (recognition) { try { recognition.stop(); } catch { /* already stopped */ } }
}

// The app reports what it heard through this function: start, partial, final, error, end.
window.__speech = (type, text) => {
  if (type === 'rms') orb?.hear(parseFloat(text));                  // how loud you are, from the phone's own recognizer (the Android app)
  else if (type === 'start') micState(true);
  else if (type === 'partial' || type === 'final') {
    if (type === 'final') finalText = text;
    $('input').value = text;
    autosize();
  } else if (type === 'error') micError(text);
  else if (type === 'end') micEnded();
};

$('mic').addEventListener('click', () => {
  if (listening) { stopListening(); return; }
  if (busy) return;
  hint('');
  finalText = '';
  if (app) { app.startListening(navigator.language || 'en-US'); return; }
  if (!Recognition) return;
  recognition = new Recognition();
  recognition.lang = navigator.language || 'en-US';
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.onstart = () => micState(true);
  recognition.onresult = (e) => {
    let interim = '';
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const r = e.results[i];
      if (r.isFinal) finalText += r[0].transcript; else interim += r[0].transcript;
    }
    $('input').value = (finalText + interim).trim();
    autosize();
  };
  recognition.onerror = (e) => micError(e.error);
  recognition.onend = micEnded;
  try { recognition.start(); } catch { hint('Could not start the microphone.'); }
});

// ---- alerts from the PC ----------------------------------------------------------------------------------------------
// While this page is open the PC can push to it: a reminder came due, a timer ended, Claude finished, a problem was found. The page
// shows it, buzzes and chimes. (A phone browser can't be woken when the page is closed or the screen is off; reminders then wait on the
// PC and arrive the moment the page is opened again, marked as late.)
let alertAbort = null;
let wake = null;

function chime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [880, 1175].forEach((f, i) => {
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.frequency.value = f; o.connect(g); g.connect(ctx.destination);
      g.gain.setValueAtTime(0.0001, ctx.currentTime + i * 0.22);
      g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + i * 0.22 + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i * 0.22 + 0.4);
      o.start(ctx.currentTime + i * 0.22); o.stop(ctx.currentTime + i * 0.22 + 0.45);
    });
  } catch { /* no sound available */ }
}

const shownAlerts = new Set();
function alertUser(ev) {
  if (ev.rid) {
    if (shownAlerts.has(ev.rid)) return;                  // the PC's push and this phone's own alarm are the same reminder
    shownAlerts.add(ev.rid);
    app?.heard(ev.rid);                                    // so its alarm here does not ring again
    syncReminders();                                       // and the PC learns it was delivered
  }
  const el = add('alert', `${ev.title}${ev.text ? `: ${ev.text}` : ''}`);
  el.addEventListener('click', () => el.remove());
  try { navigator.vibrate?.([250, 120, 250]); } catch { /* not supported */ }
  chime();
  if (document.hidden) document.title = `● ${ev.title}`;
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) document.title = 'JARVIS'; });

async function listenForAlerts() {
  if (alertAbort || !token) return;
  alertAbort = new AbortController();
  let delay = 1000;
  while (token && !alertAbort.signal.aborted) {
    try {
      const res = await api('/events', { signal: alertAbort.signal });
      if (res.status === 401) { unpair('This phone was forgotten on the PC. Pair it again.'); break; }
      if (!res.ok) throw new Error(String(res.status));
      delay = 1000;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (line.startsWith('data:')) { try { alertUser(JSON.parse(line.slice(5))); } catch { /* skip a damaged line */ } }
        }
      }
    } catch { /* offline or the PC restarted: try again below */ }
    if (alertAbort?.signal.aborted) break;
    await new Promise((r) => setTimeout(r, delay));
    delay = Math.min(delay * 2, 15000);
  }
  alertAbort = null;
}

async function keepAwake() {
  if (app) { app.keepScreenOn(!!prefs.awake); return; }
  try {
    if (prefs.awake && 'wakeLock' in navigator && !wake) wake = await navigator.wakeLock.request('screen');
    else if (!prefs.awake && wake) { await wake.release(); wake = null; }
    wake?.addEventListener('release', () => { wake = null; });
  } catch { wake = null; }
}
document.addEventListener('visibilitychange', () => { if (!document.hidden && prefs.awake) keepAwake(); });

// ---- reminders -----------------------------------------------------------------------------------------------------
// In the app the phone keeps its own copy and sets its own alarms (they ring with the PC off); in a browser the list lives on the PC.
// Either way, syncing sends what changed here and brings back what is waiting.
let serverReminders = [];

async function syncReminders(extra) {
  if (!token || LOCAL) return null;
  const sent = app ? app.pendingReminders() : '{"created":[],"deleted":[],"fired":[]}';
  const body = JSON.parse(sent);
  if (extra) { body.created.push(...(extra.created || [])); body.deleted.push(...(extra.deleted || [])); }
  try {
    const res = await api('/reminders/sync', { method: 'POST', body: JSON.stringify(body) });
    if (res.status === 401) { unpair('This phone was forgotten on the PC. Pair it again.'); return null; }
    if (!res.ok) return null;
    const answer = await res.json();
    serverReminders = answer.reminders || [];
    if (app) app.applySync(sent, JSON.stringify(answer));
    renderReminders();
    return answer;
  } catch {
    renderReminders();
    return null;                                           // the PC is off: the phone's own alarms still stand
  }
}

function whenText(ms) {
  const d = new Date(ms), now = new Date();
  const days = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(now.getFullYear(), now.getMonth(), now.getDate())) / 86400000);
  const clock = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  return `${days === 0 ? 'Today' : days === 1 ? 'Tomorrow' : d.toLocaleDateString([], { weekday: 'short', day: 'numeric', month: 'short' })} at ${clock}`;
}

function renderReminders() {
  const list = app ? JSON.parse(app.reminders()) : serverReminders.map((r) => ({ id: r.id, text: r.text, due: r.due * 1000 }));
  const ul = $('rem-list');
  ul.textContent = '';
  if (!list.length) {
    const li = document.createElement('li');
    li.className = 'empty';
    li.textContent = 'No reminders waiting.';
    ul.append(li);
    return;
  }
  for (const r of list) {
    const li = document.createElement('li');
    const what = document.createElement('div');
    what.className = 'what';
    const when = document.createElement('div');
    when.className = 'when';
    when.textContent = whenText(r.due);
    what.append(when, document.createTextNode(r.text));
    const del = document.createElement('button');
    del.type = 'button';
    del.textContent = '✕';
    del.setAttribute('aria-label', `Delete reminder: ${r.text}`);
    del.addEventListener('click', async () => {
      if (app) { app.deleteReminder(r.id); await syncReminders(); } else await syncReminders({ deleted: [r.id] });
      renderReminders();
    });
    li.append(what, del);
    ul.append(li);
  }
}

function localInput(ms) {
  const d = new Date(ms - new Date().getTimezoneOffset() * 60000);
  return d.toISOString().slice(0, 16);
}

$('open-rem').addEventListener('click', () => { $('menu').hidden = true; $('rem').hidden = false; if (!$('rem-when').value) $('rem-when').value = localInput(Date.now() + 10 * 60000); renderReminders(); syncReminders(); });
$('rem-close').addEventListener('click', () => { $('rem').hidden = true; });
for (const b of document.querySelectorAll('#rem .quick button')) {
  b.addEventListener('click', () => {
    if (b.dataset.min) $('rem-when').value = localInput(Date.now() + Number(b.dataset.min) * 60000);
    else { const t = new Date(); t.setDate(t.getDate() + 1); t.setHours(Number(b.dataset.tom), 0, 0, 0); $('rem-when').value = localInput(t.getTime()); }
  });
}
$('rem-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const text = $('rem-text').value.trim();
  const ms = $('rem-when').value ? new Date($('rem-when').value).getTime() : NaN;
  $('rem-msg').textContent = '';
  if (!text) { $('rem-msg').textContent = 'What should I remind you about?'; return; }
  if (!Number.isFinite(ms)) { $('rem-msg').textContent = 'Pick a time.'; return; }
  if (app) {
    const problem = app.addReminder(text, ms);
    if (problem) { $('rem-msg').textContent = problem; return; }
    await syncReminders();
  } else {
    if (ms < Date.now() + 30000) { $('rem-msg').textContent = 'Pick a time at least a minute from now.'; return; }
    await syncReminders({ created: [{ lid: `b${Date.now()}`, text, due: ms / 1000, fired: false }] });
  }
  $('rem-text').value = '';
  $('rem-when').value = '';
  renderReminders();
});
$('opt-bg').addEventListener('change', (e) => { app?.setBackgroundAlerts(e.target.checked); });
$('opt-call').addEventListener('change', (e) => { app?.setCallsOn(e.target.checked); showCalls(); });
$('call-allow').addEventListener('click', () => app?.allowCallScreen());
$('call-overlay').addEventListener('click', () => app?.allowOverlay());
document.addEventListener('visibilitychange', () => { if (!document.hidden) showCalls(); });      // back from the phone's page where the call screen is allowed

// "JARVIS calls you" (Android app): reminders ring like a call. The switch lives on the phone; the extra button shows only when the phone is holding back the lock-screen call screen.
function showCalls() {
  if (!app || typeof app.callsOn !== 'function') return;
  $('call-row').hidden = false;
  $('opt-call').checked = app.callsOn();
  $('call-allow').hidden = !(app.callsOn() && typeof app.callScreenAllowed === 'function' && !app.callScreenAllowed());
  $('call-overlay').hidden = !(app.callsOn() && typeof app.overlayAllowed === 'function' && !app.overlayAllowed());
}
$('opt-upd').addEventListener('change', (e) => { app?.setUpdates?.(e.target.checked); });
$('upd-now').addEventListener('click', () => app?.checkUpdates?.());
window.__alert = (ev) => alertUser(ev);                     // the app hands over an alarm that is ringing while the page is open
setInterval(() => { if (token && !document.hidden) syncReminders(); }, 5 * 60 * 1000);

// ---- the standalone assistant and the AI keys (app only) ----------------------------------------------------------
function keysText() {
  const n = typeof Brain === 'undefined' ? 0 : Brain.keyCount();
  $('keys-text').textContent = n ? `AI keys on this phone: ${n} model${n === 1 ? '' : 's'} ready (${Brain.keyNames().slice(0, 3).join(', ')}${n > 3 ? ', …' : ''}).` : 'No AI keys on this phone yet, so the app cannot answer without the PC.';
  $('keys-copy').hidden = LOCAL;
  $('keys-clear').hidden = !n;
  $('open-local').hidden = LOCAL || !n;
}

if (app && typeof Brain !== 'undefined') {
  $('keys-row').hidden = false;
  keysText();
  let armed = null;
  $('keys-copy').addEventListener('click', async () => {
    const b = $('keys-copy');
    if (!armed) {                                           // asks twice: these are your private keys
      b.textContent = 'Tap again to copy the keys to this phone';
      armed = setTimeout(() => { armed = null; b.textContent = 'Copy AI keys from the PC'; }, 6000);
      return;
    }
    clearTimeout(armed);
    armed = null;
    b.textContent = 'Copying…';
    const n = await Brain.copyKeys((path, body) => api(path, { method: 'POST', body: JSON.stringify(body) }).then((r) => (r.ok ? r.json() : null)).catch(() => null));
    b.textContent = 'Copy AI keys from the PC';
    if (n < 0) add('err', 'The PC would not copy its keys (it may be switched off in JARVIS_PHONE_KEYS, or the connection failed).');
    else add('did', n ? `${n} AI model${n === 1 ? '' : 's'} copied. The app can now answer without the PC.` : 'The PC had no usable AI keys to copy.');
    keysText();
  });
  $('keys-clear').addEventListener('click', () => { app.clearKeys(); keysText(); add('did', 'AI keys removed from this phone.'); });
  $('open-local').addEventListener('click', () => app.openLocal());
  $('go-pc').addEventListener('click', () => app.retry());
  $('pc-switch').addEventListener('click', () => app.retry());
}

/** On the standalone page: every half minute, is the PC back? Offer the switch (never swap in the middle of a conversation). */
function watchForPc() {
  setInterval(async () => {
    if (busy || document.hidden) return;
    const r = await Brain.ping();
    $('pc-back').hidden = !(r && r.ok);
  }, 30000);
}

function startLocal() {
  show('chat');
  setState('Standalone: your PC isn’t reachable', 'bad');
  $('set-pc').hidden = true;                                 // nothing on the PC to show things on
  $('forget').hidden = true;
  $('go-pc').hidden = false;
  $('opt-read').checked = prefs.read;
  $('opt-auto').checked = prefs.auto;
  $('opt-awake').checked = prefs.awake;
  $('bg-row').hidden = false;
  $('opt-bg').checked = app.backgroundAlerts();
  showCalls();
  showUpdates();
  if (!$('log').childElementCount) {
    add('note', Brain.keyCount() ? 'Your PC isn’t reachable, so I’m running on the phone: chat, web search, weather, reminders and timers, and what I remember about you. Lights, music and the board need the PC.' : 'No AI keys on this phone yet. Connect to the PC once and copy them (menu, AI keys), then I can answer without it.');
  }
  setupVoice();
  keepAwake();
  renderReminders();
  watchForPc();
  checkShare();
}

// ---- share to JARVIS (app only) ---------------------------------------------------------------------------------------
// Another app's Share menu hands the app some text, a link or a picture. Nothing happens by itself: this sheet asks what to do with it.
let shared = null;
const URL_ONLY = /^https?:\/\/\S+$/i;

function shareMessage(text) { $('share-msg').textContent = text || ''; }

function closeShare() {
  $('share').hidden = true;
  $('share-img').removeAttribute('src');
  if (shared?.kind === 'image') app?.discardShare?.();
  shared = null;
}

function checkShare() {
  if (!app || typeof app.takeShare !== 'function' || $('chat').hidden || shared) return;
  let item = null;
  try { item = JSON.parse(app.takeShare() || 'null'); } catch { item = null; }
  if (!item) return;
  shared = item;
  const image = item.kind === 'image';
  const url = !image && URL_ONLY.test(String(item.text || '').trim());
  $('share-img').hidden = !image;
  if (image) $('share-img').src = `data:image/jpeg;base64,${app.sharedImage()}`;
  $('share-text').textContent = image ? '' : String(item.text || '');
  $('share-ask').hidden = image;
  $('share-wall').hidden = !image || LOCAL;
  $('share-note').hidden = image || LOCAL;
  $('share-open').hidden = !url || LOCAL;
  shareMessage(LOCAL ? 'Your PC isn’t reachable, so the wall isn’t available. I can still answer about it.' : '');
  if (image && LOCAL) shareMessage('Your PC isn’t reachable, so I can’t put a picture on the wall right now.');
  $('share').hidden = false;
}

async function shareToPc(what) {
  if (!shared) return;
  shareMessage('Sending…');
  try {
    let res;
    if (shared.kind === 'image') {
      const raw = atob(app.sharedImage());
      const bytes = Uint8Array.from(raw, (c) => c.charCodeAt(0));
      res = await fetch('/picture?title=From%20your%20phone', { method: 'POST', headers: { 'Content-Type': 'image/jpeg', Authorization: `Bearer ${token}` }, body: bytes });
    } else {
      res = await api('/share', { method: 'POST', body: JSON.stringify({ what, text: String(shared.text || '').slice(0, 2000) }) });
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { shareMessage(data.detail || `The PC said no (${res.status}).`); return; }
    add('did', shared.kind === 'image' ? 'Picture sent to the wall' : what === 'open' ? 'Opened on the PC' : 'Added to the board');
    closeShare();
  } catch {
    shareMessage('Could not reach your PC.');
  }
}

$('share-wall').addEventListener('click', () => shareToPc('wall'));
$('share-note').addEventListener('click', () => shareToPc('note'));
$('share-open').addEventListener('click', () => shareToPc('open'));
$('share-cancel').addEventListener('click', closeShare);
$('share-ask').addEventListener('click', () => {
  const text = String(shared?.text || '').trim();
  closeShare();
  if (text) send(URL_ONLY.test(text) ? `Look at this page and tell me what it is about: ${text}` : `About this: ${text}`);
});
window.__shareReady = () => checkShare();                   // the app has something shared with it

// ---- go ------------------------------------------------------------------------------------------------------------
if (LOCAL) startLocal(); else if (token) start(); else show('pair');
