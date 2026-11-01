"""Claude Code token usage, read from the session logs Claude Code keeps on this PC.

Claude Code writes every conversation to ~/.claude/projects/**/*.jsonl, and each reply there carries its token
counts. JARVIS reads only the timestamp, model and token counts from those lines (never the conversation) and keeps
one small row per reply in a local database, so the totals survive Claude Code deleting old logs. Nothing is sent
anywhere. What this cannot see: chats on claude.ai (web or phone app), and your plan's 5-hour and weekly limits.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

from . import store

log = logging.getLogger("jarvis")

DB = store.STATE / "claude_usage.sqlite"
STALE_SECONDS = 60
_lock = threading.Lock()
state = {"scanning": False, "last": 0.0, "error": None, "files": 0}


def projects_dir() -> Path:
    base = os.getenv("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "projects"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=15)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS msgs (key TEXT PRIMARY KEY, day TEXT, model TEXT, inp INT, out INT, cw INT, cr INT);
        CREATE TABLE IF NOT EXISTS files (path TEXT PRIMARY KEY, size INT, off INT);
        CREATE INDEX IF NOT EXISTS msgs_day ON msgs(day);
    """)
    return conn


def parse_line(line: str) -> tuple | None:
    """(key, day, model, input, output, cache_write, cache_read) from one log line, or None if it isn't a counted reply."""
    if '"usage"' not in line or '"assistant"' not in line:
        return None            # cheap check first: most lines are not replies, and parsing them all would be slow
    try:
        obj = json.loads(line)
    except ValueError:
        return None
    if obj.get("type") != "assistant":
        return None
    msg = obj.get("message")
    usage = msg.get("usage") if isinstance(msg, dict) else None
    model = msg.get("model") if isinstance(msg, dict) else None
    if not isinstance(usage, dict) or not model or str(model).startswith("<"):
        return None            # "<synthetic>" entries are Claude Code's own notices, not model calls
    try:
        day = datetime.fromisoformat(str(obj["timestamp"]).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
    except (KeyError, ValueError):
        return None
    # A reply is logged once per content block, all sharing the message id: they're one reply, counted once below.
    key = f"{msg.get('id') or obj.get('uuid')}|{obj.get('requestId') or ''}"

    def n(name: str) -> int:
        v = usage.get(name)
        return int(v) if isinstance(v, (int, float)) else 0

    return (key, day, str(model), n("input_tokens"), n("output_tokens"),
            n("cache_creation_input_tokens"), n("cache_read_input_tokens"))


def scan_file(conn: sqlite3.Connection, path: Path) -> int:
    """Reads what was added to one log since last time. Returns the number of reply lines found."""
    try:
        size = path.stat().st_size
    except OSError:
        return 0
    row = conn.execute("SELECT size, off FROM files WHERE path = ?", (str(path),)).fetchone()
    offset = row[1] if row else 0
    if row and size == row[0]:
        return 0
    if size < offset:
        offset = 0             # the log was rewritten: start again (replies already stored are kept, the ids dedupe)
    rows, pos = [], offset
    try:
        with path.open("rb") as f:
            f.seek(offset)
            for raw in f:
                if not raw.endswith(b"\n"):
                    break      # a half-written last line: pick it up next time
                pos += len(raw)
                parsed = parse_line(raw.decode("utf-8", errors="replace"))
                if parsed:
                    rows.append(parsed)
    except OSError as e:
        log.warning("couldn't read %s: %s", path, e)
        return 0
    conn.executemany(
        """INSERT INTO msgs (key, day, model, inp, out, cw, cr) VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET inp = max(inp, excluded.inp), out = max(out, excluded.out),
                                          cw = max(cw, excluded.cw), cr = max(cr, excluded.cr)""", rows)
    conn.execute("INSERT OR REPLACE INTO files (path, size, off) VALUES (?, ?, ?)", (str(path), size, pos))
    conn.commit()
    return len(rows)


def refresh(root: Path | None = None) -> int:
    """Scans every log for new replies. Safe to call from several places: only one scan runs at a time."""
    if not _lock.acquire(blocking=False):
        return 0
    state.update(scanning=True, error=None)
    found = 0
    try:
        root = root or projects_dir()
        conn = _connect()
        try:
            paths = sorted(root.rglob("*.jsonl")) if root.exists() else []
            state["files"] = len(paths)
            for path in paths:
                found += scan_file(conn, path)
        finally:
            conn.close()
    except (sqlite3.Error, OSError) as e:
        state["error"] = str(e)
        log.warning("Claude Code usage scan failed: %s", e)
    finally:
        state.update(scanning=False, last=time.time())
        _lock.release()
    return found


def refresh_in_background() -> None:
    if not state["scanning"] and time.time() - state["last"] > STALE_SECONDS:
        threading.Thread(target=refresh, daemon=True).start()


def days_data(measure: str = "all") -> dict:
    """{day: {requests, prompt, completion, estimated, models}} in the shape store.usage_summary reads.

    measure "all" counts every token the model processed, including re-reads of cached context (which is most of
    them in long sessions). "fresh" leaves out cache reads: new input, cache writes and output only.
    """
    conn = _connect()
    try:
        out: dict = {}
        for day, model, count, inp, outp, cw, cr in conn.execute(
                "SELECT day, model, count(*), sum(inp), sum(out), sum(cw), sum(cr) FROM msgs GROUP BY day, model"):
            entry = out.setdefault(day, {"requests": 0, "prompt": 0, "completion": 0, "estimated": 0, "models": {}})
            prompt = inp + cw + (cr if measure == "all" else 0)
            entry["requests"] += count
            entry["prompt"] += prompt
            entry["completion"] += outp
            entry["models"][model] = entry["models"].get(model, 0) + prompt + outp
        return out
    finally:
        conn.close()


def summary(measure: str = "all") -> dict:
    refresh_in_background()
    measure = "fresh" if measure == "fresh" else "all"
    data = store.usage_summary(days_data=days_data(measure))
    data["source"] = "claude-code"
    data["measure"] = measure
    data["scanning"] = state["scanning"]
    data["files"] = state["files"]
    data["error"] = state["error"]
    return data
