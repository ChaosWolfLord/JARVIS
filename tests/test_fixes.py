"""Tests for the safe fixes: each is shown first, only runs after Allow, and refuses what it must never touch.
No real program is closed and nothing outside a temporary folder is deleted."""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, audit, fixes  # noqa: E402

DAY = 86400


def info(name="notepad", pid=4321, session=1, mb=50, path=r"C:\Windows\notepad.exe"):
    return json.dumps({"name": name, "id": pid, "session": session, "mb": mb, "path": path})


class Temp(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name).resolve()
        self.now = time.time()

    def make(self, rel, age_days, size=10):
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)
        t = self.now - age_days * DAY
        os.utime(path, (t, t))
        return path

    def test_only_old_files_are_counted(self):
        old, new = self.make("old.tmp", 10), self.make("sub/new.tmp", 1)
        self.make("claude/session.tmp", 30)                         # another program's working folder is left alone
        found = {p for p, _ in fixes.old_temp_files(self.dir, self.now)}
        self.assertEqual(found, {old})
        self.assertNotIn(new, found)

    def test_preview_says_how_many_and_how_big_and_changes_nothing(self):
        old = self.make("a.tmp", 9, 2048)
        self.make("b.tmp", 9, 2048)
        prepared = fixes.prepare_clean_temp(self.dir, self.now)
        self.assertIn("2 files", prepared.preview)
        self.assertIn("Recycle Bin", prepared.preview)
        self.assertTrue(old.exists())

    def test_running_it_deletes_only_what_was_shown(self):
        old = self.make("a.tmp", 9)
        keep = self.make("keep.tmp", 1)
        prepared = fixes.prepare_clean_temp(self.dir, self.now)
        newcomer = self.make("late.tmp", 9)                          # appeared after the preview: not on the approved list
        result = prepared.run()
        self.assertFalse(old.exists())
        self.assertTrue(keep.exists() and newcomer.exists())
        self.assertIn("Cleared 1", result)

    def test_a_file_touched_after_the_preview_is_kept(self):
        path = self.make("a.tmp", 9)
        prepared = fixes.prepare_clean_temp(self.dir, self.now)
        os.utime(path, (self.now, self.now))
        prepared.run()
        self.assertTrue(path.exists())

    def test_nothing_to_clear_is_explained(self):
        self.make("new.tmp", 0)
        with self.assertRaises(fixes.FixError):
            fixes.prepare_clean_temp(self.dir, self.now)

    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_links_are_never_followed(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        victim = Path(outside.name) / "precious.txt"
        victim.write_text("keep me")
        t = self.now - 20 * DAY
        os.utime(victim, (t, t))
        try:
            os.symlink(outside.name, self.dir / "link", target_is_directory=True)
        except OSError:
            self.skipTest("symlinks need privileges here")
        self.make("old.tmp", 9)
        fixes.prepare_clean_temp(self.dir, self.now).run()
        self.assertTrue(victim.exists())


class EndProgram(unittest.TestCase):
    def prepare(self, target, text, session=1, **kw):
        return fixes.prepare_end_program(target, run=lambda script: text, own_session=session, supervisor_pid=kw.get("supervisor", 999_999))

    def test_the_card_names_the_program_and_warns_about_unsaved_work(self):
        p = self.prepare("4321", info())
        self.assertIn("notepad", p.title)
        self.assertIn("4321", p.preview)
        self.assertIn("unsaved", p.preview)

    def test_a_name_instead_of_an_id_is_refused(self):
        with self.assertRaises(fixes.FixError):
            self.prepare("chrome", info())

    def test_windows_and_security_programs_are_refused(self):
        for name in ("svchost", "lsass", "MsMpEng", "explorer", "csrss", "SecurityHealthService"):
            with self.assertRaises(fixes.FixError, msg=name):
                self.prepare("4321", info(name=name))

    def test_background_services_and_other_users_programs_are_refused(self):
        with self.assertRaises(fixes.FixError):
            self.prepare("4321", info(session=0))
        with self.assertRaises(fixes.FixError):
            self.prepare("4321", info(session=3), session=1)

    def test_jarvis_itself_and_pid_zero_to_four_are_refused(self):
        for pid in (0, 4, os.getpid(), os.getppid()):
            with self.assertRaises(fixes.FixError, msg=str(pid)):
                self.prepare(str(pid), info(pid=pid))
        with self.assertRaises(fixes.FixError):
            self.prepare("777", info(pid=777), supervisor=777)

    def test_a_missing_program_is_explained(self):
        with self.assertRaises(fixes.FixError):
            self.prepare("4321", "{}")

    def test_running_it_asks_nicely_then_checks_it_closed(self):
        p = self.prepare("4321", info())
        calls = []
        later = iter([info(), "{}"])                                  # still there when re-checked before closing, gone afterwards
        with mock.patch.object(fixes.diagnostics, "powershell_json", side_effect=lambda *a, **k: json.loads(next(later))),                 mock.patch.object(fixes.subprocess, "run", side_effect=lambda cmd, **k: calls.append(cmd)), mock.patch.object(fixes.time, "sleep"):
            result = p.run()
        self.assertEqual(calls, [["taskkill", "/PID", "4321"]])         # a polite request only: no /F because it closed
        self.assertEqual(result, "Closed notepad.")

    def test_it_is_forced_only_if_it_ignores_the_polite_request(self):
        p = self.prepare("4321", info())
        calls = []
        with mock.patch.object(fixes.diagnostics, "powershell_json", return_value=json.loads(info())), \
                mock.patch.object(fixes.subprocess, "run", side_effect=lambda cmd, **k: calls.append(cmd)), mock.patch.object(fixes.time, "sleep"):
            result = p.run()
        self.assertIn(["taskkill", "/PID", "4321", "/F"], calls)
        self.assertTrue(result.startswith("Error"))

    def test_a_different_program_with_a_reused_id_is_left_alone(self):
        p = self.prepare("4321", info(name="notepad"))
        with mock.patch.object(fixes.diagnostics, "powershell_json", return_value=json.loads(info(name="other"))), \
                mock.patch.object(fixes.subprocess, "run") as run:
            result = p.run()
        run.assert_not_called()
        self.assertIn("already closed", result)


class Restart(unittest.TestCase):
    def test_refused_when_nothing_would_bring_it_back(self):
        with mock.patch.object(fixes, "supervisor_pid_now", return_value=None), self.assertRaises(fixes.FixError):
            fixes.prepare_restart_jarvis()

    def test_exits_shortly_after_answering(self):
        quit_now = mock.Mock()
        p = fixes.prepare_restart_jarvis(supervisor_pid=1234, exit_fn=quit_now)
        with mock.patch.object(fixes.threading, "Timer") as timer:
            self.assertIn("restarting", p.run())
        timer.assert_called_once_with(2.0, quit_now)
        quit_now.assert_not_called()

    def test_pid_alive_for_this_process_and_a_dead_one(self):
        self.assertTrue(fixes.pid_alive(os.getpid()))
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        self.assertFalse(fixes.pid_alive(child.pid))


class Simple(unittest.TestCase):
    def test_unknown_fix_is_refused(self):
        with self.assertRaises(fixes.FixError):
            fixes.prepare("format_disk")

    def test_hooked_fixes_say_when_unavailable(self):
        with mock.patch.dict(fixes.hooks, clear=True):
            p = fixes.prepare("restart_wake_word")
            self.assertTrue(fixes.execute(p, "restart_wake_word").startswith("Error"))
        with mock.patch.dict(fixes.hooks, {"reload_tools": lambda: "Reconnecting."}):
            self.assertEqual(fixes.execute(fixes.prepare("reload_tools"), "reload_tools"), "Reconnecting.")

    def test_flush_dns_reports_success_and_failure(self):
        ok = subprocess.CompletedProcess([], 0, "Successfully flushed", "")
        self.assertEqual(fixes.flush_dns(run=lambda: ok), "DNS cache cleared.")
        bad = subprocess.CompletedProcess([], 1, "", "access denied")
        self.assertTrue(fixes.flush_dns(run=lambda: bad).startswith("Error"))

    def test_a_crashing_fix_becomes_an_error_line(self):
        p = fixes.Prepared("t", "p", lambda: 1 / 0)
        with self.assertLogs("jarvis", "ERROR"):
            self.assertTrue(fixes.execute(p, "x").startswith("Error"))


class AskFirst(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(audit, "LOG_FILE", Path(tmp.name) / "a.log")
        patch.start()
        self.addCleanup(patch.stop)

    def go(self, args, allow):
        with mock.patch.object(agent.runner, "wait", return_value=allow):
            return list(agent._run_action("system_fix", args))

    def test_the_card_shows_the_exact_action_and_nothing_runs_when_declined(self):
        ran = mock.Mock(return_value="done")
        with mock.patch.object(fixes, "prepare", return_value=fixes.Prepared("JARVIS wants to X", "Does exactly X.", ran)):
            events = self.go({"action": "flush_dns"}, allow=False)
        ran.assert_not_called()
        self.assertEqual(events[0]["title"], "JARVIS wants to X")
        self.assertEqual(events[0]["code"], "Does exactly X.")
        self.assertIn("did not allow", events[-1])

    def test_allowed_fix_runs_once_and_reports(self):
        ran = mock.Mock(return_value="DNS cache cleared.")
        with mock.patch.object(fixes, "prepare", return_value=fixes.Prepared("t", "p", ran)):
            events = self.go({"action": "flush_dns"}, allow=True)
        ran.assert_called_once()
        self.assertEqual(events[-1], "DNS cache cleared.")

    def test_a_refused_fix_never_reaches_the_user(self):
        with mock.patch.object(agent.runner, "request") as asked:
            events = list(agent._run_action("system_fix", {"action": "end_program", "target": "chrome"}))
        asked.assert_not_called()
        self.assertTrue(events[-1].startswith("Error"))

    def test_the_tool_is_an_action_that_asks_first(self):
        self.assertIn("system_fix", agent.ACTION_TOOLS)
        self.assertIn("system_fix", {t["function"]["name"] for t in agent.active_tools()})
        self.assertEqual(agent._step_text("system_fix", {}), "Preparing a fix")
        self.assertEqual(audit.describe("system_fix", {"action": "end_program", "target": "12"}), "end_program 12")

    def test_main_provides_the_two_hooks(self):
        from server import main  # noqa: F401 - importing wires the hooks
        self.assertTrue({"restart_wake_word", "reload_tools"} <= set(fixes.hooks))
        with mock.patch.dict("os.environ", {"JARVIS_WAKEWORD": "0"}), self.assertRaises(fixes.FixError):
            fixes.hooks["restart_wake_word"]()


if __name__ == "__main__":
    unittest.main()
