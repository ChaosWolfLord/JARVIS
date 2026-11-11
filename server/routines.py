"""Routines: a name you say ("movie night", "goodnight", "focus") that runs a list of steps, which you write yourself in the status menu.

A step is a plain sentence, the same words you would say to JARVIS:
    dim the lights to 20 percent       play some jazz                    open spotify            open youtube.com
    set a timer for 90 minutes         say Enjoy the film                note Pizza is on its way   wait 5 seconds
Anything JARVIS already does without asking an AI (the lights, the music, opening an app or a web page, show off, a picture, finding a file) works as a
step, and so do a timer, a spoken line, a note on the board and a short wait. Steps run one after the other; one that fails is reported and the rest
still run. A routine cannot run another routine, and it can do nothing that those same sentences could not do by themselves.

Routines are made and changed only on the PC (status menu), never from the phone. The phone can start one by its name or by pressing it in the
menu, which does what saying the same words to JARVIS from the phone would do.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Callable

from . import store

CONFIG = store.STATE / "routines.json"
MAX_ROUTINES = 20
MAX_STEPS = 12
MAX_PHRASES = 5
MAX_WAIT_S = 30
MAX_TOTAL_WAIT_S = 60

_lock = threading.Lock()


class RoutineError(ValueError):
    """What is wrong with a routine, in words the person can act on."""


# ---- what you say ----------------------------------------------------------------------------------------------------------
_LEAD = re.compile(r"^(?:(?:hey|ok|okay) )?(?:jarvis )?(?:please )?(?:(?:run|start|activate|begin|launch|do|trigger|enable|engage|initiate|go to|switch to|its time for|time for|lets have|lets do|lets|its) )?(?:the |my )?")
_TAIL = re.compile(r"(?: (?:routine|mode|scene|please))+$")


_POLITE_LEAD = re.compile(r"^(?:(?:hey|ok|okay) )?(?:jarvis )?(?:please )?")
_POLITE_TAIL = re.compile(r"(?: (?:please|jarvis))+$")


def _words(text: str) -> str:
    t = str(text or "").lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def plain(text: str) -> str:
    """The words as said, without punctuation, capitals or a polite "Jarvis," / "please": an extra phrase must be said as written to start its routine."""
    t = _POLITE_LEAD.sub("", _words(text), count=1)
    return _POLITE_TAIL.sub("", t).strip()


def normalize(text: str) -> str:
    """"Jarvis, start the Movie Night routine please" -> "movie night". Used for a routine's NAME, which can be asked for in many ways. The page does the
    same (web/routines.js), so both agree."""
    t = _LEAD.sub("", _words(text), count=1)
    return _TAIL.sub("", t).strip()


def keys(routine: dict) -> tuple[set, set]:
    """(the ways the name can be asked for, the exact phrases)."""
    return {normalize(routine["name"]), plain(routine["name"])}, {plain(p) for p in routine["phrases"]}


# ---- the saved list --------------------------------------------------------------------------------------------------------
def clean(items) -> list[dict]:
    """Checks a whole list of routines and returns it tidied, or raises RoutineError saying what to fix."""
    if not isinstance(items, list):
        raise RoutineError("the routines must be a list.")
    if len(items) > MAX_ROUTINES:
        raise RoutineError(f"at most {MAX_ROUTINES} routines.")
    out, used = [], {}
    for item in items:
        if not isinstance(item, dict):
            raise RoutineError("a routine is missing its details.")
        name = " ".join(str(item.get("name") or "").split())[:40]
        if not name:
            raise RoutineError("every routine needs a name.")
        steps = [" ".join(str(s).split())[:200] for s in (item.get("steps") or []) if str(s).strip()]
        if not steps:
            raise RoutineError(f"{name}: add at least one step.")
        if len(steps) > MAX_STEPS:
            raise RoutineError(f"{name}: at most {MAX_STEPS} steps.")
        raw = [str(p) for p in (item.get("phrases") or []) if str(p).strip()]
        if len(raw) > MAX_PHRASES:
            raise RoutineError(f"{name}: at most {MAX_PHRASES} phrases.")
        phrases = []
        mine = {normalize(name), plain(name)}
        if len(normalize(name)) < 4:
            raise RoutineError(f"{name}: the name is too short to say on purpose (at least 4 letters).")
        for p in raw:
            n = plain(p)
            if len(n) < 4:
                raise RoutineError(f"{name}: “{p.strip()[:30]}” is too short to say on purpose (at least 4 letters).")
            if n not in mine:
                mine.add(n)
                phrases.append(" ".join(p.split())[:60])
        for n in mine:
            if n in used and used[n] != name.lower():
                raise RoutineError(f"“{n}” already starts the routine {used[n]!r}.")
        for n in mine:
            used[n] = name.lower()
        rid = str(item.get("id") or "")
        if not re.fullmatch(r"[a-z0-9]{6,16}", rid):
            rid = secrets.token_hex(4)
        out.append({"id": rid, "name": name, "phrases": phrases, "steps": steps})
    names = [r["name"].lower() for r in out]
    if len(set(names)) != len(names):
        raise RoutineError("two routines have the same name.")
    return out


def load(config: Path | None = None) -> list[dict]:
    try:
        return clean(json.loads((config or CONFIG).read_text("utf-8")).get("routines", []))
    except (OSError, ValueError, RoutineError):
        return []


def save(items, config: Path | None = None) -> list[dict]:
    tidy = clean(items)
    target = config or CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps({"routines": tidy}, indent=1), "utf-8")
        os.replace(tmp, target)
    return tidy


def find(key: str, routines: list[dict] | None = None) -> dict | None:
    """A routine by its id or its name."""
    for r in load() if routines is None else routines:
        if r["id"] == key or r["name"].lower() == str(key).strip().lower():
            return r
    return None


def match(text: str, routines: list[dict] | None = None) -> dict | None:
    """The routine a sentence asks for: its name in any of the usual ways ("movie night", "start the movie night routine"), or one of its other phrases exactly."""
    flexible, exact = normalize(text), plain(text)
    if not flexible and not exact:
        return None
    for r in load() if routines is None else routines:
        name_keys, phrase_keys = keys(r)
        if (flexible and flexible == normalize(r["name"])) or exact in name_keys or exact in phrase_keys:
            return r
    return None


# ---- running one -----------------------------------------------------------------------------------------------------------
_TIMER = re.compile(r"^(?:set (?:a |an )?|start (?:a |an )?)?timer(?: for| of)? (\d+(?:\.\d+)?) ?(seconds?|secs?|minutes?|mins?|hours?|hrs?)(?: (?:called|for|labell?ed|named))?(?: (.+))?$")
_WAIT = re.compile(r"^(?:wait|pause)(?: for)? (\d+(?:\.\d+)?) ?(seconds?|secs?|s)$")
_SAY = re.compile(r"^(?:say|tell me|announce)[:,]? (.+)$")
_NOTE = re.compile(r"^(?:note|add a note|put a note|write a note)[:,]? (?:that |saying )?(.+)$")


def parse_step(step: str):
    """("timer", seconds, label) | ("wait", seconds) | ("say", text) | ("note", text) | ("command", sentence)."""
    s = " ".join(str(step).split())
    low = s.lower().rstrip(".!")
    m = _TIMER.match(low)
    if m:
        unit = m.group(2)[0]
        seconds = float(m.group(1)) * (3600 if unit == "h" else 60 if unit == "m" else 1)
        if not 1 <= seconds <= 86400:
            raise RoutineError("a timer is between 1 second and 24 hours.")
        return "timer", round(seconds), (m.group(3) or "")[:30]
    m = _WAIT.match(low)
    if m:
        return "wait", min(float(m.group(1)), MAX_WAIT_S)
    m = _SAY.match(s)
    if m:
        return "say", m.group(1)[:200]
    m = _NOTE.match(s)
    if m:
        return "note", m.group(1)[:200]
    return "command", s


def run(routine: dict, runner: Callable[[str], dict], tell_page: Callable[[dict], None] | None = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    """Runs the steps in order. `runner(sentence)` is what answers a spoken command (the lights, music, apps...) and returns {handled, ok, text}.
    Returns {text, done, total, problems}."""
    problems, done, waited = [], 0, 0.0
    steps = routine["steps"]
    for number, step in enumerate(steps, 1):
        try:
            kind, *rest = parse_step(step)
            if kind == "wait":
                pause = min(rest[0], MAX_TOTAL_WAIT_S - waited)
                if pause > 0:
                    sleep(pause)
                    waited += pause
            elif kind == "timer":
                if tell_page is None:
                    raise RoutineError("a timer needs the PC's page to be open.")
                tell_page({"type": "phone_event", "event": {"type": "timer", "action": "start", "seconds": rest[0], "label": rest[1]}})
            elif kind == "say":
                if tell_page is None:
                    raise RoutineError("speaking needs the PC's page to be open.")
                tell_page({"type": "notify", "title": routine["name"], "text": rest[0], "speak": rest[0]})
            elif kind == "note":
                if tell_page is None:
                    raise RoutineError("a note needs the PC's page to be open.")
                tell_page({"type": "phone_event", "event": {"type": "add_note", "text": rest[0], "color": "cyan"}})
            else:
                result = runner(rest[0])
                if not result.get("handled"):
                    raise RoutineError("I don't know how to do that one by itself.")
                if not result.get("ok", True):
                    raise RoutineError(str(result.get("text") or "it did not work.").strip())
            done += 1
        except RoutineError as e:
            problems.append(f"step {number} (“{str(step)[:40]}”): {e}")
        except Exception as e:  # noqa: BLE001 - one broken step must not stop the rest
            problems.append(f"step {number} (“{str(step)[:40]}”): {e.__class__.__name__}")
    total = len(steps)
    if not problems:
        text = f"{routine['name']}: done."
    else:
        text = f"{routine['name']}: {done} of {total} steps worked. {problems[0]}"
    return {"text": text, "done": done, "total": total, "problems": problems}


def handle_voice(text: str, runner: Callable[[str], dict], tell_page=None, routines: list[dict] | None = None, sleep=time.sleep) -> dict:
    """{handled, ok, text}: "movie night" and "start the movie night routine" run the routine; any other sentence is not taken."""
    r = match(text, routines)
    if r is None:
        return {"handled": False, "text": ""}
    out = run(r, runner, tell_page, sleep)
    return {"handled": True, "ok": not out["problems"], "text": out["text"], "routine": r["name"]}
