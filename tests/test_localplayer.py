"""Music on this PC when no speaker can be reached: the address that is opened, the player (with a pretend browser, keyboard and screen), and when
the music module falls back to it. No window is opened, no key is pressed and nothing is searched online."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import localplayer, music  # noqa: E402

VID = "dQw4w9WgXcQ"                              # eleven letters, digits, - and _


class Address(unittest.TestCase):
    def test_only_a_plain_song_id_makes_an_address(self):
        self.assertEqual(localplayer.watch_url(VID), f"https://music.youtube.com/watch?v={VID}")
        self.assertEqual(localplayer.watch_url(VID, "RDAMVM" + VID), f"https://music.youtube.com/watch?v={VID}&list=RDAMVM{VID}")
        for bad in ("", "short", VID + "x", VID[:-1] + "&", "abc/../defgh", "a b c d e f g", "<script>aaa", None, 12345678901, ["x"] * 11):
            with self.assertRaises(localplayer.LocalPlayerError, msg=str(bad)):
                localplayer.watch_url(bad)

    def test_a_strange_playlist_is_left_out_not_trusted(self):
        for bad in ("a&b=c", "x", "has space", "../x", "z" * 81, "a;b", "list=1"):
            self.assertEqual(localplayer.watch_url(VID, bad), f"https://music.youtube.com/watch?v={VID}", bad)

    def test_the_window_is_small_has_its_own_profile_and_nothing_else_from_outside(self):
        args = localplayer.window_args("C:/Edge/msedge.exe", localplayer.watch_url(VID), Path("C:/p/browser-music"), screen=(1920, 1080))
        self.assertEqual(args[0], "C:/Edge/msedge.exe")
        self.assertEqual(args[1], f"--app=https://music.youtube.com/watch?v={VID}")
        self.assertIn("--window-size=460,760", args)
        self.assertIn("--autoplay-policy=no-user-gesture-required", args)
        self.assertTrue(any(a.startswith("--user-data-dir=") and "browser-music" in a for a in args))
        self.assertIn("--window-position=1436,160", args)                              # right side, middle
        self.assertEqual(sum(a.startswith("--app=") for a in args), 1)
        self.assertEqual(len([a for a in args if not a.startswith("--")]), 1)          # only the browser itself, no loose arguments
        self.assertNotIn("--window-position", " ".join(localplayer.window_args("b", "https://music.youtube.com/", Path("p"), screen=(0, 0))))

    def test_the_profile_is_not_the_everyday_or_the_wall_one(self):
        self.assertEqual(localplayer.PROFILE.name, "browser-music")


class Player(unittest.TestCase):
    def setUp(self):
        self.pressed, self.closed, self.launched = [], [], []
        self.browser = "C:/Edge/msedge.exe"
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.p = localplayer.LocalPlayer(find_browser=lambda: self.browser, launch=lambda args, **kw: self.launched.append(args) or mock.Mock(),
                                         press=lambda name, n=1: self.pressed.append((name, n)), close=lambda profile: self.closed.append(profile),
                                         profile=Path(tmp.name) / "browser-music", screen=lambda: (1920, 1080))
        win = mock.patch.object(localplayer.sys, "platform", "win32")
        win.start()
        self.addCleanup(win.stop)

    def test_play_opens_one_window(self):
        self.p.play(VID, "RDAMVM" + VID)
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(self.launched[0][1], f"--app=https://music.youtube.com/watch?v={VID}&list=RDAMVM{VID}")
        self.assertTrue(self.p.active)
        self.assertEqual(self.closed, [])

    def test_the_next_song_closes_the_last_window_first(self):
        self.p.play(VID)
        self.p.play("AAAAAAAAAAA")
        self.assertEqual(len(self.closed), 1)
        self.assertEqual(len(self.launched), 2)

    def test_it_says_so_when_there_is_no_browser_or_the_song_is_odd(self):
        self.browser = None
        with self.assertRaisesRegex(localplayer.LocalPlayerError, "Edge or Chrome"):
            self.p.play(VID)
        self.browser = "C:/Edge/msedge.exe"
        with self.assertRaises(localplayer.LocalPlayerError):
            self.p.play("not an id")
        self.assertEqual(self.launched, [])
        self.assertFalse(self.p.available() and self.browser is None)

    def test_pause_and_resume_do_not_double_up(self):
        self.p.play(VID)
        self.assertEqual(self.p.control("pause"), "Paused.")
        self.assertEqual(self.p.control("pause"), "Already paused.")
        self.assertEqual(self.p.control("resume"), "Playing.")
        self.assertEqual(self.p.control("resume"), "Already playing.")
        self.assertEqual(self.pressed, [("playpause", 1), ("playpause", 1)])

    def test_next_and_previous_press_the_media_keys(self):
        self.p.play(VID)
        self.p.control("next")
        self.p.control("previous")
        self.assertEqual(self.pressed, [("next", 1), ("prev", 1)])
        with self.assertRaises(localplayer.LocalPlayerError):
            self.p.control("explode")

    def test_stop_closes_the_window(self):
        self.p.play(VID)
        self.assertEqual(self.p.control("stop"), "Stopped.")
        self.p.closer.join(2)
        self.assertEqual(len(self.closed), 1)
        self.assertFalse(self.p.active)

    def test_volume_up_down_and_to_a_level(self):
        self.p.volume(direction="up")
        self.p.volume(direction="down")
        self.assertEqual(self.pressed, [("volup", 5), ("voldown", 5)])
        self.pressed.clear()
        self.assertEqual(self.p.volume(level=30), "Volume 30 percent.")
        self.assertEqual(self.pressed, [("voldown", 50), ("volup", 15)])
        self.pressed.clear()
        self.p.volume(level=500)
        self.assertEqual(self.pressed, [("voldown", 50), ("volup", 50)])
        with self.assertRaises(localplayer.LocalPlayerError):
            self.p.volume()


class Unreachable(music.MusicError):
    pass


class FakeBackend:
    """Like the speaker backend in test_music, but each thing can fail the way a lost speaker does."""

    def __init__(self, speakers=("Kitchen speaker",), fail_play=False):
        self.speakers, self.fail_play, self.calls = list(speakers), fail_play, []
        self.song = {"video_id": VID, "title": "Bohemian Rhapsody", "artist": "Queen", "playlist_id": "RDAMVM" + VID}

    def devices(self):
        if not self.speakers:
            return []
        return [{"name": n, "kind": "audio"} for n in self.speakers]

    def search(self, query):
        self.calls.append(("search", query))
        return self.song

    def play(self, device, video_id, playlist_id):
        if self.fail_play:
            raise music.SpeakerUnreachable(f"{device} isn't answering. Is it on, and on the same Wi-Fi as this PC?")
        self.calls.append(("play", device))

    def control(self, device, what):
        self.calls.append((what, device))

    def volume(self, device, level=None, delta=None):
        self.calls.append(("volume", device))
        return 0.5

    def now_playing(self, device):
        return {"title": "x", "artist": "y", "state": "PLAYING", "volume": 50}

    def stop(self):
        pass


class FakeLocal:
    def __init__(self, ok=True):
        self.ok, self.calls, self.paused, self.active = ok, [], False, False

    def available(self):
        return self.ok

    def play(self, video_id, playlist_id=None):
        if not self.ok:
            raise localplayer.LocalPlayerError("I can't find Edge or Chrome on this PC to play it in.")
        self.calls.append(("play", video_id, playlist_id))
        self.active = True

    def control(self, what):
        self.calls.append((what,))
        if what == "pause":
            self.paused = True
        if what == "resume":
            self.paused = False
        return {"pause": "Paused.", "resume": "Playing.", "next": "Next song.", "previous": "Previous song.", "stop": "Stopped."}[what]

    def volume(self, level=None, direction=""):
        self.calls.append(("volume", level, direction))
        return f"Volume {level} percent." if level is not None else f"Volume {direction}."


def make(speakers=("Kitchen speaker",), fail_play=False, on=True, local_ok=True, local=True):
    return music.Music(FakeBackend(speakers, fail_play), FakeLocal(local_ok) if local else None, fallback=lambda: on)


class Fallback(unittest.TestCase):
    def test_no_speakers_plays_on_this_pc_and_says_why(self):
        m = make(speakers=())
        say = m.play("bohemian rhapsody")
        self.assertEqual(m.local.calls, [("play", VID, "RDAMVM" + VID)])
        self.assertEqual(say, "I couldn't reach the speaker, so I'm playing Bohemian Rhapsody by Queen on this PC.")
        self.assertEqual((m.where, m.now["device"], m.now["fallback"]), ("here", "this PC", True))

    def test_a_speaker_that_stops_answering_falls_back_and_names_it(self):
        m = make(fail_play=True)
        say = m.play("bohemian rhapsody", "kitchen speaker")
        self.assertTrue(say.startswith("I couldn't reach the kitchen speaker, so I'm playing"), say)
        self.assertEqual(len(m.local.calls), 1)

    def test_a_speaker_that_works_is_used_not_the_pc(self):
        m = make()
        self.assertEqual(m.play("bohemian rhapsody"), "Playing Bohemian Rhapsody by Queen on Kitchen speaker.")
        self.assertEqual(m.local.calls, [])
        self.assertEqual(m.where, "speaker")

    def test_a_mistyped_or_ambiguous_speaker_is_not_a_reason_to_play_on_the_pc(self):
        for speakers, named, words in ((("Kitchen speaker",), "garage speaker", "don't know a speaker"), (("Kitchen speaker", "Bedroom display"), "", "Which speaker")):
            m = make(speakers=speakers)
            with self.assertRaisesRegex(music.MusicError, words):
                m.play("x", named)
            self.assertEqual(m.local.calls, [])

    def test_switched_off_it_gives_the_old_error(self):
        for m in (make(speakers=(), on=False), make(fail_play=True, on=False), make(speakers=(), local=False), make(speakers=(), local_ok=False)):
            with self.assertRaises(music.SpeakerUnreachable):
                m.play("bohemian rhapsody")

    def test_nothing_is_searched_when_it_cannot_be_played_anywhere(self):
        m = make(speakers=(), on=False)
        with self.assertRaises(music.MusicError):
            m.play("x")
        self.assertEqual(m.backend.calls, [])

    def test_when_the_pc_cannot_play_it_either_both_reasons_are_given(self):
        m = make(speakers=(), local_ok=True)
        m.local.ok = True
        m.local.play = mock.Mock(side_effect=localplayer.LocalPlayerError("the browser won't start."))
        with self.assertRaisesRegex(music.MusicError, "don't see any speakers.*couldn't play it on this PC either: the browser won't start"):
            m.play("x")
        self.assertEqual(m.where, "")

    def test_the_cast_add_on_missing_still_lets_the_pc_play(self):
        be = music.CastBackend()
        with mock.patch.dict(sys.modules, {"pychromecast": None, "ytmusicapi": None}):
            with self.assertRaises(music.SpeakerUnreachable):
                be.devices()
            with self.assertRaises(music.MusicError) as caught:
                be.search("x")
            self.assertNotIsInstance(caught.exception, music.SpeakerUnreachable)       # no search add-on: nothing can be found, here or on a speaker

    def test_other_speaker_failures_count_as_unreachable(self):
        be = music.CastBackend()
        be.casts = {"Cove": mock.Mock(**{"wait.side_effect": TimeoutError("x")})}
        be.found_at = 10 ** 12
        be.refresh = lambda force=False: None
        with self.assertRaises(music.SpeakerUnreachable):
            be._cast("Cove")


class Controls(unittest.TestCase):
    def playing_here(self):
        m = make(speakers=())
        m.play("bohemian rhapsody")
        m.local.calls.clear()
        return m

    def test_transport_goes_to_the_pc_while_the_song_is_playing_there(self):
        m = self.playing_here()
        self.assertEqual(m.control("pause"), "Paused.")
        self.assertEqual(m.control("next"), "Next song.")
        self.assertEqual(m.local.calls, [("pause",), ("next",)])
        self.assertEqual(m.backend.calls, [("search", "bohemian rhapsody")])

    def test_stop_ends_it_and_later_commands_go_back_to_the_speakers(self):
        m = self.playing_here()
        m.control("stop")
        self.assertEqual(m.where, "")
        with self.assertRaises(music.SpeakerUnreachable):
            m.control("pause")

    def test_volume_and_status_on_the_pc(self):
        m = self.playing_here()
        self.assertEqual(m.volume(level=30), "Volume 30 percent.")
        self.assertEqual(m.volume(direction="up"), "Volume up.")
        self.assertEqual(m.status(), "Playing Bohemian Rhapsody by Queen on this PC.")
        m.control("pause")
        self.assertEqual(m.status(), "Paused on Bohemian Rhapsody by Queen on this PC.")

    def test_naming_a_speaker_still_talks_to_that_speaker(self):
        m = make(speakers=("Kitchen speaker",))
        m.where = "here"
        m.control("pause", "kitchen")
        self.assertEqual(m.backend.calls, [("pause", "Kitchen speaker")])
        self.assertEqual(m.local.calls, [])

    def test_a_pc_problem_is_a_message_not_a_traceback(self):
        m = self.playing_here()
        m.local.control = mock.Mock(side_effect=localplayer.LocalPlayerError("that isn't something I can do on this PC."))
        with self.assertRaisesRegex(music.MusicError, "isn't something"):
            m.control("pause")


class Voice(unittest.TestCase):
    def test_play_says_why_it_is_on_this_pc(self):
        m = make(speakers=())
        out = music.handle_voice("play bohemian rhapsody", m)
        self.assertEqual((out["handled"], out["ok"]), (True, True))
        self.assertIn("couldn't reach", out["text"])
        self.assertIn("on this PC", out["text"])

    def test_volume_by_voice_on_the_pc_has_an_answer_even_without_a_number(self):
        m = make(speakers=())
        music.handle_voice("play bohemian rhapsody", m)
        for sentence in ("volume up", "turn it down", "set the volume to 20 percent", "pause", "next song", "stop the music"):
            out = music.handle_voice(sentence, m)
            self.assertEqual((out["handled"], out["ok"]), (True, True), sentence)
            self.assertTrue(out["text"], sentence)

    def test_with_the_fallback_off_a_spoken_play_is_an_honest_failure(self):
        out = music.handle_voice("play bohemian rhapsody", make(speakers=(), on=False))
        self.assertEqual((out["handled"], out["ok"]), (True, False))

    def test_the_ai_tool_gets_the_same_sentence(self):
        text = music.tool({"action": "play", "query": "bohemian rhapsody"}, make(speakers=()))
        self.assertIn("on this PC", text)


class Setting(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.object(music, "PREFS", Path(tmp.name) / "music.json")
        patch.start()
        self.addCleanup(patch.stop)

    def test_on_by_default_and_remembered_when_switched(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MUSIC_FALLBACK", None)
            self.assertTrue(music.fallback_enabled())
            music.set_fallback(False)
            self.assertFalse(music.fallback_enabled())
            music.set_fallback(True)
            self.assertTrue(music.fallback_enabled())

    def test_the_environment_can_switch_it_off_for_good(self):
        with mock.patch.dict(os.environ, {"MUSIC_FALLBACK": "0"}):
            music.set_fallback(True)
            self.assertFalse(music.fallback_enabled())

    def test_the_real_music_has_a_real_player_and_the_card_can_switch_it(self):
        self.assertIsInstance(music.instance.local, localplayer.LocalPlayer)
        from server import main
        with mock.patch.object(main.music_mod, "instance", music.Music(FakeBackend(()), FakeLocal(), fallback=music.fallback_enabled)):
            out = main.music_prefs(main.MusicPrefs(fallback=False))
            self.assertFalse(out["fallback"])
            self.assertFalse(music.fallback_enabled())
        root = Path(__file__).resolve().parent.parent
        self.assertIn('id="music-fallback"', (root / "web" / "index.html").read_text(encoding="utf-8"))
        self.assertIn("/api/music/prefs", (root / "web" / "music.js").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
