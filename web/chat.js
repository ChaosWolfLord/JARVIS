// JARVIS chat panel: sends messages (plus an optional board snapshot) and renders the SSE reply.

const esc = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function inline(s) {
  return esc(s).replace(/`([^`\n]+)`/g, '<code>$1</code>').replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
}

// Small markdown subset: fenced code, bullet/numbered lists, bold, inline code, paragraphs.
export function renderMarkdown(src) {
  return src
    .split('```')
    .map((part, i) => {
      if (i % 2) {
        const nl = part.indexOf('\n');
        const code = nl >= 0 ? part.slice(nl + 1) : part;
        return `<pre><code>${esc(code.replace(/\n$/, ''))}</code></pre>`;
      }
      const out = [];
      let list = null;
      const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
      for (const raw of part.split('\n')) {
        const line = raw.trimEnd();
        const bullet = line.match(/^\s*[-*]\s+(.*)/);
        const num = line.match(/^\s*\d+[.)]\s+(.*)/);
        if (bullet || num) {
          const kind = bullet ? 'ul' : 'ol';
          if (list !== kind) { close(); out.push(`<${kind}>`); list = kind; }
          out.push(`<li>${inline((bullet || num)[1])}</li>`);
        } else {
          close();
          if (line.trim()) out.push(`<p>${inline(line.replace(/^#+\s*/, ''))}</p>`);
        }
      }
      close();
      return out.join('');
    })
    .join('');
}

export class Chat {
  constructor({ log, form, input, includeBoard, spendEl }, board, toast) {
    this.log = log;
    this.input = input;
    this.includeBoard = includeBoard;
    this.spendEl = spendEl;
    this.board = board;
    this.toast = toast;
    this.history = [];
    this.privateTouched = false;   // set once JARVIS has read mail, calendar, Discord or files: later web lookups then ask first
    this.summary = '';   // a short summary of the older part of a long conversation (the newest messages are sent whole)
    this.busy = false;
    this.turn = null;
    this.controller = null;
    this.sendButton = form.querySelector('button[type="submit"]');

    // While JARVIS is working, the Send button becomes Stop.
    this.sendButton?.addEventListener('click', (e) => { if (this.busy) { e.preventDefault(); this.stop(); } });
    form.addEventListener('submit', (e) => { e.preventDefault(); this.submit(); });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.submit(); }
    });
    input.addEventListener('input', () => {
      input.style.height = 'auto';
      input.style.height = `${Math.min(140, input.scrollHeight)}px`;
    });
  }

  setUsage(requests, model = this.model) {
    this.model = model;
    this.spendEl.textContent = `${model || 'no model'} · ${requests} request${requests === 1 ? '' : 's'} today`;
  }

  // Code JARVIS wants to run: shown with Run / Don't run buttons; nothing executes until Run is clicked.
  runCard(ev) {
    const card = document.createElement('details');
    card.className = 'run';
    card.open = true;
    card.dataset.run = ev.id;
    // The same card asks permission for Python code and for a tool from a connected app (ev.kind === 'tool').
    const tool = ev.kind === 'tool';
    card.dataset.kind = tool ? 'tool' : 'code';
    card.innerHTML =
      '<summary></summary><pre><code></code></pre>' +
      '<div class="run-actions"><button type="button" class="go"></button><button type="button" class="no"></button></div>';
    card.querySelector('summary').textContent = ev.title || 'JARVIS wants to run this Python';
    card.querySelector('.go').textContent = tool ? 'Allow' : 'Run';
    card.querySelector('.no').textContent = tool ? 'Don’t allow' : 'Don’t run';
    card.querySelector('code').textContent = ev.code;
    const decide = (approve) => {
      card.querySelector('.run-actions').textContent = approve ? (tool ? 'Working…' : 'Running…') : 'Declined.';
      fetch(`/api/run/${ev.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approve }),
      });
    };
    card.querySelector('.go').addEventListener('click', () => decide(true));
    card.querySelector('.no').addEventListener('click', () => decide(false));
    return card;
  }

  showRunResult(card, r) {
    card.querySelector('.run-actions')?.remove();
    const pre = document.createElement('pre');
    if (r.declined) {
      pre.className = 'out bad';
      pre.textContent = card.dataset.kind === 'tool' ? 'Not allowed.' : 'Not run.';
    } else {
      pre.className = `out${r.return_code ? ' bad' : ''}`;
      pre.textContent = [r.stdout, r.stderr].filter(Boolean).join('\n') || '(no output)';
    }
    card.append(pre);
  }

  scrollDown() { this.log.scrollTop = this.log.scrollHeight; }

  addMessage(kind, text) {
    const el = document.createElement('div');
    el.className = `msg ${kind}`;
    if (text) el.textContent = text;
    this.log.append(el);
    this.scrollDown();
    return el;
  }

  submit() {
    const text = this.input.value.trim();
    if (!text || this.busy) return;
    this.input.value = '';
    this.input.style.height = 'auto';
    if (this.onTyped?.(text)) return;     // a command JARVIS's own page handles (show off, privacy, lights, music...): typing it works like saying it
    return this.ask(text);
  }

  /** Once a conversation is long, the oldest messages are folded into a short summary (one cheap model call), so
      the thread isn't lost and the request doesn't keep growing. Runs quietly in the background. */
  async condenseHistory() {
    const FOLD = 12;
    if (this.history.length <= 30 || this.condensing) return;
    this.condensing = true;
    const old = this.history.slice(0, FOLD);
    try {
      const res = await fetch('/api/summarize', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: old, previous: this.summary }),
      });
      const { summary } = await res.json();
      if (summary && summary !== this.summary) {
        this.summary = summary;
        this.history = this.history.slice(FOLD);
      } else if (this.history.length > 36) {
        this.history = this.history.slice(FOLD);      // no model could summarise: drop the oldest rather than grow forever
      }
    } catch { /* try again after the next reply */ }
    this.condensing = false;
  }

  /** The Stop button: ends the answer in progress (the server stops at its next safe point; the page lets go at once). */
  stop() {
    if (!this.busy) return;
    this.stopped = true;
    if (this.turn) fetch(`/api/chat/cancel/${this.turn}`, { method: 'POST' }).catch(() => {});
    this.controller?.abort();
    this.onStopped?.();                            // lets the voice stop talking too
  }

  /** Stops any answer in progress and waits (briefly) until the chat can take a new request. */
  async interrupt() {
    this.stop();
    const began = Date.now();
    while (this.busy && Date.now() - began < 1500) await new Promise((r) => setTimeout(r, 30));
  }

  /** Something a phone's answer did to the wall (the phone itself only gets a line about it). */
  applyRemote(ev) {
    if (ev.type === 'add_note') {
      const at = ev.x == null ? {} : { x: this.board.fromAi(ev.x), y: this.board.fromAi(ev.y) };
      this.board.addNote({ text: ev.text, color: ev.color, ...at });
    } else if (ev.type === 'board_edit') this.board.applyEdit(ev);
    else if (ev.type === 'widget') this.onWidget?.(ev);
    else if (ev.type === 'holo') this.onHolo?.(ev);
    else if (ev.type === 'picture') this.onPicture?.(ev);
    else if (ev.type === 'files') this.onFiles?.(ev);
    else if (ev.type === 'timer') this.onTimer?.(ev);
  }

  setBusy(on) {
    this.busy = on;
    if (this.sendButton) this.sendButton.textContent = on ? 'Stop' : 'Send';
    this.sendButton?.classList.toggle('stop', on);
  }

  // Sends one message. With speak (voice commands), the reply is handed to onReply to be read aloud.
  async ask(text, { speak = false } = {}) {
    if (!text || this.busy) return;
    this.setBusy(true);
    this.stopped = false;
    this.turn = (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}${Math.random()}`).slice(0, 60);
    this.controller = new AbortController();

    this.addMessage('user', text);
    const reply = this.addMessage('assistant');
    reply.innerHTML = '<span class="thinking">Thinking</span>';
    let segment = null; // current text segment: {el, text}
    let fullText = '';
    let spoken = ''; // what the voice says when the model wrote no words of its own
    let failed = false;
    let errorText = '';
    this.onStart?.(text); // lets the orb and its speech bubble follow along when the panel is closed

    const newSegment = () => {
      segment = { el: document.createElement('div'), text: '' };
      reply.append(segment.el);
    };

    try {
      const board = this.includeBoard.checked ? this.board.snapshot() : null;
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history: this.history, board, turn: this.turn, summary: this.summary, private: this.privateTouched }),
        signal: this.controller.signal,
      });
      if (!res.ok) throw new Error(`Server returned ${res.status}`);

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      const handle = (ev) => {
        if (ev.type === 'text') {
          if (!segment) { reply.querySelector('.thinking')?.remove(); newSegment(); }
          segment.text += ev.delta;
          fullText += ev.delta;
          segment.el.innerHTML = renderMarkdown(segment.text);
        } else if (ev.type === 'run_request') {
          reply.querySelector('.thinking')?.remove();
          segment = null;
          reply.append(this.runCard(ev));
          this.onNeedsYou?.();                    // an approval is waiting: open the panel if it is closed
        } else if (ev.type === 'run_result') {
          const card = reply.querySelector(`details[data-run="${ev.id}"]`);
          if (card) this.showRunResult(card, ev);
        } else if (ev.type === 'add_note') {
          const at = ev.x == null ? {} : { x: this.board.fromAi(ev.x), y: this.board.fromAi(ev.y) };
          this.board.addNote({ text: ev.text, color: ev.color, ...at });
          this.chip(reply, `Note added: ${ev.text.slice(0, 40)}`);
        } else if (ev.type === 'board_edit') {
          const summary = this.board.applyEdit(ev);
          if (summary) this.chip(reply, summary);
        } else if (ev.type === 'widget') {
          this.onWidget?.(ev);
          this.chip(reply, ev.show ? `Showing the ${ev.name} widget` : `Hid the ${ev.name} widget`);
        } else if (ev.type === 'holo') {
          this.onHolo?.(ev);
          this.chip(reply, `Showing: ${ev.title}`);
        } else if (ev.type === 'picture') {
          this.onPicture?.(ev);
          this.chip(reply, `Picture on the wall: ${ev.title}`);
        } else if (ev.type === 'timer') {
          this.onTimer?.(ev);
          this.chip(reply, ev.action === 'start' ? `Timer started: ${ev.label || `${Math.round(ev.seconds / 60)} min`}` : 'Timer cancelled');
        } else if (ev.type === 'memory') {
          this.chip(reply, ev.action === 'saved' ? `Remembered: ${ev.fact}` : 'Forgot a fact');
        } else if (ev.type === 'private') {
          this.privateTouched = true;
        } else if (ev.type === 'progress') {      // which model call this is, out of the most it may make
          const wait = reply.querySelector('.thinking');
          if (wait && ev.step > 1) wait.textContent = `Thinking · step ${ev.step} of ${ev.max}`;
          this.onProgress?.(ev);
        } else if (ev.type === 'step') {          // a lookup the agent is doing: searching, reading a page...
          const wait = reply.querySelector('.thinking');
          if (wait) wait.textContent = ev.text;
          else this.chip(reply, ev.text);
          this.onStatus?.(ev.text);
          segment = null;                         // words after the lookup start a fresh paragraph
        } else if (ev.type === 'summary') {
          spoken = ev.text;
        } else if (ev.type === 'notice') {
          reply.append(Object.assign(document.createElement('div'), { className: 'msg notice', textContent: ev.text }));
          this.onStatus?.(ev.text);
        } else if (ev.type === 'error') {
          failed = true;
          errorText = ev.message;
          reply.querySelector('.thinking')?.remove();
          this.addMessage('error', ev.message);
          if (speak) this.onReply?.(ev.message);
        } else if (ev.type === 'done') {
          this.setUsage(ev.requests, ev.model || undefined);
        }
        this.scrollDown();
      };

      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf('\n\n')) >= 0) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (line.startsWith('data:')) handle(JSON.parse(line.slice(5)));
        }
      }
    } catch (err) {
      reply.querySelector('.thinking')?.remove();
      if (this.stopped) {
        this.addMessage('notice', 'Stopped.');
        failed = true;
      } else {
        failed = true;
        this.addMessage('error', `Connection problem: ${err.message}`);
        if (speak) this.onReply?.('Sorry, I lost the connection.');
      }
    } finally {
      reply.querySelector('.thinking')?.remove();
      if (!reply.childNodes.length) reply.remove();
      if (fullText.trim()) {
        this.history.push({ role: 'user', content: text }, { role: 'assistant', content: fullText });
        this.history = this.history.slice(-40);
      }
      this.setBusy(false);
      this.turn = null;
      this.condenseHistory();
      this.onFinal?.({ text: fullText.trim() || spoken, failed, error: errorText });
      if (speak && !failed) this.onReply?.(fullText.trim() || spoken || 'Done.');
    }
  }

  chip(parent, text) {
    parent.append(Object.assign(document.createElement('div'), { className: 'chip', textContent: text }));
  }
}
