"""Dev venvs for a Claude Code coder's clone (`[backend.local] clone_venvs`; cli/context/runner.md).

A placed session cannot reach PyPI, so it cannot build the venv its project's checks run in. The
runner, which can, builds one per subpackage the configuration names, outside the sandbox, and
runs nothing from the clone while it does:

- The lock is `<sub>/requirements/dev.txt` as the project's repository has it on the placement's
  branch, fetched into the runner's own bare repository (skills._git: no hooks, no user or system
  configuration). The work tree's copy is never read: the agent can write it, and the runner runs
  no git in a clone (workspace.py).
- Every requirement must be `name==version`, optionally with extras and an environment marker,
  with at least one `--hash=sha256:`; anything else (an option, also one after a marker, a URL,
  a path, an include) refuses the lock.
- pip installs wheels only (`--only-binary=:all:`), each checked against its hash, with no
  resolution of its own (`--no-deps`): no build script of any package runs.
- The clone's own package is not built, since its build script is clone code: a `.pth` names
  `<clone>/<sub>/src`.
- Each venv is built into a new directory with the runner's python3 (the first on its PATH) and
  swapped in by rename; the
  runner never runs a venv's interpreter after a session could reach it. A session reads and
  runs it; its commands cannot write it (adapters.claude_settings), and whether Claude Code's
  file tools refuse a write through the clone's link is not verified (cli/context/runner.md).
- `<clone>/<sub>/.venv` is made a link to it only where nothing stands there, and only below a
  real directory: a link the agent put on the way is never followed.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import subprocess
from pathlib import Path

from maity.runner import skills

LOCK = "requirements/dev.txt"
STAMP = "maity-lock.sha256"
MAX_LOCK_BYTES = 1024 * 1024
PIP_TIMEOUT = 20 * 60
# Each requirement of a lock, its continuation lines joined: a pinned name with optional extras,
# an optional environment marker, and its hashes. Nothing else passes (no option, URL or path).
_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
_REQUIREMENT = re.compile(
    rf"{_NAME}(?:\[{_NAME}(?:,{_NAME})*\])?==[A-Za-z0-9.+!_-]+"
    r"(?:\s*;\s*[A-Za-z0-9_ .<>=!'\"(),~-]+?)?"
    r"(?:\s+--hash=sha256:[0-9a-f]{64})+"
)
_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")
_PIP_ENV = ("PATH", "HOME", "LANG", "https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY",
            "no_proxy", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR")  # fmt: skip


class Unavailable(Exception):
    """No venv for this subpackage now: the reason is logged, the start goes on."""


def check_lock(text: str) -> str:
    """The lock as pip gets it: one requirement per line, each checked; else Unavailable."""
    if len(text.encode()) > MAX_LOCK_BYTES:
        raise Unavailable(f"the lock is larger than {MAX_LOCK_BYTES} bytes")
    joined = re.sub(r"\\\r?\n", " ", text)
    kept = []
    for raw in joined.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = " ".join(line.split())
        # An option rides on no line: every token that starts with '-' is a sha256 hash, also
        # after an environment marker, whose characters alone would let one through.
        options = [w for w in line.split() if w.startswith("-") and not _HASH.fullmatch(w)]
        if options or not _REQUIREMENT.fullmatch(line):
            raise Unavailable(
                f"the lock holds a line that is no pinned, hashed requirement: {line[:80]!r}"
            )
        kept.append(line)
    if not kept:
        raise Unavailable("the lock names no requirement")
    return "\n".join(kept) + "\n"


def fetch(venvs_dir: Path, placement_id: str, repository: str, branch: str | None) -> Path:
    """The placement's branch (the repository's default without one), fetched into a bare
    repository of the runner's own, one per placement so two starts never share a FETCH_HEAD."""
    git_dir = venvs_dir / placement_id / ".git-locks"
    git_dir.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        skills._git(git_dir, "init", "--quiet", "--bare", str(git_dir))
        ref = branch or "HEAD"
        skills._git(git_dir, "fetch", "--quiet", "--depth", "1", "--no-tags", "--", repository, ref)
    except skills.Unavailable as exc:
        raise Unavailable(str(exc)) from None
    return git_dir


def lock_of(git_dir: Path, sub: str) -> str:
    """`<sub>/requirements/dev.txt` as the fetched commit has it, checked (check_lock)."""
    try:
        text = str(skills._git(git_dir, "show", f"FETCH_HEAD:{sub}/{LOCK}"))
    except skills.Unavailable as exc:
        raise Unavailable(str(exc)) from None
    return check_lock(text)


def _python() -> str:
    found = shutil.which("python3")
    if found is None:
        raise Unavailable("no python3 for the runner to build a venv with")
    return found


def _run(argv: list[str], timeout: int) -> None:
    env = {k: v for k, v in os.environ.items() if k in _PIP_ENV}
    env.update({"PIP_CONFIG_FILE": os.devnull, "PIP_NO_INPUT": "1", "PYTHONNOUSERSITE": "1"})
    try:
        done = subprocess.run(
            argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout,
            check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unavailable(f"{Path(argv[0]).name} failed: {exc}") from None
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        last = (said or [""])[-1][:200]
        raise Unavailable(f"{Path(argv[0]).name} exited {done.returncode}: {last}")


def stamp_of(lock: str, clone: Path, sub: str) -> str:
    """What a built venv was built for: its lock, and the clone its `.pth` names."""
    return hashlib.sha256(f"{lock}\0{clone}\0{sub}".encode()).hexdigest()


def build(venvs_dir: Path, placement_id: str, sub: str, lock: str, clone: Path) -> Path:
    """The venv for `sub` of this placement's clone, built from `lock` (checked) unless one built
    from the same lock for the same clone is there already; its path."""
    home = venvs_dir / placement_id
    target = home / sub
    stamp = stamp_of(lock, clone, sub)
    try:
        if (target / STAMP).read_text() == stamp and (target / "bin" / "python").exists():
            return target
    except OSError:
        pass
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    fresh = home / f".{sub}.new-{secrets.token_hex(4)}"
    try:
        _run([_python(), "-m", "venv", str(fresh)], 300)
        (fresh / "requirements.txt").write_text(lock)
        pip = [str(fresh / "bin" / "python"), "-m", "pip", "install", "--quiet",
               "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:",
               "--no-deps", "--cache-dir", str(venvs_dir / ".pip-cache"),
               "-r", str(fresh / "requirements.txt")]  # fmt: skip
        _run(pip, PIP_TIMEOUT)
        site = sorted(fresh.glob("lib/python*/site-packages"))
        if len(site) != 1:
            raise Unavailable("the new venv has no single site-packages")
        (site[0] / f"_maity_clone_{sub}.pth").write_text(f"{clone / sub / 'src'}\n")
        (fresh / STAMP).write_text(stamp)
        # The old venv is set aside, not removed, until the new one stands in its place: a
        # rename that fails puts it back, so a failed swap never leaves the clone without one.
        old = None
        if target.exists() or target.is_symlink():
            old = home / f".{sub}.old-{secrets.token_hex(4)}"
            target.rename(old)
        try:
            fresh.rename(target)
        except OSError:
            if old is not None:
                old.rename(target)
            raise
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    finally:
        if fresh.exists():
            shutil.rmtree(fresh, ignore_errors=True)
    return target


def link(clone: Path, sub: str, venv: Path) -> bool:
    """`<clone>/<sub>/.venv` a link to `venv`: made where nothing stands there, below a real
    directory; one that already names `venv` stays. False where something else stands."""
    folder = clone / sub
    if folder.is_symlink() or not folder.is_dir():
        return False
    place = folder / ".venv"
    if place.is_symlink():
        return os.readlink(place) == str(venv)
    if place.exists():
        return False
    try:
        os.symlink(venv, place)
    except FileExistsError:
        return False
    return True


def remove(venvs_dir: Path, placement_id: str) -> None:
    """A placement's venvs, once it has ended: nothing else names them."""
    shutil.rmtree(venvs_dir / placement_id, ignore_errors=True)
