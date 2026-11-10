"""Measures how well "Jarvis, <command>" is understood on this PC, using the very same code as the live listener (server.wakeword.Pipeline).

    1. make clips (Windows voices say natural commands):   powershell tools\\make_command_clips.ps1 <folder>
    2. python tools\\command_eval.py <folder>

Two things are checked for every clip:
  in one breath  "Jarvis, turn on the lights" is said straight through: was the command understood, and how soon after you stopped talking?
  with a pause   "Jarvis", a pause, then the command (the old way): is it still understood?
Synthetic voices are kinder than a noisy room: use the numbers to compare changes, not as a promise.
"""
from __future__ import annotations

import glob
import os
import sys
import wave
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vosk  # noqa: E402

from server import wakeword  # noqa: E402

BLOCK = 4000          # samples per update: a quarter of a second, as in the live listener

SAME_BREATH = {
    "c01": "turn on the lights", "c02": "what is the weather like today", "c03": "play some jazz music", "c04": "show me a three d model of a cat",
    "c05": "set a timer for ten minutes", "c06": "how tall is mount everest", "c07": "open discord", "c08": "show off",
    "c09": "draw a house with a red roof on the board", "c10": "what time is it in tokyo",
}
AFTER_A_PAUSE = {"p01": "turn on the lights", "p02": "what is the weather like today", "p03": "show me a three d model of a cat"}


def pcm(path: str) -> array:
    with wave.open(path, "rb") as w:
        a = array("h")
        a.frombytes(w.readframes(w.getnframes()))
        return a


def run(model, samples: array) -> tuple[list[tuple[float, str]], list[float]]:
    """Feeds the audio like the microphone would. Returns [(seconds, command)] and the seconds at which the name was heard."""
    woke: list[float] = []
    got: list[tuple[float, str]] = []
    clock = [0.0]
    pipe = wakeword.Pipeline(model, vosk, lambda: woke.append(clock[0]), lambda text: got.append((clock[0], text)))
    raw = samples.tobytes() + b"\x00\x00" * 16000 * 12                 # then silence, long enough for the follow-up time to run out
    for i in range(0, len(raw), BLOCK * 2):
        clock[0] += 0.25
        pipe.feed(raw[i:i + BLOCK * 2], clock[0])
        if got:
            break
    return got, woke


def main() -> int:
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(wakeword.MODEL_DIR))
    clips = {os.path.basename(p).split("__")[0]: p for p in sorted(glob.glob(os.path.join(folder, "*.wav")))}
    voices = sorted({os.path.basename(p).split("__")[1] for p in glob.glob(os.path.join(folder, "*.wav"))})
    right = total = 0
    lag: list[float] = []
    for voice in voices:
        def clip(key):
            return os.path.join(folder, f"{key}__{voice}")
        for key, want in SAME_BREATH.items():
            if not os.path.exists(clip(key)):
                continue
            samples = pcm(clip(key))
            got, woke = run(model, samples)
            heard = got[0][1] if got else None
            ok = heard == want
            right += ok
            total += 1
            if got:
                lag.append(got[0][0] - len(samples) / 16000)
            print(f"{'ok  ' if ok else 'MISS'} one breath  {voice[:14]:<14} {key}: {heard!r}" + ("" if ok else f"   (wanted {want!r})"))
        name_only = clip("n00")
        for key, want in AFTER_A_PAUSE.items():
            if not (os.path.exists(clip(key)) and os.path.exists(name_only)):
                continue
            gap = array("h", [0]) * int(16000 * 1.6)
            joined = array("h")
            joined.extend(pcm(name_only))
            joined.extend(gap)
            joined.extend(pcm(clip(key)))
            got, woke = run(model, joined)
            heard = got[0][1] if got else None
            ok = heard == want
            right += ok
            total += 1
            print(f"{'ok  ' if ok else 'MISS'} with a pause {voice[:14]:<14} {key}: {heard!r}" + ("" if ok else f"   (wanted {want!r})"))
    print(f"\nunderstood {right} of {total}" + (f"; about {sum(lag) / len(lag):.1f} s after the end of the sentence (one breath)" if lag else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
