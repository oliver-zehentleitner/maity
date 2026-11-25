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
before this stop existed.

Before that stop, Codex's updater loop is ended (slice 2, `end_updater`): only the process
Codex records for it in this home, opened as a pidfd and shown to be that loop before a TERM,
then waited for. The runner signals no other process. A closed placement gets the same stop
before its scratch goes (Supervisor._clear_scratch).
"""

from __future__ import annotations

import json
import os
import select
import signal
import stat
import subprocess
import sys
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


# --- the updater loop (slice 2) ---------------------------------------------------------------
#
# `daemon stop` ends the app-server but not the `app-server daemon pid-update-loop` that comes
# with it, Codex's package updater (ops' measurement on 0.171.0 and 0.172.0: alive 120 s after
# the stop, ended by TERM within 2 s). At a package update it starts a replacement app-server
# itself, with the environment of the start that made the loop. So it is ended first, then the
# daemon: never by a pattern, only by the pid Codex records for it in this home, and only once
# the process behind that pid is shown to be that loop.

# Codex's record of the loop: `{"pid": N, "processIdentity": {"bootId": "…", "startTicks": N}}`.
UPDATER_DIR = "app-server-daemon"
UPDATER_PID = "daemon-updater.pid"
UPDATER_ARGV = ("app-server", "daemon", "pid-update-loop")
PID_FILE_MAX = 4096
# How long `end_updater` waits for the loop to exit after its TERM (ops: within 2 s), so the
# daemon stop and a close's removal run only once it is gone.
UPDATER_WAIT = 3.0
# What `end_updater` says, one token: the loop ended; no record of one; the recorded process
# is gone; the process behind the pid is not that loop; it got its TERM but had not exited
# within the wait; the record or the process could not be read; no pidfd here (not Linux).
UPDATER_TOKENS = (
    "stopped", "absent", "gone", "mismatch", "running", "unreadable", "unsupported",
)  # fmt: skip
QUIET = ("stopped", "absent", "gone")  # nothing to say in the log


def _record(raw: bytes) -> tuple[int, str, int] | None:
    """The pid, boot id and start ticks of Codex's record of the loop, or None."""
    if len(raw) > PID_FILE_MAX:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    identity = data.get("processIdentity") if isinstance(data, dict) else None
    if not isinstance(identity, dict):
        return None
    pid, boot, ticks = data.get("pid"), identity.get("bootId"), identity.get("startTicks")
    if type(pid) is not int or type(ticks) is not int or not isinstance(boot, str):
        return None
    if pid <= 1 or ticks < 0 or not boot:
        return None
    return pid, boot, ticks


def _read_record(root: Path, home: Path) -> tuple[int, str, int] | str:
    """Codex's record of the loop in `home`, reached from `root` one directory at a time with
    no link followed at any step (the root itself included), as `(pid, boot id, start ticks)`,
    or the token for why there is none. A home not plainly below `root` is `unreadable`."""
    parts = below(root, home)
    if parts is None:
        return "unreadable"
    flags = os.O_RDONLY | os.O_NOFOLLOW
    opened: list[int] = []
    try:
        opened.append(os.open(root, flags | os.O_DIRECTORY))
        for part in (*parts, UPDATER_DIR):
            opened.append(os.open(part, flags | os.O_DIRECTORY, dir_fd=opened[-1]))
        fd = os.open(UPDATER_PID, flags | os.O_NONBLOCK, dir_fd=opened[-1])
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return "unreadable"
            raw = os.read(fd, PID_FILE_MAX + 1)
        finally:
            os.close(fd)
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unreadable"
    finally:
        for fd in opened:
            os.close(fd)
    record = _record(raw)
    return "unreadable" if record is None else record


def _is_updater(pid: int, home: Path, boot: str, ticks: int, proc: Path) -> bool | str:
    """Whether the process `pid` is the loop Codex recorded for `home`: this boot, its start
    ticks (field 22 of `stat`), all four of its uids this user's, the loop's argv at the end
    of a cmdline with a program before it, and CODEX_HOME in its environment equal to `home`.
    `"gone"` for a process that has exited and is not reaped yet (a zombie has no cmdline).
    Raises OSError when /proc cannot say."""
    if (proc / "sys" / "kernel" / "random" / "boot_id").read_text().strip() != boot:
        return False
    base = proc / str(pid)
    text = (base / "stat").read_text()
    fields = text[text.rindex(")") + 2 :].split()  # field 3 onward; the name may hold spaces
    if fields[0] in ("Z", "X"):  # field 3, the state: exited
        return "gone"
    if int(fields[19]) != ticks:  # field 22
        return False
    uids = [line.split()[1:] for line in (base / "status").read_text().splitlines()
            if line.startswith("Uid:")]  # fmt: skip
    if len(uids) != 1 or len(uids[0]) != 4 or any(int(u) != os.getuid() for u in uids[0]):
        return False
    raw = (base / "cmdline").read_bytes()
    argv = (raw[:-1] if raw.endswith(b"\0") else raw).split(b"\0")
    if len(argv) < 4 or tuple(p.decode("utf-8", "replace") for p in argv[-3:]) != UPDATER_ARGV:
        return False
    environ = (base / "environ").read_bytes().split(b"\0")
    return f"CODEX_HOME={home}".encode() in environ


def _exited(pidfd: int, wait: float) -> bool:
    """Whether the process behind `pidfd` exits within `wait` seconds: a pidfd turns readable
    when its process exits, for a process that is not our child too."""
    ready, _, _ = select.select([pidfd], [], [], max(wait, 0.0))
    return bool(ready)


def end_updater(
    root: Path, home: Path, wait: float = UPDATER_WAIT, proc: Path = Path("/proc")
) -> str:
    """End the updater loop Codex recorded in `home` (below `root`), run as the loop's own
    user, and say how it went (UPDATER_TOKENS). The pid is opened as a pidfd first, then
    checked (`_is_updater`), then the pidfd is signalled: 0 to show the checked process is
    still the one opened, so no reused pid can be hit, then TERM, and then it waits up to `wait`
    for the process to exit (`running` if it has not). Never KILL, never a pattern, nothing
    outside `home`."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return "unsupported"
    record = _read_record(root, home)
    if isinstance(record, str):
        return record
    pid, boot, ticks = record
    try:
        pidfd = os.pidfd_open(pid)
    except ProcessLookupError:
        return "gone"
    except OSError:
        return "unreadable"
    try:
        verdict = _is_updater(pid, home, boot, ticks, proc)
        if verdict == "gone":
            return "gone"
        if verdict is not True:
            return "mismatch"
        signal.pidfd_send_signal(pidfd, 0)
        signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        return "stopped" if _exited(pidfd, wait) else "running"
    except ProcessLookupError:
        return "gone"
    except (OSError, ValueError, IndexError):
        return "unreadable"
    finally:
        os.close(pidfd)


def main(args: Sequence[str] | None = None) -> int:
    """`end-updater <root> <home> [<wait>]`, as the agents' user (`maity runner codexd`):
    print one token of UPDATER_TOKENS. Exit 2 on other arguments."""
    words = list(sys.argv[1:] if args is None else args)
    usage = "usage: end-updater <absolute root> <absolute codex-home> [<wait seconds>]"
    if len(words) not in (3, 4) or words[0] != "end-updater":
        print(usage, file=sys.stderr)
        return 2
    root, home = Path(words[1]), Path(words[2])
    try:
        wait = float(words[3]) if len(words) == 4 else UPDATER_WAIT
    except ValueError:
        wait = -1.0
    if not root.is_absolute() or not home.is_absolute() or not 0 <= wait <= DEADLINE:
        print(usage, file=sys.stderr)
        return 2
    print(end_updater(root, home, wait))
    return 0


def _end_updater(as_user: AsUser, root: Path, home: Path, timeout: float) -> str:
    """`end_updater` for `home` as the agents' user, waiting at most what `timeout` leaves
    after the checks: in this process where that is the runner's own user, else through the
    runner's module on their side, with its PATH (`module_env`). An answer that is no token,
    or no answer, is `unreadable`."""
    wait = max(min(UPDATER_WAIT, timeout - 1.0), 0.0)
    if as_user.direct:
        return end_updater(root, home, wait)
    argv = [*as_user.runner_module("codexd"), "end-updater", str(root), str(home), f"{wait:g}"]
    done = as_user.run(argv, env=as_user.module_env(), timeout=timeout)
    token = done.stdout.strip()
    return token if done.returncode == 0 and token in UPDATER_TOKENS else "unreadable"


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
    then: str = "the start goes on",
) -> None:
    """Stop the Codex app-server daemon that holds `home`, before a start, within DEADLINE.
    `then` ends a log line that says something was not stopped (`the close goes on` when the
    placement is closed).
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
        log(f"the codex-home is not below its root; no Codex app-server daemon stopped, {then}")
        return
    began = time.monotonic()
    try:
        kind = check_home(as_user, root, parts, CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        log(f"the codex-home cannot be checked (timeout); no Codex app-server daemon stopped, "
            f"{then}")  # fmt: skip
        return
    except (OSError, subprocess.SubprocessError) as exc:
        log(f"the codex-home cannot be checked ({type(exc).__name__}); "
            f"no Codex app-server daemon stopped, {then}")  # fmt: skip
        return
    if kind == "absent":
        log("no codex-home yet, so no Codex app-server daemon to stop")
        return
    if kind != "dir":
        log(f"the codex-home is a link (or not a directory); "
            f"no Codex app-server daemon stopped, {then}")  # fmt: skip
        return
    left = DEADLINE - (time.monotonic() - began)
    if left <= 0:
        log(f"the codex-home check used the whole deadline; "
            f"no Codex app-server daemon stopped, {then}")  # fmt: skip
        return
    # The updater loop first, waited for until it has exited: stopped after the daemon, or
    # still running at the stop, it could start a replacement between.
    try:
        ended = _end_updater(as_user, root, home, min(left, CHECK_TIMEOUT))
    except (OSError, subprocess.SubprocessError):  # a timeout included
        ended = "unreadable"
    if ended not in QUIET:
        log(f"the Codex updater loop was not ended ({ended}); the daemon stop goes on")
    left = DEADLINE - (time.monotonic() - began)
    if left <= 0:
        log(f"the updater step used the whole deadline; "
            f"no Codex app-server daemon stopped, {then}")  # fmt: skip
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
    log(f"`codex app-server daemon stop` {failed}; {then}")


if __name__ == "__main__":
    raise SystemExit(main())
