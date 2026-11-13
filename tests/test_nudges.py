"""JARVIS speaks first: what it says, when it stays quiet, and that it never repeats itself."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from server import nudges

NOON = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = NOON
        self.events, self.mails, self.calls = [], [], {"cal": 0, "mail": 0}
        self.n = nudges.Nudges(self.calendar, self.mail, Path(self.tmp.name) / "n.json", Path(self.tmp.name) / "seen.json", clock=lambda: self.now.timestamp())

    def calendar(self, minutes, now):
        self.calls["cal"] += 1
        return [e for e in self.events if now < e["start"] <= now + timedelta(minutes=minutes)]

    def mail(self):
        self.calls["mail"] += 1
        return list(self.mails)

    def event(self, title, minutes, id="e1", where=""):
        self.events.append({"id": id, "title": title, "start": self.now + timedelta(minutes=minutes), "where": where})

    def message(self, id, sender, age_minutes=1):
        self.mails.append({"id": id, "sender": sender, "when_ms": int((self.now - timedelta(minutes=age_minutes)).timestamp() * 1000)})

    def later(self, minutes):
        self.now += timedelta(minutes=minutes)
        return self.n.check(self.now)


class Calendar(Fixture):
    def test_a_meeting_is_announced_once(self):
        self.event("Dentist", 8, where="Main St")
        first = self.n.check(self.now)
        self.assertEqual([(i["kind"], i["text"]) for i in first], [("calendar", "Dentist starts in 8 minutes, at Main St.")])
        self.assertEqual(self.later(3), [])                      # not again
        self.assertEqual(self.n.check(self.now, force=True), [])

    def test_a_meeting_far_off_waits(self):
        self.event("Later", 45)
        self.assertEqual(self.n.check(self.now), [])

    def test_one_minute_is_singular(self):
        self.event("Stand-up", 1)
        self.assertEqual(self.n.check(self.now)[0]["text"], "Stand-up starts in 1 minute.")

    def test_it_asks_google_only_every_couple_of_minutes(self):
        self.n.check(self.now)
        self.n.check(self.now)
        self.assertEqual(self.calls["cal"], 1)
        self.later(3)
        self.assertEqual(self.calls["cal"], 2)


class Mail(Fixture):
    def test_the_first_look_only_notes_what_is_waiting(self):
        self.message("old1", "Sam")
        self.assertEqual(self.n.check(self.now), [])
        self.message("new1", "Alex")
        self.message("new2", "Sam")
        said = self.later(6)
        self.assertEqual(said, [{"kind": "mail", "text": "You have 2 new important emails, from Alex and Sam."}])
        self.assertEqual(self.later(6), [])

    def test_old_mail_is_not_announced(self):
        self.n.check(self.now)
        self.message("stale", "Pat", age_minutes=5 * 60)
        self.assertEqual(self.later(6), [])

    def test_only_who_it_is_from_is_ever_used(self):
        self.n.check(self.now)
        self.message("x", "Dana")
        self.assertNotIn("subject", self.later(6)[0]["text"].lower())

    def test_three_senders_are_listed_and_more_are_cut(self):
        self.n.check(self.now)
        for i, name in enumerate(["A", "B", "C", "D"]):
            self.message(f"m{i}", name)
        self.assertEqual(self.later(6)[0]["text"], "You have 4 new important emails, from A, B and C.")


class Quiet(Fixture):
    def test_quiet_hours_cross_midnight(self):
        at = lambda h, m=0: datetime(2026, 11, 12, h, m)
        self.assertTrue(nudges.in_quiet(at(23), "22:00", "07:00"))
        self.assertTrue(nudges.in_quiet(at(3), "22:00", "07:00"))
        self.assertFalse(nudges.in_quiet(at(7), "22:00", "07:00"))
        self.assertFalse(nudges.in_quiet(at(12), "22:00", "07:00"))
        self.assertFalse(nudges.in_quiet(at(23), "09:00", "09:00"))       # equal times: no quiet hours

    def test_nothing_is_said_in_quiet_hours(self):
        self.now = datetime(2026, 11, 12, 23, 0, tzinfo=timezone.utc)
        self.n.clock = lambda: self.now.timestamp()
        self.event("Late call", 5)
        self.assertEqual(self.n.check(self.now.replace(tzinfo=None)), [])

    def test_snooze_and_resume(self):
        self.event("Call", 5)
        self.n.snooze(60)
        self.assertTrue(self.n.status()["snoozed"])
        self.assertEqual(self.n.check(self.now), [])
        self.n.snooze(0)
        self.assertEqual(len(self.n.check(self.now, force=True)), 1)

    def test_switched_off_means_silent_and_no_google_calls(self):
        self.n.update({"enabled": False})
        self.event("Call", 5)
        self.assertEqual(self.n.check(self.now), [])
        self.assertEqual(self.calls, {"cal": 0, "mail": 0})


class Failures(Fixture):
    def test_google_being_down_is_not_fatal_and_is_reported(self):
        def broken(*a):
            raise RuntimeError("Couldn't reach Google.")
        self.n.calendar = broken
        self.assertEqual(self.n.check(self.now), [])
        self.assertIn("Couldn't reach Google", self.n.status()["error"])


class Settings(Fixture):
    def test_settings_are_made_safe(self):
        s = self.n.update({"minutes": 9999, "quiet_from": "25:99", "quiet_to": "6:30", "enabled": "yes", "evil": 1})
        self.assertEqual((s["minutes"], s["quiet_from"], s["quiet_to"], s["enabled"]), (60, "22:00", "06:30", True))
        self.assertNotIn("evil", s)
        self.assertEqual(self.n.settings(), s)                    # and they were saved

    def test_a_broken_settings_file_falls_back_to_the_defaults(self):
        (Path(self.tmp.name) / "n.json").write_text("{nope", encoding="utf-8")
        self.assertEqual(self.n.settings(), nudges.DEFAULTS)


class Voice(unittest.TestCase):
    def test_which_sentences_snooze_it(self):
        for text, minutes in [("be quiet for an hour", 60), ("don't interrupt me for 30 minutes", 30), ("stop nudging me", 60), ("quiet for half an hour", 30),
                              ("don't disturb me today", 480), ("no more heads ups for 2 hours", 120), ("Jarvis, stop interrupting me for 15 minutes", 15)]:
            self.assertEqual(nudges.snooze_minutes(text), minutes, text)
        for text in ["be quiet", "quiet please", "what time is it", "stop the music", "play something quiet", "what is the quietest planet", ""]:
            self.assertIsNone(nudges.snooze_minutes(text), text)


class Wiring(unittest.TestCase):
    def test_the_loop_never_runs_while_private_or_without_google(self):
        src = (Path(__file__).resolve().parent.parent / "server" / "main.py").read_text(encoding="utf-8")
        loop = src[src.index("def nudge_loop"):src.index("def on_monitor_event")]
        self.assertIn("privacy.locked()", loop)
        self.assertIn("google_tools.available()", loop)
        self.assertNotIn("agent.", loop)                          # nothing goes to an AI

    def test_the_google_look_ups_never_read_subjects_or_bodies(self):
        src = (Path(__file__).resolve().parent.parent / "server" / "google_tools.py").read_text(encoding="utf-8")
        part = src[src.index("def important_unread"):src.index("# ---- actions")]
        self.assertIn('"metadataHeaders": ["From"]', part)
        self.assertNotIn('"Subject"', part)
        self.assertNotIn("snippet", part)


if __name__ == "__main__":
    unittest.main()
