"""Where an attachment's bytes live (docs/api.md §8.7): a blob store behind the hub.

The key is made from the project and the attachment id, never from the name. `local` is
the one store built: a directory of the operator's volume. A blob is written whole to a
file of its own and moved into place, so a reader never sees half of one, and a removal
that finds nothing is a removal that is done.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path

from maity_hub.config import Settings
from maity_hub.errors import ApiError


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        project, _, name = key.partition("/")
        if not project or not name or "/" in name or {".", ".."} & {project, name}:
            raise ValueError("not a blob key")
        return self.root / project / name

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        scratch = path.with_name(f".{path.name}.{secrets.token_hex(6)}")
        try:
            with open(scratch, "xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(scratch, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                scratch.unlink()
            raise

    def get(self, key: str) -> bytes | None:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError:
            return None

    def delete(self, key: str) -> None:
        with contextlib.suppress(FileNotFoundError):
            self._path(key).unlink()

    def keys(self, project: str) -> list[str]:
        """The blobs of one project, for the sweep."""
        folder = self.root / project
        if not folder.is_dir():
            return []
        return [f"{project}/{p.name}" for p in folder.iterdir() if not p.name.startswith(".")]


def key_of(project_id: str, attachment_id: str) -> str:
    return f"{project_id}/{attachment_id}"


def store_of(settings: Settings) -> LocalStore:
    """The configured store, or `attachments_not_configured` (409) when the operator has
    set no `MAITY_ATTACHMENT_DIR`."""
    if settings.attachment_dir is None:
        raise ApiError(
            409,
            "attachments_not_configured",
            "this hub has no attachment store: the operator sets MAITY_ATTACHMENT_DIR",
        )
    return LocalStore(settings.attachment_dir)
