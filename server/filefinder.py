"""File finder: "find the doc I edited yesterday about the budget", "find my pdfs from last week", "where is the invoice spreadsheet".

It looks only in folders you added yourself (status menu, "Files JARVIS may search"); until you add one it searches nothing. It reads file names, folder
names and dates, and for small text, Word, Excel and PowerPoint files also the words inside, to match what you describe. Nothing leaves the PC: the
answer is shown on the wall (or the phone), and no file is uploaded anywhere.

Guard rails:
  * Only the chosen folders (and what is under them) are ever looked at, never a whole drive, Windows, Program Files, program data or JARVIS's own data.
  * Whatever the folders hold, files that look like secrets are never listed, read or opened: .env files, keys and certificates, password stores, files with
    "password", "secret", "token", "credential" or "private key" in the name.
  * Opening a result is limited to documents, pictures, music, video and similar; programs and scripts (.exe, .bat, .ps1, .lnk ...) are never launched,
    but "show in folder" works for anything that is listed.
  * Links and junctions are not followed, so a folder cannot lead the search somewhere you did not choose.
  * A search stops after a few seconds and after a fixed number of files.
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from . import store

CONFIG = store.STATE / "finder.json"
MAX_FOLDERS = 12
MAX_FILES = 150_000
TIME_BUDGET_S = 6.0
CONTENT_FILES = 400                   # how many files' contents one search may read
CONTENT_BYTES = 300_000
LIST_TTL_S = 120.0

SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "site-packages", "$recycle.bin", "system volume information", "appdata", ".ssh", ".aws",
             ".gnupg", ".azure", ".kube", ".docker", ".cache", ".npm", ".gradle"}
SECRET_NAME = re.compile(r"(^\.env|\.env$|\.pem$|\.key$|\.pfx$|\.p12$|\.kdbx$|\.keystore$|\.jks$|id_rsa|id_ed25519|password|passwd|secret|token|credential|private.?key|wallet|seed.?phrase|recovery.?code)", re.I)
NEVER_OPEN = {".exe", ".bat", ".cmd", ".com", ".scr", ".msi", ".msp", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".lnk", ".url", ".reg", ".jar", ".dll",
              ".sys", ".cpl", ".pif", ".gadget", ".application", ".appx", ".msix", ".chm", ".inf", ".sh", ".py", ".pyw", ".apk"}
TEXT_EXT = {".txt", ".md", ".csv", ".tsv", ".log", ".json", ".xml", ".html", ".htm", ".rtf", ".tex", ".ini", ".yaml", ".yml", ".py", ".js", ".ts", ".css", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rs", ".sql"}
ZIP_TEXT = {".docx": ("word/document.xml",), ".xlsx": ("xl/sharedStrings.xml",), ".pptx": ("ppt/slides/",), ".odt": ("content.xml",), ".ods": ("content.xml",), ".odp": ("content.xml",)}

TYPES = {                              # what people call a kind of file -> its extensions
    "document": {".doc", ".docx", ".odt", ".rtf", ".txt", ".md", ".pdf"},
    "pdf": {".pdf"},
    "spreadsheet": {".xls", ".xlsx", ".csv", ".ods", ".tsv"},
    "presentation": {".ppt", ".pptx", ".odp", ".key"},
    "image": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".tif", ".tiff"},
    "video": {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv", ".m4v"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"},
    "archive": {".zip", ".7z", ".rar"},
}
TYPE_WORDS = {
    "document": "document", "documents": "document", "doc": "document", "docs": "document", "word": "document", "essay": "document", "letter": "document", "report": "document",
    "pdf": "pdf", "pdfs": "pdf", "spreadsheet": "spreadsheet", "spreadsheets": "spreadsheet", "sheet": "spreadsheet", "sheets": "spreadsheet", "excel": "spreadsheet", "csv": "spreadsheet",
    "presentation": "presentation", "presentations": "presentation", "slides": "presentation", "slideshow": "presentation", "powerpoint": "presentation", "deck": "presentation",
    "photo": "image", "photos": "image", "picture": "image", "pictures": "image", "image": "image", "images": "image", "screenshot": "image", "screenshots": "image", "pic": "image", "pics": "image",
    "video": "video", "videos": "video", "recording": "video", "recordings": "video", "movie": "video", "clip": "video", "clips": "video",
    "song": "audio", "songs": "audio", "music": "audio", "audio": "audio", "mp3": "audio",
}
STOP = set("""find search searching look looking locate get show me us the my a an that those these any all some file files please can could you would where is was were are it
i we edited edit modified changed saved made worked work on opened open created wrote written downloaded download from of to in at about called named with for and or last this week weeks
month months day days ago yesterday today night recently recent latest newest oldest one thing stuff""".split())
OPENABLE_NOTE = "documents, pictures, music, video and similar"


class FinderError(ValueError):
    """What is wrong, in words the person can act on."""


# ---- the chosen folders ---------------------------------------------------------------------------------------------------
_lock = threading.Lock()
_listing: dict[str, tuple[float, list]] = {}


def _blocked_roots() -> list[Path]:
    roots = []
    for var in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "SystemRoot"):
        if os.getenv(var):
            roots.append(Path(os.environ[var]))
    roots.append(store.STATE)                                      # JARVIS's own data: pairing tokens, saved keys, the activity log
    roots.append(store.ROOT / "data")
    appdata = os.getenv("APPDATA")
    if appdata:
        roots.append(Path(appdata))
    return roots


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def clean_folder(raw: str) -> Path:
    """A folder the finder may be given, or FinderError saying why not."""
    text = str(raw or "").strip().strip('"')
    if not text:
        raise FinderError("type or pick a folder.")
    path = Path(os.path.expandvars(os.path.expanduser(text)))
    try:
        path = path.resolve()
    except OSError:
        raise FinderError("that folder could not be read.") from None
    if not path.is_dir():
        raise FinderError("that is not a folder on this PC.")
    if len(path.parts) <= 1:
        raise FinderError("choose a folder, not a whole drive.")
    if path == Path.home() or path == Path.home().parent:
        raise FinderError("choose a folder inside your user folder (Documents, Downloads...), not the whole thing.")
    given = Path(os.path.abspath(os.path.expandvars(os.path.expanduser(text))))      # also as typed: some systems redirect a folder behind the scenes
    for root in _blocked_roots():
        try:
            forms = {root, root.resolve()}
        except OSError:
            forms = {root}
        for r in forms:
            if any(_inside(p, r) or _inside(r, p) for p in (path, given)):
                raise FinderError("that folder holds system, program or JARVIS data, so it can't be searched.")
    return path


def folders(config: Path | None = None) -> list[str]:
    try:
        data = json.loads((config or CONFIG).read_text("utf-8"))
        return [str(f) for f in data.get("folders", []) if isinstance(f, str)][:MAX_FOLDERS]
    except (OSError, ValueError):
        return []


def set_folders(paths: list[str], config: Path | None = None) -> list[str]:
    """Replaces the list (each folder is checked). Returns what was saved."""
    if len(paths) > MAX_FOLDERS:
        raise FinderError(f"at most {MAX_FOLDERS} folders.")
    seen, kept = set(), []
    for raw in paths:
        p = str(clean_folder(raw))
        if p.lower() not in seen:
            seen.add(p.lower())
            kept.append(p)
    target = config or CONFIG
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"folders": kept}, indent=1), "utf-8")
    os.replace(tmp, target)
    with _lock:
        _listing.clear()
    return kept


def suggestions() -> list[str]:
    """The usual places, for one-click adding (only those that exist)."""
    home = Path.home()
    found = []
    for name in ("Documents", "Downloads", "Desktop", "Pictures", "Videos", "Music"):
        for base in (home, home / "OneDrive"):
            p = base / name
            if p.is_dir() and str(p) not in found:
                found.append(str(p))
    return found


# ---- looking through them -------------------------------------------------------------------------------------------------
def _secret(name: str) -> bool:
    return bool(SECRET_NAME.search(name))


def _is_link(entry: os.DirEntry) -> bool:
    try:
        if entry.is_symlink():
            return True
        attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
        return bool(attrs & 0x400)                                  # a Windows junction or reparse point
    except OSError:
        return True


def _walk(root: str, deadline: float, budget: list[int]):
    """Every file under `root` as (path, name, mtime, size), without following links, skipping hidden things and secrets."""
    stack = [root]
    while stack and time.monotonic() < deadline and budget[0] > 0:
        folder = stack.pop()
        try:
            it = os.scandir(folder)
        except OSError:
            continue
        with it:
            for entry in it:
                if budget[0] <= 0 or time.monotonic() >= deadline:
                    return
                name = entry.name
                if name.startswith(".") or _is_link(entry):
                    continue
                try:
                    if entry.is_dir(follow_symlinks=False):
                        if name.lower() not in SKIP_DIRS:
                            stack.append(entry.path)
                        continue
                    if _secret(name):
                        continue
                    st = entry.stat(follow_symlinks=False)
                    if getattr(st, "st_file_attributes", 0) & 0x2:           # hidden
                        continue
                except OSError:
                    continue
                budget[0] -= 1
                yield entry.path, name, st.st_mtime, st.st_size


def listing(root: str, deadline: float, now: float | None = None) -> list:
    """The files under a chosen folder, remembered for two minutes so a second question is quick."""
    now = time.monotonic() if now is None else now
    with _lock:
        hit = _listing.get(root)
        if hit and now - hit[0] < LIST_TTL_S:
            return hit[1]
    files = list(_walk(root, deadline, [MAX_FILES]))
    if time.monotonic() < deadline:                                   # an unfinished walk is not remembered
        with _lock:
            _listing[root] = (now, files)
    return files


# ---- understanding the request ---------------------------------------------------------------------------------------------
def parse_when(text: str, now: datetime.datetime) -> tuple[float | None, float | None, str]:
    """(start, end, the words left) for "yesterday", "last week", "this month", "last 3 days"... Times are the file's modified time."""
    t = " " + text.lower() + " "
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    def span(a: datetime.datetime, b: datetime.datetime, phrase: str):
        return a.timestamp(), b.timestamp(), t.replace(phrase, " ", 1)

    one = datetime.timedelta(days=1)
    monday = today - datetime.timedelta(days=today.weekday())
    m = re.search(r"\b(?:in |over |from )?the (?:last|past) (\d{1,3}|a|one|two|three|four|five|six|seven) (day|days|week|weeks|month|months)\b", t) or \
        re.search(r"\b(?:last|past) (\d{1,3}|a|one|two|three|four|five|six|seven) (day|days|week|weeks|month|months)\b", t)
    if m:
        words = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
        n = words.get(m.group(1)) or int(m.group(1))
        unit = {"day": 1, "week": 7, "month": 30}[m.group(2).rstrip("s")]
        return span(today - datetime.timedelta(days=n * unit - 1), today + one, m.group(0))
    for phrase, (a, b) in (
        ("yesterday", (today - one, today)),
        ("today", (today, today + one)),
        ("this morning", (today, today + one)),
        ("last night", (today - one, today + one)),
        ("this week", (monday, today + one)),
        ("last week", (monday - 7 * one, monday)),
        ("this month", (today.replace(day=1), today + one)),
        ("last month", ((today.replace(day=1) - one).replace(day=1), today.replace(day=1))),
        ("recently", (today - 14 * one, today + one)),
        ("recent", (today - 14 * one, today + one)),
    ):
        if f" {phrase} " in t:
            return span(a, b, f" {phrase} ")
    return None, None, text


def parse_request(text: str, now: datetime.datetime | None = None) -> dict:
    """{keywords, types, start, end}: what to look for, from words like "the doc I edited yesterday about the budget"."""
    now = now or datetime.datetime.now()
    start, end, rest = parse_when(text, now)
    types, keywords = [], []
    for word in re.findall(r"[a-z0-9']+", rest.lower()):
        word = word.strip("'")
        if word in TYPE_WORDS:
            kind = TYPE_WORDS[word]
            if kind not in types:
                types.append(kind)
        elif word not in STOP and len(word) > 1:
            keywords.append(word)
    return {"keywords": keywords[:8], "types": types, "start": start, "end": end}


def _variants(word: str) -> list[str]:
    out = [word]
    if word.endswith("ies") and len(word) > 4:
        out.append(word[:-3] + "y")
    elif word.endswith("s") and len(word) > 3:
        out.append(word[:-1])
    return out


def _content(path: str, ext: str) -> str:
    """The words inside a small text, Word, Excel or PowerPoint file (lowercase), or ''."""
    try:
        if ext in TEXT_EXT:
            with open(path, "rb") as f:
                return f.read(CONTENT_BYTES).decode("utf-8", "ignore").lower()
        if ext in ZIP_TEXT:
            with zipfile.ZipFile(path) as z:
                chunks = []
                for name in z.namelist():
                    if any(name == w or (w.endswith("/") and name.startswith(w) and name.endswith(".xml")) for w in ZIP_TEXT[ext]):
                        info = z.getinfo(name)
                        if info.file_size <= 4_000_000:
                            chunks.append(re.sub(r"<[^>]+>", " ", z.read(name).decode("utf-8", "ignore")))
                        if sum(len(c) for c in chunks) > CONTENT_BYTES:
                            break
                return " ".join(chunks).lower()[:CONTENT_BYTES]
    except (OSError, zipfile.BadZipFile, KeyError, RuntimeError, ValueError):
        return ""
    return ""


def search(query: str, limit: int = 8, folder_list: list[str] | None = None, now: datetime.datetime | None = None, time_budget: float = TIME_BUDGET_S) -> dict:
    """{items, searched, complete, request}: the best matches, newest and best-named first."""
    chosen = folders() if folder_list is None else folder_list
    if not chosen:
        raise FinderError("no folders are chosen yet. In the status menu, under \"Files JARVIS may search\", add the folders it may look in.")
    req = parse_request(query, now)
    if not (req["keywords"] or req["types"] or req["start"]):
        raise FinderError("say what to look for, for example: the budget spreadsheet from last week.")
    exts = set().union(*(TYPES[t] for t in req["types"])) if req["types"] else None
    deadline = time.monotonic() + time_budget
    candidates, scanned = [], 0
    for root in chosen:
        for path, name, mtime, size in listing(root, deadline):
            scanned += 1
            ext = os.path.splitext(name)[1].lower()
            if exts is not None and ext not in exts:
                continue
            if req["start"] is not None and not (req["start"] <= mtime < req["end"]):
                continue
            candidates.append((path, name, ext, mtime, size, root))
    keywords = req["keywords"]
    scored, read = [], 0
    for path, name, ext, mtime, size, root in candidates:
        if not keywords:
            scored.append((1.0, "date", path, name, ext, mtime, size, root))
            continue
        lowered = name.lower()
        parent = os.path.dirname(path).lower()
        body, score, matched, how = None, 0.0, 0, "name"
        for word in keywords:
            forms = _variants(word)
            if any(f in lowered for f in forms):
                score += 3
                matched += 1
            elif any(f in parent for f in forms):
                score += 1.5
                matched += 1
            else:                                                       # the words inside the file, if it is a small text, Word, Excel or PowerPoint file
                if body is None:
                    body = ""
                    if (ext in TEXT_EXT or ext in ZIP_TEXT) and read < CONTENT_FILES and time.monotonic() < deadline:
                        read += 1
                        body = _content(path, ext)
                if body and any(f in body for f in forms):
                    score += 2
                    matched += 1
                    how = "inside"
        if matched >= max(1, (len(keywords) + 1) // 2):                 # all the words, or at least half of them (ranked lower)
            scored.append((score - 2.0 * (len(keywords) - matched), how, path, name, ext, mtime, size, root))
    scored.sort(key=lambda r: (-r[0], -r[5]))
    items = []
    for score, how, path, name, ext, mtime, size, root in scored[:limit]:
        items.append({"path": path, "name": name, "folder": os.path.dirname(path), "modified": int(mtime), "size": size, "kind": _kind(ext), "found": how,
                      "openable": ext not in NEVER_OPEN, "image": ext in TYPES["image"] and size <= 12_000_000 and ext in {".jpg", ".jpeg", ".png", ".gif", ".webp"}})
    return {"items": items, "searched": scanned, "complete": time.monotonic() < deadline, "request": req}


def _kind(ext: str) -> str:
    for kind, exts in TYPES.items():
        if ext in exts:
            return kind
    return "file"


# ---- opening what was found ------------------------------------------------------------------------------------------------
def _allowed_file(raw: str, folder_list: list[str] | None = None) -> Path:
    path = Path(str(raw or ""))
    try:
        path = path.resolve()
    except OSError:
        raise FinderError("that file could not be found.") from None
    if not path.is_file() or _secret(path.name):
        raise FinderError("that file could not be found.")
    for folder in (folders() if folder_list is None else folder_list):
        try:
            if _inside(path, Path(folder).resolve()):
                return path
        except OSError:
            continue
    raise FinderError("that file is not in a folder JARVIS may search.")


def open_file(raw: str, folder_list: list[str] | None = None, starter=None) -> str:
    """Opens a found document, picture, song or video with its normal program. Programs and scripts are refused."""
    path = _allowed_file(raw, folder_list)
    if path.suffix.lower() in NEVER_OPEN or not path.suffix:
        raise FinderError(f"JARVIS opens only {OPENABLE_NOTE}; use \"show in folder\" for this one.")
    (starter or os.startfile)(str(path))                               # type: ignore[attr-defined]
    return f"Opened {path.name}."


def reveal(raw: str, folder_list: list[str] | None = None, run=None) -> str:
    """Shows the file selected in its folder (nothing is run)."""
    path = _allowed_file(raw, folder_list)
    if sys.platform != "win32" and run is None:
        raise FinderError("showing a file in its folder only works on Windows.")
    (run or subprocess.Popen)(["explorer", f"/select,{path}"])
    return f"Showing {path.name} in its folder."


def image_bytes(raw: str, folder_list: list[str] | None = None) -> bytes:
    """A found picture's bytes, for putting it on the wall (the picture module checks it is really a picture)."""
    path = _allowed_file(raw, folder_list)
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".gif", ".webp"}:
        raise FinderError("only JPEG, PNG, GIF and WebP pictures can go on the wall.")
    if path.stat().st_size > 12_000_000:
        raise FinderError("that picture is too big for the wall.")
    return path.read_bytes()


# ---- saying it -------------------------------------------------------------------------------------------------------------
def when_text(ts: float, now: datetime.datetime | None = None) -> str:
    now = now or datetime.datetime.now()
    d = datetime.datetime.fromtimestamp(ts)
    days = (now.date() - d.date()).days
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    if 1 < days < 7:
        return d.strftime("%A")
    return d.strftime("%d %b %Y").lstrip("0")


def size_text(n: int) -> str:
    for unit, scale in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= scale:
            return f"{n / scale:.1f} {unit}"
    return f"{n} B"


def summary(found: dict, now: datetime.datetime | None = None) -> str:
    items = found["items"]
    if not items:
        return "I didn't find a matching file in the folders you chose." + ("" if found["complete"] else " The search ran out of time, so some were not checked.")
    top = items[0]
    more = f" and {len(items) - 1} more" if len(items) > 1 else ""
    return f"The best match is {top['name']}, in {os.path.basename(top['folder']) or top['folder']}, changed {when_text(top['modified'], now)}{more}."


def event(query: str, found: dict, now: datetime.datetime | None = None) -> dict:
    """What the wall is told: show these results."""
    return {"type": "files", "title": re.sub(r"\s+", " ", query).strip()[:80] or "Files", "searched": found["searched"], "complete": found["complete"],
            "items": [{**i, "when": when_text(i["modified"], now), "size_text": size_text(i["size"])} for i in found["items"]]}


# ---- spoken requests -------------------------------------------------------------------------------------------------------
_ASK = re.compile(r"^(?:please |hey )?(?:jarvis )?(?:can you |could you |would you )?(?:(?:find|search for|search my files for|look for|locate|dig up|get me|where(?:'s| is| are| did i put| did i save)) )(.+)$")
_FILEISH = re.compile(r"\b(files?|documents?|docs?|pdfs?|spreadsheets?|sheets?|excel|presentations?|slides|powerpoint|screenshots?|photos?|pictures?|images?|videos?|recordings?|downloads?|"
                      r"report|essay|invoice|receipt|notes?|folder|csv|word|deck)\b")


def from_words(text: str) -> str | None:
    """The description in "find the doc I edited yesterday about the budget", else None. A picture of something (a web photo) is left to the picture finder."""
    t = " ".join(re.sub(r"[^a-z0-9' \-]", " ", str(text).lower()).split())
    m = _ASK.match(t)
    if not m:
        return None
    rest = m.group(1)
    if not _FILEISH.search(rest):
        return None
    if re.match(r"^(?:a |an |some |the )?(?:picture|photo|image|pic)s? (?:of|for|showing) ", rest):
        return None
    return rest[:160]


def handle_voice(text: str, tell_page=None) -> dict:
    """{handled, ok, text, event}: a spoken file request, answered here with no AI request. Nothing about the files leaves the PC."""
    what = from_words(text)
    if not what:
        return {"handled": False, "text": ""}
    try:
        found = search(what)
    except FinderError as e:
        return {"handled": True, "ok": False, "text": f"Sorry, {e}"}
    ev = event(what, found)
    if tell_page is not None:
        tell_page({"type": "phone_event", "event": ev})
    return {"handled": True, "ok": True, "text": summary(found), "event": ev}


def tool(args: dict) -> str:
    """The AI's `find_files` tool (a private tool: what it returns is file names from the chosen folders). Errors start with 'Error'."""
    try:
        found = search(str(args.get("query") or ""), limit=10)
    except FinderError as e:
        return f"Error: {e}"
    if not found["items"]:
        return "No matching file in the folders the user chose." + ("" if found["complete"] else " (The search ran out of time.)")
    lines = [f"{i['name']} | {i['folder']} | changed {when_text(i['modified'])} | {size_text(i['size'])}" for i in found["items"]]
    return "Files found:\n" + "\n".join(lines)
