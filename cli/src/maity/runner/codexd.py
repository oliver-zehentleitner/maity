"""A Codex placement's app-server daemon, stopped before each start (card tsk-n6sajs3gyh8h).

Codex 0.171 runs a managed app-server daemon per CODEX_HOME, detached from the pane's process
group, so the TERM a stop sends to that group (Tmux.terminate) does not reach it. It outlives
the session and a placement restart, and the next TUI talks to it. The daemon keeps the
environment of the start that made it, and with it a TMPDIR leaf the runner removes at the next
start, so every sandboxed command fails. The runner stops it at every Codex start, before the
old leaf is removed and before the new session starts.

The stop is `codex app-server daemon stop` with that CODEX_HOME, as the agents' user, on every
target. A stop that fails, times out or cannot run is logged, never refused: the start goes on,
and the next start tries again. Nothing is signalled by the runner: a fallback by signal is
left to slice 2, where it uses an identity Codex records, checked with a pidfd before any
signal (the review of #2175).
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from .asuser import AsUser, present

# The check that the codex-home is there, on the agents' side.
CHECK_TIMEOUT = 5.0
# `codex app-server daemon stop`: a daemon that has not stopped within this is left running,
# and the start goes on.
STOP_TIMEOUT = 15.0
# The most the stop adds to a start: the check and the stop share it, the stop getting what
# the check left (never below MIN_STOP).
DEADLINE = CHECK_TIMEOUT + STOP_TIMEOUT
MIN_STOP = 1.0
STOP = ("app-server", "daemon", "stop")


def stop_argv(binary: str, home: Path, agents_home: Path, agent_path: str) -> list[str]:
    """The stop command with an environment of only HOME, PATH and CODEX_HOME: never the
    runner's own TMPDIR or CODEX_HOME, which the direct layout would otherwise pass on."""
    return ["env", "-i", f"HOME={agents_home}", f"PATH={agent_path}", f"CODEX_HOME={home}",
            binary, *STOP]  # fmt: skip


def check_home(as_user: AsUser, home: Path, timeout: float) -> bool:
    """Whether the codex-home is a directory: a stat on the runner's own side, `test -d` within
    `timeout` elsewhere (AsUser.exists takes no timeout). OSError when it cannot be told,
    subprocess.TimeoutExpired when the agents' side does not answer in time."""
    if as_user.direct:
        return present(home, "-d")
    done = as_user.run(["test", "-d", str(home)], timeout=timeout)
    if done.returncode not in (0, 1):  # `test`'s own error, or ssh's unreachable 255
        raise OSError(f"exit {done.returncode}")
    return done.returncode == 0


def stop_codex_daemon(
    as_user: AsUser,
    binary: str,
    home: Path,
    agents_home: Path,
    agent_path: str,
    log: Callable[[str], None],
) -> None:
    """Stop the Codex app-server daemon that holds `home`, before a start, within DEADLINE. A
    home that is not there yet has no daemon to stop; a home that cannot be checked is not
    stopped. A stop that exits non-zero, does not answer in time or cannot run is logged. One
    log line for anything but a clean stop; nothing raises."""
    began = time.monotonic()
    try:
        there = check_home(as_user, home, CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        log("the codex-home cannot be checked (timeout); "
            "no Codex app-server daemon stopped, the start goes on")  # fmt: skip
        return
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"the codex-home cannot be checked ({type(exc).__name__}); "
            "no Codex app-server daemon stopped, the start goes on")  # fmt: skip
        return
    if not there:
        log("no codex-home yet, so no Codex app-server daemon to stop")
        return
    timeout = max(MIN_STOP, DEADLINE - (time.monotonic() - began))
    try:
        done = as_user.run(stop_argv(binary, home, agents_home, agent_path), timeout=timeout)
    except subprocess.TimeoutExpired:
        failed = f"did not answer within {timeout:.0f} s"
    except (OSError, subprocess.SubprocessError) as exc:
        failed = f"could not run ({type(exc).__name__})"
    else:
        if done.returncode == 0:
            return
        failed = f"exited {done.returncode}"
    log(f"`codex app-server daemon stop` {failed}; the start goes on")
