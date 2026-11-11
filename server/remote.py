"""The phone as a remote control for this PC: a touchpad (move, click, right-click, scroll), slide keys (arrows, page up and down, F5, Esc) and media
keys (play and pause, next and previous, volume, mute).

This is real control of the PC, so it is held tightly:
  * It is OFF until you switch it on here (status menu, Phone, "Let my phone be a remote"), for a time you pick (30 minutes unless you say
    otherwise, at most two hours), and it switches itself off after that. A restart of JARVIS also switches it off. Nothing a phone says can switch it on.
  * Only the commands below exist. There is no way to type text, press Enter, the Windows key, Alt, Ctrl or any combination, so a phone cannot
    type a command, open a program by keyboard or confirm a dialog by keyboard. (A click is a click: switch it off when you hand your phone to someone.)
  * Every command is checked, its size is capped (one move is at most 300 pixels, a scroll at most 20 notches) and the rate is limited.
  * The privacy screen locks the remote too, and switching it on or off is written to the activity log.
Windows only (it uses SendInput); on any other system the commands are refused.
"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
from collections import deque
from typing import Callable

DEFAULT_MINUTES = 30
MAX_MINUTES = 120
MAX_MOVE = 300
MAX_SCROLL = 20
MAX_PER_SECOND = 120                     # a finger can produce about 60 moves a second; the phone sends fewer

# Keys a slide remote needs, as Windows virtual-key codes. Deliberately no Enter, space, letters, Windows key or modifiers.
KEYS = {"left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28, "pageup": 0x21, "pagedown": 0x22, "home": 0x24, "end": 0x23, "escape": 0x1B, "f5": 0x74}
EXTENDED = {"left", "up", "right", "down", "pageup", "pagedown", "home", "end"}
MEDIA = {"playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "volup": 0xAF, "voldown": 0xAE, "mute": 0xAD}
BUTTONS = ("left", "right")
ACTIONS = ("move", "click", "scroll", "key", "media")


class RemoteError(ValueError):
    """Why a command was refused, in words the phone can show."""


class NotArmed(RemoteError):
    pass


# ---- sending the input to Windows -----------------------------------------------------------------------------------------
class WindowsInput:
    """SendInput, through ctypes. Each method is one small, fixed kind of event."""

    INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
    MOVE, LEFTDOWN, LEFTUP, RIGHTDOWN, RIGHTUP, WHEEL = 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0800
    KEYUP, EXTENDEDKEY = 0x0002, 0x0001

    def __init__(self) -> None:
        from ctypes import wintypes

        class Mouse(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ctypes.c_size_t)]

        class Keyboard(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class Hardware(ctypes.Structure):
            _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]

        class Union(ctypes.Union):
            _fields_ = [("mi", Mouse), ("ki", Keyboard), ("hi", Hardware)]

        class Input(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", Union)]

        self._Mouse, self._Keyboard, self._Input = Mouse, Keyboard, Input

    def _send(self, *inputs) -> None:
        array = (self._Input * len(inputs))(*inputs)
        if ctypes.windll.user32.SendInput(len(inputs), array, ctypes.sizeof(self._Input)) != len(inputs):
            raise RemoteError("Windows did not accept the input (a program with higher rights may be in front).")

    def _mouse(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0):
        i = self._Input(type=self.INPUT_MOUSE)
        i.u.mi = self._Mouse(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
        return i

    def _key(self, vk: int, up: bool, extended: bool):
        i = self._Input(type=self.INPUT_KEYBOARD)
        i.u.ki = self._Keyboard(vk, 0, (self.KEYUP if up else 0) | (self.EXTENDEDKEY if extended else 0), 0, 0)
        return i

    def move(self, dx: int, dy: int) -> None:
        self._send(self._mouse(self.MOVE, dx, dy))

    def click(self, button: str) -> None:
        down, up = (self.LEFTDOWN, self.LEFTUP) if button == "left" else (self.RIGHTDOWN, self.RIGHTUP)
        self._send(self._mouse(down), self._mouse(up))

    def scroll(self, notches: int) -> None:
        self._send(self._mouse(self.WHEEL, data=notches * 120))

    def key(self, vk: int, extended: bool) -> None:
        self._send(self._key(vk, False, extended), self._key(vk, True, extended))


# ---- the remote itself --------------------------------------------------------------------------------------------------------
class Remote:
    def __init__(self, backend=None, now: Callable[[], float] = time.monotonic, log: Callable[[str], None] | None = None) -> None:
        self.backend = backend
        self.now = now
        self.log = log or (lambda text: None)
        self._until = 0.0
        self._lock = threading.Lock()
        self._recent: deque[float] = deque()
        self._count = 0                  # commands accepted since it was switched on (shown on the PC)

    # -- on and off (only the PC's own page does this) --
    def arm(self, minutes: float = DEFAULT_MINUTES) -> dict:
        try:
            minutes = float(minutes)
        except (TypeError, ValueError):
            raise RemoteError("minutes must be a number.") from None
        if not 1 <= minutes <= MAX_MINUTES:
            raise RemoteError(f"choose between 1 and {MAX_MINUTES} minutes.")
        with self._lock:
            self._until = self.now() + minutes * 60
            self._count = 0
        self.log(f"phone remote switched on for {minutes:g} minutes")
        return self.status()

    def disarm(self) -> dict:
        with self._lock:
            was = self._until > self.now()
            self._until = 0.0
        if was:
            self.log("phone remote switched off")
        return self.status()

    def seconds_left(self) -> int:
        with self._lock:
            return max(0, int(self._until - self.now()))

    def status(self) -> dict:
        left = self.seconds_left()
        return {"armed": left > 0, "seconds_left": left, "commands": self._count, "supported": self.backend is not None or sys.platform == "win32"}

    # -- one command from the phone --
    def do(self, cmd: dict) -> None:
        if self.seconds_left() <= 0:
            raise NotArmed("The remote is off. On the PC open the status menu, Phone, and press \"Let my phone be a remote\".")
        with self._lock:
            now = self.now()
            while self._recent and now - self._recent[0] > 1.0:
                self._recent.popleft()
            if len(self._recent) >= MAX_PER_SECOND:
                raise RemoteError("too many commands at once.")
            self._recent.append(now)
        backend = self.backend
        if backend is None:
            if sys.platform != "win32":
                raise RemoteError("the remote only works on Windows.")
            backend = self.backend = WindowsInput()
        what = str(cmd.get("do", ""))
        if what == "move":
            dx, dy = self._whole(cmd.get("dx"), MAX_MOVE), self._whole(cmd.get("dy"), MAX_MOVE)
            if dx or dy:
                backend.move(dx, dy)
        elif what == "click":
            button = str(cmd.get("button") or "left")
            if button not in BUTTONS:
                raise RemoteError("a click is left or right.")
            backend.click(button)
        elif what == "scroll":
            notches = self._whole(cmd.get("dy"), MAX_SCROLL)
            if notches:
                backend.scroll(notches)
        elif what == "key":
            key = str(cmd.get("key", ""))
            if key not in KEYS:
                raise RemoteError(f"keys are: {', '.join(KEYS)}.")
            backend.key(KEYS[key], key in EXTENDED)
        elif what == "media":
            key = str(cmd.get("key", ""))
            if key not in MEDIA:
                raise RemoteError(f"media keys are: {', '.join(MEDIA)}.")
            backend.key(MEDIA[key], True)
        else:
            raise RemoteError(f"commands are: {', '.join(ACTIONS)}.")
        self._count += 1

    @staticmethod
    def _whole(value, limit: int) -> int:
        try:
            n = int(round(float(value or 0)))
        except (TypeError, ValueError):
            raise RemoteError("that is not a number.") from None
        return max(-limit, min(limit, n))


remote = Remote()                        # the one the phone door and the PC page share
