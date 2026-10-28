"""The hub image's memory setting (hub/context/packaging.md)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DOCKERFILE = Path(__file__).resolve().parents[2] / "deploy" / "Dockerfile"


@pytest.mark.skipif(not DOCKERFILE.is_file(), reason="the Dockerfile is not in this checkout")
def test_the_image_limits_the_allocators_arenas() -> None:
    """Without it the process grows with every request through fragmented per-thread arenas;
    with two arenas it stays flat (measured: +5.3 MiB over 5,200 requests against +0.3)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^\s+MALLOC_ARENA_MAX=2\b", text, re.MULTILINE), "MALLOC_ARENA_MAX=2 is gone"
    assert re.search(r"^ENV MAITY_BIND=", text, re.MULTILINE)  # it is in the image's one ENV block
