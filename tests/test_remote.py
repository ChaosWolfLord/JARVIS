"""The phone as a remote, and "find my phone": the remote is off until the PC switches it on, only a short fixed list of commands exists (no typing, no
Enter, no combinations), every size is capped, and a phone can never switch it on. Nothing here sends input to the real PC: a pretend backend records it."""
import json
import re
import socket
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import audit, phone, remote  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

_log_patch = mock.patch.object(audit, "LOG_FILE", Path(tempfile.mkdtemp()) / "activity.log")


def setUpModule():
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()


class Backend:
    """Records what would have been sent to Windows."""

    def __init__(self):
        self.sent = []

    def move(self, dx, dy):
        self.sent.append(("move", dx, dy))

    def click(self, button):
        self.sent.append(("click", button))

    def scroll(self, notches):
        self.sent.append(("scroll", notches))

    def key(self, vk, extended):
        self.sent.append(("key", vk, extended))


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Switch(unittest.TestCase):
    def setUp(self):
        self.clock, self.backend, self.logged = Clock(), Backend(), []
        self.remote = remote.Remote(self.backend, self.clock, self.logged.append)

    def test_it_is_off_until_switched_on_and_nothing_gets_through_while_off(self):
        self.assertFalse(self.remote.status()["armed"])
        with self.assertRaises(remote.NotArmed):
            self.remote.do({"do": "key", "key": "right"})
        self.assertEqual(self.backend.sent, [])

    def test_it_switches_itself_off_after_the_time_and_can_be_switched_off(self):
        self.remote.arm(30)
        self.assertEqual(self.remote.status()["seconds_left"], 1800)
        self.remote.do({"do": "key", "key": "right"})
        self.clock.t += 1801
        with self.assertRaises(remote.NotArmed):
            self.remote.do({"do": "key", "key": "right"})
        self.remote.arm(5)
        self.remote.disarm()
        with self.assertRaises(remote.NotArmed):
            self.remote.do({"do": "click", "button": "left"})
        self.assertEqual(len(self.backend.sent), 1)
        self.assertTrue(any("on for 30" in line for line in self.logged))
        self.assertTrue(any("off" in line for line in self.logged))

    def test_the_time_is_limited(self):
        for bad in (0, -5, 121, "soon", None):
            with self.assertRaises(remote.RemoteError, msg=str(bad)):
                self.remote.arm(bad)


class Commands(unittest.TestCase):
    def setUp(self):
        self.clock, self.backend = Clock(), Backend()
        self.remote = remote.Remote(self.backend, self.clock)
        self.remote.arm(30)

    def test_the_commands_work(self):
        self.remote.do({"do": "move", "dx": 12.4, "dy": -7})
        self.remote.do({"do": "click", "button": "right"})
        self.remote.do({"do": "scroll", "dy": 3})
        self.remote.do({"do": "key", "key": "right"})
        self.remote.do({"do": "key", "key": "f5"})
        self.remote.do({"do": "media", "key": "playpause"})
        self.assertEqual(self.backend.sent, [("move", 12, -7), ("click", "right"), ("scroll", 3), ("key", 0x27, True), ("key", 0x74, False), ("key", 0xB3, True)])

    def test_sizes_are_capped(self):
        self.remote.do({"do": "move", "dx": 99999, "dy": -99999})
        self.remote.do({"do": "scroll", "dy": 500})
        self.assertEqual(self.backend.sent, [("move", remote.MAX_MOVE, -remote.MAX_MOVE), ("scroll", remote.MAX_SCROLL)])

    def test_nothing_that_could_type_or_confirm_exists(self):
        for key in ("enter", "return", "space", "a", "tab", "delete", "win", "windows", "alt", "ctrl", "shift", "ctrl+c", "alt+f4", "f4", "backspace", "printscreen", ""):
            with self.assertRaises(remote.RemoteError, msg=key):
                self.remote.do({"do": "key", "key": key})
        for key in ("launch_app", "mail", "browser", "sleep", ""):
            with self.assertRaises(remote.RemoteError, msg=key):
                self.remote.do({"do": "media", "key": key})
        for what in ("type", "text", "run", "shell", "combo", "middle", ""):
            with self.assertRaises(remote.RemoteError, msg=what):
                self.remote.do({"do": what, "key": "a", "text": "x"})
        with self.assertRaises(remote.RemoteError):
            self.remote.do({"do": "click", "button": "middle"})
        self.assertEqual(self.backend.sent, [])
        self.assertEqual(set(remote.KEYS), {"left", "up", "right", "down", "pageup", "pagedown", "home", "end", "escape", "f5"})
        self.assertEqual(set(remote.MEDIA), {"playpause", "next", "prev", "volup", "voldown", "mute"})

    def test_a_flood_is_refused(self):
        for _ in range(remote.MAX_PER_SECOND):
            self.remote.do({"do": "move", "dx": 1})
        with self.assertRaises(remote.RemoteError):
            self.remote.do({"do": "move", "dx": 1})
        self.clock.t += 1.1
        self.remote.do({"do": "move", "dx": 1})

    def test_garbage_numbers_are_refused(self):
        with self.assertRaises(remote.RemoteError):
            self.remote.do({"do": "move", "dx": "lots"})


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def post(url, body, token=None):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST"), timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def get(url, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class FromThePhone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.backend = Backend()
        cls.remote = remote.Remote(cls.backend)
        cls.locked = False
        cls.port = free_port()
        cls.service = phone.PhoneService(phone.Phones(cls.dir / "phones.json"))
        cls.service.start(lambda *a: iter(()), lambda e: None, lambda: cls.locked, port=cls.port, tls=False, host="127.0.0.1", remote=cls.remote)
        for _ in range(100):
            if cls.service.server.started:
                break
            time.sleep(0.1)
        cls.base = f"http://127.0.0.1:{cls.port}"
        code = cls.service.phones.new_code()["code"]
        cls.token = json.loads(post(f"{cls.base}/pair", {"code": code, "name": "Test"})[1])["token"]

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()

    def setUp(self):
        self.backend.sent.clear()
        self.remote.disarm()
        type(self).locked = False

    def test_a_phone_cannot_use_it_while_it_is_off(self):
        status, body = post(f"{self.base}/remote", {"do": "key", "key": "right"}, self.token)
        self.assertEqual(status, 403)
        self.assertIn("Let my phone be a remote", body)
        self.assertEqual(self.backend.sent, [])

    def test_a_phone_cannot_switch_it_on(self):
        for path in ("/remote/arm", "/remote/on", "/arm", "/api/phone/remote"):
            self.assertEqual(post(f"{self.base}{path}", {"minutes": 60}, self.token)[0], 404, path)
        self.assertFalse(self.remote.status()["armed"])

    def test_it_works_when_the_pc_has_switched_it_on(self):
        self.remote.arm(10)
        self.assertEqual(post(f"{self.base}/remote", {"do": "key", "key": "left"}, self.token)[0], 200)
        self.assertEqual(post(f"{self.base}/remote", {"do": "move", "dx": 5, "dy": 6}, self.token)[0], 200)
        self.assertEqual(self.backend.sent, [("key", 0x25, True), ("move", 5, 6)])
        status, body = get(f"{self.base}/remote/status", self.token)
        self.assertTrue(json.loads(body)["armed"])

    def test_only_a_paired_phone_may_ask(self):
        self.remote.arm(10)
        self.assertEqual(post(f"{self.base}/remote", {"do": "key", "key": "left"})[0], 401)
        self.assertEqual(post(f"{self.base}/remote", {"do": "key", "key": "left"}, "made-up")[0], 401)
        self.assertEqual(get(f"{self.base}/remote/status")[0], 401)
        self.assertEqual(self.backend.sent, [])

    def test_bad_commands_are_refused_before_they_reach_the_pc(self):
        self.remote.arm(10)
        for body in ({"do": "key", "key": "enter"}, {"do": "type", "key": "a"}, {"do": "media", "key": "launch"}, {"do": "move", "dx": "x"}, {"do": "click", "button": "middle"}, {}):
            self.assertIn(post(f"{self.base}/remote", body, self.token)[0], (400, 422), str(body))
        self.assertEqual(self.backend.sent, [])

    def test_the_privacy_screen_locks_the_remote_too(self):
        self.remote.arm(10)
        type(self).locked = True
        self.assertEqual(post(f"{self.base}/remote", {"do": "key", "key": "left"}, self.token)[0], 423)
        self.assertEqual(self.backend.sent, [])


class Wiring(unittest.TestCase):
    def test_the_pc_routes_switch_the_remote_and_find_the_phone(self):
        main = (ROOT / "server" / "main.py").read_text("utf-8")
        for route in ('@app.get("/api/phone/remote")', '@app.post("/api/phone/remote")', '@app.delete("/api/phone/remote")', '@app.post("/api/phone/find")', '@app.delete("/api/phone/find")'):
            self.assertIn(route, main)
        self.assertIn('{"type": "find"}', main)
        self.assertIn('{"type": "find_stop"}', main)
        self.assertIn("remote_mod.remote.log", main)                        # switching it on and off is in the activity log

    def test_the_phone_door_only_lists_the_remote_routes_it_needs(self):
        text = (ROOT / "server" / "phone.py").read_text("utf-8")
        for route in ('@app.get("/remote/status")', '@app.post("/remote")'):
            self.assertIn(route, text)
        self.assertNotIn("remote.arm(", text)                               # nothing on the phone door can switch it on

    def test_the_pc_page_has_the_buttons_and_the_voice_command(self):
        html = (ROOT / "web" / "index.html").read_text("utf-8")
        link = (ROOT / "web" / "phonelink.js").read_text("utf-8")
        app = (ROOT / "web" / "app.js").read_text("utf-8")
        self.assertIn('id="phone-find"', html)
        self.assertIn('id="phone-remote"', html)
        self.assertIn("phoneLink.handleVoice", app)
        self.assertIn("minutes: 30", link)
        self.assertNotRegex(link, r"fetch\('/api/phone/remote'[^)]*minutes: (?!30)")

    def test_the_phone_page_sends_only_the_fixed_commands(self):
        js = (ROOT / "web" / "phone" / "phone.js").read_text("utf-8")
        html = (ROOT / "web" / "phone" / "phone.html").read_text("utf-8")
        sent = set(re.findall(r"remoteSend\(\{ do: '(\w+)'", js))
        self.assertLessEqual(sent, {"move", "scroll", "click", "key", "media"})
        keys = set(re.findall(r'data-key="(\w+)"', html))
        self.assertLessEqual(keys, set(remote.KEYS))
        media = set(re.findall(r'data-media="(\w+)"', html))
        self.assertLessEqual(media, set(remote.MEDIA))
        self.assertNotIn("'/remote/arm'", js)


if __name__ == "__main__":
    unittest.main()
