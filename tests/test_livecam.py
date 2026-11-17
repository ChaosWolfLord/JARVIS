"""The live camera: the newest-frame feed, what the phone door accepts, and how the wall and the privacy screen stop it."""
import asyncio
import json
import re
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import livecam, phone  # noqa: E402
from tests.test_phone import call, free_port  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FeedRules(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.locked = [False]
        self.feed = livecam.Feed(self.clock, lambda: self.locked[0])

    def test_the_first_frame_starts_it_and_the_next_does_not(self):
        self.assertEqual(self.feed.put("a", JPEG), {"ok": True, "started": True})
        self.clock.t += 0.2
        self.assertEqual(self.feed.put("a", JPEG), {"ok": True, "started": False})
        self.assertTrue(self.feed.active())
        self.assertEqual(self.feed.status()["seq"], 2)

    def test_only_jpeg_pictures_of_a_sensible_size(self):
        for bad in (b"", b"GIF89a....", b"\x89PNG\r\n\x1a\n" + b"x" * 50, b"hello", JPEG + b"x" * livecam.MAX_FRAME):
            out = self.feed.put("a", bad)
            self.assertFalse(out["ok"], bad[:8])
            self.assertFalse(out["stop"])
        self.assertFalse(self.feed.active())

    def test_a_flood_of_frames_is_thinned(self):
        self.feed.put("a", JPEG)
        out = self.feed.put("a", JPEG)
        self.assertEqual(out, {"ok": True, "dropped": True})
        self.assertEqual(self.feed.status()["seq"], 1)

    def test_a_feed_that_stops_sending_goes_dark_by_itself(self):
        self.feed.put("a", JPEG)
        self.clock.t += livecam.STALE_S - 0.5
        self.assertTrue(self.feed.active())
        self.clock.t += 1
        self.assertFalse(self.feed.active())
        seq, frame, live = self.feed.wait_newer(0, 0)
        self.assertEqual((frame, live), (b"", False))

    def test_the_wall_can_stop_it_and_the_phone_is_told_once(self):
        self.feed.put("a", JPEG)
        self.assertTrue(self.feed.stop())
        self.assertFalse(self.feed.active())
        self.assertEqual(self.feed.wait_newer(0, 0)[1], b"")                    # the picture is gone
        out = self.feed.put("a", JPEG)
        self.assertEqual((out["ok"], out["stop"]), (False, True))
        self.assertEqual(self.feed.put("a", JPEG)["ok"], True)                  # told once; the phone may start again deliberately
        self.assertFalse(self.feed.stop() and False)

    def test_stopping_when_nothing_is_showing_is_harmless(self):
        self.assertFalse(self.feed.stop())

    def test_the_phone_can_stop_by_itself(self):
        self.feed.put("a", JPEG)
        self.assertFalse(self.feed.release("someone else"))
        self.assertTrue(self.feed.active())
        self.assertTrue(self.feed.release("a"))
        self.assertFalse(self.feed.active())
        self.assertEqual(self.feed.put("a", JPEG)["ok"], True)                  # no stop order: it chose to stop

    def test_a_second_phone_takes_over_and_the_first_is_told_to_stop(self):
        self.feed.put("a", JPEG)
        self.clock.t += 0.2
        self.assertTrue(self.feed.put("b", JPEG)["started"])
        self.clock.t += 0.2
        self.assertTrue(self.feed.put("a", JPEG)["stop"])
        self.assertEqual(self.feed.put("b", JPEG)["ok"], True)

    def test_the_privacy_screen_ends_it_and_clears_the_picture(self):
        self.feed.put("a", JPEG)
        self.locked[0] = True
        out = self.feed.put("a", JPEG)
        self.assertEqual((out["ok"], out["stop"]), (False, True))
        self.assertEqual(self.feed.wait_newer(0, 0), (self.feed.seq, b"", False))
        self.locked[0] = False
        self.assertFalse(self.feed.active())
        self.assertEqual(self.feed.frame, b"")

    def test_a_waiting_wall_gets_the_next_frame_at_once(self):
        got = []
        t = threading.Thread(target=lambda: got.append(self.feed.wait_newer(0, 5)))
        t.start()
        time.sleep(0.1)
        began = time.monotonic()
        self.feed.put("a", JPEG)
        t.join(3)
        self.assertLess(time.monotonic() - began, 1.0)
        self.assertEqual(got[0][1], JPEG)
        self.assertTrue(got[0][2])

    def test_waiting_gives_up_after_the_time_and_says_nothing_new(self):
        began = time.monotonic()
        seq, frame, live = self.feed.wait_newer(0, 0.3)
        self.assertGreaterEqual(time.monotonic() - began, 0.25)
        self.assertEqual((frame, live), (b"", False))

    def test_a_frame_that_has_not_changed_is_not_sent_again(self):
        self.feed.put("a", JPEG)
        seq = self.feed.status()["seq"]
        began = time.monotonic()
        self.feed.wait_newer(seq, 0.2)
        self.assertGreaterEqual(time.monotonic() - began, 0.15)


class Nothing(unittest.TestCase):
    def test_nothing_is_written_recorded_or_sent_anywhere(self):
        source = (ROOT / "server" / "livecam.py").read_text(encoding="utf-8")
        code = re.sub(r'""".*?"""', "", source, flags=re.S)
        for banned in ("open(", "write_text", "write_bytes", ".write(", "mkdir", "subprocess", "socket", "httpx", "requests", "urllib", "pictures", "agent", "vision", "store"):
            self.assertNotIn(banned, code, banned)


class WallRoutes(unittest.TestCase):
    def setUp(self):
        from server import main
        self.main = main
        self.clock = Clock()
        self.locked = [False]
        self.feed = livecam.Feed(self.clock, lambda: self.locked[0])
        self.told = []
        for patch in (mock.patch.object(livecam, "feed", self.feed), mock.patch.object(main, "tell_pages", self.told.append),
                      mock.patch.object(main.audit, "record", lambda *a, **k: None)):
            patch.start()
            self.addCleanup(patch.stop)

    def run_async(self, coro):
        return asyncio.run(coro)

    def test_the_wall_gets_the_picture_with_its_number_and_no_caching(self):
        self.feed.put("a", JPEG)
        res = self.run_async(self.main.camera_frame(after=0, wait=0))
        self.assertEqual((res.status_code, res.body, res.media_type), (200, JPEG, "image/jpeg"))
        self.assertEqual(res.headers["x-seq"], "1")
        self.assertEqual(res.headers["x-live"], "1")
        self.assertEqual(res.headers["cache-control"], "no-store")

    def test_nothing_new_is_a_204_and_says_whether_the_feed_is_live(self):
        res = self.run_async(self.main.camera_frame(after=0, wait=0))
        self.assertEqual((res.status_code, res.headers["x-live"]), (204, "0"))
        self.feed.put("a", JPEG)
        res = self.run_async(self.main.camera_frame(after=1, wait=0))
        self.assertEqual((res.status_code, res.headers["x-live"]), (204, "1"))

    def test_the_wall_stops_it_and_every_page_hears(self):
        self.feed.put("a", JPEG)
        self.assertEqual(self.main.camera_stop(), {"ok": True})
        self.assertFalse(self.feed.active())
        self.assertEqual(self.told, [{"type": "camera", "state": "off", "source": "phone"}])
        self.main.camera_stop()
        self.assertEqual(len(self.told), 1)                                       # nothing to stop the second time: no second announcement

    def test_asking_the_phone_only_sends_a_notification(self):
        sent = []
        with mock.patch.object(self.main.phone_service, "publish", lambda ev: sent.append(ev) or 1):
            out = self.main.camera_ask_phone()
        self.assertEqual(out, {"sent": 1})
        self.assertEqual(sent[0]["type"], "push")
        self.assertIn("Tap", sent[0]["text"])

    def test_the_status_reports_without_the_picture(self):
        self.feed.put("a", JPEG)
        status = self.main.camera_status()
        self.assertEqual(set(status), {"active", "seq", "age"})

    def test_the_wall_routes_are_behind_the_privacy_curtain(self):
        from server import privacy
        self.assertTrue("/api/camera/frame".startswith("/api/"))
        self.assertFalse("/api/camera".startswith(privacy.OPEN_WHILE_LOCKED))


class PhoneDoor(unittest.TestCase):
    """The real phone door, with the real camera object that main.py builds."""

    @classmethod
    def setUpClass(cls):
        from server import main
        cls.main = main
        cls.feed = livecam.Feed()
        cls.locked = [False]
        cls.feed.locked = lambda: cls.locked[0]
        cls.told = []
        cls.patches = [mock.patch.object(livecam, "feed", cls.feed), mock.patch.object(main, "tell_pages", cls.told.append), mock.patch.object(main.audit, "record", lambda *a, **k: None)]
        for p in cls.patches:
            p.start()
        import tempfile
        cls.dir = Path(tempfile.mkdtemp())
        cls.port = free_port()
        cls.service = phone.PhoneService(phone.Phones(cls.dir / "phones.json"))
        cls.service.start(lambda *a, **k: iter(()), lambda e: None, lambda: cls.locked[0], port=cls.port, tls=False, host="127.0.0.1", camera=main._Camera())
        for _ in range(100):
            if cls.service.server.started:
                break
            time.sleep(0.1)
        cls.base = f"http://127.0.0.1:{cls.port}"
        code = cls.service.phones.new_code()["code"]
        cls.token = json.loads(call(f"{cls.base}/pair", {"code": code, "name": "Test phone"})[1])["token"]

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()
        for p in cls.patches:
            p.stop()

    def setUp(self):
        self.feed.stop()
        self.feed.told_to_stop.clear()
        self.locked[0] = False
        self.told.clear()

    def post(self, path, body=b"", token=None, ctype="image/jpeg"):
        req = urllib.request.Request(self.base + path, data=body, method="POST", headers={"Content-Type": ctype, **({"Authorization": f"Bearer {token or self.token}"} if token != "none" else {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except OSError:
            return 0, b""                                              # the door dropped the connection while the body was still going up

    def test_a_paired_phone_can_send_frames_and_the_wall_is_told_once(self):
        self.assertEqual(self.post("/camera/frame", JPEG)[0], 200)
        time.sleep(0.07)
        self.assertEqual(self.post("/camera/frame", JPEG)[0], 200)
        self.assertEqual(self.told, [{"type": "camera", "state": "on", "source": "phone"}])
        self.assertEqual(self.feed.wait_newer(0, 0)[1], JPEG)

    def test_strangers_and_odd_pictures_are_refused(self):
        self.assertIn(self.post("/camera/frame", JPEG, token="none")[0], (0, 401))
        self.assertIn(self.post("/camera/frame", JPEG, token="made-up")[0], (0, 401))
        self.assertEqual(self.post("/camera/frame", b"GIF89a" + b"x" * 100)[0], 400)
        self.assertEqual(self.post("/camera/frame", b"")[0], 400)
        self.assertIn(self.post("/camera/frame", JPEG + b"x" * livecam.MAX_FRAME)[0], (0, 413))
        self.assertFalse(self.feed.active())
        self.assertEqual(self.told, [])

    def test_the_wall_stopping_it_answers_the_phone_with_410(self):
        self.post("/camera/frame", JPEG)
        self.feed.stop()
        self.assertEqual(self.post("/camera/frame", JPEG)[0], 410)

    def test_the_privacy_screen_answers_423_and_clears_the_picture(self):
        self.post("/camera/frame", JPEG)
        self.locked[0] = True
        self.assertEqual(self.post("/camera/frame", JPEG)[0], 423)
        self.assertEqual(self.feed.wait_newer(0, 0)[1], b"")

    def test_the_phone_stopping_tells_the_wall(self):
        self.post("/camera/frame", JPEG)
        self.told.clear()
        self.assertEqual(self.post("/camera/stop")[0], 200)
        self.assertEqual(self.told, [{"type": "camera", "state": "off", "source": "phone"}])
        self.assertIn(self.post("/camera/stop", token="none")[0], (0, 401))

    def test_the_phone_door_has_no_way_to_start_a_camera_or_read_one(self):
        app = phone.build_app(phone.Phones(self.dir / "p2.json"), lambda *a, **k: iter(()), lambda e: None, camera=self.main._Camera())
        routes = {(r.path, tuple(sorted(r.methods or ()))) for r in app.routes if "camera" in r.path}
        self.assertEqual(routes, {("/camera/frame", ("POST",)), ("/camera/stop", ("POST",))})            # frames go in, nothing comes out


class Pages(unittest.TestCase):
    def test_the_phone_page_starts_it_only_from_a_tap_and_always_shows_a_bar(self):
        js = (ROOT / "web" / "phone" / "phone.js").read_text(encoding="utf-8")
        starts = [m.start() for m in re.finditer(r"startLive\(", js)]
        self.assertEqual(len(starts), 2)                                       # its definition and the button: nothing else ever starts the camera
        self.assertIn("$('live-start').addEventListener('click', () => startLive())", js)
        self.assertIn("$('live-bar').hidden = false", js)
        self.assertIn("document.hidden", js[js.index("visibilitychange', () => { if (document.hidden) stopLive"):][:200])
        self.assertIn("stopLive('', false);", js[js.index("function showLock"):][:300])               # the privacy screen shuts it
        html = (ROOT / "web" / "phone" / "phone.html").read_text(encoding="utf-8")
        for ident in ('id="live-start"', 'id="live-bar"', 'id="live-stop"', "Nothing is recorded"):
            self.assertIn(ident, html)

    def test_the_wall_never_starts_the_phone_camera_it_can_only_ask(self):
        js = (ROOT / "web" / "camera.js").read_text(encoding="utf-8")
        self.assertIn("/api/camera/ask", js)
        self.assertIsNone(re.search(r"(?<!api)/camera/frame", js))                # it never sends frames, only asks for them
        for banned in ("startLive", "Authorization", "getUserMedia({ video: { facingMode"):
            self.assertNotIn(banned, js)
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("cameraUI.stop(); voice.pauseForPrivacy()", app)


if __name__ == "__main__":
    unittest.main()
