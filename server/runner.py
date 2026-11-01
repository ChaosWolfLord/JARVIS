"""Runs Python snippets JARVIS writes, but only after the user clicks Run in the UI.

This is an approval gate, not a sandbox: approved code runs as you, on this PC.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading

TIMEOUT_S = 20
MAX_OUTPUT = 4000
APPROVAL_WAIT_S = 120

_pending: dict[str, dict] = {}
_lock = threading.Lock()


def request(run_id: str) -> None:
    with _lock:
        _pending[run_id] = {"event": threading.Event(), "approved": False}


def decide(run_id: str, approve: bool) -> bool:
    with _lock:
        item = _pending.get(run_id)
    if not item:
        return False
    item["approved"] = approve
    item["event"].set()
    return True


def wait(run_id: str) -> bool:
    """Blocks until the user decides (or the wait times out). True means approved."""
    item = _pending[run_id]
    item["event"].wait(APPROVAL_WAIT_S)
    with _lock:
        _pending.pop(run_id, None)
    return item["approved"]


def _clean_env() -> dict[str, str]:
    """Child processes don't get API keys or other secrets from this process."""
    secret = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    return {k: v for k, v in os.environ.items() if not any(s in k.upper() for s in secret)}


def execute(code: str) -> dict:
    with tempfile.TemporaryDirectory(prefix="jarvis-run-") as tmp:
        path = os.path.join(tmp, "snippet.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        try:
            done = subprocess.run(
                [sys.executable, "-I", path],
                cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT_S, env=_clean_env(),
            )
            return {
                "stdout": done.stdout[:MAX_OUTPUT],
                "stderr": done.stderr[:MAX_OUTPUT],
                "return_code": done.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"stdout": "", "stderr": f"Stopped: ran longer than {TIMEOUT_S}s.", "return_code": -1}
