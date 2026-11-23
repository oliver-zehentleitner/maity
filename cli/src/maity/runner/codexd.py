"""A Codex placement's app-server daemon, stopped before each start (card tsk-n6sajs3gyh8h).

Codex 0.171 runs a managed app-server daemon per CODEX_HOME, detached from the pane's process
group, so the TERM a stop sends to that group (Tmux.terminate) does not reach it. It outlives
the session and a placement restart, and the next TUI talks to it. The daemon keeps the
environment of the start that made it, and with it a TMPDIR leaf the runner removes at the next
start, so every sandboxed command fails. The runner stops it at every Codex start, before the
old leaf is removed and before the new session starts.

The stop is `codex app-server daemon stop` with that CODEX_HOME, as the agents' user. Where it
fails on this host, the processes of the agents' uid that name that CODEX_HOME are ended by
signal (`stop_by_home`): in the runner's own process where the agents are its own user, through
`python -I -m maity.runner.codexd stop --home HOME` as the agents' user otherwise, which prints
its answer as one JSON line. An ssh host gets the stop command only. A stop that fails is
logged, never refused: the next start tries again.

Imports only the standard library at run time: the module runs with `-I` on the agents' side.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .asuser import AsUser

# `codex app-server daemon stop`: a daemon that has not stopped within this is left to the
# fallback, and the start goes on.
STOP_TIMEOUT = 15.0
# The fallback: from SIGTERM to SIGKILL for a process that names the home and is still there.
GRACE = 5.0
# How often the fallback looks again during the grace.
POLL = 0.1
# The fallback run as the agents' user: its grace and two scans of /proc, with room to spare.
FALLBACK_TIMEOUT = GRACE + 10.0
STOP = ("app-server", "daemon", "stop")
UNSUPPORTED = 3  # the module's exit code where there is no /proc to read
_KEY = b"CODEX_HOME="


class Unsupported(OSError):
    """No /proc here (not Linux): the fallback cannot find the processes."""


def stop_argv(binary: str, home: Path, agents_home: Path, agent_path: str) -> list[str]:
    """The stop command with an environment of only HOME, PATH and CODEX_HOME: never the
    runner's own TMPDIR or CODEX_HOME, which the direct layout would otherwise pass on."""
    return ["env", "-i", f"HOME={agents_home}", f"PATH={agent_path}", f"CODEX_HOME={home}",
            binary, *STOP]  # fmt: skip


def stop_codex_daemon(
    as_user: AsUser,
    binary: str,
    home: Path,
    agents_home: Path,
    agent_path: str,
    log: Callable[[str], None],
    grace: float | None = None,
) -> None:
    """Stop the Codex app-server daemon that holds `home`, before a start. A home that is not
    there yet has no daemon to stop. A stop that exits non-zero, does not answer within
    STOP_TIMEOUT or cannot run is followed on this host by the fallback (`stop_by_home`); on an
    ssh host it is only logged. One log line for anything but a clean stop; nothing raises."""
    try:
        there = as_user.exists(home, "-d")
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"the codex-home cannot be checked ({type(exc).__name__}); "
            "no Codex app-server daemon stopped, the start goes on")  # fmt: skip
        return
    if not there:
        log("no codex-home yet, so no Codex app-server daemon to stop")
        return
    try:
        done = as_user.run(stop_argv(binary, home, agents_home, agent_path), timeout=STOP_TIMEOUT)
    except subprocess.TimeoutExpired:
        failed = f"did not answer within {STOP_TIMEOUT:.0f} s"
    except (OSError, subprocess.SubprocessError) as exc:
        failed = f"could not run ({type(exc).__name__})"
    else:
        if done.returncode == 0:
            return
        failed = f"exited {done.returncode}"
    said = f"`codex app-server daemon stop` {failed}"
    if not as_user.here:
        log(f"{said}; no fallback on an ssh host, the start goes on")
        return
    log(f"{said}; {_fallback(as_user, home, grace)}; the start goes on")


def _fallback(as_user: AsUser, home: Path, grace: float | None) -> str:
    """`stop_by_home` as the agents' user on this host, in words for the log."""
    try:
        if as_user.direct:  # the agents are the runner's own user: its own uid's processes
            found = stop_by_home(str(home), grace)
        else:
            argv = [*as_user.runner_module("codexd"), "stop", "--home", str(home)]
            done = as_user.run(argv, timeout=FALLBACK_TIMEOUT)
            if done.returncode == UNSUPPORTED:
                raise Unsupported("no /proc")
            if done.returncode != 0:
                return f"the fallback by CODEX_HOME failed (exit {done.returncode})"
            found = json.loads(done.stdout)
            if not isinstance(found, dict):
                return "the fallback by CODEX_HOME gave no answer"
    except Unsupported:
        return "the fallback by CODEX_HOME is not available on this platform"
    except subprocess.TimeoutExpired:
        return f"the fallback by CODEX_HOME did not answer within {FALLBACK_TIMEOUT:.0f} s"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return f"the fallback by CODEX_HOME failed ({type(exc).__name__})"
    return (f"the fallback by CODEX_HOME sent SIGTERM to {found.get('termed', 0)} and SIGKILL "
            f"to {found.get('killed', 0)} process(es)")  # fmt: skip


# --- the fallback, on the agents' side ------------------------------------------------------


def supported() -> bool:
    """Linux, whose /proc shows each process's owner, environment and command line."""
    return sys.platform.startswith("linux") and os.path.isdir("/proc")


def _pids() -> list[int]:
    return [int(name) for name in os.listdir("/proc") if name.isdigit()]


def _stat(pid: int) -> tuple[int, int] | None:
    """(ppid, pgid) of `pid`, None when it is gone or cannot be read. The command name in
    `/proc/<pid>/stat` may hold spaces and parentheses: the fields are read after the last `)`."""
    try:
        data = Path(f"/proc/{pid}/stat").read_bytes()
    except OSError:
        return None
    fields = data[data.rfind(b")") + 2 :].split()
    if len(fields) < 3 or not fields[1].isdigit() or not fields[2].isdigit():
        return None
    return int(fields[1]), int(fields[2])


def _ancestors() -> set[int]:
    """This process and those above it: never signalled, whatever they name."""
    found: set[int] = set()
    pid = os.getpid()
    while pid > 1 and pid not in found:
        found.add(pid)
        parent = _stat(pid)
        pid = parent[0] if parent is not None else 0
    return found


def _names(pid: int, real: str, uid: int) -> bool:
    """Whether `pid` is a process of `uid` that holds the home `real` (resolved): CODEX_HOME in
    its environment is exactly that home, or one of its arguments is that home or a path in it.
    Another placement's home is never a match, nor a path that only starts with the same
    letters. A process that is gone or cannot be read is no match."""
    try:
        if os.stat(f"/proc/{pid}").st_uid != uid:
            return False
        environ = Path(f"/proc/{pid}/environ").read_bytes()
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:  # gone, or unreadable (PermissionError)
        return False
    values = [os.fsdecode(e[len(_KEY) :]) for e in environ.split(b"\0") if e.startswith(_KEY)]
    if any(os.path.isabs(v) and os.path.realpath(v) == real for v in values):
        return True
    args = [os.fsdecode(a) for a in cmdline.split(b"\0") if a]
    return any(a == real or a.startswith(real + os.sep) for a in args)


def matching(home: str, uid: int, among: set[int] | None = None) -> set[int]:
    """The processes of `uid` that hold `home` (`_names`), of `among` when given; never this
    process or one above it."""
    real = os.path.realpath(home)
    mine = _ancestors()
    pids = _pids() if among is None else sorted(among)
    return {pid for pid in pids if pid not in mine and _names(pid, real, uid)}


def _signal(pids: set[int], sig: int) -> int:
    """Send `sig` to `pids`: to a whole process group only where its leader and every member
    are among `pids`, else to each pid alone; never to this process's own group. A pid that is
    gone, or that may not be signalled, is skipped. How many processes it went to."""
    stats = {pid: _stat(pid) for pid in _pids()}
    groups: dict[int, set[int]] = {}
    for pid, found in stats.items():
        if found is not None:
            groups.setdefault(found[1], set()).add(pid)
    own, sent = os.getpgrp(), 0
    done: set[int] = set()
    for pid in sorted(pids):
        found = stats.get(pid)
        if pid in done or found is None:
            continue
        pgid = found[1]
        members = groups.get(pgid, set())
        whole = pgid in pids and pgid != own and members <= pids
        try:
            if whole:
                os.killpg(pgid, sig)
            else:
                os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            continue
        reached = members if whole else {pid}
        done |= reached
        sent += len(reached)
    return sent


def stop_by_home(home: str, grace: float | None = None, uid: int | None = None) -> dict[str, int]:
    """End the processes of `uid` (this process's own by default) that hold `home`: SIGTERM,
    then after `grace` (GRACE) SIGKILL to those still there and still holding it, so a pid
    reused meanwhile is left alone. Unsupported where there is no /proc."""
    if not supported():
        raise Unsupported("no /proc on this platform")
    uid = os.getuid() if uid is None else uid
    wait = GRACE if grace is None else grace
    found = matching(home, uid)
    termed = _signal(found, signal.SIGTERM) if found else 0
    left, deadline = found, time.monotonic() + wait
    while left and time.monotonic() < deadline:
        time.sleep(POLL)
        left = matching(home, uid, among=left)
    killed = _signal(left, signal.SIGKILL) if left else 0
    return {"termed": termed, "killed": killed}


def main(argv: Sequence[str] | None = None) -> int:
    """`stop --home HOME`: one JSON line with what was signalled; UNSUPPORTED without /proc."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3 or args[0] != "stop" or args[1] != "--home" or not args[2]:
        print("usage: codexd stop --home HOME", file=sys.stderr)
        return 2
    try:
        answer = stop_by_home(args[2])
    except Unsupported as exc:
        print(f"codexd: {exc}", file=sys.stderr)
        return UNSUPPORTED
    except OSError as exc:
        print(f"codexd: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    sys.exit(main())
