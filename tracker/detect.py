"""Finding the pen's light in a grey camera frame, smoothing it, and deciding when the pen is down."""
from __future__ import annotations

import math
from typing import Callable

import cv2
import numpy as np


def find_blob(gray: np.ndarray, min_peak: float | None = None, min_area: int = 2,
              max_area: int = 800, frac: float = 0.5) -> dict | None:
    """Brightest small spot in the frame, or None.

    The frame's slowly varying glow (a lit wall, sensor shading) is subtracted first, so only a compact
    bright spot stands out. Returns {x, y, peak, area} with x, y at sub-pixel precision.
    min_peak is how far above the local background the spot must be; left as None it is set from the
    frame's own noise.
    """
    g = cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    d = g - cv2.GaussianBlur(g, (0, 0), 12)
    if min_peak is None:
        noise = 1.4826 * float(np.median(np.abs(d - np.median(d))))
        min_peak = max(3.0, 8.0 * noise)
    if float(d.max()) < min_peak:
        return None

    # Each candidate spot is judged on its own, so a big bright patch elsewhere (a hand, a shirt) can't
    # raise the bar and hide a smaller, fainter pen.
    low = 0.5 * min_peak
    count, labels, stats, _ = cv2.connectedComponentsWithStats((d >= low).astype(np.uint8), connectivity=8)
    best, best_score = None, 0.0
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] < min_area or stats[i, cv2.CC_STAT_AREA] > max_area * 8:
            continue
        sel = labels == i
        comp_peak = float(d[sel].max())
        if comp_peak < min_peak:
            continue
        core = sel & (d >= frac * comp_peak)  # the bright core, without the dim halo around it
        area = int(core.sum())
        if area < min_area or area > max_area:
            continue
        score = float(d[core].sum())
        if score > best_score:
            best, best_score = core, score
    if best is None:
        return None

    ys, xs = np.nonzero(best)
    w = np.clip(d[ys, xs], 1e-3, None)
    return {
        "x": float((xs * w).sum() / w.sum()),
        "y": float((ys * w).sum() / w.sum()),
        "peak": float(d[best].max()),
        "area": int(len(xs)),
    }


class OneEuro:
    """One Euro filter: steady when the pen is still, quick to follow when it moves."""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.01, d_cutoff: float = 1.0) -> None:
        self.min_cutoff, self.beta, self.d_cutoff = min_cutoff, beta, d_cutoff
        self.reset()

    def reset(self) -> None:
        self.t = self.x = self.dx = None

    @staticmethod
    def _alpha(cutoff: float, dt: float) -> float:
        tau = 1.0 / (2 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, t: float, x: float) -> float:
        if self.t is None:
            self.t, self.x, self.dx, self.raw = t, x, 0.0, x
            return x
        dt = max(t - self.t, 1e-3)
        dx = (x - self.raw) / dt
        self.dx += self._alpha(self.d_cutoff, dt) * (dx - self.dx)
        cutoff = self.min_cutoff + self.beta * abs(self.dx)
        self.x += self._alpha(cutoff, dt) * (x - self.x)
        self.t, self.raw = t, x
        return self.x


class PenTracker:
    """Turns a stream of blob-or-nothing into pen events: down, move, up.

    The pen's LED is on only while its tip is pressed, so "light seen" means "pen down". A couple of frames
    are required before a stroke starts, and a few empty frames before it ends, so noise and one dropped
    frame don't make stray dots or broken lines.
    """

    def __init__(self, to_board: Callable[[float, float], tuple[float, float]], down_frames: int = 2,
                 up_frames: int = 3, min_cutoff: float = 1.5, beta: float = 0.004) -> None:
        self.to_board = to_board
        self.down_frames, self.up_frames = down_frames, up_frames
        self.fx = OneEuro(min_cutoff, beta)
        self.fy = OneEuro(min_cutoff, beta)
        self.state = "up"
        self.seen = self.missed = 0
        self.pending: list[tuple[float, float, float]] = []
        self.last: tuple[float, float] | None = None

    def _filtered(self, t: float, x: float, y: float) -> tuple[float, float]:
        return self.fx(t, x), self.fy(t, y)

    def update(self, t: float, blob: dict | None) -> list[dict]:
        events: list[dict] = []
        if blob is not None:
            self.missed = 0
            self.seen += 1
            x, y = self.to_board(blob["x"], blob["y"])
            if self.state == "up":
                self.pending.append((t, x, y))
                if self.seen >= self.down_frames:
                    self.state = "down"
                    for n, (pt, px, py) in enumerate(self.pending):
                        fx, fy = self._filtered(pt, px, py)
                        events.append({"type": "pen", "s": "down" if n == 0 else "move", "x": fx, "y": fy})
                        self.last = (fx, fy)
                    self.pending = []
            else:
                fx, fy = self._filtered(t, x, y)
                events.append({"type": "pen", "s": "move", "x": fx, "y": fy})
                self.last = (fx, fy)
        else:
            if self.state == "down":
                self.missed += 1
                if self.missed >= self.up_frames:
                    events.append({"type": "pen", "s": "up", "x": self.last[0], "y": self.last[1]})
                    self.state = "up"
                    self.seen = 0
                    self.fx.reset()
                    self.fy.reset()
            else:
                self.seen = 0
                self.pending = []
        return events
