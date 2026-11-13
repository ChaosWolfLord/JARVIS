"""The privacy screen: "Jarvis, privacy" hides everything on the wall until the unlock code is given.

This is a curtain for casual eyes (a guest walks in, someone glances at the wall), not a lock against someone who
can use your PC. While it is down JARVIS also refuses to answer questions or show data (the server answers 423 Locked
to everything except the lock screen itself), so a guest can't ask it for your mail, and nothing listens: the PC's microphone closes and the page's
voice and camera stop. With a code set and a phone paired, the code is typed in the JARVIS app on the phone (the wall's own keypad is then off, so
it can't be guessed at the wall and the code is never said out loud); the keypad on the wall returns when no phone is paired, or when "Unlock only from
the phone app" is switched off. The code is only ever stored as a
salted hash, wrong guesses are slowed down (5 wrong in a row locks you out, for longer each time), and the state
survives a restart. Anyone who hears the code when you say it out loud can use it: say it quietly, or tap it in on the
on-screen keypad (it appears when you touch the screen).
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from typing import Callable

from . import store

FILE = store.STATE / "privacy.json"
ITERATIONS = 200_000
MAX_FAILS = 5
_lock = threading.Lock()


def _read() -> dict:
    return store._read(FILE, {})


def _write(data: dict) -> None:
    store._write(FILE, data)


def _hash(code: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", code.encode("utf-8"), salt, ITERATIONS).hex()


def valid_code(code: str) -> bool:
    return isinstance(code, str) and code.isascii() and code.isdigit() and 4 <= len(code) <= 8


def has_code() -> bool:
    return bool(_read().get("hash"))


def locked() -> bool:
    return bool(_read().get("locked"))


# Set by the app: is the phone door running with at least one phone paired? Without that the wall's keypad must stay usable, or nobody could unlock.
phone_ready: Callable[[], bool] = lambda: False


def phone_only() -> bool:
    """The "Unlock only from the phone app" choice (on unless switched off)."""
    return bool(_read().get("phone_only", True))


def set_phone_only(on: bool) -> bool:
    with _lock:
        d = _read()
        d["phone_only"] = bool(on)
        _write(d)
    return bool(on)


def wall_may_unlock() -> bool:
    """May the code be typed on the wall itself? Not when it has to come from the phone (a code is set, a phone is paired, and the choice is on)."""
    d = _read()
    return not (d.get("phone_only", True) and d.get("hash") and phone_ready())


def status() -> dict:
    d = _read()
    wait = max(0, int(d.get("until", 0) - time.time()))
    return {"locked": bool(d.get("locked")), "has_code": bool(d.get("hash")), "wait": wait, "phone_only": bool(d.get("phone_only", True)),
            "wall_unlock": wall_may_unlock()}


def lock() -> dict:
    with _lock:
        d = _read()
        d["locked"] = True
        _write(d)
    return status()


def _check(d: dict, code: str) -> bool:
    return bool(d.get("hash")) and valid_code(code) and hmac.compare_digest(_hash(code, bytes.fromhex(d["salt"])), d["hash"])


def unlock(code: str | None, now: float | None = None, via: str = "wall") -> tuple[bool, int]:
    """(unlocked?, seconds to wait before another try). With no code set, anyone can unlock (it's just a curtain). `via` is "wall" (this PC's page) or
    "phone"; when the code has to come from the phone, the wall is refused without counting as a wrong guess."""
    now = time.time() if now is None else now
    with _lock:
        d = _read()
        if not d.get("locked"):
            return True, 0
        if via != "phone" and not wall_may_unlock():
            return False, 0
        if d.get("until", 0) > now:
            return False, int(d["until"] - now) + 1
        if d.get("hash") and not _check(d, str(code or "")):
            d["fails"] = d.get("fails", 0) + 1
            if d["fails"] >= MAX_FAILS:                      # 30 s, then 60, 120... up to 15 minutes
                d["until"] = now + min(900, 30 * 2 ** (d.get("rounds", 0)))
                d["rounds"] = d.get("rounds", 0) + 1
                d["fails"] = 0
            _write(d)
            return False, max(0, int(d.get("until", 0) - now))
        d.update(locked=False, fails=0, rounds=0, until=0)
        _write(d)
        return True, 0


def set_code(new: str | None, current: str | None = None) -> bool:
    """Sets (or with new=None removes) the unlock code. Changing an existing code needs the current one. False if refused."""
    with _lock:
        d = _read()
        if d.get("hash") and not _check(d, str(current or "")):
            return False
        if new is None:
            d.pop("hash", None)
            d.pop("salt", None)
        else:
            if not valid_code(new):
                return False
            salt = secrets.token_bytes(16)
            d.update(salt=salt.hex(), hash=_hash(new, salt))
        d.update(fails=0, rounds=0, until=0)
        _write(d)
        return True


# What may still be asked of the server while the screen is down: the lock screen itself and the plain "is it running" check.
OPEN_WHILE_LOCKED = ("/api/privacy", "/api/status")


class Curtain:
    """An ASGI wrapper: while locked, every /api request except the ones above gets "423 Locked"."""

    def __init__(self, app, is_locked=locked) -> None:
        self.app = app
        self.is_locked = is_locked

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith("/api/") and not path.startswith(OPEN_WHILE_LOCKED) and self.is_locked():
            body = b'{"detail":"Privacy screen is on."}'
            await send({"type": "http.response.start", "status": 423,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            return await send({"type": "http.response.body", "body": body})
        return await self.app(scope, receive, send)
