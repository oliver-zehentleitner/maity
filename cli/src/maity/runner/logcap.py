"""A placement's pane log, held to `limits.log_keep_bytes` (runner design §15.7).

tmux's `pipe-pane` hands every byte an agent's pane shows to this module, started on the
agents' side (`python -I -m maity.runner.logcap LOG LIMIT`, `maity runner logcap LOG LIMIT` on
an ssh host). It appends to LOG; when the next chunk would take the file past LIMIT bytes,
the file is cut to its newest LIMIT / 2 bytes first, through a copy renamed over it, so the
log keeps the latest output. A write that fails (a full disk) drops that chunk and the module
reads on: the pane never waits on its log.

This module is the log's only writer. The log lies on the agents' side, though, where they can
write it too: so before every write, and once more when the pane ends, the module takes the
file as it is, not its own count of what it wrote. A file at LOG that is no longer the one it
opened (renamed, replaced) is opened anew, never through a link; the file's real size decides
the cut. Bytes another writer appends count at the module's next write, so the log holds at
most LIMIT bytes after each of the module's writes and when it ends. Only the standard
library: the module runs with `-I`.
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


def _same(path: str, fd: int) -> bool:
    """Whether `path` is still the file open at `fd`, not a link or another file put there."""
    try:
        here = os.stat(path, follow_symlinks=False)
    except OSError:
        return False
    there = os.fstat(fd)
    return (here.st_dev, here.st_ino) == (there.st_dev, there.st_ino)


def _hold(path: str, fd: int, limit: int, incoming: int) -> int:
    """The log's descriptor, with room for `incoming` more bytes within `limit`: the file at
    `path` as it is now, its real size, whoever else wrote to it."""
    if not _same(path, fd):
        fresh, _ = _open(path)
        os.close(fd)
        fd = fresh
    if os.fstat(fd).st_size + incoming > limit:
        fd, _ = _cut(path, fd, min(limit // 2, limit - incoming))
    return fd


def run(path: str, limit: int, source: int = 0) -> int:
    """Copy `source` into the log at `path` until it ends, holding the log to `limit`."""
    fd, _ = _open(path)
    try:
        while True:
            chunk = os.read(source, CHUNK)[-limit:]
            try:
                fd = _hold(path, fd, limit, len(chunk))
                if not chunk:  # the pane ended: what others wrote since is cut too
                    return 0
                os.write(fd, chunk)
            except OSError:  # a full disk: this chunk is lost, the pane goes on
                if not chunk:
                    return 0
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
