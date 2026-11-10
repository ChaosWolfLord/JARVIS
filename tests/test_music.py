"""Tests for music on the speakers: spoken commands, choosing a speaker, and what is asked of the (faked) backend.
No speaker is contacted and nothing is searched online."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import agent, audit, music  # noqa: E402


class FakeBackend:
    def __init__(self, speakers=("Kitchen speaker", "Bedroom display")):
        self.speakers, self.calls = list(speakers), []
        self.song = {"video_id": "vid1", "title": "Bohemian Rhapsody", "artist": "Queen", "playlist_id": "RDAMVMvid1"}
        self.level = 0.3
        self.state = {"title": "Bohemian Rhapsody", "artist": "Queen", "state": "PLAYING", "volume": 30}

    def devices(self):
        return [{"name": n, "kind": "audio"} for n in self.speakers]

    def search(self, query):
        self.calls.append(("search", query))
        if "nothing" in query:
            raise music.MusicError(f"I couldn't find “{query}” on YouTube Music.")
        return self.song

    def play(self, device, video_id, playlist_id):
        self.calls.append(("play", device, video_id, playlist_id))

    def control(self, device, what):
        self.calls.append((what, device))

    def volume(self, device, level=None, delta=None):
        self.level = level if level is not None else max(0.0, min(1.0, self.level + (delta or 0)))
        self.calls.append(("volume", device, round(self.level, 2)))
        return self.level

    def now_playing(self, device):
        return self.state

    def stop(self):
        pass


def make(*speakers):
    return music.Music(FakeBackend(speakers) if speakers else FakeBackend())


class Parsing(unittest.TestCase):
    def check(self, text, **expected):
        self.assertEqual(music.parse_command(text), expected, text)

    def test_play(self):
        self.check("Jarvis, play bohemian rhapsody", action="play", query="bohemian rhapsody", device="")
        self.check("play some jazz", action="play", query="jazz", device="")
        self.check("play bohemian rhapsody by queen on the kitchen speaker", action="play", query="bohemian rhapsody by queen", device="kitchen speaker")
        self.check("play despacito in the living room", action="play", query="despacito", device="living room")
        self.check("can you play thriller please", action="play", query="thriller", device="")

    def test_a_song_with_on_in_its_title_is_not_a_speaker(self):
        self.check("play dancing on the ceiling", action="play", query="dancing on the ceiling", device="")

    def test_transport(self):
        self.check("pause", action="pause")
        self.check("pause the music", action="pause")
        self.check("resume", action="resume")
        self.check("play the music", action="resume")
        self.check("stop the music", action="stop")
        self.check("turn the music off", action="stop")
        self.check("next song", action="next")
        self.check("skip", action="next")
        self.check("previous song", action="previous")

    def test_volume(self):
        self.check("louder", action="volume", direction="up")
        self.check("turn it down", action="volume", direction="down")
        self.check("set the volume to 30 percent", action="volume", level=30)
        self.check("volume 40", action="volume", level=40)

    def test_what_is_playing(self):
        self.check("what's playing", action="status")
        self.check("what song is this", action="status")

    def test_everything_else_is_left_alone(self):
        for text in ("stop", "lights off", "what is the weather", "set a timer for ten minutes", "tell me a joke", "how loud is it"):
            self.assertIsNone(music.parse_command(text), text)


class Speakers(unittest.TestCase):
    def test_the_only_speaker_is_used(self):
        self.assertEqual(make("Kitchen speaker").choose(), "Kitchen speaker")

    def test_a_named_speaker_is_found_by_part_of_its_name(self):
        m = make()
        self.assertEqual(m.choose("the kitchen speaker"), "Kitchen speaker")
        self.assertEqual(m.choose("bedroom"), "Bedroom display")

    def test_more_than_one_and_none_named_asks_which(self):
        with self.assertRaisesRegex(music.MusicError, "Which speaker"):
            make().choose()

    def test_the_last_used_and_the_configured_speaker_are_remembered(self):
        m = make()
        m.last_device = "Bedroom display"
        self.assertEqual(m.choose(), "Bedroom display")
        with mock.patch.dict("os.environ", {"MUSIC_DEVICE": "kitchen"}):
            self.assertEqual(m.choose(), "Kitchen speaker")

    def test_an_unknown_speaker_lists_the_known_ones(self):
        with self.assertRaisesRegex(music.MusicError, "Kitchen speaker"):
            make().choose("garage")

    def test_two_matches_asks_which(self):
        with self.assertRaisesRegex(music.MusicError, "Which one"):
            make("Kitchen left", "Kitchen right").choose("kitchen")

    def test_no_speakers_is_explained(self):
        m = music.Music(FakeBackend(speakers=()))
        with self.assertRaisesRegex(music.MusicError, "don't see any speakers"):
            m.choose()


class Playing(unittest.TestCase):
    def test_play_searches_then_casts_and_says_what_it_is_playing(self):
        m = make("Kitchen speaker")
        say = m.play("bohemian rhapsody queen")
        self.assertEqual(m.backend.calls, [("search", "bohemian rhapsody queen"), ("play", "Kitchen speaker", "vid1", "RDAMVMvid1")])
        self.assertEqual(say, "Playing Bohemian Rhapsody by Queen on Kitchen speaker.")
        self.assertEqual(m.view()["now"]["title"], "Bohemian Rhapsody")

    def test_nothing_found_plays_nothing(self):
        m = make("Kitchen speaker")
        with self.assertRaises(music.MusicError):
            m.play("nothing at all")
        self.assertFalse([c for c in m.backend.calls if c[0] == "play"])

    def test_an_empty_request_is_explained(self):
        with self.assertRaisesRegex(music.MusicError, "what should I play"):
            make("Kitchen speaker").play("  ")

    def test_transport_and_volume(self):
        m = make("Kitchen speaker")
        self.assertEqual(m.control("pause"), "Paused.")
        self.assertEqual(m.control("next"), "Next song.")
        self.assertEqual(m.volume(direction="up"), "Volume 40 percent.")
        self.assertEqual(m.volume(level=75), "Volume 75 percent.")
        self.assertEqual(m.volume(level=500), "Volume 100 percent.")
        self.assertEqual([c[0] for c in m.backend.calls], ["pause", "next", "volume", "volume", "volume"])

    def test_status_sentences(self):
        m = make("Kitchen speaker")
        self.assertIn("Playing Bohemian Rhapsody by Queen on Kitchen speaker, volume 30", m.status())
        m.backend.state = {"title": "Song", "artist": None, "state": "PAUSED", "volume": 20}
        self.assertTrue(m.status().startswith("Paused on Song on"))
        m.backend.state = {"title": None, "artist": None, "state": "IDLE", "volume": 20}
        self.assertEqual(m.status(), "Nothing is playing on Kitchen speaker.")

    def test_view_survives_an_error(self):
        class Broken(FakeBackend):
            def devices(self):
                raise music.MusicError("not installed")
        self.assertEqual(music.Music(Broken()).view()["error"], "not installed")


class VoiceAndTool(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(audit, "LOG_FILE", Path(tmp.name) / "a.log")
        patch.start()
        self.addCleanup(patch.stop)
        self.m = make("Kitchen speaker")

    def test_voice_runs_music_commands_only(self):
        out = music.handle_voice("play thriller", self.m)
        self.assertEqual((out["handled"], out["ok"]), (True, True))
        self.assertIn("Bohemian Rhapsody", out["text"])                  # whatever the mood, it says what it is playing
        self.assertFalse(music.handle_voice("what time is it", self.m)["handled"])

    def test_voice_errors_say_what_went_wrong(self):
        out = music.handle_voice("play nothing here", self.m)
        self.assertTrue(out["handled"] and not out["ok"])
        self.assertIn("couldn't find", out["text"])

    def test_tool_actions_and_errors(self):
        self.assertIn("Kitchen speaker", music.tool({"action": "devices"}, self.m))
        self.assertIn("Playing", music.tool({"action": "play", "query": "adele"}, self.m))
        self.assertEqual(music.tool({"action": "pause"}, self.m), "Paused.")
        self.assertIn("Volume 20", music.tool({"action": "volume", "volume": 20}, self.m))
        self.assertTrue(music.tool({"action": "dance"}, self.m).startswith("Error"))
        self.assertTrue(music.tool({"action": "volume", "volume": "loud"}, self.m).startswith("Error"))

    def test_missing_add_ons_say_how_to_install(self):
        backend = music.CastBackend()
        with mock.patch.dict(sys.modules, {"pychromecast": None, "ytmusicapi": None}):
            with self.assertRaisesRegex(music.MusicError, "requirements-music.txt"):
                backend.devices()
            with self.assertRaisesRegex(music.MusicError, "requirements-music.txt"):
                backend.search("x")

    def test_the_ai_tool_is_only_music_and_asks_nothing(self):
        self.assertIn("music", agent.FOLLOW_UP_TOOLS)
        self.assertNotIn("music", agent.ACTION_TOOLS)
        params = next(t for t in agent.TOOLS if t["function"]["name"] == "music")["function"]["parameters"]["properties"]
        self.assertEqual(set(params), {"action", "query", "device", "volume", "direction"})
        names = lambda: {t["function"]["name"] for t in agent.active_tools()}   # noqa: E731
        with mock.patch.dict("os.environ", {"JARVIS_MUSIC": "0"}):
            self.assertNotIn("music", names())
        self.assertIn("music", names())
        self.assertEqual(agent._step_text("music", {}), "Asking the speaker")
        self.assertEqual(audit.describe("music", {"action": "play", "query": "adele"}), "play adele")

    def test_main_routes(self):
        from server import main
        with mock.patch.object(music.instance, "backend", self.m.backend), mock.patch.object(music.instance, "last_device", ""):
            out = main.command_music(main.MusicCommand(action="play", query="thriller"))
            self.assertTrue(out["ok"])
            self.assertIn("Playing", out["text"])
            self.assertTrue(main.voice_music(main.SpokenLight(text="pause the music"))["handled"])
            self.assertFalse(main.voice_music(main.SpokenLight(text="open the pod bay doors"))["handled"])
            self.assertEqual(main.get_music()["devices"][0]["name"], "Kitchen speaker")


class DeadConnection(unittest.TestCase):
    """A speaker connection that died (the PC changed Wi-Fi, the speaker slept) must be found again, not fail until the list expires."""

    class Cast:
        def __init__(self, name, alive):
            self.cast_info = type("Info", (), {"friendly_name": name, "cast_type": "cast"})()
            self.alive, self.registered = alive, []

        def wait(self, timeout=None):
            if not self.alive:
                raise TimeoutError("Execution of wait timed out")

        def register_handler(self, handler):
            self.registered.append(handler)

    def backend(self, rounds):
        """A CastBackend whose network look-ups hand out the given casts, one list per look."""
        be = music.CastBackend()
        looks = iter(rounds)
        fake_pc = type("PC", (), {"get_chromecasts": staticmethod(lambda timeout=6: (next(looks), object())),
                                  "discovery": type("D", (), {"stop_discovery": staticmethod(lambda b: None)})()})
        be._import = lambda name: fake_pc if name == "pychromecast" else type("YT", (), {"YouTubeController": lambda: type("C", (), {"play_video": lambda self, v, playlist_id=None: None})()})
        return be

    def test_a_dead_connection_is_replaced_by_a_fresh_one(self):
        dead, fresh = self.Cast("Cove", alive=False), self.Cast("Cove", alive=True)
        be = self.backend([[dead], [fresh]])
        self.assertIs(be._cast("Cove"), fresh)

    def test_a_speaker_that_never_answers_gives_a_message_not_a_traceback(self):
        be = self.backend([[self.Cast("Cove", alive=False)], [self.Cast("Cove", alive=False)]])
        with self.assertRaises(music.MusicError) as e:
            be._cast("Cove")
        self.assertIn("isn't answering", str(e.exception))

    def test_a_new_network_forces_a_new_look(self):
        old, new = self.Cast("Cove", alive=True), self.Cast("Cove", alive=True)
        be = self.backend([[old], [new]])
        with mock.patch.object(music, "_local_ip", return_value="192.168.1.5"):
            be.refresh()
        with mock.patch.object(music, "_local_ip", return_value="192.168.86.120"):
            self.assertIs(be._cast("Cove"), new)


if __name__ == "__main__":
    unittest.main()
