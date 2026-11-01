// Checks how Voice (web/voice.js) reacts when someone talks over JARVIS. Runs under Node with stand-ins for the browser's speech
// APIs; tests/test_js_voice.py runs it as part of the normal test suite. Prints one line per check; exits 1 if any fails.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const log = [];
class FakeRecognition {
  start() { log.push('recognition.start'); }
  abort() { log.push('recognition.abort'); }
}
class FakeUtterance { constructor(text) { this.text = text; } }
let cancelled = 0, spoken = [];
const synth = {
  speaking: true, pending: false, cancel() { cancelled += 1; this.speaking = false; }, speak(u) { spoken.push(u.text); },
  getVoices: () => [], addEventListener() {},
};
globalThis.window = globalThis;
globalThis.SpeechRecognition = FakeRecognition;
globalThis.SpeechSynthesisUtterance = FakeUtterance;
globalThis.speechSynthesis = synth;
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
const toasts = [];

const { Voice, parseWake, maskName } = await import(pathToFileURL(path.resolve('web/voice.js')).href);

function setup({ offline = false, busy = false, enabled = true } = {}) {
  log.length = 0; cancelled = 0; spoken = []; store.clear(); toasts.length = 0;
  const asked = [];
  const chat = {
    busy, onReply: null, stops: 0,
    stop() { if (!this.busy) return; this.stops += 1; this.busy = false; },
    async interrupt() { this.stop(); },
    ask(text) { asked.push(text); },
  };
  const button = { addEventListener() {}, classList: { add() {}, remove() {} }, title: '' };
  const caption = { textContent: '', classList: { add() {}, remove() {} } };
  const voice = new Voice({ button, caption, chat, toast: (t) => toasts.push(t) });
  voice.enabled = enabled;
  voice.offline = offline;
  return { voice, chat, asked };
}
const startSpeaking = (voice) => { voice.speak('This is a long answer. It has several sentences. Keep talking.'); synth.speaking = true; return voice; };
const results = (...items) => ({ resultIndex: 0, results: items.map(([transcript, isFinal]) => Object.assign([{ transcript }], { isFinal })) });
const tick = () => new Promise((r) => setTimeout(r, 5));

const checks = {
  async 'saying Jarvis over an answer (PC wake word) stops the speech and starts listening'() {
    const { voice } = setup({ offline: true });
    startSpeaking(voice);
    assert.equal(voice.speaking, true);
    voice.wake();
    assert.equal(voice.speaking, false);
    assert.ok(cancelled >= 1);
    assert.ok(log.includes('recognition.start'), 'it should now be listening for the command');
    assert.equal(voice.ignoreUntil, 0, 'no waiting for the room to go quiet');
  },
  async 'the wake word also drops an answer that is still being worked out'() {
    const { voice, chat } = setup({ offline: true, busy: true });
    voice.wake();
    await tick();
    assert.equal(chat.stops, 1);
    assert.ok(log.includes('recognition.start'));
  },
  async 'with browser listening, hearing "Jarvis ..." while speaking cuts in at once (before the sentence ends)'() {
    const { voice } = setup();
    startSpeaking(voice);
    voice.onResult(results(['jarvis what about', false]));
    assert.equal(voice.speaking, false);
  },
  async 'and what is said next is run as the new command, not thrown away'() {
    const { voice, asked } = setup();
    startSpeaking(voice);
    voice.onResult(results(['jarvis what about tomorrow', true]));
    await tick();
    assert.deepEqual(asked, ['what about tomorrow']);
  },
  async 'a bare "Jarvis" over an answer stops it and waits for the command'() {
    const { voice, asked } = setup();
    startSpeaking(voice);
    voice.onResult(results(['jarvis', true]));
    await tick();
    assert.equal(voice.speaking, false);
    assert.deepEqual(asked, []);
    assert.ok(voice.awaitUntil > Date.now(), 'the next sentence should count as the command');
  },
  async 'room noise or its own voice (no name said) does not interrupt'() {
    const { voice, asked } = setup();
    startSpeaking(voice);
    voice.onResult(results(['the weather tomorrow will be sunny', false]));
    voice.onResult(results(['the weather tomorrow will be sunny', true]));
    await tick();
    assert.equal(voice.speaking, true);
    assert.deepEqual(asked, []);
  },
  async '"Jarvis, stop" stops and asks nothing'() {
    const { voice, asked, chat } = setup({ busy: true });
    startSpeaking(voice);
    voice.onResult(results(['jarvis stop', true]));
    await tick();
    assert.equal(voice.speaking, false);
    assert.deepEqual(asked, []);
    assert.ok(chat.stops >= 1);
  },
  async 'a new command while JARVIS is still working replaces the old one'() {
    const { voice, asked, chat } = setup({ busy: true });
    voice.handleFinal('jarvis turn the lights off');
    await tick();
    assert.equal(chat.stops, 1);
    assert.deepEqual(asked, ['turn the lights off']);
  },
  async 'interrupt() is safe when nothing is happening'() {
    const { voice } = setup();
    synth.speaking = false;
    await voice.interrupt();
    assert.equal(voice.speaking, false);
  },
  async 'a reload must not leave the microphone off: voice comes back the way it was left'() {
    let { voice } = setup({ offline: true, enabled: false });
    voice.restore(true);
    assert.equal(voice.enabled, true, 'never chosen, PC wake word running: it should come on');
    ({ voice } = setup({ offline: true, enabled: false }));
    voice.restore(false);
    assert.equal(voice.enabled, false, 'never chosen and no PC wake word: stays off, as before');
    ({ voice } = setup({ offline: true, enabled: false }));
    localStorage.setItem('jarvis.voice.on', '1');
    voice.restore(false);
    assert.equal(voice.enabled, true, 'you left it on: it comes back on');
    ({ voice } = setup({ offline: true, enabled: false }));
    localStorage.setItem('jarvis.voice.on', '0');
    voice.restore(true);
    assert.equal(voice.enabled, false, 'you switched it off on purpose: that is respected even with the wake word running');
  },
  async 'only your own button press changes the remembered choice'() {
    const { voice } = setup({ offline: true, enabled: false });
    assert.equal(voice.preference(), null);
    voice.toggle();
    assert.equal(voice.enabled, true);
    assert.equal(voice.preference(), true);
    voice.stop();                                              // stopped by an error, not by you
    assert.equal(voice.preference(), true);
    voice.toggle();                                            // you press it
    assert.equal(voice.enabled, true);
    voice.toggle();
    assert.equal(voice.enabled, false);
    assert.equal(voice.preference(), false);
  },
  async 'hearing the name while voice is off says so instead of staying silent'() {
    const { voice } = setup({ offline: true, enabled: false });
    voice.wake();
    assert.equal(toasts.length, 1);
    assert.match(toasts[0], /voice is switched off/);
    assert.equal(log.includes('recognition.start'), false);
  },
  async 'JARVIS never says its own name aloud, so its voice cannot wake it (or interrupt it)'() {
    const { voice } = setup({ offline: true });
    synth.speaking = false;
    voice.speak('Claude is done in JARVIS. Jarvis online. Good evening, jarvis.');
    const said = spoken.join(' ');
    assert.equal(said.toLowerCase().includes('jarvis'), false, said);
    assert.ok(said.includes('J A R V I S'), 'the name is spelled out instead');
    assert.ok(said.includes('Claude is done in'), 'everything else is untouched');
  },
  async 'the spelled-out name works for all the ways the recogniser might hear it, and leaves other words alone'() {
    for (const word of ['JARVIS', 'Jarvis', 'jarvis', 'Jervis', 'jarvas']) {
      assert.equal(maskName(`say ${word} now`), 'say J A R V I S now');
    }
    assert.equal(maskName('Travis ran a service for the jar'), 'Travis ran a service for the jar');
    assert.equal(maskName('no name here'), 'no name here');
  },
  async 'a real "Jarvis" from you still cuts in over an answer that does not contain the name'() {
    const { voice } = setup({ offline: true });
    startSpeaking(voice);
    voice.wake();
    assert.equal(voice.speaking, false);
  },
  async 'the wake word is still parsed the same way'() {
    assert.equal(parseWake('hey jarvis what time is it'), 'what time is it');
    assert.equal(parseWake('what time is it'), null);
    assert.equal(parseWake('Jarvis'), '');
  },
};

let failed = 0;
for (const [name, run] of Object.entries(checks)) {
  try { await run(); console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
