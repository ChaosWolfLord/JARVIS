"""Unit tests for the pen tracker's logic. Run from the project folder:  python -m unittest discover tests"""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker import calib  # noqa: E402
from tracker.detect import OneEuro, PenTracker, find_blob  # noqa: E402
from tracker.sources import Simulated  # noqa: E402


def frame_with(pos, amp=40.0, noise=1.0, seed=0, size=(340, 340)):
    return Simulated(lambda t: pos, size=size, noise=noise, amp=amp, seed=seed).render(pos)


class FindBlob(unittest.TestCase):
    def test_subpixel_accuracy(self):
        rng = np.random.default_rng(5)
        for amp in (40.0, 15.0):
            errs = []
            for i in range(60):
                x, y = rng.uniform(20, 320, 2)
                blob = find_blob(frame_with((x, y), amp=amp, seed=i))
                self.assertIsNotNone(blob, f"missed a pen of brightness {amp} at {x:.0f},{y:.0f}")
                errs.append(math.hypot(blob["x"] - x, blob["y"] - y))
            self.assertLess(float(np.mean(errs)), 0.4, f"mean error with amp {amp}")
            self.assertLess(max(errs), 1.5)

    def test_noise_alone_is_not_a_pen(self):
        hits = sum(find_blob(frame_with(None, seed=i)) is not None for i in range(200))
        self.assertEqual(hits, 0)

    def test_big_bright_area_and_gradients_are_ignored(self):
        f = frame_with((250, 90), amp=30).astype(np.float32)
        f[150:230, 40:130] += 90          # a big reflective patch (a hand, a shirt)
        f += np.linspace(0, 40, 340)[None, :]  # a wall glow that brightens to the right
        blob = find_blob(np.clip(f, 0, 255).astype(np.uint8))
        self.assertIsNotNone(blob)
        self.assertLess(math.hypot(blob["x"] - 250, blob["y"] - 90), 1.5)

    def test_faint_spot_below_threshold_is_rejected(self):
        self.assertIsNone(find_blob(frame_with((100, 100), amp=1.5)))


class Smoothing(unittest.TestCase):
    def test_steady_pen_jitters_less_and_a_moving_pen_is_followed(self):
        rng = np.random.default_rng(2)
        f = OneEuro(1.5, 0.004)
        raw = 500 + rng.normal(0, 3, 300)
        out = [f(i / 30, v) for i, v in enumerate(raw)]
        self.assertLess(np.std(out[30:]), 0.5 * np.std(raw[30:]))
        f = OneEuro(1.5, 0.004)
        ramp = [f(i / 30, 20 * i) for i in range(60)]   # 600 px per second
        self.assertLess(abs(ramp[-1] - 20 * 59), 60)


class PenStates(unittest.TestCase):
    def setUp(self):
        self.pen = PenTracker(lambda x, y: (x, y))

    def run_frames(self, seq):
        events = []
        for i, present in enumerate(seq):
            events += self.pen.update(i / 30, {"x": 100.0 + i, "y": 50.0} if present else None)
        return [e["s"] for e in events]

    def test_one_stray_frame_makes_nothing(self):
        self.assertEqual(self.run_frames([1, 0, 0, 0, 1, 0, 0]), [])

    def test_stroke_goes_down_moves_and_goes_up(self):
        s = self.run_frames([1, 1, 1, 1, 0, 0, 0])
        self.assertEqual(s[0], "down")
        self.assertEqual(s[-1], "up")
        self.assertEqual(s.count("down"), 1)
        self.assertEqual(s.count("up"), 1)

    def test_a_dropped_frame_does_not_break_the_line(self):
        s = self.run_frames([1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 0])
        self.assertEqual((s.count("down"), s.count("up")), (1, 1))

    def test_a_second_stroke_needs_its_own_confirmation(self):
        s = self.run_frames([1, 1, 1, 0, 0, 0, 1, 0, 0, 0])     # the lone frame after lifting is noise
        self.assertEqual((s.count("down"), s.count("up")), (1, 1))
        s = self.run_frames([1, 1, 0, 0, 0, 1, 1, 0, 0, 0])
        self.assertEqual(s.count("down"), 2)


def make_truth():
    """A camera that sees the board slightly rotated, keystoned and mirrored-free: board -> camera."""
    src = np.float32([[0, 0], [1920, 0], [1920, 1080], [0, 1080]])
    dst = np.float32([[40, 30], [300, 20], [320, 290], [25, 310]])
    import cv2
    return cv2.getPerspectiveTransform(src, dst)


class Calibration(unittest.TestCase):
    def setUp(self):
        import cv2
        self.cv2 = cv2
        self.board_to_cam = make_truth()
        self.cam_to_board = np.linalg.inv(self.board_to_cam)
        self.targets = [(fx * 1920, fy * 1080) for fy in (0.12, 0.5, 0.88) for fx in (0.1, 0.5, 0.9)]

    def cam_of(self, bx, by):
        p = self.board_to_cam @ np.array([bx, by, 1.0])
        return p[0] / p[2], p[1] / p[2]

    def touch(self, session, board_pt, frames=12, jitter=0.3, seed=0):
        rng = np.random.default_rng(seed)
        cx, cy = self.cam_of(*board_pt)
        events = []
        for _ in range(frames):
            events += session.update({"x": cx + rng.normal(0, jitter), "y": cy + rng.normal(0, jitter)})
        for _ in range(6):
            events += session.update(None)
        return events

    def test_nine_touches_give_an_accurate_map(self):
        s = calib.CalibrationSession(self.targets)
        events = []
        for i, pt in enumerate(self.targets):
            events += self.touch(s, pt, seed=i)
        done = [e for e in events if e["type"] == "calib_done"]
        self.assertEqual(len(done), 1)
        self.assertTrue(done[0]["ok"], done[0])
        self.assertLess(done[0]["rms"], 3.0)
        for bx, by in [(300, 200), (1500, 900), (960, 540)]:     # points that were never touched
            gx, gy = calib.apply(s.H, *self.cam_of(bx, by))
            self.assertLess(math.hypot(gx - bx, gy - by), 6.0)

    def test_one_badly_touched_target_is_ignored(self):
        s = calib.CalibrationSession(self.targets)
        for i, pt in enumerate(self.targets):
            wrong = (pt[0] + 400, pt[1] + 250) if i == 4 else pt   # the middle one lands far off
            self.touch(s, wrong, seed=i)
        self.assertTrue(s.finished)
        self.assertEqual(s.H is not None, True)
        gx, gy = calib.apply(s.H, *self.cam_of(1500, 900))
        self.assertLess(math.hypot(gx - 1500, gy - 900), 8.0)

    def test_a_moving_pen_does_not_count_as_a_touch(self):
        s = calib.CalibrationSession(self.targets)
        for i in range(30):
            s.update({"x": 50.0 + 5 * i, "y": 100.0})            # sweeping across, never still
        self.assertEqual(s.cam_points, [])

    def test_one_long_touch_is_not_counted_twice(self):
        s = calib.CalibrationSession(self.targets)
        cx, cy = self.cam_of(*self.targets[0])
        for _ in range(60):
            s.update({"x": cx, "y": cy})
        self.assertEqual(len(s.cam_points), 1)


class WholeChain(unittest.TestCase):
    def test_a_drawn_circle_comes_out_as_a_circle_on_the_board(self):
        import cv2
        board_to_cam = make_truth()
        cam_to_board = np.linalg.inv(board_to_cam)

        def to_board(x, y):
            return calib.apply(cam_to_board, x, y)

        def path(t):
            bx, by = 960 + 400 * math.cos(2 * math.pi * t / 2), 540 + 300 * math.sin(2 * math.pi * t / 2)
            p = board_to_cam @ np.array([bx, by, 1.0])
            return p[0] / p[2], p[1] / p[2]

        pen = PenTracker(to_board)
        got = []
        for t, frame, _ in Simulated(path, seconds=2.0, seed=3).frames():
            got += pen.update(t, find_blob(frame))
        self.assertEqual(got[0]["s"], "down")
        pts = [(e["x"], e["y"]) for e in got]
        radii = [math.hypot((x - 960) / 400, (y - 540) / 300) for x, y in pts]
        self.assertGreater(len(pts), 50)
        self.assertLess(abs(float(np.mean(radii)) - 1.0), 0.03)   # smoothing pulls corners in a little


if __name__ == "__main__":
    unittest.main()
