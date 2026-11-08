"""Tests for the offline wake word: the decision logic, the listener (with a pretend microphone and recognizer),
and the model download's safety check. No audio, no packages and no downloads are needed."""
import json
import sys
import tempfile
import threading
import time
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import wakeword  # noqa: E402


class DetectorLogic(unittest.TestCase):
    def feed(self, detector, updates, final_last=False):
        """Gives the detector one update per quarter second; returns the update numbers that woke it."""
        woke = []
        for i, text in enumerate(updates):
            if detector.hears(text, 100.0 + i * 0.25, final=(final_last and i == len(updates) - 1)):
                woke.append(i)
        return woke

    def test_the_name_has_to_stay_the_answer_for_a_moment(self):
        d = wakeword.Detector(need=3, need_ambiguous=5)
        self.assertEqual(self.feed(d, ["", "jarvis", "jarvis", "jarvis", "jarvis what"]), [3])      # woke on the third update in a row

    def test_a_passing_look_alike_does_not_wake_it(self):
        # a real run: while someone said "...Gervais..." the recognizer flickered through "jervis" for one update
        d = wakeword.Detector(need=3, need_ambiguous=5)
        self.assertEqual(self.feed(d, ["[unk]", "[unk] jervis", "[unk] gervais", "[unk]", "[unk] services"]), [])
        self.assertEqual(self.feed(wakeword.Detector(need=3, need_ambiguous=5), ["jarvis", "[unk]", "jarvis", "[unk]", "jarvis"]), [])

    def test_a_confident_final_answer_wakes_it_at_once(self):
        d = wakeword.Detector(need=3, need_ambiguous=5)
        self.assertTrue(d.hears("jarvis", 100.0, final=True, conf=1.0))
        self.assertFalse(wakeword.Detector().hears("jarvis", 100.0, final=True, conf=0.5))        # not sure: it has to keep hearing it
        self.assertFalse(wakeword.Detector().hears("jervis", 100.0, final=True, conf=1.0))        # "jervis" is also "Gervais": needs longer

    def test_hey_and_other_words_before_the_name(self):
        for first in ("hey", "[unk]", "gervais", "harvest"):
            d = wakeword.Detector(need=2, need_ambiguous=3)
            self.assertEqual(self.feed(d, [f"{first} jarvis"] * 3), [1], first)
        d = wakeword.Detector(need=2, need_ambiguous=3)
        self.assertEqual(self.feed(d, ["so then jarvis"] * 4), [])                                # the name in the middle of a sentence is not a call

    def test_the_names_other_accents_count_when_they_last(self):
        for word in ("jarvas", "jarvus", "jarves"):
            self.assertEqual(self.feed(wakeword.Detector(need=3, need_ambiguous=5), [word] * 4), [2], word)
        self.assertEqual(self.feed(wakeword.Detector(need=3, need_ambiguous=5), ["jervis"] * 4), [])
        self.assertEqual(self.feed(wakeword.Detector(need=3, need_ambiguous=5), ["jervis"] * 6), [4])

    def test_ignores_other_words(self):
        for text in ("", "service", "jar", "travis", "the jarvises", "nothing at all", "[unk]"):
            self.assertEqual(self.feed(wakeword.Detector(need=1, need_ambiguous=1), [text] * 6), [], text)

    def test_wakes_once_per_utterance_and_again_after_the_cooldown(self):
        d = wakeword.Detector(cooldown=4.0, need=1, need_ambiguous=1)
        self.assertTrue(d.hears("jarvis", 10.0))
        self.assertFalse(d.hears("jarvis what", 10.25))        # the same utterance carrying on
        self.assertFalse(d.hears("jarvis what time", 20.0))    # still the same utterance, even long after: it has to end first
        self.assertFalse(d.hears("", 20.25))                   # ...which it does...
        self.assertTrue(d.hears("jarvis", 20.5))               # ...and then a new "Jarvis" works
        self.assertFalse(d.hears("", 21.0))
        self.assertFalse(d.hears("jarvis", 22.0))              # inside the cooldown
        self.assertTrue(d.hears("jarvis", 25.0))

    def test_the_sensitivity_setting(self):
        for level, expected in (("high", (2, 3)), ("normal", (3, 5)), ("low", (4, 7)), ("nonsense", (3, 5)), ("HIGH", (2, 3))):
            with mock.patch.dict("os.environ", {"JARVIS_WAKEWORD_SENSITIVITY": level}):
                d = wakeword.Detector()
                self.assertEqual((d.need, d.need_ambiguous), expected, level)


class Grammar(unittest.TestCase):
    def test_includes_the_name_look_alikes_and_anything_else(self):
        words = json.loads(wakeword.grammar())
        self.assertEqual(words[0], "jarvis")
        self.assertEqual(words[-1], "[unk]")
        for decoy in ("service", "travis", "jar", "harvest"):
            self.assertIn(decoy, words)
        self.assertNotIn("marvis", words)               # not in the model's vocabulary: it would only log warnings

    def test_extra_decoys_from_the_environment_are_added_safely(self):
        with mock.patch.dict("os.environ", {"JARVIS_WAKEWORD_DECOYS": "Garbo, car-ver, 123, ,  harvey"}):
            words = json.loads(wakeword.grammar())
        self.assertIn("garbo", words)
        self.assertIn("harvey", words)
        self.assertNotIn("car-ver", words)
        self.assertNotIn("123", words)


class Setup(unittest.TestCase):
    def test_model_ready_looks_for_the_models_main_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(wakeword.model_ready(Path(tmp)))
            (Path(tmp) / "am").mkdir()
            (Path(tmp) / "am" / "final.mdl").write_bytes(b"x")
            self.assertTrue(wakeword.model_ready(Path(tmp)))

    def test_without_the_packages_it_says_what_is_missing_and_does_not_start(self):
        w = wakeword.WakeWord(lambda: None)
        with mock.patch.object(wakeword, "available", return_value=False):
            w.start()
        self.assertIn("vosk", w.error)
        self.assertIsNone(w.thread)

    def test_without_the_model_it_says_how_to_get_it(self):
        w = wakeword.WakeWord(lambda: None, model_path=Path("nowhere"))
        with mock.patch.object(wakeword, "available", return_value=True):
            w.start()
        self.assertIn("--get-model", w.error)


class Listening(unittest.TestCase):
    def fakes(self, partials):
        """Stand-ins for the two packages: a microphone that delivers three chunks, and a recognizer that 'hears' partials."""
        said = iter(partials)

        class Recognizer:
            def __init__(self, model, rate, grammar):
                words = json.loads(grammar)
                assert "jarvis" in words and "[unk]" in words and "service" in words

            def AcceptWaveform(self, data):
                return False

            def PartialResult(self):
                return json.dumps({"partial": next(said, "")})

            def Result(self):
                return json.dumps({"text": ""})

        class Stream:
            def __init__(self, samplerate, blocksize, dtype, channels, device, callback):
                self.callback = callback

            def __enter__(self):
                def feed():
                    for _ in range(6):
                        self.callback(b"\x00" * 8000, 4000, None, None)
                        time.sleep(0.02)
                threading.Thread(target=feed, daemon=True).start()
                return self

            def __exit__(self, *a):
                return False

        vosk = types.SimpleNamespace(SetLogLevel=lambda n: None, Model=lambda path: object(), KaldiRecognizer=Recognizer)
        sd = types.SimpleNamespace(RawInputStream=Stream)
        return {"vosk": vosk, "sounddevice": sd}

    def run_listener(self, partials):
        heard = []
        with mock.patch.dict(sys.modules, self.fakes(partials)), mock.patch.object(wakeword, "model_ready", return_value=True):
            w = wakeword.WakeWord(lambda: heard.append(1))
            w.start()
            deadline = time.time() + 5
            while time.time() < deadline and w.thread.is_alive() is False:
                time.sleep(0.01)
            time.sleep(0.6)
            self.assertTrue(w.running, w.error)
            w.stop()
        return heard, w

    def test_calls_back_when_the_name_is_heard_once_not_repeatedly(self):
        heard, w = self.run_listener(["", "jarvis", "jarvis", "jarvis", "jarvis what", ""])
        self.assertEqual(heard, [1])
        self.assertFalse(w.running)

    def test_a_single_flicker_of_the_name_is_not_enough(self):
        heard, w = self.run_listener(["", "jarvis", "", "jarvis", "", ""])
        self.assertEqual(heard, [])
        self.assertTrue(w.status()["last_text"])                       # it still shows what it heard, so you can see why it did not wake

    def test_the_status_tells_what_it_heard_and_when(self):
        heard, w = self.run_listener(["", "hey jarvis", "hey jarvis", "hey jarvis", "", ""])
        st = w.status()
        self.assertEqual(heard, [1])
        self.assertGreater(st["blocks"], 0)
        self.assertIn("jarvis", st["last_text"])
        self.assertGreater(st["last_wake"], 0)
        self.assertIsNotNone(st["heard_ago"])

    def test_a_callback_that_fails_does_not_stop_the_listener(self):
        with mock.patch.dict(sys.modules, self.fakes(["jarvis", "jarvis", "jarvis", "", "", ""])), mock.patch.object(wakeword, "model_ready", return_value=True):
            w = wakeword.WakeWord(lambda: 1 / 0)
            w.start()
            time.sleep(0.6)
            self.assertTrue(w.running, w.error)
            w.stop()

    def test_a_missing_microphone_is_reported_not_raised(self):
        fakes = self.fakes([])

        def boom(**kw):
            raise OSError("no microphone")
        fakes["sounddevice"].RawInputStream = boom
        with mock.patch.dict(sys.modules, fakes), mock.patch.object(wakeword, "model_ready", return_value=True):
            w = wakeword.WakeWord(lambda: None)
            w.start()
            w.thread.join(timeout=5)
        self.assertIn("no microphone", w.error)
        self.assertFalse(w.running)


class LiveStatus(unittest.TestCase):
    """What the status menu shows about the listener: which microphone, whether audio is flowing, what it last heard."""

    def test_status_has_the_fields_the_menu_shows(self):
        w = wakeword.WakeWord(lambda: None)
        self.assertEqual((w.status()["running"], w.status()["blocks"], w.status()["heard_ago"]), (False, 0, None))
        self.assertEqual(set(w.status()), {"running", "error", "device", "level", "blocks", "heard_ago", "last_text", "last_wake"})

    def test_block_level(self):
        import struct
        self.assertEqual(wakeword.block_level(b""), 0.0)
        self.assertEqual(wakeword.block_level(b"\x00" * 400), 0.0)
        loud = struct.pack("<200h", *([20000, -20000] * 100))
        self.assertGreater(wakeword.block_level(loud), 0.5)
        self.assertEqual(wakeword.block_level(b"\x01"), 0.0)                        # half a sample is ignored, not an error


class Download(unittest.TestCase):
    def test_an_unsafe_archive_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "models" / "m"

            def fake_download(url, path):
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr("../evil.txt", "x")

            with mock.patch.object(wakeword, "MODEL_DIR", model_dir), mock.patch.object(wakeword.urllib.request, "urlretrieve", fake_download):
                with self.assertRaises(SystemExit):
                    wakeword.download_model()
            self.assertFalse((Path(tmp) / "evil.txt").exists())
            self.assertFalse((Path(tmp) / "models" / "evil.txt").exists())

    def test_a_good_archive_unpacks_and_the_zip_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp) / "models" / wakeword.MODEL_NAME

            def fake_download(url, path):
                assert url.startswith("https://alphacephei.com/")
                with zipfile.ZipFile(path, "w") as z:
                    z.writestr(f"{wakeword.MODEL_NAME}/am/final.mdl", "model")

            with mock.patch.object(wakeword, "MODEL_DIR", model_dir), mock.patch.object(wakeword.urllib.request, "urlretrieve", fake_download):
                wakeword.download_model()
                self.assertTrue(wakeword.model_ready(model_dir))
            self.assertEqual(list(model_dir.parent.glob("*.zip")), [])


if __name__ == "__main__":
    unittest.main()
