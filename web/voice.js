// Voice: say "Jarvis, <command>". Uses the browser's built-in speech recognition (Chrome/Edge send the
// audio to their cloud service) and speech synthesis for replies. Only phrases that start with the
// wake word are acted on; everything else is ignored and never reaches the AI.

// Accepts "Jarvis ...", "Hey Jarvis ...", and a few common mishearings.
const WAKE = /^\W*(?:(?:hey|ok|okay)\W+)?(?:jarvis|jarvas|jarvus|jarves)\b\W*(.*)$/is;
const STOP = /^(stop|cancel|quiet|be quiet|shut up|enough|never mind)\b/i;
const FOLLOW_UP_MS = 8000; // how long after a bare "Jarvis" the next sentence counts as the command
const REPLY_MS = 10000;    // after JARVIS asks a question: how long your answer is waited for, without saying "Jarvis" first
const REPLY_DELAY_MS = 800;   // ...starting this long after it stops talking, so its own voice dying away in the room is not taken for your answer
const MAX_SPOKEN_CHARS = 900;
const SETTINGS_KEY = 'jarvis.voice';
const ON_KEY = 'jarvis.voice.on';      // '1' / '0': whether you last left the microphone on or off
const MALE_NAMES = /ryan|george|thomas|daniel|james|oliver|guy|davis|brian|christopher|eric|mark|david|male/i;

/** How good a built-in voice is likely to sound, for choosing the default: neural/natural ones, British English, male. */
export function voiceScore(v) {
  let score = 0;
  if (/natural|neural|online/i.test(v.name)) score += 100;
  if (/en[-_]GB/i.test(v.lang)) score += 30;
  else if (/en[-_](AU|IE|US)/i.test(v.lang)) score += 12;
  else if (!/^en/i.test(v.lang)) score -= 200;
  if (MALE_NAMES.test(v.name)) score += 20;
  if (/espeak|compact/i.test(v.name)) score -= 20;
  return score;
}

/** Text after the wake word ('' for a bare "Jarvis"), or null if the phrase doesn't start with it. */
export function parseWake(text) {
  const m = String(text).match(WAKE);
  return m ? m[1].trim() : null;
}

/** JARVIS's own voice leaks into the microphone, and the PC's wake-word listener would hear it say its name and wake itself (and, since saying
 *  the name over an answer interrupts it, cut itself off). So when it speaks, its name is spelled out letter by letter, which can't match. */
export function maskName(text) {
  return String(text).replace(/\b(?:jarvis|jarvas|jarvus|jarves|jervis)\b/gi, 'J A R V I S');
}

/** Did what was said end by asking you something? ("Want me to dim the lights?") Only the last sentence counts, so a question in the middle of an
 *  answer, or a long answer that merely mentions one, does not make JARVIS wait for a reply. */
export function asksQuestion(text) {
  const sentences = String(text || '').trim().replace(/["'”’)\]]+$/, '').match(/[^.!?]+[.!?]*/g);     // (a closing quote after the question mark does not matter)
  const last = (sentences ? sentences[sentences.length - 1] : '').trim();
  return last.length >= 5 && last.length <= 220 && last.endsWith('?');
}

/** Markdown reply -> something pleasant to hear. */
export function stripForSpeech(md) {
  return md
    .replace(/```[\s\S]*?(```|$)/g, ' (code on screen) ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\*\*|__/g, '')
    .replace(/^\s*[-*]\s+/gm, '')
    .replace(/https?:\/\/\S+/g, ' link ')
    .replace(/[#>]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, MAX_SPOKEN_CHARS);
}

export class Voice {
  constructor({ button, caption, chat, toast }) {
    this.button = button;
    this.caption = caption;
    this.chat = chat;
    this.toast = toast;
    this.enabled = false;
    this.speaking = false;
    this.ignoreUntil = 0;
    this.awaitUntil = 0;
    this.generation = 0;
    this.listening = false; // true between the recognizer's start and end events
    this.lastStart = 0;
    this.watchdog = null;
    this.utterances = []; // kept referenced: Chrome can drop an utterance's end event if it's garbage collected
    this.speechTimer = null;
    this.restarts = [];
    this.captionTimer = null;
    this.voice = null;
    this.offline = false;     // true when the PC's offline wake word is running: the cloud recognizer only runs for a command
    this.offlineCommands = false;   // true when the PC also understands the command after the name (so the cloud recognizer is not needed at all)
    this.client = (crypto.randomUUID && crypto.randomUUID()) || `page-${Math.random().toString(36).slice(2)}`;     // this page's id, for the PC's microphone switch
    this.windowUntil = 0;     // offline mode: the recognizer stays open for the command until this time
    this.windowTimer = null;
    this.settings = { name: '', rate: 1, pitch: 0.9 };
    try { Object.assign(this.settings, JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}); } catch { /* defaults */ }

    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    this.supported = Boolean(SR) && 'speechSynthesis' in window;
    chat.onReply = (text) => this.speak(text, { reply: true });          // JARVIS's own answers: one that ends in a question is followed by listening for your reply
    this.expectReply = false;   // the answer being spoken ended with a question
    this.replyTimer = null;
    button.addEventListener('click', () => this.toggle());
    if (!this.supported) {
      button.title = 'Voice needs Chrome or Edge';
      button.classList.add('unsupported');
      return;
    }

    this.rec = new SR();
    this.rec.continuous = true;
    this.rec.interimResults = true;
    this.rec.lang = 'en-US';
    this.rec.onstart = () => { this.listening = true; };
    // The PC's microphone follows this page's voice switch: while voice is on, say so every few seconds (a page that goes away stops counting),
    // and when the page closes say it is off at once.
    setInterval(() => { if (this.enabled) this.syncServer(true); }, 6000)?.unref?.();
    window.addEventListener?.('pagehide', () => { try { navigator.sendBeacon('/api/wake', new Blob([JSON.stringify({ client: this.client, on: false })], { type: 'application/json' })); } catch { /* nothing to do */ } });
    this.rec.onresult = (e) => this.onResult(e);
    this.rec.onend = () => this.onEnd();
    this.rec.onerror = (e) => this.onError(e);

    speechSynthesis.addEventListener('voiceschanged', () => this.pickVoice());
    this.pickVoice();
  }

  // ---- offline wake word -----------------------------------------------------
  /** The server says whether its offline wake word is running; if so, the cloud recognizer is used only for commands. */
  setOffline(on) {
    if (on === this.offline) return;
    this.offline = on;
    if (this.enabled) { this.stop(); this.start(); }       // restart in the right mode
  }

  /** Tells the PC whether voice is on here, so it opens or closes its microphone: with voice off, nothing listens for "Jarvis". */
  syncServer(on) {
    fetch('/api/wake', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ client: this.client, on }) }).catch(() => {});
  }

  /** The PC heard "Jarvis" (offline). Play the listening sound; the command follows from the PC (or, without that, from the browser). */
  wake() {
    if (!this.supported || !this.enabled || !this.offline) return;         // voice is off here: nothing to do (the PC's microphone is closed then, anyway)
    clearTimeout(this.replyTimer);                               // the name was said: no need for the "listening for your answer" cue as well
    if (this.speaking || this.chat.busy) this.interrupt();       // saying "Jarvis" over an answer cuts it off, then JARVIS listens
    this.cue();
    this.awaitUntil = Date.now() + FOLLOW_UP_MS + 1500;
    this.show('Listening…', FOLLOW_UP_MS);
    if (this.offlineCommands) return;                            // the PC is already listening to what follows: no waiting for a recognizer to start
    this.windowUntil = this.awaitUntil + 1500;
    this.beginRecognition();
    clearTimeout(this.windowTimer);
    this.windowTimer = setTimeout(() => this.closeWindow(), this.windowUntil - Date.now() + 200);
  }

  /** What the PC understood after "Jarvis" ("" if nothing followed). It was heard on the PC, including the words said right after the name. */
  heardCommand(text) {
    if (!this.supported || !this.enabled) return;
    this.awaitUntil = 0;
    const command = String(text || '').trim();
    if (!command) { this.show('I didn’t catch a command. Say “Jarvis…” again.', 3000); return; }
    this.dispatch(command);
  }

  /** Cuts JARVIS off mid-answer: the voice stops at once and any answer still being worked out is dropped. Resolves when it is ready for the next command. */
  async interrupt() {
    this.cancelSpeech();
    this.ignoreUntil = 0;                    // no waiting for the room to go quiet: whatever you say next is the new command
    await this.chat.interrupt?.();
  }

  closeWindow() {
    clearTimeout(this.windowTimer);
    this.windowUntil = 0;
    this.awaitUntil = 0;
    if (this.offline) this.rec?.abort();
  }

  // ---- on/off ------------------------------------------------------------
  toggle() {
    if (!this.supported) return this.toast('Voice needs Chrome or Edge.');
    if (this.enabled) this.stop();
    else this.start();
    this.remember(this.enabled);                           // only your own choice is remembered, not a stop caused by an error
  }

  remember(on) {
    try { localStorage.setItem(ON_KEY, on ? '1' : '0'); } catch { /* not remembered */ }
  }

  /** true / false if you have chosen, null if you never have. */
  preference() {
    try {
      const v = localStorage.getItem(ON_KEY);
      return v === null ? null : v === '1';
    } catch { return null; }
  }

  /** Called when the page has loaded and the server has said whether the PC's wake word is running: puts voice back the way you left it.
   *  If you never chose, voice comes on when the PC's wake word is running (you clearly want it). */
  restore(wakeRunning) {
    if (!this.supported || this.enabled) return;
    const want = this.preference();
    if (want === true || (want === null && wakeRunning)) this.start();
  }

  start() {
    this.enabled = true;
    this.syncServer(true);
    this.button.classList.add('on');
    if (this.offline) {                                    // the PC listens for the name; nothing goes to the cloud until then
      this.show('Listening for “Jarvis…” (on this PC)', 3000);
      return;
    }
    this.show('Listening for “Jarvis…”', 3000);
    this.beginRecognition();
    // Safety net: if the recognizer ever stops without a restart sticking, bring it back.
    this.watchdog = setInterval(() => {
      if (this.enabled && !this.listening && Date.now() - this.lastStart > 1500) this.beginRecognition();
    }, 1500);
  }

  stop() {
    this.enabled = false;
    this.syncServer(false);                                // the PC's microphone closes too
    this.awaitUntil = 0;
    clearInterval(this.watchdog);
    clearTimeout(this.windowTimer);
    this.button.classList.remove('on');
    this.rec?.abort();
    this.cancelSpeech();
    this.show('Voice off', 1500);
  }

  beginRecognition() {
    this.lastStart = Date.now();
    try {
      this.rec.start();
    } catch {
      /* already started: the watchdog tries again if it really is stopped */
    }
  }

  onEnd() {
    // The browser ends continuous recognition every so often; restart unless that's happening in a loop.
    this.listening = false;
    if (!this.enabled) return;
    if (this.offline && Date.now() > this.windowUntil) return;     // offline mode: only restart while a command is awaited
    const now = Date.now();
    this.restarts = this.restarts.filter((t) => now - t < 10_000).concat(now);
    if (this.restarts.length > 8) {
      this.stop();
      this.toast('Voice stopped: the speech service keeps disconnecting.');
      return;
    }
    setTimeout(() => this.enabled && this.beginRecognition(), 250);
  }

  onError(e) {
    if (e.error === 'no-speech' || e.error === 'aborted') return;
    if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
      this.stop();
      this.toast('Microphone blocked. Allow it in the address bar, then click the mic again.');
    } else if (e.error === 'audio-capture') {
      this.stop();
      this.toast('No microphone found.');
    } else if (e.error === 'network') {
      this.toast('Speech service unreachable. Check the internet connection.');
    }
  }

  // ---- hearing ---------------------------------------------------------
  onResult(e) {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const result = e.results[i];
      const text = result[0].transcript;
      if (result.isFinal) this.handleFinal(text);
      else if (this.speaking && parseWake(text) !== null) this.interrupt();   // "Jarvis…" over an answer: stop talking the moment the name is heard
      else if (!this.speaking && parseWake(text) !== null) this.show(`“${text.trim()}”`, 4000);
    }
  }

  handleFinal(text) {
    const heard = text.trim();
    if (!heard) return;
    const now = Date.now();
    let command = parseWake(heard);

    // While JARVIS talks, its own voice can leak into the mic, so anything that doesn't start with its name is ignored.
    // Starting with the name is an interruption: it stops the answer and is then handled as the new command.
    if (this.speaking && command !== null) {
      this.interrupt();
    } else if (this.speaking || now < this.ignoreUntil) {
      if (command !== null && STOP.test(command)) this.cancelSpeech();
      return;
    }
    if (command === null) {
      if (now >= this.awaitUntil) {
        this.show(`Heard “${heard}”. Start with “Jarvis…”`, 2500); // so you can see what the mic picks up
        return;
      }
      command = heard; // follow-up after a bare "Jarvis"
    }
    this.awaitUntil = 0;
    this.cue();

    if (command === '') {
      this.awaitUntil = now + FOLLOW_UP_MS;
      this.show('Yes? Go ahead…', FOLLOW_UP_MS);
      return;
    }
    this.dispatch(command);
    if (this.offline) this.closeWindow();               // one command per wake-up: the cloud recognizer goes quiet again
  }

  async dispatch(command) {
    if (this.special?.(command)) return;                 // commands about the privacy screen are handled on the page, not by the AI
    if (STOP.test(command)) { this.chat.stop?.(); return this.cancelSpeech(); }   // "Jarvis, stop" also ends an answer in progress
    this.show(`“${command}”`, 5000);
    if (this.chat.busy) await this.interrupt();          // a new request replaces the one still being worked on
    this.chat.ask(command, { speak: true });
  }

  // ---- speaking --------------------------------------------------------
  /** Every voice this browser has, best sounding first (for the voice menu). */
  voices() {
    return [...speechSynthesis.getVoices()].sort((a, b) => voiceScore(b) - voiceScore(a) || a.name.localeCompare(b.name));
  }

  pickVoice() {
    const all = this.voices();
    this.voice = all.find((v) => v.name === this.settings.name) || all.find((v) => /^en/i.test(v.lang)) || all[0] || null;
  }

  /** Remembers the voice, speed and pitch chosen in the status menu. */
  configure(changes) {
    Object.assign(this.settings, changes);
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(this.settings)); } catch { /* not remembered */ }
    this.pickVoice();
  }

  speak(text, { reply = false } = {}) {
    if (!this.supported || window.jarvis?.privacy?.locked) return;     // nothing is spoken while the privacy screen is up
    const clean = maskName(stripForSpeech(text));
    if (!clean) return;
    this.cancelSpeech();
    this.expectReply = reply && this.enabled && asksQuestion(clean);   // judged on what is really spoken (a long answer is cut short)
    // Short sentence-sized chunks: some browsers cut off long utterances.
    const chunks = clean.match(/[^.!?]+[.!?]*\s*/g) || [clean];
    const mine = ++this.generation; // a cancelled older utterance must not end this one
    this.speaking = true;
    this.button.classList.add('talking');
    this.utterances = chunks.map((chunk, i) => {
      const u = new SpeechSynthesisUtterance(chunk.trim());
      if (this.voice) u.voice = this.voice;
      u.lang = this.voice?.lang || 'en-GB';
      u.pitch = this.settings.pitch;
      u.rate = this.settings.rate;
      if (i === chunks.length - 1) {
        u.onend = u.onerror = () => { if (mine === this.generation) this.doneSpeaking(true); };
      }
      return u;
    });
    this.utterances.forEach((u) => speechSynthesis.speak(u));

    // The end event is not always delivered. Don't stay deaf: poll the real state and cap the total time.
    const startedAt = Date.now();
    const maxMs = clean.length * 90 + 4000;
    clearInterval(this.speechTimer);
    this.speechTimer = setInterval(() => {
      if (mine !== this.generation) return;
      const elapsed = Date.now() - startedAt;
      const idle = !speechSynthesis.speaking && !speechSynthesis.pending;
      if (idle && elapsed > 800) { speechSynthesis.cancel(); this.doneSpeaking(true); }       // it finished, but the browser never said so
      else if (elapsed > maxMs) this.cancelSpeech();
    }, 250);
  }

  cancelSpeech() {
    if (!this.supported) return;
    speechSynthesis.cancel();
    this.doneSpeaking();
  }

  /** `natural`: it said everything it meant to (not cut off by you, by Stop, or by a newer answer). If that answer asked a question, listen for the reply. */
  doneSpeaking(natural = false) {
    clearInterval(this.speechTimer);
    clearTimeout(this.replyTimer);
    this.utterances = [];
    this.speaking = false;
    this.ignoreUntil = Date.now() + 600; // let the room echo die down
    this.button.classList.remove('talking');
    const ask = natural && this.expectReply && this.enabled;
    this.expectReply = false;
    if (ask) this.replyTimer = setTimeout(() => this.listenForReply(), REPLY_DELAY_MS);
  }

  /** JARVIS just asked something: for a few seconds the next sentence you say is the answer, with no need to say "Jarvis" first. */
  listenForReply() {
    if (!this.supported || !this.enabled || this.speaking || this.chat.busy) return;
    this.cue();
    this.awaitUntil = Date.now() + REPLY_MS;
    this.show('Listening for your answer…', REPLY_MS);
    if (!this.offline) return;                                   // the browser's recognizer is already listening: the next sentence counts as the command
    if (this.offlineCommands) { this.syncReply(); return; }      // the PC listens for it (and says nothing if you stay quiet)
    this.windowUntil = this.awaitUntil + 1500;
    this.beginRecognition();
    clearTimeout(this.windowTimer);
    this.windowTimer = setTimeout(() => this.closeWindow(), this.windowUntil - Date.now() + 200);
  }

  /** Asks the PC's microphone to treat the next sentence as a command even though the name was not said. */
  syncReply() {
    fetch('/api/wake/listen', { method: 'POST' }).catch(() => {});
  }

  // ---- feedback --------------------------------------------------------
  cue() {
    if (this.onCue) return this.onCue();               // the page's own listening sound, if it has one
    try {
      this.audio ??= new AudioContext();
      const osc = this.audio.createOscillator();
      const gain = this.audio.createGain();
      osc.frequency.value = 880;
      gain.gain.value = 0.06;
      osc.connect(gain).connect(this.audio.destination);
      osc.start();
      osc.stop(this.audio.currentTime + 0.1);
    } catch {
      /* no audio output: the caption still shows */
    }
  }

  show(text, ms) {
    this.caption.textContent = text;
    this.caption.classList.add('show');
    clearTimeout(this.captionTimer);
    this.captionTimer = setTimeout(() => this.caption.classList.remove('show'), ms);
  }
}
