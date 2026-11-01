"""Tests for the agent's lookup tools and for choosing OpenRouter's free models. No network: HTTP is faked."""
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, agent_tools, openrouter  # noqa: E402

httpx = agent_tools.httpx   # whichever name the installed HTTP library has

_memory_dir = _memory_patch = None


def setUpModule():
    """Running a chat turn reads (and counts uses in) the memory file: point it at a throwaway one, never the user's."""
    global _memory_dir, _memory_patch, _log_patch
    _memory_dir = tempfile.TemporaryDirectory()
    _memory_patch = mock.patch.object(agent.store, "MEMORY_FILE", Path(_memory_dir.name) / "memory.json")
    _log_patch = mock.patch.object(agent.audit, "LOG_FILE", Path(_memory_dir.name) / "activity.log")   # nor the activity log
    _memory_patch.start()
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()
    _memory_patch.stop()
    _memory_dir.cleanup()


def resolver(ip):
    return lambda host, port, proto=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


class CheckUrl(unittest.TestCase):
    def test_public_https_is_allowed(self):
        self.assertIsNone(agent_tools.check_url("https://example.com/a?b=1", resolver("93.184.216.34")))

    def test_this_pc_and_the_home_network_are_refused(self):
        for ip in ("127.0.0.1", "192.168.1.1", "10.0.0.5", "172.16.3.4", "169.254.1.1", "0.0.0.0", "::1"):
            self.assertIsNotNone(agent_tools.check_url("http://site.example/", resolver(ip)), ip)

    def test_names_that_point_home_are_refused_without_a_lookup(self):
        for url in ("http://localhost:8000/api/status", "http://printer.local/", "http://nas.lan/"):
            self.assertIsNotNone(agent_tools.check_url(url, resolver("93.184.216.34")), url)

    def test_other_schemes_are_refused(self):
        for url in ("file:///C:/Windows/win.ini", "ftp://example.com/x", "javascript:alert(1)", "http://"):
            self.assertIsNotNone(agent_tools.check_url(url, resolver("93.184.216.34")), url)

    def test_unknown_host(self):
        def nope(*a, **k):
            raise socket.gaierror
        self.assertIn("not be found", agent_tools.check_url("https://nope.example/", nope))


class Fetch(unittest.TestCase):
    def client(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    def test_page_text_is_extracted_and_marked_untrusted(self):
        page = ("<html><head><title>Hello</title><style>p{}</style></head><body><script>evil()</script>"
                "<h1>Big</h1><p>First   para</p><p>Second</p></body></html>")
        c = self.client(lambda r: httpx.Response(200, text=page, headers={"content-type": "text/html"}))
        out = agent_tools.fetch_url("https://example.com/", c, resolver("93.184.216.34"))
        self.assertTrue(out.startswith(agent_tools.UNTRUSTED))
        self.assertIn("Title: Hello", out)
        self.assertIn("First para", out)
        self.assertNotIn("evil()", out)
        self.assertNotIn("p{}", out)

    def test_a_redirect_to_the_home_network_is_refused(self):
        def handler(request):
            if request.url.host == "example.com":
                return httpx.Response(302, headers={"location": "http://192.168.0.1/admin"})
            return httpx.Response(200, text="router admin")
        addresses = {"example.com": "93.184.216.34", "192.168.0.1": "192.168.0.1"}
        def resolve(host, port, proto=0):
            return resolver(addresses[host])(host, port)
        out = agent_tools.fetch_url("https://example.com/", self.client(handler), resolve)
        self.assertTrue(out.startswith("Error"))
        self.assertNotIn("router admin", out)

    def test_http_errors_and_binary_files_are_reported(self):
        c = self.client(lambda r: httpx.Response(404))
        self.assertIn("404", agent_tools.fetch_url("https://example.com/x", c, resolver("93.184.216.34")))
        c = self.client(lambda r: httpx.Response(200, content=b"\x00\x01", headers={"content-type": "application/pdf"}))
        self.assertIn("not a text page", agent_tools.fetch_url("https://example.com/x.pdf", c, resolver("93.184.216.34")))

    def test_long_pages_are_trimmed(self):
        c = self.client(lambda r: httpx.Response(200, text="word " * 5000, headers={"content-type": "text/plain"}))
        out = agent_tools.fetch_url("https://example.com/", c, resolver("93.184.216.34"))
        self.assertLess(len(out), agent_tools.MAX_RESULT_CHARS + 400)
        self.assertIn("[trimmed]", out)


class Search(unittest.TestCase):
    PAGE = (
        '<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg='
        'https%3A%2F%2Fexample.org%2Fone&amp;rut=abc">First <b>result</b></a>'
        '<a class="result__snippet" href="x">Snippet &amp; one</a></div>'
        '<div class="result"><a rel="nofollow" class="result__a" href="https://example.net/two">Second</a>'
        '<a class="result__snippet" href="y">Snippet two</a></div>'
        '<div class="result"><a rel="nofollow" class="result__a" href="//duckduckgo.com/y.js?ad=1">An advert</a></div>'
    )

    def test_results_are_parsed_and_adverts_dropped(self):
        results = agent_tools.parse_search(self.PAGE)
        self.assertEqual([r["url"] for r in results], ["https://example.org/one", "https://example.net/two"])
        self.assertEqual(results[0]["title"], "First result")
        self.assertEqual(results[0]["snippet"], "Snippet & one")

    def test_search_wraps_results(self):
        c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=self.PAGE)))
        out = agent_tools.web_search("anything", c)
        self.assertTrue(out.startswith(agent_tools.UNTRUSTED))
        self.assertIn("https://example.org/one", out)

    def test_blocked_search_says_so(self):
        c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>captcha</html>")))
        self.assertIn("No results", agent_tools.web_search("x", c))


class Workspace(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "workspace"
        self.root.mkdir()
        (self.root / "notes.txt").write_text("buy resistors", "utf-8")
        (Path(self.tmp.name) / "secret.txt").write_text("keys", "utf-8")
        self.patch = mock.patch.object(agent_tools, "WORKSPACE", self.root)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_reads_a_file_inside_the_workspace(self):
        self.assertIn("buy resistors", agent_tools.read_file("notes.txt"))
        self.assertIn("notes.txt", agent_tools.list_files())

    def test_cannot_leave_the_workspace(self):
        for path in ("../secret.txt", "..\\secret.txt", str(Path(self.tmp.name) / "secret.txt"), "sub/../../secret.txt"):
            out = agent_tools.read_file(path)
            self.assertTrue(out.startswith("Error"), path)
            self.assertNotIn("keys", out)


def model(id_, free=True, tools=True, image=False, out=("text",), ctx=100_000):
    price = "0" if free else "0.000001"
    return {"id": id_, "context_length": ctx, "pricing": {"prompt": price, "completion": price},
            "supported_parameters": ["tools", "temperature"] if tools else ["temperature"],
            "architecture": {"input_modalities": ["text", "image"] if image else ["text"], "output_modalities": list(out)}}


class FreeModels(unittest.TestCase):
    def test_only_free_tool_capable_text_models_are_kept(self):
        data = [
            model("a/big:free", image=True, ctx=262_144),
            model("b/paid", free=False),
            model("c/no-tools:free", tools=False),
            model("d/media:free", out=("image",)),
            model("e/safety-classifier:free"),
            model("f/tiny-2.6b:free"),
            model("g/gemma-31b-it:free", image=True, ctx=262_144),   # 31b is a big model, not a tiny one
            model("openrouter/free", image=True, ctx=200_000),
            model("h/text-only:free", ctx=1_000_000),
        ]
        ids = [m["id"] for m in openrouter.pick_free(data)]
        self.assertEqual(sorted(ids), sorted(["a/big:free", "g/gemma-31b-it:free", "h/text-only:free", "openrouter/free"]))

    def test_models_that_see_images_come_first_and_the_router_last(self):
        data = [model("t/text:free", ctx=1_000_000), model("openrouter/free", image=True), model("v/vision:free", image=True)]
        self.assertEqual([m["id"] for m in openrouter.pick_free(data)], ["v/vision:free", "t/text:free", "openrouter/free"])

    def test_preferred_models_can_be_forced_to_the_front(self):
        data = [model("v/vision:free", image=True), model("t/text:free")]
        self.assertEqual(openrouter.pick_free(data, first=["t/text:free"])[0]["id"], "t/text:free")

    def test_offline_falls_back_to_a_short_list(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(openrouter, "CACHE_FILE", Path(tmp) / "m.json"), \
                mock.patch.object(openrouter.httpx, "get", side_effect=httpx.ConnectError("offline")):
            self.assertEqual(openrouter.free_models(), openrouter.FALLBACK)

    def test_a_fresh_cache_is_used_without_the_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "m.json"
            cache.write_text(json.dumps({"fetched": __import__("time").time(), "models": [{"id": "x:free", "vision": False}]}))
            with mock.patch.object(openrouter, "CACHE_FILE", cache), \
                    mock.patch.object(openrouter.httpx, "get", side_effect=AssertionError("should not fetch")):
                self.assertEqual(openrouter.free_models(), [{"id": "x:free", "vision": False}])


class Wiring(unittest.TestCase):
    def test_lookups_continue_the_turn_but_board_tools_end_it(self):
        self.assertTrue({"web_search", "fetch_url", "read_file", "list_files", "run_python"} <= agent.FOLLOW_UP_TOOLS)
        self.assertFalse({"add_note", "draw", "remember"} & agent.FOLLOW_UP_TOOLS)

    def test_every_tool_is_defined_once_with_a_runner(self):
        names = [t["function"]["name"] for t in agent.TOOLS]
        self.assertEqual(len(names), len(set(names)))
        for name in agent.FOLLOW_UP_TOOLS - {"run_python"}:
            self.assertIn(name, names)
            self.assertTrue(agent._step_text(name, {"query": "q", "url": "u", "path": "p"}))

    def test_openrouter_free_list_expands_in_a_chain(self):
        with mock.patch.dict("os.environ", {"JARVIS_CHAIN": "openrouter:auto-free,groq:x"}, clear=False), \
                mock.patch.object(openrouter, "free_models",
                                  return_value=[{"id": "a:free", "vision": True}, {"id": "b:free", "vision": False}]):
            chain = agent._parse_chain()
        self.assertEqual([t.key for t in chain], ["openrouter:a:free", "openrouter:b:free", "groq:x"])
        self.assertIn("openrouter:b:free", agent._text_only)
        self.assertFalse(agent._can_see(agent.Target("openrouter", "b:free")))


def scripted(rounds):
    """A stand-in for agent._run_round that replays model answers: each is (text, [(tool, args), ...])."""
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


class Loop(unittest.TestCase):
    def run_turn(self, rounds, lookup="RESULT"):
        target = agent.Target("openrouter", "t:free")
        calls = []
        with mock.patch.object(agent, "_run_round", scripted(rounds)), \
                mock.patch.object(agent, "CHAIN", [target]), mock.patch.object(agent, "usable", return_value=[target]), \
                mock.patch.object(agent, "_refresh_chain"), mock.patch.object(agent, "_openrouter_notice", return_value=None), \
                mock.patch.object(agent, "_run_lookup", side_effect=lambda n, a: calls.append((n, a)) or lookup):
            events = list(agent.chat_turn("question", [], None))
        return events, calls

    def test_a_lookup_is_run_then_the_model_answers(self):
        events, calls = self.run_turn([("", [("web_search", {"query": "arducam"})]), ("It costs $50.", [])])
        self.assertEqual(calls, [("web_search", {"query": "arducam"})])
        kinds = [e["type"] for e in events]
        self.assertIn("step", kinds)
        self.assertLess(kinds.index("step"), kinds.index("text"))
        self.assertEqual("".join(e["delta"] for e in events if e["type"] == "text"), "It costs $50.")
        self.assertNotIn("notice", kinds)

    def test_a_search_then_a_read_then_an_answer(self):
        events, calls = self.run_turn([
            ("", [("web_search", {"query": "x"})]),
            ("", [("fetch_url", {"url": "https://example.com"})]),
            ("Done.", []),
        ])
        self.assertEqual([c[0] for c in calls], ["web_search", "fetch_url"])
        self.assertEqual([e["text"] for e in events if e["type"] == "step"], ["Searching: x", "Reading: https://example.com"])

    def test_board_tools_end_the_turn_without_another_model_call(self):
        rounds = [("Noted.", [("add_note", {"text": "buy resistors"})])]   # a second call would raise StopIteration
        events, calls = self.run_turn(rounds)
        self.assertEqual(calls, [])
        self.assertIn("add_note", [e["type"] for e in events])

    def test_a_model_that_never_stops_looking_things_up_is_cut_off(self):
        endless = [("", [("web_search", {"query": "again"})])] * (agent.MAX_ROUNDS + 3)
        events, calls = self.run_turn(endless)
        self.assertEqual(len(calls), agent.MAX_ROUNDS)
        self.assertTrue(any(e["type"] == "notice" and "Stopped after" in e["text"] for e in events))
        self.assertEqual(events[-1]["type"], "done")

    def test_each_step_announces_its_number_and_the_limit(self):
        events, _ = self.run_turn([("", [("web_search", {"query": "x"})]), ("Done.", [])])
        steps = [(e["step"], e["max"]) for e in events if e["type"] == "progress"]
        self.assertEqual(steps, [(1, agent.MAX_ROUNDS), (2, agent.MAX_ROUNDS)])

    def test_stop_before_the_first_step_makes_no_model_call(self):
        import threading
        stop = threading.Event()
        stop.set()
        target = agent.Target("openrouter", "t:free")
        with mock.patch.object(agent, "_run_round", side_effect=AssertionError("no call expected")), \
                mock.patch.object(agent, "CHAIN", [target]), mock.patch.object(agent, "usable", return_value=[target]), \
                mock.patch.object(agent, "_refresh_chain"), mock.patch.object(agent, "_openrouter_notice", return_value=None):
            events = list(agent.chat_turn("q", [], None, stop))
        self.assertIn("Stopped.", [e.get("text") for e in events])
        self.assertEqual(events[-1]["type"], "done")

    def test_stop_during_a_model_call_skips_its_tools(self):
        import threading
        stop = threading.Event()
        ran = []
        def round_that_gets_stopped(msgs, cancel=None):
            stop.set()                                              # the user pressed Stop while the model was answering
            r = agent._Round()
            r.calls = {0: {"id": "c0", "name": "web_search", "args": "{}", "extra": {}}}
            yield {"type": "_round", "target": agent.Target("openrouter", "t:free"), "round": r}
        target = agent.Target("openrouter", "t:free")
        with mock.patch.object(agent, "_run_round", round_that_gets_stopped), \
                mock.patch.object(agent, "CHAIN", [target]), mock.patch.object(agent, "usable", return_value=[target]), \
                mock.patch.object(agent, "_refresh_chain"), mock.patch.object(agent, "_openrouter_notice", return_value=None), \
                mock.patch.object(agent, "_run_lookup", side_effect=lambda n, a: ran.append(n) or "x"):
            events = list(agent.chat_turn("q", [], None, stop))
        self.assertEqual(ran, [])
        self.assertIn("Stopped.", [e.get("text") for e in events])

    def test_stop_cuts_a_streaming_answer_short_and_closes_it(self):
        import threading
        from types import SimpleNamespace as NS
        stop = threading.Event()
        closed = []

        class Stream:
            def __iter__(self):
                yield NS(usage=None, choices=[NS(delta=NS(content="Hello ", tool_calls=None), finish_reason=None)])
                stop.set()                                           # the user presses Stop after the first words
                yield NS(usage=None, choices=[NS(delta=NS(content="world", tool_calls=None), finish_reason=None)])

            def close(self):
                closed.append(True)

        r = agent._Round()
        list(agent._consume(Stream(), r, stop))
        self.assertEqual(r.text, "Hello ")
        self.assertEqual(closed, [True])

    def test_a_crashing_tool_is_reported_to_the_model_not_raised(self):
        target = agent.Target("openrouter", "t:free")
        with mock.patch.object(agent, "_run_round", scripted([("", [("fetch_url", {"url": "x"})]), ("Sorry.", [])])), \
                mock.patch.object(agent, "CHAIN", [target]), mock.patch.object(agent, "usable", return_value=[target]), \
                mock.patch.object(agent, "_refresh_chain"), mock.patch.object(agent, "_openrouter_notice", return_value=None), \
                mock.patch.object(agent, "_run_lookup", side_effect=RuntimeError("boom")):
            events = list(agent.chat_turn("q", [], None))
        self.assertFalse(any(e["type"] == "error" for e in events))
        self.assertEqual("".join(e["delta"] for e in events if e["type"] == "text"), "Sorry.")


class TokenHistory(unittest.TestCase):
    def test_tokens_are_added_up_per_day_and_per_model(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent.store, "HISTORY_FILE", Path(tmp) / "h.json"):
            agent.store.record_usage("openrouter", "a:free", 1000, 200)
            agent.store.record_usage("openrouter", "a:free", 500, 100, exact=False)
            agent.store.record_usage("groq", "b", 50, 5)
            s = agent.store.usage_summary()
        self.assertEqual(s["today"]["tokens"], 1855)
        self.assertEqual(s["today"]["requests"], 3)
        self.assertEqual(s["models"][0], {"name": "openrouter:a:free", "tokens": 1800})
        self.assertAlmostEqual(s["estimated_share"], 0.33, places=2)

    def sample(self, today):
        from datetime import timedelta
        mk = lambda tokens: {"requests": 2, "prompt": tokens, "completion": 0, "estimated": 0, "models": {"m": tokens}}
        return {
            (today - timedelta(days=0)).isoformat(): mk(1000),
            (today - timedelta(days=1)).isoformat(): mk(3000),
            (today - timedelta(days=20)).isoformat(): mk(2000),
            (today - timedelta(days=400)).isoformat(): mk(8000),
        }

    def test_averages_use_only_the_days_jarvis_has_existed(self):
        from datetime import date
        today = date(2026, 10, 27)
        s = agent.store.usage_summary(today, self.sample(today))
        self.assertEqual(s["today"]["tokens"], 1000)
        self.assertEqual(s["week"]["tokens"], 4000)
        self.assertEqual(s["week"]["avg_per_day"], round(4000 / 7))
        self.assertEqual(s["month"]["tokens"], 6000)
        self.assertEqual(s["month"]["avg_per_day"], 200)
        self.assertEqual(s["year"]["tokens"], 6000)           # the 400-day-old day is outside the last 365
        self.assertEqual(s["all"]["tokens"], 14000)
        self.assertEqual(s["all"]["since"], "2025-09-22")

    def test_a_brand_new_install_isnt_averaged_over_a_year_of_nothing(self):
        from datetime import date
        today = date(2026, 10, 27)
        s = agent.store.usage_summary(today, {today.isoformat(): {"requests": 1, "prompt": 700, "completion": 0, "estimated": 0, "models": {}}})
        self.assertEqual(s["year"]["avg_per_day"], 700)
        self.assertEqual(s["year"]["days"], 1)

    def test_series_have_the_right_length_and_end_today(self):
        from datetime import date
        today = date(2026, 10, 27)
        s = agent.store.usage_summary(today, self.sample(today))
        self.assertEqual((len(s["daily"]), len(s["weekly"]), len(s["monthly"])), (30, 12, 12))
        self.assertEqual(s["daily"][-1], {"label": "Oct 27", "tokens": 1000, "requests": 2})
        self.assertEqual(s["monthly"][-1]["label"], "Oct 26")
        self.assertEqual(s["monthly"][-1]["tokens"], 6000)
        self.assertEqual([y["label"] for y in s["yearly"]], ["2025", "2026"])
        self.assertEqual(sum(w["tokens"] for w in s["weekly"]), 6000)

    def test_december_rolls_into_january_without_error(self):
        from datetime import date
        s = agent.store.usage_summary(date(2026, 12, 31), {})
        self.assertEqual(s["monthly"][-1]["label"], "Dec 26")
        self.assertEqual(agent.store.usage_summary(date(2027, 1, 5), {})["monthly"][0]["label"], "Feb 26")

    def test_provider_token_counts_are_read(self):
        from types import SimpleNamespace as NS
        self.assertEqual(agent._tokens_from(NS(usage=NS(prompt_tokens=120, completion_tokens=30))), (120, 30))
        self.assertEqual(agent._tokens_from(NS(usage=None, x_groq={"usage": {"prompt_tokens": 7, "completion_tokens": 3}})), (7, 3))
        self.assertIsNone(agent._tokens_from(NS(usage=None)))

    def test_missing_counts_are_estimated_from_text_length(self):
        r = agent._Round()
        r.text = "x" * 400
        prompt, completion = agent._estimate_tokens([{"role": "user", "content": "y" * 4000}], r)
        self.assertEqual(completion, 100)
        self.assertGreater(prompt, 1000)

    def test_the_widget_tool_shows_and_removes_cards(self):
        text, event = agent._run_client_tool("widget", {"name": "usage"})
        self.assertEqual(event, {"type": "widget", "name": "usage", "show": True})
        self.assertEqual(agent._run_client_tool("widget", {"name": "weather", "show": False})[1], {"type": "widget", "name": "weather", "show": False})
        text, event = agent._run_client_tool("widget", {"name": "bitcoin"})
        self.assertIsNone(event)
        self.assertTrue(text.startswith("Error"))

    def test_the_timer_tool_starts_and_cancels(self):
        text, event = agent._run_client_tool("timer", {"action": "start", "minutes": 10, "label": "pasta"})
        self.assertEqual(event, {"type": "timer", "action": "start", "seconds": 600, "label": "pasta"})
        self.assertIn("10 minutes (pasta)", text)
        self.assertEqual(agent._run_client_tool("timer", {"action": "start", "minutes": 0.5})[1]["seconds"], 30)
        self.assertIn("1 minute.", agent._run_client_tool("timer", {"action": "start", "minutes": 1})[0])
        self.assertEqual(agent._run_client_tool("timer", {"action": "cancel"})[1], {"type": "timer", "action": "cancel", "label": ""})
        self.assertEqual(agent._run_client_tool("timer", {"action": "cancel", "label": "pasta"})[1]["label"], "pasta")

    def test_a_timer_without_a_length_is_refused_and_huge_ones_are_capped(self):
        text, event = agent._run_client_tool("timer", {"action": "start"})
        self.assertIsNone(event)
        self.assertTrue(text.startswith("Error"))
        self.assertEqual(agent._run_client_tool("timer", {"action": "start", "minutes": 99999})[1]["seconds"], 24 * 3600)


class Usage(unittest.TestCase):
    def test_openrouter_requests_are_counted_by_utc_day(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent.store, "USAGE_FILE", Path(tmp) / "usage.json"):
            self.assertEqual(agent.store.provider_requests_today("openrouter"), 0)
            for _ in range(3):
                agent.store.record_request("openrouter")
            agent.store.record_request("groq")
            self.assertEqual(agent.store.provider_requests_today("openrouter"), 3)
            self.assertEqual(agent.store.provider_requests_today("groq"), 1)
            self.assertEqual(agent.store.requests_today(), 4)

    def test_warning_appears_near_the_limit(self):
        target = agent.Target("openrouter", "t:free")
        with mock.patch.object(agent, "usable", return_value=[target]):
            with mock.patch.object(agent.store, "provider_requests_today", return_value=10):
                self.assertIsNone(agent._openrouter_notice())
            with mock.patch.object(agent.store, "provider_requests_today", return_value=45):
                self.assertIn("left today", agent._openrouter_notice())
            with mock.patch.object(agent.store, "provider_requests_today", return_value=50):
                self.assertIn("$10", agent._openrouter_notice())


if __name__ == "__main__":
    unittest.main()
