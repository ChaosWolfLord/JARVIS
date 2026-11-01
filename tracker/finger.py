"""Finger pointing with an ordinary colour camera: no pen, no laser, no wires. Rough on purpose.

The camera looks at the wall from behind you. Whatever moves into view and looks like skin is taken to be
your hand, and the point of it farthest from where the arm enters the picture is taken to be the fingertip.
A static background model removes things that merely look like skin (a beige wall, a wooden desk), and a
region of interest keeps your face and body out of it.

Accuracy is a few centimetres at best: the camera cannot tell how far the finger is from the wall, so the
cursor shifts if you hold your hand well in front of the wall. Good enough for pointing at big buttons.
"""
from __future__ import annotations

import math
from typing import Callable

import cv2
import numpy as np

from .detect import OneEuro


class FingerDetector:
    """Colour frame in, fingertip out: {x, y, area} in the original frame's pixels, or None."""

    def __init__(self, roi: tuple[float, float, float, float] = (0.0, 0.0, 1.0, 1.0), work_width: int = 480,
                 learn: float = 0.004, fg_thresh: int = 28, warmup: int = 30,
                 min_area: float = 0.004, max_area: float = 0.45) -> None:
        self.roi = roi                  # x0, y0, x1, y1 as fractions of the frame: only this part is searched
        self.work_width = work_width
        self.learn, self.fg_thresh, self.warmup = learn, fg_thresh, warmup
        self.min_area, self.max_area = min_area, max_area   # as fractions of the region of interest
        self.bg: np.ndarray | None = None
        self.frames = 0
        self.mask = None                # last mask, for the --view window

    @property
    def ready(self) -> bool:
        return self.frames >= self.warmup

    def detect(self, bgr: np.ndarray) -> dict | None:
        h, w = bgr.shape[:2]
        scale = self.work_width / w
        small = cv2.GaussianBlur(cv2.resize(bgr, (self.work_width, max(1, round(h * scale))), interpolation=cv2.INTER_AREA), (5, 5), 0)
        sh, sw = small.shape[:2]

        if self.bg is None:
            self.bg = small.astype(np.float32)
        diff = cv2.absdiff(small, cv2.convertScaleAbs(self.bg)).max(axis=2)
        # Learn the empty scene fast at first, then very slowly, so a hand that pauses isn't absorbed at once.
        cv2.accumulateWeighted(small, self.bg, 0.1 if self.frames < self.warmup else self.learn)
        self.frames += 1
        if not self.ready:
            return None

        ycc = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
        skin = cv2.inRange(ycc, (40, 133, 77), (255, 173, 127))
        mask = cv2.bitwise_and(skin, (diff > self.fg_thresh).astype(np.uint8) * 255)

        x0, y0, x1, y1 = (int(self.roi[0] * sw), int(self.roi[1] * sh), int(self.roi[2] * sw), int(self.roi[3] * sh))
        region = np.zeros_like(mask)
        region[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
        mask = cv2.morphologyEx(region, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        self.mask = mask

        roi_area = max(1, (x1 - x0) * (y1 - y0))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best, best_area = None, 0.0
        for c in contours:
            area = cv2.contourArea(c)
            if self.min_area * roi_area <= area <= self.max_area * roi_area and area > best_area:
                best, best_area = c, area
        if best is None:
            return None

        pts = best.reshape(-1, 2).astype(np.float32)
        # Where the arm comes in: contour points on the edge of the region. A floating hand uses its centre.
        edge = (pts[:, 0] <= x0 + 2) | (pts[:, 0] >= x1 - 3) | (pts[:, 1] <= y0 + 2) | (pts[:, 1] >= y1 - 3)
        if edge.any():
            base = pts[edge].mean(axis=0)
        else:
            m = cv2.moments(best)
            base = np.array([m["m10"] / m["m00"], m["m01"] / m["m00"]], dtype=np.float32)
        dist = np.hypot(pts[:, 0] - base[0], pts[:, 1] - base[1])
        far = dist >= 0.96 * dist.max()           # the cluster of points at the tip, not just one noisy pixel
        tip = pts[far].mean(axis=0)
        return {"x": float(tip[0] / scale), "y": float(tip[1] / scale), "area": float(best_area / scale ** 2),
                "base": (float(base[0] / scale), float(base[1] / scale))}


class FingerPointer:
    """Turns fingertip positions into pointer events.

    - hover: every frame the finger is seen, with `dwell` (0 to 1) showing how close it is to a tap.
    - tap: hold the fingertip still for `dwell_s` seconds and it taps there (down, then up a moment later).
      After a tap it must move away before it can tap again, so one long hold is one tap.
    - gone: the finger left the view.
    """

    def __init__(self, to_board: Callable[[float, float], tuple[float, float]], dwell_s: float = 0.8,
                 radius: float = 70.0, lost_frames: int = 6, tap_s: float = 0.12) -> None:
        self.to_board = to_board
        self.dwell_s, self.radius, self.lost_frames, self.tap_s = dwell_s, radius, lost_frames, tap_s
        self.fx, self.fy = OneEuro(0.8, 0.002), OneEuro(0.8, 0.002)
        self.anchor: tuple[float, float] | None = None
        self.anchor_t = 0.0
        self.armed = True
        self.tap_up_at: float | None = None
        self.tap_pos = (0.0, 0.0)
        self.missed = 0
        self.visible = False

    def _reset_filters(self) -> None:
        self.fx.reset()
        self.fy.reset()

    def update(self, t: float, tip: dict | None) -> list[dict]:
        events: list[dict] = []
        if self.tap_up_at is not None and t >= self.tap_up_at:
            events.append({"type": "pen", "s": "up", "x": self.tap_pos[0], "y": self.tap_pos[1]})
            self.tap_up_at = None

        if tip is None:
            self.missed += 1
            if self.visible and self.missed >= self.lost_frames:
                self.visible = False
                self.anchor = None
                self.armed = True
                self._reset_filters()
                if self.tap_up_at is not None:
                    events.append({"type": "pen", "s": "up", "x": self.tap_pos[0], "y": self.tap_pos[1]})
                    self.tap_up_at = None
                events.append({"type": "pen", "s": "gone", "x": 0.0, "y": 0.0})
            return events

        self.missed = 0
        self.visible = True
        bx, by = self.to_board(tip["x"], tip["y"])
        x, y = self.fx(t, bx), self.fy(t, by)

        if self.anchor is None or math.hypot(x - self.anchor[0], y - self.anchor[1]) > self.radius:
            self.anchor, self.anchor_t = (x, y), t     # moved: the hold starts again from here
            if not self.armed and math.hypot(x - self.tap_pos[0], y - self.tap_pos[1]) > 1.5 * self.radius:
                self.armed = True                       # far enough from the last tap to tap again
        progress = min(1.0, (t - self.anchor_t) / self.dwell_s) if self.armed else 0.0

        events.append({"type": "pen", "s": "hover", "x": x, "y": y, "dwell": round(progress, 2)})
        if self.armed and progress >= 1.0 and self.tap_up_at is None:
            self.armed = False
            self.tap_pos = self.anchor
            self.tap_up_at = t + self.tap_s
            events.append({"type": "pen", "s": "down", "x": self.anchor[0], "y": self.anchor[1]})
        return events
