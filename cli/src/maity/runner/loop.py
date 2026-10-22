"""The supervised loop (runner design §6.2): `python -m maity.runner.loop --spec FILE`.

Runs the harness headless with the start prompt, then waits for the agent's next event with
`maity wait --keep-cursor` (the agent's own credential; no model tokens while idle), lets a
burst settle, and runs the harness again, whose `maity resume` lists the event as unread.

Exit codes the runner maps (§15.7): 20 the agent's credential is revoked
(`agent_credential_revoked`), 21 runs keep ending without progress (`crash_loop`,
`hot_loop`). A run that ends within `quick_exit` without the event having been acknowledged
counts toward `crash_cap` within `crash_window`, with the runner's backoff between runs.
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
from typing import Any

from . import config, restart

WAIT_TIMEOUT = 600
SETTLE = 15.0
EXIT_REVOKED = 20
EXIT_HOT_LOOP = 21


@dataclass
class Loop:
    spec: dict[str, Any]
    run: Callable[[list[str], dict[str, str]], int]
    wait: Callable[[], tuple[int, str, str]]  # (exit code, stdout, stderr)
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic
    rand: Callable[[], float] = random.random
    crashes: list[float] = field(default_factory=list)
    log: Callable[[str], None] = lambda line: print(f"maity loop: {line}", flush=True)

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

    def turn(self, argv: list[str]) -> int | None:
        """One headless run. A non-zero exit counts against the cap; a clean one does not,
        however short: a quick answer to an event is progress."""
        started = self.now()
        code = self.run(argv, self.spec.get("env") or {})
        if code != 0:
            self.log(f"the run exited {code}")
            return self.count(started, self.now())
        return None

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
            failures += 1
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


def _wait() -> tuple[int, str, str]:
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-m", "maity", "wait", "--timeout", str(WAIT_TIMEOUT), "--keep-cursor"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.returncode, done.stdout, done.stderr


def main(args: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maity-loop")
    parser.add_argument("--spec", required=True)
    options = parser.parse_args(args)
    with open(options.spec, encoding="utf-8") as fh:
        spec = json.load(fh)
    return Loop(spec, _run, _wait).main()


if __name__ == "__main__":
    sys.exit(main())
