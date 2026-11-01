"""Tests for saving the whiteboard on the PC: the file, the backups, and restoring one."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import store  # noqa: E402


def board(n=1, notes=0):
    return {"strokes": [{"id": i, "color": "cyan", "w": 4, "pts": [[i, i], [i + 1, i + 1]]} for i in range(n)],
            "notes": [{"id": 100 + i, "text": f"n{i}", "x": 1, "y": 2, "color": "cyan"} for i in range(notes)],
            "nextId": 500, "savedAt": 1}


class BoardStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        for patch in (mock.patch.object(store, "BOARD_FILE", root / "board.json"),
                      mock.patch.object(store, "BACKUP_DIR", root / "backups"),
                      mock.patch.dict(store._last_backup, {"time": 0.0, "digest": None})):
            patch.start()
            self.addCleanup(patch.stop)

    def test_nothing_saved_yet_is_none_not_an_error(self):
        self.assertIsNone(store.load_board())

    def test_a_saved_board_comes_back_unchanged(self):
        store.save_board(board(3, 2))
        self.assertEqual(store.load_board(), board(3, 2))

    def test_a_busy_file_is_an_error_not_an_empty_board(self):
        store.save_board(board(1))
        with mock.patch.object(store, "_RETRY_DELAYS", ()), mock.patch.object(Path, "read_text", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                store.load_board()

    def test_first_save_makes_a_backup_and_the_next_waits_ten_minutes(self):
        store.save_board(board(2))
        self.assertEqual(len(store.list_board_backups()), 1)
        store.save_board(board(3))
        self.assertEqual(len(store.list_board_backups()), 1)           # too soon
        with mock.patch.object(store.time, "time", return_value=store.time.time() + 700):
            store.save_board(board(4))
        self.assertEqual(len(store.list_board_backups()), 2)

    def test_an_unchanged_or_empty_board_takes_no_backup(self):
        store.save_board({"strokes": [], "notes": [], "nextId": 1, "savedAt": 1})
        self.assertEqual(store.list_board_backups(), [])
        store.save_board(board(2))
        with mock.patch.object(store.time, "time", return_value=store.time.time() + 700):
            store.save_board(board(2))
        self.assertEqual(len(store.list_board_backups()), 1)

    def test_old_backups_are_thinned_to_one_a_day(self):
        store.BACKUP_DIR.mkdir(parents=True)
        now = datetime.now()
        names = []
        for i in range(60):                                             # 60 recent ones, 10 minutes apart
            names.append(f"board-{now - timedelta(minutes=10 * i):%Y%m%d-%H%M%S}.json")
        for d in range(2, 5):                                           # three older days, five each
            for k in range(5):
                names.append(f"board-{now - timedelta(days=d, minutes=k):%Y%m%d-%H%M%S}.json")
        names.append(f"board-{now - timedelta(days=60):%Y%m%d-%H%M%S}.json")   # older than the 30 days
        for n in names:
            (store.BACKUP_DIR / n).write_text("{}")
        store._prune_backups()
        left = sorted(p.name for p in store.BACKUP_DIR.glob("board-*.json"))
        self.assertLessEqual(len(left), store.KEEP_RECENT + 3 + 1)      # 48 newest + one per older day
        self.assertNotIn(names[-1], left)                               # the 60-day-old one is gone
        newest = sorted(names, reverse=True)[:store.KEEP_RECENT]
        self.assertTrue(set(newest) <= set(left))

    def test_restore_puts_a_backup_back_after_saving_the_current_board(self):
        store.save_board(board(2))
        name = store.list_board_backups()[0]["name"]
        store.save_board(board(5, 1))
        restored = store.restore_board_backup(name)
        self.assertEqual(len(restored["strokes"]), 2)
        self.assertEqual(len(store.load_board()["strokes"]), 2)
        self.assertTrue(any(b["name"].endswith("-before-restore.json") for b in store.list_board_backups()))

    def test_restore_refuses_names_that_are_not_backups(self):
        for bad in ("../board.json", "board-1.json", "..\\x.json", "board-20260101-000000.json/../../x", "memory.json"):
            with self.assertRaises(ValueError):
                store.restore_board_backup(bad)


if __name__ == "__main__":
    unittest.main()
