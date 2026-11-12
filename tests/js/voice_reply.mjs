// Checks that JARVIS listens for your answer, without the name, after it asks you a question (web/voice.js). Runs under Node with stand-ins for the
// browser's speech APIs; tests/test_js_voice.py runs it. Prints one line per check; exits 1 if any fails.
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const log = [];
class FakeRecognition {
  start() { log.push('recognition.start'); }
  abort() { log.push('recognition.abort'); }
}
class FakeUtterance { constructor(text) { this.text = text; } }
const synth = { speaking: false, pending: false, cancel() { this.speaking = false; }, speak() { this.speaking = true; }, getVoices: () => [], addEventListener() {} };
globalThis.window = globalThis;
globalThis.SpeechRecognition = FakeRecognition;
globalThis.SpeechSynthesisUtterance = FakeUtterance;
globalThis.speechSynthesis = synth;
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) };
const fetched = [];
globalThis.fetch = async (url, opts = {}) => { fetched.push(`${opts.method || 'GET'} ${url}`); return { ok: true, json: async () => ({}) }; };

const { Voice, asksQuestion } = await import(pathToFileURL(path.resolve('web/voice.js')).href);

function setup({ offline = false, offlineCommands = false, enabled = true } = {}) {
  log.length = 0; fetched.length = 0; store.clear();
  const asked = [];
  const chat = { busy: false, onReply: null, stop() {}, async interrupt() {}, ask(text) { asked.push(text); } };
  const button = { addEventListener() {}, classList: { add() {}, remove() {} }, title: '' };
  const caption = { textContent: '', classList: { add() {}, remove() {} } };
  const voice = new Voice({ button, caption, chat, toast() {} });
  voice.onCue = () => log.push('cue');
  voice.enabled = enabled;
  voice.offline = offline;
  voice.offlineCommands = offlineCommands;
  return { voice, chat, asked };
}
const finish = (voice) => voice.utterances.at(-1).onend();                     // the last sentence finished playing, as the browser reports it
const results = (...items) => ({ resultIndex: 0, results: items.map(([transcript, isFinal]) => Object.assign([{ transcript }], { isFinal })) });
const asks = () => fetched.filter((f) => f !== 'POST /api/wake');               // (every page also tells the PC every few seconds that voice is on)
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const checks = {
  async 'only a question at the end counts'() {
    for (const yes of ['Want me to dim the lights?', 'The lights are on. Should I turn them off?', 'Do you want the weather, or the news?', '“Shall I go on?”']) assert.equal(asksQuestion(yes), true, yes);
    for (const no of ['The lights are on.', 'Why is the sky blue? Because of scattering.', 'I asked, how are you? Fine, thanks!', '', 'Ok?', 'Done']) assert.equal(asksQuestion(no), false, no);
    assert.equal(asksQuestion(`${'A very long rambling sentence '.repeat(10)}?`), false);
  },
  async 'after a question, the next sentence is the answer without saying Jarvis (browser listening)'() {
    const { voice, asked } = setup();
    voice.speak('The timer is set. Want me to dim the lights as well?', { reply: true });
    finish(voice);
    assert.equal(voice.speaking, false);
    await wait(900);
    assert.ok(log.includes('cue'), 'it should signal that it is listening');
    assert.ok(voice.awaitUntil > Date.now(), 'a window for the answer is open');
    voice.onResult(results(['yes please', true]));
    await wait(5);
    assert.deepEqual(asked, ['yes please']);
  },
  async 'without a question nothing is waited for'() {
    const { voice, asked } = setup();
    voice.speak('The timer is set.', { reply: true });
    finish(voice);
    await wait(900);
    assert.equal(voice.awaitUntil, 0);
    voice.onResult(results(['yes please', true]));
    await wait(5);
    assert.deepEqual(asked, []);
  },
  async 'only JARVIS\'s own answers do it, not an alert or a timer that happens to be a question'() {
    const { voice } = setup();
    voice.speak('Your tea timer is done. Shall I start another?');
    finish(voice);
    await wait(900);
    assert.equal(voice.awaitUntil, 0);
  },
  async 'being cut off (you speak over it, or press stop) does not open a window'() {
    const { voice } = setup();
    voice.speak('Want me to dim the lights?', { reply: true });
    voice.cancelSpeech();
    await wait(900);
    assert.equal(voice.awaitUntil, 0);
    voice.speak('Want me to dim the lights?', { reply: true });
    await voice.interrupt();
    await wait(900);
    assert.equal(voice.awaitUntil, 0);
  },
  async 'a newer answer replaces the waiting one'() {
    const { voice } = setup();
    voice.speak('Want me to dim the lights?', { reply: true });
    finish(voice);
    voice.speak('Sure, done.', { reply: true });
    await wait(900);
    assert.equal(voice.awaitUntil, 0);
  },
  async 'with voice off nothing listens'() {
    const { voice } = setup({ enabled: false });
    voice.speak('Want me to dim the lights?', { reply: true });
    finish(voice);
    await wait(900);
    assert.equal(voice.awaitUntil, 0);
    assert.deepEqual(asks(), []);
  },
  async 'the room is given a moment first, so the end of JARVIS\'s own voice is not taken for the answer'() {
    const { voice } = setup();
    voice.speak('Want me to dim the lights?', { reply: true });
    finish(voice);
    await wait(200);
    assert.equal(voice.awaitUntil, 0, 'not yet');
    voice.onResult(results(['dim the lights', true]));          // the echo, inside the quiet moment
    assert.ok(voice.ignoreUntil > Date.now());
  },
  async 'the PC wake word (it hears commands) is asked to listen for the answer'() {
    const { voice } = setup({ offline: true, offlineCommands: true });
    voice.speak('Want me to dim the lights?', { reply: true });
    finish(voice);
    await wait(900);
    assert.deepEqual(asks(), ['POST /api/wake/listen']);
    assert.ok(voice.awaitUntil > Date.now());
  },
  async 'the PC wake word with the browser hearing commands opens the browser for a moment'() {
    const { voice, asked } = setup({ offline: true, offlineCommands: false });
    voice.speak('Want me to dim the lights?', { reply: true });
    finish(voice);
    await wait(900);
    assert.ok(log.includes('recognition.start'));
    assert.deepEqual(asks(), []);
    assert.ok(voice.windowUntil > Date.now());
    voice.onResult(results(['yes', true]));
    await wait(5);
    assert.deepEqual(asked, ['yes']);
  },
  async 'saying Jarvis during the quiet moment works as before, without a second signal'() {
    const { voice } = setup({ offline: true, offlineCommands: true });
    voice.speak('Want me to dim the lights?', { reply: true });
    finish(voice);
    voice.wake();
    const cues = log.filter((l) => l === 'cue').length;
    await wait(900);
    assert.equal(log.filter((l) => l === 'cue').length, cues);
    assert.deepEqual(asks(), []);
  },
};

let failed = 0;
for (const [name, run] of Object.entries(checks)) {
  try { await run(); console.log(`ok   ${name}`); } catch (e) { failed += 1; console.log(`FAIL ${name}\n     ${e.message}`); }
}
process.exit(failed ? 1 : 0);
