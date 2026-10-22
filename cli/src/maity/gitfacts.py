"""What `maity report` states about the code, read from git and gh instead of typed by the agent.

The agent never types a commit hash or a pull request number. `collect()` reads them,
`mismatches()` lists every way the local state disagrees with the remote one, and the report
is refused while that list is not empty.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from maity import proc


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
    pr: PullRequest | None
    pr_unknown_reason: str | None = None


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return proc.run(cmd, cwd)
    except proc.ToolError as exc:
        raise FactsError(str(exc)) from exc


def _git(cwd: Path, *args: str) -> str | None:
    """For lookups where a non-zero exit is an answer (no such ref, no such key): None."""
    result = _run(["git", *args], cwd)
    return result.stdout.strip() if result.returncode == 0 else None


def _git_required(cwd: Path, *args: str) -> str:
    """For questions that must be answered; a failure is an error, never an empty answer."""
    result = _run(["git", *args], cwd)
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no output"
        raise FactsError(f"git {args[0]} failed: {detail}")
    return result.stdout.strip()


def _pull_request(cwd: Path, branch: str) -> PullRequest | None:
    result = _run(
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
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no output"
        raise FactsError(f"gh could not list pull requests: {detail}")
    try:
        rows = json.loads(result.stdout or "[]")
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


def remote_host(url: str) -> str | None:
    """The host of a Git remote URL (https, ssh, or scp-like `git@host:path`); None for a path."""
    if "://" in url:
        return urllib.parse.urlsplit(url).hostname
    match = re.match(r"^(?:[^@/]+@)?([^:/]+):", url)
    return match.group(1) if match else None


def _forge_unknown(cwd: Path, remote: str | None) -> str | None:
    """Why gh cannot say anything about this branch, or None when it can be asked."""
    if shutil.which("gh") is None:
        return "gh is not installed"
    if remote is None:
        return None
    url = _git(cwd, "config", "--get", f"remote.{remote}.url") or ""  # as written, before insteadOf
    host = remote_host(url)
    known = {"github.com", os.environ.get("GH_HOST", "github.com")}
    if host not in known:
        return f"the remote {remote} is not on a GitHub host gh knows ({host or 'a local path'})"
    return None


def position(cwd: Path) -> tuple[str, str | None]:
    """The head commit and the branch (None when detached).

    Every failure is an error, an unborn HEAD included: a checkpoint is stored as signed, which
    says its refs came from git, so it never goes out without them.
    """
    _git_required(cwd, "rev-parse", "--git-dir")  # outside a clone, dubious ownership: an error
    head = _git(cwd, "rev-parse", "--verify", "--quiet", "HEAD")
    if head is None:
        raise FactsError("this clone has no commit yet; commit before writing a checkpoint")
    return head, _git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")


def collect(cwd: Path) -> Facts:
    head = _git(cwd, "rev-parse", "--verify", "HEAD")
    if head is None:
        raise FactsError(f"{cwd} is not a Git clone with at least one commit")
    branch = _git(cwd, "symbolic-ref", "--quiet", "--short", "HEAD")
    dirty = bool(_git_required(cwd, "status", "--porcelain", "--untracked-files=no"))

    remote = remote_branch = remote_head = None
    if branch:
        remote = _git(cwd, "config", "--get", f"branch.{branch}.remote")
        if remote == ".":  # tracks a local branch: ls-remote would answer from this clone
            remote = None
        merge_ref = _git(cwd, "config", "--get", f"branch.{branch}.merge")
        if remote and merge_ref:
            remote_branch = merge_ref.removeprefix("refs/heads/")
            listing = _git_required(cwd, "ls-remote", "--heads", remote, merge_ref).splitlines()
            remote_head = listing[0].split()[0] if listing else None

    unknown = _forge_unknown(cwd, remote)
    pr = _pull_request(cwd, remote_branch or branch) if unknown is None and branch else None
    return Facts(
        head=head,
        branch=branch,
        remote=remote,
        remote_branch=remote_branch,
        remote_head=remote_head,
        dirty=dirty,
        pr=pr,
        pr_unknown_reason=unknown,
    )


def mismatches(facts: Facts) -> list[str]:
    """Every reason the facts cannot be reported as they are; empty when they agree."""
    problems: list[str] = []
    if facts.dirty:
        problems.append("tracked files have uncommitted changes; commit or stash them")
    if facts.branch is None:
        problems.append("HEAD is detached; check out the branch the work is on")
        return problems
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
