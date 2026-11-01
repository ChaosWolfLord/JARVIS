"""Tests for the MCP connector: config, the stdio and HTTP clients (against a fake server), tool names, approvals."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, agent_tools, mcp  # noqa: E402

httpx = agent_tools.httpx
FAKE = str(Path(__file__).resolve().parent / "fake_mcp_server.py")


def write_config(tmp, servers):
    path = Path(tmp) / "mcp.json"
    path.write_text(json.dumps({"servers": servers}))
    return path


def stdio(autoapprove=None, **extra):
    cfg = {"command": sys.executable, "args": ["-u", FAKE], **extra}
    if autoapprove is not None:
        cfg["autoApprove"] = autoapprove
    return cfg


class Config(unittest.TestCase):
    def test_missing_file_is_just_no_servers(self):
        self.assertEqual(mcp.load_config(Path("nowhere.json")), {})

    def test_bad_entries_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_config(tmp, {"good": {"command": "x"}, "off": {"command": "x", "disabled": True}, "empty": {},
                                      "bad name!": {"command": "x"}, "remote": {"url": "https://example.com/mcp"}, "oops": "text"})
            self.assertEqual(sorted(mcp.load_config(path)), ["good", "remote"])
            path.write_text("{ not json")
            self.assertEqual(mcp.load_config(path), {})

    def test_the_claude_desktop_layout_works_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text(json.dumps({"mcpServers": {"files": {"command": "npx", "args": ["-y", "x"]}}}))
            self.assertEqual(list(mcp.load_config(path)), ["files"])

    def test_dollar_names_come_from_the_environment(self):
        self.assertEqual(mcp.expand({"a": ["${TOKEN}", "x"], "b": "Bearer ${TOKEN}", "c": "${MISSING}"}, {"TOKEN": "t0k"}),
                         {"a": ["t0k", "x"], "b": "Bearer t0k", "c": ""})


class Names(unittest.TestCase):
    def test_function_names_are_clean_unique_and_short(self):
        taken = set()
        a = mcp.tool_function_name("files", "read file!", taken)
        b = mcp.tool_function_name("files", "read_file_", taken)             # cleans to the same name
        long = mcp.tool_function_name("files", "x" * 100, taken)
        self.assertEqual(a, "mcp__files__read_file_")
        self.assertNotEqual(a, b)
        self.assertLessEqual(len(long), 64)
        for name in (a, b, long):
            self.assertRegex(name, r"^[A-Za-z0-9_-]{1,64}$")

    def test_schemas_are_made_acceptable(self):
        cleaned = mcp.clean_schema({"$schema": "http://x", "type": "object", "properties": {"a": {"type": "string", "$schema": "y"}}})
        self.assertNotIn("$schema", json.dumps(cleaned))
        self.assertEqual(mcp.clean_schema({}), {"type": "object", "properties": {}})
        self.assertEqual(mcp.clean_schema("nonsense"), {"type": "object", "properties": {}})
        self.assertEqual(mcp.clean_schema({"type": "array"}), {"type": "object", "properties": {}})

    def test_result_text(self):
        self.assertEqual(mcp.result_text({"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]}), "a\nb")
        self.assertIn("image", mcp.result_text({"content": [{"type": "image", "data": "...", "mimeType": "image/png"}]}))
        self.assertEqual(mcp.result_text({"content": [{"type": "resource", "resource": {"uri": "x", "text": "body"}}]}), "body")
        self.assertIn("nothing", mcp.result_text({"content": []}))


class Stdio(unittest.TestCase):
    def manager(self, servers):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        m = mcp.Manager(write_config(tmp.name, servers))
        self.addCleanup(m.stop)
        m.start(wait=True)
        return m

    def test_connects_lists_all_pages_and_names_the_tools(self):
        m = self.manager({"fake": stdio()})
        self.assertEqual(m.status()["servers"][0]["state"], "ready")
        names = sorted(t["function"]["name"] for t in m.openai_tools())
        self.assertEqual(names, ["mcp__fake__add", "mcp__fake__boom", "mcp__fake__die", "mcp__fake__echo", "mcp__fake__slow", "mcp__fake__weird_name_"])
        echo = next(t for t in m.openai_tools() if t["function"]["name"].endswith("echo"))
        self.assertEqual(echo["function"]["description"], "[fake] Repeat the text back.")
        self.assertNotIn("$schema", json.dumps(echo))

    def test_a_call_returns_the_tools_text(self):
        m = self.manager({"fake": stdio()})
        self.assertEqual(m.call("mcp__fake__echo", {"text": "hi"}), "echo: hi")
        self.assertEqual(m.call("mcp__fake__add", {"a": 2, "b": 3}), "5")

    def test_a_tool_that_reports_an_error_is_marked_as_one(self):
        m = self.manager({"fake": stdio()})
        out = m.call("mcp__fake__boom", {})
        self.assertTrue(out.startswith("Error"))
        self.assertIn("it went wrong", out)

    def test_a_server_that_stops_gives_a_message_not_a_crash(self):
        m = self.manager({"fake": stdio()})
        m.call("mcp__fake__die", {})
        time.sleep(0.5)
        self.assertTrue(m.call("mcp__fake__echo", {"text": "x"}).startswith("Error"))

    def test_a_slow_tool_times_out(self):
        m = self.manager({"fake": stdio()})
        with mock.patch.object(mcp, "CALL_TIMEOUT", 0.5):
            out = m.call("mcp__fake__slow", {})
        self.assertTrue(out.startswith("Error"))
        self.assertIn("no answer", out)

    def test_a_server_that_cant_start_is_reported_and_others_still_work(self):
        m = self.manager({"fake": stdio(), "broken": {"command": "definitely-not-a-program-xyz"}})
        states = {s["name"]: s for s in m.status()["servers"]}
        self.assertEqual(states["fake"]["state"], "ready")
        self.assertEqual(states["broken"]["state"], "error")
        self.assertIn("couldn't start", states["broken"]["error"])
        self.assertEqual(m.call("mcp__fake__echo", {"text": "ok"}), "echo: ok")

    def test_unknown_tool_name(self):
        m = self.manager({"fake": stdio()})
        self.assertTrue(m.call("mcp__fake__nope", {}).startswith("Error"))

    def test_approval_is_required_unless_the_tool_is_listed(self):
        m = self.manager({"fake": stdio(autoapprove=["echo"])})
        self.assertFalse(m.needs_approval("mcp__fake__echo"))
        self.assertTrue(m.needs_approval("mcp__fake__add"))
        m2 = self.manager({"fake": stdio(autoapprove=True)})
        self.assertFalse(m2.needs_approval("mcp__fake__add"))
        m3 = self.manager({"fake": stdio()})
        self.assertTrue(m3.needs_approval("mcp__fake__echo"))

    def test_reload_replaces_the_servers(self):
        m = self.manager({"fake": stdio()})
        first = m.servers["fake"].proc
        m.start(wait=True)
        self.assertIsNotNone(first.poll())                  # the old program was stopped
        self.assertEqual(m.call("mcp__fake__echo", {"text": "again"}), "echo: again")


class Http(unittest.TestCase):
    def conn(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        return mcp.HttpConnection("web", {"url": "https://example.com/mcp", "headers": {"Authorization": "Bearer ${T}"}}, client)

    def test_json_and_event_stream_answers_and_the_session_header(self):
        seen = []

        def handler(request):
            body = json.loads(request.content)
            seen.append((body.get("method"), request.headers.get("mcp-session-id"), request.headers.get("authorization")))
            if body["method"] == "notifications/initialized":
                return httpx.Response(202)
            if body["method"] == "initialize":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {}}, headers={"Mcp-Session-Id": "abc"})
            if body["method"] == "tools/list":
                return httpx.Response(200, json={"jsonrpc": "2.0", "id": body["id"], "result": {"tools": [{"name": "ping", "inputSchema": {}}]}})
            sse = 'event: message\ndata: {"jsonrpc":"2.0","id":%d,"result":{"content":[{"type":"text","text":"pong"}]}}\n\n' % body["id"]
            return httpx.Response(200, text=sse, headers={"content-type": "text/event-stream"})

        with mock.patch.dict("os.environ", {"T": "secret"}):
            c = self.conn(handler)
            c.connect()
            self.assertEqual([t["name"] for t in c.tools], ["ping"])
            self.assertEqual(mcp.result_text(c.request("tools/call", {"name": "ping", "arguments": {}})), "pong")
        self.assertEqual(seen[0][1], None)
        self.assertTrue(all(s[1] == "abc" for s in seen[1:]))
        self.assertTrue(all(s[2] == "Bearer secret" for s in seen))

    def test_http_errors_are_explained(self):
        c = self.conn(lambda r: httpx.Response(401))
        with self.assertRaises(mcp.McpError) as cm:
            c.request("tools/list")
        self.assertIn("token", str(cm.exception))
        c = self.conn(lambda r: httpx.Response(500))
        with self.assertRaises(mcp.McpError):
            c.request("tools/list")


class InTheAgent(unittest.TestCase):
    """The agent offers MCP tools, asks before running them, and hands results back as outside data."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.m = mcp.Manager(write_config(tmp.name, {"fake": stdio(autoapprove=["echo"])}))
        self.addCleanup(self.m.stop)
        self.m.start(wait=True)
        patch = mock.patch.object(mcp, "manager", self.m)
        patch.start()
        self.addCleanup(patch.stop)
        patch2 = mock.patch.object(agent.mcp_client, "manager", self.m)
        patch2.start()
        self.addCleanup(patch2.stop)

    def test_the_tools_are_offered_to_the_model(self):
        names = {t["function"]["name"] for t in agent.active_tools()}
        self.assertIn("mcp__fake__echo", names)
        self.assertIn("web_search", names)
        self.assertTrue(agent._gives_result_back("mcp__fake__echo"))
        self.assertFalse(agent._gives_result_back("add_note"))

    def test_an_auto_approved_tool_just_runs_and_its_result_is_marked_as_outside_data(self):
        events = list(agent._run_mcp("mcp__fake__echo", {"text": "hi"}))
        self.assertEqual(events[0]["type"], "step")
        self.assertTrue(events[-1].startswith(agent_tools.UNTRUSTED))
        self.assertIn("echo: hi", events[-1])

    def test_other_tools_ask_first_and_run_only_if_allowed(self):
        with mock.patch.object(agent.runner, "wait", return_value=True):
            events = list(agent._run_mcp("mcp__fake__add", {"a": 1, "b": 2}))
        request = events[0]
        self.assertEqual((request["type"], request["kind"]), ("run_request", "tool"))
        self.assertIn("add from fake", request["title"])
        self.assertIn('"a": 1', request["code"])
        self.assertEqual(events[1]["type"], "run_result")
        self.assertIn("3", events[-1])

        with mock.patch.object(agent.runner, "wait", return_value=False), mock.patch.object(self.m, "call") as call:
            events = list(agent._run_mcp("mcp__fake__add", {"a": 1, "b": 2}))
        call.assert_not_called()
        self.assertTrue(events[1]["declined"])
        self.assertIn("did not allow", events[-1])


if __name__ == "__main__":
    unittest.main()
