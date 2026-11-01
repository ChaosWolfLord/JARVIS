"""Messages from programs on this PC that want JARVIS to say something, currently Claude Code ("Claude has finished in JARVIS").

Only two things reach the page: one of a few fixed kinds of message, and a short project name. The wording is chosen here (in JARVIS's
current personality), never by the sender, so a program that gets hold of the token can make JARVIS say "Claude has finished in <name>",
not an arbitrary sentence. The token lives in %LOCALAPPDATA%\\jarvis\\notify.token; web pages can't send these at all (JARVIS's request
guard refuses them), and nothing is spoken while the privacy screen is up.
"""
from __future__ import annotations

import hmac
import re
import secrets
import time

from . import persona, store

TOKEN_FILE = store.STATE / "notify.token"
KINDS = {"finished": "claude_finished", "permission": "claude_permission", "idle": "claude_idle", "failed": "claude_failed"}
MIN_GAP = 3.0                     # seconds: a program stuck in a loop can't make JARVIS talk non-stop


def token(path=None) -> str:
    """The shared secret, created the first time it is needed."""
    path = path or TOKEN_FILE
    try:
        value = path.read_text("utf-8").strip()
        if len(value) >= 20:
            return value
    except OSError:
        pass
    value = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, "utf-8")
    return value


def valid(given, path=None) -> bool:
    return bool(given) and hmac.compare_digest(str(given).encode(), token(path).encode())


def clean_project(name: str) -> str:
    """A folder name that is safe to show and say: letters, digits, spaces and . _ - only, short."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w .\-]", "", str(name or ""))).strip()[:40]


def compose(kind: str, project: str = "") -> dict:
    """What the page shows and says for this kind of message, in the current personality."""
    if kind not in KINDS:
        raise ValueError("unknown kind of message")
    project = clean_project(project)
    where = f" in {project}" if project else ""
    text = persona.line(KINDS[kind], where=where)
    return {"title": "Claude Code", "text": text, "speak": text, "level": "warn" if kind in ("permission", "failed") else "info"}


class Limiter:
    def __init__(self, now=time.time) -> None:
        self.now, self.last = now, 0.0

    def allow(self) -> bool:
        t = self.now()
        if t - self.last < MIN_GAP:
            return False
        self.last = t
        return True


limiter = Limiter()
