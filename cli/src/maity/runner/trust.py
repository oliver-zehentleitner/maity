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
- Claude Code saves the file holding the directory `<file>.lock` (taken with `mkdir`, given up
  as stale after 10 s), and re-reads and merges `projects` under it. This module takes the same
  lock, so a running session neither loses this entry nor has its own write lost.

Nothing else in the file changes: no other project, no other key of this one. A file that is
not a JSON object is left as it is. The runner runs this in its own process when the agents
are its own user; through sudo or on an ssh host it starts this module there (`python -I -m
maity.runner.trust HOME CLONE`, `maity runner trust HOME CLONE`).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

KEY = "hasTrustDialogAccepted"
STALE_SECONDS = 10.0  # proper-lockfile's default, which Claude Code's config lock keeps
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
    lock = Path(f"{path}.lock")
    deadline = now() + WAIT_SECONDS
    while True:
        try:
            lock.mkdir()
            return lock
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > STALE_SECONDS:
                    lock.rmdir()  # a holder refreshes it every 5 s; this one is gone
                    continue
            except OSError:
                continue  # given up in between
        if now() > deadline:
            raise TrustError(f"{lock} is held by another process")
        sleep(0.1)


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
    lock = _lock(path, now, sleep)
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
            os.replace(temp, target)
        except BaseException:
            Path(temp).unlink(missing_ok=True)
            raise
        return True
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


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
