"""Several named whiteboards: the files and the index, what the PC's routes allow, and what the phone may do."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import phone, store  # noqa: E402
from tests.test_phone import call, free_port  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def content(n=1):
    return {"strokes": [{"id": i, "color": "cyan", "w": 4, "pts": [[i, i], [i + 1, i + 1]]} for i in range(n)], "notes": [], "nextId": 50, "savedAt": 1}


class Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.root = root
        for patch in (mock.patch.object(store, "BOARD_FILE", root / "board.json"), mock.patch.object(store, "BOARDS_DIR", root / "boards"),
                      mock.patch.object(store, "BOARDS_INDEX", root / "boards" / "index.json"), mock.patch.object(store, "BACKUP_DIR", root / "backups"),
                      mock.patch.dict(store._last_backup, {"time": 0.0, "digest": None}), mock.patch.dict(store._other_backups, {}, clear=True)):
            patch.start()
            self.addCleanup(patch.stop)


class Store(Fixture):
    def test_with_nothing_saved_there_is_one_board_called_main(self):
        self.assertEqual(store.load_index(), {"boards": [{"id": "main", "name": "Main"}], "current": "main"})

    def test_the_first_board_stays_in_the_old_file(self):
        store.save_board(content(2))
        self.assertTrue((self.root / "board.json").exists())
        self.assertEqual(store.load_board(), content(2))

    def test_each_board_has_its_own_content(self):
        store.save_board(content(1))
        other = store.create_board("Work")["current"]
        self.assertIsNone(store.load_board(other))
        store.save_board(content(3), other)
        self.assertEqual(len(store.load_board(other)["strokes"]), 3)
        self.assertEqual(len(store.load_board()["strokes"]), 1)

    def test_names_are_tidied_and_must_be_unique_ignoring_capitals(self):
        index = store.create_board("   Work   stuff ")
        self.assertEqual(index["boards"][-1]["name"], "Work stuff")
        with self.assertRaisesRegex(ValueError, "already"):
            store.create_board("WORK STUFF")
        with self.assertRaisesRegex(ValueError, "name"):
            store.create_board("   ")
        self.assertEqual(len(store.clean_board_name("x" * 100)), store.MAX_NAME)

    def test_there_is_a_limit(self):
        for i in range(store.MAX_BOARDS - 1):
            store.create_board(f"Board {i}")
        with self.assertRaisesRegex(ValueError, "most boards"):
            store.create_board("One too many")

    def test_rename_and_switch(self):
        other = store.create_board("Work", switch=False)["boards"][-1]["id"]
        self.assertEqual(store.current_board_id(), "main")
        store.set_current_board("work")                              # by name, any capitals
        self.assertEqual(store.current_board_id(), other)
        store.rename_board(other, "Plans")
        self.assertEqual(store.load_index()["boards"][-1]["name"], "Plans")
        with self.assertRaisesRegex(ValueError, "already"):
            store.rename_board(other, "main")
        with self.assertRaises(KeyError):
            store.set_current_board("nope")

    def test_the_last_board_cannot_be_deleted(self):
        with self.assertRaisesRegex(ValueError, "only board"):
            store.delete_board("main")

    def test_deleting_keeps_a_last_backup_and_moves_the_current_one(self):
        other = store.create_board("Work")["current"]
        store.save_board(content(2), other)
        index = store.delete_board(other)
        self.assertEqual([b["id"] for b in index["boards"]], ["main"])
        self.assertEqual(index["current"], "main")
        self.assertFalse((self.root / "boards" / f"{other}.json").exists())
        backups = list((self.root / "backups" / other).glob("board-*-before-delete.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(len(json.loads(backups[0].read_text())["strokes"]), 2)

    def test_the_first_board_can_be_deleted_when_there_are_others(self):
        store.save_board(content(1))
        store.create_board("Work")
        store.delete_board("main")
        self.assertEqual([b["name"] for b in store.load_index()["boards"]], ["Work"])
        self.assertIsNone(store.load_board())

    def test_each_board_has_its_own_backups(self):
        store.save_board(content(1))
        other = store.create_board("Work")["current"]
        store.save_board(content(2), other)
        self.assertEqual(len(store.list_board_backups()), 1)
        self.assertEqual(len(store.list_board_backups(other)), 1)
        name = store.list_board_backups(other)[0]["name"]
        store.save_board(content(5), other)
        self.assertEqual(len(store.restore_board_backup(name, other)["strokes"]), 2)
        self.assertEqual(len(store.load_board()["strokes"]), 1)           # the other board was not touched

    def test_a_damaged_index_falls_back_safely(self):
        store.create_board("Work")
        store.BOARDS_INDEX.write_text("{nope", encoding="utf-8")
        self.assertEqual(store.load_index(), {"boards": [{"id": "main", "name": "Main"}], "current": "main"})
        store.BOARDS_INDEX.write_text(json.dumps({"boards": [{"id": "../evil", "name": "x"}, {"id": "main", "name": "A"}, {"id": "main", "name": "B"}], "current": "../evil"}), encoding="utf-8")
        index = store.load_index()
        self.assertEqual(index, {"boards": [{"id": "main", "name": "A"}], "current": "main"})

    def test_only_real_ids_become_file_names(self):
        for bad in ("../x", "main/../x", "b-zzzzzzzz", "b-1234567", "", "B-12345678"):
            self.assertFalse(store.valid_board_id(bad), bad)
            with self.assertRaises(ValueError):
                store.load_board(bad)
        self.assertTrue(store.valid_board_id("b-0123abcd"))


class Routes(Fixture):
    def setUp(self):
        super().setUp()
        from server import main
        self.main = main
        told = mock.patch.object(main, "tell_pages", lambda e: self.told.append(e))
        self.told = []
        told.start()
        self.addCleanup(told.stop)

    def test_create_switch_rename_delete_and_every_page_is_told(self):
        m = self.main
        out = m.boards_create(m.BoardName(name="Work"))
        self.assertEqual(out["current"], out["created"])
        work = out["created"]
        self.assertEqual(m.get_board(board=None)["id"], work)                      # no id: the one showing
        self.assertEqual(m.get_board(board="main")["id"], "main")
        m.put_board(m.BoardIn(notes=[{"id": 1, "text": "hi", "x": 0, "y": 0, "color": "cyan"}]), id=work)
        self.assertEqual(m.get_board(board=work)["board"]["notes"][0]["text"], "hi")
        self.assertIsNone(m.get_board(board="main")["board"])
        m.boards_switch(m.BoardChoice(id="Main"))
        self.assertEqual(m.boards_list()["current"], "main")
        m.boards_rename(work, m.BoardName(name="Plans"))
        self.assertEqual(m.boards_list()["boards"][-1]["name"], "Plans")
        m.boards_delete(work)
        self.assertEqual(len(m.boards_list()["boards"]), 1)
        self.assertEqual(len(self.told), 4)
        self.assertTrue(all(e == {"type": "boards"} for e in self.told))

    def test_mistakes_are_answered_in_words(self):
        m = self.main
        m.boards_create(m.BoardName(name="Work"))
        for call_, code in ((lambda: m.boards_create(m.BoardName(name="work")), 400), (lambda: m.boards_create(m.BoardName(name=" ")), 400),
                            (lambda: m.boards_switch(m.BoardChoice(id="nope")), 404), (lambda: m.boards_delete("b-00000000"), 404),
                            (lambda: m.get_board(board="b-00000000"), 404), (lambda: m.get_board(board="../x"), 404),
                            (lambda: m.put_board(m.BoardIn(), id="b-00000000"), 404)):
            with self.assertRaises(m.HTTPException) as caught:
                call_()
            self.assertEqual(caught.exception.status_code, code)
        m.boards_delete(m.boards_list()["boards"][-1]["id"])
        with self.assertRaises(m.HTTPException) as caught:
            m.boards_delete("main")
        self.assertEqual(caught.exception.status_code, 400)

    def test_the_old_calls_still_work_on_the_first_board(self):
        m = self.main
        m.put_board(m.BoardIn(strokes=[{"id": 1, "pts": [[0, 0]]}]), id=None)
        self.assertEqual(len(m.get_board(board=None)["board"]["strokes"]), 1)
        self.assertEqual(len(store.load_board()["strokes"]), 1)

    def test_the_ai_is_told_which_board_it_is_looking_at(self):
        from server import agent
        text = agent._board_context({"name": "Work", "notes": []})
        self.assertIn('"Work"', text)
        self.assertNotIn("None", agent._board_context(None))


class PhoneDoor(Fixture):
    def test_the_phone_can_list_and_switch_but_not_make_or_delete(self):
        from server import main
        told = []
        with mock.patch.object(main, "tell_pages", told.append):
            store.create_board("Work", switch=False)
            door = main._Boards()
            port = free_port()
            svc = phone.PhoneService(phone.Phones(self.root / "phones.json"))
            svc.start(lambda *a, **k: iter(()), lambda e: None, lambda: False, port=port, tls=False, host="127.0.0.1", boards=door)
            self.addCleanup(svc.stop)
            for _ in range(100):
                if svc.server.started:
                    break
                time.sleep(0.1)
            base = f"http://127.0.0.1:{port}"
            token = json.loads(call(f"{base}/pair", {"code": svc.phones.new_code()["code"], "name": "t"})[1])["token"]
            status, body, _ = call(f"{base}/boards", token=token)
            self.assertEqual(status, 200)
            self.assertEqual([b["name"] for b in json.loads(body)["boards"]], ["Main", "Work"])
            status, body, _ = call(f"{base}/boards/switch", {"id": "Work"}, token, "POST")
            self.assertEqual((status, json.loads(body)["current"] != "main"), (200, True))
            self.assertEqual(told, [{"type": "boards"}])
            self.assertEqual(call(f"{base}/boards/switch", {"id": "nope"}, token, "POST")[0], 404)
            self.assertIn(call(f"{base}/boards")[0], (0, 401))
            self.assertEqual(call(f"{base}/boards/switch", {"id": "Main"}, "made-up", "POST")[0], 401)
            for path, method in (("/boards", "POST"), ("/boards/work", "DELETE"), ("/boards/work/rename", "POST")):
                self.assertIn(call(base + path, {"name": "x"}, token, method)[0], (404, 405), path)

    def test_the_privacy_screen_blocks_it(self):
        locked = [True]
        app = phone.build_app(phone.Phones(self.root / "p.json"), lambda *a, **k: iter(()), lambda e: None, lambda: locked[0], boards=mock.Mock())
        self.assertIn("/boards/switch", {r.path for r in app.routes})
        src = (ROOT / "server" / "phone.py").read_text(encoding="utf-8")
        part = src[src.index('@app.get("/boards")'):src.index('@app.get("/privacy")')]
        self.assertEqual(part.count("is_locked()"), 2)


class Pages(unittest.TestCase):
    def test_the_board_page_saves_before_it_switches_and_never_mixes_boards(self):
        js = (ROOT / "web" / "board.js").read_text(encoding="utf-8")
        self.assertIn("const id = this.id;", js[js.index("async push()"):])                       # a push belongs to the board it started on
        self.assertIn("this.dirty", js)
        switch = js[js.index("async switchTo"):js.index("step(delta)")]
        self.assertLess(switch.index("await this.push()"), switch.index("this.id = target.id"))      # the old board is saved first
        self.assertIn("this.penUp()", switch)
        self.assertIn("if (this.id !== id) return;", js[js.index("async pull()"):])                 # a late answer for another board is dropped

    def test_the_wall_looks_again_when_the_boards_change(self):
        app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("pen.onBoards = () => board.sync()", app)
        self.assertIn("boardsUI.handleVoice(command)", app)
        self.assertIn("board.step(-1)", app)
        self.assertIn("case 'boards'", (ROOT / "web" / "pen.js").read_text(encoding="utf-8"))

    def test_backups_follow_the_board_that_is_showing(self):
        status = (ROOT / "web" / "status.js").read_text(encoding="utf-8")
        self.assertIn("/api/board/backups?board=", status)
        self.assertIn("board: this.board.id", status)

    def test_the_phone_only_chooses_it_does_not_edit_boards(self):
        js = (ROOT / "web" / "phone" / "phone.js").read_text(encoding="utf-8")
        self.assertIn("'/boards/switch'", js)
        self.assertNotIn("/api/boards", js)


if __name__ == "__main__":
    unittest.main()
