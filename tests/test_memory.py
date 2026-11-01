"""Tests for memory: saving without duplicates, searching, what the AI is told, and the agent's memory tools."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, store  # noqa: E402


class Memory(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(store, "MEMORY_FILE", Path(tmp.name) / "memory.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_old_entries_without_the_new_fields_still_load(self):
        store.MEMORY_FILE.write_text(json.dumps([{"id": 3, "fact": "Likes tea", "created": "2026-01-01T00:00:00+00:00"}]))
        [f] = store.list_facts()
        self.assertEqual((f["kind"], f["pinned"], f["uses"], f["last_used"]), ("fact", False, 0, None))

    def test_a_reworded_fact_updates_the_old_one_instead_of_adding_a_copy(self):
        a = store.add_fact("The user studies electrical engineering at the University of Minnesota")
        b = store.add_fact("User studies electrical engineering at University of Minnesota")
        self.assertTrue(b["merged"])
        self.assertEqual(b["id"], a["id"])
        self.assertEqual(len(store.list_facts()), 1)
        c = store.add_fact("Sister Priya's birthday is in March")
        self.assertNotIn("merged", c)
        self.assertEqual(len(store.list_facts()), 2)

    def test_update_changes_text_kind_and_pin(self):
        f = store.add_fact("Likes coffee")
        store.update_fact(f["id"], fact="Likes tea", kind="preference", pinned=True)
        [g] = store.list_facts()
        self.assertEqual((g["fact"], g["kind"], g["pinned"]), ("Likes tea", "preference", True))
        self.assertIsNone(store.update_fact(999, fact="x"))

    def test_search_finds_the_right_fact_and_ignores_filler_words(self):
        store.add_fact("Sister Priya's birthday is on 14 March", "person")
        store.add_fact("Building an infrared whiteboard with a projector", "project")
        store.add_fact("Prefers short answers", "preference")
        self.assertEqual(store.search_facts("when is my sister's birthday?")[0]["fact"].split()[0], "Sister")
        self.assertIn("whiteboard", store.search_facts("how is the whiteboard project going")[0]["fact"])
        self.assertEqual(store.search_facts("what is the weather like"), [])
        self.assertEqual(store.search_facts("   "), [])

    def test_search_handles_plurals_and_endings(self):
        store.add_fact("Owns two projectors and a webcam")
        self.assertEqual(len(store.search_facts("projector")), 1)

    def test_prompt_gets_pinned_matching_and_newest_facts_but_not_everything(self):
        store.add_fact("Name is Vihaan", "fact", pinned=True)
        for i in range(30):
            store.add_fact(f"Filler fact number {i} about topic{i}")
        store.add_fact("Sister Priya lives in Chicago", "person")
        shown, total = store.facts_for_prompt("tell me about my sister", max_chars=700)
        texts = [f["fact"] for f in shown]
        self.assertEqual(total, 32)
        self.assertEqual(texts[0], "Name is Vihaan")                       # pinned first
        self.assertIn("Sister Priya lives in Chicago", texts)             # matches the message
        self.assertLess(len(texts), 32)                                    # not the whole list
        self.assertLessEqual(sum(len(t) + 24 for t in texts[1:]), 700 + 80)

    def test_using_a_fact_in_the_prompt_is_counted(self):
        f = store.add_fact("Likes jazz", "preference")
        store.facts_for_prompt("what music do I like")
        [g] = store.list_facts()
        self.assertEqual(g["uses"], 1)
        self.assertIsNotNone(g["last_used"])


class MemoryTools(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(store, "MEMORY_FILE", Path(tmp.name) / "memory.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_remember_saves_once_and_says_when_it_already_knew(self):
        text, ev = agent._run_client_tool("remember", {"fact": "Studies engineering at the U of M", "kind": "project"})
        self.assertIn("Remembered", text)
        self.assertEqual(ev["action"], "saved")
        text, ev = agent._run_client_tool("remember", {"fact": "Studies engineering at the U of M."})
        self.assertIn("Already known", text)
        self.assertEqual(ev["action"], "updated")
        self.assertEqual(len(store.list_facts()), 1)

    def test_update_memory_and_forget(self):
        agent._run_client_tool("remember", {"fact": "Lives in Chicago"})
        [f] = store.list_facts()
        text, ev = agent._run_client_tool("update_memory", {"id": f["id"], "fact": "Lives in Minneapolis"})
        self.assertEqual(store.list_facts()[0]["fact"], "Lives in Minneapolis")
        self.assertTrue(agent._run_client_tool("update_memory", {"id": 99, "fact": "x"})[0].startswith("Error"))
        agent._run_client_tool("forget", {"id": f["id"]})
        self.assertEqual(store.list_facts(), [])

    def test_recall_is_a_lookup_that_returns_matches(self):
        store.add_fact("Sister Priya lives in Chicago", "person")
        out = agent._run_lookup("recall", {"query": "where does my sister live"})
        self.assertIn("Priya", out)
        self.assertIn("(person)", out)
        self.assertIn("Nothing in memory", agent._run_lookup("recall", {"query": "quantum chromodynamics"}))
        self.assertIn("recall", agent.FOLLOW_UP_TOOLS)

    def test_the_system_prompt_holds_matching_memory_and_the_summary(self):
        store.add_fact("Sister Priya lives in Chicago", "person")
        for i in range(12):
            store.add_fact(f"Unrelated entry {i} about gadget{i}")
        s = agent.build_system("where does my sister live", "We were fixing the dock.")
        self.assertIn("Priya", s)
        self.assertIn("We were fixing the dock.", s)
        self.assertIn("more in memory", s)


class Summary(unittest.TestCase):
    def test_summarize_uses_the_first_model_that_answers(self):
        from types import SimpleNamespace as NS
        calls = []

        class Completions:
            def create(self, **kw):
                calls.append(kw)
                return NS(choices=[NS(message=NS(content="They fixed the dock and chose OpenRouter."))], usage=NS(prompt_tokens=50, completion_tokens=10))

        client = NS(chat=NS(completions=Completions()))
        target = agent.Target("openrouter", "t:free")
        with mock.patch.object(agent, "_candidates", return_value=[target]), mock.patch.object(agent, "_client", return_value=client), \
                mock.patch.object(agent.store, "record_request"), mock.patch.object(agent.store, "record_usage") as usage:
            out = agent.summarize([{"role": "user", "content": "fix the dock"}, {"role": "assistant", "content": "done"}], "Earlier: setup.")
        self.assertEqual(out, "They fixed the dock and chose OpenRouter.")
        self.assertIn("Earlier: setup.", calls[0]["messages"][1]["content"])
        usage.assert_called_once()

    def test_if_no_model_answers_the_old_summary_is_kept(self):
        with mock.patch.object(agent, "_candidates", return_value=[]):
            self.assertEqual(agent.summarize([{"role": "user", "content": "hi"}], "keep me"), "keep me")
        self.assertEqual(agent.summarize([], "keep me"), "keep me")


if __name__ == "__main__":
    unittest.main()
