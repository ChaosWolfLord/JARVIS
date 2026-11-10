// Spoken "open Discord", "launch Spotify", "open youtube.com": handled on the PC without asking the AI (instant, uses no free requests). A website
// opens in Chrome (web addresses only); only ordinary apps from the Start Menu can be opened this way; anything else ("open the weather", "start a timer", an app the PC doesn't have) is passed
// on to the AI as usual. Closing an app is never a voice shortcut: it goes through the AI and shows an Allow card first.

const OPEN_TALK = /^(?:please |can you |could you |hey )?(?:jarvis[ ,]*)?(?:open|launch|start|go to|visit|browse to|pull up|navigate to|take me to)\b/i;

export class Apps {
  constructor({ speak }) {
    this.speak = speak;
    this.fallback = null;       // (command) => void: asks the AI when the sentence wasn't an app to open
  }

  /** True means: don't send this to the AI (the PC is dealing with it, or will hand it back). */
  handleVoice(command) {
    if (!OPEN_TALK.test(command.trim())) return false;
    this.answer(command);
    return true;
  }

  async answer(command) {
    try {
      const res = await fetch('/api/apps/voice', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: command }) });
      const out = await res.json();
      if (!res.ok || !out.handled) return this.fallback?.(command);
      this.speak(out.text);
    } catch {
      this.fallback?.(command);
    }
    return undefined;
  }
}
