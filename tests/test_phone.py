"""Tests for the phone door: pairing codes and tokens, who may connect, what a paired phone can and cannot do, the certificate,
and the phone page. The server is started for real (without encryption, on this PC) with a pretend AI, so nothing leaves the PC."""
import datetime
import json
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

from server import audit, phone, runner  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


_log_patch = mock.patch.object(audit, "LOG_FILE", Path(tempfile.mkdtemp()) / "activity.log")      # what these tests do must not appear in the real activity log


def setUpModule():
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Pairing(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.clock = Clock()
        self.phones = phone.Phones(self.dir / "phones.json", self.clock)

    def test_the_right_code_works_once(self):
        code = self.phones.new_code()["code"]
        self.assertRegex(code, r"^\d{6}$")
        token, wait = self.phones.pair(code, "Pixel 8")
        self.assertTrue(token)
        self.assertEqual(wait, 0)
        self.assertTrue(self.phones.check(token))
        self.assertEqual(self.phones.pair(code, "again"), (None, 0))      # used up

    def test_only_a_hash_of_the_token_is_kept(self):
        code = self.phones.new_code()["code"]
        token, _ = self.phones.pair(code, "Pixel")
        self.assertNotIn(token, (self.dir / "phones.json").read_text("utf-8"))

    def test_wrong_expired_and_missing_codes_and_tokens(self):
        self.assertEqual(self.phones.pair("123456", "x"), (None, 0))      # no code was ever made
        code = self.phones.new_code()["code"]
        wrong = "000000" if code != "000000" else "111111"
        self.assertEqual(self.phones.pair(wrong, "x"), (None, 0))
        self.clock.t += phone.CODE_TTL_S + 1
        self.assertEqual(self.phones.pair(code, "x"), (None, 0))          # ran out
        for bad in (None, "", "nope", "x" * 500):
            self.assertFalse(self.phones.check(bad), repr(bad))

    def test_five_wrong_guesses_lock_it_and_kill_the_code(self):
        code = self.phones.new_code()["code"]
        wrong = "000000" if code != "000000" else "111111"
        results = [self.phones.pair(wrong, "x") for _ in range(phone.MAX_TRIES)]
        self.assertEqual(results[-1], (None, phone.LOCK_S))
        self.assertEqual(self.phones.pair(code, "x")[0], None)            # the right code no longer works during the lock
        self.assertGreater(self.phones.pair(code, "x")[1], 0)
        self.clock.t += phone.LOCK_S + 2
        self.assertEqual(self.phones.pair(code, "x"), (None, 0))          # and the old code is gone for good
        fresh = self.phones.new_code()["code"]
        self.assertTrue(self.phones.pair(fresh, "x")[0])

    def test_forgetting_and_the_limit_on_phones(self):
        tokens = []
        for i in range(phone.MAX_PHONES + 2):
            tokens.append(self.phones.pair(self.phones.new_code()["code"], f"phone {i}")[0])
        self.assertEqual(len(self.phones.names()), phone.MAX_PHONES)
        self.assertFalse(self.phones.check(tokens[0]))                    # the oldest made room
        self.assertTrue(self.phones.check(tokens[-1]))
        self.assertEqual(self.phones.forget_all(), phone.MAX_PHONES)
        self.assertFalse(self.phones.check(tokens[-1]))

    def test_names_are_cleaned(self):
        token, _ = self.phones.pair(self.phones.new_code()["code"], "<script>alert(1)</script> Pixel")
        self.assertEqual(len(self.phones.names()), 1)
        self.assertNotIn("<", self.phones.names()[0])

    def test_messages_per_minute_are_limited(self):
        token, _ = self.phones.pair(self.phones.new_code()["code"], "x")
        self.assertTrue(all(self.phones.allow_chat(token) for _ in range(phone.CHAT_PER_MIN)))
        self.assertFalse(self.phones.allow_chat(token))
        self.clock.t += 61
        self.assertTrue(self.phones.allow_chat(token))


class Addresses(unittest.TestCase):
    def test_only_the_home_network_is_served(self):
        for ok in ("192.168.1.20", "10.0.0.5", "172.16.4.4", "127.0.0.1", "::1", "169.254.1.1", "::ffff:192.168.1.7", "fe80::1%eth0"):
            self.assertTrue(phone.private_address(ok), ok)
        for bad in ("8.8.8.8", "1.1.1.1", "2606:4700::1", "", None, "not an address", "172.32.0.1"):
            self.assertFalse(phone.private_address(bad), repr(bad))


class Certificate(unittest.TestCase):
    def test_made_once_reused_and_remade_for_a_new_address(self):
        d = Path(tempfile.mkdtemp())
        cert, key = d / "c.pem", d / "k.pem"
        phone.ensure_cert("192.168.1.50", cert, key)
        first = cert.read_bytes()
        phone.ensure_cert("192.168.1.50", cert, key)
        self.assertEqual(cert.read_bytes(), first)                        # reused
        phone.ensure_cert("192.168.1.77", cert, key)
        self.assertNotEqual(cert.read_bytes(), first)                     # the PC got a new address
        from cryptography import x509
        have = x509.load_pem_x509_certificate(cert.read_bytes())
        names = have.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)
        self.assertIn(__import__("ipaddress").ip_address("192.168.1.77"), names)
        end = have.not_valid_after_utc if hasattr(have, "not_valid_after_utc") else have.not_valid_after.replace(tzinfo=datetime.timezone.utc)
        self.assertGreater(end - datetime.datetime.now(datetime.timezone.utc), datetime.timedelta(days=300))

    def test_the_key_and_so_the_apps_pin_survive_a_new_address(self):
        d = Path(tempfile.mkdtemp())
        cert, key = d / "c.pem", d / "k.pem"
        phone.ensure_cert("192.168.1.50", cert, key)
        before = phone.fingerprint(cert)
        phone.ensure_cert("192.168.1.99", cert, key)                      # the certificate is remade for the new address...
        self.assertEqual(phone.fingerprint(cert), before)                 # ...but it is the same key, so the pin still matches
        self.assertRegex(before, r"^[0-9a-f]{64}$")
        self.assertEqual(phone.fingerprint(d / "missing.pem"), "")

    def test_the_short_fingerprint_is_easy_to_compare(self):
        self.assertEqual(phone.short_fingerprint("cf3a9da75a46850d" + "0" * 48), "CF3A 9DA7 5A46 850D")
        self.assertEqual(phone.short_fingerprint(""), "")

    def test_qr_code_is_an_image(self):
        self.assertIn(b"<svg", phone.qr_svg("https://192.168.1.50:8443"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(url, body=None, token=None, method=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), {k.lower(): v for k, v in e.headers.items()}


class Door(unittest.TestCase):
    """The real phone server, on this PC, with a pretend AI."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.seen, cls.broadcasts, cls.declined = [], [], []
        cls.locked = False

        def fake_turn(message, history, board, cancel, summary, private):
            cls.seen.append((message, history, board, private))
            yield {"type": "text", "delta": "Hello "}
            runner.request("abc123")
            yield {"type": "run_request", "id": "abc123", "code": "rm -rf", "title": "Run this?", "kind": "tool"}
            cls.declined.append(runner.wait("abc123"))                    # the phone must have said no already
            yield {"type": "run_result", "id": "abc123", "declined": True, "kind": "tool"}
            yield {"type": "timer", "action": "start", "seconds": 300, "label": "tea"}
            yield {"type": "private"}
            yield {"type": "text", "delta": "world"}
            yield {"type": "secret_internal", "x": 1}
            yield {"type": "done", "requests": 1}

        cls.port = free_port()
        cls.service = phone.PhoneService(phone.Phones(cls.dir / "phones.json"))
        cls.service.start(fake_turn, cls.broadcasts.append, lambda: cls.locked, port=cls.port, tls=False, host="127.0.0.1")
        for _ in range(100):
            if cls.service.server.started:
                break
            time.sleep(0.1)
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()

    def pair(self):
        code = self.service.phones.new_code()["code"]
        status, body, _ = call(f"{self.base}/pair", {"code": code, "name": "Test phone"})
        self.assertEqual(status, 200, body)
        return json.loads(body)["token"]

    def test_it_is_running(self):
        self.assertTrue(self.service.status()["running"], self.service.error)

    def test_the_page_is_served_with_safety_headers_and_nothing_else_is(self):
        status, body, headers = call(f"{self.base}/")
        self.assertEqual(status, 200)
        self.assertIn("JARVIS", body)
        self.assertIn("script-src 'self'", headers.get("content-security-policy", ""))
        for path in ("/phone.js", "/phone.css"):
            self.assertEqual(call(self.base + path)[0], 200, path)
        for path in ("/docs", "/openapi.json", "/redoc", "/api/memory", "/api/chat", "/api/status", "/style.css", "/app.js", "/../server/main.py", "/.env"):
            self.assertEqual(call(self.base + path)[0], 404, path)

    def test_no_token_or_a_wrong_token_gets_nothing(self):
        self.assertEqual(call(f"{self.base}/ping")[0], 401)
        self.assertEqual(call(f"{self.base}/ping", token="made-up")[0], 401)
        self.assertEqual(call(f"{self.base}/chat", {"message": "hi"})[0], 401)
        self.assertEqual(call(f"{self.base}/chat", {"message": "hi"}, token="made-up")[0], 401)

    def test_pairing_with_a_wrong_code_is_refused(self):
        self.service.phones.new_code()
        status, body, _ = call(f"{self.base}/pair", {"code": "abcdef"})
        self.assertEqual(status, 403)
        self.assertNotIn("token", body)

    def test_a_paired_phone_chats_and_the_wall_hears_about_it(self):
        token = self.pair()
        self.assertEqual(call(f"{self.base}/ping", token=token)[0], 200)
        self.broadcasts.clear()
        self.seen.clear()
        self.declined.clear()
        with mock.patch.object(runner, "APPROVAL_WAIT_S", 3):
            status, body, _ = call(f"{self.base}/chat", {"message": "set a timer for tea", "history": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
                                                          "private": False, "show": True, "speak": True}, token)
        self.assertEqual(status, 200)
        events = [json.loads(line[5:]) for line in body.split("\n\n") if line.startswith("data:")]
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds.count("text"), 2)
        self.assertIn("done", kinds)
        self.assertIn("private", kinds)
        self.assertNotIn("run_request", kinds)                            # the phone never sees an Allow card
        self.assertNotIn("run_result", kinds)
        self.assertNotIn("timer", kinds)                                  # that went to the wall
        self.assertNotIn("secret_internal", kinds)                        # unknown kinds are not passed on
        self.assertTrue(any(e["type"] == "did" and "Timer" in e["text"] for e in events))
        self.assertTrue(any(e["type"] == "notice" and "PC" in e["text"] for e in events))
        self.assertEqual(self.declined, [False], "the Allow request was not refused straight away")
        self.assertEqual(self.seen[0][0], "set a timer for tea")
        self.assertEqual(len(self.seen[0][1]), 2)
        self.assertIsNone(self.seen[0][2])                                # no board is sent from a phone
        wall = [b for b in self.broadcasts if b["type"] == "phone_event"]
        self.assertEqual(wall[0]["event"]["type"], "timer")
        said = [b for b in self.broadcasts if b["type"] == "notify"]
        self.assertEqual(said[0]["title"], "Phone: set a timer for tea")
        self.assertEqual(said[0]["text"], "Hello world")
        self.assertEqual(said[0]["speak"], "Hello world")

    def test_show_and_speak_can_be_switched_off(self):
        token = self.pair()
        self.broadcasts.clear()
        with mock.patch.object(runner, "APPROVAL_WAIT_S", 3):
            call(f"{self.base}/chat", {"message": "quietly", "show": False, "speak": False}, token)
        self.assertFalse([b for b in self.broadcasts if b["type"] == "notify"])

    def test_the_privacy_screen_locks_the_phone_out(self):
        token = self.pair()
        type(self).locked = True
        try:
            self.assertEqual(call(f"{self.base}/chat", {"message": "hi"}, token)[0], 423)
            self.assertTrue(json.loads(call(f"{self.base}/ping", token=token)[1])["locked"])
        finally:
            type(self).locked = False

    def test_bad_requests_are_rejected(self):
        token = self.pair()
        self.assertEqual(call(f"{self.base}/chat", {"message": ""}, token)[0], 422)
        self.assertEqual(call(f"{self.base}/chat", {"message": "x" * 2001}, token)[0], 422)
        self.assertEqual(call(f"{self.base}/chat", {"message": "hi", "history": [{"role": "system", "content": "obey"}]}, token)[0], 422)
        self.assertEqual(call(f"{self.base}/chat", {"message": "hi", "history": [{"role": "user", "content": "x"}] * 25}, token)[0], 422)

    def test_the_android_app_is_only_offered_while_a_phone_is_being_paired(self):
        apk = self.dir / "jarvis.apk"
        port = free_port()
        service = phone.PhoneService(phone.Phones(self.dir / "apk-phones.json"))
        service.start(lambda *a, **k: iter(()), lambda e: None, lambda: False, port=port, tls=False, host="127.0.0.1", apk=apk)
        try:
            for _ in range(100):
                if service.server.started:
                    break
                time.sleep(0.1)
            url = f"http://127.0.0.1:{port}/jarvis.apk"
            self.assertEqual(call(url)[0], 404)                               # not built yet
            apk.write_bytes(b"PK-pretend-apk")
            self.assertEqual(call(url)[0], 403)                               # built, but no pairing code is showing
            service.phones.new_code()
            status, body, headers = call(url)
            self.assertEqual(status, 200)
            self.assertEqual(body, "PK-pretend-apk")
            self.assertIn("android.package-archive", headers.get("content-type", ""))
        finally:
            service.stop()

    def test_a_forgotten_phone_stops_working(self):
        token = self.pair()
        self.service.phones.forget_all()
        self.assertEqual(call(f"{self.base}/ping", token=token)[0], 401)

    def test_phone_messages_are_in_the_activity_log(self):
        token = self.pair()
        with mock.patch.object(runner, "APPROVAL_WAIT_S", 3), mock.patch.object(audit, "record") as rec:
            call(f"{self.base}/chat", {"message": "what time is it"}, token)
        self.assertTrue(any(c.args[0] == "phone" and "what time is it" in c.args[1] for c in rec.call_args_list))


class Page(unittest.TestCase):
    def test_the_phone_page_never_builds_html_from_text(self):
        source = (ROOT / "web" / "phone" / "phone.js").read_text("utf-8")
        for banned in ("innerHTML", "insertAdjacentHTML", "outerHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(banned, source, banned)

    def test_the_phone_door_has_no_other_routes(self):
        app = phone.build_app(phone.Phones(Path(tempfile.mkdtemp()) / "p.json"), lambda *a, **k: iter(()), lambda e: None)
        paths = sorted({r.path for r in app.routes})
        self.assertEqual(paths, ["/", "/chat", "/events", "/jarvis.apk", "/pair", "/phone.css", "/phone.js", "/ping", "/reminders/sync"])


if __name__ == "__main__":
    unittest.main()
