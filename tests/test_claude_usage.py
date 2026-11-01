"""Tests for reading Claude Code's session logs for token counts. Uses made-up logs in a temp folder."""
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import claude_usage as cu  # noqa: E402


def reply(msg_id, ts="2026-10-27T15:00:00.000Z", model="claude-opus-5-5", inp=10, out=100, cw=1000, cr=50_000, request="req1", **extra):
    return json.dumps({"type": "assistant", "timestamp": ts, "requestId": request, "uuid": f"u-{msg_id}-{out}",
                       "message": {"id": msg_id, "model": model, "role": "assistant",
                                   "content": [{"type": "text", "text": "SECRET CONVERSATION TEXT"}],
                                   "usage": {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": cw,
                                             "cache_read_input_tokens": cr}}, **extra})


class Parse(unittest.TestCase):
    def test_reads_tokens_model_and_local_day(self):
        key, day, model, inp, out, cw, cr = cu.parse_line(reply("m1"))
        self.assertEqual((model, inp, out, cw, cr), ("claude-opus-5-5", 10, 100, 1000, 50_000))
        self.assertEqual(key, "m1|req1")
        self.assertRegex(day, r"^2026-10-2[678]$")   # depends on the PC's time zone

    def test_everything_else_is_ignored(self):
        user = json.dumps({"type": "user", "message": {"role": "user", "content": "usage assistant"}})
        for line in (user, "not json {", "", reply("m1", model="<synthetic>"), json.dumps({"type": "assistant", "message": {"model": "x"}}),
                     reply("m1", ts="not a date")):
            self.assertIsNone(cu.parse_line(line))

    def test_conversation_text_is_never_returned(self):
        self.assertNotIn("SECRET", repr(cu.parse_line(reply("m1"))))


class Scan(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "projects"
        (self.root / "proj").mkdir(parents=True)
        for patch in (mock.patch.object(cu, "DB", Path(self.tmp.name) / "u.sqlite"),
                      mock.patch.dict(cu.state, {"scanning": False, "last": 0.0, "error": None, "files": 0})):
            patch.start()
            self.addCleanup(patch.stop)
        self.log = self.root / "proj" / "s1.jsonl"

    def rows(self):
        conn = cu._connect()
        try:
            return conn.execute("SELECT key, inp, out FROM msgs ORDER BY key").fetchall()
        finally:
            conn.close()

    def test_a_reply_logged_once_per_content_block_counts_once(self):
        self.log.write_text("\n".join([reply("m1", out=5), reply("m1", out=100), reply("m1", out=100), reply("m2", request="r2")]) + "\n")
        self.assertEqual(cu.refresh(self.root), 4)
        self.assertEqual(self.rows(), [("m1|req1", 10, 100), ("m2|r2", 10, 100)])

    def test_only_new_lines_are_read_next_time(self):
        self.log.write_text(reply("m1") + "\n")
        cu.refresh(self.root)
        with self.log.open("a") as f:
            f.write(reply("m2", request="r2") + "\n")
        self.assertEqual(cu.refresh(self.root), 1)
        self.assertEqual(cu.refresh(self.root), 0)           # nothing changed
        self.assertEqual(len(self.rows()), 2)

    def test_a_half_written_last_line_waits_for_the_rest(self):
        full = reply("m2", request="r2")
        self.log.write_text(reply("m1") + "\n" + full[:40])
        cu.refresh(self.root)
        self.assertEqual(len(self.rows()), 1)
        self.log.write_text(reply("m1") + "\n" + full + "\n")
        cu.refresh(self.root)
        self.assertEqual(len(self.rows()), 2)

    def test_the_same_reply_in_a_resumed_session_log_isnt_counted_twice(self):
        self.log.write_text(reply("m1") + "\n")
        (self.root / "proj" / "s2.jsonl").write_text(reply("m1") + "\n" + reply("m3", request="r3") + "\n")
        cu.refresh(self.root)
        self.assertEqual(len(self.rows()), 2)

    def test_history_stays_after_claude_code_deletes_old_logs(self):
        self.log.write_text(reply("m1") + "\n")
        cu.refresh(self.root)
        self.log.unlink()
        cu.refresh(self.root)
        self.assertEqual(len(self.rows()), 1)

    def test_a_missing_folder_is_not_an_error(self):
        self.assertEqual(cu.refresh(Path(self.tmp.name) / "nope"), 0)
        self.assertIsNone(cu.state["error"])

    def test_measures_differ_only_by_cache_reads(self):
        self.log.write_text(reply("m1", inp=10, out=100, cw=1000, cr=50_000) + "\n")
        cu.refresh(self.root)
        day = next(iter(cu.days_data("all")))
        everything, fresh = cu.days_data("all")[day], cu.days_data("fresh")[day]
        self.assertEqual(everything["prompt"] + everything["completion"], 10 + 100 + 1000 + 50_000)
        self.assertEqual(fresh["prompt"] + fresh["completion"], 10 + 100 + 1000)
        self.assertEqual(fresh["requests"], 1)

    def test_summary_has_the_widget_shape(self):
        self.log.write_text(reply("m1") + "\n")
        cu.refresh(self.root)
        with mock.patch.object(cu, "refresh_in_background"):
            s = cu.summary("fresh")
        self.assertEqual(s["measure"], "fresh")
        self.assertEqual((len(s["daily"]), len(s["weekly"]), len(s["monthly"])), (30, 12, 12))
        self.assertEqual(s["all"]["requests"], 1)
        self.assertEqual(s["models"][0]["name"], "claude-opus-5-5")


if __name__ == "__main__":
    unittest.main()
