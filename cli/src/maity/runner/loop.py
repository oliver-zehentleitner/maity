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
EXIT_REVOKED = 20
EXIT_HOT_LOOP = 21
EXIT_RATE_LIMITED = 22
EXIT_RATE_LIMITED_AFTER_CLEAN = 23
# The workspace folder refused before a run (workspace.check_folder), by its detail.
EXIT_FOLDER = {"workspace_not_bare": 24, "workspace_in_repository": 25}


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
        non-zero exit counts against the cap and is
        run again after the backoff, without waiting for a new event: the work it was doing
        is still there. A clean run does not count, however short: a quick answer to an
        event is progress."""
        while True:
            refused = self.refused()
            if refused is not None:
                return refused
            started = self.now()
            code = self.run(argv, self.spec.get("env") or {})
            if code == 0:
                self.clean = True
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
    return Loop(spec, _run, lambda: _wait(clone if isinstance(clone, str) else None)).main()


if __name__ == "__main__":
    sys.exit(main())
