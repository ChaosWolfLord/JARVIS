"""A model that does not respond is left alone until tomorrow (once another model has answered, so it is the model at fault and not the
internet). Nothing real is called."""
import sys
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import openai

try:                                    # the HTTP library the openai package is built on (its name differs between releases)
    import httpx2 as httpx
except ImportError:
    import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent  # noqa: E402

REQ = httpx.Request("POST", "https://example.test/v1/chat/completions")


def timeout():
    return openai.APITimeoutError(request=REQ)


def server_error():
    return openai.InternalServerError("overloaded", response=httpx.Response(503, request=REQ), body=None)


def rate_limited():
    return openai.RateLimitError("slow down", response=httpx.Response(429, request=REQ, headers={"retry-after": "30"}), body=None)


class Rest(unittest.TestCase):
    def setUp(self):
        self.a, self.b, self.c = agent.Target("gemini", "slow-model"), agent.Target("groq", "good-model"), agent.Target("groq", "other-model")
        self.calls, self.fail = [], {}
        self.cooldown = {}
        outer = self

        class Completions:
            def create(self_inner, model, **kw):
                outer.calls.append(model)
                if model in outer.fail:
                    raise outer.fail[model]()
                return object()

        client = mock.Mock()
        client.chat.completions = Completions()

        def fake_consume(stream, r, cancel):
            r.text = "ok"
            yield {"type": "text", "delta": "ok"}

        self.patches = [
            mock.patch.object(agent, "_candidates", lambda: [t for t in (self.a, self.b, self.c) if self.cooldown.get(t.key, 0) <= time.time()]),
            mock.patch.object(agent, "_cooldown", self.cooldown), mock.patch.object(agent, "_client", lambda t: client),
            mock.patch.object(agent, "_consume", fake_consume), mock.patch.object(agent.store, "record_request"), mock.patch.object(agent.store, "record_usage"),
            mock.patch.object(agent.store, "save_cooldowns"),
        ]
        for p in self.patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in self.patches])

    def ask(self):
        events = list(agent._run_round([{"role": "user", "content": "hi"}]))
        return [e for e in events if e["type"] == "notice"], events[-1]

    def tomorrow(self):
        return (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp()

    def test_a_model_that_times_out_is_skipped_for_the_rest_of_the_day(self):
        self.fail = {"slow-model": timeout}
        notices, last = self.ask()
        self.assertEqual(self.calls, ["slow-model", "good-model"])
        self.assertEqual(last["target"], self.b)
        self.assertEqual(self.cooldown[self.a.key], self.tomorrow())
        self.assertTrue(any("skip it until tomorrow" in n["text"] for n in notices))
        self.calls.clear()
        self.ask()
        self.assertEqual(self.calls, ["good-model"])                       # the next question goes straight to the one that works, no waiting

    def test_a_server_error_counts_as_not_responding_too(self):
        self.fail = {"slow-model": server_error}
        self.ask()
        self.assertEqual(self.cooldown[self.a.key], self.tomorrow())

    def test_it_is_used_again_the_next_day(self):
        self.fail = {"slow-model": timeout}
        self.ask()
        self.calls.clear()
        self.cooldown[self.a.key] = time.time() - 1                           # tomorrow has come
        self.fail = {}
        self.ask()
        self.assertEqual(self.calls, ["slow-model"])

    def test_without_an_answer_from_anyone_nothing_is_left_alone_for_a_day(self):
        # the internet may just be down: that must not bench every model until tomorrow
        self.fail = {"slow-model": timeout, "good-model": timeout, "other-model": timeout}
        with self.assertRaises(agent.AllUnavailable):
            self.ask()
        for t in (self.a, self.b, self.c):
            self.assertLess(self.cooldown.get(t.key, 0), self.tomorrow() - 3600, t.key)

    def test_running_out_of_requests_is_not_the_same_as_not_responding(self):
        self.fail = {"slow-model": rate_limited}
        self.ask()
        self.assertLess(self.cooldown[self.a.key], time.time() + 3600)       # a rate limit rests it for as long as the provider said, not a day

    def test_several_models_that_did_not_respond_all_rest(self):
        self.fail = {"slow-model": timeout, "good-model": server_error}
        _, last = self.ask()
        self.assertEqual(last["target"], self.c)
        self.assertEqual((self.cooldown[self.a.key], self.cooldown[self.b.key]), (self.tomorrow(), self.tomorrow()))


if __name__ == "__main__":
    unittest.main()
