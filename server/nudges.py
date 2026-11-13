"""JARVIS speaks first: a short heads-up when something needs you, without being asked.

Two kinds, both read-only and both optional:
  * the calendar: "Dentist starts in 10 minutes."
  * important mail: "You have 2 new important emails, from Sam and Alex."  (only who it is from: subjects and bodies are never read, and nothing here goes to an AI)

Guard rails: it stays quiet during quiet hours (22:00 to 07:00 unless you change them) and while snoozed ("Quiet for an hour"), it never repeats a heads-up, it
says nothing about old mail (the first look just notes what is already there, and only mail from the last two hours counts after that), and it does
nothing at all while the privacy screen is on or Google is not connected. Settings are kept on this PC.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import store

CONFIG = store.STATE / "nudges.json"
SEEN = store.STATE / "nudges_seen.json"
DEFAULTS = {"enabled": True, "calendar": True, "minutes": 10, "mail": True, "speak": True, "phone": True,
            "quiet_from": "22:00", "quiet_to": "07:00", "snooze_until": 0}
CALENDAR_EVERY_S = 120
MAIL_EVERY_S = 300
MAIL_FRESH_MS = 2 * 60 * 60 * 1000
KEEP_SEEN = 300
_lock = threading.Lock()


def _clock(value, fallback: str) -> str:
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(value).strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else fallback


def clean(raw: dict | None, base: dict | None = None) -> dict:
    """Settings made safe: known keys only, the right types and ranges."""
    out = dict(base or DEFAULTS)
    raw = raw if isinstance(raw, dict) else {}
    for key in ("enabled", "calendar", "mail", "speak", "phone"):
        if key in raw:
            out[key] = bool(raw[key])
    if "minutes" in raw:
        try:
            out["minutes"] = max(1, min(int(raw["minutes"]), 60))
        except (TypeError, ValueError):
            pass
    for key in ("quiet_from", "quiet_to"):
        if key in raw:
            out[key] = _clock(raw[key], out[key])
    if "snooze_until" in raw:
        try:
            out["snooze_until"] = max(0.0, float(raw["snooze_until"]))
        except (TypeError, ValueError):
            pass
    return out


def in_quiet(now: datetime, start: str, end: str) -> bool:
    """Is `now` inside the quiet hours? They may cross midnight (22:00 to 07:00). Equal times mean no quiet hours."""
    minutes = now.hour * 60 + now.minute
    a, b = (int(start[:2]) * 60 + int(start[3:])), (int(end[:2]) * 60 + int(end[3:]))
    if a == b:
        return False
    return a <= minutes < b if a < b else (minutes >= a or minutes < b)


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, data) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _names(senders: list[str]) -> str:
    names = list(dict.fromkeys(senders))[:3]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


class Nudges:
    """Decides what to say. `calendar(minutes, now)` and `mail()` fetch from Google (injected so tests need no network)."""

    def __init__(self, calendar: Callable, mail: Callable, config: Path | None = None, seen: Path | None = None, clock: Callable[[], float] = time.time):
        self.calendar, self.mail, self.clock = calendar, mail, clock
        self.config_path, self.seen_path = config or CONFIG, seen or SEEN
        self.last_error = ""
        self._next_calendar = self._next_mail = 0.0

    # ---- settings
    def settings(self) -> dict:
        with _lock:
            return clean(_read(self.config_path))

    def update(self, changes: dict) -> dict:
        with _lock:
            merged = clean(changes, clean(_read(self.config_path)))
            _write(self.config_path, merged)
        return merged

    def snooze(self, minutes: float) -> dict:
        until = self.clock() + max(0.0, min(float(minutes), 24 * 60)) * 60
        return self.update({"snooze_until": until})

    def status(self) -> dict:
        s = self.settings()
        s["snoozed"] = s["snooze_until"] > self.clock()
        s["error"] = self.last_error
        return s

    # ---- what has been announced
    def _seen(self) -> dict:
        data = _read(self.seen_path)
        return data if isinstance(data, dict) else {"ids": [], "mail_started": False}

    def _remember(self, data: dict) -> None:
        data["ids"] = data.get("ids", [])[-KEEP_SEEN:]
        _write(self.seen_path, data)

    # ---- the check
    def check(self, now: datetime | None = None, force: bool = False) -> list[dict]:
        """What to say right now: a list of {kind, text}. Quiet when disabled, snoozed, in quiet hours, or not yet due (`force` skips the timers)."""
        s = self.settings()
        t = self.clock()
        now = now or datetime.now().astimezone()
        if not s["enabled"] or s["snooze_until"] > t or in_quiet(now, s["quiet_from"], s["quiet_to"]):
            return []
        out: list[dict] = []
        seen = self._seen()
        ids: list[str] = list(seen.get("ids", []))
        try:
            if s["calendar"] and (force or t >= self._next_calendar):
                self._next_calendar = t + CALENDAR_EVERY_S
                for ev in self.calendar(s["minutes"], now):
                    key = f"cal:{ev['id']}:{ev['start'].isoformat()}"
                    if key in ids:
                        continue
                    ids.append(key)
                    mins = max(1, round((ev["start"] - now).total_seconds() / 60))
                    where = f", at {ev['where']}" if ev.get("where") else ""
                    out.append({"kind": "calendar", "text": f"{ev['title']} starts in {_plural(mins, 'minute')}{where}."})
            if s["mail"] and (force or t >= self._next_mail):
                self._next_mail = t + MAIL_EVERY_S
                mails = self.mail()
                if not seen.get("mail_started"):
                    ids.extend(f"mail:{m['id']}" for m in mails)          # the first look only notes what is already waiting
                    seen["mail_started"] = True
                else:
                    fresh = [m for m in mails if f"mail:{m['id']}" not in ids]
                    ids.extend(f"mail:{m['id']}" for m in fresh)
                    recent = [m for m in fresh if t * 1000 - m["when_ms"] <= MAIL_FRESH_MS]
                    if recent:
                        out.append({"kind": "mail", "text": f"You have {_plural(len(recent), 'new important email')}, from {_names([m['sender'] for m in recent])}."})
            self.last_error = ""
        except Exception as e:  # noqa: BLE001 - Google being unreachable must never break the loop; the status menu shows why it is quiet
            self.last_error = str(e)[:200]
        seen["ids"] = ids
        self._remember(seen)
        return out



def snooze_minutes(text: str) -> float | None:
    """"quiet for an hour", "don't interrupt me for 30 minutes", "stop nudging me": how long to stay quiet, or None when this is not about that."""
    t = re.sub(r"[^\w' ]", " ", str(text or "").lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:please |hey |ok |okay )?(?:jarvis )?", "", t)
    about_nudges = re.search(r"\b(?:interrupt\w*|nudg\w*|heads ?ups?|speak first|disturb\w*)\b", t)
    quiet = re.search(r"\b(?:quiet|silent)\b", t)
    if not (about_nudges or quiet):
        return None
    if not re.match(r"(?:be |stay |quiet |silent |keep quiet|keep it quiet|don't |do not |stop |no more |mute |no |hold the |pause )", t):
        return None
    m = re.search(r"\b(\d+|an|one|a|half an?)\s*(hours?|hrs?|minutes?|mins?)\b", t)
    if m:
        word = m.group(1)
        n = 0.5 if word.startswith("half") else (float(word) if word.isdigit() else 1.0)
        return n * (60 if m.group(2).startswith("h") else 1)
    if re.search(r"\b(?:today|tonight|rest of the day)\b", t):
        return 8 * 60
    return 60 if about_nudges else None                        # a bare "be quiet" only stops the talking


def _calendar(minutes: int, now: datetime) -> list[dict]:
    from . import google_tools
    return google_tools.upcoming_events(minutes, now)


def _mail() -> list[dict]:
    from . import google_tools
    return google_tools.important_unread()


instance = Nudges(_calendar, _mail)


def handle_voice(text: str) -> dict:
    """"Quiet for an hour" and the like: no heads-ups for a while."""
    minutes = snooze_minutes(text)
    if minutes is None:
        return {"handled": False, "ok": False, "text": ""}
    instance.snooze(minutes)
    when = f"{round(minutes / 60, 1):g} hours" if minutes >= 120 else ("an hour" if minutes == 60 else f"{round(minutes):g} minutes")
    return {"handled": True, "ok": True, "text": f"All right, no heads-ups for {when}."}
