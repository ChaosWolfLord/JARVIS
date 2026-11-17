"""JARVIS can read your code folder, and only read it.

You choose one folder (status menu, "Code folder") and switch this on; until then JARVIS cannot see any of it. Then the AI can list the folders and text
files in it, read a file and search the text of your code ("what does music.py do?", "where do I handle the privacy screen?", "which project uses Roblox?").

This is read-only by construction: nothing in this file can write, rename, delete or run anything (a test checks that the file contains no such call).
The other guard rails:

  * One folder only. A path is checked piece by piece against that folder: no "..", no drive letters, no streams, no device names, and a link or junction
    anywhere on the way is refused, so nothing inside the folder can lead somewhere you did not choose.
  * Never shown, never listed: .git, .claude and other tool folders, dependencies and build output (node_modules, venv, build...), signing and keystore
    folders and files, JARVIS's own private data (its
    data folder with your memory and boards, and %LOCALAPPDATA%\\jarvis with the keys), and any file that looks like a secret (.env files, keys,
    certificates, keystores, local.properties, anything called password, secret, token or credential).
  * Only text files of a known kind, up to 1 MB. Binary files are not read.
  * What is read is cleaned first: anything shaped like an API key, token or private key, and the value in lines like api_key = "...", is replaced by
    [hidden] before the AI sees it, in case a secret is written inside a normal file.
  * Online-only OneDrive files are never downloaded by a search (a single file you ask for is read normally).
  * All of it is private data: after the AI reads your code in a conversation, JARVIS asks before it opens a web page or an app. Everything the AI
    reads is labelled as outside data that must not be obeyed. Every read is in the activity log.

What is read is sent to the AI service that answers you (Gemini, Groq, OpenRouter...), like anything you ask about. That is the one real cost, and why this
is off until you turn it on.
"""
from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path

from . import agent_tools, filefinder, store

CONFIG = store.STATE / "codefolder.json"
MAX_READ_BYTES = 1_000_000
MAX_CHARS = 12_000
MAX_LINES = 400
MAX_LIST = 200
MAX_PATH = 400
MAX_DEPTH = 14
SEARCH_SECONDS = 6.0
SEARCH_FILES = 4000
SEARCH_MATCHES = 40
SEARCH_FILE_BYTES = 400_000
MAX_LINE_CHARS = 220

# Never entered, listed or searched, wherever they are in the folder.
SKIP_DIRS = frozenset(filefinder.SKIP_DIRS) | {".idea", ".vs", ".vscode", ".claude", ".gradle", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".tox", ".next", ".nuxt", "dist", "build", "out", "target", "obj", "bin",
                                                "coverage", "htmlcache", "__MACOSX".lower(), "$recycle.bin", ".svn", ".hg"}
# Text files of a known kind, by extension, and a few well-known names without one.
TEXT_EXTENSIONS = frozenset({".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".json", ".jsonc", ".md", ".markdown", ".txt", ".rst", ".html", ".htm", ".css", ".scss", ".less",
                             ".java", ".kt", ".kts", ".xml", ".gradle", ".properties", ".bat", ".cmd", ".ps1", ".sh", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".go", ".rs", ".lua", ".luau",
                             ".yml", ".yaml", ".toml", ".ini", ".cfg", ".csv", ".tsv", ".sql", ".svg", ".gitignore", ".gitattributes", ".editorconfig", ".rb", ".php", ".swift", ".dart",
                             ".vue", ".svelte", ".r", ".m", ".pl", ".ino", ".csproj", ".sln", ".manifest", ".pro", ".cmake", ".mk", ".lock"})
TEXT_NAMES = frozenset({"readme", "license", "licence", "notice", "makefile", "dockerfile", "procfile", "gemfile", "requirements", "changelog", "authors", "todo", "plan", "copying"})
# Names that are secrets whatever they hold (on top of filefinder.SECRET_NAME): signing and sign-in files and tool credentials.
SECRET_EXTRA = re.compile(r"(signing|keystore|^local\.properties$|^google_client|client_secret|\.keystore$|\.jks$|\.p8$|\.ppk$|^\.npmrc$|^\.pypirc$|^\.netrc$|\.git-credentials|known_hosts|^auth\.json$|\.tfstate|\.pgpass)", re.I)
WINDOWS_DEVICES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))})
SYMLINK_TAGS = {0xA000000C, 0xA0000003}                   # a symbolic link and a junction (not OneDrive's online-only placeholders)
ONLINE_ONLY = 0x400000 | 0x40000 | 0x1000                 # recall on data access / recall on open / offline


class CodeError(Exception):
    """Something the person can act on; the message says what."""


# ---- cleaning what is read ----------------------------------------------------------------------------------------------------
_SHAPES = [re.compile(p) for p in (
    r"AIza[0-9A-Za-z_\-]{30,}", r"sk-[A-Za-z0-9_\-]{20,}", r"gsk_[A-Za-z0-9]{20,}", r"gh[pousr]_[A-Za-z0-9]{30,}", r"github_pat_[A-Za-z0-9_]{30,}",
    r"xox[baprs]-[A-Za-z0-9\-]{10,}", r"AKIA[0-9A-Z]{16}", r"ya29\.[A-Za-z0-9_\-]{20,}", r"1//[A-Za-z0-9_\-]{30,}",
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", r"[MNO][A-Za-z0-9_\-]{23,25}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}",
)]
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(?:-----END [A-Z ]*PRIVATE KEY-----|\Z)", re.S)
_NAME = r"(?:api[_\-]?key|secret|token|passw(?:or)?d|passwd|client[_\-]?secret|private[_\-]?key|auth[_\-]?key|access[_\-]?key|bearer|credential)"
_QUOTED = re.compile(r"(?i)(\b[A-Za-z0-9_\-.]*" + _NAME + r"[A-Za-z0-9_\-]*[\"']?\s*[:=]\s*)([\"'])[^\"'\n]{8,}\2")
_BARE = re.compile(r"(?i)(\b[A-Za-z0-9_\-.]*" + _NAME + r"[A-Za-z0-9_\-]*\s*[:=]\s*)([A-Za-z0-9+/=_\-.]{16,})(?=\s|$|[,;)])")


def redact(text: str) -> str:
    """The text with anything that looks like a secret replaced by [hidden]."""
    text = _PRIVATE_KEY.sub("[private key hidden]", text)
    for shape in _SHAPES:
        text = shape.sub("[hidden]", text)
    text = _QUOTED.sub(lambda m: f"{m.group(1)}{m.group(2)}[hidden]{m.group(2)}", text)
    return _BARE.sub(lambda m: f"{m.group(1)}[hidden]" if re.search(r"\d", m.group(2)) and "(" not in m.group(2) else m.group(0), text)


# ---- settings -----------------------------------------------------------------------------------------------------------------
def _settings() -> dict:
    data = store._read(CONFIG, {})
    return data if isinstance(data, dict) else {}


def _excluded_roots() -> list[Path]:
    """JARVIS's own private folders, kept out of reach wherever the code folder is."""
    out = []
    for p in (store.DATA, store.STATE):
        try:
            out.append(p.resolve())
        except OSError:
            pass
    return out


def _under(path: Path, parent: Path) -> bool:
    return path == parent or parent in path.parents


def check_root(raw: str) -> Path:
    """The folder as a resolved path if it is a sensible code folder, else a CodeError saying why not."""
    text = str(raw or "").strip().strip('"')
    if not text:
        raise CodeError("Type the folder first, for example C:\\Users\\you\\Code.")
    if "\x00" in text or len(text) > 300:
        raise CodeError("That doesn't look like a folder.")
    try:
        path = Path(os.path.expandvars(text)).expanduser().resolve()
    except (OSError, ValueError, RuntimeError):
        raise CodeError("That doesn't look like a folder.") from None
    if not path.is_dir():
        raise CodeError("That folder doesn't exist.")
    if len(path.parts) < 3 or path == Path(path.anchor):
        raise CodeError("That is too broad. Choose the folder that holds your projects, not a whole drive or user folder.")
    home = Path(os.path.expanduser("~")).resolve()
    if path == home or _under(home, path):
        raise CodeError("That is too broad: it holds your whole user folder. Choose the folder that holds your projects.")
    for risky in (os.getenv("SystemRoot"), os.getenv("ProgramFiles"), os.getenv("ProgramFiles(x86)"), os.getenv("ProgramData")):
        if risky and _under(path, Path(risky).resolve()):
            raise CodeError("That is a system folder. Choose the folder that holds your projects.")
    if _under(store.STATE.resolve(), path):                    # the folder is, or holds, the one with JARVIS's keys and settings
        raise CodeError("That folder holds JARVIS's private settings and keys. Choose the folder that holds your projects.")
    for private in _excluded_roots():
        if _under(path, private):
            raise CodeError("That is inside JARVIS's private data. Choose the folder that holds your projects.")
    return path


def status() -> dict:
    s = _settings()
    root = str(s.get("root") or "")
    ok, note = False, ""
    if root:
        try:
            check_root(root)
            ok = True
        except CodeError as e:
            note = str(e)
    suggestion = ""
    try:
        suggestion = str(check_root(str(store.ROOT.parent)))
    except CodeError:
        pass
    return {"enabled": bool(s.get("enabled")), "root": root, "valid": ok, "note": note, "suggestion": suggestion, "on": enabled()}


def configure(enabled_: bool | None = None, root: str | None = None) -> dict:
    """Changes the settings. A folder is only stored once it passes check_root. Switching on needs a folder."""
    s = _settings()
    if root is not None:
        s["root"] = str(check_root(root)) if str(root).strip() else ""
    if enabled_ is not None:
        if enabled_ and not s.get("root"):
            raise CodeError("Choose the folder first.")
        s["enabled"] = bool(enabled_)
    store._write(CONFIG, s)
    return status()


def root_path() -> Path | None:
    s = _settings()
    if not s.get("enabled") or not s.get("root"):
        return None
    try:
        return check_root(s["root"])
    except CodeError:
        return None


def enabled() -> bool:
    """Is JARVIS allowed to read the code folder right now? (Off unless you switched it on and the folder is still a good one.)"""
    return root_path() is not None


# ---- looking at paths -----------------------------------------------------------------------------------------------------------
def _hidden_name(name: str, is_dir: bool) -> bool:
    if is_dir and name.lower() in SKIP_DIRS:
        return True
    return bool(filefinder.SECRET_NAME.search(name) or SECRET_EXTRA.search(name))


def _link(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or getattr(st, "st_reparse_tag", 0) in SYMLINK_TAGS


def _readable_kind(name: str) -> bool:
    low = name.lower()
    ext = os.path.splitext(low)[1]
    return ext in TEXT_EXTENSIONS or (not ext and (low in TEXT_NAMES or low.startswith(".") and low[1:] in {"gitignore", "gitattributes", "editorconfig"}))


def resolve(rel: str, root: Path) -> Path:
    """A path inside the code folder, checked one piece at a time. CodeError for anything that is not allowed (the message never says what exists)."""
    text = str(rel or "").strip().replace("\\", "/")
    if len(text) > MAX_PATH or "\x00" in text:
        raise CodeError("that path isn't allowed.")
    if text.startswith("/") or ":" in text or text.startswith("~"):
        raise CodeError("give a path inside the code folder, like JARVIS/server/music.py.")
    cur = root
    for part in [p for p in text.split("/") if p not in ("", ".")]:
        if part == ".." or part.rstrip(". ").lower().split(".")[0] in WINDOWS_DEVICES or part != part.strip() or part.endswith("."):
            raise CodeError("that path isn't allowed.")
        cur = cur / part
        try:
            st = os.lstat(cur)
        except OSError:
            raise CodeError("no such file or folder. Use code_list to see what is there.") from None
        if _link(st) or _hidden_name(part, stat.S_ISDIR(st.st_mode)):
            raise CodeError("that isn't available.")
    try:
        real = cur.resolve()
    except OSError:
        raise CodeError("no such file or folder.") from None
    if not _under(real, root):
        raise CodeError("that isn't available.")
    if any(_under(real, private) for private in _excluded_roots()):
        raise CodeError("that isn't available.")
    return cur


def _private_dir(path: Path) -> bool:
    try:
        real = path.resolve()
    except OSError:
        return True
    return any(_under(real, p) for p in _excluded_roots())


def _need_root() -> Path:
    root = root_path()
    if root is None:
        raise CodeError("JARVIS isn't allowed to read your code folder. Turn it on in the status menu, under Code folder.")
    return root


# ---- the three things the AI can do ---------------------------------------------------------------------------------------------
def list_dir(path: str = "") -> str:
    root = _need_root()
    target = resolve(path, root)
    if not target.is_dir():
        raise CodeError("that is a file. Use code_read to read it.")
    dirs, files = [], []
    try:
        with os.scandir(target) as it:
            for entry in it:
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                is_dir = stat.S_ISDIR(st.st_mode)
                if _link(st) or _hidden_name(entry.name, is_dir) or (is_dir and _private_dir(Path(entry.path))):
                    continue
                if is_dir:
                    dirs.append(entry.name)
                elif _readable_kind(entry.name):
                    files.append((entry.name, st.st_size))
    except OSError:
        raise CodeError("that folder can't be opened.") from None
    dirs.sort(key=str.lower)
    files.sort(key=lambda f: f[0].lower())
    where = "/".join(p for p in str(path or "").replace("\\", "/").split("/") if p not in ("", ".")) or "(the code folder)"
    lines = [f"{where}:"] + [f"  {d}/" for d in dirs[:MAX_LIST]] + [f"  {n} ({size:,} bytes)" for n, size in files[:max(0, MAX_LIST - len(dirs))]]
    if len(dirs) + len(files) > MAX_LIST:
        lines.append(f"[{len(dirs) + len(files) - MAX_LIST} more not shown]")
    if len(lines) == 1:
        lines.append("  (nothing readable here)")
    return "\n".join(lines)


def read_file(path: str, start: int = 1, count: int = 200) -> str:
    root = _need_root()
    target = resolve(path, root)
    if not target.is_file():
        raise CodeError("that is a folder. Use code_list to see inside it.")
    if not _readable_kind(target.name):
        raise CodeError("that isn't a kind of text file I read.")
    try:
        size = target.stat().st_size
        if size > MAX_READ_BYTES:
            raise CodeError(f"that file is too big to read ({size:,} bytes; the limit is {MAX_READ_BYTES:,}).")
        data = target.read_bytes()
    except OSError:
        raise CodeError("that file can't be opened.") from None
    if b"\x00" in data[:4096]:
        raise CodeError("that isn't a text file.")
    text = redact(data.decode("utf-8", errors="replace"))
    lines = text.splitlines()
    start = max(1, int(start or 1))
    count = max(1, min(int(count or 200), MAX_LINES))
    chunk, used = [], 0
    for number in range(start, min(len(lines), start + count - 1) + 1):
        row = f"{number:>5}  {lines[number - 1][:400]}"
        if used + len(row) > MAX_CHARS:
            break
        chunk.append(row)
        used += len(row) + 1
    if not chunk:
        return f"{path}: the file has {len(lines)} lines, so there is nothing at line {start}."
    last = start + len(chunk) - 1
    more = f"\n[lines {start}-{last} of {len(lines)}; ask for start={last + 1} to continue]" if last < len(lines) else f"\n[end of file: {len(lines)} lines]"
    return f"{path} (lines {start}-{last} of {len(lines)}):\n" + "\n".join(chunk) + more


def search(query: str, path: str = "") -> str:
    root = _need_root()
    needle = " ".join(str(query or "").split()).lower()
    if len(needle) < 2:
        raise CodeError("give at least two characters to search for.")
    base = resolve(path, root)
    if not base.is_dir():
        raise CodeError("search a folder, not a file.")
    deadline = time.monotonic() + SEARCH_SECONDS
    hits, names, looked, skipped_online, stopped = [], [], 0, 0, ""
    stack = [(base, 0)]
    while stack and not stopped:
        folder, depth = stack.pop()
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
        except OSError:
            continue
        for entry in entries:
            if time.monotonic() > deadline:
                stopped = "it ran out of time"
                break
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            is_dir = stat.S_ISDIR(st.st_mode)
            if _link(st) or _hidden_name(entry.name, is_dir):
                continue
            rel = Path(entry.path).relative_to(root).as_posix()
            if is_dir:
                if depth < MAX_DEPTH and not _private_dir(Path(entry.path)):
                    stack.append((Path(entry.path), depth + 1))
                continue
            if not _readable_kind(entry.name):
                continue
            if needle in entry.name.lower() and len(names) < 20:
                names.append(rel)
            if st.st_size > SEARCH_FILE_BYTES:
                continue
            if getattr(st, "st_file_attributes", 0) & ONLINE_ONLY:
                skipped_online += 1
                continue
            looked += 1
            if looked > SEARCH_FILES:
                stopped = "it reached the limit on files"
                break
            try:
                data = Path(entry.path).read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:4096] or needle.encode("utf-8", "ignore") not in data.lower():
                continue
            for number, line in enumerate(data.decode("utf-8", errors="replace").splitlines(), 1):
                if needle in line.lower():
                    hits.append(f"{rel}:{number}: {redact(line.strip())[:MAX_LINE_CHARS]}")
                    if len(hits) >= SEARCH_MATCHES:
                        stopped = f"it stopped at {SEARCH_MATCHES} matches"
                        break
            if stopped:
                break
    out = []
    if names:
        out.append("Files with that in the name:\n" + "\n".join(f"  {n}" for n in names))
    if hits:
        out.append("Matches in the text:\n" + "\n".join(f"  {h}" for h in hits))
    if not out:
        out.append(f"Nothing in the code matches “{query}” ({looked} files looked at).")
    notes = ([f"Stopped early: {stopped}."] if stopped else []) + ([f"{skipped_online} online-only OneDrive files were skipped (not downloaded)."] if skipped_online else [])
    return "\n".join(out + notes)


# ---- the AI's tools ---------------------------------------------------------------------------------------------------------------
def _num(value, low: int, high: int, default: int) -> int:
    try:
        return max(low, min(high, int(value)))
    except (TypeError, ValueError):
        return default


def tool(name: str, args: dict) -> str:
    """code_list, code_read or code_search for the AI. What is read is wrapped as outside data. Errors start with 'Error'."""
    try:
        if name == "code_list":
            return agent_tools.wrap(list_dir(str(args.get("path") or "")))
        if name == "code_read":
            return agent_tools.wrap(read_file(str(args.get("path") or ""), _num(args.get("start"), 1, 10 ** 7, 1), _num(args.get("lines"), 1, MAX_LINES, 200)))
        if name == "code_search":
            return agent_tools.wrap(search(str(args.get("query") or ""), str(args.get("path") or "")))
    except CodeError as e:
        return f"Error: {e}"
    return "Error: not a code tool."
