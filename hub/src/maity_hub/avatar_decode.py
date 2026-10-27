"""The avatar decoder, run in a child process (docs/api.md §6.10).

This is the most exposed parser of the hub: it reads bytes any agent credential can
send. Before Pillow sees the bytes, the image's width and height are read from its own
header here (`dimensions`: PNG's IHDR, JPEG's first SOF, WebP's VP8/VP8L/VP8X) and
anything past `SIDE` on a side is refused; Pillow's own size check comes after
`Image.open`, too late for a format that allocates its canvas while opening (APNG).
Then only the decoder of the sniffed type, the first frame only, the decoded size
checked against the header, PNG text chunks capped and dropped. What leaves is a fresh
RGBA image cropped to a centred square, at most `OUT` pixels on a side, encoded as PNG
with nothing but its pixels: the output is built from raw bytes, so no `info` of the
input (EXIF, ICC profile, text) can follow it. A JPEG's EXIF orientation is applied
first, so a photo is stored as it is seen.

`draft()` and `thumbnail()` are not used: in Pillow before 13.0 they reached a JPEG heap
overflow (GHSA-8g5g-8vmr-9782), and the decoder keeps to the plain path.

An attachment's image (docs/api.md §8.7) takes the same path with `attachment` as the
fourth argument: the same checks and budgets, a larger limit (`FILE_SIDE` on a side and
`FILE_PIXELS` in all, taken from the header before decoding), GIF as a fourth format, and
an output that keeps the image's size: EXIF orientation applied, the colour profile
converted to sRGB, then PNG for PNG and GIF, JPEG (quality 90) for JPEG, WebP (lossless
when the source was) for WebP, built from raw pixels so nothing else of the input survives.

`avatars.decode` runs this file as its own process (`main`), by path, under `python -I`
and an empty environment: the operator's memory budget is that process's address-space
limit, it may write no file, and the time budget is its CPU limit and the parent's
deadline. It imports nothing of the hub, so the process holds Pillow and nothing else.
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
FILE_SIDE = 8192  # an attachment's image: this many pixels on a side ...
FILE_PIXELS = 40_000_000  # ... and in all, in the header and decoded
FILE_FORMATS = {**FORMATS, "image/gif": "GIF"}
FILE_JPEG_QUALITY = 90
REFUSED = 3  # the exit code of a refusal; the reason is on stdout


class Refused(Exception):
    """The image is not accepted: `reason` is one of §6.10's `details.fields.body`
    values the decoder can tell (`dimensions`, `undecodable`); `detail` is for the log."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail or reason


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


_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg_size(data: bytes) -> tuple[int, int]:
    position = 2
    while position + 4 <= len(data):
        if data[position] != 0xFF:
            raise Refused("undecodable", "jpeg: no marker where one belongs")
        marker = data[position + 1]
        if marker == 0xFF:  # fill byte
            position += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD8)):  # no length
            position += 2
            continue
        if marker in (0xD9, 0xDA):  # end, or the scan before any frame header
            break
        length = int.from_bytes(data[position + 2 : position + 4], "big")
        if marker in _SOF and position + 9 <= len(data):
            height = int.from_bytes(data[position + 5 : position + 7], "big")
            width = int.from_bytes(data[position + 7 : position + 9], "big")
            return width, height
        position += 2 + length
    raise Refused("undecodable", "jpeg: no frame header")


def _webp_size(data: bytes) -> tuple[int, int]:
    kind = data[12:16]
    if kind == b"VP8X" and len(data) >= 30:
        return int.from_bytes(data[24:27], "little") + 1, int.from_bytes(data[27:30], "little") + 1
    if kind == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
        width = int.from_bytes(data[26:28], "little") & 0x3FFF
        height = int.from_bytes(data[28:30], "little") & 0x3FFF
        return width, height
    raise Refused("undecodable", "webp: no frame header")


def _gif_size(data: bytes) -> tuple[int, int]:
    if len(data) < 10 or data[:6] not in (b"GIF87a", b"GIF89a"):
        raise Refused("undecodable", "gif: no header")
    return int.from_bytes(data[6:8], "little"), int.from_bytes(data[8:10], "little")


def dimensions(data: bytes, content_type: str) -> tuple[int, int]:
    """Width and height as the file's own header states them, read without Pillow."""
    if content_type == "image/gif":
        return _gif_size(data)
    if content_type == "image/png":
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise Refused("undecodable", "png: no IHDR first")
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if content_type == "image/jpeg":
        return _jpeg_size(data)
    if content_type == "image/webp":
        return _webp_size(data)
    raise Refused("undecodable", f"no decoder for {content_type}")


def _rgba(image: Any) -> Any:
    """RGBA of a decoded image; 16-bit grey is scaled, not clipped to white."""
    if image.mode in ("I;16", "I;16B", "I;16L", "I;16N", "I"):
        image = image.convert("I").point(lambda value: value * (1 / 256)).convert("L")
    return image.convert("RGBA")


def process(data: bytes, content_type: str) -> bytes:
    """The stored PNG for an uploaded image, or `Refused`."""
    width, height = dimensions(data, content_type)
    if not (0 < width <= SIDE and 0 < height <= SIDE):
        raise Refused("dimensions", f"header says {width}x{height}")
    if content_type == "image/png" and not _png_text_fits(data):
        raise Refused("undecodable", "png: a text chunk over its cap")

    from PIL import Image, ImageOps, PngImagePlugin

    # Pillow refuses a decompressed text chunk over the first, and all of them over the
    # second, with an error instead of keeping them; and any image past SIDE × SIDE.
    PngImagePlugin.MAX_TEXT_CHUNK = TEXT_CHUNK
    PngImagePlugin.MAX_TEXT_MEMORY = TEXT_TOTAL
    Image.MAX_IMAGE_PIXELS = SIDE * SIDE
    image: Any = Image.open(io.BytesIO(data), formats=[FORMATS[content_type]])
    if image.size != (width, height):
        raise Refused("dimensions", f"header {width}x{height}, Pillow {image.size}")
    image.load()  # the first frame only: no seek, the others are never read
    if image.size != (width, height):
        raise Refused("dimensions", f"decoded {image.size}, header {width}x{height}")
    if content_type == "image/jpeg":
        image = ImageOps.exif_transpose(image)
    rgba = _rgba(image)
    side = min(rgba.size)
    left, top = (rgba.size[0] - side) // 2, (rgba.size[1] - side) // 2
    square = rgba.crop((left, top, left + side, top + side))
    if side > OUT:
        square = square.resize((OUT, OUT), Image.Resampling.LANCZOS)
    clean = Image.frombytes("RGBA", square.size, square.tobytes())
    out = io.BytesIO()
    clean.save(out, format="PNG")
    return out.getvalue()


def webp_lossless(data: bytes) -> bool:
    """Whether a WebP's (first) image is lossless: a `VP8L` chunk, at the top or in the
    first animation frame."""
    kind = data[12:16]
    if kind == b"VP8L":
        return True
    if kind != b"VP8X":
        return False
    position = 12
    end = len(data)
    while position + 8 <= end:
        fourcc = data[position : position + 4]
        size = int.from_bytes(data[position + 4 : position + 8], "little")
        if fourcc == b"VP8L":
            return True
        if fourcc == b"ANMF":  # a 16-byte frame header, then the frame's own chunks
            position += 8 + 16
            continue
        if fourcc == b"VP8 ":
            return False
        position += 8 + size + (size & 1)
    return False


def _to_srgb(image: Any, profile: bytes | None) -> Any:
    """The image in sRGB when it carries a colour profile of an RGB space; any other
    profile is dropped with the rest of the metadata."""
    if not profile or image.mode not in ("RGB", "RGBA"):
        return image
    from PIL import ImageCms

    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        if source.profile.xcolor_space.strip() != "RGB":
            return image
        target = ImageCms.createProfile("sRGB")
        converted = ImageCms.profileToProfile(
            image.convert("RGB"), source, target, outputMode="RGB"
        )
    except ImageCms.PyCMSError as error:
        raise Refused("undecodable", f"colour profile: {error}") from None
    if converted is None:
        raise Refused("undecodable", "colour profile: no conversion")
    if image.mode == "RGBA":
        converted.putalpha(image.getchannel("A"))
    return converted


def process_file(data: bytes, content_type: str) -> bytes:
    """The stored bytes for an attachment's image, or `Refused`. The image keeps its size;
    PNG and GIF come out as PNG, JPEG as JPEG, WebP as WebP."""
    width, height = dimensions(data, content_type)
    if not (0 < width <= FILE_SIDE and 0 < height <= FILE_SIDE and width * height <= FILE_PIXELS):
        raise Refused("dimensions", f"header says {width}x{height}")
    if content_type == "image/png" and not _png_text_fits(data):
        raise Refused("undecodable", "png: a text chunk over its cap")
    lossless = content_type == "image/webp" and webp_lossless(data)

    from PIL import Image, ImageOps, PngImagePlugin

    PngImagePlugin.MAX_TEXT_CHUNK = TEXT_CHUNK
    PngImagePlugin.MAX_TEXT_MEMORY = TEXT_TOTAL
    Image.MAX_IMAGE_PIXELS = FILE_PIXELS
    image: Any = Image.open(io.BytesIO(data), formats=[FILE_FORMATS[content_type]])
    if image.size != (width, height):
        raise Refused("dimensions", f"header {width}x{height}, Pillow {image.size}")
    image.load()  # the first frame only: no seek, the others are never read
    if image.size != (width, height):
        raise Refused("dimensions", f"decoded {image.size}, header {width}x{height}")
    profile = image.info.get("icc_profile")
    alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    image = ImageOps.exif_transpose(image)  # the photo as it is seen
    if image.mode in ("I;16", "I;16B", "I;16L", "I;16N", "I"):
        image = image.convert("I").point(lambda value: value * (1 / 256)).convert("L")
    keep_alpha = alpha and content_type != "image/jpeg"
    flat = image.convert("RGBA" if keep_alpha else "RGB")
    flat = _to_srgb(flat, profile)
    clean = Image.frombytes(flat.mode, flat.size, flat.tobytes())
    out = io.BytesIO()
    if content_type == "image/jpeg":
        clean.save(out, format="JPEG", quality=FILE_JPEG_QUALITY)
    elif content_type == "image/webp":
        clean.save(out, format="WEBP", lossless=lossless, quality=FILE_JPEG_QUALITY)
    else:
        clean.save(out, format="PNG")
    return out.getvalue()


def _limit(memory: int, seconds: int) -> None:
    """The child's own budgets, set before it reads a byte of the image."""
    if memory > 0:
        resource.setrlimit(resource.RLIMIT_AS, (memory, memory))
    if seconds > 0:
        resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))  # it writes no file
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))


def main() -> int:
    """`python -I avatar_decode.py <content type> <memory bytes> <cpu seconds> [attachment]`:
    the image on stdin; the stored PNG on stdout and exit 0, or the reason on stdout and
    `REFUSED` with a detail for the log on stderr."""
    content_type, memory, seconds = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    handle = process_file if sys.argv[4:] == ["attachment"] else process
    try:
        from PIL import Image, ImageCms, ImageOps, PngImagePlugin  # noqa: F401  before the limits

        _limit(memory, seconds)
        result = handle(sys.stdin.buffer.read(), content_type)
    except Refused as refused:
        sys.stdout.write(refused.reason)
        sys.stderr.write(refused.detail[:200])
        return REFUSED
    except MemoryError:
        sys.stdout.write("undecodable")
        sys.stderr.write("over the memory budget")
        return REFUSED
    except Exception as error:  # Pillow raises many kinds on malformed input
        sys.stdout.write("undecodable")
        sys.stderr.write(f"{type(error).__name__}: {error}"[:200])
        return REFUSED
    sys.stdout.buffer.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
