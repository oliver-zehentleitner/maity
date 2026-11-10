"""What `maity report` states about the code, read from git and gh instead of typed by the agent.

The agent never types a commit hash or a pull request number. `collect()` reads them,
`mismatches()` lists every way the local state disagrees with the remote one, and the report
is refused while that list is not empty.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from maity import proc
from maity.redact import without_userinfo


class FactsError(Exception):
    """git or gh could not answer a question the report depends on."""


@dataclass(frozen=True)
class PullRequest:
    number: int
    head: str
    state: str
    url: str
    # Shown before a report is sent, and searched for the card id (cli.py `_belongs`); the body
    # only where gh read it, the probe's answer has none.
    title: str = ""
    body: str = ""


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
    branch_merged: bool = False  # the branch is gone; its merged pull request has this head
    # gh is installed and was asked, but failed (no login, no network, its GraphQL refused):
    # an error, never "no pull request" (66da7721); `report` raises it unless the card's linked
    # pull request, read through the hub's probe, stands in (cli/context/report.md).
    forge_error: str | None = None


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    try:
        return proc.run(cmd, cwd)
    except proc.ToolError as exc:
        raise FactsError(str(exc)) from exc


def _git(cwd: Path, *args: str) -> str | None:
    """For lookups where a non-zero exit is an answer (no such ref, no such key): None."""
    result = _run([*proc.GIT, *args], cwd)
    return result.stdout.strip() if result.returncode == 0 else None


def _last_line(stderr: str) -> str:
    """The last line of git's or gh's error output, without a credential: both repeat the
    remote's URL as configured, a token in it included."""
    return without_userinfo(stderr.strip().splitlines()[-1]) if stderr.strip() else "no output"


def _git_required(cwd: Path, *args: str) -> str:
    """For questions that must be answered; a failure is an error, never an empty answer."""
    result = _run([*proc.GIT, *args], cwd)
    if result.returncode != 0:
        raise FactsError(f"git {args[0]} failed: {_last_line(result.stderr)}")
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
            "number,headRefOid,state,url,title,body",
        ],
        cwd,
    )
    if result.returncode != 0:
        raise FactsError(f"gh could not list pull requests: {_last_line(result.stderr)}")
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
            title=str(row.get("title") or ""),
            body=str(row.get("body") or ""),
        )
    except (ValueError, KeyError, TypeError) as exc:
        raise FactsError(f"gh returned something unexpected: {exc}") from exc


def gh_hosts() -> set[str]:
    """The forge hosts gh is asked about: github.com and GH_HOST (an empty one is unset)."""
    return {"github.com", (os.environ.get("GH_HOST") or "github.com").lower()}


def pull_request_state(cwd: Path, url: str) -> str | None:
    """`open`, `closed` or `merged` as the forge has it now; None when it can't be asked,
    a URL on a host gh does not know included (gh is never sent elsewhere)."""
    try:
        parts = urllib.parse.urlsplit(url)
        if (
            parts.scheme != "https"
            or not parts.hostname
            or parts.hostname.lower() not in gh_hosts()
        ):
            return None
        result = _run(["gh", "pr", "view", url, "--json", "state"], cwd)
        if result.returncode != 0:
            return None
        state = json.loads(result.stdout)["state"]
    except (FactsError, ValueError, KeyError, TypeError):
        return None
    return state.lower() if isinstance(state, str) else None


def remote_host(url: str) -> str | None:
    """The host of a Git remote URL (https, ssh, or scp-like `git@host:path`); None for a path
    or a URL without a host."""
    if "://" in url:
        return urllib.parse.urlsplit(url).hostname
    if os.name == "nt" and re.match(r"^[A-Za-z]:[\\/]", url):
        return None  # a drive path there; elsewhere git reads `C:/…` as host `C`, as here
    match = re.match(r"^(?:[^@/]+@)?([^:/]+):", url)
    return match.group(1) if match else None


def _forge_unknown(cwd: Path, remote: str | None) -> str | None:
    """Why gh cannot say anything about this branch, or None when it can be asked."""
    if proc.program("gh") is None:
        return "gh is not installed"
    if remote is None:
        return None
    # As written, before insteadOf; a branch pushed with `-u <url>` has the URL as its remote.
    url = _git(cwd, "config", "--get", f"remote.{remote}.url") or remote
    host = remote_host(url)
    if not host or host.lower() not in gh_hosts():
        bare = "://" in url and not url.lower().startswith("file:")
        where = host or ("no host" if bare else "a local path")
        return f"the remote {without_userinfo(remote)} is not on a GitHub host gh knows ({where})"
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


_HEAD_REF = re.compile(r"^refs/heads/[^\s~^:?*\[\\]+$")


def _check_upstream(cwd: Path, branch: str, remote: str, merge_ref: str) -> None:
    """Refuse an upstream maity would not hand to git as it stands: a remote, its configured
    URL or the merge ref that reads as an option or names a remote helper
    (`<transport>::<address>`), or a merge ref outside refs/heads/. Any other remote
    `git push -u` stores passes: a configured name in any script, a URL, a path, `host:path`;
    which transports git may then use is proc.TRANSPORTS."""
    # Every URL configured, not only the last: `ls-remote` takes the first.
    urls = (
        None if remote.startswith("-") else _git(cwd, "config", "--get-all", f"remote.{remote}.url")
    )
    values = [remote, merge_ref] + (urls.splitlines() if urls else [])
    if any(v.startswith("-") or "::" in v for v in values) or not _HEAD_REF.match(merge_ref):
        raise FactsError(_unreadable(branch))


def _unreadable(branch: str) -> str:
    return (
        f"branch {branch}'s upstream (branch.{branch}.remote / .merge) is not a remote and a "
        f"branch maity asks git about; set it with `git push -u origin {branch}`"
    )


def _default_branch(cwd: Path, remote: str) -> str | None:
    """The remote's default branch: what `refs/remotes/<remote>/HEAD` points at (set by the
    clone), else what the remote's HEAD names (`ls-remote --symref`); None when neither says."""
    local = _git(cwd, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD")
    prefix = f"refs/remotes/{remote}/"
    if local and local.startswith(prefix):
        return local.removeprefix(prefix)
    listing = _git(cwd, "ls-remote", "--symref", "--", remote, "HEAD") or ""
    for line in listing.splitlines():
        ref, _, name = line.partition("\t")
        if name == "HEAD" and ref.startswith("ref: refs/heads/"):
            return ref.removeprefix("ref: refs/heads/")
    return None


def _branch(cwd: Path) -> str | None:
    """The branch HEAD is on, None when detached. Read as the full ref and cut, not with
    `--short`: that gives `heads/<b>` when a tag `<b>` exists too, and `branch.<b>.*` would then
    name another branch's configuration."""
    ref = _git(cwd, "symbolic-ref", "--quiet", "HEAD")
    if not ref or not ref.startswith("refs/heads/"):
        return None
    return ref.removeprefix("refs/heads/")


def _remote_head(cwd: Path, remote: str, ref: str) -> str | None:
    """The commit the remote's `ref` points at, None when it has no such ref. `ls-remote` takes
    the pattern as a suffix (`refs/heads/<b>` also lists `refs/heads/x/refs/heads/<b>`), so only
    a line naming exactly `ref` counts."""
    for line in _git_required(cwd, "ls-remote", "--heads", "--", remote, ref).splitlines():
        sha, _, name = line.partition("\t")
        if name == ref:
            return sha
    return None


@dataclass(frozen=True)
class Retrack:
    """What `track_own_branch` did: `note` when it set the upstream, `problem` when the branch
    tracks the default branch and the remote has no branch of its name (nothing changed)."""

    note: str | None = None
    problem: str | None = None


def track_own_branch(cwd: Path) -> Retrack:
    """A branch whose upstream is the remote's default branch, as `git switch -c <b>
    origin/main` sets it, is set to track its own branch of the same name on that remote:
    `branch.<b>.merge` becomes `refs/heads/<b>`, the remote stays. Only when the remote has that
    branch; else nothing changes and the problem names `git push -u`. Any other upstream, the
    default branch itself and a detached HEAD are left as they are (cli/context/report.md)."""
    branch = _branch(cwd)
    if not branch:
        return Retrack()
    remote = _git(cwd, "config", "--get", f"branch.{branch}.remote")
    merge_ref = _git(cwd, "config", "--get", f"branch.{branch}.merge")
    if not remote or remote == "." or not merge_ref:
        return Retrack()
    _check_upstream(cwd, branch, remote, merge_ref)  # what git is asked about, checked first
    tracked = merge_ref.removeprefix("refs/heads/")
    if tracked == branch or tracked != _default_branch(cwd, remote):
        return Retrack()
    own = f"refs/heads/{branch}"
    shown = without_userinfo(remote)
    if _remote_head(cwd, remote, own) is None:
        return Retrack(
            problem=f"branch {branch} tracks {shown}/{tracked}, the default branch, and "
            f"{shown} has no branch {branch}; push it with `git push -u {shown} {branch}`"
        )
    _git_required(cwd, "config", f"branch.{branch}.merge", own)
    return Retrack(
        note=f"branch {branch} tracked {shown}/{tracked}, the default branch; set "
        f"branch.{branch}.merge to {own}, its own branch on {shown}"
    )


def collect(cwd: Path) -> Facts:
    head = _git(cwd, "rev-parse", "--verify", "HEAD")
    if head is None:
        raise FactsError(f"{cwd} is not a Git clone with at least one commit")
    branch = _branch(cwd)
    # proc.GIT's diff.ignoreSubmodules keeps git out of submodules; a staged gitlink still shows.
    dirty = bool(_git_required(cwd, "status", "--porcelain", "--untracked-files=no"))

    remote = remote_branch = remote_head = None
    if branch:
        remote = _git(cwd, "config", "--get", f"branch.{branch}.remote")
        if remote == ".":  # tracks a local branch: ls-remote would answer from this clone
            remote = None
        merge_ref = _git(cwd, "config", "--get", f"branch.{branch}.merge")
        if remote and merge_ref:
            _check_upstream(cwd, branch, remote, merge_ref)
            remote_branch = merge_ref.removeprefix("refs/heads/")
            remote_head = _remote_head(cwd, remote, merge_ref)

    unknown = _forge_unknown(cwd, remote)
    pr = forge_error = None
    if unknown is None and branch:
        try:
            pr = _pull_request(cwd, remote_branch or branch)
        except FactsError as exc:
            forge_error = str(exc)
    # Merged and deleted: the forge still has this head, as the merged pull request's. It
    # stands in for the branch, and the hub's probe compares only the pull request then.
    merged = (
        remote_branch is not None
        and remote_head is None
        and pr is not None
        and pr.state.upper() == "MERGED"
        and pr.head == head
    )
    if merged:
        remote_head = head
    return Facts(
        head=head,
        branch=branch,
        # A branch pushed with `-u` to a URL has that URL as its remote, a token in it included;
        # the facts go into messages and to the hub, so they keep it without.
        remote=without_userinfo(remote) if remote else remote,
        remote_branch=remote_branch,
        remote_head=remote_head,
        dirty=dirty,
        pr=pr,
        pr_unknown_reason=unknown,
        branch_merged=merged,
        forge_error=forge_error,
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
        problems.append(
            f"branch {facts.remote_branch} does not exist on {facts.remote}; push it. If it was "
            "deleted after its pull request was merged, report from the merged head (gh finds "
            "the merged pull request by the branch name); a result that is not code is "
            "reported with --no-code"
        )
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


def repository_key(value: str) -> tuple[str, str]:
    """Compare HTTPS, SSH and scp-style remotes without treating forks as upstreams."""
    value = value.strip()
    if "://" in value:
        parsed = urllib.parse.urlsplit(value)
        host, path = (parsed.hostname or "").lower(), parsed.path
    else:
        host, sep, path = value.partition(":")
        if not sep:
            host, _, path = value.partition("/")
        host = host.rpartition("@")[2].lower()
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4].rstrip("/")
    return host, path


def repository_mismatch(cwd: Path, expected: str) -> str | None:
    """The remote that disagrees, or None. Prefer upstream so a fork's origin is fine.

    This is a local advisory check: never contact a remote or block a successful join.
    Do not return the configured URL: it can contain embedded credentials.
    """
    try:
        for name in ("upstream", "origin"):
            actual = _git(cwd, "remote", "get-url", name)
            if actual:
                return name if repository_key(actual) != repository_key(expected) else None
    except (FactsError, ValueError):
        pass
    return None
