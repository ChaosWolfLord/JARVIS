"""Tests for the page's settings being kept on the PC (so a new browser or profile doesn't lose them)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import store  # noqa: E402


class Settings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = Path(tmp.name) / "ui_settings.json"
        patch = mock.patch.object(store, "UI_SETTINGS_FILE", self.file)
        patch.start()
        self.addCleanup(patch.stop)

    def test_starts_empty_and_remembers(self):
        self.assertEqual(store.ui_settings(), {})
        store.set_ui_settings({"jarvis.weather": '{"place":{"name":"Chicago"}}', "jarvis.widgets": '["weather"]'})
        self.assertEqual(json.loads(store.ui_settings()["jarvis.weather"])["place"]["name"], "Chicago")
        self.assertEqual(store.ui_settings()["jarvis.widgets"], '["weather"]')

    def test_a_null_forgets_a_setting_and_others_stay(self):
        store.set_ui_settings({"jarvis.weather": "a", "jarvis.voice": "b"})
        store.set_ui_settings({"jarvis.weather": None})
        self.assertEqual(store.ui_settings(), {"jarvis.voice": "b"})

    def test_only_known_keys_and_sane_values_are_kept(self):
        store.set_ui_settings({"jarvis.locked": "0", "something.else": "x", "jarvis.weather": 5, "jarvis.voice": "x" * (store.UI_VALUE_LIMIT + 1),
                               "jarvis.warp.v1": "ok"})
        self.assertEqual(store.ui_settings(), {"jarvis.warp.v1": "ok"})                 # the privacy lock state is never stored here

    def test_the_lock_and_the_board_are_not_among_the_kept_keys(self):
        self.assertNotIn("jarvis.locked", store.UI_KEYS)
        self.assertNotIn("jarvis.board.v1", store.UI_KEYS)

    def test_a_damaged_file_is_ignored(self):
        self.file.write_text("{not json", "utf-8")
        self.assertEqual(store.ui_settings(), {})
        self.file.write_text('["a list"]', "utf-8")
        self.assertEqual(store.ui_settings(), {})
        store.set_ui_settings({"jarvis.voice": "x"})
        self.assertEqual(store.ui_settings(), {"jarvis.voice": "x"})

    def test_the_browser_and_server_agree_on_the_keys(self):
        js = (Path(__file__).resolve().parent.parent / "web" / "settings.js").read_text("utf-8")
        listed = set(__import__("re").findall(r"'(jarvis\.[a-zA-Z0-9._]+)'", js.split("export const SYNCED = [")[1].split("];")[0]))
        self.assertEqual(listed, set(store.UI_KEYS))

    def test_routes(self):
        from server import main
        main.put_ui_settings(main.UiSettings(values={"jarvis.weather": "w", "bad.key": "x"}))
        self.assertEqual(main.get_ui_settings(), {"values": {"jarvis.weather": "w"}})


if __name__ == "__main__":
    unittest.main()
