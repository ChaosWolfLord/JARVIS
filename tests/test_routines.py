"""Routines: a name that runs a list of steps you write. They are checked on the way in, run in order with one failure never stopping the rest, cannot start
each other, and are made only on the PC (the phone can list and run them). Nothing here touches real lights, music or apps."""
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

from server import audit, localcmd, phone, routines  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "routine_phrases.json").read_text("utf-8"))

_log_patch = mock.patch.object(audit, "LOG_FILE", Path(tempfile.mkdtemp()) / "activity.log")


def setUpModule():
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()


MOVIE = {"name": "Movie night", "phrases": ["film time", "start the movie"], "steps": ["dim the lights to 20 percent", "play some jazz", "set a timer for 2 hours", "say Enjoy the film"]}


class Words(unittest.TestCase):
    def test_the_shared_phrase_list(self):                              # the page is checked against the same list (tests/js/routines.mjs)
        for said, want in FIXTURE["normalize"]:
            self.assertEqual(routines.normalize(said), want, said)
        for said, want in FIXTURE["plain"]:
            self.assertEqual(routines.plain(said), want, said)

    def test_a_name_is_understood_in_many_ways_and_an_extra_phrase_only_as_written(self):
        saved = routines.clean([MOVIE, {"name": "Goodnight", "steps": ["lights off"]}])
        for yes in ("movie night", "Jarvis, start the movie night routine", "film time", "Jarvis, film time please", "start the movie", "goodnight", "activate goodnight mode"):
            self.assertIsNotNone(routines.match(yes, saved), yes)
        for no in ("movie", "night", "play a movie", "turn off the lights", "good night", "", "start film time", "film", "it's film time", "movie night tomorrow remind me"):
            self.assertIsNone(routines.match(no, saved), no)


class Saving(unittest.TestCase):
    def test_a_routine_is_tidied_and_given_an_id(self):
        out = routines.clean([{"name": "  Movie   night ", "phrases": ["Film time", "film   time", "movie night"], "steps": [" dim the lights ", "", "play jazz"]}])
        self.assertEqual(out[0]["name"], "Movie night")
        self.assertEqual(out[0]["phrases"], ["Film time"])                # the duplicate and the name itself are dropped
        self.assertEqual(out[0]["steps"], ["dim the lights", "play jazz"])
        self.assertRegex(out[0]["id"], r"^[a-z0-9]{6,16}$")
        again = routines.clean(out)
        self.assertEqual(again[0]["id"], out[0]["id"])                    # an id stays

    def test_mistakes_are_explained(self):
        bad = ([{"name": "", "steps": ["x"]}], [{"name": "Movie night", "steps": []}], [{"name": "ab", "steps": ["x"]}], [{"name": "Movie night", "phrases": ["go"], "steps": ["x"]}],
               [{"name": "Movie night", "steps": ["x"] * (routines.MAX_STEPS + 1)}], [{"name": "A name", "phrases": ["one phrase"] * 6 + ["two"], "steps": ["x"]}],
               [{"name": "Movie night", "steps": ["x"]}, {"name": "movie NIGHT", "steps": ["y"]}],
               [{"name": "Movie night", "steps": ["x"]}, {"name": "Date night", "phrases": ["movie night"], "steps": ["y"]}],
               [{"name": f"Name {i}", "steps": ["x"]} for i in range(routines.MAX_ROUTINES + 1)], "nope", [3])
        for items in bad:
            with self.assertRaises(routines.RoutineError, msg=str(items)[:60]):
                routines.clean(items)

    def test_save_and_load(self):
        config = Path(tempfile.mkdtemp()) / "routines.json"
        saved = routines.save([MOVIE], config)
        self.assertEqual(routines.load(config), saved)
        self.assertEqual(routines.load(Path(tempfile.mkdtemp()) / "missing.json"), [])
        config.write_text("not json", "utf-8")
        self.assertEqual(routines.load(config), [])


class Steps(unittest.TestCase):
    def test_what_a_step_means(self):
        self.assertEqual(routines.parse_step("set a timer for 90 minutes"), ("timer", 5400, ""))
        self.assertEqual(routines.parse_step("timer 20 minutes pasta"), ("timer", 1200, "pasta"))
        self.assertEqual(routines.parse_step("Set a timer for 30 seconds."), ("timer", 30, ""))
        self.assertEqual(routines.parse_step("wait 5 seconds"), ("wait", 5.0))
        self.assertEqual(routines.parse_step("wait 500 seconds"), ("wait", float(routines.MAX_WAIT_S)))
        self.assertEqual(routines.parse_step("say Enjoy the film"), ("say", "Enjoy the film"))
        self.assertEqual(routines.parse_step("note: buy milk"), ("note", "buy milk"))
        self.assertEqual(routines.parse_step("play some jazz"), ("command", "play some jazz"))
        with self.assertRaises(routines.RoutineError):
            routines.parse_step("set a timer for 99 hours")

    def run_it(self, steps, runner=None, tell=True):
        told, slept = [], []
        r = {"name": "Test", "steps": steps}
        out = routines.run(r, runner or (lambda s: {"handled": True, "ok": True, "text": "ok"}), told.append if tell else None, slept.append)
        return out, told, slept

    def test_steps_run_in_order_and_use_the_right_helpers(self):
        said = []
        out, told, slept = self.run_it(["dim the lights", "say Hello there", "note buy milk", "timer 10 minutes tea", "wait 2 seconds", "play jazz"],
                                       lambda s: (said.append(s), {"handled": True, "ok": True, "text": "ok"})[1])
        self.assertEqual(said, ["dim the lights", "play jazz"])
        self.assertEqual(slept, [2.0])
        self.assertEqual(out["done"], 6)
        self.assertEqual(out["text"], "Test: done.")
        kinds = [(e["type"], e.get("event", {}).get("type")) for e in told]
        self.assertEqual(kinds, [("notify", None), ("phone_event", "add_note"), ("phone_event", "timer")])
        self.assertEqual(told[2]["event"], {"type": "timer", "action": "start", "seconds": 600, "label": "tea"})
        self.assertEqual(told[0]["speak"], "Hello there")

    def test_a_failing_step_is_reported_and_the_rest_still_run(self):
        calls = []

        def runner(step):
            calls.append(step)
            if "lights" in step:
                return {"handled": True, "ok": False, "text": "The lights didn't answer."}
            if "spaceship" in step:
                return {"handled": False, "text": ""}
            raise RuntimeError("boom")

        out, _, _ = self.run_it(["dim the lights", "launch the spaceship", "play jazz", "wait 1 seconds"], runner)
        self.assertEqual(calls, ["dim the lights", "launch the spaceship", "play jazz"])
        self.assertEqual((out["done"], out["total"]), (1, 4))
        self.assertEqual(len(out["problems"]), 3)
        self.assertIn("The lights didn't answer.", out["text"])
        self.assertIn("1 of 4", out["text"])

    def test_waiting_is_capped_in_total(self):
        _, _, slept = self.run_it(["wait 30 seconds"] * 5)
        self.assertEqual(sum(slept), routines.MAX_TOTAL_WAIT_S)

    def test_a_timer_needs_the_page(self):
        out, _, _ = self.run_it(["timer 5 minutes", "say hi", "note x"], tell=False)
        self.assertEqual(out["done"], 0)
        self.assertEqual(len(out["problems"]), 3)


class WithTheCommands(unittest.TestCase):
    def setUp(self):
        self.config = Path(tempfile.mkdtemp()) / "routines.json"
        routines.save([MOVIE], self.config)
        self.patch = mock.patch.object(routines, "CONFIG", self.config)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()

    def test_saying_the_name_runs_it_before_anything_else(self):
        steps = []
        told = []
        with mock.patch.object(localcmd, "commands", side_effect=lambda t, tp=None: (steps.append(t), {"handled": True, "ok": True, "text": "ok"})[1]):
            out = localcmd.handle("Jarvis, start the movie night routine", told.append)
        self.assertEqual(out, {"handled": True, "ok": True, "text": "Movie night: done."})
        self.assertEqual(steps, ["dim the lights to 20 percent", "play some jazz"])
        self.assertEqual([e["type"] for e in told], ["phone_event", "notify"])

    def test_other_sentences_go_to_the_normal_commands(self):
        with mock.patch.object(localcmd, "commands", return_value={"handled": False, "ok": False, "text": ""}) as normal:
            out = localcmd.handle("what is the weather")
        normal.assert_called_once()
        self.assertFalse(out["handled"])

    def test_a_routine_cannot_start_another_routine(self):
        routines.save([MOVIE, {"name": "Chain", "steps": ["movie night", "lights off"]}], self.config)
        ran = []
        with mock.patch.object(localcmd.lights_mod, "handle_voice", side_effect=lambda t: (ran.append(("lights", t)), {"handled": True, "ok": True, "text": "x"})[1]), \
                mock.patch.object(localcmd.music_mod, "handle_voice", return_value={"handled": False, "text": ""}), \
                mock.patch.object(localcmd.browser_mod, "handle_voice", return_value={"handled": False, "text": ""}), \
                mock.patch.object(localcmd.filefinder, "handle_voice", return_value={"handled": False, "text": ""}), \
                mock.patch.object(localcmd.pictures, "handle_voice", return_value={"handled": False, "text": ""}), \
                mock.patch.object(localcmd.apps_mod, "available", return_value=False):
            out = localcmd.handle("chain", lambda e: None)
        self.assertEqual(ran, [("lights", "movie night"), ("lights", "lights off")])        # "movie night" as a step was only offered to the normal commands, so its own steps never ran
        self.assertTrue(out["ok"])
        self.assertNotIn(("lights", "dim the lights to 20 percent"), ran)    # the movie routine's own steps never ran


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def call(url, body=None, token=None, method=None):
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data is not None else "GET")), timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except (urllib.error.URLError, ConnectionError, OSError):     # refused and hung up on before the body was read
        return 0, ""


class FromThePhone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.ran, cls.locked = [], False

        class Api:
            def list(self):
                return [{"id": "abc123", "name": "Movie night", "steps": 4}]

            def run(self, key):
                cls.ran.append(key)
                return {"ok": True, "text": "Movie night: done."}

        cls.port = free_port()
        cls.service = phone.PhoneService(phone.Phones(cls.dir / "phones.json"))
        cls.service.start(lambda *a: iter(()), lambda e: None, lambda: cls.locked, port=cls.port, tls=False, host="127.0.0.1", routines=Api())
        for _ in range(100):
            if cls.service.server.started:
                break
            time.sleep(0.1)
        cls.base = f"http://127.0.0.1:{cls.port}"
        code = cls.service.phones.new_code()["code"]
        cls.token = json.loads(call(f"{cls.base}/pair", {"code": code, "name": "Test"})[1])["token"]

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()

    def setUp(self):
        self.ran.clear()
        type(self).locked = False

    def test_a_paired_phone_lists_and_runs_routines(self):
        status, body = call(f"{self.base}/routines", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["routines"][0]["name"], "Movie night")
        status, body = call(f"{self.base}/routines/run", {"id": "abc123"}, self.token)
        self.assertEqual((status, json.loads(body)["text"]), (200, "Movie night: done."))
        self.assertEqual(self.ran, ["abc123"])

    def test_nobody_else_can(self):
        self.assertEqual(call(f"{self.base}/routines")[0], 401)
        self.assertEqual(call(f"{self.base}/routines/run", {"id": "abc123"})[0], 401)
        self.assertEqual(call(f"{self.base}/routines/run", {"id": "abc123"}, "made-up")[0], 401)
        self.assertEqual(self.ran, [])

    def test_a_phone_cannot_make_or_change_routines(self):
        for method in ("PUT", "POST", "DELETE"):
            for path in ("/api/routines", "/routines/save", "/routines/new"):
                self.assertIn(call(f"{self.base}{path}", None if method == "DELETE" else {"routines": []}, self.token, method)[0], (0, 404, 405, 422), f"{method} {path}")
        self.assertEqual(self.ran, [])

    def test_the_privacy_screen_stops_them(self):
        type(self).locked = True
        self.assertEqual(call(f"{self.base}/routines/run", {"id": "abc123"}, self.token)[0], 423)
        self.assertEqual(self.ran, [])


class Wiring(unittest.TestCase):
    def test_the_pc_routes(self):
        main = (ROOT / "server" / "main.py").read_text("utf-8")
        for route in ('@app.get("/api/routines")', '@app.put("/api/routines")', '@app.post("/api/routines/run")', '@app.get("/api/finder")', '@app.put("/api/finder")',
                      '@app.post("/api/finder/search")', '@app.post("/api/finder/voice")', '@app.post("/api/finder/open")'):
            self.assertIn(route, main)
        self.assertIn("routines=_Routines()", main)
        phone_text = (ROOT / "server" / "phone.py").read_text("utf-8")
        self.assertNotIn("routines_mod.save", phone_text)                  # the phone door has no way to change them
        self.assertNotIn("routines.save", phone_text)

    def test_the_settings_are_in_the_status_menu(self):
        html = (ROOT / "web" / "index.html").read_text("utf-8")
        for ident in ('id="sec-routines"', 'id="routine-form"', 'id="routine-steps"', 'id="sec-files"', 'id="finder-form"', 'id="files-list"'):
            self.assertIn(ident, html)
        app = (ROOT / "web" / "app.js").read_text("utf-8")
        for name in ("routinesUI.handleVoice", "filesUI.handleVoice", "finderFolders.refresh()", "chat.onFiles"):
            self.assertIn(name, app)
        self.assertLess(app.index("routinesUI.handleVoice"), app.index("lightsUI.handleVoice"))      # your own words come before the built-in commands

    def test_the_finder_is_private_for_the_ai(self):
        from server import agent, audit as audit_mod
        self.assertIn("find_files", audit_mod.PRIVATE_TOOLS)
        self.assertIn("find_files", agent.FOLLOW_UP_TOOLS)
        self.assertIn("find_files", {t["function"]["name"] for t in agent.TOOLS})


if __name__ == "__main__":
    unittest.main()
