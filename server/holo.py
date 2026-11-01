"""The hologram card: 3D wireframes and animated charts the AI can put on the board ("show me a torus", "chart these numbers").

The AI only supplies data; the page draws it (web/holo.js). This checks what the AI sent so the page never gets something
huge or malformed: sizes are capped, every number must really be a number, and text is trimmed to plain short strings.
"""
from __future__ import annotations

import math

SHAPES = ("cube", "pyramid", "sphere", "torus", "icosahedron", "helix", "globe", "reactor", "custom")
CHARTS = ("bar", "line", "pie", "radar")
MAX_VERTICES, MAX_EDGES, MAX_POINTS = 300, 600, 24


class HoloError(ValueError):
    """What was wrong with the request, in words the AI can act on."""


def _text(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _number(value) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise HoloError(f"{value!r} isn't a number.") from None
    if not math.isfinite(n):
        raise HoloError("numbers must be finite.")
    return n


def model_event(args: dict) -> dict:
    shape = str(args.get("shape") or "").lower()
    if shape not in SHAPES:
        raise HoloError(f"shape must be one of: {', '.join(SHAPES)}.")
    event = {"type": "holo", "kind": "model", "shape": shape, "title": _text(args.get("title") or shape.capitalize(), 60)}
    if shape == "custom":
        raw_v, raw_e = args.get("vertices"), args.get("edges")
        if not isinstance(raw_v, list) or not isinstance(raw_e, list):
            raise HoloError("a custom shape needs flat lists: vertices [x,y,z, x,y,z, ...] and edges [a,b, a,b, ...].")
        nums = [_number(v) for v in raw_v]
        if len(nums) % 3 or not nums:
            raise HoloError("vertices must be groups of three numbers (x, y, z).")
        count = len(nums) // 3
        if count > MAX_VERTICES:
            raise HoloError(f"at most {MAX_VERTICES} vertices.")
        idx = [int(_number(v)) for v in raw_e]
        if len(idx) % 2 or not idx:
            raise HoloError("edges must be pairs of vertex numbers.")
        if len(idx) // 2 > MAX_EDGES:
            raise HoloError(f"at most {MAX_EDGES} edges.")
        if any(i < 0 or i >= count for i in idx):
            raise HoloError(f"edge numbers must be between 0 and {count - 1} (vertex numbers start at 0).")
        event["vertices"] = [max(-1000.0, min(1000.0, n)) for n in nums]
        event["edges"] = idx
    return event


def chart_event(args: dict) -> dict:
    kind = str(args.get("type") or "bar").lower()
    if kind not in CHARTS:
        raise HoloError(f"type must be one of: {', '.join(CHARTS)}.")
    labels, values = args.get("labels"), args.get("values")
    if not isinstance(labels, list) or not isinstance(values, list) or not values:
        raise HoloError("give labels and values as lists of the same length.")
    n = min(len(labels), len(values), MAX_POINTS)
    nums = [_number(v) for v in values[:n]]
    if kind == "pie" and any(v < 0 for v in nums):
        raise HoloError("a pie chart can't have negative values.")
    if kind == "radar" and n < 3:
        raise HoloError("a radar chart needs at least three points.")
    if n < 2 and kind in ("line",):
        raise HoloError("a line needs at least two points.")
    return {"type": "holo", "kind": "chart", "chart": kind, "title": _text(args.get("title") or "Chart", 60), "unit": _text(args.get("unit"), 12),
            "labels": [_text(l, 24) for l in labels[:n]], "values": nums}
