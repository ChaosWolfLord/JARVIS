"""Tests for saved reminders: understanding the time, saving and cancelling, delivery (including late and held-back ones), the AI tool,
and the phone's event stream. No clock is waited on and nothing is spoken."""
import asyncio
import json
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, audit, phone, reminders  # noqa: E402

NOW = datetime(2026, 11, 5, 14, 30, 0).timestamp()          # Thursday 5 November 2026, 14:30 local


def stamp(text: str) -> float:
    return datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


_log_patch = mock.patch.object(audit, "LOG_FILE", Path(tempfile.mkdtemp()) / "activity.log")      # what these tests do must not appear in the real activity log


def setUpModule():
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


class When(unittest.TestCase):
    def test_minutes_from_now(self):
        self.assertEqual(reminders.parse_when({"minutes": 10}, NOW), NOW + 600)
        self.assertEqual(reminders.parse_when({"minutes": "0.5"}, NOW), NOW + 30)

    def test_clock_times(self):
        self.assertEqual(reminders.parse_when({"at": "2026-11-05 17:00"}, NOW), stamp("2026-11-05 17:00"))
        self.assertEqual(reminders.parse_when({"at": "2026-11-06T09:15"}, NOW), stamp("2026-11-06 09:15"))
        self.assertEqual(reminders.parse_when({"at": "17:00"}, NOW), stamp("2026-11-05 17:00"))      # later today
        self.assertEqual(reminders.parse_when({"at": "09:00"}, NOW), stamp("2026-11-06 09:00"))      # already passed: tomorrow

    def test_things_that_cannot_work(self):
        for args in ({}, {"minutes": "soon"}, {"minutes": 0}, {"minutes": 99999999}, {"at": "tea time"}, {"at": "2026-11-05 14:00"},
                     {"at": "2026-11-05 25:99"}, {"at": "2030-01-01 10:00"}):
            with self.assertRaises(reminders.ReminderError, msg=str(args)):
                reminders.parse_when(args, NOW)

    def test_how_a_time_is_said(self):
        self.assertEqual(reminders.when_text(stamp("2026-11-05 17:00"), NOW), "today at 5:00 PM")
        self.assertEqual(reminders.when_text(stamp("2026-11-06 09:30"), NOW), "tomorrow at 9:30 AM")
        self.assertEqual(reminders.when_text(stamp("2026-11-09 08:05"), NOW), "Mon 9 Nov at 8:05 AM")


class Saving(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.clock = Clock()
        self.store = reminders.Reminders(self.dir / "r.json", self.clock)

    def test_saved_in_order_and_kept_between_runs(self):
        self.store.add("second", NOW + 7200)
        self.store.add("first", NOW + 60)
        self.assertEqual([r["text"] for r in self.store.open()], ["first", "second"])
        again = reminders.Reminders(self.dir / "r.json", self.clock)           # a restart
        self.assertEqual([r["text"] for r in again.open()], ["first", "second"])

    def test_text_is_tidied_and_must_exist(self):
        self.assertEqual(self.store.add("  call   Sam\n now ", NOW + 60)["text"], "call Sam now")
        self.assertEqual(len(self.store.add("x" * 500, NOW + 60)["text"]), reminders.MAX_TEXT)
        with self.assertRaises(reminders.ReminderError):
            self.store.add("   ", NOW + 60)

    def test_cancel_by_words_or_everything(self):
        self.store.add("call Sam", NOW + 60)
        self.store.add("take the bins out", NOW + 120)
        self.store.add("call Mum", NOW + 180)
        self.assertEqual([r["text"] for r in self.store.cancel("CALL")], ["call Sam", "call Mum"])
        self.assertEqual(self.store.cancel("nothing like this"), [])
        self.assertEqual(self.store.cancel(""), [])                            # no words and not "everything": nothing
        self.assertEqual(len(self.store.cancel(everything=True)), 1)
        self.assertEqual(self.store.open(), [])

    def test_due_and_done(self):
        a = self.store.add("soon", NOW + 60)
        self.store.add("later", NOW + 3600)
        self.assertEqual(self.store.due(), [])
        self.clock.t += 61
        self.assertEqual([r["text"] for r in self.store.due()], ["soon"])
        self.store.mark_done([a["id"]])
        self.assertEqual(self.store.due(), [])
        self.assertEqual([r["text"] for r in self.store.open()], ["later"])
        self.clock.t += reminders.KEEP_DONE_S + 10
        self.store.mark_done([])                                               # tidying drops what was delivered a day ago
        self.assertEqual(len(json.loads((self.dir / "r.json").read_text("utf-8"))["reminders"]), 1)

    def test_a_limit_and_a_damaged_file(self):
        for i in range(reminders.MAX_OPEN):
            self.store.add(f"r{i}", NOW + 60 + i)
        with self.assertRaises(reminders.ReminderError):
            self.store.add("one too many", NOW + 5000)
        (self.dir / "r.json").write_text("{not json", "utf-8")
        self.assertEqual(self.store.open(), [])
        self.store.add("fresh start", NOW + 60)
        self.assertEqual(len(self.store.open()), 1)


class Delivery(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = reminders.Reminders(Path(tempfile.mkdtemp()) / "r.json", self.clock)
        self.pc, self.phone_events = [], []
        self.pc_listeners, self.phone_listeners = 1, 0
        self.is_locked = False
        self.courier = reminders.Courier(self.store, self._pc, self._phone, lambda: self.is_locked)

    def _pc(self, event):
        self.pc.append(event)
        return self.pc_listeners

    def _phone(self, event):
        self.phone_events.append(event)
        return self.phone_listeners

    def test_on_time_goes_to_the_page_and_is_finished(self):
        self.store.add("call Sam", NOW + 30)
        self.assertEqual(self.courier.deliver_due(), 0)                        # not yet
        self.clock.t += 31
        self.assertEqual(self.courier.deliver_due(), 1)
        ev = self.pc[0]
        self.assertEqual((ev["type"], ev["text"], ev["late"]), ("reminder", "call Sam", False))
        self.assertEqual(ev["speak"], "Reminder: call Sam.")
        self.assertEqual(self.courier.deliver_due(), 0)                        # never twice
        self.assertEqual(self.store.open(), [])

    def test_the_phone_gets_it_too(self):
        self.phone_listeners = 1
        self.store.add("take the bins out", NOW + 10)
        self.clock.t += 11
        self.courier.deliver_due()
        self.assertEqual(self.phone_events[0]["type"], "push")
        self.assertIn("bins", self.phone_events[0]["text"])

    def test_waits_until_somebody_can_hear_it_then_says_it_is_late(self):
        self.pc_listeners = 0
        self.store.add("pay rent", NOW + 10)
        self.clock.t += 11
        self.assertEqual(self.courier.deliver_due(), 0)                        # the page is closed: it waits
        self.assertEqual(len(self.store.open()), 1)
        self.clock.t += 3600
        self.pc_listeners = 1
        self.assertEqual(self.courier.deliver_due(), 1)
        late = self.pc[-1]
        self.assertTrue(late["late"])
        self.assertIn("from ", late["title"])
        self.assertTrue(late["speak"].startswith("You asked me to remind you"))

    def test_phone_alone_is_enough(self):
        self.pc_listeners, self.phone_listeners = 0, 1
        self.store.add("ring the dentist", NOW + 10)
        self.clock.t += 11
        self.assertEqual(self.courier.deliver_due(), 1)

    def test_nothing_is_delivered_behind_the_privacy_screen(self):
        self.store.add("secret", NOW + 10)
        self.clock.t += 11
        self.is_locked = True
        self.assertEqual(self.courier.deliver_due(), 0)
        self.assertEqual((self.pc, self.phone_events), ([], []))
        self.is_locked = False
        self.assertEqual(self.courier.deliver_due(), 1)


class Tool(unittest.TestCase):
    def setUp(self):
        self.store = reminders.Reminders(Path(tempfile.mkdtemp()) / "r.json")
        patcher = mock.patch.object(reminders, "reminders", self.store)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_tool(self, **args):
        return agent._run_lookup("reminder", args)

    def test_add_list_cancel(self):
        out = self.run_tool(action="add", text="call Sam", minutes=90)
        self.assertTrue(out.startswith("Reminder saved for "), out)
        self.assertIn("call Sam", out)
        self.assertIn("call Sam", self.run_tool(action="list"))
        self.assertIn("Cancelled 1", self.run_tool(action="cancel", text="sam"))
        self.assertEqual(self.run_tool(action="list"), "No reminders are waiting.")
        self.assertEqual(self.run_tool(action="cancel", text="nothing"), "No waiting reminder matches that.")

    def test_mistakes_are_explained_to_the_model(self):
        self.assertTrue(self.run_tool(action="add", text="x").startswith("Error: Say when"))
        self.assertTrue(self.run_tool(action="add", minutes=5).startswith("Error: What should I remind you about"))
        self.assertTrue(self.run_tool(action="add", text="x", at="yesterday").startswith("Error:"))

    def test_it_is_wired_into_the_agent(self):
        names = [t["function"]["name"] for t in agent.TOOLS]
        self.assertIn("reminder", names)
        self.assertIn("reminder", agent.FOLLOW_UP_TOOLS)
        self.assertIn("local time is", agent.build_system("hello"))
        self.assertIn("call Sam", audit.describe("reminder", {"action": "add", "text": "call Sam", "minutes": 5}))
        self.assertTrue(agent._step_text("reminder", {}))


class PhoneEvents(unittest.TestCase):
    """The phone page's event stream, on a real (unencrypted, this-PC-only) server."""

    def test_events_reach_a_connected_phone_and_a_forgotten_one_is_refused(self):
        import socket
        import time
        import urllib.error
        import urllib.request

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        connected = []
        service = phone.PhoneService(phone.Phones(Path(tempfile.mkdtemp()) / "p.json"))
        service.start(lambda *a, **k: iter(()), lambda e: None, lambda: False, port=port, tls=False, host="127.0.0.1", on_events_connect=lambda: connected.append(1))
        try:
            for _ in range(100):
                if service.server.started:
                    break
                time.sleep(0.1)
            self.assertEqual(service.publish({"type": "push", "title": "nobody listening"}), 0)
            token, _ = service.phones.pair(service.phones.new_code()["code"], "t")
            req = urllib.request.Request(f"http://127.0.0.1:{port}/events", headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=10) as stream:
                self.assertEqual(stream.readline().decode().strip(), ": connected")
                stream.readline()
                for _ in range(50):
                    if service.events.queues:
                        break
                    time.sleep(0.1)
                self.assertEqual(service.publish({"type": "push", "title": "Reminder", "text": "call Sam"}), 1)
                line = stream.readline().decode().strip()
                self.assertTrue(line.startswith("data:"), line)
                self.assertEqual(json.loads(line[5:])["text"], "call Sam")
            time.sleep(1.6)
            self.assertTrue(connected, "connecting did not trigger the hand-over of waiting reminders")
            with self.assertRaises(urllib.error.HTTPError) as err:
                urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/events", headers={"Authorization": "Bearer nope"}), timeout=5)
            self.assertEqual(err.exception.code, 401)
        finally:
            service.stop()


class Sync(unittest.TestCase):
    """The phone's reminder sync (POST /reminders/sync) on a real server, with its own reminder file."""

    @classmethod
    def setUpClass(cls):
        import socket
        import time

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.dir = Path(tempfile.mkdtemp())
        cls.store = reminders.Reminders(cls.dir / "r.json")
        cls.service = phone.PhoneService(phone.Phones(cls.dir / "p.json"))
        cls.service.reminder_store = cls.store
        cls.service.start(lambda *a, **k: iter(()), lambda e: None, lambda: False, port=cls.port, tls=False, host="127.0.0.1")
        for _ in range(100):
            if cls.service.server.started:
                break
            time.sleep(0.1)
        cls.token, _ = cls.service.phones.pair(cls.service.phones.new_code()["code"], "t")

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()

    def sync(self, body, token=None):
        import urllib.error
        import urllib.request

        req = urllib.request.Request(f"http://127.0.0.1:{self.port}/reminders/sync", data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {token or self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, {}

    def setUp(self):
        self.store.cancel(everything=True)

    def test_a_token_is_needed(self):
        self.assertEqual(self.sync({"created": [], "deleted": [], "fired": []}, token="nope")[0], 401)

    def test_new_cancelled_and_rung(self):
        import time

        now = time.time()
        status, out = self.sync({"created": [{"lid": "L1", "text": "from the phone", "due": now + 600}, {"lid": "L2", "text": "rung offline", "due": now - 60, "fired": True}]})
        self.assertEqual(status, 200)
        ids = {m["lid"]: m["id"] for m in out["created"]}
        self.assertTrue(ids["L1"] and ids["L2"])
        self.assertEqual([r["text"] for r in out["reminders"]], ["from the phone"])          # the one the phone rang is not waiting on the PC
        self.assertEqual(self.store.due(), [])
        status, out = self.sync({"created": [], "deleted": [ids["L1"]], "fired": []})
        self.assertEqual(out["reminders"], [])
        a = self.store.add("on the PC", now + 3600)
        self.assertEqual([r["text"] for r in self.sync({"created": [], "deleted": [], "fired": []})[1]["reminders"]], ["on the PC"])
        self.sync({"created": [], "deleted": [], "fired": [a["id"]]})                          # the phone announced it: the PC will not
        self.assertEqual(self.store.open(), [])

    def test_bad_times_and_too_many_are_refused_politely(self):
        import time

        now = time.time()
        status, out = self.sync({"created": [{"lid": "L9", "text": "far away", "due": now + 10 * 365 * 86400}, {"lid": "L8", "text": "  ", "due": now + 600}]})
        self.assertEqual(status, 200)
        self.assertEqual([m["id"] for m in out["created"]], [None, None])
        self.assertEqual(self.sync({"created": [{"lid": f"x{i}", "text": "a", "due": now + 600} for i in range(51)]})[0], 422)
        self.assertEqual(self.sync({"created": [{"lid": "x", "text": "a" * 201, "due": now + 600}]})[0], 422)


class Ids(unittest.TestCase):
    def test_cancel_by_exact_id_only(self):
        st = reminders.Reminders(Path(tempfile.mkdtemp()) / "r.json", Clock())
        a, b = st.add("one", NOW + 60), st.add("two", NOW + 120)
        self.assertEqual([r["text"] for r in st.cancel_ids([a["id"], "nope"])], ["one"])
        self.assertEqual([r["text"] for r in st.open()], ["two"])

    def test_the_phone_push_names_the_reminder_so_it_is_not_shown_twice(self):
        st = reminders.Reminders(Path(tempfile.mkdtemp()) / "r.json", Clock())
        r = st.add("call Sam", NOW + 10)
        st.now = Clock(NOW + 11)
        seen = []
        reminders.Courier(st, lambda e: 0, lambda e: seen.append(e) or 1).deliver_due()
        self.assertEqual(seen[0]["rid"], r["id"])


if __name__ == "__main__":
    unittest.main()
