"""Reminders that survive restarts: "remind me at 5 to call Sam".

They are saved on the PC (not in the browser), so closing the page or restarting JARVIS never loses one. When one is due it is handed to
the Courier, which delivers it to every open JARVIS page (a spoken line, a chime and an amber note on the wall) and to a paired phone that
has the phone page open. If nobody can receive it yet (the page is closed, or the privacy screen is up) it waits and arrives the moment
someone can, marked as late. Delivered reminders are forgotten after a day.
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import store

FILE = store.STATE / "reminders.json"
MAX_OPEN = 50
MAX_TEXT = 200
KEEP_DONE_S = 24 * 3600
LATE_AFTER_S = 120                 # delivered more than this long after it was due: say so
MAX_AHEAD_S = 366 * 24 * 3600


class ReminderError(ValueError):
    """Something the person (or the AI) can fix: the message says what."""


def clean(text) -> str:
    return " ".join(str(text or "").split())[:MAX_TEXT]


def parse_when(args: dict, now: float | None = None) -> float:
    """Epoch seconds for 'minutes' (from now) or 'at' (local time, 'YYYY-MM-DD HH:MM' or 'HH:MM' for the next time that happens)."""
    now = time.time() if now is None else now
    minutes, at = args.get("minutes"), str(args.get("at") or "").strip()
    if minutes not in (None, ""):
        try:
            m = float(minutes)
        except (TypeError, ValueError):
            raise ReminderError("'minutes' must be a number.") from None
        if not 0.5 <= m <= MAX_AHEAD_S / 60:
            raise ReminderError("A reminder can be 30 seconds to a year from now.")
        return now + m * 60
    if not at:
        raise ReminderError("Say when: give 'minutes' from now, or 'at' as a local time like 2026-11-05 17:00.")
    base = datetime.fromtimestamp(now)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            due = datetime.strptime(at, fmt).timestamp()
            break
        except ValueError:
            continue
    else:
        try:
            t = datetime.strptime(at, "%H:%M")
        except ValueError:
            raise ReminderError("'at' must look like 2026-11-05 17:00 (24-hour local time) or 17:00.") from None
        due = base.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0).timestamp()
        if due <= now:
            due += 24 * 3600                                    # "17:00" after 17:00 means tomorrow
    if due <= now:
        raise ReminderError("That time has already passed.")
    if due - now > MAX_AHEAD_S:
        raise ReminderError("A reminder can be at most a year ahead.")
    return due


def when_text(due: float, now: float | None = None) -> str:
    """'today at 5:00 PM', 'tomorrow at 9:30 AM', 'Mon 9 Nov at 5:00 PM'."""
    now = time.time() if now is None else now
    d, n = datetime.fromtimestamp(due), datetime.fromtimestamp(now)
    clock = d.strftime("%I:%M %p").lstrip("0")
    days = (d.date() - n.date()).days
    day = "today" if days == 0 else "tomorrow" if days == 1 else d.strftime("%a %d %b").replace(" 0", " ")
    return f"{day} at {clock}"


class Reminders:
    def __init__(self, path: Path | None = None, now: Callable[[], float] = time.time) -> None:
        self.path = path or FILE
        self.now = now
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
            return [r for r in data.get("reminders", []) if isinstance(r, dict) and r.get("id") and r.get("text")]
        except (OSError, ValueError):
            return []

    def _write(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"reminders": items}, indent=1), "utf-8")
        os.replace(tmp, self.path)

    def add(self, text, due: float) -> dict:
        text = clean(text)
        if not text:
            raise ReminderError("What should I remind you about?")
        with self._lock:
            items = self._read()
            if sum(1 for r in items if not r.get("done")) >= MAX_OPEN:
                raise ReminderError(f"There are already {MAX_OPEN} reminders waiting.")
            entry = {"id": uuid.uuid4().hex[:8], "text": text, "due": due, "done": False, "made": self.now()}
            items.append(entry)
            self._write(items)
            return entry

    def open(self) -> list[dict]:
        return sorted((r for r in self._read() if not r.get("done")), key=lambda r: r["due"])

    def cancel(self, match: str = "", everything: bool = False) -> list[dict]:
        """Removes reminders whose text contains `match` (or all of them); returns what was removed."""
        match = clean(match).lower()
        with self._lock:
            items, gone, keep = self._read(), [], []
            for r in items:
                hit = not r.get("done") and (everything or (match and match in r["text"].lower()))
                (gone if hit else keep).append(r)
            if gone:
                self._write(keep)
            return gone

    def due(self) -> list[dict]:
        now = self.now()
        return [r for r in self.open() if r["due"] <= now]

    def mark_done(self, ids: list[str]) -> None:
        with self._lock:
            items, now = self._read(), self.now()
            for r in items:
                if r["id"] in ids and not r.get("done"):
                    r["done"], r["delivered"] = True, now
            items = [r for r in items if not r.get("done") or now - r.get("delivered", now) < KEEP_DONE_S]
            self._write(items)


reminders = Reminders()


class Courier:
    """Hands due reminders to whoever can receive them. `send_pc(event)` and `send_phone(event)` return how many listeners got it."""

    def __init__(self, store_: Reminders, send_pc, send_phone, locked: Callable[[], bool] = lambda: False) -> None:
        self.store, self.send_pc, self.send_phone, self.locked = store_, send_pc, send_phone, locked
        self._busy = threading.Lock()

    def event(self, r: dict) -> dict:
        late = self.store.now() - r["due"] > LATE_AFTER_S
        when = datetime.fromtimestamp(r["due"]).strftime("%I:%M %p").lstrip("0")
        speak = f"You asked me to remind you: {r['text']}." if late else f"Reminder: {r['text']}."
        return {"type": "reminder", "id": r["id"], "title": "Reminder" + (f" (from {when})" if late else ""), "text": r["text"], "speak": speak, "late": late}

    def deliver_due(self) -> int:
        """Sends everything that is due; returns how many reminders reached someone. Nothing is sent while the privacy screen is up."""
        if self.locked() or not self._busy.acquire(blocking=False):
            return 0
        try:
            done = []
            for r in self.store.due():
                ev = self.event(r)
                reached = self.send_pc(ev) + self.send_phone({"type": "push", "title": ev["title"], "text": ev["text"]})
                if reached:
                    done.append(r["id"])
            if done:
                self.store.mark_done(done)
            return len(done)
        finally:
            self._busy.release()
