"""Commands JARVIS answers itself (show off, lights, music, apps): the same words the page understands, handled from the phone too,
instantly and without an AI request. Nothing real is contacted."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import audit, localcmd, phone  # noqa: E402
from tests.test_phone import call, free_port  # noqa: E402

_log_patch = mock.patch.object(audit, "LOG_FILE", Path(tempfile.mkdtemp()) / "activity.log")


def setUpModule():
    _log_patch.start()


def tearDownModule():
    _log_patch.stop()


class ShowOff(unittest.TestCase):
    def test_the_same_words_as_the_page(self):
        for text, want in (("show off", "toggle"), ("Jarvis, show off", "toggle"), ("hey jarvis show off mode", "toggle"), ("start show off", "on"),
                           ("enable show-off mode", "on"), ("stop show off", "off"), ("please stop showing off", "off"), ("shoe of", "toggle"), ("Show off!", "toggle")):
            self.assertEqual(localcmd.parse_showoff(text), want, text)

    def test_other_sentences_are_left_for_the_ai(self):
        for text in ("what is show off", "show me a cat", "off", "show", "turn the lights on", "tell me about showing off in school"):
            self.assertIsNone(localcmd.parse_showoff(text), text)


class Handling(unittest.TestCase):
    def test_show_off_goes_to_the_page_and_nothing_else(self):
        sent = []
        with mock.patch.object(localcmd.lights_mod, "handle_voice") as lights, mock.patch.object(localcmd.music_mod, "handle_voice") as music:
            result = localcmd.handle("show off", sent.append)
        self.assertTrue(result["handled"] and result["ok"])
        self.assertEqual(sent, [{"type": "command", "text": "show off"}])
        lights.assert_not_called()
        music.assert_not_called()

    def test_without_a_page_to_tell_show_off_is_left_alone(self):
        self.assertFalse(localcmd.handle("show off", None)["handled"])

    def test_lights_music_and_apps_are_tried_in_turn(self):
        no = {"handled": False, "text": ""}
        with mock.patch.object(localcmd.lights_mod, "handle_voice", return_value={"handled": True, "ok": True, "text": "Lights on."}), \
                mock.patch.object(localcmd.music_mod, "handle_voice", return_value=no):
            self.assertEqual(localcmd.handle("lights on"), {"handled": True, "ok": True, "text": "Lights on."})
        with mock.patch.object(localcmd.lights_mod, "handle_voice", return_value=no), \
                mock.patch.object(localcmd.music_mod, "handle_voice", return_value={"handled": True, "ok": False, "text": "Speaker not found."}):
            result = localcmd.handle("play baby music")
            self.assertEqual((result["handled"], result["ok"], result["text"]), (True, False, "Speaker not found."))

    def test_a_question_is_not_a_command(self):
        no = {"handled": False, "text": ""}
        with mock.patch.object(localcmd.lights_mod, "handle_voice", return_value=no), mock.patch.object(localcmd.music_mod, "handle_voice", return_value=no), \
                mock.patch.object(localcmd.apps_mod, "available", return_value=False):
            self.assertFalse(localcmd.handle("what is the capital of France?")["handled"])
        self.assertFalse(localcmd.handle("")["handled"])


class OnThePhone(unittest.TestCase):
    """The phone's /chat: a command is answered without the AI; everything else still goes to it."""

    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        cls.asked, cls.broadcasts = [], []

        def fake_turn(message, history, board, cancel, summary, private):
            cls.asked.append(message)
            yield {"type": "text", "delta": "from the AI"}
            yield {"type": "done", "requests": 1}

        def commands(text):
            return {"handled": True, "ok": True, "text": "Show-off mode on."} if text == "show off" else {"handled": False}

        cls.port = free_port()
        cls.service = phone.PhoneService(phone.Phones(cls.dir / "phones.json"))
        cls.service.start(fake_turn, cls.broadcasts.append, lambda: False, port=cls.port, tls=False, host="127.0.0.1", local_command=commands)
        for _ in range(100):
            if cls.service.server.started:
                break
            time.sleep(0.1)
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.service.stop()

    def token(self):
        code = self.service.phones.new_code()["code"]
        return json.loads(call(f"{self.base}/pair", {"code": code, "name": "Test phone"})[1])["token"]

    def test_a_command_is_answered_without_the_ai(self):
        token = self.token()
        before = len(self.asked)
        status, body, _ = call(f"{self.base}/chat", {"message": "show off"}, token)
        self.assertEqual(status, 200)
        self.assertIn("Show-off mode on.", body)
        self.assertIn('"requests": 0', body)
        self.assertEqual(len(self.asked), before)                              # no AI request was made

    def test_anything_else_still_goes_to_the_ai(self):
        token = self.token()
        status, body, _ = call(f"{self.base}/chat", {"message": "what is the capital of France?"}, token)
        self.assertEqual(status, 200)
        self.assertIn("from the AI", body)
        self.assertIn("what is the capital of France?", self.asked)

    def test_a_private_message_never_takes_the_shortcut(self):
        token = self.token()
        before = len(self.asked)
        call(f"{self.base}/chat", {"message": "show off", "private": True}, token)
        self.assertEqual(len(self.asked), before + 1)


if __name__ == "__main__":
    unittest.main()
