import { Board, COLORS } from './board.js';
import { Chat } from './chat.js';
import { Voice } from './voice.js';
import { Fit } from './fit.js';
import { PenInput } from './pen.js';
import { Keyboard } from './keyboard.js';
import { Orb } from './orb.js';
import { dockMenus, watchDockSize } from './dockmenus.js';
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
import { PhoneLink } from './phonelink.js';
import { Sounds } from './sounds.js';
import { Boot } from './boot.js';
import { Holo } from './holo.js';
import { Picture } from './picture.js';
import { Files, FinderFolders } from './files.js';
import { Routines } from './routines.js';
import { Vision } from './vision.js';
import { Nudges } from './nudges.js';
import { Boards } from './boards.js';
import { BoardFlip } from './boardflip.js';
import { News } from './news.js';
import { ShowOff } from './showoff.js';
import { Ambient } from './ambient.js';
import { Privacy } from './privacy.js';
import { MemoryPanel } from './memory.js';

import { syncSettings } from './settings.js';
import { applyLook, currentLook, inkPalette } from './theme.js';

await syncSettings();            // take the PC's saved settings before anything reads them
applyLook();                     // and show the look they chose (look.js already did a first pass from the browser's own copy)

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

function showInkColour() { $('btn-ink').style.setProperty('--ink', COLORS[board.color]); }

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
    showInkColour();
    setTool('pen');
    document.querySelectorAll('.swatch').forEach((s) => s.classList.toggle('active', s === sw));
  });
  $('swatches').append(sw);
}

// The ink colours, the swatches and the canvases follow the look (modern or classic); switching it repaints the board in the other palette.
function refreshLook() {
  Object.assign(COLORS, inkPalette());
  document.querySelectorAll('.swatch').forEach((s) => s.style.setProperty('--sw', COLORS[s.title]));
  showInkColour();
  board.redraw();
}
window.addEventListener('jarvis-look', refreshLook);
refreshLook();

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
  if (open) { const b = $('orb-bubble'); b.classList.remove('open'); b.hidden = true; document.body.classList.remove('bubble-on'); }
  if (remember) { try { localStorage.setItem('jarvis.panel', open ? '1' : '0'); } catch { /* not saved */ } }
}
const togglePanel = () => setPanel(document.body.classList.contains('panel-hidden'));
try { setPanel(localStorage.getItem('jarvis.panel') === '1', false); } catch { setPanel(false, false); }
$('btn-panel').addEventListener('click', togglePanel);
// Tapping the orb while JARVIS is talking or working stops it; otherwise it turns the voice on or off (the Chat button opens the chat).
$('orb').addEventListener('click', () => { if (voice.speaking || chat.busy) voice.interrupt(); else voice.toggle(); });
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
const orbLabel = $('orb-label');
const bubble = $('orb-bubble');
setInterval(() => {
  const state = chat.busy ? 'thinking'
    : voice.speaking ? 'speaking'
      : voice.enabled && Date.now() < voice.awaitUntil ? 'listening'
        : voice.enabled ? 'ready' : 'idle';
  if (orbButton.dataset.state !== state) { orbButton.dataset.state = state; bigOrbEl.dataset.state = state; }
  const label = voice.supported === false ? 'Voice needs Chrome or Edge' : {
    idle: 'Voice off · tap to talk', ready: 'Say “Jarvis” · tap to mute', listening: 'Listening…', thinking: 'Thinking · tap to stop', speaking: 'Speaking · tap to stop',
  }[state];
  if (orbLabel.textContent !== label) orbLabel.textContent = label;
  // The visualizer listens to the microphone only while voice is on.
  if (voice.enabled) orb.startMic(); else orb.stopMic();
}, 150);

let bubbleTimer;
let bubbleHide;
let bubbleMs = 0;

/** Slips the bubble back up and out of sight (immediately, when the chat opens or the screen locks). */
function hideBubble(immediate = false) {
  clearTimeout(bubbleTimer);
  clearTimeout(bubbleHide);
  bubble.classList.remove('open');
  document.body.classList.remove('bubble-on');
  if (immediate) { bubble.hidden = true; return; }
  bubbleHide = setTimeout(() => { if (!bubble.classList.contains('open')) bubble.hidden = true; }, 450);
}

/** Pops the bubble out of the top of the screen with this text (paragraphs as HTML, built with plain() from anything typed or spoken). `stop` adds the Stop button. */
function showBubble(html, ms = 0, stop = false) {
  if (!document.body.classList.contains('panel-hidden')) return; // the open panel shows it already
  clearTimeout(bubbleHide);
  clearTimeout(bubbleTimer);
  const wasOut = bubble.classList.contains('open');
  bubble.innerHTML = `<div class="bubble-body">${html}</div>${stop ? stopButton : ''}`;
  bubble.hidden = false;
  document.body.classList.add('bubble-on');
  if (!wasOut) requestAnimationFrame(() => requestAnimationFrame(() => bubble.classList.add('open')));      // the pill pops out of the top edge
  bubbleMs = ms;
  if (ms) bubbleTimer = setTimeout(() => hideBubble(), ms);
}
// reading a long answer: it stays while the pointer is on it
bubble.addEventListener('pointerenter', () => clearTimeout(bubbleTimer));
bubble.addEventListener('pointerleave', () => { if (bubbleMs && bubble.classList.contains('open')) bubbleTimer = setTimeout(() => hideBubble(), 3500); });
// a toast (a short notice) sits just under the bubble
if (window.ResizeObserver) new ResizeObserver(() => document.body.style.setProperty('--bubble-h', `${bubble.offsetHeight + 12}px`)).observe(bubble);
const plain = (s) => Object.assign(document.createElement('div'), { textContent: s }).innerHTML;
const stopButton = '<button type="button" class="bubble-stop">■ Stop</button>';
chat.onStart = (text) => showBubble(`<p class="step">“${plain(text.slice(0, 160))}”</p><p class="step">Thinking…</p>`, 0, true);
chat.onProgress = (ev) => {
  const left = ev.left == null ? '' : ` · about ${ev.left} free requests left today`;
  if (ev.step > 1 || ev.left != null) bubble.querySelector('.step:last-of-type')?.replaceChildren(`Thinking · step ${ev.step} of ${ev.max}${left}`);
};
chat.onStatus = (text) => showBubble(`<p class="step">${plain(text)}</p>`, 0, true);
chat.onFinal = ({ text, failed, error }) => {
  const shown = failed ? error : text;
  if (!shown) { hideBubble(); return; }
  const body = plain(shown).replace(/\n+/g, '</p><p>');                              // the whole answer, however long (it scrolls inside the bubble)
  showBubble(`<p>${body}</p>`, Math.min(60_000, 6000 + shown.length * 45));
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
    fetch('/api/phone/push', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: 'Timer done', text: `Your ${what} is done.` }) }).catch(() => {});
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
const pictureUI = new Picture({
  el: $('picture'),
  speak: (t) => voice.speak(t),
  show: (ev) => chat.onPicture(ev),
});
pictureUI.fit = () => {                    // the card changed shape: keep all of it on the wall
  const l = widgets.layout.picture;
  if (!l) return;
  const b = widgets.box('picture');
  const down = b.top + b.height - 1070;
  if (down > 0) l.y = Math.max(8, Math.round(l.y - down));
  const out = (l.a === 'r' ? 0 : b.left + b.width - (widgets.board.w - 8));
  if (out > 0) l.x = Math.max(8, Math.round(l.x - out));
  if (l.a === 'r' && l.x < 8) l.x = 8;
  widgets.apply('picture');
  widgets.saveLayout();
};
widgets.register({ id: 'picture', title: 'Picture', icon: '▣', blurb: 'A photo on the wall: ask JARVIS to show you a picture of something, or share one from your phone',
  el: $('picture'), onShow: () => pictureUI.onShow(), onHide: () => pictureUI.onHide() });
const filesUI = new Files({ el: $('files'), speak: (t) => voice.speak(t), show: (ev) => chat.onFiles(ev), showPicture: (ev) => chat.onPicture(ev) });
widgets.register({ id: 'files', title: 'Files', icon: '🗂', blurb: 'What JARVIS found when you asked it to find a file (only in the folders you chose)', el: $('files') });
chat.onFiles = (ev) => {
  if (!filesUI.show(ev)) return;
  widgets.set('files', true, false);       // not remembered: a result card shouldn't come back after a restart
  sounds.play('holo');
  ambient.poke();
};
const finderFolders = new FinderFolders({ root: $('status-menu') });
const routinesUI = new Routines({ root: $("status-menu"), speak: (t) => voice.speak(t) });
const nudgesUI = new Nudges({ root: $("status-menu"), busy: () => chat.busy || voice.speaking, speak: (t) => voice.speak(t), show: (t) => showBubble(`<p><b>JARVIS</b></p><p>${plain(t)}</p>`, Math.min(40_000, 10_000 + t.length * 45)) });
const visionUI = new Vision({ root: $("status-menu"), speak: (t) => voice.speak(t), show: (t) => showBubble(`<p>${plain(t)}</p>`, Math.min(40_000, 6000 + t.length * 45)) });
routinesUI.refresh();
chat.onPicture = (ev) => {
  if (!pictureUI.show(ev)) return;
  widgets.set('picture', true, false);     // not remembered: a "show me" card shouldn't come back after a restart
  sounds.play('holo');
  ambient.poke();
};
chat.onHolo = (ev) => {
  widgets.set('holo', true, false);       // not remembered: a "show me" card shouldn't come back after a restart
  holo.show(ev);
  sounds.play('holo');
  ambient.poke();
};
// "Jarvis, show off": a random hologram on the left and code being typed on the right; the same words put it away.
const showoff = new ShowOff({
  root: $('showoff'), sounds, speak: (t) => voice.speak(t),
  getLine: (on) => fetch(`/api/persona/showoff?on=${on}`).then((r) => r.json()).then((d) => d.text),
});
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
pictureUI.fallback = lightsUI.fallback;
filesUI.fallback = lightsUI.fallback;
nudgesUI.fallback = lightsUI.fallback;
const musicUI = new Music({ el: $('music'), speak: (t) => voice.speak(t), toast });
widgets.register({ id: 'music', title: 'Music', icon: '🎵', blurb: 'Play YouTube Music on your speakers',
  el: $('music'), onShow: () => musicUI.onShow(), onHide: () => musicUI.onHide() });
widgets.restore();
Object.assign(window.jarvis, { usage, weather, timers, widgets, system, lights: lightsUI, music: musicUI, sounds, holo, showoff });
const status = new Status({ button: $('btn-status'), menu: $('status-menu'), banner: $('offline-banner'), board, voice, pen, toast });
dockMenus([{ button: $('btn-ink'), menu: $('ink-menu') }, { button: $('btn-more'), menu: $('more-menu'), closeOnChoice: true }, { button: $('btn-boards'), menu: $('boards-menu'), closeOnChoice: true }]);      // Boards opens from a row in More, or from the name tag
board.flip = new BoardFlip({ board });                           // the pull-back, showcase and fly-forward when switching boards
const boardsUI = new Boards({ board, button: $('btn-boards'), menu: $('boards-menu'), pill: $('board-name'), speak: (t) => voice.speak(t),
  show: (t) => showBubble(`<p><b>${plain(t)}</b></p>`, 2500) });
window.jarvis.boards = boardsUI;
watchDockSize($('toolbar'));
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
// A saved reminder is due: a chime, the words out loud, and an amber note on the wall that stays until you close it.
pen.onReminder = (m) => {
  ambient.poke();
  sounds.play('alert');
  showBubble(`<p><b>${plain(m.title)}</b></p><p>${plain(m.text)}</p>`, 20_000);
  board.addNote({ text: `⏰ ${m.text}`, color: 'amber' });
  voice.speak(m.speak);
};
// A phone paired with JARVIS asked for something that changes the wall (a note, a timer, a widget): do it here.
pen.onPhoneEvent = (ev) => { ambient.poke(); chat.applyRemote(ev); };
pen.onCommand = (text) => { ambient.poke(); showoff.handleVoice(text); };
pen.onWakeCommand = (text) => { ambient.poke(); voice.heardCommand(text); };
const phoneLink = new PhoneLink({ root: $('status-menu'), fit: () => {} });
status.onOpen = () => { phoneLink.refresh(); finderFolders.refresh(); routinesUI.refresh(); visionUI.cameras(); nudgesUI.refresh(); };
// "Claude has finished in JARVIS": announced by the Claude Code hook (see README, "Claude Code alerts").
pen.onNotify = (m) => {
  ambient.poke();
  sounds.play('ok');
  showBubble(`<p><b>${plain(m.title)}</b></p><p>${plain(m.text)}</p>`, 15_000);
  if (m.speak) voice.speak(m.speak);
};
pen.onBoards = () => board.sync();                              // a board was added, switched or deleted (from the phone, or another screen)
pen.onPrivacy = () => privacy.refresh();                       // the phone locked or unlocked the screen
pen.onNudge = (m) => { ambient.poke(); sounds.play('ok'); nudgesUI.deliver(m); };      // JARVIS speaks first
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
$('opt-look').value = currentLook();
$('opt-look').addEventListener('change', (e) => { applyLook(e.target.value); toast(e.target.value === 'classic' ? 'Classic look' : 'Modern look'); });
$('opt-sounds').checked = sounds.enabled;
$('opt-sounds').addEventListener('change', (e) => { sounds.setEnabled(e.target.checked); if (e.target.checked) sounds.play('ok'); });
$('opt-boot').checked = localStorage.getItem('jarvis.boot') !== '0';
$('opt-boot').addEventListener('change', (e) => { try { localStorage.setItem('jarvis.boot', e.target.checked ? '1' : '0'); } catch { /* not remembered */ } });
$('boot-replay').addEventListener('click', () => { status.toggle(false); boot.run(status.info || {}, voice.supported); });
let voiceRestored = false;
status.onInfo = (info) => {
  maybeBoot(info);
  const wake = info.wake || {};
  voice.offlineCommands = Boolean(wake.commands);
  voice.setOffline(Boolean(wake.running));
  if (!voiceRestored) { voiceRestored = true; voice.restore(Boolean(wake.running)); }      // a reload must not leave the microphone off
  if (voice.supported) {
    $('voice-note').textContent = wake.running && !wake.listening
      ? 'Voice is off, so this PC’s microphone is closed: nothing can hear “Jarvis”. Turn voice on (tap the orb, or press M) to use the offline wake word.'
      : wake.running
      ? `The wake word “Jarvis” is detected on this PC (offline)${wake.device ? `, listening on: ${wake.device}` : ''}. ${wake.commands ? 'It also understands the command after it on this PC, so nothing is sent to the internet, and its microphone is only open while voice is on.' : 'Only the command after it goes to the browser’s speech service.'}${wake.last_text ? ` Last heard: “${wake.last_text}”.` : ''}`
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
  onLocked: () => { voice.pauseForPrivacy(); showoff.stop(); voice.cancelSpeech?.(); setPanel(false, false); hideBubble(true); status.toggle(false); widgets.toggleMenu(false); },
  onUnlocked: () => { board.sync(); status.poll(); voice.resumeIfPaused(); },
  onState: (s) => { $('privacy-phone-only').checked = Boolean(s.phone_only); },
});
window.jarvis.privacy = privacy;
voice.special = (command) => privacy.handleVoice(command) || boardsUI.handleVoice(command) || showoff.handleVoice(command) || system.handleVoice(command) || routinesUI.handleVoice(command) || lightsUI.handleVoice(command) || musicUI.handleVoice(command) || filesUI.handleVoice(command) || nudgesUI.handleVoice(command) || visionUI.handleVoice(command) || pictureUI.handleVoice(command) || phoneLink.handleVoice(command, (t) => voice.speak(t)) || appsUI.handleVoice(command);
chat.onTyped = (text) => voice.special(text);       // typing "show off", "lights off"... in the chat box works like saying it
$('privacy-lock').addEventListener('click', () => privacy.lock());
$('privacy-phone-only').addEventListener('change', async (e) => {
  const res = await fetch('/api/privacy/phone-only', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ on: e.target.checked }) });
  if (res.ok) privacy.set(await res.json()); else privacy.refresh();
});
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
  busy: () => showoff.on || chat.busy || voice.speaking || keyboard.el?.hidden === false || !$('widget-menu').hidden || !$('status-menu').hidden
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
  else if (key === '[') board.step(-1);                          // the previous whiteboard
  else if (key === ']') board.step(1);                           // the next one
  else if (key === 'f') toggleFullscreen();
  else if (key === 'm') voice.toggle();
  else if (key === 'l') toggleLights();
  else if (key === 'j') fit.toggle();
  else if (key === 'k') pen.toggleCalibration();
  else if (key === 'b') keyboard.toggle();
  else if (key === 'u') widgets.toggle('usage');
  else if (key === 'a') ambient.toggle();
  else if (key === 'h') privacy.lock();
  else if (key === 's') status.toggle();
  else if (key === 'w') widgets.toggleMenu();
  else if (key === 't') setTouch(!document.body.classList.contains('touch'), true);
  else if (e.key === 'Tab') { e.preventDefault(); togglePanel(); }
});
