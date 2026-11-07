"""Tests for tools/ci_watch.py, with `gh` and `maity say` faked.

Standard library only, so CI runs them without installing anything:
    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import contextlib
import io
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ci_watch  # noqa: E402

REPO = "o/r"
SHA = "a" * 40
NEWER = "b" * 40
BRANCH = "agent-b/thing"
AUTHOR = "maity-coder-claude-001#hrjz"


def run(
    run_id: int,
    created: str,
    *,
    status: str = "completed",
    conclusion: str | None = "success",
    branch: str = BRANCH,
    path: str = ci_watch.WORKFLOW,
    attempt: int = 1,
) -> dict[str, Any]:
    return {
        "id": run_id,
        "path": path,
        "head_branch": branch,
        "created_at": created,
        "status": status,
        "conclusion": conclusion,
        "run_attempt": attempt,
        "html_url": f"https://example.org/runs/{run_id}",
    }


class FakeGh:
    """Answers `gh api` paths from a table and records every call."""

    def __init__(
        self, pr: dict[str, Any] | None = None, runs: list[dict[str, Any]] | None = None
    ) -> None:
        self.pr = pr or {
            "state": "open",
            "merged": False,
            "mergeable_state": "clean",
            "head": {"sha": SHA, "ref": BRANCH},
        }
        self.runs = runs or []
        self.jobs: dict[tuple[int, int], list[dict[str, Any]]] = {}
        self.calls: list[str] = []
        self.fail = False

    def __call__(self, path: str) -> object:
        self.calls.append(path)
        if self.fail:
            raise ci_watch.Transient("gh api: HTTP 502")
        if path == f"repos/{REPO}/pulls/7":
            return self.pr
        if path.startswith(f"repos/{REPO}/actions/runs?"):
            return {"workflow_runs": self.runs}
        for (run_id, attempt), jobs in self.jobs.items():
            if path.startswith(f"repos/{REPO}/actions/runs/{run_id}/attempts/{attempt}/jobs"):
                return {"jobs": jobs}
        raise AssertionError(f"unexpected gh call {path}")


def jobs(**conclusions: str) -> list[dict[str, Any]]:
    return [{"name": name.replace("_", "-"), "conclusion": c} for name, c in conclusions.items()]


class QueueTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.queue = self.tmp / "ciwatch.txt"
        self.said: list[tuple[str, str]] = []

    def say(self, author: str, text: str) -> None:
        self.said.append((author, text))

    def lines(self) -> list[str]:
        return self.queue.read_text().splitlines()

    def add(self, pr: str = "7", sha: str = SHA, author: str = AUTHOR) -> None:
        ci_watch.add(self.queue, ci_watch.parse_entry(pr, sha, author))

    def one_pass(self, gh: FakeGh) -> int:
        return ci_watch.run_pass(self.queue, gh, self.say, REPO, log=io.StringIO())

    # --- the queue file ---

    def test_add_replaces_an_older_head_of_the_same_pull_request(self) -> None:
        self.add()
        self.add(pr="8")
        self.add(sha=NEWER)
        self.assertEqual(self.lines(), [f"8 {SHA} {AUTHOR}", f"7 {NEWER} {AUTHOR}"])

    def test_add_refuses_a_short_sha_a_path_and_a_bad_number(self) -> None:
        for pr, sha, author in [
            ("7", SHA[:7], AUTHOR),
            ("7", SHA.upper(), AUTHOR),
            ("7", SHA, "/home/x/.local/state/maity#hrjz"),
            ("7", SHA, "hrjz"),
            ("07", SHA, AUTHOR),
            ("x", SHA, AUTHOR),
        ]:
            with self.subTest(pr=pr, sha=sha, author=author), self.assertRaises(ci_watch.Refused):
                ci_watch.parse_entry(pr, sha, author)
        self.assertFalse(self.queue.exists())

    def test_remove(self) -> None:
        self.add()
        self.add(pr="8")
        self.assertTrue(ci_watch.remove(self.queue, 7))
        self.assertFalse(ci_watch.remove(self.queue, 7))
        self.assertEqual(self.lines(), [f"8 {SHA} {AUTHOR}"])

    # --- what is reported ---

    def test_green_is_reported_to_the_author_and_the_line_removed(self) -> None:
        self.add()
        gh = FakeGh(runs=[run(1, "2026-11-07T08:00:00Z")])
        gh.jobs[(1, 1)] = jobs(hub="success", ci_ok="success")
        self.assertEqual(self.one_pass(gh), 1)
        self.assertEqual(len(self.said), 1)
        author, text = self.said[0]
        self.assertEqual(author, AUTHOR)
        self.assertIn(f"#7 on {SHA}: ci-ok green", text)
        self.assertEqual(self.lines(), [])

    def test_red_is_reported_red_with_the_failed_jobs(self) -> None:
        self.add()
        gh = FakeGh(runs=[run(1, "2026-11-07T08:00:00Z", conclusion="failure")])
        gh.jobs[(1, 1)] = jobs(hub="failure", web="success", cli="timed_out", ci_ok="failure")
        self.one_pass(gh)
        text = self.said[0][1]
        self.assertIn("RED, ci-ok failure", text)
        self.assertIn("failed: cli, hub", text)
        self.assertNotIn("green", text)
        self.assertEqual(self.lines(), [])

    def test_an_old_green_push_run_on_the_same_sha_is_not_reported(self) -> None:
        # After a fast-forward, main's push run of this SHA is green; the pull request's own
        # run is still going. Only the latter counts.
        self.add()
        gh = FakeGh(
            runs=[
                run(1, "2026-11-07T07:00:00Z", branch="main"),
                run(2, "2026-11-07T08:00:00Z", status="in_progress", conclusion=None),
            ]
        )
        gh.jobs[(1, 1)] = jobs(ci_ok="success")
        self.assertEqual(self.one_pass(gh), 0)
        self.assertEqual(self.said, [])
        self.assertEqual(self.lines(), [f"7 {SHA} {AUTHOR}"])
        # The runs are asked for this head and pull_request events only.
        self.assertIn(f"head_sha={SHA}&event=pull_request", gh.calls[1])

    def test_the_newest_run_decides_over_an_older_green_one(self) -> None:
        self.add()
        gh = FakeGh(
            runs=[
                run(1, "2026-11-07T07:00:00Z"),
                run(2, "2026-11-07T08:00:00Z", conclusion="failure", attempt=2),
            ]
        )
        gh.jobs[(1, 1)] = jobs(ci_ok="success")
        gh.jobs[(2, 2)] = jobs(hub_postgresql="failure", ci_ok="failure")
        self.one_pass(gh)
        self.assertIn("RED", self.said[0][1])
        self.assertIn("failed: hub-postgresql", self.said[0][1])
        self.assertIn("runs/2/attempts/2/jobs", gh.calls[-1])

    def test_other_workflows_are_not_ci(self) -> None:
        self.add()
        gh = FakeGh(runs=[run(1, "2026-11-07T08:00:00Z", path=".github/workflows/audit.yml")])
        self.assertEqual(self.one_pass(gh), 0)
        self.assertEqual(self.lines(), [f"7 {SHA} {AUTHOR}"])

    def test_a_cancelled_run_without_ci_ok_is_red(self) -> None:
        self.add()
        gh = FakeGh(runs=[run(1, "2026-11-07T08:00:00Z", conclusion="cancelled")])
        gh.jobs[(1, 1)] = jobs(hub="cancelled")
        self.one_pass(gh)
        self.assertIn("RED, no ci-ok result (run cancelled); failed: hub", self.said[0][1])

    def test_a_moved_head_a_merge_a_close_and_a_conflict_are_reported_and_removed(self) -> None:
        cases: dict[str, dict[str, object]] = {
            "head moved": {"head": {"sha": NEWER, "ref": BRANCH}},
            "is merged": {"merged": True, "state": "closed"},
            "is closed": {"state": "closed"},
            "conflicts with main": {"mergeable_state": "dirty"},
        }
        for said, change in cases.items():
            with self.subTest(said):
                self.said.clear()
                self.add()
                gh = FakeGh()
                gh.pr.update(change)
                self.assertEqual(self.one_pass(gh), 1)
                self.assertIn(said, self.said[0][1])
                self.assertEqual(self.lines(), [])

    def test_no_run_yet_waits(self) -> None:
        self.add()
        self.assertEqual(self.one_pass(FakeGh()), 0)
        self.assertEqual(self.lines(), [f"7 {SHA} {AUTHOR}"])

    # --- trouble ---

    def test_a_failing_gh_keeps_the_line(self) -> None:
        self.add()
        gh = FakeGh()
        gh.fail = True
        self.assertEqual(self.one_pass(gh), 0)
        self.assertEqual(self.said, [])
        self.assertEqual(self.lines(), [f"7 {SHA} {AUTHOR}"])

    def test_a_failing_say_keeps_the_line(self) -> None:
        self.add()
        gh = FakeGh(runs=[run(1, "2026-11-07T08:00:00Z")])
        gh.jobs[(1, 1)] = jobs(ci_ok="success")

        def say(author: str, text: str) -> None:
            raise ci_watch.Transient("maity say: offline")

        ci_watch.run_pass(self.queue, gh, say, REPO, log=io.StringIO())
        self.assertEqual(self.lines(), [f"7 {SHA} {AUTHOR}"])

    def test_a_newer_head_added_during_a_pass_stays(self) -> None:
        self.add()
        gh = FakeGh(runs=[run(1, "2026-11-07T08:00:00Z")])
        gh.jobs[(1, 1)] = jobs(ci_ok="success")

        def say(author: str, text: str) -> None:
            self.add(sha=NEWER)

        ci_watch.run_pass(self.queue, gh, say, REPO, log=io.StringIO())
        self.assertEqual(self.lines(), [f"7 {NEWER} {AUTHOR}"])

    def test_a_malformed_line_is_skipped_and_the_rest_watched(self) -> None:
        self.queue.write_text(f"# a comment\n9 {SHA[:7]} {AUTHOR}\n\n")
        self.add()
        gh = FakeGh(runs=[run(1, "2026-11-07T08:00:00Z")])
        gh.jobs[(1, 1)] = jobs(ci_ok="success")
        log = io.StringIO()
        self.assertEqual(ci_watch.run_pass(self.queue, gh, self.say, REPO, log=log), 1)
        self.assertIn("skipped a line", log.getvalue())
        self.assertEqual(self.lines(), ["# a comment", f"9 {SHA[:7]} {AUTHOR}", ""])

    # --- only reading ---

    def test_gh_is_only_ever_called_with_a_path(self) -> None:
        with mock.patch("subprocess.run") as sub:
            sub.return_value.returncode = 0
            sub.return_value.stdout = "{}"
            ci_watch.gh_get("repos/o/r/pulls/7")
        argv = sub.call_args.args[0]
        self.assertEqual(argv[:2], ["gh", "api"])
        for flag in ("-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"):
            self.assertNotIn(flag, argv)

    def test_run_refuses_without_maity_state_dir(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "MAITY_STATE_DIR"}
        err = io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), contextlib.redirect_stderr(err):
            code = ci_watch.main(["run", str(self.queue), "--once"])
        self.assertEqual(code, 2)
        self.assertIn("MAITY_STATE_DIR", err.getvalue())

    def test_main_add_and_remove(self) -> None:
        self.assertEqual(ci_watch.main(["add", str(self.queue), "7", SHA, AUTHOR]), 0)
        self.assertEqual(self.lines(), [f"7 {SHA} {AUTHOR}"])
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ci_watch.main(["add", str(self.queue), "7", SHA[:7], AUTHOR]), 2)
        self.assertEqual(ci_watch.main(["remove", str(self.queue), "7"]), 0)
        self.assertEqual(self.lines(), [])


if __name__ == "__main__":
    unittest.main()
