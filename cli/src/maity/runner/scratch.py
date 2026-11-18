"""A placement's scratch (§15.5): its size, its removal, and the operator's record of each.

The scratch is `<workspaces>/<project_id>/.scratch/<placement id>` (workspace.scratch_of),
made by the supervisor at a start. Nothing in it is kept as unsaved work: the runner removes
it when the hub reads the placement as closed, and `maity runner gc` removes what no placement
of the runner names. Neither its size nor its removal goes to the hub; the operator reads them
with `maity runner status` and in `removed.jsonl` in the runner's state directory.

Everything here runs as the agents' user (AsUser): the scratch is theirs. Making, measuring
and removing it opens every directory from the workspaces root down without following a link
and holds the last one open while it works (scratchop), so no directory on the way, swapped
for a link before or during the operation, leads it anywhere else.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Any

from .. import state
from .asuser import RUNNER, AsUser

REMOVED_FILE = "removed.jsonl"
REMOVED_KEEP = 1000  # the newest lines kept in REMOVED_FILE
SIZE_TIMEOUT = 60.0


def size(path: Path, as_user: AsUser = RUNNER) -> int | None:
    """The bytes under `path` on the agents' side (`du -sb`, without following links); None
    when it is missing or cannot be measured in time."""
    try:
        done = as_user.run(["du", "-sbP", "--", str(path)], timeout=SIZE_TIMEOUT)
    except (subprocess.TimeoutExpired, OSError):
        return None
    if done.returncode != 0:
        return None
    first = done.stdout.split(None, 1)[0] if done.stdout.strip() else ""
    return int(first) if first.isdigit() else None


def _under(path: Path) -> Path:
    """The workspaces root of a scratch path (`<workspaces>/<project>/.scratch/<id>`), as
    workspace.scratch_of built it: the place every operation is anchored."""
    return path.parents[2]


def make(path: Path, as_user: AsUser = RUNNER) -> None:
    """The scratch at `path` with `tmp` in it. scratchop.OnTheWay when a directory on the way
    from the workspaces root is a link: nothing is made through it."""
    as_user.scratch("make", _under(path), path)


def measure(path: Path, as_user: AsUser = RUNNER) -> int | None:
    """The bytes under the scratch at `path`; None when it is missing, reached through a link
    or cannot be measured in time."""
    try:
        answer = as_user.scratch("size", _under(path), path)
    except (OSError, subprocess.SubprocessError):
        return None
    found = answer.get("bytes")
    return found if isinstance(found, int) and not isinstance(found, bool) else None


def remove(path: Path, as_user: AsUser = RUNNER) -> int | None:
    """Remove the scratch at `path` and return its size before; None when there was none.
    Every directory from the workspaces root down is opened without following a link and
    held while it goes (scratchop): scratchop.OnTheWay when one is a link, OSError when it
    cannot be removed."""
    answer = as_user.scratch("remove", _under(path), path)
    if answer.get("result") == "missing":
        return None
    found = answer.get("bytes")
    return found if isinstance(found, int) and not isinstance(found, bool) else 0


def log_removal(
    state_dir: Path, placement: str, path: Path, size_bytes: int | None, why: str,
    at: float | None = None,
) -> dict[str, Any]:  # fmt: skip
    """One line in REMOVED_FILE: when, which placement, the path, its size, why. Only the
    newest REMOVED_KEEP lines stay."""
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() if at is None else at)),
        "placement": placement,
        "path": str(path),
        "size_bytes": size_bytes,
        "why": why,
    }
    lines = removals(state_dir, REMOVED_KEEP - 1)
    text = "".join(json.dumps(e, sort_keys=True) + "\n" for e in [*lines, entry])
    state.write_file(state_dir / REMOVED_FILE, text)
    return entry


def removals(state_dir: Path, last: int) -> list[dict[str, Any]]:
    """The newest `last` entries of REMOVED_FILE, oldest first; a line that is not one is
    left out."""
    try:
        text = (state_dir / REMOVED_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    found: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            found.append(entry)
    return found[-last:] if last > 0 else []
