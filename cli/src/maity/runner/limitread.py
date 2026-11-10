"""The loop's `limit.json`, read where the agents run (runner design §15.7).

The file lies on the agents' side, which may have written or replaced it. It is opened without
following a link and without blocking on a FIFO, taken only when it is a regular file, and read
up to LIMIT_BYTES. The runner reads it this way in its own process when the agents are its own
user; through sudo or on an ssh host it starts this module there (`python -I -m
maity.runner.limitread PATH`, `maity runner limitread PATH`), which prints what it read. No
`dd`: the one on macOS has no `iflag` and refuses `nofollow` and `nonblock`.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Sequence

LIMIT_BYTES = 512


def read(path: str) -> str | None:
    """At most LIMIT_BYTES of a regular file at `path`, never through a link; None otherwise."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        return os.read(fd, LIMIT_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    finally:
        os.close(fd)


def main(args: Sequence[str] | None = None) -> int:
    """Print what `read` found and exit 0; exit 1 when there is nothing to take."""
    argv = list(sys.argv[1:] if args is None else args)
    if len(argv) != 1:
        print("usage: limitread PATH", file=sys.stderr)
        return 2
    text = read(argv[0])
    if text is None:
        return 1
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
