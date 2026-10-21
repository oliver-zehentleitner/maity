"""What `maity report` states about the code, read from git and gh instead of typed by the agent.

The agent never types a commit hash or a pull request number. `collect()` reads them,
`mismatches()` lists every way the local state disagrees with the remote one, and the report
is refused while that list is not empty.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


class FactsError(Exception):
    """git or gh could not answer a question the report depends on."""


@dataclass(frozen=True)
class PullRequest:
    number: int
    head: str
    state: str
    url: str


@dataclass(frozen=True)
class Facts:
    head: str
    branch: str | None
    remote: str | None
    remote_branch: str | None
    remote_head: str | None
    dirty: bool
    gh_available: bool
    pr: PullRequest | None


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise FactsError(f"{cmd[0]} is not installed") from exc


def _git(cwd: Path, *args: str) -> str | None:
    proc = _run(["git", *args], cwd)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _pull_request(cwd: Path, branch: str) -> PullRequest | None:
    proc = _run(
        [
            "gh",
            "pr",
            "list",
            "--head",
            branch,
            "--state",
            "all",
            "--limit",
            "1",
            "--json",
            "number,headRefOid,state,url",
        ],
        cwd,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "no output"
        raise FactsError(f"gh could not list pull requests: {detail}")
    try:
        rows = json.loads(proc.stdout or "[]")
        if not rows:
            return None
        row = rows[0]
        return PullRequest(
            number=int(row["number"]),
            head=str(row["headRefOid"]),
            state=str(row["state"]),
            url=str(row["url"]),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise FactsError(f"gh returned something unexpected: {exc}") from exc


def collect(cwd: Path) -> Facts:
    head = _git(cwd, "rev-parse", "--verify", "HEAD")
    if head is None:
        raise FactsError(f"{cwd} is not a Git clone with at least one commit")
    branch = _git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    status = _git(cwd, "status", "--porcelain", "--untracked-files=no")
    dirty = bool(status)

    remote = remote_branch = remote_head = None
    if branch:
        remote = _git(cwd, "config", "--get", f"branch.{branch}.remote")
        merge_ref = _git(cwd, "config", "--get", f"branch.{branch}.merge")
        if remote and merge_ref:
            remote_branch = merge_ref.removeprefix("refs/heads/")
            proc = _run(["git", "ls-remote", "--heads", remote, merge_ref], cwd)
            if proc.returncode != 0:
                raise FactsError(f"git ls-remote {remote} failed: {proc.stderr.strip()}")
            line = proc.stdout.strip().splitlines()
            remote_head = line[0].split()[0] if line else None

    gh_available = shutil.which("gh") is not None
    pr = _pull_request(cwd, remote_branch or branch) if gh_available and branch else None
    return Facts(
        head=head,
        branch=branch,
        remote=remote,
        remote_branch=remote_branch,
        remote_head=remote_head,
        dirty=dirty,
        gh_available=gh_available,
        pr=pr,
    )


def mismatches(facts: Facts) -> list[str]:
    """Every reason the facts cannot be reported as they are; empty when they agree."""
    problems: list[str] = []
    if facts.branch is None:
        problems.append("HEAD is detached; check out the branch the work is on")
        return problems
    if facts.dirty:
        problems.append("tracked files have uncommitted changes; commit or stash them")
    if facts.remote is None or facts.remote_branch is None:
        problems.append(f"branch {facts.branch} has no upstream; push it with `git push -u`")
    elif facts.remote_head is None:
        problems.append(f"branch {facts.remote_branch} does not exist on {facts.remote}; push it")
    elif facts.remote_head != facts.head:
        problems.append(
            f"{facts.remote}/{facts.remote_branch} is at {facts.remote_head[:12]}, "
            f"local HEAD is at {facts.head[:12]}; push or pull until they agree"
        )
    if facts.pr is not None and facts.pr.head != facts.head:
        problems.append(
            f"pull request #{facts.pr.number} has head {facts.pr.head[:12]}, "
            f"local HEAD is at {facts.head[:12]}"
        )
    return problems
