import { Board, COLORS } from './board.js';
import { Chat } from './chat.js';
import { Voice } from './voice.js';
import { Fit } from './fit.js';
import { PenInput } from './pen.js';
import { Keyboard } from './keyboard.js';
import { Orb } from './orb.js';
import { Usage } from './usage.js';
import { Widgets } from './widgets.js';
import { Weather } from './weather.js';
import { Timers, formatTime } from './timer.js';
import { Status } from './status.js';
import { System } from './system.js';
import { Lights } from './lights.js';
import { Music } from './music.js';
import { Apps } from './apps.js';
import { Alerts } from './alerts.js';
import { Sounds } from './sounds.js';
import { Boot } from './boot.js';
import { Holo } from './holo.js';
import { News } from './news.js';
import { Ambient } from './ambient.js';
import { Privacy } from './privacy.js';
import { MemoryPanel } from './memory.js';

import { syncSettings } from './settings.js';

await syncSettings();            // take the PC's saved settings before anything reads them

const $ = (id) => document.getElementById(id);

// ---- toast -----------------------------------------------------------------
let toastTimer;
function toast(text) {
  const el = $('toast');
  el.textContent = text;
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 2200);
}

// ---- board + toolbar -------------------------------------------------------
const board = new Board({
  stage: $('stage'), boardEl: $('board'), canvas: $('ink'), notesEl: $('notes'), dockEl: $('toolbar'),
});

function setTool(tool) {
  board.tool = tool;
  document.querySelectorAll('[data-tool]').forEach((b) => b.classList.toggle('active', b.dataset.tool === tool));
  $('ink').style.cursor = tool === 'eraser' ? 'cell' : 'crosshair';
}
document.querySelectorAll('[data-tool]').forEach((b) => b.addEventListener('click', () => setTool(b.dataset.tool)));

for (const name of ['cyan', 'white', 'amber', 'green', 'red']) {
  const sw = document.createElement('button');
  sw.className = `swatch${name === board.color ? ' active' : ''}`;
  sw.style.setProperty('--sw', COLORS[name]);
  sw.title = name;
  sw.addEventListener('click', () => {
    board.color = name;
    setTool('pen');
    document.querySelectorAll('.swatch').forEach((s) => s.classList.toggle('active', s === sw));
  });
  $('swatches').append(sw);
}

$('size').addEventListener('input', (e) => { board.size = Number(e.target.value); });
$('btn-note').addEventListener('click', () => { board.addNote({ color: board.color }); });
$('btn-undo').addEventListener('click', () => board.undo());
$('btn-redo').addEventListener('click', () => board.redo());
$('btn-clear').addEventListener('click', () => { board.clearInk(); toast('Ink cleared (Ctrl+Z to undo)'); });

function toggleFullscreen() {
  if (document.fullscreenElement) document.exitFullscreen();
  else document.documentElement.requestFullscreen?.();
}
function setLights(on) {
  document.body.classList.toggle('no-lights', !on);
  $('btn-lights').classList.toggle('active', on);
  try { localStorage.setItem('jarvis.lights', on ? '1' : '0'); } catch { /* not saved, fine */ }
}
function toggleLights() { setLights(document.body.classList.contains('no-lights')); }
try { setLights(localStorage.getItem('jarvis.lights') !== '0'); } catch { /* default: on */ }
$('btn-lights').addEventListener('click', toggleLights);

const keyboard = new Keyboard({ el: $('keyboard'), board, dock: $('toolbar'), toast });
$('btn-kb').addEventListener('click', () => keyboard.toggle());

// Touch mode: bigger controls for using the interface with the pen from across the room. It switches on by
// itself when the pen tracker connects; T (or the ☝ button) overrides that and remembers the choice.
let touchChoice = null; // '1' | '0' | null (automatic)
try { touchChoice = localStorage.getItem('jarvis.touch'); } catch { /* automatic */ }
function setTouch(on, manual = false) {
  document.body.classList.toggle('touch', on);
  $('btn-touch').classList.toggle('active', on);
  if (manual) {
    touchChoice = on ? '1' : '0';
    try { localStorage.setItem('jarvis.touch', touchChoice); } catch { /* not saved */ }
  }
}
if (touchChoice) setTouch(touchChoice === '1');
$('btn-touch').addEventListener('click', () => setTouch(!document.body.classList.contains('touch'), true));

const pen = new PenInput({
  board, boardEl: $('board'), button: $('btn-pen'), caption: $('caption'), toast, keyboard,
  onTracker: (up) => { if (touchChoice === null) setTouch(up); },
});
const fit = new Fit({ app: $('app'), pattern: $('testpattern'), ui: $('fit-ui') });
$('btn-fit').addEventListener('click', () => fit.toggle());

$('btn-full').addEventListener('click', toggleFullscreen);

// The chat panel starts closed so the board has the whole wall; the orb is JARVIS's face. The chat button,
// the orb and Tab open it, and the choice is remembered.
function setPanel(open, remember = true) {
  document.body.classList.toggle('panel-hidden', !open);
  $('btn-panel').classList.toggle('active', open);
  if (open) $('orb-bubble').hidden = true;
  if (remember) { try { localStorage.setItem('jarvis.panel', open ? '1' : '0'); } catch { /* not saved */ } }
}
const togglePanel = () => setPanel(document.body.classList.contains('panel-hidden'));
try { setPanel(localStorage.getItem('jarvis.panel') === '1', false); } catch { setPanel(false, false); }
$('btn-panel').addEventListener('click', togglePanel);
// Tapping the orb while JARVIS is talking or working stops it; otherwise it opens or closes the chat.
$('orb').addEventListener('click', () => { if (voice.speaking || chat.busy) voice.interrupt(); else togglePanel(); });
// ---- chat ------------------------------------------------------------------
const chat = new Chat(
  { log: $('log'), form: $('composer'), input: $('input'), includeBoard: $('include-board'), spendEl: $('spend') },
  board,
  toast,
);

const voice = new Voice({ button: $('btn-mic'), caption: $('caption'), chat, toast });
window.jarvis = { board, chat, voice, fit, pen, keyboard }; // handy for poking at things from the browser console

// ---- the orb follows what JARVIS is doing --------------------------------------
// idle: voice off · ready: listening for "Jarvis" · listening: waiting for your command · thinking · speaking.
// With the chat closed, a bubble next to the orb shows the steps and then the answer.
const orbButton = $('orb');
const orb = new Orb({ canvas: $('orb-canvas'), button: orbButton });
const bigOrbEl = $('orb-big');
const bigOrb = new Orb({ canvas: $('orb-big-canvas'), button: bigOrbEl, follow: orb });   // the calm-mode orb: same states, same microphone
window.jarvis.orb = orb;
window.jarvis.bigOrb = bigOrb;
const bubble = $('orb-bubble');
let bubbleTimer;
setInterval(() => {
  const state = chat.busy ? 'thinking'
    : voice.speaking ? 'speaking'
      : voice.enabled && Date.now() < voice.awaitUntil ? 'listening'
        : voice.enabled ? 'ready' : 'idle';
  if (orbButton.dataset.state !== state) { orbButton.dataset.state = state; bigOrbEl.dataset.state = state; }
  // The visualizer listens to the microphone only while voice is on.
  if (voice.enabled) orb.startMic(); else orb.stopMic();
}, 150);

function showBubble(html, ms = 0) {
  if (!document.body.classList.contains('panel-hidden')) return; // the open panel shows it already
  bubble.innerHTML = html;
  bubble.hidden = false;
  clearTimeout(bubbleTimer);
  if (ms) bubbleTimer = setTimeout(() => { bubble.hidden = true; }, ms);
}
const plain = (s) => Object.assign(document.createElement('div'), { textContent: s }).innerHTML;
const stopButton = '<button type="button" class="bubble-stop">■ Stop</button>';
chat.onStart = (text) => showBubble(`<p class="step">“${plain(text.slice(0, 160))}”</p><p class="step">Thinking…</p>${stopButton}`);
chat.onProgress = (ev) => {
  const left = ev.left == null ? '' : ` · about ${ev.left} free requests left today`;
  if (ev.step > 1 || ev.left != null) bubble.querySelector('.step:last-of-type')?.replaceChildren(`Thinking · step ${ev.step} of ${ev.max}${left}`);
};
chat.onStatus = (text) => showBubble(`<p class="step">${plain(text)}</p>${stopButton}`);
chat.onFinal = ({ text, failed, error }) => {
  const shown = failed ? error : text;
  if (!shown) { bubble.hidden = true; return; }
  const body = plain(shown.length > 700 ? `${shown.slice(0, 700)}…` : shown).replace(/\n+/g, '</p><p>');
  showBubble(`<p>${body}</p>`, Math.min(30_000, 6000 + shown.length * 45));
};
chat.onNeedsYou = () => setPanel(true, false);

// ---- widgets ---------------------------------------------------------------------
// Cards on the board. The widgets button (or W) opens a menu to add or remove them; JARVIS can also add, remove
// and use them when asked ("show the weather", "set a timer for ten minutes").
const widgets = new Widgets({ board, button: $('btn-widgets'), menu: $('widget-menu'), list: $('widget-list'), reset: $('widget-reset') });
pen.widgets = widgets; // so the IR pen can drag and resize cards too
const usage = new Usage({ el: $('usage') });
const weather = new Weather({ el: $('weather') });
const timers = new Timers({
  el: $('timer'),
  onDone: (t) => {
    const what = t.label ? `${t.label} timer` : `${Math.round(t.total / 60000)} minute timer`;
    widgets.set('timer', true, false);
    ambient.poke();
    showBubble(`<p>⏰ ${plain(what)} is done.</p>`, 20_000);
    fetch(`/api/persona/timer?what=${encodeURIComponent(what)}`).then((r) => r.json()).then((d) => voice.speak(d.text), () => voice.speak(`Your ${what} is done.`));
  },
});
widgets.register({ id: 'timer', title: 'Timers', icon: '⏱', blurb: 'Countdown timers that ring when they finish', el: $('timer') });
widgets.register({ id: 'weather', title: 'Weather', icon: '⛅', blurb: 'Current weather and a 5-day forecast for your city',
  el: $('weather'), onShow: () => weather.onShow(), onHide: () => weather.onHide() });
widgets.register({ id: 'usage', title: 'Token usage', icon: '📊', blurb: 'Claude Code and JARVIS tokens, with averages',
  el: $('usage'), onShow: () => usage.onShow(), onHide: () => usage.onHide() });
const sounds = new Sounds();
widgets.onToggle = (id, show) => sounds.play(show ? 'open' : 'close');
const holo = new Holo({ el: $('holo') });
widgets.register({ id: 'holo', title: 'Hologram', icon: '◈', blurb: 'Rotating 3D models and animated charts: ask JARVIS to show you something',
  el: $('holo'), onShow: () => holo.onShow(), onHide: () => holo.onHide() });
chat.onHolo = (ev) => {
  widgets.set('holo', true, false);       // not remembered: a "show me" card shouldn't come back after a restart
  holo.show(ev);
  sounds.play('holo');
  ambient.poke();
};
const newsUI = new News({ el: $('news') });
widgets.register({ id: 'news', title: 'News ticker', icon: '📰', blurb: 'Scrolling headlines from public news feeds',
  el: $('news'), onShow: () => newsUI.onShow(), onHide: () => newsUI.onHide() });
const system = new System({ el: $('system'), speak: (t) => voice.speak(t), show: (html, ms) => showBubble(html, ms) });
widgets.register({ id: 'system', title: 'System', icon: '🖥', blurb: 'PC and JARVIS health: processor, memory, drives, internet, alerts',
  el: $('system'), onShow: () => system.onShow(), onHide: () => system.onHide() });
const lightsUI = new Lights({ el: $('lights'), speak: (t) => voice.speak(t), toast });
widgets.register({ id: 'lights', title: 'Lights', icon: '💡', blurb: 'Govee lights: on/off, brightness and colour',
  el: $('lights'), onShow: () => lightsUI.onShow(), onHide: () => lightsUI.onHide() });
lightsUI.fallback = (command) => { if (!chat.busy) chat.ask(command, { speak: true }); };
const appsUI = new Apps({ speak: (t) => voice.speak(t) });
appsUI.fallback = lightsUI.fallback;
const musicUI = new Music({ el: $('music'), speak: (t) => voice.speak(t), toast });
widgets.register({ id: 'music', title: 'Music', icon: '🎵', blurb: 'Play YouTube Music on your speakers',
  el: $('music'), onShow: () => musicUI.onShow(), onHide: () => musicUI.onHide() });
widgets.restore();
Object.assign(window.jarvis, { usage, weather, timers, widgets, system, lights: lightsUI, music: musicUI, sounds, holo });
const status = new Status({ button: $('btn-status'), menu: $('status-menu'), banner: $('offline-banner'), board, voice, pen, toast });
$('export-png').addEventListener('click', () => status.exportPng());
$('export-json').addEventListener('click', () => status.exportJson());
$('show-backups').addEventListener('click', () => status.showBackups());
$('mcp-reload').addEventListener('click', () => status.reloadMcp());
$('show-activity').addEventListener('click', () => status.showActivity());
$('activity-close').addEventListener('click', () => { $('activity-modal').hidden = true; });
$('activity-modal').addEventListener('click', (e) => { if (e.target === $('activity-modal')) $('activity-modal').hidden = true; });

// Voice settings: which voice JARVIS speaks with, how fast, how low. And the offline wake word, when the PC has it.
const pickVoice = $('voice-pick');
function fillVoices() {
  if (!voice.supported) return;
  pickVoice.replaceChildren(...voice.voices().map((v) => Object.assign(document.createElement('option'), {
    value: v.name, textContent: `${v.name.replace(/^Microsoft /, '')} (${v.lang})`, selected: v === voice.voice,
  })));
}
if (voice.supported) {
  fillVoices();
  speechSynthesis.addEventListener('voiceschanged', fillVoices);
  $('voice-rate').value = voice.settings.rate;
  $('voice-pitch').value = voice.settings.pitch;
  pickVoice.addEventListener('change', () => { voice.configure({ name: pickVoice.value }); voice.speak('This is how I sound.'); });
  $('voice-rate').addEventListener('change', () => voice.configure({ rate: Number($('voice-rate').value) }));
  $('voice-pitch').addEventListener('change', () => voice.configure({ pitch: Number($('voice-pitch').value) }));
  $('voice-test').addEventListener('click', () => voice.speak('Good evening. This is how I sound.'));
} else {
  $('voice-note').textContent = 'Voice needs Chrome or Edge.';
}
voice.onCue = () => sounds.play('listen');               // one listening sound, whether the name was heard here or by the PC
chat.onStopped = () => voice.cancelSpeech();             // the Stop button and the chat panel's Stop also silence the voice
pen.onWake = () => { ambient.poke(); voice.wake(); };

// Problems the PC's monitor finds (full drive, no internet...) arrive over the same connection as pen events: each becomes
// a red sticky note that is also spoken, and goes away by itself when the problem does.
const alerts = new Alerts({ board, speak: (t) => voice.speak(t), show: (html, ms) => showBubble(html, ms), poke: () => ambient.poke(), chime: () => sounds.play('alert') });
pen.onAlert = (m) => alerts.handle(m);
// "Claude has finished in JARVIS": announced by the Claude Code hook (see README, "Claude Code alerts").
pen.onNotify = (m) => {
  ambient.poke();
  sounds.play('ok');
  showBubble(`<p><b>${plain(m.title)}</b></p><p>${plain(m.text)}</p>`, 15_000);
  if (m.speak) voice.speak(m.speak);
};
window.jarvis.alerts = alerts;
// The start-up sequence plays once each time the JARVIS server starts (not on every page reload).
const boot = new Boot({ overlay: $('boot'), sounds, speak: (t) => voice.speak(t),
  getGreeting: () => fetch('/api/persona/boot').then((r) => r.json()).then((d) => d.text) });
let bootChecked = false;
function maybeBoot(info) {
  if (bootChecked) return;
  bootChecked = true;
  try {
    if (localStorage.getItem('jarvis.boot') === '0' || privacy.locked) return;
    if (localStorage.getItem('jarvis.boot.seen') === String(info.started)) return;
    localStorage.setItem('jarvis.boot.seen', String(info.started));
  } catch { return; }
  boot.run(info, voice.supported);
}
$('opt-sounds').checked = sounds.enabled;
$('opt-sounds').addEventListener('change', (e) => { sounds.setEnabled(e.target.checked); if (e.target.checked) sounds.play('ok'); });
$('opt-boot').checked = localStorage.getItem('jarvis.boot') !== '0';
$('opt-boot').addEventListener('change', (e) => { try { localStorage.setItem('jarvis.boot', e.target.checked ? '1' : '0'); } catch { /* not remembered */ } });
$('boot-replay').addEventListener('click', () => { status.toggle(false); boot.run(status.info || {}, voice.supported); });
let voiceRestored = false;
status.onInfo = (info) => {
  maybeBoot(info);
  const wake = info.wake || {};
  voice.setOffline(Boolean(wake.running));
  if (!voiceRestored) { voiceRestored = true; voice.restore(Boolean(wake.running)); }      // a reload must not leave the microphone off
  if (voice.supported) {
    $('voice-note').textContent = wake.running
      ? `The wake word “Jarvis” is detected on this PC (offline)${wake.device ? `, listening on: ${wake.device}` : ''}. Only the command after it goes to the browser’s speech service.${wake.last_text ? ` Last heard: “${wake.last_text}”.` : ''}`
      : wake.error
        ? `Offline wake word is on but not working: ${wake.error}`
        : 'The wake word is heard by the browser’s speech service (it sends what it hears to Google or Microsoft). For an offline one, see the README.';
  }
};
window.jarvis.status = status;

// Privacy screen: hides everything and makes the server stop answering until the unlock code is given.
const privacy = new Privacy({
  overlay: $('privacy'),
  toast,
  onLocked: () => { voice.cancelSpeech?.(); setPanel(false, false); bubble.hidden = true; status.toggle(false); widgets.toggleMenu(false); },
  onUnlocked: () => { board.sync(); status.poll(); },
});
window.jarvis.privacy = privacy;
voice.special = (command) => privacy.handleVoice(command) || system.handleVoice(command) || lightsUI.handleVoice(command) || musicUI.handleVoice(command) || appsUI.handleVoice(command);
$('privacy-lock').addEventListener('click', () => privacy.lock());
$('privacy-setcode').addEventListener('click', () => {
  $('privacy-form').hidden = !$('privacy-form').hidden;
  $('privacy-current').hidden = !privacy.hasCode;
});
async function saveCode(code) {
  const res = await fetch('/api/privacy/code', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code, current: $('privacy-current').value }),
  });
  const note = $('privacy-note');
  if (res.ok) {
    note.textContent = code ? 'Unlock code saved.' : 'Code removed: the screen now unlocks with a touch.';
    $('privacy-new').value = '';
    $('privacy-current').value = '';
    privacy.set(await res.json());
    $('privacy-current').hidden = !privacy.hasCode;
  } else {
    note.textContent = (await res.json().catch(() => ({}))).detail || 'That didn’t work.';
  }
}
$('privacy-form').addEventListener('submit', (e) => { e.preventDefault(); const v = $('privacy-new').value.trim(); if (v) saveCode(v); });
$('privacy-remove').addEventListener('click', () => saveCode(null));

// Ambient mode: after a quiet spell the wall calms down (dock fades, drawing dims, the clock grows). Anything wakes it.
const ambient = new Ambient({
  select: $('ambient-minutes'),
  busy: () => chat.busy || voice.speaking || keyboard.el?.hidden === false || !$('widget-menu').hidden || !$('status-menu').hidden
    || document.body.classList.contains('kb-open') || pen.calibrating || !$('fit-ui').hidden
    || Boolean(document.activeElement?.closest?.('input, textarea, [contenteditable]')) || timers.timers.some((t) => t.done),
});
window.jarvis.ambient = ambient;
// In calm mode the widgets are hidden, so a timer that is still running shows under the big orb.
setInterval(() => {
  if (!document.body.classList.contains('ambient')) return;
  const running = timers.timers.filter((t) => !t.done).map((t) => ({ t, left: timers.remaining(t) })).sort((a, b) => a.left - b.left)[0];
  $('ambient-timer').textContent = running ? `⏱ ${formatTime(running.left)}${running.t.label ? `  ·  ${running.t.label}` : ''}` : '';
}, 500);
pen.onActivity = () => ambient.poke();
chat.onWidget = (ev) => widgets.set(ev.name, ev.show);
chat.onTimer = (ev) => {
  if (ev.action === 'start') { timers.add(ev.seconds, ev.label || ''); widgets.set('timer', true, false); }
  else timers.cancel(ev.label || '');
};
const previousFinal = chat.onFinal;
chat.onFinal = (info) => { previousFinal(info); if (usage.visible) usage.refresh(); };
bubble.addEventListener('click', (e) => {
  if (e.target.closest('.bubble-stop')) { voice.interrupt(); return; }   // Stop ends the answer and the speaking; anything else opens the chat
  setPanel(true, false);
});

fetch('/api/status')
  .then((r) => r.json())
  .then((s) => {
    chat.setUsage(s.requests_today, s.model);
    if (!s.key_set) {
      chat.addMessage('error', `No API key found. Copy .env.example to .env, paste your key after ${s.key_env}=, then restart run.bat.`);
    }
  })
  .catch(() => { $('spend').textContent = 'server offline'; });

// ---- memory window ---------------------------------------------------------
const memory = new MemoryPanel({
  modal: $('memory-modal'), list: $('facts'), search: $('memory-search'), count: $('memory-count'),
  form: $('fact-form'), input: $('fact-input'), kind: $('fact-kind'), toast,
});
$('btn-memory').addEventListener('click', () => memory.open());
$('memory-close').addEventListener('click', () => memory.close());
window.jarvis.memory = memory;

// ---- clock widget ----------------------------------------------------------
function tick() {
  const now = new Date();
  $('clock-time').textContent = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  $('clock-date').textContent = now.toLocaleDateString([], { weekday: 'long', month: 'long', day: 'numeric' });
  $('ambient-time').textContent = $('clock-time').textContent;
  $('ambient-date').textContent = $('clock-date').textContent;
}
tick();
setInterval(tick, 10_000);

// ---- shortcuts ---------------------------------------------------------------
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && (voice.speaking || chat.busy)) { e.preventDefault(); voice.interrupt(); return; }   // Esc cuts JARVIS off
  const typing = e.target.closest('input, textarea, [contenteditable]');
  if ((e.ctrlKey || e.metaKey) && !typing) {
    if (e.key === 'z' && !e.shiftKey) { e.preventDefault(); board.undo(); }
    else if (e.key === 'y' || (e.key === 'z' && e.shiftKey)) { e.preventDefault(); board.redo(); }
    return;
  }
  if (typing || e.ctrlKey || e.altKey) return;
  const key = e.key.toLowerCase();
  if (key === 'p') setTool('pen');
  else if (key === 'e') setTool('eraser');
  else if (key === 'n') { e.preventDefault(); board.addNote({ color: board.color }); }
  else if (key === 'f') toggleFullscreen();
  else if (key === 'm') voice.toggle();
  else if (key === 'l') toggleLights();
  else if (key === 'j') fit.toggle();
  else if (key === 'k') pen.toggleCalibration();
  else if (key === 'b') keyboard.toggle();
  else if (key === 'u') widgets.toggle('usage');
  else if (key === 'a') ambient.toggle();
  else if (key === 'h') privacy.lock();
  else if (key === 'w') widgets.toggleMenu();
  else if (key === 't') setTouch(!document.body.classList.contains('touch'), true);
  else if (e.key === 'Tab') { e.preventDefault(); togglePanel(); }
});
