"""The hologram card: 3D wireframes and animated charts the AI can put on the board ("show me a torus", "chart these numbers").

The AI only supplies data; the page draws it (web/holo.js). This checks what the AI sent so the page never gets something
huge or malformed: sizes are capped, every number must really be a number, and text is trimmed to plain short strings.

Models can be a ready-made shape, a raw list of vertices and edges, or an assembly of simple parts (boxes, spheres, cylinders, cones,
pyramids with a position, size and turn). Free models are poor at typing out the coordinates of a cat, but they are good at saying
"a body, a head, two ears, four legs and a tail"; the assembly is built into one wireframe here, so a cat looks like a cat.
"""
from __future__ import annotations

import math

SHAPES = ("cube", "pyramid", "sphere", "torus", "icosahedron", "helix", "globe", "reactor", "custom")
CHARTS = ("bar", "line", "pie", "radar")
MAX_VERTICES, MAX_EDGES, MAX_POINTS = 300, 600, 24
PARTS = ("box", "sphere", "cylinder", "cone", "pyramid")
MAX_PARTS = 24
ASSEMBLY_VERTICES, ASSEMBLY_EDGES = 700, 1400          # an assembly is built here from small parts, so it may be a little bigger than a hand-typed model


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


def _ring(n: int, y: float, rx: float, rz: float, start: int) -> tuple[list, list]:
    verts = [(rx * math.cos(2 * math.pi * i / n), y, rz * math.sin(2 * math.pi * i / n)) for i in range(n)]
    return verts, [(start + i, start + (i + 1) % n) for i in range(n)]


def _primitive(kind: str) -> tuple[list, list]:
    """One part at unit size, centred on the origin: x across, y up, z toward the viewer. A cone and a pyramid point up (+y)."""
    if kind == "box":
        v = [(x, y, z) for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]
        e = [(a, b) for a in range(8) for b in range(a + 1, 8) if bin(a ^ b).count("1") == 1]
        return v, e
    if kind == "pyramid":
        v = [(-.5, -.5, -.5), (.5, -.5, -.5), (.5, -.5, .5), (-.5, -.5, .5), (0, .5, 0)]
        return v, [(0, 1), (1, 2), (2, 3), (3, 0), (0, 4), (1, 4), (2, 4), (3, 4)]
    n = 8
    if kind == "cylinder":
        top, top_e = _ring(n, .5, .5, .5, 0)
        bottom, bottom_e = _ring(n, -.5, .5, .5, n)
        return top + bottom, top_e + bottom_e + [(i, n + i) for i in range(n)]
    if kind == "cone":
        base, base_e = _ring(n, -.5, .5, .5, 0)
        return base + [(0, .5, 0)], base_e + [(i, n) for i in range(n)]
    # sphere: three rings of latitude and a pole at each end
    v, e = [(0, .5, 0)], []
    rings = (45, 0, -45)
    for k, lat in enumerate(rings):
        r, y = .5 * math.cos(math.radians(lat)), .5 * math.sin(math.radians(lat))
        ring, ring_e = _ring(n, y, r, r, len(v))
        v += ring
        e += ring_e
    v.append((0, -.5, 0))
    south = len(v) - 1
    for i in range(n):
        e += [(0, 1 + i), (1 + i, 1 + n + i), (1 + n + i, 1 + 2 * n + i), (1 + 2 * n + i, south)]
    return v, e


def _turn(p: tuple, rx: float, ry: float, rz: float) -> tuple:
    x, y, z = p
    c, s = math.cos(rx), math.sin(rx)
    y, z = y * c - z * s, y * s + z * c
    c, s = math.cos(ry), math.sin(ry)
    x, z = x * c + z * s, -x * s + z * c
    c, s = math.cos(rz), math.sin(rz)
    x, y = x * c - y * s, x * s + y * c
    return x, y, z


def _size(part: dict, key: str, fallback: float) -> float:
    raw = part.get(key)
    return fallback if raw is None else max(0.02, min(20.0, _number(raw)))


def assembly(parts) -> tuple[list[float], list[int]]:
    """Builds one wireframe from simple parts: [{type, x, y, z, w, h, d, rx, ry, rz}] (centre, full width/height/depth, turn in degrees)."""
    if not isinstance(parts, list) or not parts:
        raise HoloError(f"give parts: a list of {{type, x, y, z, w, h, d}} where type is one of {', '.join(PARTS)} (x across, y up, z toward the viewer).")
    verts: list[float] = []
    edges: list[int] = []
    for part in parts[:MAX_PARTS]:
        if not isinstance(part, dict):
            raise HoloError("each part must be an object like {\"type\": \"sphere\", \"x\": 0, \"y\": 0, \"z\": 0, \"w\": 1, \"h\": 1, \"d\": 1}.")
        kind = str(part.get("type") or part.get("shape") or "").lower()
        if kind not in PARTS:
            raise HoloError(f"a part's type must be one of: {', '.join(PARTS)}.")
        size = part.get("size")
        w, h, d = (_size(part, "w", _number(size) if size is not None else 1.0), _size(part, "h", _number(size) if size is not None else 1.0),
                   _size(part, "d", _number(size) if size is not None else 1.0))
        cx, cy, cz = (max(-50.0, min(50.0, _number(part.get(k, 0)))) for k in ("x", "y", "z"))
        rx, ry, rz = (math.radians(_number(part.get(k, 0))) for k in ("rx", "ry", "rz"))
        base = len(verts) // 3
        pv, pe = _primitive(kind)
        for (x, y, z) in pv:
            tx, ty, tz = _turn((x * w, y * h, z * d), rx, ry, rz)
            verts += [tx + cx, ty + cy, tz + cz]
        for a, b in pe:
            edges += [base + a, base + b]
    if len(verts) // 3 > ASSEMBLY_VERTICES or len(edges) // 2 > ASSEMBLY_EDGES:
        raise HoloError(f"too detailed: use fewer parts (at most {MAX_PARTS}, and boxes and cones are the lightest).")
    return verts, edges


def _flat(values):
    """A list of numbers; models often send [[x,y,z], ...] or [[a,b], ...] instead of one flat list, which is just as clear."""
    if isinstance(values, list) and values and all(isinstance(v, (list, tuple)) for v in values):
        return [n for v in values for n in v]
    return values


def model_event(args: dict) -> dict:
    shape = str(args.get("shape") or "").lower()
    parts = args.get("parts")
    if shape == "assembly" or (shape not in SHAPES and isinstance(parts, list) and parts):
        verts, edges = assembly(parts)
        return {"type": "holo", "kind": "model", "shape": "custom", "title": _text(args.get("title") or "Model", 60), "vertices": verts, "edges": edges}
    if shape not in SHAPES:
        raise HoloError(f"shape must be one of: {', '.join(SHAPES)}, or assembly (then give parts: boxes, spheres, cylinders, cones, pyramids). "
                        "For a cat, a car, a house or anything else use assembly.")
    event = {"type": "holo", "kind": "model", "shape": shape, "title": _text(args.get("title") or shape.capitalize(), 60)}
    if shape == "custom":
        raw_v, raw_e = _flat(args.get("vertices")), _flat(args.get("edges"))
        if not isinstance(raw_v, list) or not isinstance(raw_e, list):
            raise HoloError("a custom shape needs flat lists: vertices [x,y,z, x,y,z, ...] and edges [a,b, a,b, ...].")
        nums = [_number(v) for v in raw_v]
        nums = nums[:len(nums) // 3 * 3]                      # a stray number at the end is dropped
        if not nums:
            raise HoloError("vertices must be groups of three numbers (x, y, z).")
        count = len(nums) // 3
        if count > MAX_VERTICES:
            raise HoloError(f"at most {MAX_VERTICES} vertices. For something bigger use shape assembly with parts.")
        idx = [int(_number(v)) for v in raw_e]
        pairs = [(idx[i], idx[i + 1]) for i in range(0, len(idx) - 1, 2)]
        pairs = [(a, b) for a, b in pairs if 0 <= a < count and 0 <= b < count]      # an edge to a vertex that doesn't exist is skipped, not fatal
        if not pairs:
            raise HoloError(f"edges must be pairs of vertex numbers between 0 and {count - 1} (vertex numbers start at 0).")
        if len(pairs) > MAX_EDGES:
            raise HoloError(f"at most {MAX_EDGES} edges.")
        idx = [n for pair in pairs for n in pair]
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
