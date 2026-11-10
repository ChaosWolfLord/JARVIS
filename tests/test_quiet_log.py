"""Why JARVIS said "I'm logging many errors": old errors kept counting, two saves collided, speaker timeouts crashed a request, and a harmless
Windows message looked like a failure. Each is fixed; nothing real is touched."""
import json
import logging
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import diagnostics, music, store  # noqa: E402
from tests.test_diagnostics import base  # noqa: E402

TRACE = 'Traceback (most recent call last):\n  File "x.py", line 1, in f\nValueError: boom\n'


class Counting(unittest.TestCase):
    def test_a_traceback_is_one_error_and_so_is_a_lone_error_line(self):
        self.assertEqual(diagnostics.count_errors(TRACE), 1)
        self.assertEqual(diagnostics.count_errors("ERROR:    Exception in ASGI application\n" + TRACE), 1)      # not two
        self.assertEqual(diagnostics.count_errors("ERROR: the disk is full\nINFO: fine\n"), 1)
        self.assertEqual(diagnostics.count_errors("INFO: all good\nWARNING: careful\n"), 0)
        self.assertEqual(diagnostics.count_errors(TRACE * 4), 4)


class WatchingTheLog(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.log = self.dir / "jarvis.log"
        diagnostics._log_watch.clear()

    def add(self, text):
        with self.log.open("a", encoding="utf-8") as f:
            f.write(text)

    def test_errors_that_were_already_in_the_log_are_not_new(self):
        self.add(TRACE * 30)                                                    # an old burst, days ago
        self.assertEqual(diagnostics.recent_log_errors(path=self.log, now=1000.0), 0)
        self.assertEqual(diagnostics.recent_log_errors(path=self.log, now=1060.0), 0)      # and it never turns into an alert

    def test_new_errors_are_counted_and_stop_counting_after_ten_minutes(self):
        self.add("INFO: started\n")
        diagnostics.recent_log_errors(path=self.log, now=0.0)
        self.add(TRACE * 6)
        self.assertEqual(diagnostics.recent_log_errors(path=self.log, now=60.0), 6)
        self.add(TRACE * 5)
        self.assertEqual(diagnostics.recent_log_errors(path=self.log, now=120.0), 11)
        self.assertEqual(diagnostics.recent_log_errors(path=self.log, now=60.0 + 601), 5)     # the first burst is more than ten minutes old
        self.assertEqual(diagnostics.recent_log_errors(path=self.log, now=120.0 + 601), 0)    # all quiet again: the alert clears by itself

    def test_the_alert_appears_for_a_real_burst_and_clears(self):
        diagnostics.recent_log_errors(path=self.log, now=0.0)
        self.add(TRACE * 12)
        n = diagnostics.recent_log_errors(path=self.log, now=30.0)
        self.assertIn("jarvis-errors", diagnostics.evaluate(base(jarvis={"log_errors": n}), [], 0))
        self.assertNotIn("jarvis-errors", diagnostics.evaluate(base(jarvis={"log_errors": diagnostics.recent_log_errors(path=self.log, now=700.0)}), [], 0))

    def test_a_log_that_was_replaced_starts_again(self):
        self.add("x" * 500)
        diagnostics.recent_log_errors(path=self.log, now=0.0)
        self.log.write_text(TRACE * 3, "utf-8")                                 # smaller than before: a new log
        self.assertEqual(diagnostics.recent_log_errors(path=self.log, now=10.0), 0)
        self.add(TRACE)
        self.assertEqual(diagnostics.recent_log_errors(path=self.log, now=20.0), 1)

    def test_a_missing_log_is_zero_errors(self):
        self.assertEqual(diagnostics.recent_log_errors(path=self.dir / "nothing.log"), 0)


class SavingSettings(unittest.TestCase):
    def test_saves_at_the_same_moment_do_not_collide(self):
        target = Path(tempfile.mkdtemp()) / "ui_settings.json"
        failures = []

        def save(n):
            try:
                for i in range(25):
                    store._write(target, {"n": n, "i": i})
            except Exception as e:  # noqa: BLE001
                failures.append(e)

        threads = [threading.Thread(target=save, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(failures, [])
        self.assertIn("n", json.loads(target.read_text("utf-8")))                # a whole, valid file
        self.assertEqual([p.name for p in target.parent.iterdir()], ["ui_settings.json"])     # and no temp files left behind

    def test_a_file_that_stays_locked_is_still_an_error_but_leaves_no_litter(self):
        target = Path(tempfile.mkdtemp()) / "x.json"
        with mock.patch.object(Path, "replace", side_effect=PermissionError("locked")), mock.patch.object(store, "_RETRY_DELAYS", (0.0, 0.0)):
            with self.assertRaises(PermissionError):
                store._write(target, {"a": 1})
        self.assertEqual(list(target.parent.iterdir()), [])


class Speakers(unittest.TestCase):
    def test_a_speaker_that_stops_answering_is_a_message_not_a_crash(self):
        class Dead(music.CastBackend):
            def _cast(self, name):
                raise TimeoutError("Execution of wait timed out")

        for call in (lambda b: b.control("Kitchen", "pause"), lambda b: b.volume("Kitchen", level=0.3), lambda b: b.now_playing("Kitchen")):
            with self.assertRaises(music.MusicError) as e:
                call(Dead())
            self.assertIn("didn't respond", str(e.exception))


class WindowsNoise(unittest.TestCase):
    def record(self, exc, message):
        try:
            raise exc
        except Exception:  # noqa: BLE001
            return logging.LogRecord("asyncio", logging.ERROR, __file__, 1, message, None, sys.exc_info())

    def test_an_abruptly_closed_connection_is_not_logged_as_an_error(self):
        from server import main
        quiet = main._QuietResets()
        self.assertFalse(quiet.filter(self.record(ConnectionResetError(10054, "forcibly closed"), "Exception in callback _ProactorBasePipeTransport._call_connection_lost()")))

    def test_real_problems_are_still_logged(self):
        from server import main
        quiet = main._QuietResets()
        self.assertTrue(quiet.filter(self.record(ValueError("boom"), "Exception in callback _ProactorBasePipeTransport._call_connection_lost()")))
        self.assertTrue(quiet.filter(self.record(ConnectionResetError(), "Task exception was never retrieved")))
        self.assertTrue(quiet.filter(logging.LogRecord("asyncio", logging.ERROR, __file__, 1, "plain", None, None)))


if __name__ == "__main__":
    unittest.main()
