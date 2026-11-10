"""Small JSON-file stores: facts JARVIS knows about the user, plus throwaway state (usage, cooldowns).

Memory lives in the project's data/ folder (it syncs with OneDrive, so it survives a PC swap). The
throwaway state lives in %LOCALAPPDATA%\\jarvis, outside OneDrive: sync clients briefly lock files they
are uploading, and a locked counter shouldn't be able to break a chat.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

log = logging.getLogger("jarvis")

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)
STATE = Path(os.getenv("LOCALAPPDATA") or DATA) / "jarvis"
STATE.mkdir(parents=True, exist_ok=True)
ENV_FILE = STATE / ".env"       # secrets (API keys) live here, outside OneDrive; a .env in the project folder still works
MEMORY_FILE = DATA / "memory.json"
USAGE_FILE = STATE / "usage.json"
UI_SETTINGS_FILE = STATE / "ui_settings.json"      # the page's own settings (widget layout, weather place...), kept out of the browser
# The only settings the page may store here (web/settings.js lists the same keys), each as the text the page keeps in the browser.
UI_KEYS = frozenset({
    "jarvis.weather", "jarvis.widgets", "jarvis.widget.layout2", "jarvis.voice", "jarvis.warp.v1", "jarvis.ambient", "jarvis.timers",
    "jarvis.panel", "jarvis.touch", "jarvis.lights", "jarvis.usage", "jarvis.usage.measure", "jarvis.usage.source", "jarvis.alerts.seen",
    "jarvis.sounds", "jarvis.boot", "jarvis.voice.on", "jarvis.look",
})
UI_VALUE_LIMIT = 100_000
COOLDOWN_FILE = STATE / "cooldowns.json"

# Earlier versions kept these two in data/: carry them over once.
for _name in ("usage.json", "cooldowns.json"):
    _old, _new = DATA / _name, STATE / _name
    if _old.exists() and not _new.exists():
        try:
            shutil.copy2(_old, _new)
        except OSError:
            pass

_lock = threading.Lock()
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)  # seconds to wait when Windows says the file is busy


def _read(path: Path, default, strict: bool = False):
    """Reads JSON. A busy file is retried; if it stays busy, strict reads raise and others use the default."""
    for delay in (*_RETRY_DELAYS, None):
        try:
            return json.loads(path.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return default
        except PermissionError:
            if delay is None:
                if strict:
                    raise
                return default
            time.sleep(delay)


_write_lock = threading.Lock()


def _write(path: Path, obj) -> None:
    """Writes via a temp file and rename, retrying while something else (e.g. OneDrive, a virus scanner) holds the file.
    One write at a time: two page requests saving settings at once used to fight over the same temp file, and one of them failed with
    "Permission denied" (a 500 error in the log)."""
    data = json.dumps(obj, indent=2)
    with _write_lock:
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        for delay in (*_RETRY_DELAYS, None):
            try:
                tmp.write_text(data, "utf-8")
                tmp.replace(path)
                return
            except PermissionError:
                if delay is None:
                    tmp.unlink(missing_ok=True)
                    raise
                time.sleep(delay)


def load_env() -> None:
    """Loads API keys and settings: first %LOCALAPPDATA%\\jarvis\\.env (not uploaded by OneDrive), then the project's own
    .env, which is how it used to work. A variable already set is never overwritten, so the first file wins."""
    from dotenv import load_dotenv

    for path in (ENV_FILE, ROOT / ".env"):
        load_dotenv(path)


# ---- memory ---------------------------------------------------------------
# Long-term facts about the user. Each has a kind, can be pinned (always told to the AI), and is found again by
# searching: the AI is only shown the pinned ones and the ones that match what you just said, not the whole list.

KINDS = ("fact", "preference", "person", "project", "event")
STOPWORDS = frozenset("""a an and are as at be but by do does for from had has have he her his i if in is it its me my of on or
our she so than that the their them then there these they this to up us was we were what when where which who will with you your
about can could just not no yes also very really""".split())


def _stem(word: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    return [_stem(w) for w in re.findall(r"[a-z0-9']+", str(text).lower()) if w not in STOPWORDS and len(w) > 1]


def _complete(entry: dict) -> dict:
    """An entry with every field present (older saves only had id, fact and created)."""
    entry.setdefault("kind", "fact")
    entry.setdefault("updated", entry.get("created"))
    entry.setdefault("last_used", None)
    entry.setdefault("uses", 0)
    entry.setdefault("pinned", False)
    return entry


def list_facts() -> list[dict]:
    return [_complete(f) for f in _read(MEMORY_FILE, [], strict=True)]  # never mistake a busy file for "no memories"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _similar(a: str, b: str) -> bool:
    """Is one of these just a rewording of the other? Compares the words that matter."""
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return a.strip().lower() == b.strip().lower()
    return len(ta & tb) / len(ta | tb) >= 0.8


def add_fact(fact: str, kind: str = "fact", pinned: bool = False) -> dict:
    """Saves a fact. If it's a rewording of one already known, that one is updated instead (the result has merged=True)."""
    kind = kind if kind in KINDS else "fact"
    with _lock:
        facts = list_facts()
        for f in facts:
            if _similar(f["fact"], fact):
                f.update(fact=fact, kind=kind if kind != "fact" else f["kind"], updated=_now(), pinned=f["pinned"] or pinned)
                _write(MEMORY_FILE, facts)
                return {**f, "merged": True}
        entry = _complete({"id": max((f["id"] for f in facts), default=0) + 1, "fact": fact, "created": _now(), "kind": kind, "pinned": pinned})
        facts.append(entry)
        _write(MEMORY_FILE, facts)
        return entry


def update_fact(fact_id: int, fact: str | None = None, kind: str | None = None, pinned: bool | None = None) -> dict | None:
    with _lock:
        facts = list_facts()
        for f in facts:
            if f["id"] == fact_id:
                if fact is not None:
                    f["fact"] = fact
                if kind in KINDS:
                    f["kind"] = kind
                if pinned is not None:
                    f["pinned"] = bool(pinned)
                f["updated"] = _now()
                _write(MEMORY_FILE, facts)
                return f
        return None


def remove_fact(fact_id: int) -> bool:
    with _lock:
        facts = list_facts()
        kept = [f for f in facts if f["id"] != fact_id]
        if len(kept) == len(facts):
            return False
        _write(MEMORY_FILE, kept)
        return True


def search_facts(query: str, limit: int = 8, facts: list[dict] | None = None) -> list[dict]:
    """The facts that best match the words in `query`, best first (BM25-style: rare words count for more)."""
    import math

    facts = list_facts() if facts is None else facts
    q = set(tokens(query))
    if not q or not facts:
        return []
    docs = [tokens(f"{f['fact']} {f['kind']}") for f in facts]
    n = len(docs)
    scored = []
    for f, doc in zip(facts, docs):
        score = 0.0
        for term in q:
            tf = sum(1 for w in doc if w == term or (len(term) >= 4 and (w.startswith(term) or term.startswith(w)) and len(w) >= 4))
            if tf:
                df = sum(1 for d in docs if any(w == term or (len(term) >= 4 and len(w) >= 4 and (w.startswith(term) or term.startswith(w))) for w in d))
                score += math.log(1 + n / (1 + df)) * (tf * 2.2) / (tf + 1.2)
        if score > 0:
            scored.append((score, f))
    scored.sort(key=lambda s: (-s[0], -s[1]["id"]))
    return [f for _, f in scored[:limit]]


def facts_for_prompt(message: str, max_chars: int = 1800, recent: int = 4) -> tuple[list[dict], int]:
    """What the AI is told this turn: pinned facts, the ones matching the message, and the newest few, within a size budget.

    Returns (facts, total number known). The facts that are used get their use count and last-used time updated."""
    facts = list_facts()
    chosen: list[dict] = []

    def take(candidates):
        for f in candidates:
            if f not in chosen:
                chosen.append(f)

    take(sorted((f for f in facts if f["pinned"]), key=lambda f: f["id"]))
    take(search_facts(message, 8, facts))
    take(sorted(facts, key=lambda f: f["id"], reverse=True)[:recent])
    kept, size = [], 0
    for f in chosen:
        size += len(f["fact"]) + 24
        if size > max_chars and not f["pinned"]:
            break
        kept.append(f)
    if kept:
        _touch([f["id"] for f in kept])
    return kept, len(facts)


def _touch(ids: list[int]) -> None:
    """Counts a use for each fact. Skipped quietly if the file is busy: it's only a statistic."""
    try:
        with _lock:
            facts = list_facts()
            for f in facts:
                if f["id"] in ids:
                    f["uses"] += 1
                    f["last_used"] = _now()
            _write(MEMORY_FILE, facts)
    except OSError:
        pass


# ---- whiteboard -----------------------------------------------------------
# The board (ink, notes) is kept here so it survives clearing the browser, switching browsers and moving to a new PC
# (data/ syncs with OneDrive). Backups live outside OneDrive: one every ten minutes while it changes.

BOARD_FILE = DATA / "board.json"
BACKUP_DIR = STATE / "backups"
BACKUP_EVERY = 600       # seconds between backups while the board is changing
KEEP_RECENT = 48         # newest backups always kept; older ones are thinned to one per day for KEEP_DAYS
KEEP_DAYS = 30
_BACKUP_NAME = re.compile(r"^board-\d{8}-\d{6}(-before-restore)?\.json$")
_last_backup = {"time": 0.0, "digest": None}


def load_board() -> dict | None:
    """The saved board, or None if there is none yet. A busy file raises, so a stale copy is never mistaken for 'empty'."""
    data = _read(BOARD_FILE, None, strict=True)
    return data if isinstance(data, dict) else None


def save_board(board: dict) -> None:
    with _lock:
        _write(BOARD_FILE, board)
        _maybe_backup(board)


def _digest(board: dict) -> str:
    return hashlib.sha1(json.dumps([board.get("strokes"), board.get("notes")], sort_keys=True).encode()).hexdigest()


def _write_backup(board: dict, suffix: str = "") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now()
    while (path := BACKUP_DIR / f"board-{stamp:%Y%m%d-%H%M%S}{suffix}.json").exists():
        stamp += timedelta(seconds=1)  # two backups in the same second must not overwrite each other
    path.write_text(json.dumps(board), "utf-8")
    return path


def _maybe_backup(board: dict) -> None:
    """Takes a backup if the board changed and the last one is old enough, then thins out old ones."""
    try:
        now = time.time()
        digest = _digest(board)
        if digest == _last_backup["digest"] or now - _last_backup["time"] < BACKUP_EVERY:
            return
        if not board.get("strokes") and not board.get("notes"):
            return  # never spend a backup slot on an empty board
        _write_backup(board)
        _last_backup.update(time=now, digest=digest)
        _prune_backups()
    except OSError as e:
        log.warning("couldn't back up the board: %s", e)


def _prune_backups() -> None:
    files = sorted(BACKUP_DIR.glob("board-*.json"), reverse=True)  # names sort by time, newest first
    seen_days: set[str] = set()
    cutoff = datetime.now() - timedelta(days=KEEP_DAYS)
    for i, path in enumerate(files):
        if i < KEEP_RECENT:
            continue
        day = path.name[6:14]
        stamp = datetime.strptime(path.name[6:21], "%Y%m%d-%H%M%S")
        if stamp < cutoff or day in seen_days:
            path.unlink(missing_ok=True)
        else:
            seen_days.add(day)


def list_board_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    out = []
    for path in sorted(BACKUP_DIR.glob("board-*.json"), reverse=True)[:60]:
        stamp = datetime.strptime(path.name[6:21], "%Y%m%d-%H%M%S")
        out.append({"name": path.name, "time": stamp.isoformat(timespec="seconds"), "kb": max(1, round(path.stat().st_size / 1024))})
    return out


def restore_board_backup(name: str) -> dict:
    """Makes a backup the current board (after backing up what is there now). Returns the restored board."""
    if not _BACKUP_NAME.match(name):
        raise ValueError("not a backup name")
    path = BACKUP_DIR / name
    board = json.loads(path.read_text("utf-8"))
    with _lock:
        current = _read(BOARD_FILE, None)
        if isinstance(current, dict) and (current.get("strokes") or current.get("notes")):
            _write_backup(current, "-before-restore")
        board["savedAt"] = int(time.time() * 1000)
        _write(BOARD_FILE, board)
        _last_backup.update(time=time.time(), digest=_digest(board))
    return board


# ---- model cooldowns ------------------------------------------------------
# Remembered across restarts so an exhausted daily quota isn't retried (and failed) on every launch.

def load_cooldowns() -> dict[str, float]:
    now = time.time()
    return {k: v for k, v in _read(COOLDOWN_FILE, {}).items() if v > now}


def save_cooldowns(cooldowns: dict[str, float]) -> None:
    try:
        with _lock:
            _write(COOLDOWN_FILE, cooldowns)
    except OSError as e:  # worth remembering, not worth failing a chat over
        log.warning("couldn't save cooldowns: %s", e)


# ---- usage ----------------------------------------------------------------
# Free tiers cap requests per minute and per day, so count requests rather than dollars.

def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def requests_today() -> int:
    data = _read(USAGE_FILE, {})
    return data.get("requests", 0) if data.get("day") == _today() else 0


# ---- token history --------------------------------------------------------
# One small record per day (not per request), so years of history stay a tiny file. Lives outside OneDrive.

HISTORY_FILE = STATE / "usage_history.json"


def record_usage(provider: str, model: str, prompt: int, completion: int, exact: bool = True) -> None:
    """Adds one model call's tokens to today's totals. exact=False means JARVIS estimated them (about 4 characters a token)."""
    try:
        with _lock:
            data = _read(HISTORY_FILE, {"days": {}})
            day = data.setdefault("days", {}).setdefault(
                _today(), {"requests": 0, "prompt": 0, "completion": 0, "estimated": 0, "models": {}})
            day["requests"] += 1
            day["prompt"] += max(0, int(prompt))
            day["completion"] += max(0, int(completion))
            day["estimated"] += 0 if exact else 1
            key = f"{provider}:{model}"
            day["models"][key] = day["models"].get(key, 0) + max(0, int(prompt)) + max(0, int(completion))
            _write(HISTORY_FILE, data)
    except OSError as e:  # a statistic: never worth failing a chat over
        log.warning("couldn't save token usage: %s", e)


def usage_summary(today=None, days_data: dict | None = None) -> dict:
    """Token totals and per-day averages for the usage widget: daily (30), weekly (12), monthly (12) and yearly series."""
    from datetime import date, timedelta

    today = today or date.today()
    raw = days_data if days_data is not None else _read(HISTORY_FILE, {}).get("days", {})

    def tokens(d: date) -> int:
        e = raw.get(d.isoformat())
        return (e["prompt"] + e["completion"]) if e else 0

    def requests(d: date) -> int:
        e = raw.get(d.isoformat())
        return e["requests"] if e else 0

    parsed = sorted(date.fromisoformat(k) for k in raw)
    first = parsed[0] if parsed else today

    def span(n: int) -> dict:
        """Totals over the last n days, and the average per day over the days JARVIS has actually existed."""
        start = today - timedelta(days=n - 1)
        total = sum(tokens(start + timedelta(days=i)) for i in range(n))
        reqs = sum(requests(start + timedelta(days=i)) for i in range(n))
        covered = max(1, min(n, (today - first).days + 1))
        return {"tokens": total, "requests": reqs, "avg_per_day": round(total / covered), "days": covered}

    daily = [{"label": f"{(today - timedelta(days=29 - i)):%b %d}", "tokens": tokens(today - timedelta(days=29 - i)),
              "requests": requests(today - timedelta(days=29 - i))} for i in range(30)]

    monday = today - timedelta(days=today.weekday())
    weekly = []
    for i in range(11, -1, -1):
        start = monday - timedelta(weeks=i)
        weekly.append({"label": f"{start:%b %d}", "tokens": sum(tokens(start + timedelta(days=k)) for k in range(7)),
                       "requests": sum(requests(start + timedelta(days=k)) for k in range(7))})

    def month_start(offset: int) -> date:
        y, m = today.year, today.month - offset
        while m < 1:
            y, m = y - 1, m + 12
        return date(y, m, 1)

    monthly = []
    for i in range(11, -1, -1):
        start = month_start(i)
        nxt = month_start(i - 1) if i else (date(today.year + (today.month == 12), today.month % 12 + 1, 1))
        keys = [k for k in parsed if start <= k < nxt]
        monthly.append({"label": f"{start:%b %y}", "tokens": sum(tokens(k) for k in keys), "requests": sum(requests(k) for k in keys)})

    years = sorted({k.year for k in parsed} | {today.year})
    yearly = [{"label": str(y), "tokens": sum(tokens(k) for k in parsed if k.year == y),
               "requests": sum(requests(k) for k in parsed if k.year == y)} for y in years]

    models: dict[str, int] = {}
    for i in range(30):
        entry = raw.get((today - timedelta(days=i)).isoformat())
        for name, n in (entry or {}).get("models", {}).items():
            models[name] = models.get(name, 0) + n
    estimated = sum(e.get("estimated", 0) for e in raw.values())
    total_requests = sum(e["requests"] for e in raw.values())
    return {
        "today": span(1), "week": span(7), "month": span(30), "year": span(365),
        "all": {"tokens": sum(e["prompt"] + e["completion"] for e in raw.values()), "requests": total_requests,
                "since": first.isoformat() if parsed else None},
        "daily": daily, "weekly": weekly, "monthly": monthly, "yearly": yearly,
        "models": [{"name": n, "tokens": t} for n, t in sorted(models.items(), key=lambda kv: -kv[1])[:5]],
        "estimated_share": round(estimated / total_requests, 2) if total_requests else 0,
    }


def _utc_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def provider_requests_today(provider: str) -> int:
    """Requests sent to one provider today. OpenRouter counts its free allowance by UTC day, so this does too."""
    entry = _read(USAGE_FILE, {}).get("by_provider", {}).get(provider, {})
    return entry.get("n", 0) if entry.get("day") == _utc_today() else 0


def record_request(provider: str | None = None) -> None:
    try:
        with _lock:
            data = _read(USAGE_FILE, {})
            if data.get("day") != _today():
                data = {"day": _today(), "requests": 0, "by_provider": data.get("by_provider", {})}
            data["requests"] = data.get("requests", 0) + 1
            if provider:
                by = data.setdefault("by_provider", {})
                entry = by.get(provider, {})
                if entry.get("day") != _utc_today():
                    entry = {"day": _utc_today(), "n": 0}
                entry["n"] += 1
                by[provider] = entry
            _write(USAGE_FILE, data)
    except OSError as e:  # the counter is just a display; never let it break a chat
        log.warning("couldn't update the request counter: %s", e)


def ui_settings() -> dict:
    """The page's saved settings: {key: text}."""
    saved = _read(UI_SETTINGS_FILE, {})
    return {k: v for k, v in saved.items() if k in UI_KEYS and isinstance(v, str)} if isinstance(saved, dict) else {}


def set_ui_settings(changes: dict) -> dict:
    """Applies {key: text or None (to forget it)}. Unknown keys and oversized values are ignored. Returns what is now saved."""
    current = ui_settings()
    for key, value in changes.items():
        if key not in UI_KEYS:
            continue
        if value is None:
            current.pop(key, None)
        elif isinstance(value, str) and len(value) <= UI_VALUE_LIMIT:
            current[key] = value
    _write(UI_SETTINGS_FILE, current)
    return current
