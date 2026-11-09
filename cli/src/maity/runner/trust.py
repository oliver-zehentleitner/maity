"""Claude Code's folder trust for one clone, recorded where the agents run (cli/context/runner.md).

An interactive Claude Code asks "Is this a project you created or one you trust?" on its first
start in a folder and waits for a key, so a fresh clone's agent never runs `maity resume`. The
owner's placement is the trust decision; the runner records it before the session starts, the
way Claude Code records an accepted dialog: `projects[<clone>].hasTrustDialogAccepted: true` in
its global configuration file. Checked against Claude Code 2.1.319:

- The file is `~/.claude/.config.json` when that is a non-empty file (or an empty one while
  `~/.claude.json` is missing), otherwise `~/.claude.json`. CLAUDE_CONFIG_DIR is not read: the
  runner's sessions start without it.
- The key is the clone's real path: Claude Code looks up its working directory, which the
  kernel gives resolved.
- Claude Code saves the file holding the directory `<file>.lock` (proper-lockfile: taken with
  `mkdir`, its mtime renewed every 5 s, given up as stale after 10 s without renewal), and
  re-reads and merges `projects` under it. This module takes the same lock the same way: it
  renews the mtime while it holds the lock and, right before it replaces the file, checks that
  the mtime is still the one it set. A holder that lost the lock (it was taken over as stale, or
  removed) writes nothing and fails, so neither this entry nor a session's own write is lost.
  Nothing is put inside the lock: a directory left behind must stay removable with `rmdir`, as
  proper-lockfile removes a stale one.

Nothing else in the file changes: no other project, no other key of this one. A file that is
not a JSON object is left as it is. Every failure (such a file, a lock held past WAIT_SECONDS, a
stale lock that cannot be removed, a lost lock, a write that fails) raises TrustError.

The runner runs this in its own process when the agents are its own user; through sudo or on an
ssh host it starts this module there (`python -I -m maity.runner.trust HOME CLONE`, `maity
runner trust HOME CLONE`).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

KEY = "hasTrustDialogAccepted"
STALE_SECONDS = 10.0  # proper-lockfile's default, which Claude Code's config lock keeps
RENEW_SECONDS = STALE_SECONDS / 2  # proper-lockfile's `update`
WAIT_SECONDS = 15.0


class TrustError(OSError):
    pass


def config_file(home: Path) -> Path:
    """The global configuration file an interactive Claude Code started with this HOME reads."""
    legacy, current = home / ".claude" / ".config.json", home / ".claude.json"
    try:
        size = legacy.stat().st_size if legacy.is_file() else None
    except OSError:
        size = None
    if size is not None and (size > 0 or not current.exists()):
        return legacy
    return current


def _lock(path: Path, now: Callable[[], float], sleep: Callable[[float], None]) -> Path:
    """Take `<path>.lock` by `mkdir`. A lock whose mtime is older than STALE_SECONDS is left
    from a holder that is gone and is removed; one that cannot be (a regular file, a directory
    with something in it) fails at once. Every wait honours the deadline."""
    lock = Path(f"{path}.lock")
    deadline = now() + WAIT_SECONDS
    while True:
        try:
            lock.mkdir()
            return lock
        except FileExistsError:
            pass
        except OSError as exc:
            raise TrustError(f"cannot take {lock}: {exc.strerror}") from None
        try:
            stale = time.time() - lock.stat().st_mtime > STALE_SECONDS
            if stale:
                lock.rmdir()
        except FileNotFoundError:
            stale = False  # given up in between: wait as for a held lock, then try again
        except OSError as exc:
            raise TrustError(f"{lock} is stale and cannot be removed: {exc.strerror}") from None
        if now() > deadline:
            raise TrustError(f"{lock} is held by another process")
        if not stale:
            sleep(0.1)


class _Lease:
    """The lock while this process holds it: its mtime renewed every RENEW_SECONDS by a thread,
    as proper-lockfile does, so another process never takes it over as stale while the write
    is slow. Ownership is that mtime: a lock taken over (removed and made again by another
    process) or removed carries another, or none."""

    def __init__(self, lock: Path) -> None:
        self.lock = lock
        self.mutex = threading.Lock()
        self.lost = False
        self.mark = self._touch()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._renew, daemon=True, name="maity-trust-lock")
        self.thread.start()

    def _touch(self) -> int:
        stamp = time.time_ns()
        os.utime(self.lock, ns=(stamp, stamp))
        return os.stat(self.lock).st_mtime_ns

    def _owned(self) -> bool:
        try:
            return os.stat(self.lock).st_mtime_ns == self.mark
        except OSError:
            return False

    def _renew(self) -> None:
        while not self.stop.wait(RENEW_SECONDS):
            with self.mutex:
                if self.lost or not self._owned():
                    self.lost = True
                    return
                try:
                    self.mark = self._touch()
                except OSError:
                    self.lost = True
                    return

    def commit(self, write: Callable[[], None]) -> None:
        """`write` while the lock is still this process's, and the renewal cannot run between
        the check and the write; TrustError when it is not."""
        with self.mutex:
            if self.lost or not self._owned():
                self.lost = True
                raise TrustError(f"lost {self.lock} to another process; nothing written")
            write()

    def release(self) -> None:
        """Remove the lock, only while it is still this process's."""
        self.stop.set()
        self.thread.join()
        with self.mutex:
            if not self.lost and self._owned():
                try:
                    self.lock.rmdir()
                except OSError:
                    pass


def record(
    home: Path,
    clone: Path,
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """Mark `clone` trusted in the Claude Code configuration under `home`; False when it
    already was. Raises TrustError when the file cannot be read as a JSON object or written."""
    path = config_file(home)
    key = os.path.realpath(clone)
    lease = _Lease(_lock(path, now, sleep))
    try:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = "{}"
        try:
            data: Any = json.loads(text)
        except ValueError:
            raise TrustError(f"{path} is not JSON; left as it is") from None
        projects = data.get("projects", {}) if isinstance(data, dict) else None
        entry = projects.get(key, {}) if isinstance(projects, dict) else None
        if not isinstance(projects, dict) or not isinstance(entry, dict):
            raise TrustError(f"{path} is not a Claude Code configuration; left as it is")
        if entry.get(KEY) is True:
            return False
        data["projects"] = {**projects, key: {**entry, KEY: True}}
        target = Path(os.path.realpath(path))  # a linked file stays linked
        mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
        fd, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(temp, mode)
            lease.commit(lambda: os.replace(temp, target))
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
        return True
    finally:
        lease.release()


def main(args: Sequence[str] | None = None) -> int:
    """Exit 0 when the clone is trusted (now or before), 1 when it could not be recorded."""
    argv = list(sys.argv[1:] if args is None else args)
    if len(argv) != 2 or not all(os.path.isabs(a) for a in argv):
        print("usage: trust HOME CLONE (absolute paths)", file=sys.stderr)
        return 2
    try:
        record(Path(argv[0]), Path(argv[1]))
    except OSError as exc:
        print(f"trust: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
