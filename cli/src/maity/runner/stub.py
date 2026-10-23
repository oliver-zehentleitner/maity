"""The `stub` harness (runner design §6.4): no model, no repository code.

For tests and the dashboard's end-to-end run. When the clone holds a credential it runs
`maity resume` and then `maity wait` in a loop, so the agent shows up online; it exits with
`--exit-code` after `--run-seconds` (never, with 0).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from .asuser import RUNNER, AsUser


def argv(exit_code: int, run_seconds: int, as_user: AsUser = RUNNER) -> list[str]:
    """The adapter's command: this module where the agents run, two numbers."""
    return [
        *as_user.runner_module("stub"),
        "--exit-code", str(exit_code), "--run-seconds", str(run_seconds),
    ]  # fmt: skip


def _maity(*args: str, timeout: float) -> int:
    try:
        return subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
            [sys.executable, "-I", "-m", "maity", *args], timeout=timeout, check=False
        ).returncode
    except subprocess.TimeoutExpired:
        return 3


def main(args: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="maity-stub")
    parser.add_argument("--exit-code", type=int, default=0)
    parser.add_argument("--run-seconds", type=int, default=30)
    options = parser.parse_args(args)
    deadline = time.monotonic() + options.run_seconds if options.run_seconds else None
    joined = (Path.cwd() / ".git" / "maity" / "credential").is_file()
    print(f"maity stub: exit {options.exit_code} after {options.run_seconds or '∞'} s", flush=True)
    if joined:
        _maity("resume", timeout=60)
    while deadline is None or time.monotonic() < deadline:
        left = 60.0 if deadline is None else max(deadline - time.monotonic(), 0.0)
        started = time.monotonic()
        code = (
            _maity("wait", "--timeout", str(max(int(left), 1)), timeout=left + 30) if joined else 1
        )
        if code != 0 or time.monotonic() - started < 1:  # a failing or instant wait: no spin
            time.sleep(min(left, 5.0) if deadline else 5.0)
    return int(options.exit_code)


if __name__ == "__main__":
    sys.exit(main())
