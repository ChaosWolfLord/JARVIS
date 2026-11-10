// Pen input from the IR camera tracker (python -m tracker), relayed by the server over a WebSocket.
// Pen events arrive already in board coordinates (1920x1080) and go straight into the board's
// penDown / penMove / penUp, the same path the mouse uses. Also runs the calibration screen: touch each
// target with the pen so the tracker can learn where the camera's view lands on the board.

import { W, H } from './board.js';

// 3 x 3 grid of targets, kept clear of the edges where the pen's light is harder to see.
const TARGETS = [0.12, 0.5, 0.88].flatMap((fy) => [0.1, 0.5, 0.9].map((fx) => [Math.round(fx * W), Math.round(fy * H)]));

const CONTROL = 'button, label, summary, input, textarea, select, [contenteditable], a';
const TEXT_FIELD = 'input:not([type]), input[type="text"], input[type="search"], textarea, [contenteditable]';
const TAP_SLOP = 45; // board pixels the pen may wander and still count as a tap

export class PenInput {
  constructor({ board, boardEl, button, caption, toast, keyboard = null, onTracker = null }) {
    this.board = board;
    this.button = button;
    this.caption = caption;
    this.toast = toast;
    this.keyboard = keyboard;
    this.onTracker = onTracker;
    this.press_ = null; // what the pen is doing right now, from the moment it touches down
    this.trackerUp = false;
    this.calibrated = false;
    this.calibrating = false;
    this.ws = null;

    this.cursor = Object.assign(document.createElement('div'), { id: 'pen-cursor' });
    this.layer = Object.assign(document.createElement('div'), { id: 'calib', hidden: true });
    boardEl.append(this.cursor, this.layer);

    button.addEventListener('click', () => this.toggleCalibration());
    window.addEventListener('keydown', (e) => {
      if (this.calibrating && e.key === 'Escape') { e.stopImmediatePropagation(); this.cancelCalibration(); }
    }, true);
    this.connect();
  }

  connect() {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/ws/pen?role=view`);
    this.ws = ws;
    ws.onmessage = (e) => { try { this.onMessage(JSON.parse(e.data)); } catch { /* ignore a bad message */ } };
    ws.onclose = () => {
      this.setTracker(false);
      setTimeout(() => this.connect(), 2000);
    };
  }

  send(message) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(message));
  }

  setTracker(up) {
    if (up !== this.trackerUp) this.toast(up ? 'Pen tracker connected' : 'Pen tracker disconnected');
    this.trackerUp = up;
    if (!up) this.camera = null; // announce the camera again when a tracker reconnects
    if (!up && this.calibrating) this.endCalibration();
    this.refreshButton();
    this.onTracker?.(up);
  }

  refreshButton() {
    this.button.classList.toggle('on', this.trackerUp);
    const cam = this.camera ? ` Camera: ${this.camera}.` : '';
    this.button.title = !this.trackerUp
      ? 'Pen tracker is not running (start run_tracker.bat). Click to see how.'
      : this.calibrated
        ? `Pen tracker running and calibrated.${cam} Click (or K) to recalibrate.`
        : `Pen tracker running, NOT calibrated.${cam} Click (or K) to calibrate.`;
  }

  onMessage(m) {
    switch (m.type) {
      case 'tracker': this.setTracker(m.connected); break;
      case 'status':
        if (m.camera && m.camera !== this.camera) {
          this.camera = m.camera;
          this.toast(`Pen tracker is using: ${m.camera}${m.size ? ` (${m.size[0]}x${m.size[1]})` : ''}`);
        }
        if (m.calibrated !== this.calibrated) this.calibrated = m.calibrated;
        this.refreshButton();
        break;
      case 'pen': this.onPen(m); break;
      case 'wake': this.onWake?.(); break;
      case 'command': this.onCommand?.(m.text); break;           // the phone asked for something only this page can do (show off)
      case 'phone_event': this.onPhoneEvent?.(m.event); break;   // the phone's answer changed the wall (a note, a timer, a widget...)
      case 'reminder': this.onReminder?.(m); break;           // a saved reminder came due (the server keeps them, so one that was missed arrives late)
      case 'notify': this.onNotify?.(m); break;             // a program on the PC (the Claude Code hook) wants JARVIS to announce something
      case 'alert': case 'alerts': this.onAlert?.(m); break;   // the PC's monitor found (or cleared) a problem               // the PC heard "Jarvis" (offline wake word)
      case 'calib_state': this.onCalibState(m); break;
      case 'calib_point': this.markPoint(m.index); break;
      case 'calib_done': this.onCalibDone(m); break;
      default: break;
    }
  }

  onPen(m) {
    this.onActivity?.();               // a hand at the wall counts as someone being there (wakes ambient mode)
    if (this.calibrating) return;
    clearTimeout(this.hideTimer);
    // Safety net: if the tracker goes quiet mid-gesture, don't leave the cursor stuck on the wall.
    this.hideTimer = setTimeout(() => this.cursor.classList.remove('show'), 900);

    if (m.s === 'gone') { this.cursor.classList.remove('show'); return; }
    this.cursor.style.left = `${m.x}px`;
    this.cursor.style.top = `${m.y}px`;
    this.cursor.style.setProperty('--p', `${Math.round((m.dwell || 0) * 360)}deg`); // finger mode: the tap timer
    if (m.s === 'hover') { this.cursor.classList.add('show'); }
    else if (m.s === 'down') { this.cursor.classList.add('show'); this.press(m.x, m.y); }
    else if (m.s === 'move') { this.cursor.classList.add('show'); this.drag(m.x, m.y); }
    else { this.cursor.classList.remove('show'); this.release(m.x, m.y); } // a finger's next 'hover' shows it again
  }

  // ---- the pen as a pointer ---------------------------------------------
  // Touching the board draws. Touching a button, text box, slider or note acts like a click or a drag, so the
  // whole interface (dock, chat, keyboard) works from the wall. The choice is made when the pen touches down.
  press(x, y) {
    const s = this.board.toScreen(x, y);
    const el = document.elementFromPoint(s.x, s.y);
    const p = { x, y, last: [x, y], moved: 0, mode: 'ignore', el };

    if (!el || el.id === 'ink' || el.id === 'board' || el.id === 'notes' || el.closest('#hud')) {
      p.mode = 'draw';
      this.board.penDown(x, y);
    } else if (el.closest('.note-bar') && !el.closest('.note-x')) {
      p.mode = 'note';
      p.noteId = Number(el.closest('.note').dataset.noteId);
    } else if (this.widgets && (el.closest('.w-grip') || (el.closest('.widget header') && !el.closest(CONTROL)))) {
      p.mode = 'widget';                                   // the title bar moves a card, the corner grip resizes it
      this.widgets.start(el.closest('.widget').dataset.widget, el.closest('.w-grip') ? 'size' : 'move', x + this.board.pad, y);
    } else if (el.closest('input[type="range"]')) {
      p.mode = 'slider';
      p.ctl = el.closest('input[type="range"]');
      this.slide(p.ctl, s.x);
    } else if (el.closest(CONTROL)) {
      p.mode = 'tap';
      p.ctl = el.closest(CONTROL);
    }
    this.press_ = p;
  }

  drag(x, y) {
    const p = this.press_;
    if (!p) return;
    p.moved = Math.max(p.moved, Math.hypot(x - p.x, y - p.y));
    if (p.mode === 'draw') this.board.penMove(x, y);
    else if (p.mode === 'note') this.board.nudgeNote(p.noteId, x - p.last[0], y - p.last[1]);
    else if (p.mode === 'widget') this.widgets.move(x + this.board.pad, y);
    else if (p.mode === 'slider') this.slide(p.ctl, this.board.toScreen(x, y).x);
    p.last = [x, y];
  }

  release(x, y) {
    const p = this.press_;
    this.press_ = null;
    if (!p) return;
    if (p.mode === 'draw') { this.board.penMove(x, y); this.board.penUp(); }
    else if (p.mode === 'note') this.board.save();
    else if (p.mode === 'widget') this.widgets.end();
    else if (p.mode === 'tap' && p.moved < TAP_SLOP) this.activate(p.ctl);
  }

  /** A tap: text boxes get focus (and the keyboard); everything else is clicked. */
  activate(ctl) {
    if (ctl.matches(TEXT_FIELD)) {
      ctl.focus();
      if (ctl.isContentEditable) {
        const range = document.createRange();
        range.selectNodeContents(ctl);
        range.collapse(false); // caret at the end
        getSelection().removeAllRanges();
        getSelection().addRange(range);
      } else {
        ctl.setSelectionRange(ctl.value.length, ctl.value.length);
      }
      this.keyboard?.show();
    } else {
      ctl.click();
    }
  }

  slide(range, screenX) {
    const r = range.getBoundingClientRect();
    const f = Math.max(0, Math.min(1, (screenX - r.left) / r.width));
    const min = Number(range.min || 0), max = Number(range.max || 100);
    range.value = String(Math.round(min + f * (max - min)));
    range.dispatchEvent(new Event('input', { bubbles: true }));
  }

  // ---- calibration -----------------------------------------------------
  toggleCalibration() {
    if (this.calibrating) return this.cancelCalibration();
    if (!this.trackerUp) {
      this.toast('Start the pen tracker first: run_tracker.bat');
      return;
    }
    this.calibrating = true;
    this.cursor.classList.remove('show');
    this.layer.hidden = false;
    this.layer.replaceChildren();
    const prompt = Object.assign(document.createElement('div'), { className: 'calib-prompt' });
    prompt.innerHTML = '<b>Calibrate the pen</b><span>Touch the glowing target with the pen and hold still until the ring fills. ' +
      'Lift the pen before the next one. Esc cancels.</span><em></em>';
    this.layer.append(prompt);
    this.dots = TARGETS.map(([x, y]) => {
      const el = Object.assign(document.createElement('div'), { className: 'calib-target' });
      el.style.left = `${x + this.board.pad}px`; // targets are in the 1920x1080 home area; the board may be wider
      el.style.top = `${y}px`;
      this.layer.append(el);
      return el;
    });
    this.dots[0].classList.add('current');
    this.send({ type: 'calib_start', points: TARGETS });
  }

  onCalibState(m) {
    if (!this.calibrating) return;
    this.dots[m.index]?.style.setProperty('--p', `${Math.round(m.progress * 360)}deg`);
  }

  markPoint(index) {
    if (!this.calibrating) return;
    this.dots[index]?.classList.remove('current');
    this.dots[index]?.classList.add('done');
    this.dots[index + 1]?.classList.add('current');
  }

  onCalibDone(m) {
    const note = this.layer.querySelector('.calib-prompt em');
    if (m.ok) {
      this.calibrated = true;
      this.refreshButton();
      this.toast(`Pen calibrated (error ${m.rms} px)`);
      this.endCalibration();
    } else {
      note.textContent = m.message || 'Calibration failed. Try again.';
      setTimeout(() => this.calibrating && this.endCalibration(), 3500);
    }
  }

  cancelCalibration() {
    this.send({ type: 'calib_cancel' });
    this.endCalibration();
  }

  endCalibration() {
    this.calibrating = false;
    this.layer.hidden = true;
  }
}
