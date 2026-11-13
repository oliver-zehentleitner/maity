"""A placement's pane log, held to `limits.log_keep_bytes` (runner design §15.7).

tmux's `pipe-pane` hands every byte an agent's pane shows to this module, started on the
agents' side (`python -I -m maity.runner.logcap LOG LIMIT`, `maity runner logcap LOG LIMIT` on
an ssh host). It appends to LOG; when the next chunk would take the file past LIMIT bytes,
the file is cut to its newest LIMIT / 2 bytes first, through a copy renamed over it, so the
log keeps the latest output and never holds more than LIMIT bytes. A write that fails (a full
disk) drops that chunk and the module reads on: the pane never waits on its log. Only the
standard library: the module runs with `-I`.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Sequence

CHUNK = 64 * 1024
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _open(path: str) -> tuple[int, int]:
    """The log opened for appending, never through a link, and its size."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | _NOFOLLOW, 0o600)
    found = os.fstat(fd)
    if not stat.S_ISREG(found.st_mode):
        os.close(fd)
        raise OSError(f"{path} is not a regular file")
    return fd, found.st_size


def _cut(path: str, fd: int, keep: int) -> tuple[int, int]:
    """Cut the log to its newest `keep` bytes: copied to a file beside it, renamed over it,
    reopened. A copy that cannot be made empties the log instead, so the limit holds."""
    temporary = f"{path}.cut"
    try:
        with open(path, "rb", opener=lambda p, f: os.open(p, f | _NOFOLLOW)) as old:
            size = os.fstat(old.fileno()).st_size
            old.seek(max(0, size - keep))
            tail = old.read(keep)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        out = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW, 0o600)
        try:
            os.write(out, tail)
        finally:
            os.close(out)
        os.replace(temporary, path)
    except OSError:
        os.ftruncate(fd, 0)
        return fd, 0
    reopened = _open(path)
    os.close(fd)
    return reopened


def run(path: str, limit: int, source: int = 0) -> int:
    """Copy `source` into the log at `path` until it ends, holding the log to `limit`."""
    fd, size = _open(path)
    try:
        while True:
            chunk = os.read(source, CHUNK)
            if not chunk:
                return 0
            chunk = chunk[-limit:]
            try:
                if size + len(chunk) > limit:
                    fd, size = _cut(path, fd, min(limit // 2, limit - len(chunk)))
                os.write(fd, chunk)
                size += len(chunk)
            except OSError:  # a full disk: this chunk is lost, the pane goes on
                size = os.fstat(fd).st_size
    finally:
        os.close(fd)


def main(args: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if args is None else args)
    if len(argv) != 2 or not argv[1].isdigit() or int(argv[1]) < 1:
        print("usage: logcap LOG LIMIT", file=sys.stderr)
        return 2
    try:
        return run(argv[0], int(argv[1]))
    except OSError as exc:
        print(f"logcap: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
