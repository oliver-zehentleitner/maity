"""The shared dev venv a placement gets (runner design §15.16, docs/runners.md).

The runner builds one virtual environment per placement from the project's own pinned dev
dependencies — pytest, ruff, black and mypy with the versions and transitive packages the
project locks — and puts its `bin` on the session's PATH, so an agent runs the project's
checks with the versions the project pins and cannot change the tools themselves.

It is built as the agents' user, in the runner's own directory for the placement (never in
the clone, whose files the agent writes), from a hash-locked requirements file in the clone
with `pip install --require-hashes`: pip installs only what the lock names and refuses any
package whose hash does not match, so the set is reproducible and the download is checked, as
the harness installers are (installers.py). The project chooses the file in its configuration
(`dev_requirements`); without one the runner builds no venv.

The mechanism knows nothing of the harness: it takes a target directory and a requirements
file, so the same code serves coder placements as well (tsk-kshmb8vc92rr).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from .asuser import AsUser

# The marker the runner writes once a build finishes: the key the venv was built for, so an
# identical later placement reuses it and a changed lock or interpreter rebuilds it. Written
# last, so a build that fails part way leaves none and the next start builds again.
MARKER = ".maity-venv.json"
REQUIREMENTS_MAX = 4 << 20  # a lock file; refused when larger
# Creating the venv and installing the locked tools: pip may download several wheels.
BUILD_TIMEOUT = 900.0
# Bumped when the build's shape changes, so every venv is rebuilt rather than reused wrongly.
SCHEMA = "1"


class VenvError(Exception):
    """The venv could not be built; the caller logs it and starts the session without one."""


def key(requirements: bytes, python: str) -> str:
    """What a built venv is reused for: this schema, interpreter and lock file. A change in
    any of them rebuilds, nothing else does."""
    digest = hashlib.sha256()
    for part in (SCHEMA.encode(), python.encode(), requirements):
        digest.update(len(part).to_bytes(8, "big"))
        digest.update(part)
    return digest.hexdigest()


def ensure(
    as_user: AsUser,
    into: Path,
    requirements: Path,
    clone: Path,
    *,
    python: str = sys.executable,
    timeout: float = BUILD_TIMEOUT,
) -> Path:
    """Build, or reuse, the venv at `into` from the hash-locked `requirements` file in `clone`,
    as the agents' user; return its `bin` directory. A venv a matching marker shows is reused;
    otherwise any stale one is removed and a fresh one built. VenvError on any failure."""
    try:
        locked = as_user.read_whole(requirements, REQUIREMENTS_MAX, under=clone)
    except OSError as exc:
        raise VenvError(f"cannot read {requirements}: {exc}") from exc
    want = key(locked, python)
    bin_dir = into / "bin"
    if _ready(as_user, into, bin_dir, want):
        return bin_dir
    if as_user.exists(into):
        as_user.remove_tree(into)
    _build(as_user, into, bin_dir, requirements, python, timeout)
    as_user.write(into / MARKER, json.dumps({"key": want}) + "\n")
    return bin_dir


def _ready(as_user: AsUser, into: Path, bin_dir: Path, want: str) -> bool:
    """Whether a venv built for `want` is already there: its marker names the key and its
    interpreter is present. A marker the runner cannot read, or for another key, rebuilds."""
    if not as_user.exists(into / MARKER, "-f") or not as_user.exists(bin_dir / "python", "-f"):
        return False
    try:
        data = json.loads(as_user.read_whole(into / MARKER, 4096, under=into))
    except (OSError, ValueError):
        return False
    return isinstance(data, dict) and data.get("key") == want


def _build(
    as_user: AsUser, into: Path, bin_dir: Path, requirements: Path, python: str, timeout: float
) -> None:
    made = as_user.run([python, "-m", "venv", "--clear", str(into)], timeout=timeout)
    if made.returncode != 0:
        raise VenvError(f"cannot create the venv at {into}: {made.stderr.strip()[:200]}")
    # `--require-hashes` makes pip refuse any package not pinned with a matching hash in the
    # lock, so the project's configuration cannot pull an unpinned or altered package in.
    installed = as_user.run(
        [str(bin_dir / "python"), "-m", "pip", "install", "--no-input", "--require-hashes",
         "-r", str(requirements)],
        timeout=timeout,
    )  # fmt: skip
    if installed.returncode != 0:
        raise VenvError(
            f"cannot install the dev tools into {into}: {installed.stderr.strip()[:200]}"
        )
