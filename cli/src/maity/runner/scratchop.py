"""A placement's scratch, made, measured and removed where the agents run (§15.5).

The scratch lies in `<workspaces>/<project_id>/.scratch/<placement id>`, and the agents can
write the project's directory: any directory on the way may have been replaced by a link.
Every operation is anchored at the workspaces root the runner was given (`under`): that
directory is opened, and each one below it is opened from the one before without following a
link, so a name swapped for a link after any check is refused, never followed out. The last
directory is held open by its descriptor for the whole operation: what is made is made in it,
what is measured or removed is reached from it, each level below opened from the one above
(`os.fwalk`); the emptied directory itself is removed from its parent only while that name
is still the directory held. The runner calls this in its own process when the agents are its
own user; through sudo or on an ssh host it starts this module there (`python -I -m
maity.runner.scratchop`, `maity runner scratchop`), which prints its answer as one JSON line.

Only the standard library: the module runs with `-I` on the agents' side.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import PurePath

OPS = ("make", "size", "remove")
# A clone's or project's name as the runner takes it (workspace.locate).
TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# A placement's scratch (§15.5): `<workspaces>/<project_id>/.scratch/<placement id>`. A clone's
# name starts with a letter or digit (TOKEN), so `.scratch` is never one.
SCRATCH = ".scratch"
SCRATCH_ID = re.compile(r"^plc-[0-9a-z-]{1,60}$")  # a placement id, as the supervisor takes it
LINK = 4  # the exit code for a link (or no directory) on the way: nothing was done
_FOLDER = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)


class OnTheWay(OSError):
    """A name on the way is a link or not a directory: nothing was made or removed."""


def supported() -> bool:
    """Whether this system opens a directory from another without following a link and
    removes a tree from a descriptor (not Windows)."""
    return (
        hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd and hasattr(os, "fwalk")
    )  # fmt: skip


def _below(path: str, under: str) -> list[str]:
    """The names from `under` down to `path`, which must be a scratch's path and nothing
    else: `<under>/<project>/.scratch/<placement id>`."""
    try:
        names = PurePath(path).relative_to(PurePath(under)).parts
    except ValueError:
        raise OSError(f"{path} is not inside {under}") from None
    if not (len(names) == 3 and TOKEN.match(names[0]) and names[1] == SCRATCH
            and SCRATCH_ID.match(names[2])):  # fmt: skip
        raise OSError(f"{path} is not a placement's scratch under {under}")
    return list(names)


def _step(fd: int, name: str, make: int | None) -> int:
    """The directory `name` in `fd`, opened without following a link; created with mode
    `make` first when missing."""
    if make is not None:
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, make, dir_fd=fd)
    try:
        return os.open(name, _FOLDER | os.O_NOFOLLOW, dir_fd=fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
            raise OnTheWay(f"{name} is a link or not a directory; nothing done") from None
        raise


@contextlib.contextmanager
def _opened(under: str, names: Sequence[str], make: bool) -> Iterator[int]:
    """The descriptor of the directory `names` lead to from `under`, each opened from the one
    before (`make`: created when missing, the innermost one 0700)."""
    fd = os.open(under, _FOLDER)  # the root the runner was configured with
    try:
        for index, name in enumerate(names):
            mode = (0o700 if index == len(names) - 1 else 0o777) if make else None
            inner = _step(fd, name, mode)
            os.close(fd)
            fd = inner
        yield fd
    finally:
        os.close(fd)


def _size(fd: int) -> int:
    """The bytes under the open directory `fd` (files and directories, as `du -sb` counts
    them), never following a link."""
    total = os.fstat(fd).st_size
    for _top, dirs, files, top_fd in os.fwalk(".", dir_fd=fd, follow_symlinks=False):
        for name in [*dirs, *files]:
            with contextlib.suppress(FileNotFoundError):
                total += os.stat(name, dir_fd=top_fd, follow_symlinks=False).st_size
    return total


def make(under: str, path: str) -> dict[str, object]:
    """The scratch at `path` with `tmp` in it, made as needed below the workspaces root,
    which must be there (the runner makes it with the clone)."""
    with _opened(under, [*_below(path, under), "tmp"], make=True):
        return {"result": "made"}


def size(under: str, path: str) -> dict[str, object]:
    """The bytes under the scratch at `path`; `missing` when there is none."""
    names = _below(path, under)
    try:
        with _opened(under, names[:-1], make=False) as parent:
            fd = _step(parent, names[-1], None)
            try:
                return {"result": "size", "bytes": _size(fd)}
            finally:
                os.close(fd)
    except FileNotFoundError:  # no root, project or `.scratch` either: no scratch
        return {"result": "missing"}


def remove(under: str, path: str) -> dict[str, object]:
    """The scratch at `path` removed from its open parent, with its size before; `missing`
    when there is none."""
    names = _below(path, under)
    try:
        with _opened(under, names[:-1], make=False) as parent:
            return _remove_in(parent, names[-1])
    except FileNotFoundError:  # no root, project or `.scratch` either: no scratch
        return {"result": "missing"}


def _remove_in(parent: int, name: str) -> dict[str, object]:
    """The directory `name` in the open `parent` removed, with its size before: measured and
    emptied through the one descriptor opened for it, and removed from `parent` only while
    `name` there is still that directory."""
    try:
        fd = _step(parent, name, None)
    except FileNotFoundError:
        return {"result": "missing"}
    try:
        before = _size(fd)
        _empty(fd)
        held = os.fstat(fd)
        found = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (found.st_dev, found.st_ino) != (held.st_dev, held.st_ino):
            raise OnTheWay(f"{name} was replaced while it was removed; left as it is")
        os.rmdir(name, dir_fd=parent)
    finally:
        os.close(fd)
    return {"result": "removed", "bytes": before}


def _empty(fd: int) -> None:
    """Everything under the open directory `fd` removed, deepest first, each level reached
    from the one above it without following a link (a link is removed, never entered)."""
    for _top, dirs, files, top_fd in os.fwalk(".", dir_fd=fd, topdown=False,
                                              follow_symlinks=False):  # fmt: skip
        for entry in files:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(entry, dir_fd=top_fd)
        for entry in dirs:
            try:
                os.rmdir(entry, dir_fd=top_fd)
            except NotADirectoryError:  # a link to a directory: the link goes
                os.unlink(entry, dir_fd=top_fd)
            except FileNotFoundError:
                pass


def run(op: str, under: str, path: str) -> dict[str, object]:
    if op not in OPS:
        raise OSError(f"unknown operation {op}")
    if not supported():
        raise OSError("this system cannot open a directory without following links")
    return {"make": make, "size": size, "remove": remove}[op](under, path)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 4 or args[1] != "--under" or args[0] not in OPS:
        print("usage: scratchop make|size|remove --under DIR PATH", file=sys.stderr)
        return 2
    op, _flag, under, path = args
    try:
        answer = run(op, under, path)
    except OnTheWay as exc:
        print(json.dumps({"result": "link", "why": str(exc)}))
        return LINK
    except OSError as exc:
        print(f"scratch: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
