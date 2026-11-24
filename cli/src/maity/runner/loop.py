"""The supervised loop (runner design §6.2): `python -m maity.runner.loop --spec FILE`.

Runs the harness headless with the start prompt, then waits for the agent's next event with
`maity wait --keep-cursor` (the agent's own credential; no model tokens while idle), lets a
burst settle, and runs the harness again, whose `maity resume` lists the event as unread.

Exit codes the runner maps (§15.7): 20 the agent's credential is revoked
(`agent_credential_revoked`), 21 runs keep ending without progress (`crash_loop`,
`hot_loop`), 22 the harness stopped for its provider's limit (`rate_limited`, with the
harness's own exit code in the spec's `limit.file`), 23 the same after at least one run of
this loop had ended cleanly, which starts the runner's backoff row over, 24 and 25 the
workspace folder in the spec (agy's, §15.5) refused before a run (`workspace_in_use` with
`workspace_not_bare`, `workspace_in_repository`). Which exits mean a
limit is the adapter's `limit` in the spec, and only a signal verified on a real run of that
harness goes there; without one, a limit is an ordinary non-zero exit. A run that ends
within `quick_exit` without the event having been acknowledged counts toward `crash_cap`
within `crash_window`, with the runner's backoff between runs.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, restart, workspace

WAIT_TIMEOUT = 600
SETTLE = 15.0
# After a reaped turn ends, how long the turn's own process group gets to exit on SIGTERM
# before SIGKILL, and how often it is checked.
REAP_GRACE = 5.0
REAP_POLL = 0.1
# The hard bound on one reaped turn: a harness that keeps running while it reports idle or
# waits on a background task never reaches cleanup on its own, so the loop stops and reaps it
# after this long. A turn that runs past it is ended and reaped (EXIT_TURN), not run again,
# and the loop waits for the next event. The spec may lower it with `turn_timeout`.
TURN_TIMEOUT = 3600.0
EXIT_REVOKED = 20
EXIT_HOT_LOOP = 21
EXIT_RATE_LIMITED = 22
EXIT_RATE_LIMITED_AFTER_CLEAN = 23
# The workspace folder refused before a run (workspace.check_folder), by its detail.
EXIT_FOLDER = {"workspace_not_bare": 24, "workspace_in_repository": 25}
# A reaped turn that ran past its bound and was ended (TURN_TIMEOUT). `Loop.turn` neither
# runs it again nor counts it: a turn that long is past `quick_exit`, so a counted retry would
# reset the crash count and never reach the cap. The loop waits for the next event instead.
EXIT_TURN = 26


def check_folder(folder: str) -> None:
    """The supervisor's check before a start (workspace.check_folder), here as the agents'
    user the loop runs as, through the same listing: agy loads what lies in the folder and
    above it, and a run of the agent may have put something there since the last check."""
    workspace.check_folder(workspace.Workspace(Path(folder), "", "", folder=True))


@dataclass
class Loop:
    spec: dict[str, Any]
    run: Callable[[list[str], dict[str, str]], int]
    wait: Callable[[], tuple[int, str, str]]  # (exit code, stdout, stderr)
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    rand: Callable[[], float] = random.random
    crashes: list[float] = field(default_factory=list)
    clean: bool = False  # a run of this loop ended cleanly: a later limit is not "in a row"
    log: Callable[[str], None] = lambda line: print(f"maity loop: {line}", flush=True)
    check: Callable[[str], None] = check_folder

    def policy(self) -> config.Restart:
        return config.Restart(**self.spec["restart"])

    def count(self, started: float, ended: float) -> int | None:
        """One run that made no progress: back off, or stop at the cap (EXIT_HOT_LOOP)."""
        decision = restart.on_exit(self.policy(), self.crashes, started, ended, self.rand)
        self.crashes = decision.crashes
        if decision.crash_loop:
            self.log(f"{len(self.crashes)} runs ended without progress; stopping")
            return EXIT_HOT_LOOP
        if decision.retry_at is not None:
            self.sleep(max(0.0, decision.retry_at - ended))
        return None

    def limited(self, code: int) -> bool:
        """Whether exit `code` is the harness's provider limit, by the adapter's verified
        signal; if so, the harness's own code goes to the spec's file for the runner (no
        reset time: none is read until a real run shows where a harness names it)."""
        limit = self.spec.get("limit") or {}
        if code not in (limit.get("exit_codes") or []):
            return False
        self.log("the harness stopped for its provider's limit")
        try:
            if limit.get("file"):
                with open(limit["file"], "w", encoding="utf-8") as fh:
                    json.dump({"exit_code": code}, fh)
        except OSError as exc:  # still a limit: the runner then reports no exit code
            self.log(f"cannot record the limit's exit code: {exc}")
        return True

    def refused(self) -> int | None:
        """Before every run: the spec's workspace folder as the supervisor checks it before a
        start; its EXIT_FOLDER code when it is refused, with the entries named in the log
        (names only, never what they hold), nothing deleted."""
        folder = self.spec.get("folder")
        if not isinstance(folder, str) or not folder:
            return None
        try:
            self.check(folder)
        except workspace.Refused as refused:
            self.log(f"{refused.reason}/{refused.detail}: {refused.why or ''}; stopping")
            return EXIT_FOLDER.get(refused.detail or "", EXIT_FOLDER["workspace_not_bare"])
        return None

    def turn(self, argv: list[str]) -> int | None:
        """Headless runs until one ends cleanly, each after the folder check (`refused`). A
        non-zero exit counts against the cap and is run again after the backoff, without
        waiting for a new event: the work it was doing is still there. A turn ended at its time
        limit (EXIT_TURN) is the exception: it is not run again and not counted, and the loop
        goes back to waiting for the next event. A clean run does not count, however short: a
        quick answer to an event is progress."""
        while True:
            refused = self.refused()
            if refused is not None:
                return refused
            started = self.now()
            code = self.run(argv, self.spec.get("env") or {})
            if code == 0:
                self.clean = True
                return None
            if code == EXIT_TURN:
                # Ended at its bound and reaped: no retry and no crash count, since a turn that
                # long is past `quick_exit` and would reset the count, so the retries would have
                # no cap. The loop waits for the next event instead.
                self.log("the turn hit its time limit and was ended; waiting for the next event")
                return None
            self.log(f"the run exited {code}")
            if self.limited(code):
                return EXIT_RATE_LIMITED_AFTER_CLEAN if self.clean else EXIT_RATE_LIMITED
            stop = self.count(started, self.now())
            if stop is not None:
                return stop
            argv = self.spec["again"]

    def main(self) -> int:
        stop = self.turn(self.spec["first"])
        if stop is not None:
            return stop
        handed: int | None = None  # the seq of the event the last run was started for
        failures = 0
        while True:
            code, out, err = self.wait()
            if code == 3:
                continue
            if code == 0:
                failures = 0
                seq = _seq(out)
                if handed is not None and seq is not None and seq <= handed:
                    # The run ended without acknowledging its event: no progress (§6.2).
                    stop = self.count(self.now(), self.now())
                    if stop is not None:
                        return stop
                else:
                    self.sleep(SETTLE)  # a burst of events costs one run
                handed = seq if seq is not None else handed
                stop = self.turn(self.spec["again"])
                if stop is not None:
                    return stop
                continue
            if "credential_revoked" in err:
                self.log("the agent's credential was revoked; stopping")
                return EXIT_REVOKED
            # 6 (another wait of this clone), or the hub unreachable: back off, not counted.
            failures = min(failures + 1, 6)  # 2^6 > 60: the cap, without growing the power
            self.sleep(self.rand() * min(60.0, 2.0**failures))


def _seq(out: str) -> int | None:
    try:
        event = json.loads(out)
    except ValueError:
        return None
    seq = event.get("seq") if isinstance(event, dict) else None
    return seq if isinstance(seq, int) and not isinstance(seq, bool) else None


def _run(argv: list[str], env: dict[str, str]) -> int:
    return subprocess.run(argv, env={**os.environ, **env}, check=False).returncode  # noqa: S603


def _run_reaped(argv: list[str], env: dict[str, str], *, timeout: float = TURN_TIMEOUT) -> int:
    """Run one turn in a process group of its own and end that group when the turn ends, so no
    background process the turn started (a stray `maity wait`, say) outlives it (§6.2), and so a
    harness that never terminates is still bounded.

    `start_new_session` makes the child a session and process-group leader, so the group's id
    is the child's pid and the whole group is the turn's own descendants and nothing else. The
    loop waits at most `timeout` for the harness; a harness that keeps running while it reports
    idle or waits on a background task would otherwise never reach cleanup, so when the wait
    runs out the turn is ended and reaped and answers EXIT_TURN, which `Loop.turn` does not
    run again: the loop waits for the next event. When the turn
    ends `_reap` signals exactly that group id: it is created fresh for this one run, so it can
    never name another session's or placement's processes (the hard safety requirement in
    cli/context/runner.md). The loop itself runs in the tmux pane's own, separate group and is
    never touched."""
    proc = subprocess.Popen(argv, env={**os.environ, **env}, start_new_session=True)  # noqa: S603
    bounded = False
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        bounded = True  # the harness ran past the bound: end and reap it below
        code = EXIT_TURN
    finally:
        _reap(proc.pid)  # pid == the new group's id (start_new_session)
    if bounded:  # the harness was in the reaped group; collect it so it leaves no zombie
        try:
            proc.wait(timeout=REAP_GRACE + 1.0)
        except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL already sent
            proc.kill()
            proc.wait()
    return code


def _group_alive(pgid: int) -> bool:
    """Whether process group `pgid` still has a member that is doing something. A zombie (a
    process that has already exited and is only waiting to be reaped) counts as gone: it holds
    a slot but runs nothing, so waiting on it would only burn the grace — in a PID namespace,
    where the leftover's reaper may be the loop itself, that is exactly what used to stall the
    reap. Reads /proc; a process that exits mid-read is treated as gone."""
    try:
        entries = os.listdir("/proc")
    except OSError:  # pragma: no cover - /proc is always present on the runner's Linux
        return False
    want = str(pgid)
    for entry in entries:
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8", errors="replace") as fh:
                stat = fh.read()
        except OSError:
            continue  # gone between the listing and the read
        # `comm` (in parentheses) may itself hold spaces and ')': parse the fields after the
        # last ')', where they are state, ppid, pgrp, … so state is [0] and pgrp is [2].
        tail = stat[stat.rfind(")") + 1 :].split()
        if len(tail) >= 3 and tail[0] != "Z" and tail[2] == want:
            return True
    return False


def _reap(pgid: int, *, grace: float = REAP_GRACE, poll: float = REAP_POLL) -> None:
    """End process group `pgid`: SIGTERM, a short grace, then SIGKILL to whatever is left.
    `pgid` must be a group the caller made for one run (its leader's pid); nothing else is
    signalled. A group already empty, or left with only zombies (the common case: the turn left
    nothing behind, or the leader has exited), ends the grace at once — `_group_alive` treats a
    zombie as gone, so the reap does not wait out the full grace on an already-dead group."""
    if pgid <= 1:  # never a real, reapable group id; refuse to broaden the signal
        return
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return  # nothing left in the group, or not ours to signal
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if not _group_alive(pgid):  # only zombies or nothing left: done, no need to wait
            return
        time.sleep(poll)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _wait(cwd: str | None = None) -> tuple[int, str, str]:
    """`maity wait` in the clone (`cwd`): the harness may start elsewhere, as agy does in the
    workspace folder that holds the clone (§15.5); None, the loop's own directory."""
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [
            sys.executable,
            "-I",
            "-m",
            "maity",
            "wait",
            "--timeout",
            str(WAIT_TIMEOUT),
            "--keep-cursor",
            "--one",  # the event a run is started for, as one object (`_seq`)
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    return done.returncode, done.stdout, done.stderr


def main(args: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maity-loop")
    parser.add_argument("--spec", required=True)
    options = parser.parse_args(args)
    with open(options.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    clone = spec.get("clone")
    # agy leaves no setting to disable background tasks past a turn, so its spec asks the loop
    # to end each turn's own process group instead and bound the turn (adapters._supervised,
    # reap). A spec may lower the turn's bound with `turn_timeout`; without one the default
    # TURN_TIMEOUT applies, so the plain `_run_reaped` is used.
    run: Callable[[list[str], dict[str, str]], int]
    if not spec.get("reap_process_group"):
        run = _run
    elif bound := spec.get("turn_timeout"):
        run = lambda argv, env: _run_reaped(argv, env, timeout=float(bound))  # noqa: E731
    else:
        run = _run_reaped
    return Loop(spec, run, lambda: _wait(clone if isinstance(clone, str) else None)).main()


if __name__ == "__main__":
    sys.exit(main())
