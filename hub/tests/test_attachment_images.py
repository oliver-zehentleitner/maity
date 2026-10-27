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
    colour: Any = {"RGBA": (200, 30, 30, 128), "RGB": (200, 30, 30), "L": 128}.get(mode, 0)
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


# --- a source profile of the image's own space is applied before the image is flattened ---------


def _fixed(value: float) -> bytes:
    return struct.pack(">i", round(value * 65536))


def _profile(space: bytes, pcs: bytes, klass: bytes, tags: dict[bytes, bytes]) -> bytes:
    """A minimal ICC v2 profile: header, tag table, tags."""
    names = [b"desc", b"cprt", b"wtpt", *tags]
    base = {
        b"desc": b"desc"
        + bytes(4)
        + struct.pack(">I", 5)
        + b"test\x00"
        + bytes(4 + 4 + 2 + 1 + 67),
        b"cprt": b"text" + bytes(4) + b"none\x00",
        b"wtpt": b"XYZ " + bytes(4) + _fixed(0.9642) + _fixed(1.0) + _fixed(0.8249),
        **tags,
    }
    table, body = b"", b""
    start = 128 + 4 + 12 * len(names)
    for name in names:
        data = base[name]
        table += name + struct.pack(">II", start + len(body), len(data))
        body += data + bytes(-len(data) % 4)
    header = bytearray(128)
    struct.pack_into(">I", header, 0, 128 + 4 + len(table) + len(body))
    struct.pack_into(">I", header, 8, 0x02400000)
    header[12:16], header[16:20], header[20:24] = klass, space, pcs
    header[36:40] = b"acsp"
    header[68:80] = _fixed(0.9642) + _fixed(1.0) + _fixed(0.8249)
    return bytes(header) + struct.pack(">I", len(names)) + table + body


def _grey_profile(gamma: float) -> bytes:
    curve = b"curv" + bytes(4) + struct.pack(">IH", 1, round(gamma * 256))
    return _profile(b"GRAY", b"XYZ ", b"mntr", {b"kTRC": curve})


def _cmyk_profile() -> bytes:
    """Four inputs, two grid points each, to Lab: darker and tinted by ink, nothing like
    the naive CMYK to RGB."""
    clut = bytearray()
    for c in (0, 1):
        for m in (0, 1):
            for y in (0, 1):
                for k in (0, 1):
                    lightness = (1 - 0.9 * k) * (1 - 0.25 * (c + m + y))
                    clut += bytes(
                        [
                            round(255 * lightness),
                            128 + round(40 * (m - c)),
                            128 + round(40 * (y - 0.3 * c)),
                        ]
                    )
    identity = bytes(range(256))
    matrix = b"".join(_fixed(v) for v in (1, 0, 0, 0, 1, 0, 0, 0, 1))
    lut = b"mft1" + bytes(4) + bytes([4, 3, 2, 0]) + matrix + identity * 4 + bytes(clut)
    lut += identity * 3
    return _profile(b"CMYK", b"Lab ", b"prtr", {b"A2B0": lut})


def _centre(data: bytes) -> tuple[int, ...]:
    image = reopen(data).convert("RGB")
    value: tuple[int, ...] = image.getpixel((image.width // 2, image.height // 2))  # type: ignore[assignment]
    return value


def test_a_grey_image_with_its_profile_is_converted_to_srgb(settings: Settings) -> None:
    profile = _grey_profile(1.0)  # linear grey: far from sRGB's curve
    source = make("PNG", (32, 32), mode="L", icc_profile=profile)
    stored = avatars.decode_attachment(settings, source, "image/png")
    grey = Image.open(io.BytesIO(source))
    wanted = ImageCms.profileToProfile(
        grey,
        ImageCms.ImageCmsProfile(io.BytesIO(profile)),
        ImageCms.createProfile("sRGB"),
        outputMode="RGB",
    )
    assert wanted is not None
    expected = wanted.getpixel((5, 5))
    naive = grey.convert("RGB").getpixel((5, 5))
    got = _centre(stored.data)
    assert all(abs(g - e) <= 2 for g, e in zip(got, expected, strict=True))
    assert max(abs(g - n) for g, n in zip(got, naive, strict=True)) >= 20  # the profile mattered
    assert "icc_profile" not in reopen(stored.data).info and reopen(stored.data).mode == "RGB"


def test_a_cmyk_jpeg_with_its_profile_is_converted_to_srgb(settings: Settings) -> None:
    profile = _cmyk_profile()
    out = io.BytesIO()
    Image.new("CMYK", (32, 32), (60, 120, 30, 40)).save(out, format="JPEG", icc_profile=profile)
    source = out.getvalue()
    stored = avatars.decode_attachment(settings, source, "image/jpeg")
    reopened = Image.open(io.BytesIO(source))
    wanted = ImageCms.profileToProfile(
        reopened,
        ImageCms.ImageCmsProfile(io.BytesIO(profile)),
        ImageCms.createProfile("sRGB"),
        outputMode="RGB",
    )
    assert wanted is not None
    expected = wanted.getpixel((16, 16))
    naive = reopened.convert("RGB").getpixel((16, 16))
    got = _centre(stored.data)
    assert all(abs(g - e) <= 3 for g, e in zip(got, expected, strict=True))
    assert max(abs(g - n) for g, n in zip(got, naive, strict=True)) >= 10  # the profile mattered
    assert "icc_profile" not in reopen(stored.data).info and reopen(stored.data).mode == "RGB"


def test_a_profile_of_another_space_than_the_image_is_ignored(settings: Settings) -> None:
    source = make("PNG", (16, 16), icc_profile=_grey_profile(1.0))  # grey profile, RGB image
    stored = avatars.decode_attachment(settings, source, "image/png")
    assert _centre(stored.data) == (200, 30, 30)  # untouched
    assert "icc_profile" not in reopen(stored.data).info


def _palette_png(transparent: bool, **save: Any) -> bytes:
    palette = Image.new("P", (32, 32))
    palette.putpalette([200, 30, 30, 20, 160, 40] + [0] * 756)
    if transparent:
        save["transparency"] = 0
    out = io.BytesIO()
    palette.save(out, format="PNG", **save)
    return out.getvalue()


def _linear_rgb_profile() -> bytes:
    """An RGB matrix profile with sRGB's primaries and a linear curve: a conversion to
    sRGB changes every mid-tone, so a profile that is skipped shows."""
    primaries = {
        b"rXYZ": (0.4360, 0.2225, 0.0139),
        b"gXYZ": (0.3851, 0.7169, 0.0971),
        b"bXYZ": (0.1431, 0.0606, 0.7141),
    }
    tags = {
        name: b"XYZ " + bytes(4) + b"".join(_fixed(v) for v in xyz)
        for name, xyz in primaries.items()
    }
    curve = b"curv" + bytes(4) + struct.pack(">IH", 1, 256)  # gamma 1.0
    tags |= {b"rTRC": curve, b"gTRC": curve, b"bTRC": curve}
    return _profile(b"RGB ", b"XYZ ", b"mntr", tags)


def test_a_palette_png_with_an_rgb_profile_is_converted_and_keeps_its_transparency(
    settings: Settings,
) -> None:
    profile = _linear_rgb_profile()
    sRGB = ImageCms.createProfile("sRGB")
    for transparent in (False, True):
        source = _palette_png(transparent, icc_profile=profile)
        stored = reopen(avatars.decode_attachment(settings, source, "image/png").data)
        expanded = Image.open(io.BytesIO(source)).convert("RGB")
        wanted = ImageCms.profileToProfile(
            expanded, ImageCms.ImageCmsProfile(io.BytesIO(profile)), sRGB, outputMode="RGB"
        )
        assert wanted is not None
        # Pixel (20, 20) is palette index 0, the red, on a plain image and a see-through one.
        expected, naive = wanted.getpixel((20, 20)), expanded.getpixel((20, 20))
        got = stored.convert("RGB").getpixel((20, 20))
        assert all(abs(g - e) <= 3 for g, e in zip(got, expected, strict=True))
        assert max(abs(g - n) for g, n in zip(got, naive, strict=True)) >= 20
        assert "icc_profile" not in stored.info
        assert stored.mode == ("RGBA" if transparent else "RGB")
        if transparent:
            assert stored.getpixel((20, 20))[3] == 0  # index 0 stayed transparent


def test_a_palette_png_without_a_profile_keeps_its_transparency(settings: Settings) -> None:
    stored = avatars.decode_attachment(settings, _palette_png(True), "image/png")
    assert reopen(stored.data).mode == "RGBA" and reopen(stored.data).getpixel((1, 1))[3] == 0
