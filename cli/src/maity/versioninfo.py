"""A build's Git identity, frozen in packages and live in source checkouts."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from maity import proc

STAMP_FILE = "_build.json"
REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_GIT_LOCATIONS = {
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
}


@dataclass(frozen=True)
class Stamp:
    revision: str
    dirty: bool


def read_stamp(path: Path) -> Stamp | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    revision, dirty = data.get("revision"), data.get("dirty")
    if not isinstance(revision, str) or not REVISION.fullmatch(revision):
        return None
    return Stamp(revision, dirty) if isinstance(dirty, bool) else None


def write_stamp(path: Path, stamp: Stamp | None) -> None:
    data = {"revision": stamp.revision if stamp else None, "dirty": stamp.dirty if stamp else False}
    path.parent.mkdir(parents=True, exist_ok=True)
    # An sdist release tree can hard-link its inputs: never overwrite the source file.
    path.unlink(missing_ok=True)
    path.write_text(json.dumps(data, sort_keys=True) + "\n", encoding="utf-8")


def _git(root: Path, *args: str) -> str:
    result = proc.run([*proc.GIT, *args], root, timeout=2)
    if result.returncode:
        raise proc.ToolError("Git build identity is unavailable")
    return result.stdout.strip()


def _git_locations_match(root: Path) -> bool:
    expected = {"GIT_DIR": root / ".git", "GIT_COMMON_DIR": root / ".git", "GIT_WORK_TREE": root}
    for key in _GIT_LOCATIONS:
        value = os.environ.get(key)
        if not value:
            continue
        path = Path(value)
        if (
            key not in expected
            or not path.is_absolute()
            or path.resolve() != expected[key].resolve()
        ):
            return False
    return True


def stamp_for(project: Path) -> Stamp | None:
    """Only the project itself or its monorepo parent can supply live Git identity.
    An extracted sdist, without either marker, carries the stamp of its source build."""
    project = project.resolve()
    root = next((p for p in (project, project.parent) if (p / ".git").exists()), None)
    if root is None:
        return read_stamp(project / "src" / "maity" / STAMP_FILE)
    try:
        if not _git_locations_match(root):
            return None
        if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
            return None
        # A neighboring .git can belong to the repository hosting an unpacked
        # sdist. Its manifest and Maity package must both belong to that tree.
        members = {
            (project / path).relative_to(root).as_posix()
            for path in ("pyproject.toml", "src/maity/__init__.py")
        }
        if set(_git(root, "ls-files", "--", *sorted(members)).splitlines()) != members:
            return read_stamp(project / "src" / "maity" / STAMP_FILE)
        revision = _git(root, "rev-parse", "HEAD")
        dirty = bool(
            _git(root, "status", "--porcelain", "--untracked-files=normal", "--", str(project))
        )
    except (OSError, proc.ToolError):
        return None
    return Stamp(revision, dirty) if REVISION.fullmatch(revision) else None


def version_text(version: str) -> str:
    package = Path(__file__).resolve().parent
    stamp = (
        stamp_for(package.parent.parent)
        if package.parent.name == "src"
        else read_stamp(package / STAMP_FILE)
    )
    build = stamp.revision[:12] + ("-dirty" if stamp.dirty else "") if stamp else "unknown"
    return f"maity {version} (build {build})"
