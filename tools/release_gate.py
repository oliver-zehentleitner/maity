#!/usr/bin/env python3
"""Lets a release tag through only when CI already passed on its commit.

The release workflows (release-hub.yml, release-cli.yml) run this in their
`check` job instead of running the test suites again. It reads, and never
writes:

- ci: the `ci` run of a push to main for the tagged commit, whose `ci-ok`
  job must have passed. A commit that is not on main has no such run.
- with --mariadb (the hub): a hub-mariadb run whose `hub-mariadb` job ran on
  a commit of main with the same files the suite reads as the tagged commit
  (the list `decide` in hub-mariadb.yml compares, MARIADB_PATHS below). The
  newest such run must have passed. A run that skipped the suite counts for
  nothing, and only main's own workflow file counts: the run's ref is main
  and the commit it ran is on main.

While the ci run, or a hub-mariadb run, is still queued or running, it waits
(up to --wait-minutes), so a tag pushed right after a merge works; a newer
matching MariaDB run still going is waited for even when an older one is
green. Anything missing, red or impossible to compare stops the release with
a message naming what to do.
Standard library only; the token is the job's own, read-only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

# The files the MariaDB suite reads: the same list as the `decide` job of
# .github/workflows/hub-mariadb.yml (test_release_gate.py holds them equal).
MARIADB_PATHS = (
    "hub",
    "docs/join-page.md",
    "docs/api.md",
    "deploy/Dockerfile*",
    ".github/workflows/hub-mariadb.yml",
)

DONE = "completed"
# A job that ran the suite and ended; skipped (nothing to test) is not one.
RAN = {"success", "failure", "cancelled", "timed_out"}
HAND = re.compile(r"hub-mariadb hand (head|[0-9a-f]{40})")


@dataclass
class State:
    """One check's result: ok, wait (still running) or fail."""

    kind: str
    text: str


class Api:
    """GET on the repository's REST API with the job's token."""

    def __init__(self, repo: str, token: str, base: str = "https://api.github.com") -> None:
        self.root = f"{base}/repos/{repo}/"
        self.token = token

    def get(self, path: str, **params: object) -> dict:
        query = urllib.parse.urlencode(params)
        req = urllib.request.Request(
            self.root + path + (f"?{query}" if query else ""),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "maity-release-gate",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)


def job(api: Api, run: dict, name: str) -> dict | None:
    """The run's job called name, in its latest attempt."""
    jobs = api.get(f"actions/runs/{run['id']}/jobs", filter="latest", per_page=100)["jobs"]
    return next((j for j in jobs if j["name"] == name), None)


def ci_state(api: Api, sha: str) -> State:
    """ci-ok of the ci run that a push to main started for sha."""
    runs = api.get(
        "actions/workflows/ci.yml/runs", head_sha=sha, event="push", branch="main", per_page=10
    )["workflow_runs"]
    if not runs:
        return State(
            "fail",
            f"no ci run from a push to main for {sha}: tag a commit of main whose ci-ok is green",
        )
    run = runs[0]
    if run["status"] != DONE:
        return State("wait", f"ci for {sha} is {run['status']}: {run['html_url']}")
    ok = job(api, run, "ci-ok")
    result = ok["conclusion"] if ok else f"missing (the run ended {run.get('conclusion')})"
    if result == "success":
        return State("ok", f"ci-ok passed on {sha}: {run['html_url']}")
    return State(
        "fail",
        f"ci-ok is {result} on {sha} ({run['html_url']}): re-run ci there until ci-ok is green,"
        " or tag a later commit of main whose ci-ok is green; then re-run this job",
    )


def tested(run: dict) -> str | None:
    """The commit a hub-mariadb run tested, when the run list tells it.

    Automatic runs (the clock, a start from ci) test the head of main they
    ran on. A hand run tests its `sha` input, which only its title carries
    (`hub-mariadb hand <sha>`, or `hand head` without one); older hand runs,
    titled `hub-mariadb hand`, cannot be told and are left out. Whether the
    run's own workflow file can be trusted is `trusted`'s question.
    """
    title = run.get("display_title") or ""
    if run["event"] == "schedule":
        return run["head_sha"]
    if run["event"] != "workflow_dispatch":
        return None
    if title == "hub-mariadb ci":
        return run["head_sha"]
    hand = HAND.fullmatch(title)
    if hand:
        return run["head_sha"] if hand.group(1) == "head" else hand.group(1)
    return None


class Git:
    """The checkout's history; a commit it lacks is fetched before it is judged."""

    def __init__(self) -> None:
        # main moves while the gate waits: one fetch per look (gate makes a Git per look).
        self.main_fetched = False

    @staticmethod
    def _run(*args: str) -> int:
        return subprocess.run(["git", *args], capture_output=True, check=False).returncode

    def _have(self, sha: str) -> bool:
        if self._run("cat-file", "-e", f"{sha}^{{commit}}") == 0:
            return True
        self._run("fetch", "--quiet", "--no-tags", "origin", sha)
        return self._run("cat-file", "-e", f"{sha}^{{commit}}") == 0

    def on_main(self, sha: str) -> bool | None:
        """Whether sha is on main; None when that cannot be told."""
        if not self.main_fetched:
            main = "+refs/heads/main:refs/remotes/origin/main"
            if self._run("fetch", "--quiet", "--no-tags", "origin", main) != 0:
                return None
            self.main_fetched = True
        if not self._have(sha):
            return None
        code = self._run("merge-base", "--is-ancestor", sha, "refs/remotes/origin/main")
        if code == 0:
            return True
        if code == 1:
            return False
        return None

    def same(self, a: str, b: str) -> bool | None:
        """Whether a and b hold the same MARIADB_PATHS; None when that cannot be told."""
        if not (self._have(a) and self._have(b)):
            return None
        code = self._run("diff", "--quiet", a, b, "--", *MARIADB_PATHS)
        if code == 0:
            return True
        if code == 1:
            return False
        return None


def mariadb_state(api: Api, sha: str, git: Git) -> State:
    """The newest hub-mariadb run that tested the tagged commit's hub files.

    Only runs of main's own workflow file count: a dispatch on another ref
    runs that ref's version of hub-mariadb.yml, which could keep the title
    and the job's name and drop the suite. So the run's ref must be main and
    the commit it ran (head_sha, whose workflow file it used) must be on
    main. A newer matching run that is still going is waited for, and a
    commit that cannot be compared stops the gate, so an older green run
    never stands in for a newer one.
    """
    # Only main's runs: those of other refs can never count, and must not push main's own
    # off the page.
    runs = api.get("actions/workflows/hub-mariadb.yml/runs", branch="main", per_page=50)[
        "workflow_runs"
    ]
    for run in runs:
        commit = tested(run)
        if commit is None or run.get("head_branch") != "main":
            continue
        trusted = git.on_main(run["head_sha"])
        if trusted is None:
            return State(
                "fail",
                f"cannot tell whether {run['head_sha']} is on main ({run['html_url']}):"
                " re-run this job",
            )
        if not trusted:
            continue
        same = git.same(commit, sha)
        if same is None:
            return State(
                "fail",
                f"cannot compare the hub files of {commit} with {sha} ({run['html_url']}):"
                " re-run this job",
            )
        if not same:
            continue
        if run["status"] != DONE:
            return State(
                "wait",
                f"hub-mariadb on {commit}, same hub files as {sha}, is {run['status']}:"
                f" {run['html_url']}",
            )
        suite = job(api, run, "hub-mariadb")
        result = suite["conclusion"] if suite else None
        if result not in RAN:
            continue
        if result == "success":
            return State(
                "ok",
                f"hub-mariadb passed on {commit}, same hub files as {sha}: {run['html_url']}",
            )
        return State(
            "fail",
            f"hub-mariadb is {result} on {commit}, same hub files as {sha}"
            f" ({run['html_url']}): fix main and tag again, or if it was a flake start"
            f" hub-mariadb by hand from main (Actions, hub-mariadb, Run workflow, sha {sha})"
            " and re-run this job when it is green",
        )
    return State(
        "fail",
        f"no hub-mariadb run tested the hub files of {sha}: start it by hand from main"
        f" (Actions, hub-mariadb, Run workflow, sha {sha}) and re-run this job when it is green",
    )


def gate(
    api: Api,
    sha: str,
    mariadb: bool,
    wait: float,
    interval: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    git: Git | None = None,
) -> int:
    """0 when every check passed, 1 when one failed or the wait ran out."""
    end = clock() + wait
    # ci starts the MariaDB run in its last job; give that run a moment to
    # show in the list before calling it missing.
    grace = 2
    while True:
        states = [ci_state(api, sha)]
        if mariadb and states[0].kind == "ok":
            state = mariadb_state(api, sha, git or Git())
            if (
                state.kind == "fail"
                and "no hub-mariadb run" in state.text
                and grace > 0
                and clock() < end
            ):
                grace -= 1
                state = State("wait", state.text)
            states.append(state)
        for state in states:
            print(f"{state.kind}: {state.text}", flush=True)
        failed = [s for s in states if s.kind == "fail"]
        if failed:
            for state in failed:
                print(f"::error::{state.text}", flush=True)
            return 1
        if all(s.kind == "ok" for s in states) and (len(states) == 2 or not mariadb):
            return 0
        if clock() >= end:
            print(
                f"::error::still waiting after {wait / 60:.0f} minutes: re-run this job when it is done",
                flush=True,
            )
            return 1
        sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sha", default=os.environ.get("GITHUB_SHA"), help="the tagged commit")
    parser.add_argument("--mariadb", action="store_true", help="also require the hub's MariaDB run")
    parser.add_argument(
        "--wait-minutes", type=float, default=0, help="how long to wait for running checks"
    )
    parser.add_argument("--interval", type=float, default=60, help="seconds between looks")
    args = parser.parse_args(argv)
    if not args.sha or not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha needs the full commit id")
    api = Api(os.environ["GITHUB_REPOSITORY"], os.environ["GH_TOKEN"])
    return gate(api, args.sha, args.mariadb, args.wait_minutes * 60, args.interval)


if __name__ == "__main__":
    sys.exit(main())
