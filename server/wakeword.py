"""Offline wake word: listens for "Jarvis" on this PC, without sending your room's audio to Google or Microsoft.

It uses Vosk, a small speech recognizer that runs locally, set to recognise only a few words so it is light and quick.
When it hears the name it tells the page, and only then does the page turn on the browser's (cloud) speech recognition,
for the command that follows. So the always-on part stays on the PC.

Optional: needs two Python packages (vosk, sounddevice) and a 40 MB model. Set it up with
    python -m server.wakeword --get-model        (downloads the model once)
and put JARVIS_WAKEWORD=1 in .env. Try it with  python -m server.wakeword --test
"""
from __future__ import annotations

import argparse
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


class WakeWord:
    """A background listener. on_wake() is called (from its own thread) each time the name is heard."""

    def __init__(self, on_wake, device=None, model_path: Path | None = None) -> None:
        self.on_wake = on_wake
        self.device = device
        self.model_path = model_path or MODEL_DIR
        self.detector = Detector()
        self.thread: threading.Thread | None = None
        self.stop_flag = threading.Event()
        self.running = False
        self.error = ""
        # what the listener is doing, shown in the status menu so a silent microphone problem can be seen at a glance
        self.device_name = ""
        self.blocks = 0
        self.level = 0.0                 # how loud the microphone is right now (0 to 1, smoothed)
        self.last_block = 0.0
        self.last_text = ""              # the last words it recognised, including look-alikes
        self.last_wake = 0.0

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
        return {"running": self.running, "error": self.error, "device": self.device_name, "level": round(self.level, 4), "blocks": self.blocks,
                "heard_ago": round(time.time() - self.last_block, 1) if self.last_block else None, "last_text": self.last_text,
                "last_wake": int(self.last_wake)}

    def _run(self) -> None:
        try:
            import sounddevice as sd
            import vosk

            vosk.SetLogLevel(-1)
            recognizer = vosk.KaldiRecognizer(vosk.Model(str(self.model_path)), SAMPLE_RATE, grammar())
            if hasattr(recognizer, "SetWords"):
                recognizer.SetWords(True)                 # final results then say how sure the recognizer is of each word
            audio: queue.Queue[bytes] = queue.Queue(maxsize=50)

            def capture(indata, frames, t, status):  # noqa: ARG001 - sounddevice's signature
                try:
                    audio.put_nowait(bytes(indata))
                except queue.Full:
                    pass                                  # fall behind rather than grow

            try:
                self.device_name = str(sd.query_devices(self.device, "input")["name"])
            except Exception:  # noqa: BLE001 - the name is only for display
                self.device_name = ""
            with sd.RawInputStream(samplerate=SAMPLE_RATE, blocksize=4000, dtype="int16", channels=1, device=self.device, callback=capture):
                self.running, self.error = True, ""
                log.info("wake word listening (offline) on %s", self.device_name or "the default microphone")
                while not self.stop_flag.is_set():
                    try:
                        data = audio.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    self.blocks += 1
                    self.last_block = time.time()
                    self.level = 0.7 * self.level + 0.3 * block_level(data)
                    final, conf = recognizer.AcceptWaveform(data), 0.0
                    if final:
                        result = json.loads(recognizer.Result())
                        text = result.get("text", "")
                        conf = max((w.get("conf", 0.0) for w in result.get("result", []) if w.get("word") in NAME_WORDS), default=0.0)
                    else:
                        text = json.loads(recognizer.PartialResult()).get("partial", "")
                    if text and text != "[unk]":
                        self.last_text = text[-60:]
                    if self.detector.hears(text, final=final, conf=conf):
                        self.last_wake = time.time()
                        try:
                            self.on_wake()
                        except Exception:  # noqa: BLE001 - a failing page notification must not stop the listener
                            log.exception("wake word callback failed")
        except Exception as e:  # noqa: BLE001 - report it in the status menu instead of dying silently
            self.error = f"{e.__class__.__name__}: {e}"
            log.warning("wake word stopped: %s", self.error)
        finally:
            self.running = False


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
        w = WakeWord(lambda: print(f"[{time.strftime('%H:%M:%S')}] heard “Jarvis”", flush=True), device=os.getenv("JARVIS_WAKEWORD_DEVICE") or None)
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
