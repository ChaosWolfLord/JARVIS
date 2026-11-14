"""Draws assets/JARVIS.ico: the orb (a sphere of dots with a glowing ring) in the app's colours. Only the Python standard library is used.

    python tools/make_icon.py

The icon is committed, so this only needs running to change the picture."""
from __future__ import annotations

import math
import struct
import sys
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "assets" / "JARVIS.ico"
SIZES = (256, 128, 64, 48, 32, 24, 16)
BASE = 256
SS = 2                                         # 2 x 2 samples per pixel
CYAN = (77, 225, 255)
DEEP = (4, 12, 18)


def sphere_points(n: int, tilt: float = 0.5, turn: float = 0.6) -> list[tuple[float, float, float]]:
    """About n points spread evenly over a sphere, turned a little so it looks alive, front side only."""
    pts = []
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - 2 * (i + 0.5) / n
        r = math.sqrt(1 - y * y)
        a = i * golden + turn
        x, z = math.cos(a) * r, math.sin(a) * r
        y2, z2 = y * math.cos(tilt) - z * math.sin(tilt), y * math.sin(tilt) + z * math.cos(tilt)
        if z2 > -0.05:
            pts.append((x, y2, z2))
    return pts


def render() -> list[list[tuple[int, int, int, int]]]:
    dots = sphere_points(210)
    big = BASE * SS
    c = big / 2
    rim = 0.47 * big                           # the disc
    sphere = 0.36 * big                        # the sphere of dots
    rows = []
    for py in range(big):
        row = []
        for px in range(big):
            x, y = px + 0.5 - c, py + 0.5 - c
            d = math.hypot(x, y)
            r = g = b = 0.0
            a = 0.0
            if d <= rim:
                t = d / rim                    # a dark disc, a little lighter in the middle
                base = 1 - t * t
                r, g, b = (DEEP[0] + 10 * base), (DEEP[1] + 26 * base), (DEEP[2] + 34 * base)
                a = 1.0
                ring = abs(d - rim * 0.965)    # the ring, brightest at its centre
                if ring < 0.022 * big:
                    k = 1 - ring / (0.022 * big)
                    r, g, b = r + (CYAN[0] - r) * k, g + (CYAN[1] - g) * k, b + (CYAN[2] - b) * k
                glow = max(0.0, 1 - abs(d - rim * 0.965) / (0.07 * big)) * 0.25
                r, g, b = r + CYAN[0] * glow, g + CYAN[1] * glow, b + CYAN[2] * glow
                if d < sphere * 1.05:           # the dots: each a small disc, brighter and larger when it faces you
                    for (dx, dy, dz) in dots:
                        ex, ey = x - dx * sphere, y - dy * sphere
                        rad = (0.014 + 0.016 * max(dz, 0)) * big
                        if ex * ex + ey * ey <= rad * rad:
                            k = 0.35 + 0.65 * max(dz, 0)
                            r, g, b = r + (CYAN[0] - r) * k, g + (CYAN[1] - g) * k, b + (CYAN[2] - b) * k
                            break
            row.append((r, g, b, a))
        rows.append(row)
    return rows


def downsample(rows, size: int) -> list[bytes]:
    """The picture at `size` pixels: boxes of samples averaged (colour weighted by how much of the box is covered)."""
    big = len(rows)
    f = big // size if big % size == 0 else big / size
    out = []
    for oy in range(size):
        line = bytearray()
        y0, y1 = int(oy * big / size), max(int((oy + 1) * big / size), int(oy * big / size) + 1)
        for ox in range(size):
            x0, x1 = int(ox * big / size), max(int((ox + 1) * big / size), int(ox * big / size) + 1)
            r = g = b = a = 0.0
            n = 0
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    pr, pg, pb, pa = rows[yy][xx]
                    r, g, b, a, n = r + pr * pa, g + pg * pa, b + pb * pa, a + pa, n + 1
            if a > 0:
                line += bytes((min(255, round(r / a)), min(255, round(g / a)), min(255, round(b / a)), min(255, round(255 * a / n))))
            else:
                line += b"\x00\x00\x00\x00"
        out.append(bytes(line))
    return out


def png(lines: list[bytes], size: int) -> bytes:
    raw = b"".join(b"\x00" + line for line in lines)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def ico(images: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    entries, data, offset = b"", b"", 6 + 16 * len(images)
    for size, blob in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(blob), offset)
        data += blob
        offset += len(blob)
    return head + entries + data


def main() -> int:
    rows = render()
    images = [(s, png(downsample(rows, s), s)) for s in SIZES]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(ico(images))
    print(f"Wrote {OUT} ({OUT.stat().st_size // 1024} KB, sizes {', '.join(str(s) for s in SIZES)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
