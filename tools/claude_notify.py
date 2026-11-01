"""Claude Code hook: tells JARVIS when Claude finishes, fails, or needs you.

Claude Code runs this for several events and passes details as JSON on standard input. It uses only the standard library, always exits
quietly (it must never slow down or break Claude Code), and does nothing if JARVIS isn't running.

  UserPromptSubmit  notes when a prompt started
  Stop              Claude finished: tells JARVIS if the prompt took at least `min_seconds` (default 20), so quick answers stay silent
  Notification      Claude needs permission, or has been waiting for you
  StopFailure       the prompt ended with an error
  SessionEnd        forgets the session

Settings (all optional) in %LOCALAPPDATA%\\jarvis\\claude_notify.json:
  {"enabled": true, "min_seconds": 20, "port": 8000, "events": ["finished", "permission", "idle", "failed"]}
JARVIS says the message itself (and wraps it in its current mood); this script only names the kind of event and the project folder.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

STATE = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "jarvis"
CONFIG_FILE = STATE / "claude_notify.json"
PROMPTS_FILE = STATE / "claude_prompts.json"
TOKEN_FILE = STATE / "notify.token"
DEFAULTS = {"enabled": True, "min_seconds": 20, "port": 8000, "events": ["finished", "permission", "idle", "failed"]}
KEEP_SECONDS = 24 * 3600


def read_json(path, default):
    try:
        data = json.loads(Path(path).read_text("utf-8-sig"))
        return data if isinstance(data, type(default)) else default
    except (OSError, ValueError):
        return default


def load_config(path=CONFIG_FILE) -> dict:
    config = dict(DEFAULTS)
    config.update({k: v for k, v in read_json(path, {}).items() if k in DEFAULTS})
    return config


def project_name(cwd) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w .\-]", "", Path(str(cwd or "")).name)).strip()[:40]


def decide(payload: dict, now: float, config: dict, prompts: dict) -> str | None:
    """Which kind of message to send for this hook call (or None). Updates `prompts` (when each session's prompt began)."""
    event = payload.get("hook_event_name", "")
    session = str(payload.get("session_id") or "")
    for key in [k for k, t in prompts.items() if now - float(t) > KEEP_SECONDS]:
        prompts.pop(key, None)
    if event == "UserPromptSubmit":
        prompts[session] = now
        return None
    if event == "SessionEnd":
        prompts.pop(session, None)
        return None
    if event == "Stop":
        started = prompts.pop(session, None)
        if payload.get("stop_hook_active"):
            return None
        if started is not None and now - float(started) < float(config["min_seconds"]):
            return None                                    # a quick answer: you're probably still looking at it
        return "finished"
    if event == "StopFailure":
        return "failed"
    if event == "Notification":
        text = f"{payload.get('notification_type', '')} {payload.get('message', '')}".lower()
        if "permission" in text:
            return "permission"
        if "idle" in text or "waiting" in text:
            return "idle"
    return None


def post(kind: str, project: str, config: dict, token: str) -> bool:
    body = json.dumps({"kind": kind, "project": project}).encode()
    request = urllib.request.Request(f"http://127.0.0.1:{int(config['port'])}/api/notify", data=body, method="POST",
                                     headers={"Content-Type": "application/json", "X-Jarvis-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=2.0) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def main(stdin_text: str | None = None, now: float | None = None, config_path=CONFIG_FILE, prompts_path=PROMPTS_FILE, token_path=TOKEN_FILE, sender=post) -> int:
    try:
        payload = json.loads(stdin_text if stdin_text is not None else sys.stdin.read())
        if not isinstance(payload, dict):
            return 0
        config = load_config(config_path)
        if not config["enabled"]:
            return 0
        prompts = read_json(prompts_path, {})
        kind = decide(payload, time.time() if now is None else now, config, prompts)
        try:
            Path(prompts_path).parent.mkdir(parents=True, exist_ok=True)
            Path(prompts_path).write_text(json.dumps(prompts), "utf-8")
        except OSError:
            pass
        if kind and kind in config["events"]:
            token = Path(token_path).read_text("utf-8").strip() if Path(token_path).exists() else ""
            if token:                                        # no token yet means JARVIS has never run on this PC: nothing to tell
                sender(kind, project_name(payload.get("cwd")), config, token)
    except Exception:  # noqa: BLE001 - a hook must never break Claude Code
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
