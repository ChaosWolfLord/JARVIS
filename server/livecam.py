"""A live camera feed on the wall.

Two sources, both shown in the wall's Camera card:
  * This PC's own camera: the wall page opens it itself (nothing here is involved; the picture never leaves the page).
  * The phone's camera: the phone page sends a small JPEG about nine times a second to the phone door, this module keeps the newest one, and the wall
    page asks for it (a long poll, so it arrives as soon as it is there).

How it is kept safe and private:
  * Only the phone can start it. The wall can ask (it sends the phone a notification), but nothing on the PC can switch the phone's camera on: you tap
    "Show my camera on the wall" in the phone app each time, and the phone shows a bar saying so, with a Stop button.
  * Only ever the newest frame, in memory. Nothing is written to disk, nothing is recorded, nothing goes to an AI or to the internet.
  * Only a paired phone (its token), only over your home Wi-Fi like the rest of the phone door, and only JPEG pictures up to 400 KB.
  * The wall can stop it at any moment (the phone is told on its next frame and shuts its camera), the privacy screen stops it and clears the frame, and a
    feed that stops sending (the phone closed the app) goes dark by itself after a few seconds.
  * A second phone starting a feed takes over; the first is told to stop.
"""
from __future__ import annotations

import threading
import time
from typing import Callable

MAX_FRAME = 400_000
STALE_S = 6.0                # no new frame for this long: the feed is over
MIN_GAP_S = 0.05             # frames closer together than this are dropped (at most about 20 a second)
JPEG = b"\xff\xd8\xff"


class Feed:
    """The newest frame from the phone that is showing its camera. All of it is in memory."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, locked: Callable[[], bool] = lambda: False) -> None:
        self.cond = threading.Condition()
        self.clock, self.locked = clock, locked
        self.frame = b""
        self.seq = 0
        self.owner = ""
        self.last = 0.0
        self.told_to_stop: dict[str, float] = {}

    def _live(self) -> bool:
        return bool(self.frame) and self.clock() - self.last <= STALE_S

    def active(self) -> bool:
        with self.cond:
            return self._live()

    def put(self, owner: str, data: bytes) -> dict:
        """A frame from a phone. {ok, started?, stop?, why?}: `stop` tells the phone to shut its camera."""
        if self.locked():
            self.stop()
            return {"ok": False, "stop": True, "why": "The privacy screen is on."}
        with self.cond:
            now = self.clock()
            for who in [w for w, t in self.told_to_stop.items() if now - t > 60]:
                del self.told_to_stop[who]
            if owner in self.told_to_stop:
                del self.told_to_stop[owner]
                return {"ok": False, "stop": True, "why": "The camera was stopped on the PC."}
            if not data or len(data) > MAX_FRAME or not data.startswith(JPEG):
                return {"ok": False, "stop": False, "why": "That isn't a JPEG picture."}
            live = self._live()
            started = not live or self.owner != owner
            if live and self.owner and self.owner != owner:
                self.told_to_stop[self.owner] = now                # the newest phone wins
            if not started and now - self.last < MIN_GAP_S:
                return {"ok": True, "dropped": True}
            self.frame, self.owner, self.last = data, owner, now
            self.seq += 1
            self.cond.notify_all()
            return {"ok": True, "started": started}

    def release(self, owner: str) -> bool:
        """The phone stopped by itself. True if it was the one showing."""
        with self.cond:
            if owner != self.owner:
                return False
            was = self._live()
            self.frame, self.owner, self.last = b"", "", 0.0
            self.seq += 1
            self.cond.notify_all()
            return was

    def stop(self) -> bool:
        """The wall (or the privacy screen) ends the feed; the phone is told on its next frame. True if one was live."""
        with self.cond:
            was = self._live()
            if self.owner:
                self.told_to_stop[self.owner] = self.clock()
            self.frame, self.owner, self.last = b"", "", 0.0
            self.seq += 1
            self.cond.notify_all()
            return was

    def wait_newer(self, after: int, timeout: float) -> tuple[int, bytes, bool]:
        """(seq, frame, live): returns at once if there is a frame newer than `after`, otherwise waits up to `timeout` seconds for one."""
        if self.locked():
            self.stop()
            return self.seq, b"", False
        with self.cond:
            self.cond.wait_for(lambda: self.seq != after, timeout=max(0.0, min(timeout, 10.0)))
            live = self._live()
            return self.seq, (self.frame if live and self.seq != after else b""), live          # a frame the wall already has is not sent again

    def status(self) -> dict:
        with self.cond:
            return {"active": self._live(), "seq": self.seq, "age": round(self.clock() - self.last, 1) if self.last else None}


feed = Feed()
