"""Opening and closing apps on this PC, with limits.

What it can do: open an app by its name, list the apps it is allowed to open, list what is running, and (only after you press Allow
on a card) close one running program. What it cannot do:

- run commands, scripts or files. An app is opened only by its entry in the Windows Start Menu, found by name from the PC's own
  list; there is no way to pass it a path, an argument or a command.
- open shells, scripting tools, admin consoles, installers or uninstallers (Command Prompt, PowerShell, Terminal, Python, WSL,
  Registry Editor, Task Scheduler, Services, Run, "Uninstall ...", and so on), or anything that is a web link or a document.
- close Windows, security software, JARVIS itself, or anything outside your own session (see fixes.py).

You can tighten it further in %LOCALAPPDATA%\\jarvis\\apps.json:
  {"blocked": ["Fortnite"], "only": []}      blocked = names JARVIS must never open; only = if not empty, the ONLY apps it may open.
JARVIS_APPS=0 in .env turns the whole thing off.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

from . import diagnostics, fixes, store

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
FRAME_HOST = "applicationframehost"        # Windows hosts the windows of modern (Store) apps in this one shared process
CONFIG = store.STATE / "apps.json"
CATALOGUE_TTL = 600.0
OPEN_LIMIT = (6, 60.0)            # at most 6 openings a minute: a confused AI must not be able to flood the screen

# Names that are never opened, whatever the user or the AI asks (matched against the display name).
DENY_NAMES = re.compile(
    r"command prompt|\bcmd\b|powershell|windows terminal|^terminal$|\bpython\b|\bidle\b|pydoc|\bwsl\b|ubuntu|\bbash\b|git cmd|git bash|"
    r"node\.js command|registry|regedit|^services$|^run$|task scheduler|computer management|component services|event viewer|"
    r"group policy|system configuration|msconfig|device manager|disk management|local security|odbc|iscsi|resource monitor|"
    r"uninstall|\bsetup\b|installer|install additional|install manager|update assistant|^command palette$|windows sandbox|hyper-v|"
    r"remote desktop|remote assistance|quick assist|\bssh\b|openssh|netsh|sysinternals|^node\.js$|^windows tools$|^settings$|^windows settings$|system settings|^control panel$",
    re.I,
)
# Entries whose Start Menu target is not an ordinary app: links, documents, scripts, consoles, shells.
DENY_TARGETS = re.compile(
    r"^(https?:|ftp:|file:)|\.(html?|url|txt|pdf|chm|lnk|msc|bat|cmd|ps1|vbs|vbe|js|jse|wsf|jar|reg|msi|msix|appx)\b|"
    r"(^|\\)(cmd|powershell|pwsh|wt|wsl|bash|wscript|cscript|mshta|regedit|mmc|msconfig|rundll32|python\w*|pythonw\w*|ssh|sc|net|reg)\.exe$|"
    r"^Chrome\._crx_|immersivecontrolpanel|ms-settings|windows\.controlpanel|control\.exe",                     # the "web apps" Chrome creates for every site shortcut
    re.I,
)
JUNK_NAMES = re.compile(r"^https?\b|manual|documentation|release notes|\bfaq\b|online|readme|license|help$", re.I)
UNSAFE_ID = re.compile(r'[\x00-\x1f"&|<>^%]')
QUESTION = re.compile(r"^(what|which|how|why|who|when|where|is|are|do|does|did|can|could|should|will)\b", re.I)
WIDGET_WORDS = {"weather", "timer", "timers", "music", "lights", "light", "news", "system", "usage", "hologram", "chat", "memory", "widgets",
                "widget", "settings", "calendar", "email", "mail", "board", "notes", "note", "keyboard", "ticker", "alerts", "privacy"}


class AppError(Exception):
    """Something the user can act on; the message says what."""


@dataclass(frozen=True)
class App:
    name: str
    id: str


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(text).lower())).strip()


def safe_entry(name: str, app_id: str) -> bool:
    """Is this Start Menu entry an ordinary app that may be opened?"""
    if not name or not app_id or UNSAFE_ID.search(app_id) or UNSAFE_ID.search(name):
        return False
    if DENY_NAMES.search(name) or JUNK_NAMES.search(name) or DENY_TARGETS.search(app_id):
        return False
    return True


_CATALOGUE_SCRIPT = ("Get-StartApps | ForEach-Object { @{ name = [string]$_.Name; id = [string]$_.AppID } } | ConvertTo-Json -Compress")
_RUNNING_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$cmd = @{}
Get-CimInstance Win32_Process | ForEach-Object { $cmd[[int]$_.ProcessId] = [string]$_.CommandLine }
@(Get-Process | Where-Object { $_.MainWindowTitle } | ForEach-Object {
  @{ name = [string]$_.ProcessName; id = $_.Id; title = [string]$_.MainWindowTitle; session = $_.SessionId; cmd = [string]$cmd[[int]$_.Id] } }) | ConvertTo-Json -Compress
"""


def _as_list(data):
    return data if isinstance(data, list) else [data] if isinstance(data, dict) else []


class Apps:
    def __init__(self, catalogue_fn=None, running_fn=None, launch_fn=None, config_path=CONFIG, now=time.time, close_window_fn=None) -> None:
        self._catalogue_fn = catalogue_fn or (lambda: _as_list(diagnostics.powershell_json(_CATALOGUE_SCRIPT, timeout=30)))
        self._running_fn = running_fn or (lambda: _as_list(diagnostics.powershell_json(_RUNNING_SCRIPT, timeout=30)))
        self._launch_fn = launch_fn or self._launch
        self._close_window_fn = close_window_fn or self._close_window
        self.config_path = config_path
        self.now = now
        self.lock = threading.Lock()
        self._entries: list[App] = []
        self._loaded = 0.0
        self._opened: deque = deque()

    @staticmethod
    def _launch(app_id: str) -> None:
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{app_id}"], creationflags=NO_WINDOW, close_fds=True)

    # -- the list of apps JARVIS may open --
    def config(self) -> dict:
        raw = store._read(self.config_path, {})
        raw = raw if isinstance(raw, dict) else {}
        return {"blocked": [norm(x) for x in raw.get("blocked", []) if isinstance(x, str)], "only": [norm(x) for x in raw.get("only", []) if isinstance(x, str)]}

    def entries(self, force: bool = False) -> list[App]:
        with self.lock:
            if force or not self._entries or self.now() - self._loaded > CATALOGUE_TTL:
                rows = [App(str(r.get("name", "")).strip(), str(r.get("id", "")).strip()) for r in self._catalogue_fn() if isinstance(r, dict)]
                seen, found = set(), []
                for app in rows:
                    key = norm(app.name)
                    if key and key not in seen and safe_entry(app.name, app.id):
                        seen.add(key)
                        found.append(app)
                self._entries, self._loaded = sorted(found, key=lambda a: a.name.lower()), self.now()
            cfg = self.config()
            out = [a for a in self._entries if norm(a.name) not in cfg["blocked"]]
            return [a for a in out if norm(a.name) in cfg["only"]] if cfg["only"] else out

    def names(self) -> list[str]:
        return [a.name for a in self.entries()]

    def find(self, query: str) -> App:
        """The one app a spoken or typed name means. Raises AppError (with the candidates) if it is none or more than one."""
        q = norm(re.sub(r"^(the|my|a)\s+", "", str(query).strip(), flags=re.I))
        if len(q) < 2:
            raise AppError("which app?")
        entries = self.entries()
        exact = [a for a in entries if norm(a.name) == q]
        if len(exact) == 1:
            return exact[0]
        starts = [a for a in entries if norm(a.name).startswith(q + " ") or norm(a.name).startswith(q)] if len(q) >= 3 else []
        words = q.split()
        contains = [a for a in entries if all(w in norm(a.name).split() for w in words)]
        for group in (starts, contains):
            if len(group) == 1:
                return group[0]
            if 1 < len(group) <= 5:
                raise AppError(f"“{query}” could be {', '.join(a.name for a in group)}. Which one?")
            if len(group) > 5:
                raise AppError(f"“{query}” matches too many apps. Be more specific.")
        raise AppError(f"I don't know an app called “{query}” that I'm allowed to open.")

    @staticmethod
    def _close_window(pid: int) -> None:
        """Asks that process's main window to close, like pressing its X. The id is a number we checked, never text."""
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", f"(Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue).CloseMainWindow() | Out-Null"],
                       capture_output=True, timeout=15, creationflags=NO_WINDOW)

    # -- opening --
    def open(self, query: str) -> str:
        app = self.find(query)
        recent = [t for t in self._opened if self.now() - t < OPEN_LIMIT[1]]
        if len(recent) >= OPEN_LIMIT[0]:
            raise AppError("that's a lot of apps in a minute, so I'll stop here. Ask again shortly.")
        try:
            self._launch_fn(app.id)
        except OSError as e:
            raise AppError(f"{app.name} wouldn't start ({e.__class__.__name__}).") from None
        self._opened = deque(recent + [self.now()])
        return app.name

    # -- what is running --
    def running(self) -> list[dict]:
        """Programs with a window: [{name, id, title}], without JARVIS's own window, other sessions, or the system's."""
        out = []
        for r in self._running_fn():
            if not isinstance(r, dict) or not r.get("id"):
                continue
            cmd, title = str(r.get("cmd") or ""), str(r.get("title") or "")
            hosted = str(r.get("name", "")).lower() == FRAME_HOST          # a Store app's window: listed (closed as a window), unlike the host itself
            if "jarvis" in cmd.lower() or title.strip().lower() == "jarvis" or (not hosted and str(r.get("name", "")).lower() in fixes.PROTECTED):
                continue
            out.append({"name": title[:60] if hosted else str(r.get("name", "")), "id": int(r["id"]), "title": title[:80], "hosted": hosted})
        return sorted(out, key=lambda x: x["name"].lower())

    def prepare_close(self, query: str = "", pid=None) -> fixes.Prepared:
        """The Allow card for closing one running program. Never closes anything by itself."""
        running = self.running()
        if pid not in (None, ""):
            try:
                chosen = [r for r in running if r["id"] == int(pid)]
            except (TypeError, ValueError):
                raise AppError("the process id must be a number from the list of running programs.") from None
            if not chosen:
                raise AppError(f"no program with id {pid} is one I can close.")
        else:
            q = norm(query)
            if len(q) < 2:
                raise AppError("which program should I close?")
            chosen = [r for r in running if q in norm(r["name"]) or q in norm(r["title"]) or norm(r["name"]) in q.split()]
            if not chosen:
                raise AppError(f"I can't see a running program called “{query}” that I'm allowed to close.")
            if len({r["id"] for r in chosen}) > 1:
                names = "; ".join(f"{r['name']} (id {r['id']}, “{r['title'][:30]}”)" for r in chosen[:6])
                raise AppError(f"“{query}” matches several programs: {names}. Say which one (by id).")
        target = chosen[0]
        if target["hosted"]:
            return self._prepare_close_window(target)
        try:
            return fixes.prepare_end_program(str(target["id"]))
        except fixes.FixError as e:
            raise AppError(str(e)) from None

    def _prepare_close_window(self, target: dict) -> fixes.Prepared:
        """A Windows (Store) app: close just its window. The shared host process is never ended (it would take other apps' windows too)."""
        pid, title = target["id"], target["title"] or target["name"]

        def run() -> str:
            self._close_window_fn(pid)
            for _ in range(8):
                time.sleep(0.5)
                if not any(r["id"] == pid and r["title"] == target["title"] for r in self.running()):
                    return f"Closed {title}."
            return f"Error: {title} is still open (it may be asking whether to save). I won't force it."
        return fixes.Prepared(f"JARVIS wants to close {title}", f"Asks the “{title}” window to close, as if you pressed its X. It is never forced. Anything unsaved in it may be lost, "
                              "or it may ask you to save first.", run)


apps = Apps()


def available() -> bool:
    return os.getenv("JARVIS_APPS", "1") != "0"


def tool(args: dict, registry: Apps | None = None) -> str:
    """The AI's `apps` tool. Lists are outside content (titles can come from web pages), so they are marked as such."""
    from . import agent_tools
    reg = registry or apps
    action = str(args.get("action") or "list")
    try:
        if action == "open":
            return f"Opening {reg.open(str(args.get('name') or ''))}."
        if action == "running":
            rows = reg.running()
            return agent_tools.wrap("\n".join(f"- {r['name']} (id {r['id']}): {r['title']}" for r in rows) or "No programs with windows are open.")
        names = reg.names()
        return agent_tools.wrap(", ".join(names) if names else "No apps found.")
    except AppError as e:
        return f"Error: {e}"


# ---- spoken commands ----------------------------------------------------------------------------------

_OPEN = re.compile(r"^(?:please |can you |could you )?(?:open|launch|start)(?: up)?\s+(?:the |my |a )?(.+?)(?: app| application| program)?(?: please)?$")


def parse_command(text: str) -> str | None:
    """"Open Discord" -> "discord"; None for anything else (including "open the weather", which is a widget)."""
    t = re.sub(r"[^a-z0-9' ]", " ", str(text).lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:hey )?jarvis ", "", t)
    if QUESTION.match(t):
        return None
    m = _OPEN.match(t)
    if not m:
        return None
    target = m.group(1).strip()
    if not target or set(target.split()) <= WIDGET_WORDS or target in WIDGET_WORDS:
        return None
    return target


def handle_voice(text: str, registry: Apps | None = None) -> dict:
    """"Open Discord": {handled, ok, text}. handled is False when it isn't an app command, or no app by that name exists (the AI can then take it)."""
    from . import persona
    target = parse_command(text)
    if target is None:
        return {"handled": False, "text": ""}
    reg = registry or apps
    try:
        name = reg.open(target)
        return {"handled": True, "ok": True, "text": persona.line("app_open", app=name)}
    except AppError as e:
        if str(e).startswith("I don't know an app"):
            return {"handled": False, "text": ""}
        return {"handled": True, "ok": False, "text": persona.failure(str(e))}
