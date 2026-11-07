"""One shared watcher for a pull request's CI result on an exact head.

    python3 tools/ci_watch.py add <queue> <pr> <full head sha> <author handle#instance>
    python3 tools/ci_watch.py remove <queue> <pr>
    python3 tools/ci_watch.py run <queue> [--once] [--interval 120] [--repo owner/name]

The queue file holds one line per watched head: `<pr> <full head sha> <author>`, where the
author is the Maity address the result goes to (`handle#instance` or `agt-…#instance`). The
author adds the line after a push; a newer head for the same pull request replaces it. The line
holds nothing else: no path, no state directory, no credentials.

`run` goes through the queue every `--interval` seconds (one pass with `--once`). For each line
it takes the newest run of the `ci` workflow (`.github/workflows/ci.yml`) for exactly that head,
started by that pull request's branch (`pull_request` event), and waits until the run is
completed. It then reports the `ci-ok` job's conclusion, and the jobs that failed, to the author
and removes the line. A head that moved, a closed or merged pull request, and a conflict with
main (no run starts then) are reported and removed too.

Who reports: `run` posts with `maity say` under the Maity identity of the `MAITY_STATE_DIR` it is
started with, and refuses to start without one, so the sender is never a guess. On the shared
machine that is the identity of whoever runs the merge queue.

What it never does: it only reads. Every GitHub call is a GET through `gh api`; it never
cancels, re-runs or merges anything. It does not use `gh pr checks` (exit code 8 while a check
fails or is pending, and an older cancelled run listed next to the newer one), nor the commit's
check runs (after a fast-forward an old green `ci-ok` of a push run hangs on the same SHA). A
failing `gh` or `maity` call is taken as passing trouble: the line stays and is tried again.

Standard library only; `gh` must be logged in.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

REPO = "oliver-zehentleitner/maity"
WORKFLOW = ".github/workflows/ci.yml"
SUMMARY_JOB = "ci-ok"
_SHA = re.compile(r"^[0-9a-f]{40}$")
_PR = re.compile(r"^[1-9][0-9]*$")
# A Maity address: a handle or member id, `#`, an instance. No `/`, so never a path.
_AUTHOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*#[A-Za-z0-9]+$")
_FAILED = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}


class Refused(Exception):
    """A queue line or command the tool will not take, said so the author can fix it."""


class Transient(Exception):
    """A `gh` or `maity` call that failed; the line is tried again on the next pass."""


@dataclass(frozen=True)
class Entry:
    pr: int
    sha: str
    author: str

    def line(self) -> str:
        return f"{self.pr} {self.sha} {self.author}"


def parse_entry(pr: str, sha: str, author: str) -> Entry:
    if not _PR.match(pr):
        raise Refused(f"pull request {pr!r}: not a number")
    if not _SHA.match(sha):
        raise Refused("head: give the full 40-character SHA in lower case")
    if not _AUTHOR.match(author):
        raise Refused("author: give a Maity address, handle#instance")
    return Entry(int(pr), sha, author)


def parse_line(line: str) -> Entry | None:
    """An entry, or None for a blank or `#` line; a malformed line raises Refused."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    parts = text.split()
    if len(parts) != 3:
        raise Refused("a line is `<pr> <full head sha> <author handle#instance>`")
    return parse_entry(*parts)


@contextlib.contextmanager
def locked(queue: Path) -> Iterator[None]:
    """Holds the queue's lock file, so `add`, `remove` and `run` never write over each other."""
    with open(f"{queue}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(queue: Path) -> list[str]:
    try:
        return queue.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []


def _write(queue: Path, lines: list[str]) -> None:
    tmp = queue.with_name(queue.name + ".tmp")
    tmp.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    os.replace(tmp, queue)


def _same_pr(line: str, pr: int) -> bool:
    parts = line.split()
    return bool(parts) and parts[0] == str(pr)


def add(queue: Path, entry: Entry) -> None:
    """Adds the entry; a line of the same pull request (an older head) is replaced."""
    with locked(queue):
        lines = [line for line in _read(queue) if not _same_pr(line, entry.pr)]
        _write(queue, [*lines, entry.line()])


def remove(queue: Path, pr: int) -> bool:
    with locked(queue):
        lines = _read(queue)
        kept = [line for line in lines if not _same_pr(line, pr)]
        _write(queue, kept)
    return len(kept) != len(lines)


def _drop(queue: Path, entry: Entry) -> None:
    """Removes exactly this line; a line added meanwhile (a newer head) stays."""
    with locked(queue):
        _write(queue, [line for line in _read(queue) if line.split() != entry.line().split()])


Gh = Callable[[str], object]
Say = Callable[[str, str], None]


def check(entry: Entry, gh: Gh, repo: str = REPO) -> str | None:
    """The report for this entry, or None while there is nothing to report yet."""
    pr = gh(f"repos/{repo}/pulls/{entry.pr}")
    assert isinstance(pr, dict)
    where = f"#{entry.pr} on {entry.sha}"
    if pr.get("merged"):
        return f"CI watch: {where}: the pull request is merged; no longer watched."
    if pr.get("state") != "open":
        return f"CI watch: {where}: the pull request is closed; no longer watched."
    head = pr["head"]
    if head["sha"] != entry.sha:
        return (
            f"CI watch: {where}: the head moved to {head['sha']}; not watched. "
            "Add the new head to watch it."
        )
    runs = gh(f"repos/{repo}/actions/runs?head_sha={entry.sha}&event=pull_request&per_page=100")
    assert isinstance(runs, dict)
    ours = [
        run
        for run in runs.get("workflow_runs", [])
        if run.get("path") == WORKFLOW and run.get("head_branch") == head["ref"]
    ]
    if not ours:
        # A pull request that conflicts with main gets no run at all.
        if pr.get("mergeable_state") == "dirty":
            return f"CI watch: {where}: conflicts with main, so no CI run starts; not watched."
        return None
    run = max(ours, key=lambda r: (r["created_at"], r["id"]))
    if run.get("status") != "completed":
        return None
    jobs = gh(
        f"repos/{repo}/actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs?per_page=100"
    )
    assert isinstance(jobs, dict)
    by_name = {job["name"]: job for job in jobs.get("jobs", [])}
    failed = sorted(
        name
        for name, job in by_name.items()
        if name != SUMMARY_JOB and job.get("conclusion") in _FAILED
    )
    summary = by_name.get(SUMMARY_JOB, {}).get("conclusion")
    url = run.get("html_url", "")
    if summary == "success":
        return f"CI watch: {where}: ci-ok green. {url}"
    said = f"ci-ok {summary}" if summary else "no ci-ok result"
    jobs_said = f"; failed: {', '.join(failed)}" if failed else ""
    return f"CI watch: {where}: RED, {said} (run {run.get('conclusion')}){jobs_said}. {url}"


def run_pass(queue: Path, gh: Gh, say: Say, repo: str = REPO, log: TextIO = sys.stderr) -> int:
    """One pass over the queue; returns how many lines were reported and removed."""
    with locked(queue):
        lines = _read(queue)
    done = 0
    for line in lines:
        try:
            entry = parse_line(line)
        except Refused as refused:
            print(f"ci_watch: skipped a line: {refused}", file=log)
            continue
        if entry is None:
            continue
        try:
            report = check(entry, gh, repo)
            if report is None:
                continue
            say(entry.author, report)
        except Transient as trouble:
            print(f"ci_watch: #{entry.pr}: {trouble}; tried again next pass", file=log)
            continue
        _drop(queue, entry)
        print(report, file=log)
        done += 1
    return done


def gh_get(path: str) -> object:
    """`gh api <path>`: a GET, never anything that writes."""
    done = subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise Transient(f"gh api {path.split('?')[0]}: {done.stderr.strip()[:200]}")
    try:
        return json.loads(done.stdout)
    except ValueError as bad:
        raise Transient(f"gh api {path.split('?')[0]}: not JSON") from bad


def maity_say(author: str, text: str) -> None:
    done = subprocess.run(
        ["maity", "say", "--type", "notice", author, "-"],
        input=text,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise Transient(f"maity say: {done.stderr.strip()[:200]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_add = sub.add_parser("add", help="watch a pull request's head")
    p_add.add_argument("queue", type=Path)
    p_add.add_argument("pr")
    p_add.add_argument("sha")
    p_add.add_argument("author")
    p_remove = sub.add_parser("remove", help="stop watching a pull request")
    p_remove.add_argument("queue", type=Path)
    p_remove.add_argument("pr")
    p_run = sub.add_parser("run", help="watch the queue and report results")
    p_run.add_argument("queue", type=Path)
    p_run.add_argument("--once", action="store_true", help="one pass, then exit")
    p_run.add_argument("--interval", type=int, default=120, help="seconds between passes")
    p_run.add_argument("--repo", default=REPO)
    args = parser.parse_args(argv)
    try:
        if args.command == "add":
            add(args.queue, parse_entry(args.pr, args.sha, args.author))
            return 0
        if args.command == "remove":
            if not _PR.match(args.pr):
                raise Refused(f"pull request {args.pr!r}: not a number")
            if not remove(args.queue, int(args.pr)):
                print(f"ci_watch: #{args.pr} is not in the queue", file=sys.stderr)
            return 0
        if not os.environ.get("MAITY_STATE_DIR"):
            raise Refused("run: set MAITY_STATE_DIR to the identity the reports go out under")
        while True:
            run_pass(args.queue, gh_get, maity_say, args.repo)
            if args.once:
                return 0
            time.sleep(args.interval)
    except Refused as refused:
        print(f"ci_watch: {refused}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
