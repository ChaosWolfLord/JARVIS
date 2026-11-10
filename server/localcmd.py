"""Commands JARVIS answers itself, without asking an AI model: show off, lights, music and opening apps.

The PC's own page already does this for what you say or type there. This is the same for the phone (and anything else that sends text),
so "play some music", "lights off" or "show off" from the phone is instant and costs no AI request. Before, they went to the AI like any
question: slow when a model was busy, and impossible for "show off", which only the page can do. Anything that isn't one of these
is left for the AI.
"""
from __future__ import annotations

import re
from typing import Callable

from . import apps as apps_mod, audit, lights as lights_mod, music as music_mod, persona

_PREFIX = re.compile(r"^(?:hey )?jarvis ")
_SHOWOFF = re.compile(r"^(?:please )?(?:(stop|end|exit|quit|cancel|disable|leave)(?: the)?|(start|begin|enter|go into|activate|enable)(?: the)?)? ?(?:show|shoe)(?:ing)?[- ]?(?:off|of|offs)(?: mode)?$")
_SHOWOFF_STOP = re.compile(r"^(?:please )?(stop|end|cancel) showing off$")


def parse_showoff(text: str) -> str | None:
    """'on', 'off' or 'toggle' for a show-off command, None for anything else. The same words the page understands (web/showoff.js)."""
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z\- ]", " ", str(text).lower())).strip()
    t = _PREFIX.sub("", t)
    m = _SHOWOFF.match(t)
    if not m:
        return "off" if _SHOWOFF_STOP.match(t) else None
    return "off" if m.group(1) else "on" if m.group(2) else "toggle"


def handle(text: str, tell_page: Callable[[dict], None] | None = None) -> dict:
    """{handled, ok, text}. `tell_page` sends an event to the PC's page (show off lives there)."""
    text = str(text or "").strip()
    if not text:
        return {"handled": False, "ok": False, "text": ""}

    action = parse_showoff(text)
    if action:
        if tell_page is None:
            return {"handled": False, "ok": False, "text": ""}
        tell_page({"type": "command", "text": text})
        audit.record("showoff", action)
        return {"handled": True, "ok": True, "text": persona.line("showoff_off" if action == "off" else "showoff_on")}

    for kind, fn in (("lights", lights_mod.handle_voice), ("music", music_mod.handle_voice),
                     ("apps", lambda t: apps_mod.handle_voice(t) if apps_mod.available() else {"handled": False, "text": ""})):
        result = fn(text)
        if result.get("handled"):
            audit.record(kind, text[:100], "ok" if result.get("ok") else "error")
            return {"handled": True, "ok": bool(result.get("ok")), "text": result.get("text", "")}
    return {"handled": False, "ok": False, "text": ""}
