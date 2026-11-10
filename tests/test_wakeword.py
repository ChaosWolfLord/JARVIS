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
            w.vote("page", True)
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
            w.vote("page", True)
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
            w.vote("page", True)
            w.start()
            w.thread.join(timeout=5)
        self.assertIn("no microphone", w.error)
        self.assertFalse(w.running)


class Scripted:
    """A pretend free-vocabulary recognizer: each block of audio it is given makes it 'hear' the next scripted thing (a partial, or a final)."""

    def __init__(self, script):
        self.script = list(script)       # items: ("partial", text) or ("final", text) or ("", "")
        self.current = ""

    def AcceptWaveform(self, block):
        kind, text = self.script.pop(0) if self.script else ("", "")
        self.current = text
        return kind == "final"

    def Result(self):
        return json.dumps({"text": self.current})

    def PartialResult(self):
        return json.dumps({"partial": self.current})


class AfterTheName(unittest.TestCase):
    def test_the_command_is_what_follows_the_name(self):
        for heard, want in (("jarvis turn on the lights", "turn on the lights"), ("hey jarvis what is the weather today", "what is the weather today"),
                            ("okay jarvis show me a three d model of a cat", "show me a three d model of a cat"), ("jarvis", ""), ("hey jarvis", ""),
                            ("turn on the lights", "turn on the lights"), ("okay turn it off", "turn it off"), ("", ""), ("jervis open discord", "open discord")):
            self.assertEqual(wakeword.command_after_name(heard), want, heard)

    def test_words_said_before_the_name_are_left_out(self):
        self.assertEqual(wakeword.command_after_name("so anyway jarvis play some jazz"), "play some jazz")

    def test_a_command_said_in_the_same_breath_is_caught(self):
        rec = Scripted([("partial", "jarvis"), ("partial", "jarvis turn on"), ("final", "jarvis turn on the lights"), ("", ""), ("", ""), ("", ""), ("", "")])
        cap = wakeword.CommandCapture(rec, [b"x"], now=0.0)
        out = [cap.feed(b"x", t * 0.25 + 0.25) for t in range(6)]
        self.assertEqual([o for o in out if o is not None], ["turn on the lights"])
        self.assertIsNone(out[0])                                                         # it waits a moment in case more of the command follows

    def test_the_audio_from_before_the_name_was_recognised_is_not_lost(self):
        # the name and the first words are in the kept audio: the finished sentence is heard while that audio is replayed
        rec = Scripted([("partial", "jarvis"), ("final", "jarvis set a timer for ten minutes")])
        cap = wakeword.CommandCapture(rec, [b"a", b"b"], now=0.0)
        self.assertEqual(cap.texts, ["jarvis set a timer for ten minutes"])
        self.assertEqual(cap.command(), "set a timer for ten minutes")

    def test_a_pause_after_the_name_waits_for_the_next_sentence(self):
        rec = Scripted([("final", "jarvis")] + [("", "")] * 3 + [("partial", "what"), ("final", "what time is it")] + [("", "")] * 6)
        cap = wakeword.CommandCapture(rec, [], now=0.0)
        got = None
        for i in range(1, 14):
            got = cap.feed(b"x", i * 0.25)
            if got is not None:
                break
        self.assertEqual(got, "what time is it")

    def test_only_the_name_and_then_silence_ends_with_nothing(self):
        rec = Scripted([("final", "jarvis")] + [("", "")] * 60)
        cap = wakeword.CommandCapture(rec, [], now=0.0, follow_up=2.0)
        got = None
        for i in range(1, 12):
            got = cap.feed(b"x", i * 0.25)
            if got is not None:
                break                                                                     # the listener stops feeding it at the first answer
        self.assertEqual(got, "")
        self.assertGreaterEqual(i * 0.25, 2.0)                                            # and only after the whole follow-up time

    def test_a_long_command_is_cut_off_eventually(self):
        rec = Scripted([("final", "jarvis tell me a story")] + [("partial", "and then")] * 200)
        cap = wakeword.CommandCapture(rec, [], now=0.0, longest=3.0)
        got = [cap.feed(b"x", i * 0.25) for i in range(1, 20)]
        self.assertEqual([g for g in got if g is not None][0], "tell me a story")


class TheMicrophoneFollowsTheVoiceSwitch(unittest.TestCase):
    def test_it_listens_only_while_a_page_says_voice_is_on(self):
        w = wakeword.WakeWord(lambda: None)
        self.assertFalse(w.wanted())                                 # nobody has asked: the microphone stays closed
        w.vote("wall", True)
        self.assertTrue(w.wanted())
        w.vote("wall", False)
        self.assertFalse(w.wanted())

    def test_one_page_turning_it_off_does_not_close_it_for_another_that_wants_it(self):
        w = wakeword.WakeWord(lambda: None)
        w.vote("wall", True)
        w.vote("laptop tab", False)
        self.assertTrue(w.wanted())

    def test_a_page_that_went_away_stops_counting(self):
        w = wakeword.WakeWord(lambda: None)
        w.vote("wall", True)
        with mock.patch.object(wakeword.time, "monotonic", return_value=time.monotonic() + wakeword.CLIENT_TTL + 1):
            self.assertFalse(w.wanted())

    def test_the_stream_is_closed_when_voice_is_switched_off_and_opened_again_when_it_is_back(self):
        events = []

        class Stream:
            def __init__(self, **kw):
                self.callback = kw["callback"]

            def __enter__(self):
                events.append("open")
                return self

            def __exit__(self, *a):
                events.append("closed")
                return False

        class Recognizer:
            def __init__(self, model, rate, grammar=None):
                pass

            def AcceptWaveform(self, data):
                return False

            def PartialResult(self):
                return json.dumps({"partial": ""})

            def Result(self):
                return json.dumps({"text": ""})

        fakes = {"vosk": types.SimpleNamespace(SetLogLevel=lambda n: None, Model=lambda path: object(), KaldiRecognizer=Recognizer),
                 "sounddevice": types.SimpleNamespace(RawInputStream=Stream, query_devices=lambda *a, **k: {"name": "Fake mic"})}
        with mock.patch.dict(sys.modules, fakes), mock.patch.object(wakeword, "model_ready", return_value=True):
            w = wakeword.WakeWord(lambda: None)
            w.start()
            time.sleep(0.8)
            self.assertEqual(events, [])                                                  # no page wants voice: never opened
            w.vote("wall", True)
            deadline = time.time() + 3
            while time.time() < deadline and "open" not in events:
                time.sleep(0.05)
            self.assertEqual(events, ["open"])
            self.assertTrue(w.status()["listening"])
            w.vote("wall", False)
            deadline = time.time() + 3
            while time.time() < deadline and "closed" not in events:
                time.sleep(0.05)
            self.assertEqual(events, ["open", "closed"])                                  # closed: nothing can hear "Jarvis"
            self.assertFalse(w.status()["listening"])
            w.vote("wall", True)
            deadline = time.time() + 3
            while time.time() < deadline and events.count("open") < 2:
                time.sleep(0.05)
            self.assertEqual(events.count("open"), 2)
            w.stop()


class WholePipeline(unittest.TestCase):
    """The name, then the command: the same Pipeline the microphone feeds, with pretend recognizers."""

    def fake_vosk(self, name_updates, command_script):
        listening = Scripted([(kind, text) for kind, text in name_updates])

        class Grammar:
            """The restricted recognizer: only the name, one update per block."""
            def __init__(self, model, rate, grammar):
                self.updates = iter(name_updates)
                self.text = ""

            def SetWords(self, on):
                pass

            def AcceptWaveform(self, block):
                kind, self.text = next(self.updates, ("", ""))
                return kind == "final"

            def Result(self):
                return json.dumps({"text": self.text, "result": [{"word": "jarvis", "conf": 1.0}]})

            def PartialResult(self):
                return json.dumps({"partial": self.text})

        made = []

        def recognizer(model, rate, grammar=None):
            if grammar is not None:
                return Grammar(model, rate, grammar)
            made.append(Scripted(command_script))
            return made[-1]

        return types.SimpleNamespace(KaldiRecognizer=recognizer), made

    def test_the_name_wakes_at_once_and_the_command_follows_when_it_has_been_said(self):
        vosk, made = self.fake_vosk([("", ""), ("partial", "jarvis"), ("partial", "jarvis"), ("partial", "jarvis"), ("partial", "jarvis turn on"), ("final", "jarvis turn on the lights"), ("", "")],
                                    [("partial", "jarvis"), ("partial", "jarvis turn on the"), ("final", "jarvis turn on the lights")] + [("", "")] * 10)
        events = []
        pipe = wakeword.Pipeline(object(), vosk, lambda: events.append("wake"), lambda text: events.append(("command", text)))
        for i in range(14):
            pipe.feed(b"x" * 8000, i * 0.25)
        self.assertEqual(events[0], "wake")                                                 # the listening sound does not wait for the sentence to end
        self.assertEqual(events[1:], [("command", "turn on the lights")])
        self.assertEqual(len(made), 1)

    def test_without_command_capture_only_the_name_is_reported(self):
        vosk, made = self.fake_vosk([("partial", "jarvis")] * 4, [])
        events = []
        pipe = wakeword.Pipeline(object(), vosk, lambda: events.append("wake"), None)
        for i in range(8):
            pipe.feed(b"x" * 8000, i * 0.25)
        self.assertEqual(events, ["wake"])
        self.assertEqual(made, [])

    def test_a_failing_page_callback_does_not_stop_the_command(self):
        vosk, _ = self.fake_vosk([("partial", "jarvis")] * 4 + [("", "")] * 10, [("final", "jarvis open discord")] + [("", "")] * 10)
        events = []

        def boom():
            raise RuntimeError("page gone")
        pipe = wakeword.Pipeline(object(), vosk, boom, lambda text: events.append(text))
        for i in range(14):
            pipe.feed(b"x" * 8000, i * 0.25)
        self.assertEqual(events, ["open discord"])


class Route(unittest.TestCase):
    def test_a_page_switches_the_microphone_through_the_server(self):
        from server import main
        w = wakeword.WakeWord(lambda: None)
        with mock.patch.object(main.wake, "service", w):
            out = main.wake_vote(main.WakeVote(client="wall", on=True))
            self.assertTrue(out["wanted"] and w.wanted())
            out = main.wake_vote(main.WakeVote(client="wall", on=False))
            self.assertFalse(out["wanted"] or w.wanted())

    def test_without_a_listener_the_route_just_says_so(self):
        from server import main
        with mock.patch.object(main.wake, "service", None):
            self.assertEqual(main.wake_vote(main.WakeVote(client="wall", on=True))["running"], False)

    def test_the_status_says_whether_the_microphone_is_open(self):
        w = wakeword.WakeWord(lambda: None, on_command=lambda t: None)
        st = w.status()
        self.assertEqual((st["listening"], st["wanted"], st["commands"]), (False, False, True))
        with mock.patch.dict("os.environ", {"JARVIS_WAKEWORD_COMMAND": "cloud"}):
            self.assertFalse(wakeword.WakeWord(lambda: None, on_command=lambda t: None).commands)        # the old way, on request


class LiveStatus(unittest.TestCase):
    """What the status menu shows about the listener: which microphone, whether audio is flowing, what it last heard."""

    def test_status_has_the_fields_the_menu_shows(self):
        w = wakeword.WakeWord(lambda: None)
        self.assertEqual((w.status()["running"], w.status()["blocks"], w.status()["heard_ago"]), (False, 0, None))
        self.assertEqual(set(w.status()), {"running", "listening", "wanted", "commands", "error", "device", "level", "blocks", "heard_ago", "last_text", "last_wake", "last_command"})

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
