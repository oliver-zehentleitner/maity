"""docs/api.md §8.7: an attachment's image is decoded and encoded again, and nothing of the
uploaded file but its pixels is stored."""

from __future__ import annotations

import io
import struct
import zlib
from typing import Any

import pytest
from PIL import Image, ImageCms, PngImagePlugin

from maity_hub import avatar_decode, avatars
from maity_hub.config import Settings
from maity_hub.errors import ApiError


def make(kind: str, size: tuple[int, int] = (300, 200), mode: str = "RGB", **save: Any) -> bytes:
    colour: Any = {"RGBA": (200, 30, 30, 128), "RGB": (200, 30, 30)}.get(mode, 0)
    out = io.BytesIO()
    Image.new(mode, size, colour).save(out, format=kind, **save)
    return out.getvalue()


def reopen(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


def refused(settings: Settings, data: bytes, content_type: str) -> dict[str, str]:
    with pytest.raises(ApiError) as caught:
        avatars.decode_attachment(settings, data, content_type)
    assert caught.value.code == "invalid"
    fields: dict[str, str] = caught.value.details["fields"]
    return fields


def test_a_png_keeps_its_size_and_loses_its_text_and_profile(settings: Settings) -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("Comment", "secret place")
    source = make("PNG", (640, 480), pnginfo=info)
    assert b"secret place" in source
    stored = avatars.decode_attachment(settings, source, "image/png")
    assert (stored.type, stored.width, stored.height) == ("image/png", 640, 480)
    assert b"secret place" not in stored.data
    assert reopen(stored.data).info == {}  # nothing but its pixels
    assert reopen(stored.data).size == (640, 480)  # no crop, no scaling


def test_a_png_with_transparency_keeps_its_alpha(settings: Settings) -> None:
    stored = avatars.decode_attachment(settings, make("PNG", mode="RGBA"), "image/png")
    assert reopen(stored.data).mode == "RGBA"
    assert reopen(stored.data).getpixel((1, 1)) == (200, 30, 30, 128)


def test_a_jpeg_loses_its_exif_and_is_turned_as_it_is_seen(settings: Settings) -> None:
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90° clockwise to display
    exif[0x010F] = "Camera Maker"
    source = make("JPEG", (300, 200), exif=exif.tobytes(), comment=b"secret place")
    stored = avatars.decode_attachment(settings, source, "image/jpeg")
    assert stored.type == "image/jpeg" and (stored.width, stored.height) == (200, 300)
    reopened = reopen(stored.data)
    assert reopened.format == "JPEG" and reopened.size == (200, 300)
    assert not reopened.getexif() and b"secret place" not in stored.data
    assert b"Camera Maker" not in stored.data


def test_a_gif_becomes_a_png_of_its_first_frame(settings: Settings) -> None:
    first = Image.new("RGB", (64, 48), (255, 0, 0))
    second = Image.new("RGB", (64, 48), (0, 0, 255))
    out = io.BytesIO()
    first.save(out, format="GIF", save_all=True, append_images=[second], duration=50, loop=0)
    stored = avatars.decode_attachment(settings, out.getvalue(), "image/gif")
    assert stored.type == "image/png" and (stored.width, stored.height) == (64, 48)
    pixel = reopen(stored.data).convert("RGB").getpixel((3, 3))
    assert pixel[0] > 200 and pixel[2] < 60  # the first frame, red
    assert getattr(reopen(stored.data), "n_frames", 1) == 1


def test_a_webp_stays_lossless_or_lossy_as_it_was(settings: Settings) -> None:
    lossless = avatars.decode_attachment(settings, make("WEBP", lossless=True), "image/webp")
    lossy = avatars.decode_attachment(settings, make("WEBP", quality=60), "image/webp")
    assert lossless.type == lossy.type == "image/webp"
    assert avatar_decode.webp_lossless(lossless.data) is True
    assert avatar_decode.webp_lossless(lossy.data) is False
    assert reopen(lossless.data).size == (300, 200)


def test_a_colour_profile_is_converted_to_srgb_and_dropped(settings: Settings) -> None:
    wide = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
    # A profile of another space than RGB is dropped without a conversion ...
    other = make("PNG", icc_profile=wide)
    stored = avatars.decode_attachment(settings, other, "image/png")
    assert "icc_profile" not in reopen(stored.data).info
    # ... and an RGB profile is applied, then not stored either.
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    plain = avatars.decode_attachment(settings, make("PNG", icc_profile=srgb), "image/png")
    assert "icc_profile" not in reopen(plain.data).info
    assert reopen(plain.data).getpixel((1, 1))[0] > 190  # the red is still red


def test_an_image_over_the_side_or_the_pixel_limit_is_refused_by_its_header(
    settings: Settings,
) -> None:
    assert refused(settings, make("PNG", (8193, 8)), "image/png") == {"body": "dimensions"}
    assert refused(settings, make("PNG", (7000, 6000), mode="1"), "image/png") == {
        "body": "dimensions"
    }
    assert avatars.decode_attachment(settings, make("PNG", (4097, 8)), "image/png").width == 4097


def test_hostile_inputs_are_refused_not_stored(settings: Settings) -> None:
    good = make("PNG", (64, 64))
    truncated = good[: len(good) // 2]
    assert refused(settings, truncated, "image/png") == {"body": "undecodable"}
    assert refused(settings, b"not an image at all", "image/png") == {"body": "undecodable"}
    assert refused(settings, b"GIF89a", "image/gif") == {"body": "undecodable"}
    # A PNG text chunk over its cap.
    big = bytearray(good)
    text = b"Comment\x00" + b"x" * (70 * 1024)
    chunk = struct.pack(">I", len(text)) + b"tEXt" + text
    chunk += struct.pack(">I", zlib.crc32(b"tEXt" + text))
    end = bytes(big).rindex(b"IEND") - 4
    assert refused(settings, bytes(big[:end]) + chunk + bytes(big[end:]), "image/png") == {
        "body": "undecodable"
    }


def test_a_decode_that_finds_every_slot_taken_is_rate_limited(settings: Settings) -> None:
    slots = avatars._slots_for(settings.avatar_decodes)
    taken = 0
    try:
        while slots.acquire(blocking=False):
            taken += 1
        with pytest.raises(ApiError) as caught:
            avatars.decode_attachment(settings, make("PNG", (8, 8)), "image/png")
        assert caught.value.code == "rate_limited"
    finally:
        for _ in range(taken):
            slots.release()
