"""The avatar decoder, run in a child process (docs/api.md §6.10).

This is the most exposed parser of the hub: it reads bytes any agent credential can
send. It follows Pillow's own security guidance and the contract: only the decoder of
the sniffed type, the size read from the header and refused past `SIDE` before any
decoding, the first frame only, the decoded size checked again, PNG text chunks capped
and dropped. What leaves is a fresh RGBA image cropped to a centred square, at most
`OUT` pixels on a side, encoded as PNG with nothing but its pixels: the output image is
built from raw bytes, so no `info` of the input (EXIF, ICC profile, text) can follow it.

`avatars.decode` runs this module as its own process (`main`): the operator's memory
budget is that process's address-space limit and the time budget its deadline. It
imports nothing of the hub, so the process starts with Pillow and nothing else.
"""

from __future__ import annotations

import io
import resource
import sys
from typing import Any

SIDE = 4096  # at most this many pixels on either side, in the header and decoded
OUT = 256  # the stored image's side, never scaled up
TEXT_CHUNK, TEXT_TOTAL = 64 * 1024, 256 * 1024  # PNG text, after decompression
FORMATS = {"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}


class Refused(Exception):
    """The image is not accepted; `reason` is the `details.fields.body` the hub answers."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


TEXT_TYPES = (b"tEXt", b"zTXt", b"iTXt")


def _png_text_fits(data: bytes) -> bool:
    """No PNG text chunk over `TEXT_CHUNK` as stored. Pillow caps only what `zTXt` and
    `iTXt` decompress to, and `tEXt` only in the sum, so the walk over the chunk
    headers comes first."""
    position = 8
    while position + 8 <= len(data):
        length = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        if kind in TEXT_TYPES and length > TEXT_CHUNK:
            return False
        if kind == b"IEND":
            break
        position += 12 + length
    return True


def process(data: bytes, content_type: str) -> bytes:
    """The stored PNG for an uploaded image, or `Refused`."""
    from PIL import Image, PngImagePlugin

    # Pillow refuses a decompressed text chunk over the first, and all of them over
    # the second, with an error instead of keeping them.
    PngImagePlugin.MAX_TEXT_CHUNK = TEXT_CHUNK
    PngImagePlugin.MAX_TEXT_MEMORY = TEXT_TOTAL
    if content_type == "image/png" and not _png_text_fits(data):
        raise Refused("text_too_large")
    try:
        image: Any = Image.open(io.BytesIO(data), formats=[FORMATS[content_type]])
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise Refused("undecodable") from None
    width, height = image.size
    if not (0 < width <= SIDE and 0 < height <= SIDE):
        raise Refused("too_many_pixels")
    try:
        image.load()  # the first frame only: no seek, the others are never read
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        raise Refused("undecodable") from None
    if image.size != (width, height):
        raise Refused("size_mismatch")
    rgba = image.convert("RGBA")
    side = min(width, height)
    left, top = (width - side) // 2, (height - side) // 2
    square = rgba.crop((left, top, left + side, top + side))
    if side > OUT:
        square = square.resize((OUT, OUT), Image.Resampling.LANCZOS)
    clean = Image.frombytes("RGBA", square.size, square.tobytes())
    out = io.BytesIO()
    clean.save(out, format="PNG")
    return out.getvalue()


REFUSED = 3  # the exit code of a refusal; the reason is on stdout


def main() -> int:
    """`python -m maity_hub.avatar_decode <content type> <memory bytes>`: the image on
    stdin; the stored PNG on stdout and exit 0, or the reason and `REFUSED`. The
    memory budget is this process's address-space limit, set before anything is read;
    the time budget is the parent's deadline."""
    content_type, memory = sys.argv[1], int(sys.argv[2])
    try:
        from PIL import Image  # noqa: F401  loaded before the limit; decoding is after

        if memory > 0:
            resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
        data = sys.stdin.buffer.read()
        result = process(data, content_type)
    except Refused as refused:
        sys.stdout.write(refused.reason)
        return REFUSED
    except MemoryError:
        sys.stdout.write("over_budget")
        return REFUSED
    sys.stdout.buffer.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
