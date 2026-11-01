"""Mapping camera pixels to whiteboard coordinates, and the touch-the-targets calibration routine."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

BOARD_W, BOARD_H = 1920, 1080
# Same folder the server keeps its throwaway state in: outside OneDrive, specific to this PC and camera.
STATE = Path(os.getenv("LOCALAPPDATA") or Path(__file__).resolve().parent.parent / "data") / "jarvis"
CALIB_FILE = STATE / "calibration.json"


def fit(cam_pts: list[tuple[float, float]], board_pts: list[tuple[float, float]],
        inlier_px: float = 25.0) -> tuple[np.ndarray, float, int]:
    """Homography camera -> board from touched targets. Returns (H, rms error in board px, outlier count).

    RANSAC lets one badly touched target be ignored instead of bending the whole map.
    """
    cam = np.asarray(cam_pts, dtype=np.float32)
    board = np.asarray(board_pts, dtype=np.float32)
    H, inliers = cv2.findHomography(cam, board, cv2.RANSAC, inlier_px)
    if H is None:
        raise ValueError("couldn't fit a mapping: the touched points don't form a usable layout")
    mapped = cv2.perspectiveTransform(cam.reshape(-1, 1, 2), H).reshape(-1, 2)
    ok = inliers.ravel().astype(bool)
    rms = float(np.sqrt(((mapped[ok] - board[ok]) ** 2).sum(axis=1).mean()))
    return H, rms, int((~ok).sum())


def apply(H: np.ndarray, x: float, y: float) -> tuple[float, float]:
    p = H @ np.array([x, y, 1.0])
    return float(p[0] / p[2]), float(p[1] / p[2])


def save(H: np.ndarray, rms: float, cam_pts, board_pts, source: str = "") -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    CALIB_FILE.write_text(json.dumps({
        "H": H.tolist(), "rms": rms, "source": source,
        "cam_points": [list(p) for p in cam_pts], "board_points": [list(p) for p in board_pts],
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=2), "utf-8")


def load(source: str = "") -> np.ndarray | None:
    try:
        data = json.loads(CALIB_FILE.read_text("utf-8"))
        if source and data.get("source") not in ("", source):
            return None  # made with a different camera: the mapping doesn't apply
        return np.array(data["H"], dtype=np.float64)
    except (FileNotFoundError, KeyError, ValueError):
        return None


class CalibrationSession:
    """Walks through the targets: for each, wait for the pen to be held still on it, record the camera position.

    The pen must be lifted between targets so one long touch isn't counted twice.
    """

    def __init__(self, board_points: list[tuple[float, float]], hold: int = 8, max_jitter: float = 2.5,
                 lift: int = 4, max_rms: float = 30.0) -> None:
        self.board_points = [tuple(p) for p in board_points]
        self.hold, self.max_jitter, self.lift, self.max_rms = hold, max_jitter, lift, max_rms
        self.index = 0
        self.samples: list[tuple[float, float]] = []
        self.cam_points: list[tuple[float, float]] = []
        self.must_lift = False
        self.missing = 0
        self.finished = False
        self.H: np.ndarray | None = None
        self.rms = 0.0

    def update(self, blob: dict | None) -> list[dict]:
        events: list[dict] = []
        if self.finished:
            return events

        if self.must_lift:  # wait until the pen has been away for a few frames
            self.missing = self.missing + 1 if blob is None else 0
            if self.missing >= self.lift:
                self.must_lift, self.missing = False, 0
            return events

        if blob is None:
            if self.samples:
                self.samples = []
                events.append({"type": "calib_state", "index": self.index, "progress": 0.0})
            return events

        pt = (blob["x"], blob["y"])
        if self.samples:
            cx = sum(p[0] for p in self.samples) / len(self.samples)
            cy = sum(p[1] for p in self.samples) / len(self.samples)
            if (pt[0] - cx) ** 2 + (pt[1] - cy) ** 2 > self.max_jitter ** 2:
                self.samples = []  # the pen moved: start the hold again from here
        self.samples.append(pt)
        events.append({"type": "calib_state", "index": self.index, "progress": len(self.samples) / self.hold})

        if len(self.samples) >= self.hold:
            cam = (sum(p[0] for p in self.samples) / len(self.samples),
                   sum(p[1] for p in self.samples) / len(self.samples))
            self.cam_points.append(cam)
            events.append({"type": "calib_point", "index": self.index, "cam": list(cam)})
            self.index += 1
            self.samples = []
            self.must_lift = True
            if self.index >= len(self.board_points):
                events.append(self._finish())
        return events

    def _finish(self) -> dict:
        self.finished = True
        try:
            self.H, self.rms, outliers = fit(self.cam_points, self.board_points)
        except ValueError as e:
            return {"type": "calib_done", "ok": False, "message": str(e)}
        ok = self.rms <= self.max_rms
        return {"type": "calib_done", "ok": ok, "rms": round(self.rms, 1), "outliers": outliers,
                "message": "" if ok else f"Error {self.rms:.0f} px is too large. Try again, holding the pen still on each target."}
