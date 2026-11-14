"""Files on the agents' side, read where the agents run (runner design §15.7).

A file the agents can write (the loop's `limit.json`, anything in a clone, a placement's log)
may have been replaced by a link, a FIFO or a file of any size, and so may every directory on
the way to it below the place the runner knows. A read is anchored there (`under`: the clone,
the agents' file directory, the agents' home): that directory is opened, every directory below
it is opened from the one before without following a link, and the file is opened from the
last one without following a link and without blocking on a FIFO, taken only when it is a
regular file, and read up to a limit. A directory swapped for a link after any listing is
refused, never followed out. The runner reads this way in its own process when the agents are
its own user; through sudo or on an ssh host it starts this module there (`python -I -m
maity.runner.limitread --under DIR PATH`, `maity runner limitread --under DIR PATH`), which
prints what it read. No `dd`: the one on macOS has no `iflag` and refuses `nofollow` and
`nonblock`.

`PATH` alone is the loop's limit file: at most LIMIT_BYTES, printed as text. With `--bytes N`
(and `--offset N`) it prints at most N raw bytes from the offset on, and exits BEHIND when
the offset lies past the file's end (a log that was cut). Only the standard library: the
module runs with `-I` on the agents' side.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Sequence
from pathlib import PurePath

LIMIT_BYTES = 512
BEHIND = 3  # the exit code for an offset past the end of the file
_CHUNK = 64 * 1024


class Behind(OSError):
    """The offset lies past the file's end: the file was cut since it was last read."""


def _flags() -> int:
    # Windows has neither O_NOFOLLOW nor O_NONBLOCK (nor FIFOs); O_BINARY keeps its C runtime
    # from translating line ends.
    return (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0))  # fmt: skip


def _below(path: str, under: str) -> list[str]:
    """The names from `under` down to `path`, which must lie below it: no `..` and no `.`."""
    try:
        names = PurePath(path).relative_to(PurePath(under)).parts
    except ValueError:
        raise OSError(f"{path} is not inside {under}") from None
    if not names or any(name in ("", ".", "..") for name in names):
        raise OSError(f"{path} is not inside {under}")
    return list(names)


def _open(path: str, under: str) -> int:
    """`path` opened for reading from `under` down, never through a link on the way."""
    names = _below(path, under)
    if os.open not in os.supports_dir_fd:  # Windows: no openat, so look at each step first
        here = PurePath(under)
        for n, name in enumerate(names):
            here = here / name
            mode = os.lstat(here)
            reparse = getattr(mode, "st_file_attributes", 0) & 0x400  # a REPARSE_POINT
            last = n == len(names) - 1
            if reparse or not (stat.S_ISREG if last else stat.S_ISDIR)(mode.st_mode):
                raise OSError(f"{here} is not a plain {'file' if last else 'directory'}")
        return os.open(path, _flags())
    directory = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0)
    # The anchor itself is the runner's own path (configured, or a clone it located), opened
    # as it stands; everything below it is the agents'.
    at = os.open(under, directory)
    try:
        for name in names[:-1]:
            step = os.open(name, directory | os.O_NOFOLLOW, dir_fd=at)
            os.close(at)
            at = step
        return os.open(names[-1], _flags(), dir_fd=at)
    finally:
        os.close(at)


def take(path: str, offset: int = 0, limit: int = LIMIT_BYTES, *, under: str) -> bytes:
    """At most `limit` bytes of the regular file at `path` from `offset` on, reached from
    `under` without following a link and never waiting on a FIFO; OSError otherwise, Behind
    for an offset past the end."""
    fd = _open(path, under)
    try:
        found = os.fstat(fd)
        if not stat.S_ISREG(found.st_mode):
            raise OSError(f"{path} is not a regular file")
        if offset > found.st_size:
            raise Behind(f"{path} is shorter than {offset} bytes")
        if offset:
            os.lseek(fd, offset, os.SEEK_SET)
        data = b""
        while len(data) < limit:
            chunk = os.read(fd, min(_CHUNK, limit - len(data)))
            if not chunk:
                break
            data += chunk
        return data
    finally:
        os.close(fd)


def read(path: str, *, under: str) -> str | None:
    """At most LIMIT_BYTES of a regular file at `path`, reached from `under` without
    following a link; None otherwise."""
    try:
        return take(path, under=under).decode("utf-8", errors="replace")
    except OSError:
        return None


def _number(text: str) -> int | None:
    return int(text) if text.isdigit() else None


def main(args: Sequence[str] | None = None) -> int:
    """`--under DIR PATH`: print what `read` found and exit 0, exit 1 when there is nothing
    to take. `--under DIR --bytes N [--offset N] PATH`: print the raw bytes `take` read, exit
    BEHIND past the end, 1 when there is nothing to take."""
    argv = list(sys.argv[1:] if args is None else args)
    options: dict[str, int] = {}
    under: str | None = None
    while len(argv) > 1 and argv[0] in ("--bytes", "--offset", "--under"):
        if argv[0] == "--under":
            under = argv[1]
        else:
            value = _number(argv[1])
            if value is None:
                break
            options[argv[0]] = value
        argv = argv[2:]
    if (len(argv) != 1 or not under
            or ("--offset" in options and "--bytes" not in options)):  # fmt: skip
        print("usage: limitread --under DIR [--bytes N [--offset N]] PATH", file=sys.stderr)
        return 2
    if "--bytes" not in options:
        text = read(argv[0], under=under)
        if text is None:
            return 1
        sys.stdout.write(text)
        return 0
    try:
        data = take(argv[0], options.get("--offset", 0), options["--bytes"], under=under)
    except Behind:
        return BEHIND
    except OSError:
        return 1
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
