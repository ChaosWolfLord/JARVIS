"""Keeps JARVIS running. Start it with JARVIS.bat (no console window) or JARVIS_debug.bat (shows the log).

- starts the board server and starts it again if it ever stops
- opens the board in its own full-screen browser window once the server answers
- optionally runs the pen tracker too and restarts that if it stops (set JARVIS_TRACKER_ARGS in .env)
- runs only once: starting it again just opens the window again
- logs go to %LOCALAPPDATA%\\jarvis\\logs

Stop everything with JARVIS_stop.bat.
"""
from __future__ import annotations

import argparse
import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from . import store

ROOT = store.ROOT
LOGS = store.STATE / "logs"
PID_FILE = store.STATE / "supervisor.pid"
BROWSER_PROFILE = store.STATE / "browser"          # the window's own profile (Chrome's; Edge gets its own, see profile_for)


def profile_for(browser: str) -> Path:
    """Each browser keeps its settings (microphone permission, chosen voice) in its own folder: they can't share one."""
    return store.STATE / "browser-edge" if "msedge" in str(browser).lower() else BROWSER_PROFILE
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def python_exe() -> str:
    """The console build of Python (pythonw has no standard output, which servers expect to have)."""
    exe = Path(sys.executable)
    console = exe.with_name("python.exe")
    return str(console) if exe.name.lower() == "pythonw.exe" and console.exists() else str(exe)

# Edge first: it comes with Windows and has Microsoft's natural-sounding voices, which JARVIS speaks with (Chrome only has the
# robotic Windows ones plus Google's).
BROWSER_PATHS = [
    r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe",
    r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe",
    r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
    r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
]


class Backoff:
    """Waits 1, 2, 4... up to 30 seconds between restarts; a run that lasted a minute counts as healthy and resets it."""

    def __init__(self) -> None:
        self.delay = 1.0

    def next(self, ran_for: float) -> float:
        if ran_for >= 60:
            self.delay = 1.0
        wait = self.delay
        self.delay = min(30.0, self.delay * 2)
        return wait


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def find_browser(env: dict | None = None, exists=os.path.exists) -> str | None:
    """Edge or Chrome, whichever is installed, Edge first (JARVIS_BROWSER in .env overrides)."""
    env = os.environ if env is None else env
    if env.get("JARVIS_BROWSER") and exists(env["JARVIS_BROWSER"]):
        return env["JARVIS_BROWSER"]
    for template in BROWSER_PATHS:
        path = os.path.expandvars(template)
        if "%" not in path and exists(path):
            return path
    return None


def browser_args(browser: str, url: str, profile: Path | None = BROWSER_PROFILE) -> list[str]:
    """An app-style window with no tabs or address bar, full screen. Its own profile keeps the microphone permission
    and these settings apart from your everyday browser, and lets the sound play without a first click."""
    args = [browser, f"--app={url}", "--start-fullscreen", "--no-first-run", "--no-default-browser-check",
            "--autoplay-policy=no-user-gesture-required"]
    if profile is not None:
        args.append(f"--user-data-dir={profile}")
    return args


def _log_file(name: str):
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / name
    if path.exists() and path.stat().st_size > 2_000_000:
        path.replace(path.with_suffix(".old.log"))
    return open(path, "ab", buffering=0)


def _say(log, text: str) -> None:
    log.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] supervisor: {text}\n".encode())


def wait_for_server(port: int, seconds: float = 40.0) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def open_window(port: int, default_profile: bool = False) -> None:
    url = f"http://localhost:{port}"
    browser = find_browser()
    if browser:
        subprocess.Popen(browser_args(browser, url, None if default_profile else profile_for(browser)))
    else:
        import webbrowser
        webbrowser.open(url)


def stop_running() -> int:
    """JARVIS_stop.bat: ends a running supervisor, and with it the server and tracker."""
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        print("JARVIS isn't running.")
        return 0
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    PID_FILE.unlink(missing_ok=True)
    print("JARVIS stopped.")
    return 0


class Child:
    """A program that is restarted when it exits."""

    def __init__(self, name: str, argv: list[str], log, say) -> None:
        self.name, self.argv, self.log, self.say = name, argv, log, say
        self.proc: subprocess.Popen | None = None
        self.started = 0.0
        self.not_before = 0.0
        self.backoff = Backoff()

    def tick(self) -> None:
        now = time.time()
        if self.proc and self.proc.poll() is None:
            return
        if self.proc:  # it just ended
            wait = self.backoff.next(now - self.started)
            self.say(f"{self.name} stopped (exit {self.proc.returncode}); restarting in {wait:.0f}s")
            self.not_before, self.proc = now + wait, None
        if now >= self.not_before:
            self.proc = subprocess.Popen(self.argv, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
            self.started = now
            self.say(f"started {self.name} (pid {self.proc.pid})")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def main(argv: list[str] | None = None) -> int:
    store.load_env()
    ap = argparse.ArgumentParser(prog="python -m server.supervisor", description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true", help="don't open the board window")
    ap.add_argument("--default-profile", action="store_true", help="open the window in your normal browser profile")
    ap.add_argument("--stop", action="store_true", help="stop a running JARVIS")
    args = ap.parse_args(argv)
    if args.stop:
        return stop_running()

    if port_open(args.port):
        # Already running (or something else owns the port): just show the board.
        if not args.no_browser:
            open_window(args.port, args.default_profile)
        return 0

    log = _log_file("jarvis.log")
    say = lambda text: _say(log, text)  # noqa: E731
    PID_FILE.write_text(str(os.getpid()))
    children = [Child("server", [python_exe(), "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(args.port)], log, say)]
    tracker_args = os.getenv("JARVIS_TRACKER_ARGS", "").strip()
    if tracker_args:
        children.append(Child("pen tracker", [python_exe(), "-W", "ignore", "-m", "tracker", *shlex.split(tracker_args)], log, say))
    opened = args.no_browser
    try:
        while True:
            for child in children:
                child.tick()
            if not opened and port_open(args.port):
                if wait_for_server(args.port):
                    open_window(args.port, args.default_profile)
                opened = True
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            child.stop()
        PID_FILE.unlink(missing_ok=True)
        say("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
