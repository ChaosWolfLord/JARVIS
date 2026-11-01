"""Tests for the camera-only finger pointer. Run:  python -m unittest discover tests"""
import math
import sys
import unittest
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker.finger import FingerDetector, FingerPointer  # noqa: E402
from tracker.sources import SKIN_BGR, WALL_BGR, SimulatedHand, demo_hand  # noqa: E402


def feed(det, hand, seconds, path):
    """Runs the detector over simulated frames; returns [(t, tip or None)] after the warm-up."""
    out = []
    for t, frame, _ in SimulatedHand(path, seconds=seconds, seed=2).frames():
        tip = det.detect(frame)
        out.append((t, tip))
    return out


class Skin(unittest.TestCase):
    def test_the_beige_wall_really_does_look_like_skin(self):
        """Why background subtraction matters: colour alone cannot tell this wall from a hand."""
        ycc = cv2.cvtColor(np.uint8([[WALL_BGR, SKIN_BGR]]), cv2.COLOR_BGR2YCrCb)[0]
        for cr, cb in ((int(ycc[0][1]), int(ycc[0][2])), (int(ycc[1][1]), int(ycc[1][2]))):
            self.assertTrue(133 <= cr <= 173 and 77 <= cb <= 127, (cr, cb))


class Detector(unittest.TestCase):
    def test_empty_scene_never_detects_anything_even_though_the_wall_looks_like_skin(self):
        det = FingerDetector()
        results = feed(det, None, 3.0, lambda t: None)
        self.assertEqual([r for _, r in results if r is not None], [])

    def test_finds_the_fingertip(self):
        det = FingerDetector()
        tips = []
        for t, frame, _ in SimulatedHand(lambda t: None if t < 1.5 else (400.0, 130.0), seconds=3.5, seed=3).frames():
            tip = det.detect(frame)
            if t > 2.2 and tip:
                tips.append(tip)
        self.assertGreater(len(tips), 20)
        err = [math.hypot(tp["x"] - 400, tp["y"] - 130) for tp in tips]
        self.assertLess(float(np.mean(err)), 8.0, f"mean error {np.mean(err):.1f}px")

    def test_tracks_a_moving_finger(self):
        det = FingerDetector()
        path = lambda t: None if t < 1.2 else (150 + 100 * (t - 1.2), 200 - 20 * (t - 1.2))
        errs = []
        for t, frame, _ in SimulatedHand(path, seconds=4.0, seed=4).frames():
            tip = det.detect(frame)
            truth = path(t)
            if truth and t > 1.6:
                self.assertIsNotNone(tip, f"lost the finger at t={t:.2f}")
                errs.append(math.hypot(tip["x"] - truth[0], tip["y"] - truth[1]))
        self.assertLess(float(np.mean(errs)), 14.0)

    def test_a_still_skin_coloured_object_that_was_always_there_is_ignored(self):
        det = FingerDetector()
        box = lambda frame: cv2.rectangle(frame, (400, 100), (520, 200), SKIN_BGR, -1)
        got = []
        for t, frame, _ in SimulatedHand(lambda t: None, seconds=3.0, seed=5).frames():
            got.append(det.detect(box(frame)))
        self.assertTrue(all(g is None for g in got))

    def test_the_region_of_interest_keeps_your_face_out(self):
        det = FingerDetector(roi=(0.0, 0.0, 0.5, 1.0))     # only the left half counts
        got = []
        for t, frame, _ in SimulatedHand(lambda t: None if t < 1.5 else (500.0, 140.0), seconds=3.5, seed=6).frames():
            got.append(det.detect(frame))
        self.assertTrue(all(g is None for g in got), "a hand in the right half should be ignored")


class Pointer(unittest.TestCase):
    def setUp(self):
        self.p = FingerPointer(lambda x, y: (x, y), dwell_s=0.8, radius=40, lost_frames=4)

    def run_track(self, track, dt=1 / 30):
        events = []
        for i, pos in enumerate(track):
            events += self.p.update(i * dt, None if pos is None else {"x": pos[0], "y": pos[1]})
        return events

    def kinds(self, events):
        return [e["s"] for e in events if e["s"] != "hover"]

    def test_moving_finger_hovers_but_never_taps(self):
        ev = self.run_track([(100 + 6 * i, 100) for i in range(60)])
        self.assertEqual(self.kinds(ev), [])
        self.assertTrue(all(e["s"] == "hover" for e in ev))

    def test_holding_still_taps_once(self):
        ev = self.run_track([(300, 200)] * 90)               # 3 s on one spot
        self.assertEqual(self.kinds(ev), ["down", "up"])
        down = next(e for e in ev if e["s"] == "down")
        self.assertLess(math.hypot(down["x"] - 300, down["y"] - 200), 5)

    def test_dwell_progress_climbs_to_one(self):
        ev = self.run_track([(300, 200)] * 40)
        prog = [e["dwell"] for e in ev if e["s"] == "hover"]
        self.assertEqual(prog[0], 0.0)
        until_tap = prog[:prog.index(1.0) + 1]               # after the tap the ring empties until it re-arms
        self.assertEqual(until_tap, sorted(until_tap))
        self.assertEqual(until_tap[-1], 1.0)
        self.assertTrue(all(p == 0.0 for p in prog[len(until_tap):]))

    def test_it_must_move_away_before_tapping_again(self):
        stay = [(300, 200)] * 60
        ev = self.run_track(stay + [(300 + 12 * i, 200) for i in range(1, 25)] + [(600, 200)] * 60)
        self.assertEqual(self.kinds(ev), ["down", "up", "down", "up"])

    def test_leaving_the_view_says_gone_and_resets(self):
        ev = self.run_track([(300, 200)] * 20 + [None] * 10)
        self.assertEqual(self.kinds(ev), ["gone"])
        ev2 = self.run_track([None] * 5)
        self.assertEqual(self.kinds(ev2), [])


class WholeChain(unittest.TestCase):
    def test_the_demo_hand_produces_hovers_and_exactly_one_tap_per_cycle(self):
        det = FingerDetector()
        ptr = FingerPointer(lambda x, y: (x / 640 * 1920, y / 360 * 1080))
        events = []
        for t, frame, _ in SimulatedHand(demo_hand, seconds=9.0, seed=7).frames():
            events += ptr.update(t, det.detect(frame))
        kinds = [e["s"] for e in events]
        self.assertGreater(kinds.count("hover"), 100)
        self.assertEqual(kinds.count("down"), 1)
        self.assertEqual(kinds.count("up"), 1)
        self.assertGreaterEqual(kinds.count("gone"), 1)
        down = next(e for e in events if e["s"] == "down")
        self.assertLess(math.hypot(down["x"] - 960, down["y"] - 450), 120)     # the hold was at (320, 150)


if __name__ == "__main__":
    unittest.main()
