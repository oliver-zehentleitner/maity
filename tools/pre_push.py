#!/usr/bin/env python3
"""The opt-in pre-push hook (CONTRIBUTING.md, "Lint and types before a push").

For every package a push touches (hub/, cli/) it runs CI's own lint and type targets,
`make lint typecheck`, without the tests, with the Python of the hub's environment, which
`make -C hub install` fills from the hashed lock. Before that it compares black, ruff and
mypy in that environment with their pins in hub/requirements/dev.txt and stops on a
difference, so the hook does not pass or fail on another version than the lock.

It checks the working tree, so it runs only when that is what is pushed: HEAD is the
pushed commit and the touched packages have no uncommitted change.

Git runs it as `pre-push <remote> <url>` with one line per ref on stdin:
`<local ref> <local sha> <remote ref> <remote sha>`. `git push --no-verify` skips it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

ZERO = re.compile(r"^0+$")
PACKAGES = ("hub", "cli")
TOOLS = ("black", "ruff", "mypy")
# The Makefile variable that names the Python, per package.
PYTHON_VARIABLE = {"hub": "PYTHON", "cli": "PY"}


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def ref_exists(ref: str, cwd: Path) -> bool:
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return found.returncode == 0


def pushed_ranges(lines: Iterable[str], remote: str, top: Path) -> list[tuple[str | None, str]]:
    """(base, pushed sha) per updated ref; base None when nothing to compare with is known."""
    ranges: list[tuple[str | None, str]] = []
    for line in lines:
        parts = line.split()
        if len(parts) != 4:
            continue
        _local_ref, local_sha, _remote_ref, remote_sha = parts
        if ZERO.match(local_sha):
            continue  # a deletion pushes no code
        if not ZERO.match(remote_sha) and ref_exists(remote_sha, top):
            ranges.append((remote_sha, local_sha))
            continue
        # A new branch: what it adds to the remote's main.
        main = f"refs/remotes/{remote}/main"
        base = git("merge-base", main, local_sha, cwd=top) if ref_exists(main, top) else None
        ranges.append((base or None, local_sha))
    return ranges


def touched_packages(files: Iterable[str]) -> list[str]:
    tops = {name.split("/", 1)[0] for name in files}
    return [p for p in PACKAGES if p in tops]


def pins(lock_text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for tool in TOOLS:
        match = re.search(rf"^{tool}==(\S+)", lock_text, re.M)
        if match:
            found[tool] = match.group(1)
    return found


def installed(python: str) -> dict[str, str]:
    code = (
        "import importlib.metadata as m\n"
        f"for n in {TOOLS!r}:\n"
        "    try: print(n, m.version(n))\n"
        "    except m.PackageNotFoundError: print(n, '-')\n"
    )
    out = subprocess.run([python, "-c", code], check=True, capture_output=True, text=True)
    return dict(line.split(" ", 1) for line in out.stdout.splitlines())


def main(argv: Sequence[str], stdin: Iterable[str]) -> int:
    remote = argv[1] if len(argv) > 1 else "origin"
    top = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()))

    ranges = pushed_ranges(stdin, remote, top)
    if not ranges:
        return 0
    files: set[str] = set()
    for base, sha in ranges:
        if base is None:
            files.update(PACKAGES)  # nothing to compare with: check both
        else:
            files.update(git("diff", "--name-only", base, sha, cwd=top).splitlines())
    packages = touched_packages(files)
    if not packages:
        return 0

    head = git("rev-parse", "HEAD", cwd=top)
    if any(sha != head for _, sha in ranges):
        print(
            "pre-push: the hook checks the working tree, and HEAD is not the pushed commit;"
            " check out what you push, or skip the hook with `git push --no-verify`.",
            file=sys.stderr,
        )
        return 1
    dirty = git("status", "--porcelain", "--", *packages, cwd=top)
    if dirty:
        print(
            "pre-push: uncommitted changes in "
            + ", ".join(packages)
            + " would be checked instead of the pushed commit:\n"
            + dirty
            + "\ncommit or set them aside first, or skip the hook with `git push --no-verify`.",
            file=sys.stderr,
        )
        return 1

    python = os.environ.get("MAITY_HOOK_PYTHON") or str(top / "hub" / ".venv" / "bin" / "python")
    if not Path(python).exists():
        print(
            f"pre-push: no Python at {python}. Set up the hub's environment once:\n"
            "  python3 -m venv hub/.venv && make -C hub install PYTHON=.venv/bin/python\n"
            "or point MAITY_HOOK_PYTHON at a Python where `make -C hub install` ran.",
            file=sys.stderr,
        )
        return 1
    wanted = pins((top / "hub" / "requirements" / "dev.txt").read_text())
    have = installed(python)
    differ = [f"{t} {have.get(t, '-')} (lock: {v})" for t, v in wanted.items() if have.get(t) != v]
    if differ:
        print(
            f"pre-push: {python} has " + ", ".join(differ) + ", not the versions CI uses;"
            f" bring it to the lock with `make -C hub install PYTHON={python}`.",
            file=sys.stderr,
        )
        return 1

    failed = []
    for package in packages:
        print(f"pre-push: {package}: make lint typecheck", file=sys.stderr, flush=True)
        run = subprocess.run(
            [
                "make",
                "--no-print-directory",
                "-C",
                str(top / package),
                "lint",
                "typecheck",
                f"{PYTHON_VARIABLE[package]}={python}",
            ]
        )
        if run.returncode != 0:
            failed.append(package)
    if failed:
        print(
            "pre-push: lint or types failed in " + ", ".join(failed) + "; nothing was pushed."
            " `make format` in the package fixes what black and ruff can;"
            " `git push --no-verify` skips the hook.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv, sys.stdin))
