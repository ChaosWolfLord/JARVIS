"""The activity log: a plain record of what JARVIS did on your behalf, so you can see it and spot anything odd.

One line per action: the tool it used, a short description of what it asked for (a search, an email id, a web address;
never what came back), whether it worked or you refused it, and whether private data (mail, calendar, Discord, your files)
was involved. Requests the security guard turned away are logged too. Kept in %LOCALAPPDATA%\\jarvis\\logs\\activity.log,
outside OneDrive, and shown in the status menu.
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from . import store

log = logging.getLogger("jarvis")

LOG_FILE = store.STATE / "logs" / "activity.log"
MAX_BYTES = 2_000_000
_lock = threading.Lock()

PRIVATE_TOOLS = frozenset({"gmail_search", "gmail_read", "calendar_events", "discord_channels", "discord_read", "read_file", "list_files",
                           "gmail_draft_reply", "calendar_add_event", "discord_send"})


def record(kind: str, what: str, outcome: str = "ok", private: bool = False) -> None:
    """kind: tool name or 'blocked'; outcome: ok, error, denied or blocked. Never raises: logging must not break anything."""
    entry = {"t": datetime.now().isoformat(timespec="seconds"), "kind": kind, "what": str(what)[:200], "outcome": outcome, "private": private}
    try:
        with _lock:
            LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > MAX_BYTES:
                LOG_FILE.replace(LOG_FILE.with_suffix(".old.log"))
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("couldn't write the activity log: %s", e)


def recent(limit: int = 100) -> list[dict]:
    """The newest entries first."""
    try:
        lines = LOG_FILE.read_text("utf-8").splitlines()[-max(1, min(limit, 500)):]
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def describe(name: str, args: dict) -> str:
    """A short, safe description of a tool call for the log (what was asked for, never the answer)."""
    key = {
        "web_search": "query", "fetch_url": "url", "open_url": "url", "read_file": "path", "gmail_search": "query", "gmail_read": "id",
        "discord_read": "channel", "gmail_draft_reply": "id", "calendar_add_event": "title", "discord_send": "channel", "recall": "query", "remember": "fact", "forget": "id", "update_memory": "id",
    }.get(name)
    if key:
        return str(args.get(key, ""))
    if name == "music":
        return " ".join(str(v) for k, v in args.items() if k in ("action", "query", "device", "volume", "direction") and v not in (None, ""))[:100]
    if name in ("apps", "app_close"):
        return " ".join(str(v) for k, v in args.items() if k in ("action", "name", "pid") and v not in (None, ""))[:100]
    if name == "reminder":
        return " ".join(str(v) for k, v in args.items() if k in ("action", "text", "at", "minutes") and v not in (None, ""))[:100]
    if name == "lights":
        return " ".join(str(v) for k, v in args.items() if k in ("action", "target", "power", "brightness", "color", "kelvin", "scene") and v not in (None, ""))[:100]
    if name == "system_fix":
        return f"{args.get('action', '')} {args.get('target', '')}".strip()
    if name == "calendar_events":
        return f"{args.get('days_back', 0) or 0} days back, {args.get('days_ahead', 7)} days ahead"
    if name == "run_python":
        return str(args.get("code", "")).strip().splitlines()[0][:120] if str(args.get("code", "")).strip() else ""
    if name.startswith("mcp__"):
        return json.dumps(args, ensure_ascii=False)[:160]
    return ""


def tool(name: str, args: dict, result: str, private: bool) -> None:
    denied = result.startswith(("The user did not allow", "The user did not approve"))
    outcome = "denied" if denied else "error" if result.startswith("Error") else "ok"
    record(name, describe(name, args), outcome, private or name in PRIVATE_TOOLS)
