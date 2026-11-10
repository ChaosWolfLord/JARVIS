"""Run this a few minutes before showing JARVIS to people:   python tools\\demo_check.py     (or  tools\\demo_check.bat)

It checks the things that went wrong in the first demo and says, in plain words, what is fine and what to do about the rest:
the network the PC is on (lights and speakers have to be on it), how much of each AI model's free allowance is left and how fast it
answers right now, the lights, the speakers, the microphone's wake word and the phone door. It only reads and asks: it plays no music
and changes no light. It uses one small AI request.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OK, WARN, BAD = "  ok   ", " check ", " FIX   "
problems: list[str] = []


def say(mark: str, text: str) -> None:
    print(f"[{mark}] {text}", flush=True)
    if mark == BAD:
        problems.append(text)


def server_status() -> dict | None:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/status", timeout=4) as r:
            return json.loads(r.read().decode())
    except Exception:  # noqa: BLE001 - not running is an answer
        return None


def check_network() -> str:
    from server import lights as lights_mod, phone
    ip = phone.lan_ip()
    if ip.startswith("127."):
        say(BAD, "This PC has no network address. Connect to Wi-Fi.")
        return ""
    say(OK, f"The PC is on {ip}.")
    saved = [l.ip for l in lights_mod.lights.lights.values() if getattr(l, "ip", "")] if hasattr(lights_mod.lights, "lights") else []
    other = sorted({a for a in saved if a.rsplit(".", 1)[0] != ip.rsplit(".", 1)[0]})
    if other:
        say(WARN, f"Your lights were last seen at {', '.join(other)}, which is not on this network. Lights and speakers only work on their own Wi-Fi.")
    return ip


def check_ai() -> None:
    from server import agent, store
    ready = agent.usable()
    if not ready:
        say(BAD, "No AI key is set. Add GEMINI_API_KEY (and GROQ_API_KEY as a back-up) to .env.")
        return
    now = time.time()
    resting = [(t.key, agent._cooldown.get(t.key, 0) - now) for t in ready if agent._cooldown.get(t.key, 0) > now]
    for key, secs in resting:
        say(WARN, f"{key} is out of requests for now (back in about {int(secs // 3600)}h{int(secs % 3600 // 60):02d}m).")
    used = {}
    for provider in sorted({t.provider for t in ready}):
        used[provider] = store.provider_requests_today(provider)
    say(OK if not resting else WARN, "Requests used today: " + ", ".join(f"{p} {n}" for p, n in used.items()) + ". "
        "(Each question uses 1 to 3. Free daily limits are small: a demo can use them up.)")
    if len({t.provider for t in ready}) < 2:
        say(WARN, "Only one AI provider has a key. Add GROQ_API_KEY as well, so there is a fast back-up when the first runs out.")
    start = time.time()
    answer, model = "", None
    for event in agent.chat_turn("Reply with the single word: ready", [], None):
        if event.get("type") == "text":
            answer += event.get("delta", "")
        elif event.get("type") == "done":
            model = event.get("model")
        elif event.get("type") == "error":
            say(BAD, f"The AI could not answer: {event.get('message')}")
            return
    took = time.time() - start
    if not answer.strip():
        say(BAD, "The AI answered with nothing.")
    elif took > 12:
        say(BAD, f"The AI is slow right now: {took:.0f} s for one word, from {model}. Its faster models are probably out of requests for today.")
    elif took > 6:
        say(WARN, f"The AI took {took:.1f} s for one word ({model}). That is slow for a demo.")
    else:
        say(OK, f"The AI answers in {took:.1f} s ({model}).")


def check_lights() -> None:
    from server import lights as lights_mod
    reg = lights_mod.lights
    if not reg.available():
        say(WARN, "No lights are set up (fine, if you won't show them).")
        return
    try:
        found = reg.discover()
    except Exception as e:  # noqa: BLE001
        say(BAD, f"Could not look for lights: {e}")
        return
    if not found:
        say(BAD, "No lights found on this network. They must be on the same Wi-Fi as this PC, with LAN Control on in the Govee Home app.")
        return
    for light in found:
        try:
            up = reg.confirm_reachable(light)
        except Exception:  # noqa: BLE001
            up = False
        say(OK if up else BAD, f"{light.label} answers." if up else f"{light.label} does not answer: {reg.why_unreachable(light)}")


def check_music() -> None:
    from server import music
    if not music.available():
        say(WARN, "Music is not set up (fine, if you won't show it).")
        return
    try:
        devices = music.instance.devices()
    except Exception as e:  # noqa: BLE001
        say(BAD, f"Music can't look for speakers: {e}")
        return
    if not devices:
        say(BAD, "No speakers found. They must be on, and on the same Wi-Fi as this PC.")
        return
    for d in devices:
        try:
            music.instance.backend._cast(d["name"])
            say(OK, f"The speaker {d['name']} is connected.")
        except Exception as e:  # noqa: BLE001
            say(BAD, f"The speaker {d['name']} is not answering: {e}")


def check_server(status: dict | None) -> None:
    if status is None:
        say(BAD, "JARVIS is not running. Start it with JARVIS.bat.")
        return
    say(OK, "JARVIS is running.")
    wake = status.get("wake") or {}
    if wake.get("running"):
        say(OK, f"The wake word is listening on {wake.get('device') or 'the microphone'}.")
    elif os.getenv("JARVIS_WAKEWORD", "") in ("1", "true"):
        say(WARN, f"The wake word is not running ({wake.get('error') or 'unknown reason'}). You can still type or use the microphone button.")
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/api/phone", timeout=4) as r:
            phone = json.loads(r.read().decode())
        if phone.get("running"):
            say(OK, f"The phone door is open at {phone.get('url')}.")
        else:
            say(WARN, "The phone door is not running (the phone app won't connect).")
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    from server import store
    store.load_env()
    print("JARVIS demo check\n")
    status = server_status()
    check_server(status)
    check_network()
    check_ai()
    check_lights()
    check_music()
    print()
    if problems:
        print(f"{len(problems)} thing(s) to fix before the demo:")
        for p in problems:
            print("  -", p)
        return 1
    print("Ready for the demo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
