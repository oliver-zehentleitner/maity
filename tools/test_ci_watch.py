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

    def test_a_deleted_pull_request_is_reported_and_removed(self) -> None:
        self.add()

        def gh(path: str) -> object:
            raise ci_watch.NotFound(path)

        ci_watch.run_pass(self.queue, gh, self.say, REPO, log=io.StringIO())
        self.assertIn("no such pull request", self.said[0][1])
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


INBOX = "agt-watcher"
SENDER = "agt-author"


def message(seq: int, body: str, **fields: object) -> dict[str, Any]:
    item: dict[str, Any] = {
        "seq": seq,
        "type": "notice",
        "from": SENDER,
        "from_instance": "ab12",
        "to": f"{INBOX}#hrjz",
        "body": body,
    }
    item.update(fields)
    return item


class FakeMessages:
    """`maity messages`: everything after a seq, oldest first; None asks for the newest."""

    def __init__(self, items: list[dict[str, Any]]) -> None:
        self.items = items
        self.calls: list[int | None] = []

    def __call__(self, after: int | None) -> list[dict[str, Any]]:
        self.calls.append(after)
        if after is None:
            return sorted(self.items, key=lambda i: -i["seq"])[:1]
        return [i for i in sorted(self.items, key=lambda i: i["seq"]) if i["seq"] > after]


class IntakeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.queue = self.tmp / "ciwatch.txt"
        self.cursor = self.tmp / "ciwatch.txt.seq"
        self.said: list[tuple[str, str]] = []
        self.gh = FakeGh()

    def say(self, author: str, text: str) -> None:
        self.said.append((author, text))

    def lines(self) -> list[str]:
        return self.queue.read_text().splitlines() if self.queue.exists() else []

    def intake(self, items: list[dict[str, Any]], start: int | None = 100) -> int:
        if start is not None:
            self.cursor.write_text(f"{start}\n")
        return ci_watch.intake_pass(
            self.queue, INBOX, FakeMessages(items), self.gh, self.say, REPO, log=io.StringIO()
        )

    def test_the_sender_is_the_author_never_the_text(self) -> None:
        self.assertEqual(self.intake([message(101, f"ciwatch 7 {SHA}")]), 1)
        self.assertEqual(self.lines(), [f"7 {SHA} {SENDER}#ab12"])
        self.assertEqual(self.said, [(f"{SENDER}#ab12", self.said[0][1])])
        self.assertIn(f"#7 {SHA} added", self.said[0][1])
        self.assertEqual(self.cursor.read_text().strip(), "101")

    def test_an_address_in_the_text_is_not_taken(self) -> None:
        self.intake([message(101, f"ciwatch 7 {SHA} {AUTHOR}")])
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.said, [])

    def test_other_messages_and_messages_to_others_get_no_answer(self) -> None:
        taken = self.intake(
            [
                message(101, "please review #7"),
                message(102, f"ciwatch 7 {SHA}", to="agt-someone-else#x1"),
                message(103, f"ciwatch 7 {SHA}", to="all"),
                message(104, f"ciwatch 7 {SHA[:7]}"),
            ]
        )
        self.assertEqual(taken, 0)
        self.assertEqual(self.said, [])
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.cursor.read_text().strip(), "104")

    def test_its_own_messages_are_never_intake(self) -> None:
        self.intake([message(101, f"ciwatch 7 {SHA}", **{"from": INBOX})])
        self.assertEqual(self.said, [])
        self.assertEqual(self.lines(), [])

    def test_refusals_get_one_answer_each(self) -> None:
        cases: dict[str, dict[str, Any]] = {
            "its head is " + NEWER: {"head": {"sha": NEWER, "ref": BRANCH}},
            "the pull request is merged": {"merged": True, "state": "closed"},
            "the pull request is closed": {"state": "closed"},
        }
        for why, change in cases.items():
            with self.subTest(why):
                self.said.clear()
                self.gh = FakeGh()
                self.gh.pr.update(change)
                self.assertEqual(self.intake([message(101, f"ciwatch 7 {SHA}")]), 0)
                self.assertEqual(len(self.said), 1)
                self.assertIn(f"not added: {why}.", self.said[0][1])
                self.assertEqual(self.lines(), [])

    def test_an_unknown_pull_request_is_refused(self) -> None:
        def gh(path: str) -> object:
            raise ci_watch.NotFound(path)

        self.gh = gh  # type: ignore[assignment]
        self.intake([message(101, f"ciwatch 7 {SHA}")])
        self.assertIn("not added: no such pull request.", self.said[0][1])

    def test_a_message_without_sender_instance_is_refused_to_the_member(self) -> None:
        self.intake([message(101, f"ciwatch 7 {SHA}", from_instance=None)])
        self.assertEqual(
            self.said, [(SENDER, "ciwatch: #7 not added: the message has no sender instance")]
        )
        self.assertEqual(self.lines(), [])

    def test_a_newer_head_replaces_the_older_line(self) -> None:
        ci_watch.add(self.queue, ci_watch.Entry(7, NEWER, AUTHOR))
        self.intake([message(101, f"ciwatch 7 {SHA}")])
        self.assertEqual(self.lines(), [f"7 {SHA} {SENDER}#ab12"])

    def test_the_first_start_takes_no_old_message(self) -> None:
        items = [message(101, f"ciwatch 7 {SHA}"), message(102, "hello")]
        self.assertEqual(self.intake(items, start=None), 0)
        self.assertEqual(self.cursor.read_text().strip(), "102")
        self.assertEqual(self.said, [])
        self.assertEqual(self.lines(), [])
        # A message after the start is taken on the next pass.
        self.assertEqual(self.intake([*items, message(103, f"ciwatch 7 {SHA}")], start=None), 1)

    def test_the_cursor_survives_a_restart_and_nothing_is_answered_twice(self) -> None:
        items = [message(101, f"ciwatch 7 {SHA}")]
        self.intake(items)
        self.intake(items, start=None)
        self.assertEqual(len(self.said), 1)

    def test_a_failing_say_retries_exactly_that_message(self) -> None:
        items = [message(101, "hello"), message(102, f"ciwatch 7 {SHA}")]

        def say(author: str, text: str) -> None:
            raise ci_watch.Transient("maity say: offline")

        self.cursor.write_text("100\n")
        with self.assertRaises(ci_watch.Transient):
            ci_watch.intake_pass(
                self.queue, INBOX, FakeMessages(items), self.gh, say, REPO, log=io.StringIO()
            )
        self.assertEqual(self.cursor.read_text().strip(), "101")
        self.intake(items, start=None)
        self.assertEqual(len(self.said), 1)
        self.assertEqual(self.lines(), [f"7 {SHA} {SENDER}#ab12"])

    def test_answers_per_pass_are_capped(self) -> None:
        items = [message(101 + n, f"ciwatch 7 {SHA}") for n in range(ci_watch.INTAKE_PER_PASS + 5)]
        self.intake(items)
        self.assertEqual(len(self.said), ci_watch.INTAKE_PER_PASS)
        self.intake(items, start=None)
        self.assertEqual(len(self.said), ci_watch.INTAKE_PER_PASS + 5)

    def test_maity_messages_is_read_only(self) -> None:
        # `maity messages` acknowledges nothing and moves no cursor (its --help says so); the
        # watcher only ever calls it with --json, --after/--limit/--cursor, nothing that writes.
        with mock.patch("subprocess.run") as sub:
            sub.return_value.returncode = 0
            sub.return_value.stdout = '{"items": [], "next_cursor": null}'
            ci_watch.maity_messages(100)
            ci_watch.maity_messages(None)
        for call in sub.call_args_list:
            argv = call.args[0]
            self.assertEqual(argv[:3], ["maity", "messages", "--json"])
            self.assertTrue(set(argv[3::2]) <= {"--after", "--limit", "--cursor"}, argv)

    def test_run_refuses_an_inbox_with_an_instance(self) -> None:
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"MAITY_STATE_DIR": "x"}), contextlib.redirect_stderr(err):
            code = ci_watch.main(["run", str(self.queue), "--once", "--inbox", "agt-x#hrjz"])
        self.assertEqual(code, 2)
        self.assertIn("--inbox", err.getvalue())


if __name__ == "__main__":
    unittest.main()
