"""A Codex placement's app-server daemon, stopped before each start (card tsk-n6sajs3gyh8h).

Codex 0.171 runs a managed app-server daemon per CODEX_HOME, detached from the pane's process
group, so the TERM a stop sends to that group (Tmux.terminate) does not reach it. It outlives
the session and a placement restart, and the next TUI talks to it. The daemon keeps the
environment of the start that made it, and with it a TMPDIR leaf the runner removes at the next
start, so every sandboxed command fails. The runner stops it at every Codex start, before the
old leaf is removed and before the new session starts.

The stop is `codex app-server daemon stop` with that CODEX_HOME, as the agents' user, on every
target, within one deadline shared with the check that the home is a directory and no link.
A stop that fails, times out, cannot run or is skipped is logged, never refused: the start goes
on, and the next start tries again. Such a stop leaves the old daemon running, so the new
session may still reach it, as before this stop existed. Nothing is signalled by the runner: a
fallback by signal is left to slice 2, where it uses an identity Codex records, checked with a
pidfd before any signal (the review of #2175).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from .asuser import AsUser

# The check that the codex-home is there, as the agents' user.
CHECK_TIMEOUT = 5.0
# `codex app-server daemon stop`: a daemon that has not stopped within this is left running,
# and the start goes on.
STOP_TIMEOUT = 15.0
# The most the stop adds to a start: the check and the stop share it, the stop getting what
# the check left, and no stop at all once the check has used it up.
DEADLINE = CHECK_TIMEOUT + STOP_TIMEOUT
STOP = ("app-server", "daemon", "stop")


def stop_argv(binary: str, home: Path, agents_home: Path, agent_path: str) -> list[str]:
    """The stop command with an environment of only HOME, PATH and CODEX_HOME: never the
    runner's own TMPDIR or CODEX_HOME, which the direct layout would otherwise pass on."""
    return ["env", "-i", f"HOME={agents_home}", f"PATH={agent_path}", f"CODEX_HOME={home}",
            binary, *STOP]  # fmt: skip


# What the codex-home is, said by one token on stdout: a link is told first, never followed.
_WHAT = ('if [ -L "$1" ]; then echo link; elif [ -d "$1" ]; then echo dir; '
         'elif [ -e "$1" ]; then echo other; else echo absent; fi')  # fmt: skip
KINDS = ("dir", "absent", "link", "other")


def check_home(as_user: AsUser, home: Path, timeout: float) -> str:
    """What the codex-home is, as the agents' user: `dir`, `absent`, `link` (a link, to
    anywhere) or `other` (neither a link nor a directory). One `sh` within `timeout` on every
    layout, the runner's own included, since a stat in this process cannot be bounded (a
    stuck mount). The answer is the token the script prints, never its exit code alone, so a
    sudo or ssh that fails is never read as an absent home: a non-zero exit, no token or
    another one is an OSError. subprocess.TimeoutExpired when it does not answer in time."""
    done = as_user.run(["sh", "-c", _WHAT, "sh", str(home)], timeout=timeout)
    kind = done.stdout.strip()
    if done.returncode != 0 or kind not in KINDS:
        raise OSError(f"exit {done.returncode}, no answer" if not kind else
                      f"exit {done.returncode}, an unknown answer")  # fmt: skip
    return kind


def stop_codex_daemon(
    as_user: AsUser,
    binary: str,
    home: Path,
    agents_home: Path,
    agent_path: str,
    log: Callable[[str], None],
) -> None:
    """Stop the Codex app-server daemon that holds `home`, before a start, within DEADLINE. A
    home that is not there yet has no daemon to stop. A home that is a link or no directory
    is not stopped: the scratch is the agent's to write, and a link there could point the
    stop at another placement's home or the operator's own; the launch refuses such a home
    later. Nor is a home that cannot be checked, or whose check used the whole deadline. A
    stop that exits non-zero, does not answer in time or cannot run is logged. A stop that
    fails or is skipped leaves the old daemon running, and the new session may still reach
    it. One log line for anything but a clean stop; nothing raises.

    The stop names the home by path to an external binary, so a process of the agents' uid
    could still swap the path for a link between the check and the stop."""
    began = time.monotonic()
    try:
        kind = check_home(as_user, home, CHECK_TIMEOUT)
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
