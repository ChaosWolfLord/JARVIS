"""Tests for the privacy screen: the code and its lockout, what the server refuses while locked, and state that survives."""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import privacy  # noqa: E402


class Code(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(privacy, "FILE", Path(tmp.name) / "privacy.json")
        patch.start()
        self.addCleanup(patch.stop)
        self.file = privacy.FILE

    def test_codes_must_be_four_to_eight_digits(self):
        for good in ("1234", "00000000", "5147"):
            self.assertTrue(privacy.valid_code(good), good)
        for bad in ("", "123", "123456789", "12a4", "1 234", "１２３４", None, 1234):
            self.assertFalse(privacy.valid_code(bad), bad)

    def test_the_code_is_stored_only_as_a_salted_hash(self):
        privacy.set_code("5147")
        raw = self.file.read_text()
        self.assertNotIn("5147", raw)
        first = json.loads(raw)
        privacy.set_code("5147", current="5147")
        self.assertNotEqual(json.loads(self.file.read_text())["salt"], first["salt"])      # a fresh salt each time
        self.assertTrue(privacy.has_code())

    def test_lock_then_the_right_code_unlocks(self):
        privacy.set_code("5147")
        privacy.lock()
        self.assertTrue(privacy.locked())
        self.assertEqual(privacy.unlock("5147"), (True, 0))
        self.assertFalse(privacy.locked())

    def test_a_wrong_code_keeps_it_locked(self):
        privacy.set_code("5147")
        privacy.lock()
        for bad in ("0000", "", "51470", "abcd", None):
            ok, _ = privacy.unlock(bad)
            self.assertFalse(ok, bad)
        self.assertTrue(privacy.locked())

    def test_five_wrong_tries_lock_you_out_for_longer_each_time(self):
        privacy.set_code("5147")
        privacy.lock()
        now = 1000.0
        for _ in range(5):
            ok, wait = privacy.unlock("0000", now)
        self.assertEqual((ok, wait), (False, 30))
        self.assertEqual(privacy.unlock("5147", now + 5)[0], False)              # even the right code waits out the lockout
        self.assertEqual(privacy.unlock("5147", now + 31), (True, 0))
        privacy.lock()
        for _ in range(5):
            ok, wait = privacy.unlock("0000", now + 100)
        self.assertEqual(wait, 30)                                              # unlocking reset the count
        for _ in range(5):
            privacy.unlock("0000", now + 200)
        self.assertEqual(privacy.status()["wait"] >= 0, True)

    def test_the_lockout_grows_when_it_keeps_happening(self):
        privacy.set_code("5147")
        privacy.lock()
        waits = []
        now = 5000.0
        for _ in range(4):
            for _ in range(5):
                _, wait = privacy.unlock("0000", now)
            waits.append(wait)
            now += wait + 1
        self.assertEqual(waits, [30, 60, 120, 240])

    def test_with_no_code_it_is_just_a_curtain(self):
        privacy.lock()
        self.assertEqual(privacy.status()["has_code"], False)
        self.assertEqual(privacy.unlock(None), (True, 0))

    def test_unlocking_when_not_locked_is_harmless(self):
        self.assertEqual(privacy.unlock("whatever"), (True, 0))

    def test_changing_or_removing_the_code_needs_the_current_one(self):
        self.assertTrue(privacy.set_code("1111"))
        self.assertFalse(privacy.set_code("2222", current="9999"))
        self.assertFalse(privacy.set_code(None, current=""))
        self.assertTrue(privacy.set_code("2222", current="1111"))
        self.assertFalse(privacy.set_code("12", current="2222"))                # too short
        self.assertTrue(privacy.set_code(None, current="2222"))
        self.assertFalse(privacy.has_code())

    def test_locked_state_survives_a_restart(self):
        privacy.lock()
        self.assertTrue(json.loads(self.file.read_text())["locked"])
        self.assertTrue(privacy.status()["locked"])


def call(app, path, kind="http"):
    sent = []
    inbox = [{"type": "http.request", "body": b""}]

    async def receive():
        return inbox.pop(0) if inbox else {"type": "http.disconnect"}

    async def send(m):
        sent.append(m)

    asyncio.run(app({"type": kind, "path": path, "headers": []}, receive, send))
    return sent


class Curtain(unittest.TestCase):
    def app(self, locked):
        reached = []

        async def inner(scope, receive, send):
            reached.append(scope["path"])
            if scope["type"] == "http":
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})

        return privacy.Curtain(inner, is_locked=lambda: locked), reached

    def test_while_locked_the_data_is_refused(self):
        app, reached = self.app(True)
        for path in ("/api/chat", "/api/memory", "/api/board", "/api/activity", "/api/usage", "/api/claude-usage", "/api/mcp", "/api/board/backups"):
            sent = call(app, path)
            self.assertEqual(sent[0]["status"], 423, path)
        self.assertEqual(reached, [])

    def test_while_locked_the_lock_screen_and_the_page_still_load(self):
        app, reached = self.app(True)
        for path in ("/api/privacy", "/api/privacy/unlock", "/api/status", "/", "/app.js", "/style.css"):
            self.assertEqual(call(app, path)[0]["status"], 200, path)

    def test_websockets_are_not_blocked_so_the_pen_can_press_the_keypad(self):
        app, reached = self.app(True)
        call(app, "/ws/pen", kind="websocket")
        self.assertEqual(reached, ["/ws/pen"])

    def test_when_unlocked_everything_passes(self):
        app, reached = self.app(False)
        for path in ("/api/chat", "/api/memory"):
            self.assertEqual(call(app, path)[0]["status"], 200)


if __name__ == "__main__":
    unittest.main()
