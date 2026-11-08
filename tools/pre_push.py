#!/usr/bin/env python3
"""The opt-in pre-push hook (CONTRIBUTING.md, "Lint and types before a push").

For every package a push touches (hub/, cli/) it runs CI's own lint and type targets,
`make lint typecheck`, without the tests, with the Python of the hub's environment, which
`make -C hub install` fills from the hashed lock. Before that it compares black, ruff and
mypy in that environment with their pins in hub/requirements/dev.txt and stops on a
difference, so the hook does not pass or fail on another version than the lock.

For every Keep the Why project a push touches (the root, hub/, cli/, web/, as CI's ktw-lint
job has them) it runs `ktw-lint <path>` as that job does. The `ktw-lint` on PATH (or the one
MAITY_HOOK_KTW_LINT names) must be the version CI pins, the `# lint-vX` of
.github/workflows/ktw-lint.yml; another version stops the push with both versions and the
install command. The hook installs nothing and needs no network.

It checks the working tree, so it runs only when that is what is pushed: HEAD is the
pushed commit and what it checks has no uncommitted change.

Git runs it as `pre-push <remote> <url>` with one line per ref on stdin:
`<local ref> <local sha> <remote ref> <remote sha>`. `git push --no-verify` skips it.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

ZERO = re.compile(r"^0+$")
PACKAGES = ("hub", "cli")
TOOLS = ("black", "ruff", "mypy")
# The Makefile variable that names the Python, per package.
PYTHON_VARIABLE = {"hub": "PYTHON", "cli": "PY"}
# The Keep the Why projects, as the matrix of .github/workflows/ktw-lint.yml lists them.
KTW_PATHS = (".", "hub", "cli", "web")
KTW_WORKFLOW = ".github/workflows/ktw-lint.yml"
# What ktw-lint reads in a project: a change here in a child is also checked from the root,
# and the other way round, since CI checks a family link on both ends.
KTW_FILES = ("context", ".keep-the-why")


def git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def commit_of(ref: str, cwd: Path) -> str | None:
    """The commit `ref` names, an annotated tag peeled to its commit; None for anything else."""
    found = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", ref + "^{commit}"],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    return found.stdout.strip() if found.returncode == 0 else None


def changed_files(base: str, sha: str, cwd: Path) -> list[str]:
    """The paths as stored, NUL-separated: git's quoted display form of a name like `é.py`
    would start with a quote and match no package."""
    out = subprocess.run(
        ["git", "diff", "-z", "--name-only", base, sha], cwd=cwd, check=True, capture_output=True
    ).stdout
    return [name for name in out.decode("utf-8", "surrogateescape").split("\0") if name]


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
        # An annotated tag arrives as the tag object's id; what is pushed is its commit.
        local = commit_of(local_sha, top)
        if local is None:
            continue  # a tag of a tree or a blob: no commit, nothing a package check could run on
        remote_commit = None if ZERO.match(remote_sha) else commit_of(remote_sha, top)
        if remote_commit is not None:
            ranges.append((remote_commit, local))
            continue
        # A new branch: what it adds to the remote's main.
        main = f"refs/remotes/{remote}/main"
        base = git("merge-base", main, local, cwd=top) if commit_of(main, top) else None
        ranges.append((base or None, local))
    return ranges


def touched_packages(files: Iterable[str]) -> list[str]:
    tops = {name.split("/", 1)[0] for name in files}
    return [p for p in PACKAGES if p in tops]


def touched_ktw_paths(files: Iterable[str]) -> list[str]:
    """The Keep the Why projects whose files a push changes: a file in hub/, cli/ or web/
    belongs to that project, any other to the root. A change to a project's context/ or
    .keep-the-why reaches its family: a child's to the root, the root's to every child."""
    found: set[str] = set()
    for name in files:
        top, _, rest = name.partition("/")
        if top in KTW_PATHS[1:] and rest:
            found.add(top)
            if rest.split("/", 1)[0] in KTW_FILES:
                found.add(".")
        else:
            found.add(".")
            if top in KTW_FILES:
                found.update(KTW_PATHS)
    return [p for p in KTW_PATHS if p in found]


def ktw_pin(workflow_text: str) -> str | None:
    """The linter version CI installs: the `# lint-vX` comment of the action's pin."""
    match = re.search(r"keep-the-why@[0-9a-f]{40} # lint-v(\S+)", workflow_text)
    return match.group(1) if match else None


def ktw_version(ktw_lint: str) -> str | None:
    """`ktw-lint --version` prints `ktw-lint X`; None when it cannot be run or says otherwise."""
    try:
        out = subprocess.run([ktw_lint, "--version"], check=False, capture_output=True, text=True)
    except OSError:
        return None
    match = re.fullmatch(r"ktw-lint (\S+)\s*", out.stdout)
    return match.group(1) if out.returncode == 0 and match else None


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


def ktw_ready(top: Path) -> str | None:
    """The ktw-lint to run, when it is the version CI pins; None after saying why not."""
    workflow = top / KTW_WORKFLOW
    pin = ktw_pin(workflow.read_text()) if workflow.exists() else None
    if pin is None:
        print(
            f"pre-push: no `# lint-vX` pin of the linter action in {KTW_WORKFLOW};"
            " the hook cannot tell which ktw-lint CI runs.",
            file=sys.stderr,
        )
        return None
    ktw_lint = os.environ.get("MAITY_HOOK_KTW_LINT") or shutil.which("ktw-lint") or ""
    have = ktw_version(ktw_lint) if ktw_lint else None
    if have != pin:
        found = f"ktw-lint {have} ({ktw_lint})" if have else "no ktw-lint that answers --version"
        print(
            f"pre-push: found {found}, but CI runs ktw-lint {pin} ({KTW_WORKFLOW}). Install that"
            f" version, e.g. `pipx install --force keep-the-why-lint=={pin}`, or point"
            " MAITY_HOOK_KTW_LINT at one; the hook installs nothing and runs no other version.",
            file=sys.stderr,
        )
        return None
    return ktw_lint


def python_ready(top: Path) -> str | None:
    """The hub environment's Python, when its black, ruff and mypy are the lock's; None after
    saying why not."""
    python = os.environ.get("MAITY_HOOK_PYTHON") or str(top / "hub" / ".venv" / "bin" / "python")
    if not Path(python).exists():
        print(
            f"pre-push: no Python at {python}. Set up the hub's environment once:\n"
            "  python3 -m venv hub/.venv && make -C hub install PYTHON=.venv/bin/python\n"
            "or point MAITY_HOOK_PYTHON at a Python where `make -C hub install` ran.",
            file=sys.stderr,
        )
        return None
    wanted = pins((top / "hub" / "requirements" / "dev.txt").read_text())
    have = installed(python)
    differ = [f"{t} {have.get(t, '-')} (lock: {v})" for t, v in wanted.items() if have.get(t) != v]
    if differ:
        print(
            f"pre-push: {python} has " + ", ".join(differ) + ", not the versions CI uses;"
            f" bring it to the lock with `make -C hub install PYTHON={python}`.",
            file=sys.stderr,
        )
        return None
    return python


def main(argv: Sequence[str], stdin: Iterable[str]) -> int:
    remote = argv[1] if len(argv) > 1 else "origin"
    top = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()))

    ranges = pushed_ranges(stdin, remote, top)
    if not ranges:
        return 0
    files: set[str] = set()
    everything = False
    for base, sha in ranges:
        if base is None:
            everything = True  # nothing to compare with: check every package and project
        else:
            files.update(changed_files(base, sha, cwd=top))
    packages = list(PACKAGES) if everything else touched_packages(files)
    projects = list(KTW_PATHS) if everything else touched_ktw_paths(files)
    if not packages and not projects:
        return 0

    head = git("rev-parse", "HEAD", cwd=top)
    if any(sha != head for _, sha in ranges):
        print(
            "pre-push: the hook checks the working tree, and HEAD is not the pushed commit;"
            " check out what you push, or skip the hook with `git push --no-verify`.",
            file=sys.stderr,
        )
        return 1
    # What the checks read: a package's whole tree, a project's context/ and .keep-the-why.
    checked = list(packages)
    for project in projects:
        if project not in packages:
            checked += [f if project == "." else f"{project}/{f}" for f in KTW_FILES]
    dirty = git("status", "--porcelain", "--", *checked, cwd=top)
    if dirty:
        print(
            "pre-push: uncommitted changes in "
            + ", ".join(checked)
            + " would be checked instead of the pushed commit:\n"
            + dirty
            + "\ncommit or set them aside first, or skip the hook with `git push --no-verify`.",
            file=sys.stderr,
        )
        return 1

    # Every tool's version first, so a push stops before any check on another version than CI.
    python = python_ready(top) if packages else ""
    if python is None:
        return 1
    ktw_lint = ktw_ready(top) if projects else ""
    if ktw_lint is None:
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
            failed.append(f"lint or types in {package}")
    for project in projects:
        print(f"pre-push: ktw-lint {project}", file=sys.stderr, flush=True)
        if subprocess.run([ktw_lint, project], check=False, cwd=top).returncode != 0:
            failed.append(f"ktw-lint {project}")
    if failed:
        print(
            "pre-push: failed: " + "; ".join(failed) + ". Nothing was pushed."
            " `make format` in a package fixes what black and ruff can;"
            " `git push --no-verify` skips the hook.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv, sys.stdin))
