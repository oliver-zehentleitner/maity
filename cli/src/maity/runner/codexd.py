"""A Codex placement's app-server daemon, stopped before each start (card tsk-n6sajs3gyh8h).

Codex 0.171 runs a managed app-server daemon per CODEX_HOME, detached from the pane's process
group, so the TERM a stop sends to that group (Tmux.terminate) does not reach it. It outlives
the session and a placement restart, and the next TUI talks to it. The daemon keeps the
environment of the start that made it, and with it a TMPDIR leaf the runner removes at the next
start, so every sandboxed command fails. The runner stops it at every Codex start, before the
old leaf is removed and before the new session starts.

The stop is `codex app-server daemon stop` with that CODEX_HOME, as the agents' user, on every
target, within one deadline shared with the check that the home and every directory on the way
to it from the runner's own root are directories and no links. A stop that fails, times out,
cannot run or is skipped is logged, never refused: the start goes on, and the next start tries
again. Such a stop leaves the old daemon running, so the new session may still reach it, as
before this stop existed. Nothing is signalled by the runner: a fallback by signal is left to
slice 2, where it uses an identity Codex records, checked with a pidfd before any signal (the
review of #2175).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .asuser import AsUser

# The check of the codex-home, as the agents' user.
CHECK_TIMEOUT = 5.0
# `codex app-server daemon stop`: a daemon that has not stopped within this is left running,
# and the start goes on.
STOP_TIMEOUT = 15.0
# The most the stop waits for at a start: the check and the stop share it, the stop getting
# what the check left, and no stop at all once the check has used it up.
DEADLINE = CHECK_TIMEOUT + STOP_TIMEOUT
STOP = ("app-server", "daemon", "stop")


def stop_argv(binary: str, home: Path, agents_home: Path, agent_path: str) -> list[str]:
    """The stop command with an environment of only HOME, PATH and CODEX_HOME: never the
    runner's own TMPDIR or CODEX_HOME, which the direct layout would otherwise pass on."""
    return ["env", "-i", f"HOME={agents_home}", f"PATH={agent_path}", f"CODEX_HOME={home}",
            binary, *STOP]  # fmt: skip


# What the codex-home is, said by one token on stdout. $1 is the root, the rest the home's
# components below it. The root first, then each component walked from it, each told a link
# before it is entered. A missing root is `absent`: nothing below it, so no daemon's home.
_WHAT = (
    'step() { if [ -L "$1" ]; then echo link; exit 0; fi; '
    'if [ ! -d "$1" ]; then if [ -e "$1" ]; then echo other; else echo absent; fi; exit 0; fi; }; '
    'p=$1; shift; step "$p"; '
    'for c; do p=$p/$c; step "$p"; done; echo dir'
)
KINDS = ("dir", "absent", "link", "other")


def below(root: Path, home: Path) -> tuple[str, ...] | None:
    """The components of `home` below `root`, or None when `home` is not plainly below it
    (a relative root, elsewhere, `root` itself, or a `.` or `..` on the way)."""
    if not root.is_absolute():
        return None
    try:
        parts = home.relative_to(root).parts
    except ValueError:
        return None
    if not parts or any(part in (".", "..") for part in parts):
        return None
    return parts


def check_home(as_user: AsUser, root: Path, parts: Sequence[str], timeout: float) -> str:
    """What the codex-home `root/parts…` is, as the agents' user: `dir`, `absent` (the root or
    something on the way missing), `link` (a link at the root, the home or any directory
    between them) or `other` (something on the way that is neither a link nor a directory).
    One `sh` within `timeout` on every layout, the runner's own included. The answer is the
    token the script prints, never its exit code alone, so a sudo or ssh that fails is never
    read as an absent home: a non-zero exit, no token or another one is an OSError.
    subprocess.TimeoutExpired when it does not answer in time."""
    done = as_user.run(["sh", "-c", _WHAT, "sh", str(root), *parts], timeout=timeout)
    kind = done.stdout.strip()
    if done.returncode != 0 or kind not in KINDS:
        raise OSError(f"exit {done.returncode}, no answer" if not kind else
                      f"exit {done.returncode}, an unknown answer")  # fmt: skip
    return kind


def stop_codex_daemon(
    as_user: AsUser,
    binary: str,
    home: Path,
    root: Path,
    agents_home: Path,
    agent_path: str,
    log: Callable[[str], None],
) -> None:
    """Stop the Codex app-server daemon that holds `home`, before a start, within DEADLINE.
    `root` is the directory the runner makes and checks itself that the home lies below. A
    home that is not there yet has no daemon to stop. A home not below an absolute `root`, or
    one that is a link, has a link on the way from `root` (`root` itself included), or is no
    directory, is not stopped; the launch
    refuses such a home later. Nor is a home that cannot be checked, or whose check used the
    whole deadline. A stop that exits non-zero, does not answer in time or cannot run is
    logged. A stop that fails or is skipped leaves the old daemon running, and the new session
    may still reach it. One log line for anything but a clean stop; nothing raises. The check
    and the stop are not atomic."""
    parts = below(root, home)
    if parts is None:
        log("the codex-home is not below its root; "
            "no Codex app-server daemon stopped, the start goes on")  # fmt: skip
        return
    began = time.monotonic()
    try:
        kind = check_home(as_user, root, parts, CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        log("the codex-home cannot be checked (timeout); "
            "no Codex app-server daemon stopped, the start goes on")  # fmt: skip
        return
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"the codex-home cannot be checked ({type(exc).__name__}); "
            "no Codex app-server daemon stopped, the start goes on")  # fmt: skip
        return
    if kind == "absent":
        log("no codex-home yet, so no Codex app-server daemon to stop")
        return
    if kind != "dir":
        log("the codex-home is a link (or not a directory); "
            "no Codex app-server daemon stopped, the start goes on")  # fmt: skip
        return
    left = DEADLINE - (time.monotonic() - began)
    if left <= 0:
        log("the codex-home check used the whole deadline; "
            "no Codex app-server daemon stopped, the start goes on")  # fmt: skip
        return
    try:
        done = as_user.run(stop_argv(binary, home, agents_home, agent_path), timeout=left)
    except subprocess.TimeoutExpired:
        failed = f"did not answer within {left:.0f} s"
    except (OSError, subprocess.SubprocessError) as exc:
        failed = f"could not run ({type(exc).__name__})"
    else:
        if done.returncode == 0:
            return
        failed = f"exited {done.returncode}"
    log(f"`codex app-server daemon stop` {failed}; the start goes on")
