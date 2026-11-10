"""Music on your Google Home / Nest speakers, from YouTube Music.

What it does: finds a song on YouTube Music and plays it on a speaker over Cast (the same way the YouTube or YouTube Music app
"casts" to a speaker), and then pauses, resumes, skips and sets the volume. That is all it can do. It cannot reach any other
device, and it doesn't use your Google or YouTube account, so it has no access to your library or playlists: it plays what you
ask for by name.

Two small add-ons do the work and are installed once (JARVIS asks first): `pychromecast` talks to the speakers on your
Wi-Fi, and `ytmusicapi` searches YouTube Music (an unofficial but widely used library; it needs no login for searching).
Both are imported only when music is used, so JARVIS runs fine without them.

Settings in .env (optional): MUSIC_DEVICE=Kitchen speaker (the speaker used when none is named), JARVIS_MUSIC=0 turns it off.
"""
from __future__ import annotations

import functools
import logging
import os
import re
import threading
import time

from . import persona

log = logging.getLogger("jarvis")

INSTALL_HINT = ("Music needs two small add-ons that aren't installed yet. Run:  pip install -r requirements-music.txt  "
                "(from the JARVIS folder, using JARVIS's own Python), then restart JARVIS.")
REFRESH_EVERY = 6 * 3600.0       # the finder keeps running and notices speakers by itself; a missing name forces a new look


class MusicError(Exception):
    """Something the user can act on; the message says what."""


def _local_ip() -> str:
    """This PC's address on the current network (nothing is sent). It changes when the PC joins another Wi-Fi."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
    except OSError:
        return ""


def _speaker_call(fn):
    """Whatever goes wrong while talking to a speaker (a timeout, a closed connection) becomes a message the person can act on, not a crash."""
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except MusicError:
            raise
        except Exception as e:  # noqa: BLE001
            raise MusicError(f"the speaker didn't respond ({e.__class__.__name__}).") from None
    return inner


# ---- the real speakers and YouTube Music ------------------------------------------------------------

class CastBackend:
    """pychromecast and ytmusicapi behind a few plain methods (tests replace this whole class with a fake)."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.casts: dict = {}
        self.browser = None
        self.found_at = 0.0
        self.network = ""
        self.handlers: dict = {}
        self._yt = None

    @staticmethod
    def _import(name: str):
        try:
            return __import__(name, fromlist=["x"])
        except ImportError:
            raise MusicError(INSTALL_HINT) from None

    def refresh(self, force: bool = False) -> None:
        with self.lock:
            if self.casts and not force and time.time() - self.found_at < REFRESH_EVERY:
                return
            pc = self._import("pychromecast")
            if self.browser is not None:
                try:
                    pc.discovery.stop_discovery(self.browser)
                except Exception:  # noqa: BLE001 - an old browser that won't stop is not worth failing for
                    pass
            try:
                casts, browser = pc.get_chromecasts(timeout=6)
            except Exception as e:  # noqa: BLE001
                raise MusicError(f"couldn't look for speakers on the network ({e.__class__.__name__}).") from None
            self.browser, self.found_at, self.network = browser, time.time(), _local_ip()
            self.casts = {c.cast_info.friendly_name.strip(): c for c in casts}
            self.handlers = {}

    def devices(self) -> list[dict]:
        self.refresh()
        return [{"name": n, "kind": getattr(c.cast_info, "cast_type", "") or "cast"} for n, c in self.casts.items()]

    def _cast(self, name: str):
        """The connected speaker. If the old connection is dead (the PC moved to another Wi-Fi, or the speaker was off and came back) it looks
        again once instead of failing with the same stale connection until the list expires: that is what made music fail in a demo."""
        if self.casts and self.network and _local_ip() != self.network:
            self.refresh(force=True)                       # the PC is on another network than when the speakers were found
        self.refresh()
        for attempt in (1, 2):
            cast = self.casts.get(name)
            if not cast:
                self.refresh(force=True)
                cast = self.casts.get(name)
            if not cast:
                raise MusicError(f"I can't find a speaker called {name}. Is it on and on the same Wi-Fi?")
            try:
                cast.wait(timeout=8)
                return cast
            except Exception:  # noqa: BLE001 - a timeout or a closed connection: look for the speaker again
                if attempt == 2:
                    raise MusicError(f"{name} isn't answering. Is it on, and on the same Wi-Fi as this PC?") from None
                self.refresh(force=True)

    def search(self, query: str) -> dict:
        ym = self._import("ytmusicapi")
        try:
            if self._yt is None:
                self._yt = ym.YTMusic()
            hits = [r for r in self._yt.search(query, filter="songs", limit=5) if r.get("videoId")]
            if not hits:
                raise MusicError(f"I couldn't find “{query}” on YouTube Music.")
            top = hits[0]
            playlist = None
            try:
                playlist = self._yt.get_watch_playlist(videoId=top["videoId"], radio=True, limit=25).get("playlistId")
            except Exception:  # noqa: BLE001 - without the radio it just plays that one song
                pass
            return {"video_id": top["videoId"], "title": top.get("title", query), "artist": ", ".join(a["name"] for a in top.get("artists", []) if a.get("name")),
                    "playlist_id": playlist}
        except MusicError:
            raise
        except Exception as e:  # noqa: BLE001 - an unofficial library can break when YouTube changes
            raise MusicError(f"YouTube Music search failed ({e.__class__.__name__}). It may have changed; try again later.") from None

    def play(self, device: str, video_id: str, playlist_id: str | None) -> None:
        from_pc = self._import("pychromecast.controllers.youtube")
        for attempt in (1, 2):
            cast = self._cast(device)
            with self.lock:
                handler = self.handlers.get(device)
                if handler is None:
                    handler = self.handlers[device] = from_pc.YouTubeController()
                    cast.register_handler(handler)
            try:
                handler.play_video(video_id, playlist_id=playlist_id)
                return
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    raise MusicError(f"the speaker didn't accept that ({e.__class__.__name__}).") from None
                self.refresh(force=True)                  # a stale connection: connect again and try once more

    @_speaker_call
    def control(self, device: str, what: str) -> None:
        mc = self._cast(device).media_controller
        mc.update_status()
        {"pause": mc.pause, "resume": mc.play, "stop": mc.stop, "next": mc.queue_next, "previous": mc.queue_prev}[what]()

    @_speaker_call
    def volume(self, device: str, level: float | None = None, delta: float | None = None) -> float:
        cast = self._cast(device)
        current = cast.status.volume_level if cast.status else 0.3
        new = max(0.0, min(1.0, level if level is not None else current + (delta or 0.0)))
        cast.set_volume(new)
        return new

    @_speaker_call
    def now_playing(self, device: str) -> dict:
        cast = self._cast(device)
        mc = cast.media_controller
        mc.update_status()
        s = mc.status
        return {"title": getattr(s, "title", None), "artist": getattr(s, "artist", None), "state": getattr(s, "player_state", None),
                "volume": round((cast.status.volume_level if cast.status else 0) * 100)}

    def stop(self) -> None:
        if self.browser is not None:
            try:
                self._import("pychromecast").discovery.stop_discovery(self.browser)
            except Exception:  # noqa: BLE001
                pass
            self.browser = None


# ---- what the user asked for -------------------------------------------------------------------------

class Music:
    def __init__(self, backend=None) -> None:
        self.backend = backend or CastBackend()
        self.last_device = ""
        self.now: dict = {}

    def devices(self) -> list[dict]:
        return self.backend.devices()

    def choose(self, device: str = "") -> str:
        """The speaker a command is for: the one named, else MUSIC_DEVICE, else the last one used, else the only one there is."""
        known = [d["name"] for d in self.devices()]
        if not known:
            raise MusicError("I don't see any speakers on the network. Check that they're on and on the same Wi-Fi as this PC.")
        want = re.sub(r"\b(the|my|speakers?|display|nest|google|home|mini|in|on)\b", " ", (device or "").lower()).strip()
        want = re.sub(r"\s+", " ", want)
        if want:
            words = want.split()
            hits = [n for n in known if all(w in n.lower() for w in words)]
            if len(hits) == 1:
                return hits[0]
            if hits:
                raise MusicError(f"“{device}” could be {', '.join(hits)}. Which one?")
            raise MusicError(f"I don't know a speaker called “{device}”. Your speakers: {', '.join(known)}.")
        pref = os.getenv("MUSIC_DEVICE", "").strip().lower()
        for n in known:
            if pref and pref in n.lower():
                return n
        if self.last_device in known:
            return self.last_device
        if len(known) == 1:
            return known[0]
        raise MusicError(f"Which speaker? Your speakers: {', '.join(known)}.")

    def play(self, query: str, device: str = "") -> str:
        query = re.sub(r"\s+", " ", str(query or "")).strip()
        if not query:
            raise MusicError("what should I play?")
        name = self.choose(device)
        song = self.backend.search(query)
        self.backend.play(name, song["video_id"], song.get("playlist_id"))
        self.last_device = name
        self.now = {"title": song["title"], "artist": song["artist"], "device": name}
        by = f" by {song['artist']}" if song["artist"] else ""
        return f"Playing {song['title']}{by} on {name}."

    def control(self, what: str, device: str = "") -> str:
        name = self.choose(device)
        self.backend.control(name, what)
        self.last_device = name
        return {"pause": "Paused.", "resume": "Playing.", "stop": "Stopped.", "next": "Next song.", "previous": "Previous song."}[what]

    def volume(self, level: int | None = None, direction: str = "", device: str = "") -> str:
        name = self.choose(device)
        if level is not None:
            new = self.backend.volume(name, level=max(0, min(100, int(level))) / 100)
        else:
            new = self.backend.volume(name, delta=0.1 if direction == "up" else -0.1 if direction == "down" else 0.0)
        self.last_device = name
        return f"Volume {round(new * 100)} percent."

    def status(self, device: str = "") -> str:
        name = self.choose(device)
        n = self.backend.now_playing(name)
        if not n.get("title") or n.get("state") in (None, "IDLE", "UNKNOWN"):
            return f"Nothing is playing on {name}."
        by = f" by {n['artist']}" if n.get("artist") else ""
        return f"{'Playing' if n.get('state') == 'PLAYING' else 'Paused on'} {n['title']}{by} on {name}, volume {n['volume']} percent."

    def view(self) -> dict:
        try:
            return {"devices": self.devices(), "now": self.now, "last": self.last_device, "error": ""}
        except MusicError as e:
            return {"devices": [], "now": self.now, "last": self.last_device, "error": str(e)}


# ---- spoken commands ------------------------------------------------------------------------------------

_DEVICE_TAIL = re.compile(r"^(.*?)(?: (?:on|in|at|through|using)(?: the| my)? ([a-z0-9' ]+?))?$")
QUESTION = re.compile(r"^(what|which|who|how|why|when|where|is|are|do|does|did)\b")


def parse_command(text: str) -> dict | None:
    """Turns "play bohemian rhapsody on the kitchen speaker" into {action, query, device} etc., or None if it isn't about music."""
    t = re.sub(r"[^a-z0-9' %]", " ", str(text).lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"^(?:hey )?jarvis ", "", t)
    t = re.sub(r"^(?:please|can you|could you|will you) ", "", t)
    t = re.sub(r" please$", "", t)
    if re.fullmatch(r"(?:what(?:'s| is) )?(?:currently |now )?playing(?: right now)?|what(?:'s| is| song is) (?:this|that|this song|that song)(?: song)?|what song is (?:this|playing)", t):
        return {"action": "status"}
    if QUESTION.match(t):
        return None
    if re.fullmatch(r"(?:pause|hold)(?: the)?(?: music| song| playback| it)?", t):
        return {"action": "pause"}
    if re.fullmatch(r"(?:resume|continue|unpause|keep playing|play)(?: the| some)?(?: music| song| playback| it)?|(?:un ?pause)(?: the music)?", t):
        return {"action": "resume"}
    if re.fullmatch(r"stop (?:the )?(?:music|song|playing|playback)|stop it playing|turn (?:the )?music off|music off", t):
        return {"action": "stop"}
    if re.fullmatch(r"(?:next|skip)(?: this| the)?(?: song| track)?|next song|play (?:the )?next (?:song|track)", t):
        return {"action": "next"}
    if re.fullmatch(r"(?:previous|last|go back)(?: a)?(?: song| track)?|play (?:the )?(?:previous|last) (?:song|track)|back a song", t):
        return {"action": "previous"}
    m = re.fullmatch(r"(?:set |turn |put )?(?:the )?(?:music |speaker |volume )*(?:volume )?(?:to |at )?(\d{1,3}) ?(?:%|percent)?", t) if re.search(r"volume", t) else None
    if m and 0 <= int(m.group(1)) <= 100:
        return {"action": "volume", "level": int(m.group(1))}
    if re.fullmatch(r"(?:turn |bring )?(?:the )?(?:music |volume |it |speaker )?(?:volume )?up(?: a bit| a little)?|louder|volume up|turn it up|(?:make it|a bit) louder", t):
        return {"action": "volume", "direction": "up"}
    if re.fullmatch(r"(?:turn |bring )?(?:the )?(?:music |volume |it |speaker )?(?:volume )?down(?: a bit| a little)?|quieter|softer|volume down|turn it down|(?:make it|a bit) quieter", t):
        return {"action": "volume", "direction": "down"}
    m = re.match(r"play (.+)$", t)
    if m:
        rest = re.sub(r"^(?:me |us )?(?:some |the song |the track |song |songs by |music by |something by )?", "", m.group(1)).strip()
        dm = _DEVICE_TAIL.match(rest)
        query, device = (dm.group(1).strip(), (dm.group(2) or "").strip()) if dm else (rest, "")
        if device and not re.search(r"speaker|display|nest|home|mini|kitchen|bedroom|living|room|office|bathroom|garage|everywhere|downstairs|upstairs|hub|tv", device):
            query, device = rest, ""                      # "play dancing on the ceiling": that's a song, not a speaker
        if query:
            return {"action": "play", "query": query, "device": device}
    return None


def handle_voice(text: str, music: Music | None = None) -> dict:
    """A spoken or typed music command: {handled, ok, text}. handled is False when it isn't about music."""
    cmd = parse_command(text)
    if cmd is None:
        return {"handled": False, "text": ""}
    m = music or instance
    try:
        a = cmd["action"]
        if a == "play":
            m.play(cmd["query"], cmd.get("device", ""))
            say = persona.music_reply(cmd, m.now)
        elif a == "volume":
            result = m.volume(cmd.get("level"), cmd.get("direction", ""))
            say = persona.music_reply(cmd, level_after=int(re.search(r"\d+", result).group()))
        elif a == "status":
            say = m.status()
        else:
            m.control(a)
            say = persona.music_reply(cmd)
        return {"handled": True, "ok": True, "text": say}
    except MusicError as e:
        return {"handled": True, "ok": False, "text": persona.failure(str(e))}


def tool(args: dict, music: Music | None = None) -> str:
    """The AI's `music` tool. Errors come back as text starting with 'Error'."""
    m = music or instance
    action = str(args.get("action") or "")
    device = str(args.get("device") or "")
    try:
        if action == "devices":
            return "\n".join(f"- {d['name']} ({d['kind']})" for d in m.devices()) or "No speakers found."
        if action == "play":
            return m.play(str(args.get("query") or ""), device)
        if action in ("pause", "resume", "stop", "next", "previous"):
            return m.control(action, device)
        if action == "volume":
            level = args.get("volume")
            return m.volume(int(level) if level is not None else None, str(args.get("direction") or ""), device)
        if action == "status":
            return m.status(device)
        return "Error: action must be one of play, pause, resume, stop, next, previous, volume, status, devices."
    except (MusicError, ValueError, TypeError) as e:
        return f"Error: {e}"


def available() -> bool:
    return os.getenv("JARVIS_MUSIC", "1") != "0"


instance = Music()
