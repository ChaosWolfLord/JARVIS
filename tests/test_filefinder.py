"""File finder: only the folders you chose are searched, secrets are never listed or opened, programs are never launched, and what you describe
("the doc I edited yesterday about the budget") finds the right file. Everything runs on a temporary folder."""
import datetime
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import filefinder as ff  # noqa: E402
from server import store  # noqa: E402

NOW = datetime.datetime(2026, 11, 11, 15, 30)          # a Wednesday


def touch(path: Path, text: str = "x", when: datetime.datetime | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    if when:
        ts = when.timestamp()
        os.utime(path, (ts, ts))
    return path


def docx(path: Path, words: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body><w:p><w:r><w:t>{words}</w:t></w:r></w:p></w:body></w:document>")
    return path


class Tree(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ff._listing.clear()
        cls.root = Path(tempfile.mkdtemp()) / "Documents"
        day = datetime.timedelta(days=1)
        touch(cls.root / "budget 2026.xlsx", when=NOW - datetime.timedelta(hours=3))
        touch(cls.root / "notes" / "meeting.txt", "we talked about the budget plan and hiring", NOW - day)
        docx(cls.root / "reports" / "quarterly report.docx", "Revenue grew while the marketing budget shrank")
        os.utime(cls.root / "reports" / "quarterly report.docx", ((NOW - 3 * day).timestamp(),) * 2)
        touch(cls.root / "photos" / "holiday beach.jpg", "jpg", NOW - 10 * day)
        touch(cls.root / "taxes" / "invoice march.pdf", "pdf", NOW - 40 * day)
        touch(cls.root / "taxes" / "invoice april.pdf", "pdf", NOW - 8 * day)
        touch(cls.root / "old" / "recipe.md", "pancakes", NOW - 200 * day)
        # things that must never show up
        touch(cls.root / ".env", "API_KEY=abc")
        touch(cls.root / "keys" / "server.pem", "key")
        touch(cls.root / "passwords.txt", "hunter2 budget")
        touch(cls.root / "my secret budget.txt", "x")
        touch(cls.root / "node_modules" / "pkg" / "budget.js", "x")
        touch(cls.root / ".git" / "budget.txt", "x")
        touch(cls.root / "tools" / "run budget.bat", "echo hi", NOW)
        cls.folders = [str(cls.root)]

    def search(self, text, **kw):
        ff._listing.clear()
        return ff.search(text, folder_list=self.folders, now=NOW, **kw)

    def names(self, found):
        return [i["name"] for i in found["items"]]

    def test_a_description_finds_the_file(self):
        self.assertEqual(self.names(self.search("the budget spreadsheet"))[0], "budget 2026.xlsx")
        found = self.names(self.search("the doc I edited yesterday about the budget"))
        self.assertEqual(found[0], "meeting.txt")                         # a document, changed yesterday, mentions the budget inside

    def test_the_words_inside_word_files_count(self):
        self.assertIn("quarterly report.docx", self.names(self.search("find the report about marketing")))

    def test_dates_and_types_narrow_it(self):
        self.assertEqual(self.names(self.search("pdfs from last week")), ["invoice april.pdf"])
        self.assertEqual(set(self.names(self.search("invoices", ))), {"invoice march.pdf", "invoice april.pdf"})
        self.assertEqual(self.names(self.search("photos from the last 2 weeks")), ["holiday beach.jpg"])
        self.assertEqual(self.names(self.search("my pdfs from last month")), ["invoice march.pdf"])
        self.assertEqual(self.names(self.search("files from today")), ["run budget.bat", "budget 2026.xlsx"])       # newest first

    def test_newest_first_when_only_a_date_is_given(self):
        found = self.names(self.search("documents from this week"))
        self.assertIn("meeting.txt", found)
        self.assertNotIn("recipe.md", found)

    def test_secrets_and_junk_are_never_listed(self):
        for query in ("budget", "the .env file", "passwords", "secret", "server pem key", "api key", "files from today"):
            names = self.names(self.search(query))
            for bad in (".env", "server.pem", "passwords.txt", "my secret budget.txt"):
                self.assertNotIn(bad, names, f"{query}: {bad}")
        everything = self.names(self.search("budget"))
        self.assertNotIn("budget.js", everything)                          # node_modules
        self.assertNotIn("budget.txt", everything)                         # .git

    def test_nothing_is_searched_until_a_folder_is_chosen(self):
        with self.assertRaises(ff.FinderError):
            ff.search("budget", folder_list=[], now=NOW)

    def test_an_empty_request_is_asked_again(self):
        with self.assertRaises(ff.FinderError):
            self.search("find the file please")

    def test_it_stops_when_time_runs_out(self):
        found = self.search("budget", time_budget=0.0)
        self.assertFalse(found["complete"])

    def test_the_answer_is_short_and_plain(self):
        found = self.search("the budget spreadsheet")
        self.assertIn("budget 2026.xlsx", ff.summary(found, NOW))
        self.assertIn("today", ff.summary(found, NOW))
        empty = self.search("zebra unicorn")
        self.assertIn("didn't find", ff.summary(empty, NOW))
        ev = ff.event("the budget spreadsheet", found, NOW)
        self.assertEqual(ev["type"], "files")
        self.assertEqual(ev["items"][0]["when"], "today")


class Opening(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()) / "Documents"
        self.pdf = touch(self.root / "a.pdf", "pdf")
        self.env = touch(self.root / ".env", "KEY=1")
        self.exe = touch(self.root / "setup.exe", "MZ")
        self.bat = touch(self.root / "go.bat", "echo")
        self.lnk = touch(self.root / "thing.lnk", "x")
        self.png = self.root / "p.png"
        self.png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
        self.outside = touch(Path(tempfile.mkdtemp()) / "other.pdf", "pdf")
        self.folders = [str(self.root)]

    def test_a_document_opens_with_its_program(self):
        seen = []
        self.assertIn("a.pdf", ff.open_file(str(self.pdf), self.folders, seen.append))
        self.assertEqual(seen, [str(self.pdf.resolve())])

    def test_programs_and_scripts_are_never_launched(self):
        seen = []
        for f in (self.exe, self.bat, self.lnk):
            with self.assertRaises(ff.FinderError, msg=f.name):
                ff.open_file(str(f), self.folders, seen.append)
        self.assertEqual(seen, [])

    def test_secrets_and_files_outside_the_chosen_folders_are_refused(self):
        seen = []
        for f in (self.env, self.outside, self.root / "missing.pdf", self.root / ".." / "x"):
            with self.assertRaises(ff.FinderError, msg=str(f)):
                ff.open_file(str(f), self.folders, seen.append)
            with self.assertRaises(ff.FinderError, msg=str(f)):
                ff.reveal(str(f), self.folders, seen.append)
        self.assertEqual(seen, [])

    def test_a_path_cannot_climb_out_of_the_folder(self):
        sneaky = str(self.root / ".." / self.outside.parent.name / "other.pdf")
        with self.assertRaises(ff.FinderError):
            ff.open_file(sneaky, self.folders, lambda p: None)

    def test_show_in_folder_works_for_anything_listed(self):
        ran = []
        self.assertIn("go.bat", ff.reveal(str(self.bat), self.folders, ran.append))
        self.assertEqual(ran[0][0], "explorer")
        self.assertTrue(ran[0][1].startswith("/select,"))

    def test_only_real_picture_types_go_to_the_wall(self):
        self.assertTrue(ff.image_bytes(str(self.png), self.folders).startswith(b"\x89PNG"))
        with self.assertRaises(ff.FinderError):
            ff.image_bytes(str(self.pdf), self.folders)


class Folders(unittest.TestCase):
    def test_whole_drives_system_folders_and_jarvis_data_are_refused(self):
        for bad in ("C:\\", "C:/", str(Path.home()), os.environ.get("WINDIR", "C:\\Windows"), os.environ.get("ProgramFiles", "C:\\Program Files"), str(store.STATE),
                    str(store.STATE / "app"), os.environ.get("APPDATA", "C:\\Users\\x\\AppData\\Roaming"), "", "   ", "C:\\no\\such\\folder\\anywhere"):
            with self.assertRaises(ff.FinderError, msg=bad):
                ff.clean_folder(bad)

    def test_a_normal_folder_is_accepted_and_saved(self):
        folder = Path(tempfile.mkdtemp()) / "Work stuff"
        folder.mkdir()
        config = Path(tempfile.mkdtemp()) / "finder.json"
        saved = ff.set_folders([str(folder), str(folder).upper() if os.name == "nt" else str(folder)], config)
        self.assertEqual(len(saved), 1)
        self.assertEqual(ff.folders(config), saved)

    def test_too_many_folders_are_refused(self):
        with self.assertRaises(ff.FinderError):
            ff.set_folders(["x"] * (ff.MAX_FOLDERS + 1), Path(tempfile.mkdtemp()) / "f.json")


class Words(unittest.TestCase):
    def test_what_is_asked(self):
        for said, want in (("find the doc I edited yesterday about the budget", "the doc i edited yesterday about the budget"),
                           ("Jarvis, find my pdfs from last week", "my pdfs from last week"),
                           ("where is the invoice spreadsheet", "the invoice spreadsheet"),
                           ("can you look for the presentation about the launch", "the presentation about the launch"),
                           ("search for my screenshots from today", "my screenshots from today"),
                           ("find the file called taxes", "the file called taxes")):
            self.assertEqual(ff.from_words(said), want, said)

    def test_other_sentences_are_left_alone(self):
        for said in ("find my phone", "where is my phone", "show me a picture of a cat", "find a picture of a red panda", "find a restaurant nearby", "where is the library",
                     "play some music", "find the lights", "turn off the lights", "open youtube", "what files are on mars", ""):
            self.assertIsNone(ff.from_words(said), said)

    def test_dates(self):
        for text, a, b in (("yesterday", NOW.replace(hour=0, minute=0) - datetime.timedelta(days=1), NOW.replace(hour=0, minute=0)),
                           ("last week", datetime.datetime(2026, 11, 2), datetime.datetime(2026, 11, 9)),
                           ("this week", datetime.datetime(2026, 11, 9), datetime.datetime(2026, 11, 12)),
                           ("last month", datetime.datetime(2026, 10, 1), datetime.datetime(2026, 11, 1)),
                           ("the last 3 days", datetime.datetime(2026, 11, 9), datetime.datetime(2026, 11, 12))):
            start, end, _ = ff.parse_when(f"the report {text}", NOW)
            self.assertEqual((start, end), (a.timestamp(), b.timestamp()), text)
        self.assertEqual(ff.parse_when("the budget", NOW)[:2], (None, None))

    def test_handle_voice_answers_without_an_ai_and_tells_the_wall(self):
        root = Path(tempfile.mkdtemp()) / "Documents"
        touch(root / "budget.xlsx", "x", datetime.datetime.now())
        told = []
        ff._listing.clear()
        with mock.patch.object(ff, "folders", return_value=[str(root)]):
            out = ff.handle_voice("find the budget spreadsheet", told.append)
        self.assertTrue(out["handled"] and out["ok"])
        self.assertIn("budget.xlsx", out["text"])
        self.assertEqual(told[0]["type"], "phone_event")
        self.assertEqual(told[0]["event"]["type"], "files")
        with mock.patch.object(ff, "folders", return_value=[]):
            out = ff.handle_voice("find the budget spreadsheet")
        self.assertTrue(out["handled"] and not out["ok"])
        self.assertIn("Files JARVIS may search", out["text"])
        self.assertFalse(ff.handle_voice("what time is it")["handled"])


if __name__ == "__main__":
    unittest.main()
