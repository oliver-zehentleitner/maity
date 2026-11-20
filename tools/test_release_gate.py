"""Tests for release_gate.py against a faked API and history; no network, no git."""

from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import release_gate as g
import upgrade_page

TAG = "a" * 40
LATER = "b" * 40  # a later commit of main with the same hub files
OTHER = "c" * 40  # a commit of main whose hub files differ
ROOT = Path(__file__).resolve().parent.parent


def run(rid, sha=TAG, status="completed", event="push", title="ci", branch="main"):
    return {
        "id": rid,
        "head_sha": sha,
        "status": status,
        "event": event,
        "display_title": title,
        "head_branch": branch,
        "html_url": f"https://example.test/runs/{rid}",
    }


class FakeApi:
    """Answers from fixed tables; ci and hub-mariadb runs can change per look."""

    def __init__(self, ci=None, maria=None, jobs=None):
        self.ci = ci if callable(ci) else (lambda: ci or [])
        self.maria = maria if callable(maria) else (lambda: maria or [])
        self.jobs = jobs or {}
        self.calls = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == "actions/workflows/ci.yml/runs":
            assert (
                params["head_sha"] == TAG
                and params["event"] == "push"
                and params["branch"] == "main"
            )
            return {"workflow_runs": self.ci()}
        if path == "actions/workflows/hub-mariadb.yml/runs":
            assert params["branch"] == "main"
            # The API filters by branch; the gate must still refuse what slips through.
            return {"workflow_runs": self.maria()}
        rid = int(re.fullmatch(r"actions/runs/(\d+)/jobs", path).group(1))
        assert params["filter"] == "latest"
        return {"jobs": [{"name": n, "conclusion": c} for n, c in self.jobs.get(rid, {}).items()]}


BRANCH = "d" * 40  # a commit only on a branch
UNKNOWN = "e" * 40  # a commit the checkout cannot get


OLD = "f" * 40  # a commit of main from before hub-mariadb-11-8 was added
NO_HISTORY = "9" * 40  # a commit whose ancestry the checkout cannot tell (shallow, missing)


class FakeGit:
    """TAG and LATER share the hub files; OTHER differs; BRANCH is not on main."""

    def contains(self, ancestor, sha):
        if sha in (UNKNOWN, NO_HISTORY):
            return None
        return sha != OLD

    def on_main(self, sha):
        return None if sha == UNKNOWN else sha != BRANCH

    def same(self, a, b):
        if UNKNOWN in (a, b):
            return None
        return {a, b} <= {TAG, LATER}


def gate(api, mariadb=True, wait=0.0, looks=None):
    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds
        if looks is not None:
            looks.append(clock[0])

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = g.gate(
            api, TAG, mariadb, wait, 60, sleep=sleep, clock=lambda: clock[0], git=FakeGit()
        )
    return code, out.getvalue()


GREEN_CI = {"ci": [run(1)], "jobs": {1: {"ci-ok": "success"}}}


class Ci(unittest.TestCase):
    def test_green_ci_ok_passes(self):
        code, out = gate(FakeApi(ci=GREEN_CI["ci"], jobs=GREEN_CI["jobs"]), mariadb=False)
        self.assertEqual(code, 0, out)
        self.assertIn("ci-ok passed", out)

    def test_no_push_run_on_main_stops(self):
        code, out = gate(FakeApi(), mariadb=False)
        self.assertEqual(code, 1)
        self.assertIn("::error::no ci run from a push to main", out)

    def test_red_or_cancelled_ci_ok_stops_and_names_the_run(self):
        for result in ("failure", "cancelled"):
            code, out = gate(FakeApi(ci=[run(1)], jobs={1: {"ci-ok": result}}), mariadb=False)
            self.assertEqual(code, 1)
            self.assertIn(f"::error::ci-ok is {result}", out)
            self.assertIn("https://example.test/runs/1", out)

    def test_run_without_ci_ok_job_stops(self):
        code, out = gate(FakeApi(ci=[run(1)], jobs={1: {"web": "success"}}), mariadb=False)
        self.assertEqual(code, 1)
        self.assertIn("ci-ok is missing", out)

    def test_waits_for_running_ci_then_passes(self):
        states = iter([[run(1, status="in_progress")], [run(1, status="queued")], [run(1)]])
        looks = []
        code, out = gate(
            FakeApi(ci=lambda: next(states), jobs={1: {"ci-ok": "success"}}),
            mariadb=False,
            wait=600,
            looks=looks,
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(looks, [60, 120])

    def test_wait_runs_out(self):
        code, out = gate(FakeApi(ci=[run(1, status="in_progress")]), mariadb=False, wait=120)
        self.assertEqual(code, 1)
        self.assertIn("::error::still waiting after 2 minutes", out)

    def test_no_wait_by_default(self):
        code, out = gate(FakeApi(ci=[run(1, status="in_progress")]), mariadb=False)
        self.assertEqual(code, 1)
        self.assertIn("still waiting", out)


def maria(rid, sha, title="hub-mariadb ci", event="workflow_dispatch", status="completed"):
    return run(rid, sha=sha, status=status, event=event, title=title)


def with_11_8(jobs):
    """The tables below name the 11.4 suite; a run of today's workflow has the 11.8 job too,
    green unless the test names it."""
    return {
        rid: ({"hub-mariadb-11-8": "success", **named} if "hub-mariadb" in named else named)
        for rid, named in jobs.items()
    }


class MariaDb(unittest.TestCase):
    def api(self, runs, jobs):
        return FakeApi(ci=GREEN_CI["ci"], maria=runs, jobs={**GREEN_CI["jobs"], **with_11_8(jobs)})

    def test_green_run_on_the_tag_passes(self):
        code, out = gate(
            self.api([maria(5, TAG)], {5: {"decide": "success", "hub-mariadb": "success"}})
        )
        self.assertEqual(code, 0, out)
        self.assertIn("hub-mariadb passed on " + TAG, out)

    def test_green_run_on_a_later_commit_with_the_same_hub_files_passes(self):
        code, out = gate(
            self.api(
                [maria(5, LATER, "hub-mariadb schedule", "schedule")],
                {5: {"hub-mariadb": "success"}},
            )
        )
        self.assertEqual(code, 0, out)

    def test_green_run_on_different_hub_files_does_not_count(self):
        code, out = gate(self.api([maria(5, OTHER)], {5: {"hub-mariadb": "success"}}))
        self.assertEqual(code, 1)
        self.assertIn("::error::no hub-mariadb run tested the hub files of " + TAG, out)

    def test_skipped_suite_does_not_count(self):
        # decide found nothing to test: the run is green, the suite never ran.
        runs = [maria(6, TAG), maria(5, LATER)]
        jobs = {6: {"decide": "success", "hub-mariadb": "skipped"}, 5: {"hub-mariadb": "success"}}
        code, out = gate(self.api(runs, jobs))
        self.assertEqual(code, 0, out)
        self.assertIn("passed on " + LATER, out)

    def test_newest_run_that_tested_decides(self):
        runs = [maria(6, LATER), maria(5, TAG)]
        jobs = {6: {"hub-mariadb": "failure"}, 5: {"hub-mariadb": "success"}}
        code, out = gate(self.api(runs, jobs))
        self.assertEqual(code, 1)
        self.assertIn("::error::hub-mariadb is failure on " + LATER, out)

    def test_timed_out_suite_is_red(self):
        code, out = gate(self.api([maria(5, TAG)], {5: {"hub-mariadb": "cancelled"}}))
        self.assertEqual(code, 1)
        self.assertIn("hub-mariadb is cancelled", out)

    def test_a_red_11_8_job_stops_a_green_11_4_suite(self):
        for result in ("failure", "cancelled", "timed_out", "skipped"):
            jobs = {5: {"hub-mariadb": "success", "hub-mariadb-11-8": result}}
            code, out = gate(self.api([maria(5, TAG)], jobs))
            self.assertEqual(code, 1, result)
            self.assertIn("::error::hub-mariadb-11-8 is " + result + " on " + TAG, out)

    def test_both_red_are_named(self):
        jobs = {5: {"hub-mariadb": "failure", "hub-mariadb-11-8": "failure"}}
        code, out = gate(self.api([maria(5, TAG)], jobs))
        self.assertEqual(code, 1)
        self.assertIn("hub-mariadb is failure, hub-mariadb-11-8 is failure on " + TAG, out)

    def test_both_green_pass(self):
        jobs = {5: {"decide": "success", "hub-mariadb": "success", "hub-mariadb-11-8": "success"}}
        code, out = gate(self.api([maria(5, TAG)], jobs))
        self.assertEqual(code, 0, out)
        self.assertIn("hub-mariadb passed on " + TAG, out)
        self.assertNotIn("predates", out)

    def gate_on(self, head, jobs):
        """The gate on one green-CI hand run from main at head that tested TAG."""
        runs = [maria(5, head, "hub-mariadb hand " + TAG)]
        return gate(FakeApi(ci=GREEN_CI["ci"], maria=runs, jobs={**GREEN_CI["jobs"], 5: jobs}))

    def test_a_run_from_before_the_11_8_job_counts_on_11_4_alone(self):
        # A hand run from main at OLD, a commit from before 4fafdf1f added hub-mariadb-11-8.
        code, out = self.gate_on(OLD, {"hub-mariadb": "success"})
        self.assertEqual(code, 0, out)
        self.assertIn("(its commit predates hub-mariadb-11-8)", out)

    def test_a_run_after_the_11_8_job_needs_it(self):
        # Missing (a partial re-run, a renamed job), skipped or red: never "predates".
        for result in (None, "skipped", "failure", "cancelled"):
            with self.subTest(result=result):
                listed = {} if result is None else {"hub-mariadb-11-8": result}
                code, out = self.gate_on(TAG, {"hub-mariadb": "success", **listed})
                self.assertEqual(code, 1, out)
                self.assertIn(f"::error::hub-mariadb-11-8 is {result or 'missing'} on " + TAG, out)
                self.assertNotIn("predates", out)

    def test_a_run_before_the_11_8_job_that_lists_it_red_stops(self):
        code, out = self.gate_on(OLD, {"hub-mariadb": "success", "hub-mariadb-11-8": "failure"})
        self.assertEqual(code, 1, out)
        self.assertIn("::error::hub-mariadb-11-8 is failure on " + TAG, out)

    def test_ancestry_that_cannot_be_told_stops(self):
        # A shallow checkout or a commit it cannot get: never "predates".
        for listed in ({}, {"hub-mariadb-11-8": "success"}):
            with self.subTest(listed=listed):
                code, out = self.gate_on(NO_HISTORY, {"hub-mariadb": "success", **listed})
                self.assertEqual(code, 1, out)
                self.assertIn("::error::cannot tell whether " + NO_HISTORY, out)
                self.assertIn("4fafdf1f80dedf7c50016d133984b013d8719588", out)

    def test_a_hub_mariadb_job_the_table_does_not_know_stops(self):
        for head in (TAG, OLD):
            with self.subTest(head=head):
                code, out = self.gate_on(
                    head,
                    {
                        "hub-mariadb": "success",
                        "hub-mariadb-11-8": "success",
                        "hub-mariadb-12": "x",
                    },
                )
                self.assertEqual(code, 1, out)
                self.assertIn(
                    "::error::the run lists hub-mariadb-12, which tools/release_gate.py", out
                )

    def test_a_red_11_8_beside_a_skipped_suite_stops_instead_of_an_older_green_run(self):
        runs = [maria(6, TAG), maria(5, TAG)]
        for result in ("failure", "cancelled"):
            jobs = {
                6: {"hub-mariadb": "skipped", "hub-mariadb-11-8": result},
                5: {"hub-mariadb": "success"},
            }
            code, out = gate(self.api(runs, jobs))
            self.assertEqual(code, 1, result)
            self.assertIn("hub-mariadb is skipped, hub-mariadb-11-8 is " + result, out)

    def test_both_skipped_still_counts_for_nothing(self):
        runs = [maria(6, TAG), maria(5, TAG)]
        jobs = {
            6: {"hub-mariadb": "skipped", "hub-mariadb-11-8": "skipped"},
            5: {"hub-mariadb": "success"},
        }
        code, out = gate(self.api(runs, jobs))
        self.assertEqual(code, 0, out)

    def test_hand_run_counts_by_the_sha_in_its_title(self):
        # Its head_sha is main's head (OTHER); the title names what it tested.
        runs = [maria(5, OTHER, "hub-mariadb hand " + TAG)]
        code, out = gate(self.api(runs, {5: {"hub-mariadb": "success"}}))
        self.assertEqual(code, 0, out)

    def test_hand_run_on_head_counts_by_head_sha(self):
        code, out = gate(
            self.api([maria(5, TAG, "hub-mariadb hand head")], {5: {"hub-mariadb": "success"}})
        )
        self.assertEqual(code, 0, out)

    def test_old_or_short_hand_titles_are_left_out(self):
        for title in (
            "hub-mariadb hand",
            "hub-mariadb hand " + TAG[:12],
            "hub-mariadb hand " + TAG.upper(),
        ):
            code, _out = gate(self.api([maria(5, TAG, title)], {5: {"hub-mariadb": "success"}}))
            self.assertEqual(code, 1, title)

    def test_runs_off_main_are_left_out(self):
        # Off main, hub-mariadb.yml's run-name gives a hand title whatever the trigger.
        green = {5: {"hub-mariadb": "success"}}
        for title, event in (
            ("hub-mariadb ci", "workflow_dispatch"),
            ("hub-mariadb hand head", "workflow_dispatch"),
            ("hub-mariadb hand " + TAG, "workflow_dispatch"),
            ("hub-mariadb schedule", "schedule"),
        ):
            runs = [run(5, sha=TAG, event=event, title=title, branch="v0.1.0a2")]
            code, out = gate(self.api(runs, green))
            self.assertEqual(code, 1, title)
            self.assertIn("no hub-mariadb run tested", out)

    def test_not_asked_while_ci_is_red(self):
        api = FakeApi(
            ci=[run(1)],
            maria=[maria(5, TAG)],
            jobs={1: {"ci-ok": "failure"}, 5: {"hub-mariadb": "success"}},
        )
        code, out = gate(api)
        self.assertEqual(code, 1)
        self.assertNotIn("hub-mariadb", out)

    def test_waits_for_a_running_suite(self):
        states = iter([[maria(5, TAG, status="in_progress")], [maria(5, TAG)]])
        api = self.api(lambda: next(states), {5: {"hub-mariadb": "success"}})
        code, out = gate(api, wait=600)
        self.assertEqual(code, 0, out)

    def test_grace_for_the_run_ci_starts(self):
        # ci-ok just passed; the run ci starts shows up a look later.
        states = iter([[], [maria(5, TAG)]])
        code, out = gate(self.api(lambda: next(states), {5: {"hub-mariadb": "success"}}), wait=600)
        self.assertEqual(code, 0, out)

    def test_missing_run_stops_after_the_grace(self):
        looks = []
        code, out = gate(self.api([], {}), wait=600, looks=looks)
        self.assertEqual(code, 1)
        self.assertEqual(len(looks), 2)
        self.assertIn("start it by hand", out)


class Provenance(unittest.TestCase):
    """Only main's own hub-mariadb.yml can vouch for a commit."""

    def api(self, runs, jobs):
        return FakeApi(ci=GREEN_CI["ci"], maria=runs, jobs={**GREEN_CI["jobs"], **with_11_8(jobs)})

    def test_hand_run_dispatched_on_a_branch_is_refused(self):
        # The branch's copy of the workflow keeps the title and the job name.
        r = run(
            5,
            sha=BRANCH,
            event="workflow_dispatch",
            title="hub-mariadb hand " + TAG,
            branch="x/no-suite",
        )
        code, out = gate(self.api([r], {5: {"hub-mariadb": "success"}}))
        self.assertEqual(code, 1)
        self.assertIn("no hub-mariadb run tested", out)

    def test_hand_run_on_a_ref_called_main_that_is_not_main_is_refused(self):
        # A tag named main, say: head_branch says main, the commit is not on it.
        r = run(5, sha=BRANCH, event="workflow_dispatch", title="hub-mariadb hand " + TAG)
        code, out = gate(self.api([r], {5: {"hub-mariadb": "success"}}))
        self.assertEqual(code, 1, out)

    def test_hand_run_from_main_is_accepted(self):
        r = run(5, sha=OTHER, event="workflow_dispatch", title="hub-mariadb hand " + TAG)
        code, out = gate(self.api([r], {5: {"hub-mariadb": "success"}}))
        self.assertEqual(code, 0, out)

    def test_commit_that_cannot_be_compared_stops_instead_of_being_skipped(self):
        # A newer red run on a commit the checkout lacks must not be passed over for an older
        # green one: neither when its own commit is unknown nor when the commit it tested is.
        green = {5: {"hub-mariadb": "success"}}
        for newer, message in (
            (
                maria(6, UNKNOWN, "hub-mariadb schedule", "schedule"),
                "cannot tell whether " + UNKNOWN,
            ),
            (
                maria(6, OTHER, "hub-mariadb hand " + UNKNOWN),
                "cannot compare the hub files of " + UNKNOWN,
            ),
        ):
            code, out = gate(
                self.api([newer, maria(5, TAG)], {6: {"hub-mariadb": "failure"}, **green})
            )
            self.assertEqual(code, 1, out)
            self.assertIn("::error::" + message, out)

    def test_newer_matching_run_still_going_is_waited_for(self):
        states = iter(
            [
                [maria(6, LATER, "hub-mariadb hand " + TAG, status="in_progress"), maria(5, TAG)],
                [maria(6, LATER, "hub-mariadb hand " + TAG), maria(5, TAG)],
            ]
        )
        jobs = {6: {"hub-mariadb": "failure"}, 5: {"hub-mariadb": "success"}}
        looks = []
        code, out = gate(self.api(lambda: next(states), jobs), wait=600, looks=looks)
        self.assertEqual(code, 1)
        self.assertEqual(looks, [60])
        self.assertIn("is in_progress", out)
        self.assertIn("::error::hub-mariadb is failure", out)

    def test_newer_run_on_other_files_still_going_is_not_waited_for(self):
        runs = [maria(6, OTHER, status="in_progress"), maria(5, TAG)]
        code, out = gate(self.api(runs, {5: {"hub-mariadb": "success"}}))
        self.assertEqual(code, 0, out)


class RealGit(unittest.TestCase):
    """Git against a throwaway repository with an origin."""

    def setUp(self):
        import subprocess
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.origin, self.work = root / "origin", root / "work"

        def git(cwd, *args):
            return subprocess.run(
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

        self.git = git
        self.origin.mkdir()
        git(self.origin, "init", "-q", "-b", "main")
        (self.origin / "hub").mkdir()
        (self.origin / "hub" / "a.py").write_text("1\n")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "one")
        self.one = git(self.origin, "rev-parse", "HEAD")
        (self.origin / "web.txt").write_text("web\n")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "web only")
        self.web = git(self.origin, "rev-parse", "HEAD")
        git(self.origin, "clone", "-q", str(self.origin), str(self.work))
        (self.origin / "hub" / "a.py").write_text("2\n")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "hub change, after the clone")
        self.hub = git(self.origin, "rev-parse", "HEAD")
        git(self.origin, "checkout", "-q", "-b", "side", self.one)
        (self.origin / "side.txt").write_text("x\n")
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", "side")
        self.side = git(self.origin, "rev-parse", "HEAD")
        git(self.origin, "checkout", "-q", "main")
        git(self.origin, "config", "uploadpack.allowAnySHA1InWant", "true")

    def check(self):
        cwd = Path.cwd()
        import os

        os.chdir(self.work)
        self.addCleanup(os.chdir, cwd)
        return g.Git()

    def test_same_fetches_a_commit_the_checkout_lacks(self):
        git = self.check()
        self.assertIs(git.same(self.one, self.web), True)
        self.assertIs(git.same(self.web, self.hub), False)  # self.hub was fetched for this

    def test_contains_reads_ancestry_and_fails_closed(self):
        git = self.check()
        self.assertIs(git.contains(self.one, self.hub), True)  # self.hub was fetched for this
        self.assertIs(git.contains(self.hub, self.one), False)
        self.assertIs(git.contains(self.web, self.side), False)  # another branch
        self.assertIsNone(git.contains(self.one, "e" * 40))  # a commit it cannot get
        self.assertIsNone(git.contains("e" * 40, self.hub))

    def test_contains_in_a_shallow_checkout_is_none(self):
        # A cut history would read "not an ancestor", the answer that lets a run skip a job.
        shallow = Path(self.tmp.name) / "shallow"
        self.git(self.origin, "clone", "-q", "--depth", "1", f"file://{self.origin}", str(shallow))
        cwd = Path.cwd()
        os.chdir(shallow)
        self.addCleanup(os.chdir, cwd)
        self.assertIsNone(g.Git().contains(self.one, self.hub))

    def test_unknown_commit_is_none_not_different(self):
        git = self.check()
        self.assertIsNone(git.same(self.one, "f" * 40))
        self.assertIsNone(git.on_main("f" * 40))

    def test_on_main_reads_the_fetched_main(self):
        git = self.check()
        self.assertIs(git.on_main(self.hub), True)  # newer than the clone
        self.assertIs(git.on_main(self.side), False)


class Workflows(unittest.TestCase):
    def test_hub_mariadb_defines_the_jobs_the_gate_requires_under_their_ids(self):
        # The gate looks the jobs up by name in the jobs API: the same as their keys only
        # while no job of the file sets a `name:` of its own.
        text = (ROOT / ".github/workflows/hub-mariadb.yml").read_text(encoding="utf-8")
        for job in ("hub-mariadb", *g.MARIADB_EXTRA_JOBS):
            self.assertRegex(text, rf"(?m)^  {re.escape(job)}:$")
        self.assertNotRegex(text, r"(?m)^    name:")

    def test_each_extra_job_was_added_by_its_commit(self):
        # The table's commit is the one whose hub-mariadb.yml first has the job. Needs each
        # commit and its parent: skipped in a local checkout that lacks them, failed on GitHub
        # Actions, where ci.yml's changelog job fetches them (a skip there would hide the check).
        import os
        import subprocess

        def show(rev):
            return subprocess.run(
                ["git", "show", f"{rev}:.github/workflows/hub-mariadb.yml"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

        for job, added in g.MARIADB_EXTRA_JOBS.items():
            with self.subTest(job):
                at, before = show(added), show(added + "^")
                if at.returncode != 0 or before.returncode != 0:
                    missing = f"{added} or its parent is not in this checkout"
                    if os.environ.get("GITHUB_ACTIONS") == "true":
                        self.fail(missing + " (ci.yml's changelog job fetches them)")
                    self.skipTest(missing)
                self.assertRegex(at.stdout, rf"(?m)^  {re.escape(job)}:$")
                self.assertNotRegex(before.stdout, rf"(?m)^  {re.escape(job)}:$")

    def test_the_mariadb_gate_jobs_check_out_the_full_history(self):
        # The ancestry test needs it; a shallow checkout makes the gate stop, never pass.
        for name, job in (("release-hub.yml", "check"), ("publish-image.yml", "gate")):
            with self.subTest(name):
                text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
                body = re.search(rf"(?ms)^  {job}:\n(.*?)(?=^  \S)", text).group(1)
                self.assertIn("--mariadb", body)
                self.assertRegex(body, r"fetch-depth: 0\b")

    def test_paths_match_decide_in_hub_mariadb(self):
        text = (ROOT / ".github/workflows/hub-mariadb.yml").read_text(encoding="utf-8")
        line = re.search(r'git diff --name-only "\$base" "\$sha" -- (.+)\)"', text).group(1)
        self.assertEqual(tuple(p.strip("'") for p in line.split()), g.MARIADB_PATHS)

    def test_every_release_runs_the_gate_before_it_builds_or_publishes(self):
        for name, job, mariadb in (
            ("release-hub.yml", "check", True),
            ("release-cli.yml", "check", False),
            ("publish-image.yml", "gate", True),
        ):
            text = (ROOT / ".github/workflows" / name).read_text(encoding="utf-8")
            self.assertIn('python tools/release_gate.py --sha "$GITHUB_SHA"', text, name)
            self.assertEqual("--mariadb" in text, mariadb, name)
            # The hub's releases (package and image) ask for the version's upgrade page.
            self.assertEqual("--upgrade-page" in text, mariadb, name)
            self.assertNotIn("make check", text, name)
            dependent = "publish" if name.startswith("release") else "image"
            block = text[text.index(f"\n  {dependent}:") :]
            self.assertRegex(block, rf"needs: (\[[^\]]*\b{job}\b[^\]]*\]|{job})", name)

    def test_the_image_is_built_only_for_a_v_tag(self):
        # No hand start and no branch: an image from main is signed as
        # refs/heads/main and never deployed (req-ry02xngnedjq).
        text = (ROOT / ".github/workflows/publish-image.yml").read_text(encoding="utf-8")
        on = re.search(r"^on:\n((?:[ #].*\n|\n)*)", text, re.M).group(1)
        triggers = [line.strip() for line in on.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        self.assertEqual(triggers, ["push:", 'tags: ["v*"]'])
        self.assertNotIn("workflow_dispatch", text)
        self.assertNotIn("branches", on)
        gate_job = text[text.index("\n  gate:") : text.index("\n  image:")]
        image_job = text[text.index("\n  image:") : text.index("\n  sign:")]
        for job in (gate_job, image_job):
            condition = job[job.index("\n    if:") : job.index("\n    runs-on:")]
            self.assertIn("github.ref_type == 'tag' && startsWith(github.ref_name, 'v')", condition)
            self.assertNotIn("refs/heads", condition)
            self.assertNotIn("||", condition)
        # The image is built only after the gate passed, never when it was skipped.
        self.assertIn("needs.gate.result == 'success' &&", image_job)
        self.assertNotIn("'skipped'", image_job)
        self.assertNotIn("always()", image_job)

    def test_the_documented_verify_accepts_only_a_tag_signature(self):
        # Every deploy is a release: a signature from main is refused.
        text = (ROOT / "deploy/helm/maity-hub/README.md").read_text(encoding="utf-8")
        identities = re.findall(r"--certificate-identity-regexp '([^']*)'", text)
        self.assertEqual(
            identities,
            [
                r"^https://github\.com/oliver-zehentleitner/maity/"
                r"\.github/workflows/publish-image\.yml@refs/tags/v[^/]+$"
            ],
        )
        self.assertNotIn("heads/main", identities[0])

    def test_hand_title_names_the_tested_commit(self):
        text = (ROOT / ".github/workflows/hub-mariadb.yml").read_text(encoding="utf-8")
        self.assertIn("format('hand {0}', inputs.sha || 'head')", text)


class ApiErrors(unittest.TestCase):
    """An API error ends the gate with an error, never with a pass."""

    def test_errors_propagate_and_fail(self):
        import urllib.error

        for error in (
            urllib.error.HTTPError("u", 502, "Bad Gateway", None, None),
            urllib.error.URLError("down"),
            ValueError("not JSON"),
        ):

            class Broken(FakeApi):
                def get(self, path, error=error, **params):
                    if path == "actions/workflows/hub-mariadb.yml/runs":
                        raise error
                    return super().get(path, **params)

            with self.assertRaises(type(error)):
                gate(Broken(**GREEN_CI))

            class BrokenCi(FakeApi):
                def get(self, path, error=error, **params):
                    raise error

            with self.assertRaises(type(error)):
                gate(BrokenCi(), mariadb=False)

    def test_api_get_raises_instead_of_answering_empty(self):
        import urllib.error
        from unittest import mock

        api = g.Api("o/r", "t", base="https://example.test")
        for error in (
            urllib.error.HTTPError("u", 403, "Forbidden", None, None),
            urllib.error.URLError("down"),
        ):
            with (
                mock.patch.object(g.urllib.request, "urlopen", side_effect=error),
                self.assertRaises(type(error)),
            ):
                api.get("actions/workflows/ci.yml/runs", head_sha=TAG)
        with (
            mock.patch.object(g.urllib.request, "urlopen", return_value=io.BytesIO(b"<html>")),
            self.assertRaises(ValueError),
        ):
            api.get("actions/workflows/ci.yml/runs")


class Main(unittest.TestCase):
    def test_short_sha_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            g.main(["--sha", "abc123"])

    def test_a_missing_upgrade_page_stops_before_any_api_call(self):
        failing = g.State("fail", "docs/upgrade/0.1.0a9.md is missing")
        with mock.patch.object(g, "page_state", return_value=failing), mock.patch.object(
            g, "Api", side_effect=AssertionError("no API call")
        ):
            self.assertEqual(g.main(["--sha", TAG, "--upgrade-page"]), 1)

    def test_the_page_check_gets_the_tag_only_on_a_tag_run(self):
        failing = g.State("fail", "x")
        for env, tag in (
            ({"GITHUB_REF_TYPE": "tag", "GITHUB_REF_NAME": "v0.1.0a9"}, "v0.1.0a9"),
            ({"GITHUB_REF_TYPE": "branch", "GITHUB_REF_NAME": "main"}, None),
            ({}, None),
        ):
            with self.subTest(env=env), mock.patch.dict(os.environ, env):
                for k in ("GITHUB_REF_TYPE", "GITHUB_REF_NAME"):
                    if k not in env:
                        os.environ.pop(k, None)
                with mock.patch.object(g, "page_state", return_value=failing) as page:
                    self.assertEqual(g.main(["--sha", TAG, "--upgrade-page"]), 1)
                page.assert_called_once_with(tag=tag)


class UpgradePage(unittest.TestCase):
    def page_state(self, page, tag=None):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "hub").mkdir()
            (root / "hub" / "pyproject.toml").write_text('version = "0.1.0a9"\n', encoding="utf-8")
            if page is not None:
                (root / "docs" / "upgrade").mkdir(parents=True)
                (root / "docs" / "upgrade" / "0.1.0a9.md").write_text(page, encoding="utf-8")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                state = g.page_state(root, tag)
        return state, out.getvalue()

    COMPLETE = "".join(f"## {s}\n\nNothing.\n\n" for s in upgrade_page.SECTIONS)

    def test_a_tag_of_the_pyproject_version_passes(self):
        state, _ = self.page_state(self.COMPLETE, "v0.1.0a9")
        self.assertEqual(state.kind, "ok")

    def test_a_tag_of_another_version_fails_even_with_a_complete_page(self):
        state, out = self.page_state(self.COMPLETE, "v0.1.0a10")
        self.assertEqual(state.kind, "fail")
        self.assertIn("::error::the tag v0.1.0a10 is not v0.1.0a9", out)

    def test_the_tagged_versions_page_must_exist(self):
        state, out = self.page_state(None)
        self.assertEqual(state.kind, "fail")
        self.assertIn("::error::docs/upgrade/0.1.0a9.md is missing", out)

    def test_a_complete_page_passes(self):
        page = "".join(f"## {s}\n\nNothing.\n\n" for s in upgrade_page.SECTIONS)
        state, _ = self.page_state(page)
        self.assertEqual(state.kind, "ok")


if __name__ == "__main__":
    unittest.main()
