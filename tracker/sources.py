"""Where camera frames come from. Each source yields (time, grey frame, illuminated) where illuminated is
True/False for cameras that alternate an IR light on and off frame by frame (Windows Hello cameras), else None."""
from __future__ import annotations

import math
import time
import warnings
from typing import Callable, Iterator

import numpy as np


class BrioIR:
    """The IR sensor in a Logitech BRIO (any Windows Hello camera) via whircam.

    Windows only offers that stream when the camera is opened with exclusive control, so the sharing mode
    whircam uses is switched. While this runs, Windows Hello can't use the camera.
    """

    name = "brio-ir"

    def __init__(self, camera: str | None = None) -> None:
        """camera: part of the camera's name (e.g. "BRIO") to pick it when several have an IR sensor."""
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="whircam")
        import whircam
        from winrt.windows.media.capture import MediaCaptureSharingMode

        groups = whircam.find_groups()  # also lets whircam finish its start-up checks before its setting is changed
        if not groups:
            raise SystemExit("No infrared (Windows Hello) camera found. Plug the BRIO in and try again, "
                             "or use --source cv:N for an ordinary USB camera. See: run_tracker.bat --list")
        pick = [g for g in groups if camera.lower() in g["name"].lower()] if camera else groups
        if not pick:
            raise SystemExit(f"No IR camera matches {camera!r}. Found: {', '.join(g['name'] for g in groups)}")
        whircam._SHARED_READ_ONLY = MediaCaptureSharingMode.EXCLUSIVE_CONTROL
        self.cap = whircam.IRCam(group=pick[0]["index"], format_output="gray")
        self.size = (self.cap.width, self.cap.height)
        self.camera_name = pick[0]["name"]

    def frames(self) -> Iterator[tuple[float, np.ndarray, bool | None]]:
        while True:
            ok, frame = self.cap.read(timeout=1.0)
            if ok and frame is not None:
                yield time.monotonic(), frame, bool(self.cap.illuminated)

    def close(self) -> None:
        self.cap.release()


class CvCamera:
    """An ordinary USB camera through OpenCV (the dedicated IR camera you'll buy shows up like this)."""

    def __init__(self, index: int = 0, width: int = 640, height: int = 480, fps: int = 60, color: bool = False,
                 zoom: int | None = None, exposure: int | None = None, gain: int | None = None) -> None:
        import cv2

        self.name = f"cv:{index}"
        self.color = color  # finger mode needs the colour picture; pen mode wants grey
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        # High frame rates (100 fps on the Arducam OV9281) only exist in MJPG; the default format is far slower.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)   # no queue of old frames: the newest one, always
        if not self.cap.isOpened():
            raise RuntimeError(f"couldn't open camera {index}")
        if zoom:                                    # the camera's own zoom: a hand 2x bigger in the picture at zoom 200 (BRIO: 100 to 500)
            self.cap.set(cv2.CAP_PROP_ZOOM, zoom)
        if exposure is not None:                    # manual exposure (DirectShow: -4 is 1/16 s, -5 is 1/32 s, -6 is 1/64 s): less blur, darker picture
            self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
            self.cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
        if gain is not None:                        # brightens a dark picture, with more grain
            self.cap.set(cv2.CAP_PROP_GAIN, gain)
        self.size = (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))

    def _reader(self) -> None:
        """Reads the camera as fast as it delivers, keeping only the newest frame, so a slow detector never works on old pictures."""
        while self._running:
            ok, frame = self.cap.read()
            if ok:
                with self._cond:
                    self._latest, self._seq = (time.monotonic(), frame), self._seq + 1
                    self._cond.notify_all()

    def frames(self) -> Iterator[tuple[float, np.ndarray, bool | None]]:
        import threading

        self._cond, self._latest, self._seq, self._running = threading.Condition(), None, 0, True
        threading.Thread(target=self._reader, daemon=True).start()
        seen = 0
        while True:
            with self._cond:
                self._cond.wait_for(lambda: self._seq != seen, timeout=1.0)
                if self._seq == seen:
                    continue
                seen, (t, frame) = self._seq, self._latest
            if not self.color and frame.ndim == 3:
                frame = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
            yield t, frame, None

    def close(self) -> None:
        self._running = False
        time.sleep(0.1)
        self.cap.release()


def list_cameras(probe: bool = False) -> dict:
    """What cameras this PC has. probe=True also opens each OpenCV index for an instant (its light flashes)."""
    import asyncio

    found: dict = {"windows": [], "ir_groups": [], "opencv": []}
    try:
        from winrt.windows.devices.enumeration import DeviceClass, DeviceInformation

        async def names():
            return [d.name for d in await DeviceInformation.find_all_async(DeviceClass.VIDEO_CAPTURE)]

        found["windows"] = asyncio.run(names())
    except Exception as e:  # noqa: BLE001
        found["windows_error"] = str(e)
    try:
        warnings.filterwarnings("ignore", category=RuntimeWarning, module="whircam")
        import whircam

        found["ir_groups"] = [g["name"] for g in whircam.find_groups()]
    except Exception as e:  # noqa: BLE001
        found["ir_error"] = str(e)
    if probe:
        import cv2

        for i in range(6):
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                found["opencv"].append({"index": i, "width": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                                        "height": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))})
            cap.release()
    return found


class Simulated:
    """A made-up camera: a pen light moving along a path over noisy dark frames. For tests and demos.

    path(t) returns the pen's (x, y) in camera pixels at time t seconds, or None when the pen is lifted.
    """

    name = "sim"

    def __init__(self, path: Callable[[float], tuple[float, float] | None], size: tuple[int, int] = (340, 340),
                 fps: float = 30.0, seconds: float | None = None, noise: float = 1.0, amp: float = 40.0,
                 realtime: bool = False, seed: int = 1) -> None:
        self.path, self.size, self.fps, self.seconds = path, size, fps, seconds
        self.noise, self.amp, self.realtime = noise, amp, realtime
        self.rng = np.random.default_rng(seed)

    def render(self, pos: tuple[float, float] | None) -> np.ndarray:
        w, h = self.size
        frame = 2.0 + self.rng.normal(0, self.noise, (h, w))
        if pos is not None:
            ys, xs = np.mgrid[0:h, 0:w]
            frame += self.amp * np.exp(-((xs - pos[0]) ** 2 + (ys - pos[1]) ** 2) / (2 * 1.5 ** 2))
        return np.clip(frame, 0, 255).astype(np.uint8)

    def frames(self) -> Iterator[tuple[float, np.ndarray, bool | None]]:
        n, start = 0, time.monotonic()
        while self.seconds is None or n / self.fps < self.seconds:
            t = n / self.fps
            if self.realtime:
                time.sleep(max(0.0, start + t - time.monotonic()))
            yield t, self.render(self.path(t)), None
            n += 1

    def close(self) -> None:
        pass


SKIN_BGR = (140, 172, 224)
WALL_BGR = (185, 200, 215)   # a beige wall: deliberately close to skin colour


class SimulatedHand:
    """A made-up colour camera: a beige wall and an arm reaching in from the bottom. For tests and demos.

    path(t) returns where the fingertip is in pixels at time t seconds, or None when the hand is out of view.
    """

    name = "simhand"
    camera_name = "simulated hand"

    def __init__(self, path: Callable[[float], tuple[float, float] | None], size: tuple[int, int] = (640, 360),
                 fps: float = 30.0, seconds: float | None = None, noise: float = 2.0, realtime: bool = False,
                 seed: int = 1, skin: tuple[int, int, int] = SKIN_BGR) -> None:
        self.path, self.size, self.fps, self.seconds = path, size, fps, seconds
        self.noise, self.realtime, self.skin = noise, realtime, skin
        self.rng = np.random.default_rng(seed)
        w, h = size
        # Fresh noise for every frame is slow; a small bank of noise patterns used in rotation looks the same.
        self.noise_bank = [self.rng.normal(0, noise, (h, w, 3)).astype(np.float32) for _ in range(5)]
        self.wall = np.empty((h, w, 3), np.float32)
        self.wall[:] = WALL_BGR
        self.count = 0

    def render(self, tip: tuple[float, float] | None) -> np.ndarray:
        import cv2

        w, h = self.size
        self.count += 1
        frame = np.clip(self.wall + self.noise_bank[self.count % len(self.noise_bank)], 0, 255).astype(np.uint8)
        if tip is not None:
            base = np.array([w / 2 + (tip[0] - w / 2) * 0.3, h + 40.0])      # the arm leans toward the tip
            direction = np.array(tip) - base
            direction /= np.linalg.norm(direction)
            centre = np.array(tip) - direction * 16                           # so the extreme point is `tip`
            cv2.line(frame, tuple(int(v) for v in base), tuple(int(v) for v in centre), self.skin, 44)
            cv2.circle(frame, tuple(int(v) for v in centre), 16, self.skin, -1)
        return frame

    def frames(self) -> Iterator[tuple[float, np.ndarray, bool | None]]:
        n, start = 0, time.monotonic()
        while self.seconds is None or n / self.fps < self.seconds:
            t = n / self.fps
            if self.realtime:
                time.sleep(max(0.0, start + t - time.monotonic()))
            yield t, self.render(self.path(t)), None
            n += 1

    def close(self) -> None:
        pass


def demo_hand(t: float) -> tuple[float, float] | None:
    """Every 9 s: sweep to the middle, hold still for 1.3 s (a tap), sweep on, then leave."""
    c = t % 9
    if c < 1.0:
        return None
    if c < 2.5:
        a = (c - 1.0) / 1.5
        return 140 + (320 - 140) * a, 200 - 50 * a
    if c < 3.8:
        return 320.0, 150.0
    if c < 5.3:
        a = (c - 3.8) / 1.5
        return 320 + 180 * a, 150 + 50 * a
    return None


def demo_path(t: float) -> tuple[float, float] | None:
    """Draws a looping figure for 6 s, then lifts the pen for 2 s."""
    if t % 8 >= 6:
        return None
    return 170 + 100 * math.sin(2 * math.pi * t / 3), 170 + 70 * math.sin(2 * math.pi * t / 1.5)
