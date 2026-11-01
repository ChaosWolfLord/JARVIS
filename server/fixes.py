"""Safe fixes for problems the system monitor finds. Each one is prepared first (so the user is shown exactly what will
happen, with real numbers), and only carried out after they press Allow; see agent._run_action.

The list is short on purpose. Nothing here needs administrator rights, installs anything, or touches files outside the
temp folder:

- restart_wake_word   stop and start the offline "Jarvis" listener
- reload_tools        reconnect the MCP tools from data/mcp.json
- flush_dns           clear Windows' name-lookup cache (helps when web addresses stop resolving)
- clean_temp          delete files in your Windows temp folder that haven't changed for 3 days
- end_program         close one program you choose by its process id (never a Windows or security program)
- restart_jarvis      restart the JARVIS server (only when it was started with JARVIS.bat, which brings it back)
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import diagnostics

log = logging.getLogger("jarvis")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ACTIONS = ("restart_wake_word", "reload_tools", "flush_dns", "clean_temp", "end_program", "restart_jarvis")
TEMP_AGE_DAYS = 3
TEMP_SKIP = {"claude", "jarvis"}          # other programs' working folders that may hold files for a long-running session
MAX_TEMP_FILES = 100_000

# Programs that are part of Windows, its security, or JARVIS's own plumbing: never ended from here, whatever is asked.
PROTECTED = {
    "system", "idle", "registry", "memory compression", "smss", "csrss", "wininit", "winlogon", "services", "lsass", "lsm", "svchost",
    "dwm", "fontdrvhost", "sihost", "taskhostw", "ctfmon", "explorer", "audiodg", "spoolsv", "wudfhost", "dllhost", "conhost",
    "runtimebroker", "searchhost", "startmenuexperiencehost", "shellexperiencehost", "textinputhost", "securityhealthservice",
    "securityhealthsystray", "msmpeng", "nissrv", "mssense", "smartscreen", "wmiprvse", "lockapp", "logonui", "userinit",
    # shared hosts: one process carries the windows of many apps, so ending it would close all of them
    "applicationframehost", "backgroundtaskhost", "wwahost", "systemsettingsbroker", "searchapp", "shellhost", "widgets", "phoneexperiencehost",
}

hooks: dict[str, Callable[[], str]] = {}   # set by main.py: "restart_wake_word" and "reload_tools" need the running server's objects


@dataclass
class Prepared:
    title: str                 # the heading of the Allow card
    preview: str               # exactly what will happen
    run: Callable[[], str]     # does it, returns a result line for the AI


class FixError(ValueError):
    """The fix can't be done, and the message says why."""


def prepare(action: str, target: str = "") -> Prepared:
    action = str(action or "").strip()
    target = str(target or "").strip()
    if action == "restart_wake_word":
        return Prepared("JARVIS wants to restart its wake-word listener", "Stops the offline “Jarvis” listener and starts it again. It takes a few seconds; nothing else changes.", _hook("restart_wake_word"))
    if action == "reload_tools":
        return Prepared("JARVIS wants to reconnect your tools", "Re-reads data/mcp.json and reconnects every MCP tool server. Nothing is changed on the PC.", _hook("reload_tools"))
    if action == "flush_dns":
        return Prepared("JARVIS wants to clear the DNS cache", "Runs “ipconfig /flushdns”: Windows forgets the web addresses it remembered and looks them up again. Harmless.", flush_dns)
    if action == "clean_temp":
        return prepare_clean_temp()
    if action == "end_program":
        return prepare_end_program(target)
    if action == "restart_jarvis":
        return prepare_restart_jarvis()
    raise FixError(f"unknown fix. Choose one of: {', '.join(ACTIONS)}.")


def _hook(name: str) -> Callable[[], str]:
    def run() -> str:
        if name not in hooks:
            raise FixError("that isn't available right now.")
        return hooks[name]()
    return run


# ---- individual fixes ---------------------------------------------------------------------------

def flush_dns(run=None) -> str:
    try:
        result = (run or (lambda: subprocess.run(["ipconfig", "/flushdns"], capture_output=True, text=True, timeout=15, creationflags=NO_WINDOW)))()
    except (OSError, subprocess.SubprocessError) as e:
        return f"Error: couldn't run it ({e.__class__.__name__})."
    return "DNS cache cleared." if result.returncode == 0 else f"Error: Windows said: {(result.stdout or result.stderr).strip()[:200]}"


def old_temp_files(folder: Path | None = None, now: float | None = None, days: int = TEMP_AGE_DAYS) -> list[tuple[Path, int]]:
    """(path, size) of the files in the temp folder untouched for `days`, without following links or entering other programs' folders."""
    folder = folder or Path(tempfile.gettempdir())
    cutoff = (time.time() if now is None else now) - days * 86400
    found: list[tuple[Path, int]] = []
    stack = [folder]
    while stack and len(found) < MAX_TEMP_FILES:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_symlink():
                    continue
                if e.is_dir(follow_symlinks=False):
                    if current == folder and e.name.lower() in TEMP_SKIP:
                        continue
                    stack.append(Path(e.path))
                elif e.is_file(follow_symlinks=False):
                    st = e.stat(follow_symlinks=False)
                    if st.st_mtime < cutoff and st.st_atime < cutoff:
                        found.append((Path(e.path), st.st_size))
            except OSError:
                continue
    return found


def _size(n: float) -> str:
    return f"{n / 2**30:.1f} GB" if n >= 2**30 else f"{n / 2**20:.0f} MB"


def prepare_clean_temp(folder: Path | None = None, now: float | None = None) -> Prepared:
    folder = folder or Path(tempfile.gettempdir())
    files = old_temp_files(folder, now)
    total = sum(s for _, s in files)
    if not files:
        raise FixError(f"the temp folder has nothing older than {TEMP_AGE_DAYS} days to clear.")
    preview = (f"Deletes {len(files):,} files ({_size(total)}) from {folder} that haven't been changed or opened for {TEMP_AGE_DAYS} days. "
               "Windows and programs make these files for short-term use. Files in use are skipped, and nothing outside this folder is touched. "
               "Deleted files do not go to the Recycle Bin.")

    def run() -> str:
        cutoff = (time.time() if now is None else now) - TEMP_AGE_DAYS * 86400
        freed = removed = 0
        for path, size in files:
            try:
                if path.stat().st_mtime >= cutoff or path.is_symlink():       # changed since it was counted
                    continue
                if folder not in path.parents:
                    continue
                path.unlink()
                freed += size
                removed += 1
            except OSError:
                continue                                                       # in use or already gone
        return f"Cleared {removed:,} old temp files, freeing {_size(freed)}."
    return Prepared("JARVIS wants to clear old temp files", preview, run)


def _own_session() -> int:
    sid = ctypes.c_ulong()
    ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(sid))
    return sid.value


def process_info(pid: int, run=None) -> dict | None:
    """{name, id, session, mb, path} for one running process, or None if there isn't one."""
    script = (f"$p = Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; if ($p) {{ @{{ name = [string]$p.ProcessName; id = $p.Id; "
              "session = $p.SessionId; mb = [int]($p.WorkingSet64 / 1MB); path = [string]$p.Path } | ConvertTo-Json -Compress } else { '{}' }")
    info = diagnostics.powershell_json(script, timeout=15, run=run)
    return info if info and info.get("id") else None


def prepare_end_program(target: str, run=None, own_session=None, supervisor_pid=None) -> Prepared:
    try:
        pid = int(str(target).strip())
    except ValueError:
        raise FixError("give the process id (the number from system_details processes), not a name.") from None
    if pid <= 4 or pid in (os.getpid(), os.getppid()) or pid == (supervisor_pid if supervisor_pid is not None else supervisor_pid_now()):
        raise FixError("that is JARVIS itself or a core Windows process, so it won't be ended from here.")
    info = process_info(pid, run)
    if not info:
        raise FixError(f"no program with id {pid} is running.")
    name = str(info["name"])
    mine = own_session if own_session is not None else _own_session()
    if name.lower() in PROTECTED or info.get("session") in (0, None) or info.get("session") != mine:
        raise FixError(f"{name} is part of Windows or its security (or isn't one of your own programs), so it won't be ended from here.")
    where = f" ({info['path']})" if info.get("path") else ""
    preview = (f"Closes {name}, process {pid}{where}, which is using about {info.get('mb', 0)} MB. It is asked to close politely first, then forced "
               "after 4 seconds. Anything unsaved in it will be lost.")

    def run_it() -> str:
        again = process_info(pid, run)
        if not again or again.get("name") != name:
            return f"{name} had already closed."
        subprocess.run(["taskkill", "/PID", str(pid)], capture_output=True, creationflags=NO_WINDOW)
        for _ in range(8):
            time.sleep(0.5)
            if not process_info(pid, run):
                return f"Closed {name}."
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, creationflags=NO_WINDOW)
        time.sleep(0.5)
        return f"Closed {name}." if not process_info(pid, run) else f"Error: {name} would not close."
    return Prepared(f"JARVIS wants to close {name}", preview, run_it)


def pid_alive(pid: int) -> bool:
    """Is that process running? (os.kill(pid, 0) must not be used on Windows: it would end the process.)"""
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, int(pid))      # SYNCHRONIZE
    if not handle:
        return False
    try:
        return ctypes.windll.kernel32.WaitForSingleObject(handle, 0) == 0x102     # WAIT_TIMEOUT: still running
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def supervisor_pid_now() -> int | None:
    from . import supervisor
    try:
        pid = int(supervisor.PID_FILE.read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if pid_alive(pid) else None


def prepare_restart_jarvis(supervisor_pid=None, exit_fn=None) -> Prepared:
    pid = supervisor_pid if supervisor_pid is not None else supervisor_pid_now()
    if not pid:
        raise FixError("JARVIS wasn't started with JARVIS.bat, so nothing would bring it back after it stops. Close it and start JARVIS.bat yourself.")
    quit_now = exit_fn or (lambda: os._exit(3))

    def run() -> str:
        threading.Timer(2.0, quit_now).start()           # after this answer has gone out; the supervisor starts the server again
        return "JARVIS is restarting. The board reconnects by itself in a few seconds."
    return Prepared("JARVIS wants to restart itself", "Stops the JARVIS server for a few seconds; JARVIS.bat starts it again and the board reconnects by itself. "
                    "Anything JARVIS is in the middle of (this answer excepted) is dropped.", run)


def execute(prepared: Prepared, action: str, target: str = "") -> str:
    """Runs a prepared fix after approval and returns a result line (errors start with 'Error'). The agent logs the call."""
    try:
        result = prepared.run()
    except FixError as e:
        result = f"Error: {e}"
    except Exception as e:  # noqa: BLE001 - a fix that fails is a message, never a crash
        log.exception("fix %s failed", action)
        result = f"Error: the fix failed ({e.__class__.__name__})."
    return result
