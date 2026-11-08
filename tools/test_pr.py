"""tools/pr.sh: opens or edits a pull request of origin's repository over REST, only for a pushed
branch or the checked-out branch's own pull request, sends exactly the title and the body file,
refuses attribution lines, and never ends in 0 when it did not reach GitHub."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "pr.sh"

# A stand-in for gh: records every call (argv and stdin) in calls.jsonl next to it and answers
# from answers.json, keyed by "METHOD path"; a key missing there fails like a refused call.
FAKE_GH = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, pathlib, sys
    here = pathlib.Path(__file__).parent
    args = sys.argv[1:]
    stdin = sys.stdin.read() if "--input" in args else ""
    with open(here / "calls.jsonl", "a") as f:
        f.write(json.dumps({"args": args, "stdin": stdin}) + "\\n")
    answers = json.loads((here / "answers.json").read_text())
    method = args[args.index("-X") + 1] if "-X" in args else "GET"
    path = next(a for a in args[1:] if a.startswith("repos/"))
    answer = answers.get(f"{method} {path}")
    if answer is None:
        print("HTTP 403: refused", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(answer))
    """
)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class PrTool(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.answers: dict[str, object] = {}
        # origin: a bare repository reached through insteadOf, so remote.origin.url reads as
        # GitHub's while `git ls-remote origin` answers from the bare one.
        self.bare = self.tmp / "origin.git"
        git(self.tmp, "init", "--bare", str(self.bare))
        self.clone = self.tmp / "clone"
        self.clone.mkdir()
        git(self.clone, "init")
        git(self.clone, "config", "user.email", "t@example.com")
        git(self.clone, "config", "user.name", "t")
        self.set_origin("https://github.com/acme/widget.git")
        (self.clone / "a.txt").write_text("a\n")
        git(self.clone, "add", "a.txt")
        git(self.clone, "commit", "-m", "a")
        git(self.clone, "push", "-q", "origin", "main")
        git(self.clone, "switch", "-q", "-c", "claude/topic")
        (self.clone / "b.txt").write_text("b\n")
        git(self.clone, "add", "b.txt")
        git(self.clone, "commit", "-m", "b")
        git(self.clone, "push", "-q", "origin", "claude/topic")
        self.head = git(self.clone, "rev-parse", "HEAD")
        self.body = self.tmp / "body.md"
        self.body.write_text("## Summary\n\nUses `$(date)` and \"quotes\" — as written.\n")

    def set_origin(self, url: str) -> None:
        """origin's URL as written, fetched and pushed through the bare repository."""
        if "origin" in git(self.clone, "remote").split():
            git(self.clone, "remote", "remove", "origin")
        git(self.clone, "remote", "add", "origin", url)
        key = f"url.{self.bare}.insteadOf"
        subprocess.run(["git", "config", "--unset-all", key], cwd=self.clone, check=False)
        prefix = url.rsplit("acme/widget", 1)[0]
        for form in ("acme/widget.git", "acme/widget"):
            git(self.clone, "config", "--add", key, prefix + form)

    def run_pr(self, *args: str) -> subprocess.CompletedProcess[str]:
        (self.bin / "answers.json").write_text(json.dumps(self.answers))
        env = {**os.environ, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"}
        env.pop("GH_HOST", None)
        env.pop("GH_REPO", None)
        return subprocess.run(
            ["bash", str(SCRIPT), *args], cwd=self.clone, env=env, capture_output=True, text=True
        )

    def calls(self) -> list[dict[str, object]]:
        path = self.bin / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def answer(self, number: int, head: str, title: str = "T") -> dict[str, object]:
        return {
            "number": number,
            "html_url": f"https://github.com/acme/widget/pull/{number}",
            "title": title,
            "head": {"sha": head, "ref": "claude/topic", "repo": {"full_name": "acme/widget"}},
        }

    # --- open ---------------------------------------------------------------------------------

    def test_open_sends_exactly_the_title_branch_base_and_body(self) -> None:
        self.answers["POST repos/acme/widget/pulls"] = self.answer(7, self.head, "Add b")
        done = self.run_pr("open", "--title", "Add b", "--body-file", str(self.body))
        self.assertEqual(done.returncode, 0, done.stderr)
        [call] = self.calls()
        args = call["args"]
        self.assertEqual(args[:3], ["api", "--hostname", "github.com"])
        self.assertIn("repos/acme/widget/pulls", args)
        self.assertEqual(json.loads(str(call["stdin"])), {
            "title": "Add b",
            "head": "claude/topic",
            "base": "main",
            "body": self.body.read_text(),
        })
        self.assertIn("#7 https://github.com/acme/widget/pull/7", done.stdout)
        self.assertIn(self.head, done.stdout)

    def test_open_as_draft_on_another_base(self) -> None:
        self.answers["POST repos/acme/widget/pulls"] = self.answer(8, self.head)
        done = self.run_pr(
            "open", "--title", "T", "--body-file", str(self.body), "--base", "dev", "--draft"
        )
        self.assertEqual(done.returncode, 0, done.stderr)
        sent = json.loads(str(self.calls()[0]["stdin"]))
        self.assertEqual((sent["base"], sent["draft"]), ("dev", True))

    def test_open_refuses_a_branch_origin_does_not_have(self) -> None:
        git(self.clone, "switch", "-q", "-c", "claude/unpushed")
        done = self.run_pr("open", "--title", "T", "--body-file", str(self.body))
        self.assertEqual(done.returncode, 1)
        self.assertIn("origin has no branch claude/unpushed", done.stderr)
        self.assertEqual(self.calls(), [])

    def test_open_refuses_a_local_head_origin_does_not_have(self) -> None:
        (self.clone / "c.txt").write_text("c\n")
        git(self.clone, "add", "c.txt")
        git(self.clone, "commit", "-m", "c")
        done = self.run_pr("open", "--title", "T", "--body-file", str(self.body))
        self.assertEqual(done.returncode, 1)
        self.assertIn("push first", done.stderr)
        self.assertEqual(self.calls(), [])

    def test_open_fails_visibly_when_github_answers_another_head(self) -> None:
        self.answers["POST repos/acme/widget/pulls"] = self.answer(9, "0" * 40)
        done = self.run_pr("open", "--title", "T", "--body-file", str(self.body))
        self.assertEqual(done.returncode, 2)
        self.assertIn("another head", done.stderr)

    def test_a_failed_gh_call_is_exit_2_never_0(self) -> None:
        done = self.run_pr("open", "--title", "T", "--body-file", str(self.body))
        self.assertEqual(done.returncode, 2)
        self.assertIn("failed (gh api)", done.stderr)
        done = self.run_pr("edit", "7", "--title", "T")
        self.assertEqual(done.returncode, 2)

    def test_open_needs_a_title_and_a_body(self) -> None:
        self.assertEqual(self.run_pr("open", "--body-file", str(self.body)).returncode, 1)
        self.assertEqual(self.run_pr("open", "--title", "T").returncode, 1)
        self.assertEqual(self.calls(), [])

    # --- attribution lines --------------------------------------------------------------------

    def test_a_body_with_an_attribution_line_is_refused_by_open_and_edit(self) -> None:
        lines = [
            "Co-Authored-By: Someone <x@example.com>",
            "  co-authored-by: someone",
            "Claude-Session: https://example.com/s",
            "🤖 Generated with [Claude Code](https://claude.com/claude-code)",
        ]
        self.answers["GET repos/acme/widget/pulls/7"] = self.answer(7, self.head)
        for line in lines:
            with self.subTest(line=line):
                self.body.write_text(f"## Summary\n\nText.\n\n{line}\n")
                done = self.run_pr("open", "--title", "T", "--body-file", str(self.body))
                self.assertEqual(done.returncode, 1, line)
                self.assertIn("attribution line", done.stderr)
                done = self.run_pr("edit", "7", "--body-file", str(self.body))
                self.assertEqual(done.returncode, 1, line)
        self.assertEqual(self.calls(), [])

    def test_ordinary_words_are_not_an_attribution_line(self) -> None:
        self.body.write_text("Generated with the hub's table; co-authored by two humans.\n")
        self.answers["POST repos/acme/widget/pulls"] = self.answer(7, self.head)
        done = self.run_pr("open", "--title", "T", "--body-file", str(self.body))
        self.assertEqual(done.returncode, 0, done.stderr)

    # --- edit ---------------------------------------------------------------------------------

    def test_edit_sends_only_the_fields_given_to_the_own_pull_request(self) -> None:
        self.answers["GET repos/acme/widget/pulls/7"] = self.answer(7, self.head, "Old")
        self.answers["PATCH repos/acme/widget/pulls/7"] = self.answer(7, self.head, "New")
        done = self.run_pr("edit", "7", "--title", "New")
        self.assertEqual(done.returncode, 0, done.stderr)
        get, patch = self.calls()
        self.assertNotIn("-X", get["args"])
        self.assertEqual(json.loads(str(patch["stdin"])), {"title": "New"})
        self.assertIn("title New", done.stdout)
        done = self.run_pr("edit", "7", "--body-file", str(self.body))
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(str(self.calls()[-1]["stdin"])), {"body": self.body.read_text()})

    def test_edit_refuses_a_pull_request_of_another_branch(self) -> None:
        other = self.answer(7, self.head)
        other["head"]["ref"] = "claude/someone-else"  # type: ignore[index]
        self.answers["GET repos/acme/widget/pulls/7"] = other
        self.answers["PATCH repos/acme/widget/pulls/7"] = other
        done = self.run_pr("edit", "7", "--title", "New")
        self.assertEqual(done.returncode, 1)
        self.assertIn("edit only your own pull request", done.stderr)
        self.assertEqual([c for c in self.calls() if "PATCH" in c["args"]], [])
        # Named explicitly, the other branch's pull request is allowed.
        done = self.run_pr("edit", "7", "--title", "New", "--branch", "claude/someone-else")
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_edit_refuses_a_head_in_a_fork(self) -> None:
        fork = self.answer(7, self.head)
        fork["head"]["repo"] = {"full_name": "someone/widget"}  # type: ignore[index]
        self.answers["GET repos/acme/widget/pulls/7"] = fork
        done = self.run_pr("edit", "7", "--title", "New")
        self.assertEqual(done.returncode, 1)
        self.assertIn("someone/widget", done.stderr)

    def test_edit_refuses_an_edit_that_names_no_field(self) -> None:
        done = self.run_pr("edit", "7")
        self.assertEqual(done.returncode, 1)
        self.assertIn("names no field", done.stderr)
        self.assertEqual(self.calls(), [])

    # --- origin -------------------------------------------------------------------------------

    def test_host_owner_and_repository_come_from_origin(self) -> None:
        cases = [
            ("git@github.com:acme/widget.git", "github.com"),
            ("http://127.0.0.1:41723/git/acme/widget", "github.com"),  # a cloud session's proxy
            ("https://ghe.example.com/acme/widget", "ghe.example.com"),
        ]
        for url, host in cases:
            with self.subTest(url=url):
                self.set_origin(url)
                git(self.clone, "push", "-q", "origin", "claude/topic")
                (self.bin / "calls.jsonl").unlink(missing_ok=True)
                self.answers["POST repos/acme/widget/pulls"] = self.answer(7, self.head)
                done = self.run_pr("open", "--title", "T", "--body-file", str(self.body))
                self.assertEqual(done.returncode, 0, done.stderr)
                args = self.calls()[0]["args"]
                self.assertEqual(args[1:3], ["--hostname", host])
                self.assertIn("repos/acme/widget/pulls", args)


if __name__ == "__main__":
    unittest.main()
