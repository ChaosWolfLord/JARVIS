"""OpenRouter's free models that can call tools, found from its public model list.

The list changes every few weeks, so instead of a fixed chain JARVIS asks OpenRouter which models cost
nothing and support tool calls, and remembers the answer for half a day.
"""
from __future__ import annotations

import logging
import os
import re
import time

try:
    import httpx
except ImportError:  # newer OpenAI SDKs install the same library under the name httpx2
    import httpx2 as httpx

from . import store

log = logging.getLogger("jarvis")

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_FILE = store.STATE / "openrouter_models.json"
CACHE_SECONDS = 12 * 3600
# Used when the list can't be fetched and nothing is cached. "openrouter/free" is OpenRouter's own router.
FALLBACK = [{"id": "google/gemma-4-31b-it:free", "vision": True}, {"id": "openrouter/free", "vision": True}]
# Models that can't be the assistant: safety classifiers, media generators, tiny models.
UNSUITABLE = re.compile(r"safety|guard|embed|lyria|whisper|tts|image-gen|\b[0-3](?:\.\d)?b\b", re.I)


def pick_free(models: list[dict], first: list[str] | None = None) -> list[dict]:
    """[{id, vision}] best first, from OpenRouter's /models data.

    Free (both prices zero), text out, tool calls supported. Models that can see images go first so the
    board snapshot works, then larger context windows; OpenRouter's own router is last.
    """
    picked = []
    for m in models:
        pricing = m.get("pricing") or {}
        arch = m.get("architecture") or {}
        if str(pricing.get("prompt")) != "0" or str(pricing.get("completion")) != "0":
            continue
        if "tools" not in (m.get("supported_parameters") or []):
            continue
        if "text" not in (arch.get("output_modalities") or ["text"]):
            continue
        if UNSUITABLE.search(m["id"]):
            continue
        picked.append({"id": m["id"], "vision": "image" in (arch.get("input_modalities") or []),
                       "ctx": m.get("context_length") or 0})
    wanted = {name: i for i, name in enumerate(first or [])}
    picked.sort(key=lambda m: (m["id"] not in wanted, wanted.get(m["id"], 0), m["id"] == "openrouter/free",
                               not m["vision"], -m["ctx"]))
    return [{"id": m["id"], "vision": m["vision"]} for m in picked]


def free_models(force: bool = False) -> list[dict]:
    """The current list, from the cache if it is fresh, else from OpenRouter, else a short built-in one."""
    cached = store._read(CACHE_FILE, {})
    fresh = time.time() - cached.get("fetched", 0) < CACHE_SECONDS
    if cached.get("models") and fresh and not force:
        return cached["models"]
    first = [s.strip() for s in os.getenv("JARVIS_OPENROUTER_FIRST", "").split(",") if s.strip()]
    try:
        resp = httpx.get(MODELS_URL, timeout=8.0)
        resp.raise_for_status()
        models = pick_free(resp.json().get("data", []), first)
        if models:
            try:
                store._write(CACHE_FILE, {"fetched": time.time(), "models": models})
            except OSError as e:
                log.warning("couldn't cache the OpenRouter model list: %s", e)
            return models
    except (httpx.HTTPError, ValueError) as e:
        log.warning("couldn't fetch OpenRouter's model list: %s", e)
    return cached.get("models") or FALLBACK
