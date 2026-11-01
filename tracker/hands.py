"""Hand tracking with MediaPipe: a steadier fingertip than skin colour, and a pinch gesture for clicking.

MediaPipe finds the hand from its shape, so skin colour, lighting and the colour of the wall don't matter.
It gives 21 points per hand. We use the index fingertip (8) as the pointer, and the distance between the thumb
tip (4) and the index tip, measured against the size of the palm, as the pinch.
"""
from __future__ import annotations

import math
import os
import time
import urllib.request
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .detect import OneEuro

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
MODEL = Path(os.getenv("LOCALAPPDATA") or Path(__file__).resolve().parent.parent / "data") / "jarvis" / "models" / "hand_landmarker.task"

WRIST, THUMB_TIP, INDEX_MCP, INDEX_TIP, MIDDLE_MCP, PINKY_MCP = 0, 4, 5, 8, 9, 17
# Bones to draw in the --view window.
BONES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11), (11, 12),
         (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20)]


def available() -> bool:
    """MediaPipe installed and the model file present?"""
    try:
        import mediapipe  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return MODEL.exists()


def download_model() -> None:
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {MODEL_URL}\n  to {MODEL}", flush=True)
    urllib.request.urlretrieve(MODEL_URL, MODEL)
    size = MODEL.stat().st_size
    if size < 1_000_000 or b"PK" not in MODEL.read_bytes()[:8]:
        MODEL.unlink(missing_ok=True)
        raise SystemExit("the download doesn't look like a MediaPipe model file; try again")
    print(f"done, {size / 1e6:.1f} MB", flush=True)


def search_windows(frame_w: int, frame_h: int, roi: tuple[float, float, float, float], win: int) -> list[tuple[int, int, int, int]]:
    """Square windows (x0, y0, x1, y1), overlapping by a quarter, that together cover the region of interest.

    MediaPipe shrinks whatever it is given to 192x192 pixels before looking for a hand, so a hand far from the camera
    is only found if we hand it a small, zoomed-in piece of the picture. The first window is the whole frame, which
    catches hands that are close to the camera.
    """
    out = [(0, 0, frame_w, frame_h)]
    win = max(64, min(win, frame_w, frame_h))
    margin = win // 4        # let the windows reach a little past the region, so a hand at its edge isn't cut in half
    rx0, ry0 = max(0, int(roi[0] * frame_w) - margin), max(0, int(roi[1] * frame_h) - margin)
    rx1, ry1 = min(frame_w, int(roi[2] * frame_w) + margin), min(frame_h, int(roi[3] * frame_h) + margin)
    stride = max(1, int(win * 0.75))
    xs = list(range(rx0, max(rx0 + 1, rx1 - win + 1), stride))
    ys = list(range(ry0, max(ry0 + 1, ry1 - win + 1), stride))
    if xs[-1] + win < rx1:
        xs.append(rx1 - win)
    if ys[-1] + win < ry1:
        ys.append(ry1 - win)
    for y in ys:
        for x in xs:
            x0, y0 = max(0, min(x, frame_w - win)), max(0, min(y, frame_h - win))
            out.append((x0, y0, x0 + win, y0 + win))
    return out


def follow_window(cx: float, cy: float, win: int, frame_w: int, frame_h: int) -> tuple[int, int, int, int]:
    """A square window of side `win` centred on (cx, cy), slid back inside the frame if it would stick out."""
    win = min(win, frame_w, frame_h)
    x0 = int(max(0, min(cx - win / 2, frame_w - win)))
    y0 = int(max(0, min(cy - win / 2, frame_h - win)))
    return x0, y0, x0 + win, y0 + win


def predicted_window(crop: tuple[int, int, int, int], center: tuple[float, float], vel: tuple[float, float],
                     frame_w: int, frame_h: int, margin: float = 0.25) -> tuple[int, int, int, int]:
    """Where to put the next frame's window, given the one used last frame and how the hand is moving.

    The window slides by the hand's velocity, so the hand stays at the same place inside it from frame to frame.
    That matters: MediaPipe finds the hand in each frame from where it was in the last one, so a window that jumps
    makes it lose the hand. The window only recentres if the hand is about to leave the middle of it.
    """
    x0, y0, x1, y1 = crop
    cw, ch = x1 - x0, y1 - y0
    nx0, ny0 = x0 + vel[0], y0 + vel[1]
    cx, cy = center[0] + vel[0], center[1] + vel[1]
    nx0 = min(nx0, cx - margin * cw) if cx < nx0 + margin * cw else max(nx0, cx - (1 - margin) * cw)
    ny0 = min(ny0, cy - margin * ch) if cy < ny0 + margin * ch else max(ny0, cy - (1 - margin) * ch)
    nx0 = int(max(0, min(nx0, frame_w - cw)))
    ny0 = int(max(0, min(ny0, frame_h - ch)))
    return nx0, ny0, nx0 + cw, ny0 + ch


class HandTracker:
    """Colour frame in, hand out: {x, y (index fingertip), mid (pinch point), pinch (ratio), size}, or None.

    Two modes. Searching: look for a hand in zoomed-in windows over the region of interest (and the whole frame),
    a few windows per frame so the picture stays smooth. This only recognises an open palm, which is how MediaPipe's
    palm detector works. Tracking: once a hand is found, MediaPipe follows it from frame to frame whatever shape it
    makes (fist, point, pinch), inside a window that moves with the hand. Fast hands are why the window is predicted
    from the hand's speed, and why a few missed frames are forgiven before searching starts again.
    """

    def __init__(self, model: Path = MODEL, num_hands: int = 1, confidence: float = 0.4, window: int = 480,
                 roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0), search_ms: float = 45.0,
                 track_confidence: float = 0.3, patience: int = 4) -> None:
        if not Path(model).exists():
            raise SystemExit(f"hand model missing: {model}\nGet it with:  run_tracker.bat --get-model")
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions

        self.mp = mp
        self.landmarker = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,    # remembers the hand between frames, so it needn't see an open palm again
            num_hands=num_hands,
            min_hand_detection_confidence=confidence,
            min_hand_presence_confidence=track_confidence,
            min_tracking_confidence=track_confidence,
        ))
        self.window, self.roi, self.search_ms, self.patience = window, roi, search_ms, patience
        self.ready = True
        self.points: np.ndarray | None = None       # last hand's 21 points in pixels, for the --view window
        self.rect: tuple[int, int, int, int] | None = None   # the window last used, for the --view window
        self.mask = None
        self.center: tuple[float, float] | None = None
        self.crop: tuple[int, int, int, int] | None = None   # the window being followed (None while searching)
        self.vel = (0.0, 0.0)
        self.size = 0.0
        self.lost = 0
        self.next_window = 0
        self.windows: list[tuple[int, int, int, int]] = []
        self.windows_for: tuple[int, int] | None = None
        self._ts = 0

    def _run(self, bgr: np.ndarray, rect: tuple[int, int, int, int]) -> np.ndarray | None:
        x0, y0, x1, y1 = rect
        crop = np.ascontiguousarray(cv2.cvtColor(bgr[y0:y1, x0:x1], cv2.COLOR_BGR2RGB))
        self._ts = max(self._ts + 1, int(time.monotonic() * 1000))        # VIDEO mode wants strictly rising milliseconds
        result = self.landmarker.detect_for_video(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=crop), self._ts)
        if not result.hand_landmarks:
            return None
        cw, ch = x1 - x0, y1 - y0
        return np.array([(x0 + p.x * cw, y0 + p.y * ch) for p in result.hand_landmarks[0]], dtype=np.float32)

    def _start_search_near(self, w: int, h: int) -> None:
        """Begin round-robin searching with the windows nearest to where the hand was lost."""
        if self.windows_for != (w, h):
            self.windows, self.windows_for = search_windows(w, h, self.roi, self.window), (w, h)
        if self.center is not None and len(self.windows) > 1:
            def gap(r):
                return math.hypot((r[0] + r[2]) / 2 - self.center[0], (r[1] + r[3]) / 2 - self.center[1])
            self.next_window = 1 + min(range(1, len(self.windows)), key=lambda i: gap(self.windows[i]))

    def detect(self, bgr: np.ndarray) -> dict | None:
        h, w = bgr.shape[:2]
        pts, rect = None, None

        if self.crop is not None:                             # tracking: a window that moves with the hand
            rect = predicted_window(self.crop, self.center, self.vel, w, h)
            pts = self._run(bgr, rect)
            if pts is None:
                self.lost += 1
                self.crop, self.vel = rect, (self.vel[0] * 0.5, self.vel[1] * 0.5)
                if self.lost > self.patience:                 # given up: search again, starting where it was lost
                    self.crop = None
                    self._start_search_near(w, h)

        if pts is None and self.crop is None:                 # searching: a few windows per frame, round-robin
            if self.windows_for != (w, h):
                self._start_search_near(w, h)
            started = time.perf_counter()
            for _ in range(len(self.windows)):
                rect = self.windows[self.next_window % len(self.windows)]
                self.next_window += 1
                pts = self._run(bgr, rect)
                if pts is not None or (time.perf_counter() - started) * 1000 > self.search_ms:
                    break

        if pts is None:
            self.points = None
            self.rect = rect
            return None
        center = (float(pts[:, 0].mean()), float(pts[:, 1].mean()))
        if self.crop is not None and self.lost == 0 and self.center is not None:   # speed in pixels per frame, smoothed
            self.vel = (0.6 * self.vel[0] + 0.4 * (center[0] - self.center[0]), 0.6 * self.vel[1] + 0.4 * (center[1] - self.center[1]))
        else:
            self.vel = (0.0, 0.0)
        self.points, self.rect, self.lost, self.crop, self.center = pts, rect, 0, rect, center
        size = float(np.hypot(*(pts[WRIST] - pts[MIDDLE_MCP]))) or 1.0       # palm length: scales the pinch
        self.size = size
        gap = float(np.hypot(*(pts[INDEX_TIP] - pts[THUMB_TIP])))
        mid = (pts[INDEX_TIP] + pts[THUMB_TIP]) / 2
        return {"x": float(pts[INDEX_TIP][0]), "y": float(pts[INDEX_TIP][1]), "mid": (float(mid[0]), float(mid[1])),
                "pinch": gap / size, "size": size}

    def close(self) -> None:
        self.landmarker.close()


class PinchPointer:
    """Pointer events from a hand: hover while the hand is visible, press while thumb and index finger pinch.

    - hover: every frame; `dwell` (0 to 1) shows how close the fingers are to pinching, so the ring fills as you pinch.
    - down: the pinch closes. move: while it stays closed (drag, draw). up: it opens.
    - gone: the hand left the picture.
    Two thresholds (close below `on`, open above `off`) and a short debounce stop it flickering at the edge.
    """

    def __init__(self, to_board: Callable[[float, float], tuple[float, float]], on: float = 0.32, off: float = 0.5,
                 frames: int = 2, lost_frames: int = 10) -> None:
        self.to_board = to_board
        self.on, self.off, self.frames, self.lost_frames = on, off, frames, lost_frames
        self.fx, self.fy = OneEuro(1.2, 0.004), OneEuro(1.2, 0.004)
        self.down = False
        self.streak = 0          # consecutive frames that disagree with the current state
        self.missed = 0
        self.visible = False
        self.last = (0.0, 0.0)

    def _reset(self) -> None:
        self.fx.reset()
        self.fy.reset()
        self.down = False
        self.streak = 0

    def update(self, t: float, hand: dict | None) -> list[dict]:
        events: list[dict] = []
        if hand is None:
            self.missed += 1
            if self.visible and self.missed >= self.lost_frames:
                if self.down:
                    events.append({"type": "pen", "s": "up", "x": self.last[0], "y": self.last[1]})
                events.append({"type": "pen", "s": "gone", "x": 0.0, "y": 0.0})
                self.visible = False
                self._reset()
            return events

        self.missed = 0
        self.visible = True
        ratio = hand["pinch"]
        # The pointer slides from the fingertip to the pinch point as the fingers close, so it doesn't jump.
        a = max(0.0, min(1.0, 1.0 - (ratio - self.on) / 0.6))
        px = hand["x"] + (hand["mid"][0] - hand["x"]) * a
        py = hand["y"] + (hand["mid"][1] - hand["y"]) * a
        bx, by = self.to_board(px, py)
        x, y = self.fx(t, bx), self.fy(t, by)
        self.last = (x, y)

        wants_down = ratio < self.on if not self.down else ratio < self.off
        self.streak = self.streak + 1 if wants_down != self.down else 0
        if self.streak >= self.frames:
            self.down = wants_down
            self.streak = 0
            events.append({"type": "pen", "s": "down" if self.down else "up", "x": x, "y": y})
        elif self.down:
            events.append({"type": "pen", "s": "move", "x": x, "y": y})
        if not self.down:
            closeness = max(0.0, min(1.0, 1.0 - (ratio - self.on) / (self.off + 0.3 - self.on)))
            events.append({"type": "pen", "s": "hover", "x": x, "y": y, "dwell": round(closeness, 2)})
        return events
