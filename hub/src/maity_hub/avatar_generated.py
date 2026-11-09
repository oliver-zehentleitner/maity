"""An agent's generated picture (docs/api.md §6.10, "An agent's generated picture").

The dashboard's generated avatar (`web/js/avatar.js`), drawn by the hub: the pattern and the
hue from FNV-1a over the profile id, the pattern in a 7 × 7 frame with a margin of one cell,
256 pixels square, the cells at 60 % saturation and 50 % lightness on a transparent
background. Plain Python and zlib, no image library: the upgrade that draws it for every
existing profile imports this module, and the same id gives the same bytes on every hub.
"""

from __future__ import annotations

import colorsys
import struct
import zlib

SIDE = 256
GRID = 7  # the frame: 5 × 5 cells and a margin of one cell around them


def fnv(text: str) -> int:
    """FNV-1a, 32 bits, over the code points (as `avatar.js` does)."""
    x = 0x811C9DC5
    for ch in text:
        x ^= ord(ch)
        x = (x * 0x01000193) & 0xFFFFFFFF
    return x


def cells(member_id: str) -> set[tuple[int, int]]:
    """The cells that are on, as (column, row) in 0–4: bit `row × 3 + column` for columns
    0–2, mirrored onto 3–4; the middle cell when no bit is set."""
    bits = fnv(member_id)
    on: set[tuple[int, int]] = set()
    for row in range(5):
        for col in range(3):
            if (bits >> (row * 3 + col)) & 1:
                on.add((col, row))
                on.add((4 - col, row))
    return on or {(2, 2)}


def hue(member_id: str) -> int:
    return fnv(member_id + "#hue") % 360


def _cell(pixel: int) -> int:
    """The cell (0–4, or outside) whose square holds the pixel's centre."""
    return ((2 * pixel + 1) * GRID) // (2 * SIDE) - 1


def draw(member_id: str) -> bytes:
    """The picture as a PNG (RGBA, 8 bits)."""
    red, green, blue = (round(c * 255) for c in colorsys.hls_to_rgb(hue(member_id) / 360, 0.5, 0.6))
    on = cells(member_id)
    ink = bytes((red, green, blue, 255))
    clear = bytes(4)
    columns = [_cell(x) for x in range(SIDE)]
    raw = bytearray()
    for y in range(SIDE):
        row = _cell(y)
        raw.append(0)  # filter: none
        raw += b"".join(ink if (col, row) in on else clear for col in columns)
    return _png(SIDE, SIDE, bytes(raw))


def _chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def _png(width: int, height: int, raw: bytes) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8 bits, RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )
