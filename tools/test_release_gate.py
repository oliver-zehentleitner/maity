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


OLD = "f" * 40  # a commit of main whose hub-mariadb.yml predates hub-mariadb-11-8
UNREADABLE = "9" * 40  # a commit of main whose workflow file cannot be read
NO_SUITE = "8" * 40  # a commit of main whose workflow file reads without a hub-mariadb job
WRAPPED = "7" * 40  # today's hub-mariadb.yml with a hub-mariadb value wrapped to column 0
WRAPPED_KEY = "6" * 40  # the same, where the wrapped line spells a top-level key (`env:`)


def wrapped_workflow(value):
    """Today's hub-mariadb.yml with `value` under the hub-mariadb job, before hub-mariadb-11-8.

    YAML reads such a value (a quoted string or flow collection continued at column 0) as one
    value of that job, and all four jobs; the gate's reader must not end the jobs block there."""
    text = (ROOT / ".github/workflows/hub-mariadb.yml").read_text(encoding="utf-8")
    return text.replace("\n  hub-mariadb:\n", "\n  hub-mariadb:\n    x-wrapped:\n" + value, 1)


WRAPPED_FORMS = {
    "a double-quoted string": '      NOTE: "first\nsecond line"\n',
    "a single-quoted string": "      NOTE: 'first\nsecond line'\n",
    "a flow map": "      NOTE: {a: 1,\nb: 2}\n",
    "a flow sequence": "      NOTE: [a,\nb]\n",
}
J = "  hub-mariadb-11-8:\n    runs-on: u\n"
H = "jobs:\n  hub-mariadb:\n"
BOTH = {"hub-mariadb", "hub-mariadb-11-8"}
# The reviews' reproducers (#2025 round 1) and what PyYAML reads from each: None where it reads
# no jobs: key or refuses the file.
REPRODUCERS = {
    "an open single-quoted value ending in ''": (H + "    x: 'first''\nenv: second'\n" + J, BOTH),
    "an escaped quote in an open flow value": (H + '    x: ["a\\" ]",\nenv: 1]\n' + J, BOTH),
    "a comment in an open flow value": (H + "    x: [a, # ]\nenv: 1]\n" + J, BOTH),
    "an apostrophe before a quoted flow item": (
        H + "    x: [it's, 'still open ]',\nenv: 1]\n" + J,
        BOTH,
    ),
    "a sequence item, double-quoted": (H + '    needs:\n      - "first\nenv: second"\n' + J, BOTH),
    "a sequence item, flow": (H + "    needs:\n      - [first,\nenv: second]\n" + J, BOTH),
    "jobs: inside a sequence item under on:": (
        'on:\n- "hello\njobs:\n  hub-mariadb:\n    runs-on: u\nenv: x"\n',
        None,
    ),
    "a value on the next line, quoted": (
        H + '    env:\n      NOTE:\n        "first\nenv: second"\n' + J,
        BOTH,
    ),
    "a value on the next line, flow": (H + "    needs:\n      [decide,\nenv: x]\n" + J, BOTH),
    "a dotted key": (H + '    env:\n      a.b: "first\nenv: second"\n' + J, BOTH),
    "a quoted key with a space": (H + '    env:\n      "a b": "first\nenv: second"\n' + J, BOTH),
    "an anchored quoted value": (H + '    x: &a "first\nenv: second"\n' + J, BOTH),
    "a tagged quoted value": (H + '    x: !!str "first\nenv: second"\n' + J, BOTH),
    "an anchored flow value": (H + "    x: &a [first,\nenv: second]\n" + J, BOTH),
    "an open 'it''s": (H + "    x: 'it''s\nenv: x'\n" + J, BOTH),
    "an open flow value with an escape": (H + '    x: ["a\\"]\nenv: x"]\n' + J, BOTH),
    "a plain value wrapped to column 0": (H + "    x: first\nenv: second\n" + J, None),
}
# One-line values the reader must read, as PyYAML does (round 1 read the first two as None).
READ_AS_YAML = {
    "an escaped quote in a closed flow value": H + '    x: ["a\\"b"]\n' + J,
    "an apostrophe in a plain flow word": H + "    x: [don't]\n" + J,
    "a sequence-item block scalar": H + '    steps:\n      - |\n        note: "open\n' + J,
    "a comment after a closed quote": H + "    x: \"a\" # \"\n    y: 'b'  # '\n" + J,
    "a closed flow value with a comment": H + "    x: [a, {b: c}]  # ]\n" + J,
    "a closed doubled quote": H + "    x: 'it''s'\n" + J,
}
OPEN_QUOTE = "5" * 40  # a review's reproducer: 'first'' left open, then `env: second'` at column 0
WORKFLOW_TEXTS = {
    OPEN_QUOTE: REPRODUCERS["an open single-quoted value ending in ''"][0],
    WRAPPED: wrapped_workflow(WRAPPED_FORMS["a double-quoted string"]),
    WRAPPED_KEY: wrapped_workflow('      NOTE: "first\nenv: second"\n'),
}
ALL_JOBS = {"decide", "hub-mariadb", "hub-mariadb-11-8", "report"}


class FakeGit:
    """TAG and LATER share the hub files; OTHER differs; BRANCH is not on main."""

    def workflow_jobs(self, sha):
        if sha in (UNKNOWN, UNREADABLE):
            return None
        if sha == NO_SUITE:
            return {"decide", "report"}
        if sha in WORKFLOW_TEXTS:
            return g.workflow_job_ids(WORKFLOW_TEXTS[sha])  # the real reader on a real layout
        return ALL_JOBS - {"hub-mariadb-11-8"} if sha == OLD else ALL_JOBS

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

    def test_a_run_whose_workflow_predates_the_11_8_job_counts_on_11_4_alone(self):
        # A hand run from main at OLD, whose hub-mariadb.yml has no 11.8 job yet.
        runs = [maria(5, OLD, "hub-mariadb hand " + TAG)]
        api = FakeApi(
            ci=GREEN_CI["ci"], maria=runs, jobs={**GREEN_CI["jobs"], 5: {"hub-mariadb": "success"}}
        )
        code, out = gate(api)
        self.assertEqual(code, 0, out)
        self.assertIn("its workflow file has no hub-mariadb-11-8: it predates it", out)

    def test_a_missing_11_8_job_the_workflow_defines_stops(self):
        # Renamed, a partial re-run, an answer without it: absent is not "predates".
        api = FakeApi(
            ci=GREEN_CI["ci"],
            maria=[maria(5, TAG)],
            jobs={**GREEN_CI["jobs"], 5: {"hub-mariadb": "success"}},
        )
        code, out = gate(api)
        self.assertEqual(code, 1, out)
        self.assertIn("::error::hub-mariadb-11-8 is missing on " + TAG, out)

    def test_a_workflow_file_that_cannot_be_read_stops(self):
        runs = [maria(5, UNREADABLE, "hub-mariadb hand " + TAG)]
        code, out = gate(self.api(runs, {5: {"hub-mariadb": "success"}}))
        self.assertEqual(code, 1, out)
        self.assertIn(
            "::error::cannot read .github/workflows/hub-mariadb.yml at " + UNREADABLE, out
        )

    def test_a_workflow_file_without_a_hub_mariadb_job_stops_instead_of_predating(self):
        # The reader missed the block (or the suite's job is gone): 11.4 must not count alone.
        runs = [maria(5, NO_SUITE, "hub-mariadb hand " + TAG)]
        code, out = gate(self.api(runs, {5: {"hub-mariadb": "success"}}))
        self.assertEqual(code, 1, out)
        self.assertIn(
            "::error::no hub-mariadb job read from .github/workflows/hub-mariadb.yml", out
        )
        self.assertNotIn("predates", out)

    def test_a_value_wrapped_to_column_0_does_not_let_a_red_11_8_pass(self):
        # The reader read {decide, hub-mariadb} here before: 11.8 "predated" the file, exit 0.
        for sha in (WRAPPED, WRAPPED_KEY, OPEN_QUOTE):
            stop = "::error::cannot read .github/workflows/hub-mariadb.yml at " + sha
            for result in ("failure", "success", None):
                with self.subTest(sha=sha, result=result):
                    # None: the run's list omits 11.8, so only the reader can stop the gate.
                    listed = {} if result is None else {"hub-mariadb-11-8": result}
                    jobs = {5: {"hub-mariadb": "success", **listed}}
                    runs = [maria(5, sha, "hub-mariadb hand " + TAG)]
                    code, out = gate(
                        FakeApi(ci=GREEN_CI["ci"], maria=runs, jobs={**GREEN_CI["jobs"], **jobs})
                    )
                    self.assertEqual(code, 1, out)
                    self.assertIn(stop, out)
                    self.assertNotIn("predates", out)

    def test_a_run_listing_a_hub_mariadb_job_its_file_lacks_stops(self):
        # Whatever the reader missed: the run's own job list names a job the file did not give.
        # (OLD's file reads without hub-mariadb-11-8; this run lists it, red.)
        runs = [maria(5, OLD, "hub-mariadb hand " + TAG)]
        jobs = {5: {"hub-mariadb": "success", "hub-mariadb-11-8": "failure"}}
        code, out = gate(FakeApi(ci=GREEN_CI["ci"], maria=runs, jobs={**GREEN_CI["jobs"], **jobs}))
        self.assertEqual(code, 1, out)
        self.assertIn("::error::the run lists hub-mariadb-11-8, which the gate did not read", out)

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

    def test_workflow_jobs_reads_the_file_at_the_commit_and_fails_closed(self):
        wf = self.origin / ".github" / "workflows"
        wf.mkdir(parents=True)
        (wf / "hub-mariadb.yml").write_text("on: push\njobs:\n  hub-mariadb:\n    x: 1\n")
        self.git(self.origin, "add", "-A")
        self.git(self.origin, "commit", "-q", "-m", "workflow")
        with_file = self.git(self.origin, "rev-parse", "HEAD")
        git = self.check()
        self.assertEqual(git.workflow_jobs(with_file), {"hub-mariadb"})  # fetched for this
        self.assertIsNone(git.workflow_jobs(self.one))  # the file is not there
        self.assertIsNone(git.workflow_jobs("e" * 40))  # nor the commit

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
        # The gate reads job ids from the file and looks them up by name in the jobs API:
        # the same only while no job of the file sets a `name:` of its own.
        text = (ROOT / ".github/workflows/hub-mariadb.yml").read_text(encoding="utf-8")
        ids = g.workflow_job_ids(text)
        self.assertEqual(ids, ALL_JOBS)
        self.assertTrue({"hub-mariadb", *g.MARIADB_EXTRA_JOBS} <= ids)
        self.assertNotRegex(text, r"(?m)^    name:")

    def test_job_ids_are_read_from_the_jobs_block_only(self):
        text = "on:\n  push:\nenv:\n  c: 1\njobs:\n  a:\n    steps: []\n  b-1:  # note\n    x: 1\n"
        self.assertEqual(g.workflow_job_ids(text), {"a", "b-1"})

    def test_job_ids_in_other_block_layouts_are_read(self):
        layouts = {
            "a comment after jobs:": "on: push\njobs:  # the suites\n  a:\n    x: 1\n  b:\n",
            "quoted keys": 'on: push\n"jobs":\n  "a":\n    x: 1\n  \'b\' :\n    x: 2\n',
            "four spaces": "on: push\njobs:\n    a:\n        x: 1\n    b:\n        x: 2\n",
            "one space": "on: push\njobs:\n a:\n  x: 1\n b: {x: 2}\n",
            "comments and blank lines between": (
                "jobs:\n# top\n\n  a:\n      # deep\n    x: 1\n    # under a\n  b:\n"
            ),
            "a block scalar in a job": "jobs:\n  a:\n    run: |\n      b:\n      c: 1\n  b:\n",
            "comment lines at column 0 in jobs:": "jobs:\n# a\n  a:\n# b\n    x: 1\n  b:\n# end\n",
        }
        for layout, text in layouts.items():
            with self.subTest(layout):
                self.assertEqual(g.workflow_job_ids(text), {"a", "b"})

    def test_a_job_value_wrapped_to_column_0_is_none(self):
        for form, value in WRAPPED_FORMS.items():
            with self.subTest(form):
                self.assertIsNone(g.workflow_job_ids(wrapped_workflow(value)))

    def test_lines_break_where_yaml_breaks_them(self):
        # U+2028, U+2029, U+0085, \x0b, \x0c, \x1c-\x1e are no line breaks in YAML: inside a
        # comment or a quoted value they must neither end the block nor start a job. CR alone
        # and CRLF are.
        jobs = "jobs:\n  hub-mariadb:\n{}  hub-mariadb-11-8:\n    runs-on: u\n"
        both = {"hub-mariadb", "hub-mariadb-11-8"}
        cases = {
            "U+2028 in a comment": (jobs.format("    # note\u2028more\n    runs-on: u\n"), both),
            "U+2028 in a comment, then a job's spelling": (
                "jobs:\n  hub-mariadb:\n    # note\u2028  hub-mariadb-11-8:\n    runs-on: u\n",
                {"hub-mariadb"},
            ),
            "U+2028 in a quoted value": (jobs.format('    run: "x\u2028y"\n'), both),
            "U+2029 and U+0085 in a quoted value": (
                jobs.format('    env:\n      A: "hello\u2029world\x85!"\n'),
                both,
            ),
            "\\x0b, \\x0c and \\x1c in a comment": (
                jobs.format("    # a\x0bb\x0cc\x1cd\n    runs-on: u\n"),
                both,
            ),
        }
        for case, (text, expected) in cases.items():
            with self.subTest(case):
                self.assertEqual(g.workflow_job_ids(text), expected)
        for eol in ("\r", "\r\n"):
            with self.subTest(repr(eol)):
                text = eol.join(["on: push", "jobs:  # x", "  a:", "    x: 1", "  b:", ""])
                self.assertEqual(g.workflow_job_ids(text), {"a", "b"})

    def test_markers_sequences_and_block_scalars_that_are_read(self):
        layouts = {
            "a document start first": "---\non: push\njobs:\n  a:\n  b:\n",
            "a sequence at column 0 under on:": "on:\n- push\n- pull_request\njobs:\n  a:\n  b:\n",
            "a block scalar with unclosed quotes in it": (
                'jobs:\n  a:\n    run: |\n      X: "open\n      Y: [1,\n  b:\n'
            ),
            "a step list with a block scalar": (
                "jobs:\n  a:\n    steps:\n      - run: |\n          K: 'x\n  b:\n"
            ),
            "closed quotes and flow values": (
                "jobs:\n  a:\n    x: \"a\\\"b\" # c\n    y: 'it''s'\n"
                '    z: [1, "]", {k: v}]\n  b:\n'
            ),
        }
        for layout, text in layouts.items():
            with self.subTest(layout):
                self.assertEqual(g.workflow_job_ids(text), {"a", "b"})

    def test_markers_roots_and_open_values_are_none(self):
        layouts = {
            "a root block scalar": "|\njobs:\n  hub-mariadb:\n",
            "a document end before jobs:": "on: push\n...\njobs:\n  hub-mariadb:\n    runs-on: u\n",
            "a document end inside jobs:": (
                "jobs:\n  hub-mariadb:\n    runs-on: u\n...\n  hub-mariadb-11-8:\n    runs-on: u\n"
            ),
            "a second document start": "on: push\n---\njobs:\n  hub-mariadb:\n",
            "jobs: inside a quoted name": 'name: "hello\njobs:\n  hub-mariadb: {}\n"\n',
            "a quoted value wrapped, indented": (
                'jobs:\n  hub-mariadb:\n    env:\n      X: "a\n      b"\n  hub-mariadb-11-8:\n'
            ),
            "a flow value wrapped, indented": (
                "jobs:\n  hub-mariadb:\n    needs: [a,\n      b]\n  hub-mariadb-11-8:\n"
            ),
            "a quote inside an open flow value": (
                'jobs:\n  hub-mariadb:\n    x: [a, "b]\n  c"]\n  hub-mariadb-11-8:\n'
            ),
            "a plain value wrapped to column 0": (
                "jobs:\n  hub-mariadb:\n    x: first\nsecond\n  hub-mariadb-11-8:\n"
            ),
        }
        for layout, text in layouts.items():
            with self.subTest(layout):
                self.assertIsNone(g.workflow_job_ids(text))

    def test_the_reviews_reproducers_read_as_yaml_reads_them_or_none(self):
        # Each from the reviews of #2025 round 1 (A1611, A1612), checked against PyYAML 6.0.3:
        # what it reads, or None where it reads no jobs or refuses the file. The reader may
        # answer None for any of them; it must never answer a set YAML does not read.
        both = {"hub-mariadb", "hub-mariadb-11-8"}
        for case, (text, yaml_jobs) in REPRODUCERS.items():
            with self.subTest(case):
                self.assertIn(g.workflow_job_ids(text), (None, yaml_jobs))
        for case, text in READ_AS_YAML.items():
            with self.subTest(case):
                self.assertEqual(g.workflow_job_ids(text), both)  # no false None

    def test_an_indented_continuation_never_hides_a_job(self):
        # A line deeper than the job keys is never read as a key, one at their indent always
        # is: a value continued on indented lines can add an id (a stricter gate), never drop
        # hub-mariadb-11-8.
        for pad in range(1, 8):
            for value in ("first", '"first', "[first,", "'first"):
                head = f"jobs:\n  hub-mariadb:\n    x: {value}\n{' ' * pad}"
                text = head + "hub-mariadb-zz: second\n  hub-mariadb-11-8:\n    runs-on: u\n"
                with self.subTest(pad=pad, value=value):
                    ids = g.workflow_job_ids(text)
                    if ids is not None:
                        self.assertTrue({"hub-mariadb", "hub-mariadb-11-8"} <= ids, ids)

    def test_a_workflow_whose_jobs_cannot_be_read_is_none_not_empty(self):
        # Empty would read hub-mariadb-11-8 as "predates it" and let 11.4 count alone.
        layouts = {
            "no jobs: at all": "on: push\nenv:\n  a: 1\n",
            "flow style jobs": "on: push\njobs: {hub-mariadb: {runs-on: x}}\n",
            "a flow style file": "{on: push, jobs: {hub-mariadb: {runs-on: x}}}\n",
            "an anchor on jobs:": "jobs: &all\n  hub-mariadb:\n    x: 1\n",
            "no colon space": "jobs:# x\n  hub-mariadb:\n",
            "an empty jobs:": "jobs:\non: push\n",
            "jobs: twice": "jobs:\n  a:\njobs:\n  b:\n",
            "a line shallower than the keys": "jobs:\n    a:\n      x: 1\n  b:\n",
            "a non-key at the keys' indent": "jobs:\n  - a\n  - b\n",
            "an explicit key": "jobs:\n  ? a\n  : x\n",
            "a tab in the indent": "jobs:\n\ta:\n\t\tx: 1\n",
            "a key that is no job id": "jobs:\n  a b:\n    x: 1\n",
        }
        for layout, text in layouts.items():
            with self.subTest(layout):
                self.assertIsNone(g.workflow_job_ids(text))

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
