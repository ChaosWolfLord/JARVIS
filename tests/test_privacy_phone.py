"""The privacy screen switches JARVIS off: the microphone closes, and the unlock code is typed in the phone app (not at the wall, not by voice)."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import phone, privacy, wakeword  # noqa: E402
from tests.test_phone import call, free_port  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


class WallOrPhone(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patch in (mock.patch.object(privacy, "FILE", Path(tmp.name) / "privacy.json"), mock.patch.object(privacy, "phone_ready", lambda: self.paired)):
            patch.start()
            self.addCleanup(patch.stop)
        self.paired = True
        privacy.set_code("5147")
        privacy.lock()

    def test_the_wall_is_refused_while_a_phone_is_paired(self):
        self.assertFalse(privacy.status()["wall_unlock"])
        self.assertEqual(privacy.unlock("5147"), (False, 0))
        self.assertTrue(privacy.locked())

    def test_the_phone_can_unlock_with_the_right_code(self):
        self.assertEqual(privacy.unlock("0000", via="phone")[0], False)
        self.assertEqual(privacy.unlock("5147", via="phone"), (True, 0))
        self.assertFalse(privacy.locked())

    def test_wrong_guesses_from_the_phone_are_slowed_down_too(self):
        for _ in range(5):
            ok, wait = privacy.unlock("0000", 1000.0, via="phone")
        self.assertEqual((ok, wait), (False, 30))
        self.assertEqual(privacy.unlock("5147", 1001.0, via="phone")[0], False)          # even the right code waits

    def test_a_refused_wall_attempt_is_not_a_wrong_guess(self):
        for _ in range(10):
            privacy.unlock("0000", 1000.0)
        self.assertEqual(privacy.unlock("5147", 1000.0, via="phone"), (True, 0))

    def test_without_a_paired_phone_the_wall_keypad_still_works(self):
        self.paired = False
        self.assertTrue(privacy.status()["wall_unlock"])
        self.assertEqual(privacy.unlock("5147"), (True, 0))

    def test_the_choice_can_be_switched_off_and_is_remembered(self):
        privacy.set_phone_only(False)
        self.assertTrue(privacy.status()["wall_unlock"])
        self.assertFalse(privacy.status()["phone_only"])
        self.assertEqual(privacy.unlock("5147"), (True, 0))

    def test_with_no_code_it_is_only_a_curtain_and_the_wall_unlocks(self):
        privacy.unlock("5147", via="phone")
        privacy.set_code(None, "5147")
        privacy.lock()
        self.assertTrue(privacy.status()["wall_unlock"])
        self.assertEqual(privacy.unlock(""), (True, 0))


class Microphone(unittest.TestCase):
    def test_the_pcs_microphone_closes_whatever_the_pages_say(self):
        locked = [False]
        w = wakeword.WakeWord(lambda: None, blocked=lambda: locked[0])
        w.vote("page", True)
        self.assertTrue(w.wanted())
        locked[0] = True
        self.assertFalse(w.wanted())
        self.assertFalse(w.listen_for_reply())
        locked[0] = False
        self.assertTrue(w.wanted())

    def test_an_unreadable_privacy_state_keeps_it_closed(self):
        def broken():
            raise OSError("no")
        w = wakeword.WakeWord(lambda: None, blocked=broken)
        w.vote("page", True)
        self.assertFalse(w.wanted())

    def test_the_server_gives_the_wake_word_the_privacy_state(self):
        main = (ROOT / "server" / "main.py").read_text(encoding="utf-8")
        self.assertIn("blocked=privacy.locked", main)


class PhoneDoor(unittest.TestCase):
    """The real phone server with the real privacy state."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.patch = mock.patch.object(privacy, "FILE", cls.dir / "privacy.json")
        cls.patch.start()

        class Door:
            def status(self):
                return privacy.status()

            def lock(self):
                privacy.lock()
                return privacy.status()

            def unlock(self, code):
                ok, wait = privacy.unlock(code, via="phone")
                return {**privacy.status(), "ok": ok, "wait": wait}

        cls.port = free_port()
        cls.service = phone.PhoneService(phone.Phones(cls.dir / "phones.json"))
        cls.service.start(lambda *a, **k: iter(()), lambda e: None, privacy.locked, port=cls.port, tls=False, host="127.0.0.1", privacy_door=Door())
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
        cls.patch.stop()

    def test_lock_from_the_phone_then_unlock_with_the_code(self):
        privacy.set_code("5147")
        status, body, _ = call(f"{self.base}/privacy/lock", {}, self.token, "POST")
        self.assertEqual((status, json.loads(body)["locked"]), (200, True))
        self.assertEqual(call(f"{self.base}/ping", token=self.token)[0], 200)             # the phone can still see that it is locked
        self.assertTrue(json.loads(call(f"{self.base}/privacy", token=self.token)[1])["locked"])
        status, body, _ = call(f"{self.base}/privacy/unlock", {"code": "0000"}, self.token, "POST")
        self.assertEqual((status, json.loads(body)["ok"]), (200, False))
        self.assertTrue(privacy.locked())
        status, body, _ = call(f"{self.base}/privacy/unlock", {"code": "5147"}, self.token, "POST")
        self.assertEqual((status, json.loads(body)["ok"]), (200, True))
        self.assertFalse(privacy.locked())

    def test_too_many_wrong_codes_answer_429(self):
        privacy.set_code("5147")
        privacy.lock()
        codes = [call(f"{self.base}/privacy/unlock", {"code": "0000"}, self.token, "POST")[0] for _ in range(6)]
        self.assertEqual(codes[-1], 429)
        privacy.unlock("5147", time.time() + 10_000, via="phone")                  # clean up

    def test_a_stranger_cannot_unlock_or_lock(self):
        privacy.set_code("5147")
        privacy.lock()
        for path in ("/privacy/unlock", "/privacy/lock"):
            self.assertIn(call(self.base + path, {"code": "5147"}, None, "POST")[0], (0, 401))
            self.assertEqual(call(self.base + path, {"code": "5147"}, "made-up", "POST")[0], 401)
        self.assertEqual(call(f"{self.base}/privacy")[0], 401)
        self.assertTrue(privacy.locked())
        privacy.unlock("5147", via="phone")


class Pages(unittest.TestCase):
    def test_the_wall_never_takes_the_code_by_voice(self):
        js = (ROOT / "web" / "privacy.js").read_text(encoding="utf-8")
        self.assertNotIn("UNLOCK", js)
        self.assertNotIn("spokenDigits(m", js)

    def test_the_wall_page_stops_listening_while_locked(self):
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("voice.pauseForPrivacy()", app)
        self.assertIn("voice.resumeIfPaused()", app)
        voice = (ROOT / "web" / "voice.js").read_text(encoding="utf-8")
        self.assertIn("window.jarvis?.privacy?.locked", voice)
        vision = (ROOT / "web" / "vision.js").read_text(encoding="utf-8")
        self.assertIn("globalThis.jarvis?.privacy?.locked", vision)

    def test_the_phone_page_has_the_lock_screen(self):
        html = (ROOT / "web" / "phone" / "phone.html").read_text(encoding="utf-8")
        js = (ROOT / "web" / "phone" / "phone.js").read_text(encoding="utf-8")
        for ident in ('id="lock"', 'id="lock-keys"', 'id="lock-now"'):
            self.assertIn(ident, html)
        for needle in ("'/privacy/unlock'", "'/privacy/lock'", "res.status === 423", "stopListening()"):
            self.assertIn(needle, js)


if __name__ == "__main__":
    unittest.main()
