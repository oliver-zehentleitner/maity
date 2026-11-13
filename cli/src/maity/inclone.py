"""Files maity reads or writes for an agent under a runner placement: only inside the clone,
outside its `.git`, never through a link.

Under a placement maity runs outside the harness's sandbox (cli/context/runner.md), so a
path the agent names must not take maity where the sandbox keeps the agent out. Every name
is looked up once, through descriptors: the walk starts at the clone's root as
`clonecheck.opened_clone` opened and checked it together with `.git`, opens each directory
on the way from the one before without following a link, refuses the clone's `.git` (by
device and inode of that checked `.git`), and opens the last name in the directory that
holds it. A name looked up twice could point elsewhere the second time. A new file is
written without a name where the system allows it (`O_TMPFILE`), else beside its name, and
the descriptor maity wrote and checked is what gets the name, never whatever a name points
to by then; linking fails on an existing name, so maity never replaces a file there.
"""

from __future__ import annotations

import contextlib
import errno
import os
import secrets
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO

from maity import clonecheck

# Whether this system can open a name in a directory's descriptor without following a link:
# the walk needs both. Windows has neither; there maity reads and writes no such file.
WALKS = os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW")
FOLDER = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
# File systems without hard links (vfat, some SMB and FUSE mounts): a new file is then made
# with an exclusive create in the same directory and filled from maity's own descriptor.
NO_HARD_LINKS = (errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS)
# Linux names an open file under /proc/self/fd: linking that with AT_SYMLINK_FOLLOW gives the
# open file itself a name, whatever its own name points to meanwhile.
PROC_FD = "/proc/self/fd"
CHUNK = 1024 * 1024


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
    root: Path,
    path: list[str],
    opened: clonecheck.Opened | None,
    given: str,
    what: str,
    make: str | None,
) -> Iterator[int]:
    """The descriptor of the directory `path` names below the clone's root, each step opened
    from the one before without following a link and refused when it is the clone's `.git`.
    The walk starts at `opened.top`, the root `clonecheck.opened_clone` checked with `.git`;
    without it (a caller that holds no check) the root is opened here, without following a
    link, and `.git` is read from it. A missing last directory named `make` is created 0700
    first (`./maity-files/`)."""
    if not WALKS:  # Windows
        raise Refused(
            f"{what} {given}: this system cannot open a file without following links,"
            " so under a runner placement maity takes no such path here"
        )
    git: os.stat_result | None
    if opened is not None:
        fd = os.dup(opened.top)
        git = os.fstat(opened.git)
        if _same(os.fstat(fd), git):  # never true for a checked clone; kept as a second guard
            os.close(fd)
            raise Refused(f"{what} {given}: the clone's root is its .git; maity writes no file")
    else:
        fd = os.open(root, FOLDER | os.O_NOFOLLOW)
        try:
            git = os.stat(".git", dir_fd=fd, follow_symlinks=False)
        except OSError:
            git = None
    try:
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


def read(
    root: Path, given: str, what: str, limit: int, opened: clonecheck.Opened | None = None
) -> bytes:
    """The content of the file `given` names: a regular file in the clone, outside `.git`,
    with no other hard link, opened without following a link or blocking (a FIFO), at most
    `limit` bytes. `opened` is the clone as `clonecheck.opened_clone` checked it."""
    path = names(root, given, what)
    with _walk(root, path[:-1], opened, given, what, None) as directory:
        fd = _open_at(directory, path[-1], os.O_RDONLY | os.O_NONBLOCK, given, what)
    try:
        found = os.fstat(fd)
        if opened is not None and _same(found, os.fstat(opened.git)):
            raise Refused(f"{what} {given}: the clone's .git is not a file")
        if not stat.S_ISREG(found.st_mode):
            raise Refused(f"{what} {given}: not a plain file")
        if found.st_nlink != 1:
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
    opened: clonecheck.Opened | None = None,
    *,
    make: str | None = None,
    mode: int = 0o644,
) -> None:
    """A new file at `given`, in the clone and outside `.git`, with what `fill` writes.
    `opened` is the clone as `clonecheck.opened_clone` checked it. An existing name is
    refused before `fill` runs and again when the file gets its name, so a race leaves it
    untouched: maity never replaces a file under a placement. The bytes go to a file of
    maity's own first (without a name where the system allows it); an exception from `fill`
    (a digest that does not match) leaves nothing behind. The descriptor `fill` wrote to is
    what gets the name (`_publish`). `make` names a last directory created when missing."""
    path = names(root, given, what)
    exists = Refused(
        f"{what} {given}: exists; under a runner placement maity never replaces a file"
        " (--force included): remove it first or name another file"
    )
    with _walk(root, path[:-1], opened, given, what, make) as directory:
        leaf = path[-1]
        try:
            os.stat(leaf, dir_fd=directory, follow_symlinks=False)
            raise exists
        except FileNotFoundError:
            pass
        fd, part = _fresh(directory)
        try:
            with os.fdopen(os.dup(fd), "wb") as fh:
                fill(fh)
            os.fchmod(fd, mode)
            _publish(directory, fd, part, leaf, mode, exists, f"{what} {given}")
        finally:
            os.close(fd)
            if part is not None:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(part, dir_fd=directory)


def _fresh(directory: int) -> tuple[int, str | None]:
    """A new, empty, readable and writable file of maity's own in `directory`: without a
    name (`O_TMPFILE`, Linux) where the file system has that, so no one can open it by a
    name meanwhile; else under a random name, created exclusively without following a link."""
    tmpfile = getattr(os, "O_TMPFILE", 0)
    if tmpfile:
        try:
            return os.open(".", tmpfile | os.O_RDWR, 0o600, dir_fd=directory), None
        except OSError as exc:
            if exc.errno not in (errno.EOPNOTSUPP, errno.EISDIR, errno.EINVAL, errno.ENOENT):
                raise
    part = f".maity-{secrets.token_hex(8)}.part"
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    return os.open(part, flags, 0o600, dir_fd=directory), part


def _publish(
    directory: int, fd: int, part: str | None, leaf: str, mode: int, exists: Refused, said: str
) -> None:
    """Give the file open as `fd` the name `leaf` in `directory`, never over an existing
    name, and never another file than this one: through `/proc/self/fd` where there is one
    (the open file itself is linked); else by its own name `part`, compared by device and
    inode with `fd` before and after the link. Where the file system has no hard links, a
    new file under `leaf` is filled from `fd`, not from a name."""
    own = os.fstat(fd)
    replaced = Refused(f"{said}: the file maity checked was replaced before it got its name;"
                       " nothing was saved")  # fmt: skip
    via_proc = os.path.isdir(PROC_FD)
    try:
        if via_proc:
            os.link(f"{PROC_FD}/{fd}", leaf, dst_dir_fd=directory, follow_symlinks=True)
        elif part is not None:
            if not _same(os.stat(part, dir_fd=directory, follow_symlinks=False), own):
                raise replaced
            os.link(part, leaf, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        else:  # a file without a name and no /proc to name it by: copied below
            raise OSError(errno.ENOSYS, "no name to link")
    except FileExistsError:
        raise exists from None
    except OSError as exc:
        # ENOENT through /proc: the open file has no name left (its name was taken by
        # another file, which then went away with it), and Linux links no such file.
        if exc.errno not in NO_HARD_LINKS and not (via_proc and exc.errno == errno.ENOENT):
            raise
        _copy(directory, fd, leaf, mode, exists, replaced)
        return
    # As in `_copy`: a name that holds another file now is refused and left alone; it is
    # not maity's file, and removing it could take someone else's.
    linked = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
    if not _same(linked, own):
        raise replaced


def _copy(
    directory: int, fd: int, leaf: str, mode: int, exists: Refused, replaced: Refused
) -> None:
    """A new file `leaf` in `directory`, created exclusively without following a link, with
    the bytes of `fd` from its start: maity's own descriptor, never a name reopened. It
    succeeds as the link does, only when `leaf` still names the file written here (device
    and inode); otherwise it is refused and the name is left alone, since what it names now
    is not maity's file. On an error the name is removed only while it is still that file."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    try:
        out = os.open(leaf, flags, mode, dir_fd=directory)
    except FileExistsError:
        raise exists from None
    try:
        written = os.fstat(out)
    except BaseException:
        os.close(out)
        raise
    try:
        offset = 0
        while chunk := os.pread(fd, CHUNK, offset):
            offset += len(chunk)
            view = memoryview(chunk)
            while view:
                view = view[os.write(out, view) :]
        os.fchmod(out, mode)
        try:
            named = os.stat(leaf, dir_fd=directory, follow_symlinks=False)
        except OSError:
            named = None
        if named is None or not _same(named, written):
            raise replaced
    except BaseException as exc:
        os.close(out)
        if exc is not replaced:
            _unlink_if(directory, leaf, written)
        raise
    os.close(out)


def _unlink_if(directory: int, leaf: str, ours: os.stat_result) -> None:
    """Remove `leaf` only while it names the file `ours` describes."""
    with contextlib.suppress(OSError):
        if _same(os.stat(leaf, dir_fd=directory, follow_symlinks=False), ours):
            os.unlink(leaf, dir_fd=directory)
