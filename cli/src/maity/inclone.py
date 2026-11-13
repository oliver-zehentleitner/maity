"""Files maity reads or writes for an agent under a runner placement: only inside the clone,
outside its `.git`, never through a link.

Under a placement maity runs outside the harness's sandbox (cli/context/runner.md), so a
path the agent names must not take maity where the sandbox keeps the agent out. Every name
is looked up once, through descriptors: the clone's root is opened, then each directory on
the way from the one before without following a link, refusing the clone's `.git` (by
device and inode of the `.git` that `clonecheck.opened_git` checked), and the last name is
opened in the directory that holds it. A name looked up twice could point elsewhere the
second time. A new file is written beside its name and linked to it, which fails on an
existing name: maity never replaces a file there.
"""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
import shutil
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO

# Whether this system can open a name in a directory's descriptor without following a link:
# the walk needs both. Windows has neither; there maity reads and writes no such file.
WALKS = os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")
FOLDER = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
# File systems without hard links (vfat, some SMB and FUSE mounts): a new file is then made
# with an exclusive create in the same directory and copied into.
NO_HARD_LINKS = (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS)


class Refused(Exception):
    """The path is not one maity reads or writes under the placement; the text says why."""


def names(root: Path, given: str, what: str) -> list[str]:
    """The names from the clone's root down to the file `given` names (relative to the
    current directory, as the agent wrote it), worked out on the text alone: no name is
    looked up here, so none can be swapped. Refused when it leads out of the clone."""
    absolute = os.path.normpath(os.path.join(os.getcwd(), given))
    for base in dict.fromkeys((str(root), os.path.realpath(root))):
        relative = os.path.relpath(absolute, base)
        if relative != os.curdir and relative.split(os.sep)[0] != os.pardir:
            return relative.split(os.sep)
    raise Refused(f"{what} {given}: not a file in this clone ({root})")


def _same(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def _open_at(directory: int, name: str, flags: int, given: str, what: str) -> int:
    """`name` opened in the directory `directory` without following a link."""
    try:
        return os.open(name, flags | os.O_NOFOLLOW, dir_fd=directory)
    except OSError as exc:
        try:
            link = stat.S_ISLNK(os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode)
        except OSError:
            link = False
        if link or exc.errno == errno.ELOOP:
            raise Refused(f"{what} {given}: a link; name the file itself ({name} is one)") from None
        if exc.errno == errno.ENOENT:
            raise Refused(f"{what} {given}: no such file") from None
        if exc.errno == errno.ENOTDIR:
            raise Refused(f"{what} {given}: {name} is not a directory") from None
        raise Refused(f"{what} {given}: cannot be read ({exc.strerror})") from None


@contextlib.contextmanager
def _walk(
    root: Path, path: list[str], dot_git: int | None, given: str, what: str, make: str | None
) -> Iterator[int]:
    """The descriptor of the directory `path` names below the clone's root, each step opened
    from the one before without following a link and refused when it is the clone's `.git`.
    A missing last directory named `make` is created 0700 first (`./maity-files/`)."""
    if not WALKS:  # Windows
        raise Refused(
            f"{what} {given}: this system cannot open a file without following links,"
            " so under a runner placement maity takes no such path here"
        )
    fd = os.open(root, FOLDER)
    try:
        git: os.stat_result | None
        if dot_git is not None:
            git = os.fstat(dot_git)
        else:
            try:
                git = os.stat(".git", dir_fd=fd, follow_symlinks=False)
            except OSError:
                git = None
        for index, name in enumerate(path):
            if make is not None and name == make and index == len(path) - 1:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(name, 0o700, dir_fd=fd)
            inner = _open_at(fd, name, FOLDER, given, what)
            os.close(fd)
            fd = inner
            if git is not None and _same(os.fstat(fd), git):
                raise Refused(
                    f"{what} {given}: a path under the clone's .git; under a runner placement"
                    " maity reads and writes no file there"
                )
        yield fd
    finally:
        os.close(fd)


def read(root: Path, given: str, what: str, limit: int, dot_git: int | None = None) -> bytes:
    """The content of the file `given` names: a regular file in the clone, outside `.git`,
    with no other hard link, opened without following a link or blocking (a FIFO), at most
    `limit` bytes."""
    path = names(root, given, what)
    with _walk(root, path[:-1], dot_git, given, what, None) as directory:
        fd = _open_at(directory, path[-1], os.O_RDONLY | os.O_NONBLOCK, given, what)
    try:
        opened = os.fstat(fd)
        if dot_git is not None and _same(opened, os.fstat(dot_git)):
            raise Refused(f"{what} {given}: the clone's .git is not a file")
        if not stat.S_ISREG(opened.st_mode):
            raise Refused(f"{what} {given}: not a plain file")
        if opened.st_nlink != 1:
            raise Refused(f"{what} {given}: the file has other hard links")
        chunks: list[bytes] = []
        size = 0
        while size <= limit:
            chunk = os.read(fd, limit + 1 - size)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        os.close(fd)
    if size > limit:
        raise Refused(f"{what} {given}: over {limit} bytes")
    return b"".join(chunks)


def create(
    root: Path,
    given: str,
    what: str,
    fill: Callable[[IO[bytes]], None],
    dot_git: int | None = None,
    *,
    make: str | None = None,
    mode: int = 0o644,
) -> None:
    """A new file at `given`, in the clone and outside `.git`, with what `fill` writes. An
    existing name is refused before `fill` runs and again when the file is linked into
    place, so a race leaves it untouched: maity never replaces a file under a placement. The
    bytes go to a fresh file beside the name first; an exception from `fill` (a digest that
    does not match) leaves nothing behind. `make` names a last directory created when
    missing."""
    path = names(root, given, what)
    exists = Refused(
        f"{what} {given}: exists; under a runner placement maity never replaces a file"
        " (--force included): remove it first or name another file"
    )
    with _walk(root, path[:-1], dot_git, given, what, make) as directory:
        leaf = path[-1]
        try:
            os.stat(leaf, dir_fd=directory, follow_symlinks=False)
            raise exists
        except FileNotFoundError:
            pass
        part = f".maity-{secrets.token_hex(8)}.part"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(part, flags, 0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as fh:
                fill(fh)
                os.fchmod(fh.fileno(), mode)
            _link(directory, part, leaf, exists, mode)
        finally:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(part, dir_fd=directory)


def _link(directory: int, part: str, leaf: str, exists: Refused, mode: int) -> None:
    """Give `part` the name `leaf` in `directory`, never over an existing name."""
    try:
        os.link(part, leaf, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        return
    except FileExistsError:
        raise exists from None
    except OSError as exc:
        if exc.errno not in NO_HARD_LINKS:
            raise
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(part, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory), "rb") as fh:
        try:
            out = os.open(leaf, flags, mode, dir_fd=directory)
        except FileExistsError:
            raise exists from None
        try:
            with os.fdopen(out, "wb") as dst:
                shutil.copyfileobj(fh, dst)
                os.fchmod(dst.fileno(), mode)
        except BaseException:
            os.unlink(leaf, dir_fd=directory)
            raise
