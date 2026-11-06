// JARVIS on your phone: pair once with the code from the PC, then talk or type. Everything goes to the PC over your home Wi-Fi;
// the answer comes back here (and, if you like, on the wall or the PC speakers). Nothing in this page is sent anywhere else.
const $ = (id) => document.getElementById(id);
const TOKEN_KEY = 'jarvis.phone.token';
const PREF_KEY = 'jarvis.phone.prefs';

// Inside the JARVIS Android app, window.JarvisApp exists: the app keeps the pairing token, listens for speech and keeps the screen on.
const app = window.JarvisApp || null;

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
let controller = null;
let prefs = { wall: true, speak: false, read: false, auto: true, awake: false };
try { prefs = { ...prefs, ...JSON.parse(store.get(PREF_KEY) || '{}') }; } catch { /* use the defaults */ }

function show(view) {
  $('pair').hidden = view !== 'pair';
  $('chat').hidden = view !== 'chat';
}

function setState(text, level) {
  const el = $('state');
  el.textContent = text;
  el.className = level || '';
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

function start() {
  show('chat');
  $('opt-wall').checked = prefs.wall;
  $('opt-speak').checked = prefs.speak;
  $('opt-read').checked = prefs.read;
  $('opt-auto').checked = prefs.auto;
  if (!$('log').childElementCount) add('note', 'Ask anything, or press the microphone and speak.');
  $('opt-awake').checked = prefs.awake;
  checkConnection();
  setupVoice();
  listenForAlerts();
  keepAwake();
}

function setBusy(on) {
  busy = on;
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
  } catch (err) {
    failed = true;
    if (err.name === 'AbortError') add('note', 'Stopped.');
    else add('err', err.message || 'Connection problem.');
  } finally {
    if (reply.classList.contains('dots') || !reply.textContent) reply.remove();
    setBusy(false);
    controller = null;
  }
  if (full.trim() && !failed) {
    history.push({ role: 'user', content: text }, { role: 'assistant', content: full.trim() });
    history = history.slice(-24);
    if (prefs.read && 'speechSynthesis' in window) {
      speechSynthesis.cancel();
      speechSynthesis.speak(new SpeechSynthesisUtterance(full.trim().slice(0, 600)));
    }
  }
  checkConnection();
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
  if (type === 'start') micState(true);
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

function alertUser(ev) {
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

// ---- go ------------------------------------------------------------------------------------------------------------
if (token) start(); else show('pair');
