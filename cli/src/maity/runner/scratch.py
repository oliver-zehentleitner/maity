"""A placement's scratch (§15.5): its size, its removal, and the operator's record of each.

The scratch is `<workspaces>/.scratch/<project_id>/<placement id>` (workspace.scratch_of),
made by the supervisor at a start; one in the former `<workspaces>/<project_id>/.scratch/` is
still measured and removed. Nothing in it is kept as unsaved work: the runner removes
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
from pathlib import Path
from typing import Any

from .. import state
from ..stamp import stamp
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
    """The workspaces root of a scratch path, three levels up in either shape
    (`<workspaces>/.scratch/<project>/<id>`, formerly `<workspaces>/<project>/.scratch/<id>`), as
    workspace.scratch_of built it: the place every operation is anchored."""
    return path.parents[2]


def make(path: Path, as_user: AsUser = RUNNER) -> None:
    """The scratch at `path` with `tmp` in it. scratchop.OnTheWay when a directory on the way
    from the workspaces root is a link, or the holder is another user's: nothing is made."""
    as_user.scratch("make", _under(path), path)


def make_holder(root: Path, holder: Path, as_user: AsUser = RUNNER) -> None:
    """The holder of every scratch, `<root>/.scratch`, made 0700 or checked: a real directory
    of the agents' user, reached without following a link. scratchop.OnTheWay when it is not;
    scratchop.Unsupported for an ssh host whose `maity` has no holder op (the former layout)."""
    as_user.scratch("holder", root, holder)


def write_codex_home(
    home: Path, config_text: str, auth_target: Path | None, as_user: AsUser = RUNNER
) -> None:
    """Codex's control files inside `home` (`<scratch>/codex-home`): config.toml and, when the
    operator has a login, the auth.json link. Each is written to a descriptor opened without
    following a link from the workspaces root the scratch lies under, the same anchor
    make/measure/remove use, so a codex-home swapped for a link is refused, never followed out
    of the scratch. scratchop.OnTheWay when codex-home is a link; OSError when it fails
    otherwise."""
    as_user.codex(_under(home.parent), home, config_text, auth_target)


def write_codex_skill(home: Path, payload: str, as_user: AsUser = RUNNER) -> None:
    """The skill's document (skillop.payload) as `skills/keep-the-why/` in `home`
    (`<scratch>/codex-home`), by skillop.codex_put on the agents' side, anchored at the
    workspaces root as write_codex_home is. OSError (scratchop.OnTheWay for a link on the way)
    when it fails."""
    as_user.skill_codex(_under(home.parent), home, payload)


def clear_codex_skill(home: Path, as_user: AsUser = RUNNER) -> None:
    """`skills/keep-the-why/` in `home` removed (skillop.codex_clear), anchored as
    write_codex_skill is."""
    as_user.skill_codex_clear(_under(home.parent), home)


def tmp_make(path: Path, as_user: AsUser = RUNNER) -> None:
    """The agy scratch at `path` under `/tmp`, with `tmp` in it, owned by the user the agents
    run as, under a per-user parent owned 0700 by that user (scratchop.tmp_make). scratchop.OnTheWay
    when a level is a link, a directory another user holds, or a leaf that already exists; OSError
    otherwise."""
    as_user.tmp_scratch("make", path)


def tmp_make_parent(path: Path, as_user: AsUser = RUNNER) -> None:
    """The per-user agy scratch parent at `path` (`<root>/maity-scratch-<uid>`) created or
    adopted 0700, owned by the agents' user (scratchop.tmp_parent_make). The runner makes it
    before a non-agy placement that only hides it starts, so the sandbox's deny path is a real
    directory. scratchop.OnTheWay when it is a link or a directory another user holds; OSError
    otherwise."""
    as_user.tmp_scratch("parent", path)


def tmp_measure(path: Path, as_user: AsUser = RUNNER) -> int | None:
    """The bytes under the agy scratch at `path`; None when it is missing, reached through a
    link or a foreign-owned parent, or cannot be measured in time."""
    try:
        answer = as_user.tmp_scratch("size", path)
    except (OSError, subprocess.SubprocessError):
        return None
    found = answer.get("bytes")
    return found if isinstance(found, int) and not isinstance(found, bool) else None


def tmp_remove(path: Path, as_user: AsUser = RUNNER) -> int | None:
    """Remove the agy scratch at `path` under `/tmp` and return its size before; None when
    there was none (scratchop.tmp_remove). scratchop.OnTheWay when the parent is a link or
    foreign-owned; OSError when it cannot be removed."""
    answer = as_user.tmp_scratch("remove", path)
    if answer.get("result") == "missing":
        return None
    found = answer.get("bytes")
    return found if isinstance(found, int) and not isinstance(found, bool) else 0


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
        "at": stamp(at),
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
