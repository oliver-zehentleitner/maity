"""The pictures an agent may choose (docs/api.md §6.10, "An agent's motif").

The set is part of the hub's code: `avatar_motifs/` holds the PNG files and `manifest.json`,
`{"version", "motifs": [{"name", "theme", "label", "alt", "file"}]}`. The hub reads it once,
checks it and passes every motif through the decoder and the encoder of an upload
(`avatar_decode.process`, in this process: the files are the hub's own, not a caller's), so a
motif is stored at 256 pixels and kept in every size like any picture. A set that fails the
check is not served: the list is empty and every agent shows its upload or its generated
picture; the log says why.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maity_hub import avatar_decode, images

log = logging.getLogger(__name__)

FOLDER = Path(__file__).with_name("avatar_motifs")
NAME = re.compile(r"[a-z][a-z0-9-]{1,31}")
SOURCE_SIDE = 512
SOURCE_BYTES = 64 * 1024
LABEL_MAX = 40
ALT_MAX = 120


@dataclass(frozen=True)
class Motif:
    name: str
    theme: str
    label: str
    alt: str
    data: bytes  # the stored picture, 256 pixels
    etag: str
    sizes: dict[int, tuple[bytes, str]] = field(default_factory=dict)

    @property
    def digest(self) -> str:
        return self.etag.strip('"')

    def at(self, side: int) -> tuple[bytes, str]:
        """The motif at `side` pixels (§6.10, Sizes): 256 is the stored picture."""
        return self.sizes.get(side, (self.data, self.etag))


@dataclass(frozen=True)
class MotifSet:
    version: str
    motifs: tuple[Motif, ...]

    def named(self, name: str | None) -> Motif | None:
        return next((m for m in self.motifs if m.name == name), None) if name else None

    def with_digest(self, digest: str) -> Motif | None:
        return next((m for m in self.motifs if m.digest == digest), None)


EMPTY = MotifSet("", ())


class Refused(Exception):
    """The set fails the check (§6.10): nothing of it is served."""


_lock = threading.Lock()
_loaded: dict[Path, MotifSet] = {}


def current(folder: Path | None = None) -> MotifSet:
    """The set the hub serves, read and checked once per folder."""
    where = folder or FOLDER
    with _lock:
        if where not in _loaded:
            _loaded[where] = load(where)
        return _loaded[where]


def load(folder: Path) -> MotifSet:
    try:
        return _read(folder)
    except Refused as why:
        log.error("the avatar motifs are not served: %s", why)
        return EMPTY


def _text(entry: dict[str, Any], key: str, limit: int, where: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise Refused(f"{where}: `{key}` is not a text of 1 to {limit} characters")
    return value


def _read(folder: Path) -> MotifSet:
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as why:
        raise Refused(f"manifest.json: {why}") from None
    entries = manifest.get("motifs") if isinstance(manifest, dict) else None
    if not isinstance(entries, list) or not entries:
        raise Refused("manifest.json names no motifs")
    seen: set[str] = set()
    read: list[Motif] = []
    for number, entry in enumerate(entries):
        where = f"motif {number}"
        if not isinstance(entry, dict):
            raise Refused(f"{where} is not an object")
        name, theme, file = entry.get("name"), entry.get("theme"), entry.get("file")
        if not isinstance(name, str) or not NAME.fullmatch(name):
            raise Refused(f"{where}: name {name!r} is not in the syntax {NAME.pattern}")
        where = f"motif {name}"
        if name in seen:
            raise Refused(f"{where}: the name is not unique")
        seen.add(name)
        if not isinstance(theme, str) or not NAME.fullmatch(theme):
            raise Refused(f"{where}: theme {theme!r} is not in the syntax {NAME.pattern}")
        label = _text(entry, "label", LABEL_MAX, where)
        alt = _text(entry, "alt", ALT_MAX, where)
        if not isinstance(file, str) or "/" in file or "\\" in file or file.startswith("."):
            raise Refused(f"{where}: file {file!r} is not a file name in the folder")
        try:
            source = (folder / file).read_bytes()
        except OSError as why:
            raise Refused(f"{where}: {why}") from None
        if len(source) > SOURCE_BYTES:
            raise Refused(f"{where}: {len(source)} bytes, over {SOURCE_BYTES}")
        if images.sniff(source) != "image/png":
            raise Refused(f"{where}: not a PNG")
        if avatar_decode.dimensions(source, "image/png") != (SOURCE_SIDE, SOURCE_SIDE):
            raise Refused(f"{where}: not {SOURCE_SIDE} × {SOURCE_SIDE} pixels")
        try:
            stored = avatar_decode.process(source, "image/png")
            sizes = {}
            for side in avatar_decode.SIZES:
                small = avatar_decode.process_size(stored, side)
                sizes[side] = (small, images.etag(small))
        except avatar_decode.Refused as why:
            raise Refused(f"{where}: the decoder refused it ({why})") from None
        read.append(Motif(name, theme, label, alt, stored, images.etag(stored), sizes))
    themes = list(dict.fromkeys(m.theme for m in read))  # in the order of their first motif
    ordered = sorted(read, key=lambda m: themes.index(m.theme))  # stable: the set's order
    return MotifSet(str(manifest.get("version", "")), tuple(ordered))
