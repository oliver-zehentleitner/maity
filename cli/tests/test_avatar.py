"""`maity profile avatar` (§13, §6.10) against the fake hub."""

from __future__ import annotations

import json
from pathlib import Path

import fakehub
import pytest

from maity import cli

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
WEBP = b"RIFF\x40\x00\x00\x00WEBPVP8 " + b"\x00" * 64
ANSWER = {"avatar_url": "/api/v1/avatars/agt-b?v=e4d90b12", "avatar_source": "uploaded"}


@pytest.mark.parametrize(("data", "kind"), [(PNG, "image/png"), (JPEG, "image/jpeg"),
                                             (WEBP, "image/webp")])  # fmt: skip
def test_an_image_is_sent_raw_and_signed_with_its_sniffed_type(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    data: bytes, kind: str,
) -> None:  # fmt: skip
    image = tmp_path / "me.bin"  # the name says nothing; the bytes decide
    image.write_bytes(data)
    fake.routes[("PUT", "/api/v1/me/avatar")] = lambda s: (200, ANSWER)
    assert cli.main(["profile", "avatar", str(image)]) == cli.EXIT_OK
    sent = fake.signed()[-1]
    assert sent.method == "PUT" and sent.body == data
    assert sent.headers["content-type"] == kind
    assert 16 <= len(sent.headers["idempotency-key"]) <= 128
    assert "avatar set: /api/v1/avatars/agt-b?v=e4d90b12 (uploaded)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "data",
    [b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"GIF89a" + b"\x00" * 20, b""],
)
def test_anything_else_is_refused_before_any_call(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, data: bytes,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    image = tmp_path / "me.png"  # a .png name does not make it one
    image.write_bytes(data)
    before = len(fake.seen)
    assert cli.main(["profile", "avatar", str(image)]) == cli.EXIT_REFUSED
    assert len(fake.seen) == before
    assert "not a PNG, JPEG or WebP" in capsys.readouterr().err


def test_a_file_over_one_mebibyte_is_refused_before_any_call(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path
) -> None:
    image = tmp_path / "big.png"
    image.write_bytes(PNG + b"\x00" * (1024 * 1024))
    before = len(fake.seen)
    assert cli.main(["profile", "avatar", str(image)]) == cli.EXIT_REFUSED
    assert len(fake.seen) == before


def test_remove_deletes_the_upload(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("DELETE", "/api/v1/me/avatar")] = lambda s: (
        200, {"avatar_url": None, "avatar_source": None}
    )  # fmt: skip
    assert cli.main(["profile", "avatar", "--remove", "--json"]) == cli.EXIT_OK
    assert fake.signed()[-1].method == "DELETE"
    assert json.loads(capsys.readouterr().out) == {"avatar_url": None, "avatar_source": None}


def test_a_file_and_remove_together_or_neither_is_a_usage_error(joined: Path) -> None:
    assert cli.main(["profile", "avatar"]) == cli.EXIT_USAGE
    assert cli.main(["profile", "avatar", "x.png", "--remove"]) == cli.EXIT_USAGE


def test_the_hubs_refusal_is_shown(
    joined: Path, fake: fakehub.FakeHub, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    image = tmp_path / "me.png"
    image.write_bytes(PNG)
    fake.routes[("PUT", "/api/v1/me/avatar")] = lambda s: (
        429, {"error": {"code": "rate_limited", "message": "rate_limited", "details": {}}}
    )  # fmt: skip
    assert cli.main(["profile", "avatar", str(image)]) not in (cli.EXIT_OK, cli.EXIT_REFUSED)
    assert "rate_limited" in capsys.readouterr().err
