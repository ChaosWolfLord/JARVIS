"""Tests for the MediaPipe hand pointer's logic (the pinch state machine) and that the model loads."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tracker import hands  # noqa: E402
from tracker.hands import PinchPointer  # noqa: E402


def hand(x, y, pinch, mid=None):
    return {"x": x, "y": y, "mid": mid or (x - 20, y + 10), "pinch": pinch, "size": 100.0}


class Pinch(unittest.TestCase):
    def setUp(self):
        self.p = PinchPointer(lambda x, y: (x, y))
        self.t = 0.0

    def feed(self, seq):
        events = []
        for h in seq:
            events += self.p.update(self.t, h)
            self.t += 1 / 30
        return events

    def kinds(self, events):
        return [e["s"] for e in events if e["s"] not in ("hover", "move")]

    def test_open_hand_just_hovers(self):
        ev = self.feed([hand(100 + 4 * i, 100, 0.9) for i in range(40)])
        self.assertEqual({e["s"] for e in ev}, {"hover"})

    def test_pinching_presses_and_releasing_lifts_once_each(self):
        seq = [hand(300, 200, 0.9)] * 5 + [hand(300, 200, 0.15)] * 20 + [hand(300, 200, 0.9)] * 6
        self.assertEqual(self.kinds(self.feed(seq)), ["down", "up"])

    def test_pinch_drags_with_moves(self):
        seq = [hand(300, 200, 0.9)] * 3 + [hand(300 + 10 * i, 200, 0.15) for i in range(25)] + [hand(550, 200, 0.9)] * 5
        ev = self.feed(seq)
        self.assertGreater(sum(e["s"] == "move" for e in ev), 15)
        down = next(e for e in ev if e["s"] == "down")
        up = next(e for e in ev if e["s"] == "up")
        self.assertGreater(up["x"] - down["x"], 150)

    def test_borderline_pinch_does_not_flicker(self):
        wobble = [hand(300, 200, 0.15)] * 6 + [hand(300, 200, 0.40 + 0.04 * ((-1) ** i)) for i in range(40)]
        self.assertEqual(self.kinds(self.feed(wobble)), ["down"])      # stays pressed: 0.36 to 0.44 is inside the gap

    def test_one_frame_blip_is_ignored(self):
        self.assertEqual(self.kinds(self.feed([hand(300, 200, 0.9)] * 4 + [hand(300, 200, 0.1)] + [hand(300, 200, 0.9)] * 4)), [])

    def test_losing_the_hand_mid_press_lifts_then_says_gone(self):
        seq = [hand(300, 200, 0.15)] * 8 + [None] * 10
        self.assertEqual(self.kinds(self.feed(seq)), ["down", "up", "gone"])

    def test_pointer_slides_from_fingertip_to_pinch_point(self):
        tip, mid = (500.0, 300.0), (480.0, 310.0)
        open_ev = self.feed([hand(*tip, 0.95, mid)] * 30)
        self.assertAlmostEqual(open_ev[-1]["x"], 500.0, delta=2)          # open: the fingertip itself
        p2 = PinchPointer(lambda x, y: (x, y))
        ev = [e for i in range(40) for e in p2.update(i / 30, hand(*tip, 0.15, mid))]
        self.assertAlmostEqual(ev[-1]["x"], 480.0, delta=2)               # pinched: the point between the fingers

    def test_ring_fills_as_fingers_close(self):
        ev = self.feed([hand(300, 200, r) for r in (0.95, 0.8, 0.65, 0.5, 0.4)])
        rings = [e["dwell"] for e in ev if e["s"] == "hover"]
        self.assertEqual(rings, sorted(rings))
        self.assertLess(rings[0], 0.1)
        self.assertGreater(rings[-1], 0.5)


class Windows(unittest.TestCase):
    def test_search_windows_cover_the_region_and_stay_inside_the_frame(self):
        W, H = 1920, 1080
        roi = (0.1, 0.1, 0.9, 0.8)
        wins = hands.search_windows(W, H, roi, 480)
        self.assertEqual(wins[0], (0, 0, W, H))                       # the whole frame goes first
        tiles = wins[1:]
        self.assertTrue(all(0 <= x0 < x1 <= W and 0 <= y0 < y1 <= H for x0, y0, x1, y1 in tiles))
        self.assertTrue(all(x1 - x0 == 480 and y1 - y0 == 480 for x0, y0, x1, y1 in tiles))
        for px in range(int(roi[0] * W), int(roi[2] * W), 40):        # every point of the region sits well inside some tile
            for py in range(int(roi[1] * H), int(roi[3] * H), 40):
                best = max(min(px - x0, x1 - px, py - y0, y1 - py) for x0, y0, x1, y1 in tiles)
                self.assertGreater(best, 40, f"({px},{py}) is only on the very edge of a window")

    def test_a_small_region_needs_only_a_few_tiles(self):
        self.assertLessEqual(len(hands.search_windows(1920, 1080, (0.4, 0.4, 0.6, 0.6), 480)), 4)

    def test_window_size_is_clamped_to_the_frame(self):
        wins = hands.search_windows(640, 360, (0, 0, 1, 1), 480)
        self.assertTrue(all(x1 <= 640 and y1 <= 360 for _, _, x1, y1 in wins))

    def test_follow_window_centres_on_the_hand_and_slides_inside_the_frame(self):
        self.assertEqual(hands.follow_window(960, 540, 480, 1920, 1080), (720, 300, 1200, 780))
        self.assertEqual(hands.follow_window(10, 10, 480, 1920, 1080), (0, 0, 480, 480))
        self.assertEqual(hands.follow_window(1915, 1075, 480, 1920, 1080), (1440, 600, 1920, 1080))
        self.assertEqual(hands.follow_window(500, 500, 2000, 1920, 1080), (0, 0, 1080, 1080))


class Prediction(unittest.TestCase):
    W, H = 1920, 1080

    def test_window_slides_with_the_hand_so_it_stays_put_inside_it(self):
        crop = (500, 300, 980, 780)
        nxt = hands.predicted_window(crop, (740, 540), (30, -10), self.W, self.H)
        self.assertEqual(nxt, (530, 290, 1010, 770))

    def test_a_still_hand_keeps_the_same_window(self):
        crop = (500, 300, 980, 780)
        self.assertEqual(hands.predicted_window(crop, (700, 500), (0, 0), self.W, self.H), crop)

    def test_window_recentres_only_when_the_hand_nears_its_edge(self):
        crop = (500, 300, 980, 780)
        nxt = hands.predicted_window(crop, (940, 540), (0, 0), self.W, self.H)      # 440 into a 480 window
        self.assertGreater(nxt[0], crop[0])
        self.assertGreaterEqual(940 - nxt[0], 0.25 * 480 - 1)
        self.assertLessEqual(940 - nxt[0], 0.75 * 480 + 1)

    def test_window_never_leaves_the_frame_or_changes_size(self):
        for centre, vel in [((20, 20), (-90, -90)), ((1900, 1060), (90, 90)), ((960, 540), (0, 0))]:
            nxt = hands.predicted_window((700, 400, 1180, 880), centre, vel, self.W, self.H)
            self.assertTrue(0 <= nxt[0] and nxt[2] <= self.W and 0 <= nxt[1] and nxt[3] <= self.H)
            self.assertEqual((nxt[2] - nxt[0], nxt[3] - nxt[1]), (480, 480))

    def test_whole_frame_window_stays_the_whole_frame(self):
        full = (0, 0, self.W, self.H)
        self.assertEqual(hands.predicted_window(full, (900, 500), (40, 20), self.W, self.H), full)


@unittest.skipUnless(hands.available(), "MediaPipe or its model file is not installed")
class Model(unittest.TestCase):
    def test_model_loads_and_finds_nobody_in_a_blank_frame(self):
        tracker = hands.HandTracker()
        try:
            for _ in range(5):
                self.assertIsNone(tracker.detect(np.full((360, 640, 3), 128, np.uint8)))
        finally:
            tracker.close()


if __name__ == "__main__":
    unittest.main()
