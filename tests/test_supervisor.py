"""Tests for the supervisor that keeps JARVIS running: restart timing, finding a browser, and restarting a child."""
import subprocess
import socket
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import supervisor as sup  # noqa: E402


class Backoff(unittest.TestCase):
    def test_waits_longer_each_time_up_to_thirty_seconds(self):
        b = sup.Backoff()
        self.assertEqual([b.next(1) for _ in range(8)], [1, 2, 4, 8, 16, 30, 30, 30])

    def test_a_run_that_lasted_a_minute_starts_the_count_again(self):
        b = sup.Backoff()
        [b.next(1) for _ in range(4)]
        self.assertEqual(b.next(120), 1)
        self.assertEqual(b.next(1), 2)


class Browser(unittest.TestCase):
    def test_each_browser_gets_its_own_profile_folder(self):
        edge = sup.profile_for(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
        chrome = sup.profile_for(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        self.assertNotEqual(edge, chrome)
        self.assertEqual(chrome, sup.BROWSER_PROFILE)
        self.assertEqual(edge.name, "browser-edge")

    def test_finds_edge_before_chrome(self):
        found = {r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"}
        env = {"PROGRAMFILES": r"C:\Program Files", "PROGRAMFILES(X86)": r"C:\Program Files (x86)", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}
        with mock.patch.dict("os.environ", env, clear=False):
            self.assertTrue(sup.find_browser({}, exists=lambda p: p in found).endswith("msedge.exe"))
            self.assertTrue(sup.find_browser({}, exists=lambda p: "chrome" in p).endswith("chrome.exe"))
            self.assertTrue(sup.find_browser({}, exists=lambda p: "msedge" in p).endswith("msedge.exe"))
            self.assertIsNone(sup.find_browser({}, exists=lambda p: False))

    def test_the_env_setting_wins_if_the_file_exists(self):
        self.assertEqual(sup.find_browser({"JARVIS_BROWSER": r"D:\x\brave.exe"}, exists=lambda p: True), r"D:\x\brave.exe")
        self.assertNotEqual(sup.find_browser({"JARVIS_BROWSER": r"D:\x\brave.exe"}, exists=lambda p: False), r"D:\x\brave.exe")

    def test_the_window_is_an_app_window_in_its_own_profile(self):
        args = sup.browser_args("chrome.exe", "http://localhost:8000", Path("P"))
        self.assertIn("--app=http://localhost:8000", args)
        self.assertIn("--start-fullscreen", args)
        self.assertIn("--autoplay-policy=no-user-gesture-required", args)
        self.assertTrue(any(a.startswith("--user-data-dir=") for a in args))
        self.assertFalse(any(a.startswith("--user-data-dir=") for a in sup.browser_args("chrome.exe", "http://x", None)))


class Ports(unittest.TestCase):
    def test_port_open_sees_a_listener(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertTrue(sup.port_open(port))
        finally:
            s.close()
        self.assertFalse(sup.port_open(port))


class Restarting(unittest.TestCase):
    def test_a_program_that_exits_is_started_again_after_a_pause(self):
        messages = []
        child = sup.Child("demo", [sys.executable, "-c", "import sys; sys.exit(3)"], subprocess.DEVNULL, messages.append)
        child.tick()
        first = child.proc
        self.assertIsNotNone(first)
        first.wait(timeout=10)
        child.tick()                                            # notices it ended and schedules the restart
        self.assertIsNone(child.proc)
        self.assertGreater(child.not_before, time.time())
        self.assertTrue(any("exit 3" in m for m in messages))
        child.not_before = 0
        child.tick()                                            # the pause is over
        self.assertIsNotNone(child.proc)
        self.assertNotEqual(child.proc.pid, first.pid)
        child.stop()

    def test_stop_ends_a_running_program(self):
        child = sup.Child("demo", [sys.executable, "-c", "import time; time.sleep(60)"], subprocess.DEVNULL, lambda m: None)
        child.tick()
        self.assertIsNone(child.proc.poll())
        child.stop()
        self.assertIsNotNone(child.proc.poll())


if __name__ == "__main__":
    unittest.main()

