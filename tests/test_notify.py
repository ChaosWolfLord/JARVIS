"""Tests for the Claude Code announcements: the token-guarded message slot in JARVIS, and the hook script that sends to it.
Nothing is spoken and no real hook settings are touched."""
import asyncio
import http.server
import importlib.util
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import audit, notify, persona  # noqa: E402

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "claude_notify.py"
spec = importlib.util.spec_from_file_location("claude_notify", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class Token(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.path = self.dir / "notify.token"

    def test_created_once_and_stable(self):
        first = notify.token(self.path)
        self.assertGreaterEqual(len(first), 32)
        self.assertEqual(notify.token(self.path), first)

    def test_only_the_right_token_is_accepted(self):
        good = notify.token(self.path)
        self.assertTrue(notify.valid(good, self.path))
        for bad in (None, "", "nope", good + "x", good[:-1]):
            self.assertFalse(notify.valid(bad, self.path), repr(bad))

    def test_a_too_short_or_damaged_token_file_is_replaced(self):
        self.path.write_text("abc", "utf-8")
        self.assertGreaterEqual(len(notify.token(self.path)), 32)


class Wording(unittest.TestCase):
    def test_every_kind_is_worded_by_jarvis_not_the_sender(self):
        for kind in notify.KINDS:
            for snark in ("0", "1", "2", "3"):
                with mock.patch.dict("os.environ", {"JARVIS_SNARK": snark}):
                    event = notify.compose(kind, "JARVIS")
                self.assertIn("Claude", event["text"])
                self.assertIn("in JARVIS", event["text"])
                self.assertEqual(event["speak"], event["text"])
        self.assertEqual(notify.compose("permission", "x")["level"], "warn")
        self.assertEqual(notify.compose("finished", "x")["level"], "info")

    def test_the_plainest_mood(self):
        with mock.patch.dict("os.environ", {"JARVIS_SNARK": "0"}):
            self.assertEqual(notify.compose("finished", "Cyberpi Test")["text"], "Claude has finished in Cyberpi Test.")
            self.assertEqual(notify.compose("failed")["text"], "Claude stopped with an error.")

    def test_unknown_kinds_are_refused(self):
        with self.assertRaises(ValueError):
            notify.compose("say-anything")

    def test_the_project_name_is_cleaned_before_it_is_shown_or_spoken(self):
        self.assertEqual(notify.clean_project("My Project"), "My Project")
        self.assertEqual(notify.clean_project("a<script>alert(1)</script>b\n\nc"), "ascriptalert1scriptbc")
        self.assertLessEqual(len(notify.clean_project("x" * 500)), 40)
        self.assertEqual(notify.clean_project(None), "")

    def test_it_cant_talk_non_stop(self):
        clock = [100.0]
        limiter = notify.Limiter(now=lambda: clock[0])
        self.assertTrue(limiter.allow())
        clock[0] += 1
        self.assertFalse(limiter.allow())
        clock[0] += 3
        self.assertTrue(limiter.allow())


class Route(unittest.TestCase):
    def setUp(self):
        from server import main
        self.main = main
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.token = notify.token(Path(tmp.name) / "t")
        for patch in (mock.patch.object(notify, "TOKEN_FILE", Path(tmp.name) / "t"), mock.patch.object(audit, "LOG_FILE", Path(tmp.name) / "a.log"),
                      mock.patch.object(notify, "limiter", notify.Limiter(now=lambda: self.clock[0]))):
            patch.start()
            self.addCleanup(patch.stop)
        self.clock = [1000.0]
        self.sent = []

        class Viewer:
            async def send_text(inner, text):
                self.sent.append(json.loads(text))
        self.viewer = Viewer()
        main.hub.viewers.add(self.viewer)
        self.addCleanup(lambda: main.hub.viewers.discard(self.viewer))

    def post(self, kind="finished", project="JARVIS", token=None):
        return asyncio.run(self.main.post_notify(self.main.Notice(kind=kind, project=project), token if token is not None else self.token))

    def test_the_right_token_reaches_the_page(self):
        self.assertEqual(self.post()["sent"] >= 1, True)
        message = next(m for m in self.sent if m["type"] == "notify")
        self.assertEqual(message["title"], "Claude Code")
        self.assertIn("in JARVIS", message["text"])

    def test_a_missing_or_wrong_token_is_refused_and_logged(self):
        for token in ("wrong", ""):
            with self.assertRaises(self.main.HTTPException) as caught:
                asyncio.run(self.main.post_notify(self.main.Notice(kind="finished"), token or None))
            self.assertEqual(caught.exception.status_code, 403)
        self.assertEqual([m for m in self.sent if m["type"] == "notify"], [])
        self.assertTrue(any(e["kind"] == "blocked" for e in audit.recent()))

    def test_the_sender_cannot_pick_the_words(self):
        with self.assertRaises(Exception):
            self.main.Notice(kind="say this instead")
        with self.assertRaises(Exception):
            self.main.Notice(kind="finished", project="x" * 500)

    def test_a_burst_is_cut_down_and_the_switch_works(self):
        self.post()
        self.assertEqual(self.post()["sent"], 0)
        self.clock[0] += 10
        with mock.patch.dict("os.environ", {"JARVIS_CLAUDE_NOTIFY": "0"}):
            self.assertEqual(self.post()["sent"], 0)

    def test_each_announcement_is_logged_without_the_token(self):
        self.post()
        entry = audit.recent()[0]
        self.assertEqual((entry["kind"], entry["what"]), ("notify", "claude finished JARVIS"))
        self.assertNotIn(self.token, json.dumps(audit.recent()))


class WhatToAnnounce(unittest.TestCase):
    cfg = dict(hook.DEFAULTS)

    def decide(self, payload, now=1000.0, prompts=None):
        prompts = {} if prompts is None else prompts
        return hook.decide(payload, now, self.cfg, prompts), prompts

    def test_a_long_prompt_is_announced_and_a_quick_one_is_not(self):
        _, prompts = self.decide({"hook_event_name": "UserPromptSubmit", "session_id": "s"}, now=1000.0)
        self.assertEqual(prompts, {"s": 1000.0})
        kind, prompts = self.decide({"hook_event_name": "Stop", "session_id": "s"}, now=1010.0, prompts=prompts)
        self.assertIsNone(kind)                                         # 10 s: too quick to bother you
        _, prompts = self.decide({"hook_event_name": "UserPromptSubmit", "session_id": "s"}, now=2000.0)
        kind, prompts = self.decide({"hook_event_name": "Stop", "session_id": "s"}, now=2045.0, prompts=prompts)
        self.assertEqual(kind, "finished")
        self.assertEqual(prompts, {})

    def test_a_stop_with_no_known_start_is_announced(self):
        self.assertEqual(self.decide({"hook_event_name": "Stop", "session_id": "new"})[0], "finished")

    def test_sessions_are_kept_apart(self):
        prompts = {"a": 990.0}
        self.assertEqual(self.decide({"hook_event_name": "Stop", "session_id": "b"}, prompts=prompts)[0], "finished")
        self.assertIsNone(self.decide({"hook_event_name": "Stop", "session_id": "a"}, prompts=prompts)[0])

    def test_stop_hooks_that_are_continuing_are_ignored(self):
        self.assertIsNone(self.decide({"hook_event_name": "Stop", "session_id": "s", "stop_hook_active": True})[0])

    def test_permission_waiting_and_failure(self):
        self.assertEqual(self.decide({"hook_event_name": "Notification", "notification_type": "permission_prompt", "message": "Claude needs permission to use Bash"})[0], "permission")
        self.assertEqual(self.decide({"hook_event_name": "Notification", "message": "Claude is waiting for your input"})[0], "idle")
        self.assertIsNone(self.decide({"hook_event_name": "Notification", "notification_type": "auth_success", "message": "Logged in"})[0])
        self.assertEqual(self.decide({"hook_event_name": "StopFailure", "session_id": "s"})[0], "failed")

    def test_other_events_and_old_sessions_are_cleaned_up(self):
        kind, prompts = self.decide({"hook_event_name": "PreToolUse"}, prompts={"old": 1.0})
        self.assertIsNone(kind)
        self.assertEqual(prompts, {"old": 1.0})                         # only pruned once a day has passed
        _, prompts = self.decide({"hook_event_name": "SessionEnd", "session_id": "old"}, now=1e6, prompts={"old": 1.0, "recent": 1e6 - 5})
        self.assertEqual(prompts, {"recent": 1e6 - 5})

    def test_the_project_name_comes_from_the_folder(self):
        self.assertEqual(hook.project_name(r"C:\Users\you\OneDrive\Code\Cyberpi Test"), "Cyberpi Test")
        self.assertEqual(hook.project_name(""), "")


class TheScript(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.args = dict(config_path=self.dir / "c.json", prompts_path=self.dir / "p.json", token_path=self.dir / "t")
        self.calls = []
        self.sender = lambda kind, project, config, token: self.calls.append((kind, project, token)) or True

    def run_hook(self, payload, now=1000.0, **over):
        return hook.main(json.dumps(payload) if not isinstance(payload, str) else payload, now=now, sender=self.sender, **{**self.args, **over})

    def test_nothing_is_sent_before_jarvis_has_ever_run(self):
        self.assertEqual(self.run_hook({"hook_event_name": "Stop", "session_id": "s", "cwd": "C:/x/JARVIS"}), 0)
        self.assertEqual(self.calls, [])

    def test_it_sends_the_kind_project_and_token(self):
        self.args["token_path"].write_text("secret-token-value", "utf-8")
        self.run_hook({"hook_event_name": "Stop", "session_id": "s", "cwd": "C:/x/JARVIS"})
        self.assertEqual(self.calls, [("finished", "JARVIS", "secret-token-value")])

    def test_it_remembers_when_the_prompt_started(self):
        self.args["token_path"].write_text("t" * 24, "utf-8")
        self.run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "C:/x/P"}, now=1000.0)
        self.run_hook({"hook_event_name": "Stop", "session_id": "s", "cwd": "C:/x/P"}, now=1005.0)
        self.assertEqual(self.calls, [])
        self.run_hook({"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "C:/x/P"}, now=2000.0)
        self.run_hook({"hook_event_name": "Stop", "session_id": "s", "cwd": "C:/x/P"}, now=2100.0)
        self.assertEqual([c[0] for c in self.calls], ["finished"])

    def test_settings_can_switch_it_off_or_change_what_is_announced(self):
        self.args["token_path"].write_text("t" * 24, "utf-8")
        self.args["config_path"].write_text(json.dumps({"enabled": False}), "utf-8")
        self.run_hook({"hook_event_name": "Stop", "session_id": "s"})
        self.args["config_path"].write_text(json.dumps({"events": ["permission"], "min_seconds": 1}), "utf-8")
        self.run_hook({"hook_event_name": "Stop", "session_id": "s"})
        self.assertEqual(self.calls, [])
        self.run_hook({"hook_event_name": "Notification", "message": "needs permission"})
        self.assertEqual([c[0] for c in self.calls], ["permission"])

    def test_garbage_and_failures_never_raise(self):
        self.args["token_path"].write_text("t" * 24, "utf-8")
        for junk in ("", "not json", "[]", "null", '{"hook_event_name": 5}'):
            self.assertEqual(self.run_hook(junk), 0)
        boom = lambda *a: (_ for _ in ()).throw(RuntimeError("down"))
        self.assertEqual(hook.main('{"hook_event_name": "StopFailure"}', now=1.0, sender=boom, **self.args), 0)

    def test_it_really_posts_with_the_header_and_ignores_a_dead_jarvis(self):
        got = {}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(inner):  # noqa: N802
                got["token"] = inner.headers.get("X-Jarvis-Token")
                got["body"] = json.loads(inner.rfile.read(int(inner.headers["Content-Length"])))
                inner.send_response(200)
                inner.end_headers()
                inner.wfile.write(b"{}")

            def log_message(inner, *a):
                pass
        server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        config = {**hook.DEFAULTS, "port": server.server_address[1]}
        self.assertTrue(hook.post("finished", "JARVIS", config, "tok-123"))
        self.assertEqual((got["token"], got["body"]), ("tok-123", {"kind": "finished", "project": "JARVIS"}))
        self.assertFalse(hook.post("finished", "JARVIS", {**hook.DEFAULTS, "port": 1}, "tok"))          # nothing is listening: quietly false


class InTheApp(unittest.TestCase):
    def test_the_page_listens_for_it(self):
        root = Path(__file__).resolve().parent.parent / "web"
        self.assertIn("case 'notify'", (root / "pen.js").read_text("utf-8"))
        self.assertIn("pen.onNotify", (root / "app.js").read_text("utf-8"))

    def test_the_personality_has_a_line_for_each_kind(self):
        for kind in notify.KINDS.values():
            self.assertIn(kind, persona.LINES)


if __name__ == "__main__":
    unittest.main()
