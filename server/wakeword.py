"""Offline wake word: listens for "Jarvis" on this PC, without sending your room's audio to Google or Microsoft.

It uses Vosk, a small speech recognizer that runs locally, set to recognise only a few words so it is light and quick.
When it hears the name it tells the page at once (so it can play its listening sound), and it keeps listening, on this PC, to what
follows: the words said in the same breath as the name ("Jarvis, turn on the lights") and, if you only said the name, the next
sentence. It sends that text to the page, which acts on it. Nothing is lost between the name and the command, and nothing goes to the
internet. (JARVIS_WAKEWORD_COMMAND=cloud brings back the old way: the browser's cloud recognizer listens after the name.)

The microphone is only open while voice is switched on in the page. Switch it off (the orb, the M key) and this stops reading it and
closes it, so there is nothing to hear "Jarvis".

Optional: needs two Python packages (vosk, sounddevice) and a 40 MB model. Set it up with
    python -m server.wakeword --get-model        (downloads the model once)
and put JARVIS_WAKEWORD=1 in .env. Try it with  python -m server.wakeword --test
"""
from __future__ import annotations

import argparse
import collections
import difflib
import json
import logging
import os
import queue
import re
import sys
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

from . import store

log = logging.getLogger("jarvis")

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODEL_DIR = store.STATE / "models" / MODEL_NAME
SAMPLE_RATE = 16000
# The recognizer is told it can only hear these words ("[unk]" is "anything else"). With only "jarvis" in the list it
# forces similar sounds into it: in testing, "service", "jar of jam" and "harvest" woke it more than half the time. Giving
# it look-alike words to choose from (decoys) stopped that completely. Add your own with JARVIS_WAKEWORD_DECOYS in .env
# (words the model knows, comma-separated) if something in your house keeps waking it.
DECOYS = ("service", "services", "serve", "serves", "travis", "jar", "jars", "harvest", "jervis", "gervais", "survey",
          "nervous", "garbage", "marvelous", "carvers", "carving", "charles", "marcus")


def grammar() -> str:
    extra = [w.strip().lower() for w in os.getenv("JARVIS_WAKEWORD_DECOYS", "").split(",") if w.strip().isalpha()]
    return json.dumps(["jarvis", *DECOYS, *extra, "[unk]"])


GRAMMAR = grammar()
NAME = re.compile(r"\b(jarvis|jarvas|jarvus|jarves|jervis)\b")      # "jervis" is how many accents come out: it counts
NAME_WORDS = frozenset({"jarvis", "jarvas", "jarvus", "jarves", "jervis"})
AMBIGUOUS = frozenset({"jervis"})            # also what "Gervais" sounds like, so it has to be heard for longer
COOLDOWN = 4.0   # seconds before the same word can wake it again
PREROLL = 8      # blocks (a quarter of a second each) of audio kept from before the name was recognised, so the command is heard from its first word
FOLLOW_UP = 8.0  # seconds after the name that a command is waited for
LINGER = 0.9     # after the first words of a command, this long without more speech means it is finished
MAX_COMMAND = 15.0
FILLERS = frozenset({"hey", "ok", "okay", "hi", "yo"})
CLIENT_TTL = 20.0    # a page that has not said "voice is on" for this long no longer counts

# How sure it has to be before it wakes. The recognizer is only allowed a handful of words, so it tends to force any speech into them; in a
# test with 30 minutes of ordinary talk it woke about 100 times an hour on words that were not the name. The fix is to make it prove it: the
# name has to be the first word (or the second, after "hey"), and still be the recognizer's answer on several updates in a row (each is a
# quarter of a second), or come out as its confident final answer. Briefly passing look-alikes ("Gervais") no longer count. Set
# JARVIS_WAKEWORD_SENSITIVITY=high if it ever seems deaf, or low if it still wakes on things you did not say.
SENSITIVITY = {"high": (2, 3), "normal": (3, 5), "low": (4, 7)}      # updates in a row: (for the name, for the ambiguous "jervis")


def sensitivity() -> tuple[int, int]:
    return SENSITIVITY.get(os.getenv("JARVIS_WAKEWORD_SENSITIVITY", "normal").strip().lower(), SENSITIVITY["normal"])


def available() -> bool:
    """Are the two packages installed?"""
    try:
        import sounddevice  # noqa: F401
        import vosk  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def model_ready(path: Path | None = None) -> bool:
    return ((path or MODEL_DIR) / "am" / "final.mdl").exists()


def block_level(data: bytes) -> float:
    """How loud a block of 16-bit audio is: 0 (silence) to 1 (as loud as it gets)."""
    from array import array
    samples = array("h")
    samples.frombytes(data[: len(data) // 2 * 2])
    if not samples:
        return 0.0
    return (sum(s * s for s in samples) / len(samples)) ** 0.5 / 32768


def command_after_name(text: str) -> str:
    """The command in what was heard: the words after the name ("jarvis turn on the lights" -> "turn on the lights"). When the name is not
    among the first few words (the recognizer missed it), everything that was heard, minus a leading "hey"/"okay"."""
    words = str(text).lower().split()
    for i, w in enumerate(words[:4]):
        if w in NAME_WORDS or difflib.SequenceMatcher(None, w, "jarvis").ratio() >= 0.8:
            return " ".join(words[i + 1:])
    while words and words[0] in FILLERS:
        words.pop(0)
    return " ".join(words)


class CommandCapture:
    """After the name is heard: turns what is said next into text with a free-vocabulary recognizer, on this PC.

    It is given the audio from just before the name was recognised, so the words said in the same breath are not lost, then the live audio.
    feed() returns None while it is still listening, and the command (or "" if nothing followed the name) once it is finished."""

    def __init__(self, recognizer, preroll, now: float, follow_up: float = FOLLOW_UP, linger: float = LINGER, longest: float = MAX_COMMAND) -> None:
        self.rec = recognizer
        self.start = now
        self.follow_up, self.linger, self.longest = follow_up, linger, longest
        self.texts: list[str] = []
        self.quiet_from: float | None = None        # when a heard command started to wait for more speech
        for block in preroll:
            self._accept(block)

    def _accept(self, block: bytes) -> bool:
        if self.rec.AcceptWaveform(block):
            text = json.loads(self.rec.Result()).get("text", "").strip()
            if text:
                self.texts.append(text)
            return True
        return False

    def command(self) -> str:
        return command_after_name(" ".join(self.texts))

    def feed(self, block: bytes, now: float) -> str | None:
        final = self._accept(block)
        heard = self.command()
        if not heard:
            return "" if now - self.start >= self.follow_up else None          # only the name so far: wait for the next sentence
        if now - self.start >= self.longest:
            return heard
        if final:
            self.quiet_from = now                                              # a sentence ended: wait a moment for the rest of the command
        elif json.loads(self.rec.PartialResult()).get("partial", "").strip():
            self.quiet_from = None                                             # more speech is coming in
        elif self.quiet_from is None:
            self.quiet_from = now
        if self.quiet_from is not None and now - self.quiet_from >= self.linger:
            return heard
        return None


class Detector:
    """Decides, from the recognizer's updates, whether the name was really said (once per cooldown).

    Call hears() with every update: `text` is what the recognizer thinks right now (a partial result, or a final one with final=True and
    the confidence of its best word)."""

    def __init__(self, cooldown: float = COOLDOWN, need: int | None = None, need_ambiguous: int | None = None) -> None:
        default = sensitivity()
        self.cooldown = cooldown
        self.need = need if need is not None else default[0]
        self.need_ambiguous = need_ambiguous if need_ambiguous is not None else default[1]
        self.last = -1e9
        self.streak = 0
        self.word = ""
        self.armed = True            # after a wake, the same utterance has to end (or change) before it can wake again

    def hears(self, text: str, now: float | None = None, final: bool = False, conf: float = 1.0) -> bool:
        now = time.monotonic() if now is None else now
        words = str(text).lower().split()
        i = 1 if len(words) > 1 and words[0] not in NAME_WORDS else 0      # one word may come first: "hey" is often heard as a look-alike
        name = words[i] if i < len(words) else ""
        if name not in NAME_WORDS:
            self.streak, self.word, self.armed = 0, "", True
            return False
        self.streak = self.streak + 1 if name == self.word else 1
        self.word = name
        need = self.need_ambiguous if name in AMBIGUOUS else self.need
        sure = self.streak >= need or (final and conf >= 0.9 and name not in AMBIGUOUS)
        if sure and self.armed and now - self.last >= self.cooldown:
            self.last, self.armed = now, False
            return True
        return False


class Pipeline:
    """The listening logic without the microphone: feed it blocks of audio (a quarter of a second each) and it calls on_wake() when the name is
    heard and on_command(text) when what followed has been understood. WakeWord feeds it from the microphone; tools/wake_eval.py from recordings."""

    def __init__(self, model, vosk, on_wake, on_command=None, commands: bool = True) -> None:
        self.model, self.vosk = model, vosk
        self.rec = vosk.KaldiRecognizer(model, SAMPLE_RATE, grammar())
        if hasattr(self.rec, "SetWords"):
            self.rec.SetWords(True)                     # final results then say how sure the recognizer is of each word
        self.detector = Detector()
        self.recent: collections.deque[bytes] = collections.deque(maxlen=PREROLL)
        self.capture: CommandCapture | None = None
        self.on_wake, self.on_command = on_wake, on_command
        self.commands = commands and on_command is not None
        self.last_text = ""
        self.last_wake = 0.0

    def feed(self, data: bytes, now: float) -> None:
        self.recent.append(data)
        if self.capture is not None:
            spoken = self.capture.feed(data, now)
            if spoken is not None:
                self.capture = None
                self.on_command(spoken)
        final, conf = self.rec.AcceptWaveform(data), 0.0
        if final:
            result = json.loads(self.rec.Result())
            text = result.get("text", "")
            conf = max((w.get("conf", 0.0) for w in result.get("result", []) if w.get("word") in NAME_WORDS), default=0.0)
        else:
            text = json.loads(self.rec.PartialResult()).get("partial", "")
        if text and text != "[unk]":
            self.last_text = text[-60:]
        if self.detector.hears(text, now=now, final=final, conf=conf):
            self.last_wake = time.time()
            try:
                self.on_wake()
            except Exception:  # noqa: BLE001 - a failing page notification must not stop the listener
                log.exception("wake word callback failed")
            if self.commands and self.capture is None:
                self.capture = CommandCapture(self.vosk.KaldiRecognizer(self.model, SAMPLE_RATE), list(self.recent), now)


class WakeWord:
    """A background listener. on_wake() is called (from its own thread) each time the name is heard, and on_command(text) with what was said
    after it (when commands are captured here). The microphone is open only while a page has said voice is on (vote())."""

    def __init__(self, on_wake, device=None, model_path: Path | None = None, on_command=None) -> None:
        self.on_wake = on_wake
        self.on_command = on_command
        self.device = device
        self.model_path = model_path or MODEL_DIR
        self.detector = Detector()
        self.thread: threading.Thread | None = None
        self.stop_flag = threading.Event()
        self.running = False             # the listener is alive and healthy
        self.listening = False           # the microphone is open right now
        self.error = ""
        self.commands = on_command is not None and os.getenv("JARVIS_WAKEWORD_COMMAND", "offline").strip().lower() != "cloud"
        self.clients: dict[str, tuple[bool, float]] = {}      # page id -> (wants voice on, when it last said so)
        self.lock = threading.Lock()
        # what the listener is doing, shown in the status menu so a silent microphone problem can be seen at a glance
        self.device_name = ""
        self.blocks = 0
        self.level = 0.0                 # how loud the microphone is right now (0 to 1, smoothed)
        self.last_block = 0.0
        self.last_text = ""              # the last words it recognised, including look-alikes
        self.last_wake = 0.0
        self.last_command = ""

    # ---- who wants the microphone ----
    def vote(self, client: str, on: bool) -> None:
        """A page says whether voice is on. The microphone is open while at least one page that said so recently wants it."""
        with self.lock:
            self.clients[str(client)[:64]] = (bool(on), time.monotonic())
            if len(self.clients) > 32:                                       # old pages that are gone
                for key in sorted(self.clients, key=lambda k: self.clients[k][1])[:16]:
                    self.clients.pop(key, None)

    def wanted(self) -> bool:
        now = time.monotonic()
        with self.lock:
            return any(on and now - t < CLIENT_TTL for on, t in self.clients.values())

    def start(self) -> None:
        if not available():
            self.error = "the vosk and sounddevice packages aren't installed"
            return
        if not model_ready(self.model_path):
            self.error = "the speech model isn't downloaded (run: python -m server.wakeword --get-model)"
            return
        self.stop_flag.clear()
        self.thread = threading.Thread(target=self._run, daemon=True, name="wakeword")
        self.thread.start()

    def stop(self) -> None:
        self.stop_flag.set()
        if self.thread:
            self.thread.join(timeout=3)

    def status(self) -> dict:
        return {"running": self.running, "listening": self.listening, "wanted": self.wanted(), "commands": self.commands, "error": self.error, "device": self.device_name,
                "level": round(self.level, 4), "blocks": self.blocks, "heard_ago": round(time.time() - self.last_block, 1) if self.last_block else None,
                "last_text": self.last_text, "last_wake": int(self.last_wake), "last_command": self.last_command}

    def _run(self) -> None:
        try:
            import vosk

            vosk.SetLogLevel(-1)
            model = vosk.Model(str(self.model_path))
            self.running, self.error = True, ""
            while not self.stop_flag.is_set():
                if not self.wanted():
                    self.listening = False
                    self.stop_flag.wait(0.4)                   # voice is off: the microphone stays closed
                    continue
                self._listen(model)
        except Exception as e:  # noqa: BLE001 - report it in the status menu instead of dying silently
            self.error = f"{e.__class__.__name__}: {e}"
            log.warning("wake word stopped: %s", self.error)
        finally:
            self.running = self.listening = False

    def _listen(self, model) -> None:
        """Reads the microphone until voice is switched off or JARVIS stops; the microphone is closed when this returns."""
        import sounddevice as sd
        import vosk

        audio: queue.Queue[bytes] = queue.Queue(maxsize=50)
        pipe = Pipeline(model, vosk, self._woke, self._said, self.commands)
        self.detector = pipe.detector

        def take(indata, frames, t, status):  # noqa: ARG001 - sounddevice's signature
            try:
                audio.put_nowait(bytes(indata))
            except queue.Full:
                pass                                      # fall behind rather than grow

        try:
            self.device_name = str(sd.query_devices(self.device, "input")["name"])
        except Exception:  # noqa: BLE001 - the name is only for display
            self.device_name = ""
        with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16", channels=1, device=self.device, callback=take):
            self.listening = True
            log.info("wake word listening (offline) on %s", self.device_name or "the default microphone")
            while not self.stop_flag.is_set() and self.wanted():
                try:
                    data = audio.get(timeout=0.5)
                except queue.Empty:
                    continue
                self.blocks += 1
                self.last_block = time.time()
                self.level = 0.7 * self.level + 0.3 * block_level(data)
                pipe.feed(data, time.monotonic())
                if pipe.last_text:
                    self.last_text = pipe.last_text
        self.listening = False

    def _woke(self) -> None:
        self.last_wake = time.time()
        self.on_wake()

    def _said(self, text: str) -> None:
        self.last_command = text
        if self.on_command:
            try:
                self.on_command(text)
            except Exception:  # noqa: BLE001
                log.exception("command callback failed")


def download_model() -> None:
    """Downloads and unpacks the model (about 40 MB) from alphacephei.com, the Vosk project's own site."""
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    zip_path = MODEL_DIR.parent / f"{MODEL_NAME}.zip"
    print(f"downloading {MODEL_URL}\n  to {zip_path}", flush=True)
    urllib.request.urlretrieve(MODEL_URL, zip_path)
    with zipfile.ZipFile(zip_path) as z:
        for member in z.namelist():                   # refuse anything that would unpack outside the models folder
            if Path(member).is_absolute() or ".." in Path(member).parts:
                raise SystemExit("the download contains an unsafe path; not unpacking it")
        z.extractall(MODEL_DIR.parent)
    zip_path.unlink(missing_ok=True)
    if not model_ready():
        raise SystemExit("the model didn't unpack as expected")
    print(f"done: {MODEL_DIR}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m server.wakeword", description=__doc__.splitlines()[0])
    ap.add_argument("--get-model", action="store_true", help="download the speech model (about 40 MB) and exit")
    ap.add_argument("--test", type=float, nargs="?", const=20.0, metavar="SECONDS", help="listen for this long and print each time the name is heard")
    ap.add_argument("--list-devices", action="store_true", help="list microphones and exit")
    args = ap.parse_args(argv)
    if args.get_model:
        download_model()
        return 0
    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0
    if args.test is not None:
        w = WakeWord(lambda: print(f"[{time.strftime('%H:%M:%S')}] heard “Jarvis”", flush=True), device=os.getenv("JARVIS_WAKEWORD_DEVICE") or None,
                     on_command=lambda text: print(f"[{time.strftime('%H:%M:%S')}]   then: {text!r}" if text else f"[{time.strftime('%H:%M:%S')}]   (nothing followed)", flush=True))
        w.vote("test", True)
        w.start()
        time.sleep(1.5)
        if w.error:
            print("Can't listen:", w.error)
            return 1
        print(f"Listening for {args.test:.0f} seconds. Say “Jarvis”.", flush=True)
        time.sleep(args.test)
        w.stop()
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
