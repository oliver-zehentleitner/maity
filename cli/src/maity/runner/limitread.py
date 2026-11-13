"""Files on the agents' side, read where the agents run (runner design §15.7).

A file the agents can write (the loop's `limit.json`, anything in a clone, a placement's log)
may have been replaced by a link, a FIFO or a file of any size. It is opened without following
a link and without blocking on a FIFO, taken only when it is a regular file, and read up to a
limit. The runner reads it this way in its own process when the agents are its own user;
through sudo or on an ssh host it starts this module there (`python -I -m
maity.runner.limitread PATH`, `maity runner limitread PATH`), which prints what it read. No
`dd`: the one on macOS has no `iflag` and refuses `nofollow` and `nonblock`.

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

LIMIT_BYTES = 512
BEHIND = 3  # the exit code for an offset past the end of the file
_CHUNK = 64 * 1024


class Behind(OSError):
    """The offset lies past the file's end: the file was cut since it was last read."""


def _flags() -> int:
    # Windows has neither O_NOFOLLOW nor O_NONBLOCK (nor FIFOs); O_BINARY keeps its C runtime
    # from translating line ends.
    return (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_BINARY", 0))  # fmt: skip


def take(path: str, offset: int = 0, limit: int = LIMIT_BYTES) -> bytes:
    """At most `limit` bytes of the regular file at `path` from `offset` on, never through a
    link and never waiting on a FIFO; OSError otherwise, Behind for an offset past the end."""
    if not hasattr(os, "O_NOFOLLOW"):  # Windows: no flag for it, so look before opening
        mode = os.lstat(path)
        reparse = getattr(mode, "st_file_attributes", 0) & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
        if not stat.S_ISREG(mode.st_mode) or reparse:
            raise OSError(f"{path} is not a regular file")
    fd = os.open(path, _flags())
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


def read(path: str) -> str | None:
    """At most LIMIT_BYTES of a regular file at `path`, never through a link; None otherwise."""
    try:
        return take(path).decode("utf-8", errors="replace")
    except OSError:
        return None


def _number(text: str) -> int | None:
    return int(text) if text.isdigit() else None


def main(args: Sequence[str] | None = None) -> int:
    """`PATH`: print what `read` found and exit 0, exit 1 when there is nothing to take.
    `--bytes N [--offset N] PATH`: print the raw bytes `take` read, exit BEHIND past the
    end, 1 when there is nothing to take."""
    argv = list(sys.argv[1:] if args is None else args)
    options: dict[str, int] = {}
    while len(argv) > 1 and argv[0] in ("--bytes", "--offset"):
        value = _number(argv[1])
        if value is None:
            break
        options[argv[0]] = value
        argv = argv[2:]
    if len(argv) != 1 or ("--offset" in options and "--bytes" not in options):
        print("usage: limitread [--bytes N [--offset N]] PATH", file=sys.stderr)
        return 2
    if "--bytes" not in options:
        text = read(argv[0])
        if text is None:
            return 1
        sys.stdout.write(text)
        return 0
    try:
        data = take(argv[0], options.get("--offset", 0), options["--bytes"])
    except Behind:
        return BEHIND
    except OSError:
        return 1
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
