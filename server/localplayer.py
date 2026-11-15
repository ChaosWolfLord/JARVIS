"""Music on this PC, for when no speaker can be reached.

When a speaker can't be connected to (it is off, on another network, or no speakers are found at all), JARVIS plays the song from YouTube Music on
this PC instead: it opens music.youtube.com for that song in its own small window and the sound comes out of the PC.

What it does and does not do, so it is safe to give a voice command:
- It opens exactly one kind of address, https://music.youtube.com/watch?v=<id>[&list=<id>], where the ids are the short letters-and-digits codes the
  YouTube Music search returned (checked below). Nothing you say, and nothing a web page says, ever becomes part of the address or of the
  command line.
- The window has its own browser profile (%LOCALAPPDATA%\\jarvis\\browser-music), apart from your everyday browser and from JARVIS's own window.
  Sign in to YouTube Music there once if you want your account (no ads with Premium); JARVIS never sees that.
- Pause, resume, next and previous press the PC's media keys (the same keys a keyboard has), which YouTube Music answers. Volume presses the
  volume keys. Stop closes the window. The window is closed politely (the way the close button does) before it is forced.
- Another song closes the earlier window first (found by its profile folder), so they do not pile up.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from . import store

PROFILE = store.STATE / "browser-music"
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
LIST_ID = re.compile(r"^[A-Za-z0-9_-]{2,80}$")
WINDOW = (460, 760)
NO_WINDOW = getattr(subprocess, "DETACHED_PROCESS", 0)
VOLUME_STEP = 2                  # Windows moves the volume 2 percent for each press of a volume key
KEYS = {"pause": "playpause", "resume": "playpause", "next": "next", "previous": "prev"}


class LocalPlayerError(ValueError):
    """Why the song can't be played here, in words the person can act on."""


def watch_url(video_id: str, playlist_id: str | None = None) -> str:
    """The one address that is ever opened. Raises LocalPlayerError for an id that isn't the plain kind."""
    if not isinstance(video_id, str) or not VIDEO_ID.match(video_id):
        raise LocalPlayerError("that song has an address I don't recognise.")
    url = f"https://music.youtube.com/watch?v={video_id}"
    if playlist_id and isinstance(playlist_id, str) and LIST_ID.match(playlist_id):
        url += f"&list={playlist_id}"
    return url


def _screen() -> tuple[int, int]:
    try:
        import ctypes
        return ctypes.windll.user32.GetSystemMetrics(0), ctypes.windll.user32.GetSystemMetrics(1)
    except Exception:  # noqa: BLE001 - not Windows, or no screen information: the browser picks the place
        return 0, 0


def window_args(browser: str, url: str, profile: Path = PROFILE, screen: tuple[int, int] | None = None) -> list[str]:
    """The browser's command line: a small app-style window (no tabs or address bar) at the right of the screen, with its own profile, where sound
    plays without a first click. The address is the only thing from outside, and it was built by watch_url."""
    sw, sh = screen if screen is not None else _screen()
    w, h = WINDOW
    args = [browser, f"--app={url}", f"--window-size={w},{h}", "--no-first-run", "--no-default-browser-check", "--autoplay-policy=no-user-gesture-required",
            f"--user-data-dir={profile}"]
    if sw and sh:
        args.append(f"--window-position={max(0, sw - w - 24)},{max(0, (sh - h) // 2)}")
    return args


def _find_browser() -> str | None:
    from . import supervisor
    return supervisor.find_browser()


def _press(name: str, times: int = 1) -> None:
    from . import remote
    backend = remote.WindowsInput()
    for _ in range(times):
        backend.key(remote.MEDIA[name], True)
        time.sleep(0.004)


def _profile_pids(profile: Path) -> list[int]:
    """The main process of the browser running with this profile (the window's browser; its helpers close with it). Found by its profile folder,
    because the process JARVIS starts hands the window to another one and exits."""
    script = ("Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'msedge.exe' -or $_.Name -eq 'chrome.exe') -and $_.CommandLine -and "
              "$_.CommandLine.Contains($env:JARVIS_MUSIC_PROFILE) -and -not $_.CommandLine.Contains('--type=') } | ForEach-Object { $_.ProcessId }")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True, timeout=20,
                             env={**os.environ, "JARVIS_MUSIC_PROFILE": str(profile)}, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in out.split() if x.isdigit()]


def _alive(pid: int) -> bool:
    """Is this process still running? (A quick check, so waiting for a window to close costs nothing.)"""
    try:
        import ctypes
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)           # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return bool(ok) and code.value == 259                                     # STILL_ACTIVE
    except Exception:  # noqa: BLE001 - if it can't be told, assume it is still there and let the force step decide
        return True


def _close(profile: Path) -> None:
    """Closes the music window the polite way first (the same as its close button), then ends that browser (it only ever has this one window)."""
    if sys.platform != "win32":
        return
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    pids = _profile_pids(profile)

    def kill(force: bool) -> None:
        for pid in pids:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T"] + (["/F"] if force else []), capture_output=True, timeout=10, creationflags=flags, check=False)
            except (OSError, subprocess.SubprocessError):
                pass

    kill(False)
    deadline = time.time() + 1.5                   # the window is gone by then; Edge may keep its process running in the background, so it is ended too
    while time.time() < deadline:
        if not any(_alive(pid) for pid in pids):
            return
        time.sleep(0.25)
    kill(True)


class LocalPlayer:
    """Everything the PC does is a parameter, so the tests need no browser, no keyboard and no screen."""

    def __init__(self, find_browser: Callable[[], str | None] = _find_browser, launch=subprocess.Popen, press: Callable[[str, int], None] = _press,
                 close: Callable[[Path], None] = _close, profile: Path = PROFILE, screen: Callable[[], tuple[int, int]] = _screen) -> None:
        self._find, self._launch, self._press, self._close, self.profile, self._screen = find_browser, launch, press, close, profile, screen
        self.proc = None
        self.closer: threading.Thread | None = None
        self.paused = False
        self.active = False

    def available(self) -> bool:
        return sys.platform == "win32" and bool(self._find())

    def play(self, video_id: str, playlist_id: str | None = None) -> None:
        url = watch_url(video_id, playlist_id)
        browser = self._find()
        if sys.platform != "win32" or not browser:
            raise LocalPlayerError("I can't find Edge or Chrome on this PC to play it in.")
        if self.active:
            self._end(wait=True)                               # the window of the song before goes first (a new window would join it)
        elif self.closer is not None:
            self.closer.join(timeout=8)
        try:
            self.profile.mkdir(parents=True, exist_ok=True)
            self.proc = self._launch(window_args(browser, url, self.profile, self._screen()), close_fds=True, creationflags=NO_WINDOW)
        except OSError as e:
            raise LocalPlayerError(f"I couldn't start the browser ({e.__class__.__name__}).") from None
        self.paused = False
        self.active = True

    def _end(self, wait: bool = False) -> None:
        """Closes the window of the song before, in the background (closing can take a few seconds); `wait` waits for it."""
        self.active = False
        self.proc = None
        self.closer = threading.Thread(target=self._close, args=(self.profile,), daemon=True, name="close-music")
        self.closer.start()
        if wait:
            self.closer.join(timeout=10)

    def control(self, what: str) -> str:
        if what == "stop":
            if self.active:
                self._end()
            self.paused = False
            return "Stopped."
        if what not in KEYS:
            raise LocalPlayerError("that isn't something I can do on this PC.")
        if what == "pause" and self.paused:
            return "Already paused."
        if what == "resume" and not self.paused:
            return "Already playing."
        self._press(KEYS[what], 1)
        if what in ("pause", "resume"):
            self.paused = what == "pause"
        else:
            self.paused = False
        return {"pause": "Paused.", "resume": "Playing.", "next": "Next song.", "previous": "Previous song."}[what]

    def volume(self, level: int | None = None, direction: str = "") -> str:
        """Up or down by ten percent, or to a level: all the way down, then up in steps (a PC has no key for an exact level)."""
        if level is not None:
            level = max(0, min(100, int(level)))
            self._press("voldown", 50)
            self._press("volup", round(level / VOLUME_STEP))
            return f"Volume {level} percent."
        if direction not in ("up", "down"):
            raise LocalPlayerError("up or down?")
        self._press("volup" if direction == "up" else "voldown", 5)
        return f"Volume {direction}."
