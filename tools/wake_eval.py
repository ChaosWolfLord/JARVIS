"""Measures the offline wake word on synthetic speech, so a change to it can be judged by numbers instead of by ear.

    1. make speech clips (Windows voices say 4 sentences with the name and 12 without):  powershell tools\\make_test_speech.ps1 <folder>
    2. python tools\\wake_eval.py <folder>

For each sensitivity (high / normal / low) it prints how many of the clips with the name woke it, and how often it wakes per hour of
ordinary talk that does not contain the name (one person at a time, and two people at once). Synthetic voices are kinder than a noisy room,
so use the numbers to compare settings, not as a promise.
"""
from __future__ import annotations

import glob
import json
import os
import random
import sys
import wave
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import vosk  # noqa: E402

from server import wakeword  # noqa: E402

BLOCK = 4000                                   # samples per update: a quarter of a second, as in the live listener


def pcm(path: str) -> array:
    with wave.open(path, "rb") as w:
        a = array("h")
        a.frombytes(w.readframes(w.getnframes()))
        return a


def blocks(samples: array, gain: float = 1.0):
    data = array("h", [max(-32768, min(32767, int(s * gain))) for s in samples]) if gain != 1.0 else samples
    raw = data.tobytes() + b"\x00\x00" * 16000            # a second of silence so the last words are finalised
    return [raw[i:i + BLOCK * 2] for i in range(0, len(raw), BLOCK * 2)]


def wakes(model, samples_bytes: list[bytes], level: str) -> int:
    os.environ["JARVIS_WAKEWORD_SENSITIVITY"] = level
    rec = vosk.KaldiRecognizer(model, 16000, wakeword.grammar())
    rec.SetWords(True)
    detector, count, now = wakeword.Detector(), 0, 0.0
    for block in samples_bytes:
        final = rec.AcceptWaveform(block)
        if final:
            result = json.loads(rec.Result())
            text = result.get("text", "")
            conf = max((w.get("conf", 0.0) for w in result.get("result", []) if w.get("word") in wakeword.NAME_WORDS), default=0.0)
        else:
            text, conf = json.loads(rec.PartialResult()).get("partial", ""), 0.0
        now += 0.25
        if detector.hears(text, now, final=final, conf=conf):
            count += 1
    return count


def talk(clips: list[array], rng: random.Random, overlap: bool) -> bytes:
    out = array("h")
    for _ in range(40):
        p = rng.choice(clips)
        if overlap:                                      # two people at once
            q = rng.choice(clips)
            mixed = array("h", [0]) * max(len(p), len(q))
            for i, s in enumerate(p):
                mixed[i] += s // 2
            for i, s in enumerate(q):
                mixed[i] += s // 2
            p = mixed
        out.extend(p)
        out.extend(array("h", [0]) * rng.randrange(2000, 12000))
    out.extend(array("h", [0]) * 16000)
    return out.tobytes()


def main() -> int:
    folder = sys.argv[1] if len(sys.argv) > 1 else "."
    paths = sorted(glob.glob(os.path.join(folder, "*.wav")))
    if not paths:
        print("no .wav files there: make them with tools\\make_test_speech.ps1")
        return 1
    vosk.SetLogLevel(-1)
    model = vosk.Model(str(wakeword.MODEL_DIR))
    named = [p for p in paths if os.path.basename(p).startswith("real")]
    others = [pcm(p) for p in paths if os.path.basename(p).startswith("not")]
    for level in ("high", "normal", "low"):
        heard = total = 0
        for gain in (0.4, 1.0, 2.0):
            for p in named:
                total += 1
                heard += 1 if wakes(model, blocks(pcm(p), gain), level) else 0
        false = minutes = 0.0
        for seed in range(6):
            for overlap in (False, True):
                data = talk(others, random.Random(100 + seed), overlap)
                chunks = [data[i:i + BLOCK * 2] for i in range(0, len(data), BLOCK * 2)]
                false += wakes(model, chunks, level)
                minutes += len(data) / 32000 / 60
        print(f"sensitivity {level:<6}: woke on {heard}/{total} clips with the name; {false / minutes * 60:.1f} false wake-ups per hour of talk without it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
