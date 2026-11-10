"""Sending the AI only the tools a message could need (server/toolgate.py): smaller, faster requests that fit the free tiers of the back-up
models, without ever dropping the tools a message does need."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, toolgate  # noqa: E402


def setUpModule():
    # every connection counts as set up, whatever this PC has configured, so the tests say the same everywhere
    global _connected
    _connected = mock.patch.dict(agent.CONNECTORS, {name: (lambda: True) for name in agent.CONNECTORS})
    _connected.start()


def tearDownModule():
    _connected.stop()


def names(message, history=None):
    groups = toolgate.groups_for(message, history)
    return {t["function"]["name"] for t in toolgate.filter_tools(agent.active_tools(), groups)}


def tokens(message, history=None):
    groups = toolgate.groups_for(message, history)
    return (len(agent.build_system(message, "", groups)) + len(json.dumps(toolgate.filter_tools(agent.active_tools(), groups)))) // 4


class Choosing(unittest.TestCase):
    def test_a_plain_question_needs_none_of_the_special_tools(self):
        got = names("What is the capital of France?")
        for left_out in ("lights", "music", "apps", "system_status", "hologram", "gmail_search", "timer"):
            self.assertNotIn(left_out, got)

    def test_what_the_board_and_memory_and_lookups_always_need_is_never_dropped(self):
        for message in ("hello", "what is the capital of France?", "turn on the lights", "play jazz"):
            got = names(message)
            for always in ("add_note", "edit_note", "delete_note", "draw", "undo", "clear_ink", "remember", "recall", "web_search", "fetch_url"):
                self.assertIn(always, got, f"{always} for {message!r}")

    def test_the_words_bring_in_their_tools(self):
        self.assertIn("lights", names("turn the lights blue"))
        self.assertIn("lights", names("it's too dark in here"))
        self.assertIn("music", names("play some lofi"))
        self.assertIn("music", names("turn the volume down"))
        self.assertIn("hologram", names("show me a 3D cat"))
        self.assertIn("chart", names("chart my sales as a pie"))
        self.assertIn("timer", names("set a timer for ten minutes"))
        self.assertIn("reminder", names("remind me to call mom tomorrow"))
        self.assertIn("run_python", names("what is 15 percent of 240"))
        self.assertIn("apps", names("open discord"))
        self.assertIn("system_status", names("is my computer ok? it feels slow"))

    def test_a_follow_up_keeps_what_the_conversation_was_about(self):
        history = [{"role": "user", "content": "turn on the lights"}, {"role": "assistant", "content": "Lights on."}]
        self.assertIn("lights", names("make it brighter", history))
        self.assertNotIn("lights", names("make it brighter"))
        history = [{"role": "user", "content": "play some jazz"}, {"role": "assistant", "content": "Playing jazz."}]
        self.assertIn("music", names("next one", history))

    def test_connected_apps_are_not_filtered(self):
        with mock.patch.object(agent.mcp_client.manager, "openai_tools", return_value=[{"type": "function", "function": {"name": "mcp__x__ping", "parameters": {}}}]):
            self.assertIn("mcp__x__ping", names("what is the capital of France?"))

    def test_it_can_be_turned_off(self):
        with mock.patch.dict(os.environ, {"JARVIS_TOOLS": "all"}):
            self.assertFalse(toolgate.enabled())
        self.assertTrue(toolgate.enabled())


class Instructions(unittest.TestCase):
    def test_the_instructions_for_left_out_tools_are_left_out_too(self):
        plain = agent.build_system("hello", "", toolgate.groups_for("hello"))
        self.assertNotIn("- lights controls", plain)
        self.assertNotIn("- music plays", plain)
        self.assertNotIn("- hologram shows", plain)
        self.assertIn("- add_note puts", plain)
        self.assertIn("- draw puts", plain)
        self.assertIn("Never say you are drawing", plain)                         # the closing rules are not tool lines
        lights = agent.build_system("turn the lights on", "", toolgate.groups_for("turn the lights on"))
        self.assertIn("- lights controls", lights)

    def test_without_groups_everything_is_kept(self):
        self.assertIn("- lights controls", agent.build_system("hello"))


class Size(unittest.TestCase):
    def test_a_typical_request_is_about_half_the_size_and_fits_the_small_free_tiers(self):
        full = (len(agent.build_system("x")) + len(json.dumps(agent.active_tools()))) // 4
        for message in ("What is the capital of France?", "turn the lights blue", "play some lofi", "draw a house", "set a timer for 5 minutes"):
            self.assertLess(tokens(message), 4000, message)
            self.assertLess(tokens(message), full * 0.7, message)


class InTheTurn(unittest.TestCase):
    def test_the_model_is_sent_only_the_chosen_tools(self):
        sent = {}

        class Stream:
            def __iter__(self):
                return iter(())

        def create(**kwargs):
            sent.update(kwargs)
            return Stream()

        fake = mock.Mock()
        fake.chat.completions.create = create
        target = agent.Target("gemini", "test-model")
        with mock.patch.object(agent, "CHAIN", [target]), mock.patch.object(agent, "_client", return_value=fake), \
                mock.patch.object(agent, "_candidates", return_value=[target]), mock.patch.object(agent.store, "record_request"), \
                mock.patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
            list(agent.chat_turn("What is the capital of France?", [], None))
        offered = {t["function"]["name"] for t in sent.get("tools", [])}
        self.assertIn("web_search", offered)
        self.assertNotIn("lights", offered)
        self.assertNotIn("gmail_search", offered)
        self.assertNotIn("- lights controls", sent["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
