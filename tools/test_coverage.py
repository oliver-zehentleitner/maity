"""tools/coverage.sh: whether the main a pull request's green ci-ok run tested has every main
commit on the pull request's files, decided by git's exit codes in any locale, and never exit 0
from a check that did not run."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).parent / "coverage.sh"
LOCALES = {
    "de": {"LANGUAGE": "de", "LANG": "de_DE.UTF-8", "LC_ALL": "de_DE.UTF-8"},
    "en": {"LANGUAGE": "en", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
}
PR = 12
BRANCH = "feature"


def installed(name: str) -> bool:
    """Whether the machine has the locale: without it bash warns and git speaks English, so a
    run "in German" would test nothing German."""
    probe = subprocess.run(
        ["bash", "-c", "true"],
        check=False,
        env={**os.environ, **LOCALES[name]},
        capture_output=True,
        text=True,
    )
    return "setlocale" not in probe.stderr


# A stand-in for gh: `gh api --hostname github.com` of origin's repository, answering from
# github.json next to it the four GETs the script makes. It does not run the --jq filters (the
# machine may have no jq) but checks they are exactly the script's and prints the lines they give.
# `"fail": "<path prefix>"` makes that call fail as gh does on an HTTP error. `"escape_guard"`
# makes it gh 2.97.0 or later, which lists --allow-escape-sequences in `gh api --help` and refuses
# a non-JSON body with an escape sequence without it; otherwise it is an older gh, which rejects
# the flag as unknown.
FAKE_GH = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, pathlib, sys
    here = pathlib.Path(__file__).parent
    data = json.loads((here / "github.json").read_text())
    args = sys.argv[1:]
    guard = data.get("escape_guard", False)
    if args == ["api", "--help"]:
        print("Flags:")
        if guard:
            print("      --allow-escape-sequences   Allow printing terminal escape sequences")
        print("      --hostname string          The GitHub hostname for the request")
        sys.exit(0)
    allow = "--allow-escape-sequences" in args
    if allow and not guard:
        print("unknown flag: --allow-escape-sequences", file=sys.stderr)
        sys.exit(1)
    args = [a for a in args if a != "--allow-escape-sequences"]
    if args[:3] != ["api", "--hostname", "github.com"]:
        sys.exit(3)
    if args[3:5] != ["-H", "Accept: application/vnd.github+json"]:
        sys.exit(3)
    path, rest = args[5], args[6:]
    jq = rest[1] if rest[:1] == ["--jq"] else None
    with open(here / "calls.txt", "a") as calls:
        calls.write(path + "\\n")
    if data.get("fail") and path.startswith("repos/acme/widgets/" + data["fail"]):
        print("gh: HTTP 502", file=sys.stderr)
        sys.exit(1)
    pr = data["pr"]
    def want(expected):
        if jq != expected:
            print("unexpected jq", jq, file=sys.stderr)
            sys.exit(5)
    if path == f"repos/acme/widgets/pulls/{pr['number']}":
        want(r'"\\(.state) \\(.merged) \\(.head.sha) \\(.base.ref) \\(.head.ref)"')
        print(pr["state"], str(pr["merged"]).lower(), pr["head"], pr["base"], pr["ref"])
    elif path == (
        f"repos/acme/widgets/actions/runs?head_sha={pr['head']}&event=pull_request&per_page=100"
    ):
        want(
            r'.workflow_runs[] | "\\(.created_at) \\(.id) \\(.run_attempt) \\(.status)'
            r' \\(.conclusion) \\(.path) \\(.head_branch)"'
        )
        for r in data["runs"]:
            print(r["created_at"], r["id"], r.get("attempt", 1), r["status"],
                  r.get("conclusion", "null"), r.get("path", ".github/workflows/ci.yml"),
                  r.get("branch", pr["ref"]))
    elif path.startswith("repos/acme/widgets/actions/runs/") and path.endswith(
        "/jobs?per_page=100"
    ):
        want(r'.jobs[] | "\\(.id) \\(.conclusion) \\(.name)"')
        key = path.split("/")[5] + "/" + path.split("/")[7]
        for job in data["jobs"].get(key, []):
            print(job["id"], job["conclusion"], job["name"])
    elif path.startswith("repos/acme/widgets/actions/jobs/") and path.endswith("/logs"):
        if jq is not None:
            sys.exit(5)
        log = data["logs"].get(path.split("/")[5])
        if log is None:
            print("gh: Not Found (HTTP 404)", file=sys.stderr)
            sys.exit(1)
        if guard and not allow and "\x1b" in log:
            print(
                "the response contains terminal escape sequences; "
                "pass --allow-escape-sequences to output it anyway",
                file=sys.stderr,
            )
            sys.exit(1)
        sys.stdout.write(log)
    else:
        print("unexpected path", path, file=sys.stderr)
        sys.exit(4)
    """)


def lines(*rows: str) -> str:
    return "".join(f"{row}\n" for row in rows)


def checkout_log(head: str, base: str) -> str:
    """A job log as GitHub serves it: actions/checkout of refs/pull/N/merge, timestamped."""
    return lines(
        "2026-11-08T10:00:00.0000000Z ##[group]Run actions/checkout@v4",
        "2026-11-08T10:00:00.5000000Z \x1b[36;1mwith:\x1b[0m",
        f"2026-11-08T10:00:01.0000000Z [command]/usr/bin/git -c protocol.version=2 fetch "
        f"--no-tags --prune origin +7781bd49:refs/remotes/pull/{PR}/merge",
        f"2026-11-08T10:00:02.0000000Z HEAD is now at 7781bd4 Merge {head} into {base}",
        "2026-11-08T10:00:03.0000000Z ##[endgroup]",
    )


@unittest.skipIf(shutil.which("git") is None, "needs git")
class CoverageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.origin = self.tmp / "origin.git"
        self.clone = self.tmp / "clone"
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH)
        gh.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.org",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.org",
        }
        self.git("init", "-q", "--bare", "-b", "main", str(self.origin), cwd=self.tmp)
        self.git("clone", "-q", str(self.origin), str(self.clone), cwd=self.tmp)
        # origin as GitHub names it, served from the bare repository here.
        url = "https://github.com/acme/widgets.git"
        self.git("config", "remote.origin.url", url)
        self.git("config", "--add", f"url.{self.origin}.insteadOf", url)
        self.git("checkout", "-q", "-b", "main")
        self.base = self.commit(
            {"a.txt": lines("a"), "b.txt": lines("b"), "old.txt": lines("o")}, "base"
        )
        self.push_main()

    def git(self, *args: str, cwd: Path | None = None) -> str:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd or self.clone,
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
        )
        return done.stdout.strip()

    def commit(self, files: dict[str, str | None], message: str) -> str:
        for name, text in files.items():
            if text is None:
                (self.clone / name).unlink()
            else:
                (self.clone / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")

    def push_main(self) -> str:
        self.git("push", "-q", "origin", "main")
        return self.git("rev-parse", "main")

    def on_main(self, files: dict[str, str | None], message: str) -> str:
        self.git("checkout", "-q", "main")
        sha = self.commit(files, message)
        self.push_main()
        return sha

    def pull_request(self, files: dict[str, str | None], start: str | None = None) -> str:
        """The pull request's head as origin serves it (`refs/pull/N/head`)."""
        self.git("checkout", "-q", "--detach", start or self.base)
        head = self.commit(files, "pr")
        self.git("push", "-q", "origin", f"+{head}:refs/pull/{PR}/head")
        self.git("checkout", "-q", "main")
        return head

    def github(self, head: str, tested: str, **changes: Any) -> dict[str, Any]:
        """GitHub's answers for a green ci-ok run of `head` merged into `tested`."""
        data: dict[str, Any] = {
            "pr": {
                "number": PR,
                "state": "open",
                "merged": False,
                "head": head,
                "base": "main",
                "ref": BRANCH,
            },
            "runs": [
                {"created_at": "2026-11-08T10:00:00Z", "id": 500, "status": "completed"},
            ],
            "jobs": {
                "500/1": [
                    {"id": 1, "conclusion": "skipped", "name": "docs only"},
                    {"id": 2, "conclusion": "success", "name": "changes"},
                    {"id": 3, "conclusion": "success", "name": "hub (3.12)"},
                    {"id": 4, "conclusion": "success", "name": "ci-ok"},
                ],
            },
            "logs": {
                "2": lines("no checkout here"),
                "3": checkout_log(head, tested),
                "4": lines("all needed jobs passed"),
            },
        }
        for key, value in changes.items():
            data[key] = value
        return data

    def run_check(
        self, data: dict[str, Any], locale: str = "en", args: list[str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        if not installed(locale):
            self.skipTest(f"locale {LOCALES[locale]['LC_ALL']} is not installed")
        (self.bin / "github.json").write_text(json.dumps(data))
        (self.bin / "calls.txt").unlink(missing_ok=True)
        return subprocess.run(
            ["bash", str(SCRIPT), *(args if args is not None else [str(PR)])],
            check=False,
            cwd=self.clone,
            stdin=subprocess.DEVNULL,
            env={**self.env, **LOCALES[locale]},
            capture_output=True,
            text=True,
        )

    def calls(self) -> list[str]:
        path = self.bin / "calls.txt"
        return path.read_text().splitlines() if path.exists() else []

    def assert_stops(self, got: subprocess.CompletedProcess[str], says: str) -> None:
        self.assertEqual(got.returncode, 2, got.stdout + got.stderr)
        self.assertIn(says, got.stderr)
        self.assertNotIn("in the tested main", got.stdout)

    # Covered and not covered.

    def test_a_main_commit_after_the_tested_main_on_a_pr_file_is_named_in_german_and_english(
        self,
    ) -> None:
        early = self.on_main({"a.txt": lines("main a")}, "main early on a")
        head = self.pull_request({"a.txt": lines("pr a")}, start=early)
        tested = early
        late = self.on_main({"a.txt": lines("main late"), "b.txt": lines("b2")}, "main late on a")
        for locale in LOCALES:
            with self.subTest(locale=locale):
                got = self.run_check(self.github(head, tested), locale)
                self.assertEqual(got.returncode, 1, got.stderr)
                self.assertEqual(got.stderr, "")
                out = got.stdout.splitlines()
                self.assertIn(
                    f"coverage: that run tested the merge with main {tested}; merge base {early}",
                    out,
                )
                # Only the pull request's file, not b.txt, which it does not change.
                self.assertIn(f"  {late} main late on a [a.txt]", out)
                self.assertIn(
                    "coverage: 1 main commits on #12's files are not in the tested main", out[-1]
                )
                self.assertEqual(self.git("for-each-ref", "refs/maity-coverage"), "")

    def test_every_main_commit_in_the_tested_main_is_covered(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        self.on_main({"a.txt": lines("main a"), "c.txt": lines("c")}, "main on a")
        tested = self.on_main({"b.txt": lines("main b")}, "main on b")
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        self.assertEqual(
            got.stdout.splitlines()[-1],
            "coverage: every main commit on #12's files is in the tested main",
        )

    def test_a_later_main_commit_on_another_file_is_no_gap(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.git("rev-parse", "main")
        self.on_main({"b.txt": lines("main b")}, "main on b")
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        self.assertIn("every main commit on #12's files is in the tested main", got.stdout)

    def test_a_rename_counts_under_its_old_name(self) -> None:
        head = self.pull_request({"old.txt": None, "new.txt": lines("o")})
        tested = self.git("rev-parse", "main")
        late = self.on_main({"old.txt": lines("o2")}, "main edits the old name")
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
        self.assertIn(f"  {late} main edits the old name [old.txt]", got.stdout.splitlines())

    def test_the_newest_run_by_start_time_then_id_counts(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        older = self.git("rev-parse", "main")
        newer = self.on_main({"a.txt": lines("main a")}, "main on a")
        data = self.github(head, newer)
        data["runs"] = [
            {"created_at": "2026-11-08T09:00:00Z", "id": 900, "status": "completed"},
            {"created_at": "2026-11-08T10:00:00Z", "id": 500, "status": "completed"},
            {"created_at": "2026-11-08T10:00:00Z", "id": 499, "status": "completed"},
            # Another workflow and another branch of the same head do not count.
            {
                "created_at": "2026-11-09T00:00:00Z",
                "id": 1,
                "status": "queued",
                "path": ".github/workflows/other.yml",
            },
            {"created_at": "2026-11-09T00:00:00Z", "id": 2, "status": "queued", "branch": "x"},
        ]
        data["jobs"]["900/1"] = data["jobs"]["499/1"] = [
            {"id": 9, "conclusion": "success", "name": "ci-ok"}
        ]
        data["logs"]["9"] = checkout_log(head, older)
        got = self.run_check(data)
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        self.assertIn("actions/runs/500", got.stdout)
        self.assertIn(
            "repos/acme/widgets/actions/runs/500/attempts/1/jobs?per_page=100", self.calls()
        )

    def test_the_attempt_of_the_run_is_read(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.git("rev-parse", "main")
        data = self.github(head, tested)
        data["runs"][0]["attempt"] = 2
        data["jobs"] = {"500/2": data["jobs"]["500/1"]}
        got = self.run_check(data)
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)

    # Routes to a wrong exit 0 (review R1 of #1502); each test is red on 0452c230.

    def merge_on_main(self, side: dict[str, str | None], resolve: dict[str, str | None]) -> str:
        """A merge on main of a side branch from the merge base's main, with `resolve` written
        into the merge itself (as a conflict resolution or an edit during the merge does)."""
        self.git("checkout", "-q", "-b", "side", self.base)
        self.commit(side, "side")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--no-commit", "--no-ff", "-s", "ours", "side")
        for name, text in {**side, **resolve}.items():
            if text is None:
                (self.clone / name).unlink()
            else:
                (self.clone / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "merge side")
        return self.push_main()

    def test_a_merge_on_main_that_changes_a_pr_file_is_named(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.on_main({"c.txt": lines("main c")}, "main on c")
        merge = self.merge_on_main({"b.txt": lines("side b")}, {"a.txt": lines("merge a")})
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
        self.assertIn(f"  {merge} merge side [a.txt]", got.stdout.splitlines())

    def test_a_merge_that_takes_a_pr_file_from_its_other_parent_is_named(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.on_main({"a.txt": lines("main a")}, "main on a")
        # The side branch keeps the merge base's a.txt; the merge takes it, undoing "main on a".
        merge = self.merge_on_main({"b.txt": lines("side b")}, {"a.txt": lines("a")})
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
        self.assertIn(f"  {merge} merge side [a.txt]", got.stdout.splitlines())

    def test_a_file_name_git_would_quote_is_matched(self) -> None:
        for name in ("new\nline.txt", "tab\there.txt", 'quote".txt', "back\\slash.txt", "ü.txt"):
            with self.subTest(name=name):
                self.git("checkout", "-q", "main")
                start = self.on_main({name: lines("start")}, f"add {name}")
                head = self.pull_request({name: lines("pr")}, start=start)
                late = self.on_main({name: lines("late")}, f"main on {name}")
                got = self.run_check(self.github(head, start))
                self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
                self.assertIn(late, got.stdout)

    def test_the_fetched_main_counts_not_a_stale_tracking_ref(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.git("rev-parse", "main")
        # origin/main stays at the tested main: the clone fetches another branch by default.
        self.git(
            "config", "remote.origin.fetch", "+refs/heads/unrelated:refs/remotes/origin/unrelated"
        )
        self.git("checkout", "-q", "main")
        late = self.commit({"a.txt": lines("main late")}, "main late on a")
        self.git("push", "-q", "origin", "main:main")
        self.git("update-ref", "refs/remotes/origin/main", tested)
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
        self.assertIn(f"  {late} main late on a [a.txt]", got.stdout.splitlines())
        self.assertEqual(self.git("for-each-ref", "refs/maity-coverage"), "")

    def test_jobs_that_name_different_merges_stop_the_check(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        older = self.git("rev-parse", "main")
        newer = self.on_main({"b.txt": lines("main b")}, "main on b")
        data = self.github(head, newer)
        data["logs"]["4"] = checkout_log(head, older)
        self.assert_stops(self.run_check(data), "name different merges")

    def test_a_shallow_clone_stops_the_check(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.on_main({"b.txt": lines("main b")}, "main on b")
        shallow = self.tmp / "shallow"
        self.git("clone", "-q", "--depth", "1", f"file://{self.origin}", str(shallow), cwd=self.tmp)
        url = "https://github.com/acme/widgets.git"
        self.git("config", "remote.origin.url", url, cwd=shallow)
        self.git("config", "--add", f"url.file://{self.origin}.insteadOf", url, cwd=shallow)
        self.clone = shallow
        self.assert_stops(self.run_check(self.github(head, tested)), "shallow clone")

    def test_main_merged_into_the_pr_after_its_tested_main_counts_as_tested(self) -> None:
        tested = self.git("rev-parse", "main")
        later = self.on_main({"a.txt": lines("main a")}, "main on a")
        self.git("checkout", "-q", "--detach", self.base)
        self.commit({"a.txt": lines("pr a")}, "pr")
        self.git("merge", "-q", "-X", "theirs", "-m", "merge main", later)
        head = self.git("rev-parse", "HEAD")
        self.git("push", "-q", "origin", f"+{head}:refs/pull/{PR}/head")
        self.git("checkout", "-q", "main")
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)

    def test_logs_with_escape_sequences_are_read_with_old_and_new_gh(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.git("rev-parse", "main")
        late = self.on_main({"a.txt": lines("main late")}, "main late on a")
        for guard in (False, True):
            with self.subTest(gh="2.97.0 or later" if guard else "before 2.97.0"):
                got = self.run_check({**self.github(head, tested), "escape_guard": guard})
                self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
                self.assertIn(f"  {late} main late on a [a.txt]", got.stdout.splitlines())

    def test_a_refused_log_names_gh_s_error(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        data = self.github(head, self.base)
        data["logs"].pop("2")
        self.assert_stops(self.run_check(data), "failed: gh: Not Found (HTTP 404)")

    def test_a_subject_s_control_characters_do_not_reach_the_terminal(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.git("rev-parse", "main")
        late = self.on_main({"a.txt": lines("main late")}, "main \x1b[2Jlate")
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
        self.assertNotIn("\x1b", got.stdout)
        self.assertIn(f"  {late} main ?[2Jlate [a.txt]", got.stdout.splitlines())

    def test_a_main_edit_of_a_file_the_pr_deletes_is_named(self) -> None:
        head = self.pull_request({"b.txt": None})
        tested = self.git("rev-parse", "main")
        late = self.on_main({"b.txt": lines("main b")}, "main on b")
        got = self.run_check(self.github(head, tested))
        self.assertEqual(got.returncode, 1, got.stdout + got.stderr)
        self.assertIn(f"  {late} main on b [b.txt]", got.stdout.splitlines())

    def test_no_changed_file_is_exit_0(self) -> None:
        head = self.pull_request({})
        got = self.run_check(self.github(head, self.base))
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        self.assertIn("changes no file", got.stdout)

    # The check could not run: exit 2, never 0.

    def test_a_check_that_could_not_run_is_exit_2(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        tested = self.git("rev-parse", "main")
        other = self.on_main({"b.txt": lines("x")}, "x")
        good = self.github(head, tested)
        pr = good["pr"]
        cases: dict[str, tuple[dict[str, Any], str]] = {
            "closed": ({"pr": {**pr, "state": "closed"}}, "#12 is closed"),
            "merged": ({"pr": {**pr, "state": "closed", "merged": True}}, "#12 is merged"),
            "stacked": ({"pr": {**pr, "base": "agent-x/lower"}}, "stacked on agent-x/lower"),
            "head moved": ({"pr": {**pr, "head": other}}, f"at {other} on GitHub but at {head}"),
            "no run": ({"runs": []}, "no ci run for #12"),
            "running": (
                {
                    "runs": [
                        {"created_at": "2026-11-08T10:00:00Z", "id": 500, "status": "in_progress"}
                    ]
                },
                "still in_progress",
            ),
            "red": (
                {"jobs": {"500/1": [{"id": 4, "conclusion": "failure", "name": "ci-ok"}]}},
                "ci-ok is failure",
            ),
            "no ci-ok": (
                {"jobs": {"500/1": [{"id": 3, "conclusion": "success", "name": "hub"}]}},
                "has no ci-ok job",
            ),
            "no merge line": (
                {"logs": {"2": "x\n", "3": "y\n", "4": "z\n"}},
                "names the merge it tested",
            ),
            "log gone": (
                {"logs": {"3": checkout_log(head, tested)}},
                "log of job 2 failed: gh: Not Found",
            ),
            "other head": (
                {"logs": {**good["logs"], "3": checkout_log(other, tested)}},
                f"tested a merge of {other}, not of #12's head {head}",
            ),
            "two merges": (
                {
                    "logs": {
                        **good["logs"],
                        "2": checkout_log(head, tested) + checkout_log(head, other),
                    }
                },
                "names more than one merge",
            ),
            "tested main unknown": (
                {"logs": {**good["logs"], "3": checkout_log(head, "f" * 40)}},
                f"the tested main {'f' * 40} is not in this clone",
            ),
            "tested main off main": (
                {"logs": {**good["logs"], "3": checkout_log(head, head)}},
                f"the tested main {head} is not on origin/main",
            ),
            "gh pulls fails": ({"fail": "pulls/"}, "reading pull request #12"),
            "gh runs fails": ({"fail": "actions/runs?"}, "listing the ci runs"),
            "gh jobs fails": ({"fail": "actions/runs/500/"}, "listing the jobs of run 500"),
            "bad answer": ({"pr": {**pr, "head": "nothex"}}, "unexpected answer"),
            "a full page of runs": (
                {
                    "runs": [
                        {"created_at": "2026-11-08T10:00:00Z", "id": 500 + n, "status": "completed"}
                        for n in range(100)
                    ]
                },
                "100 or more ci runs",
            ),
            "a full page of jobs": (
                {
                    "jobs": {
                        "500/1": [
                            {"id": 1000 + n, "conclusion": "success", "name": f"job {n}"}
                            for n in range(99)
                        ]
                        + [{"id": 4, "conclusion": "success", "name": "ci-ok"}]
                    }
                },
                "100 or more jobs",
            ),
        }
        for name, (change, says) in cases.items():
            with self.subTest(name):
                self.assert_stops(self.run_check({**good, **change}), says)
        for args in ([], ["0"], ["12", "13"], ["1x"], ["1234567890"]):
            with self.subTest(args=args):
                self.assert_stops(self.run_check(good, args=args), "usage:")

    def test_a_failed_fetch_is_exit_2(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        data = self.github(head, self.base)
        self.git("update-ref", "-d", f"refs/pull/{PR}/head", cwd=self.origin)
        self.assert_stops(self.run_check(data), "git fetch of origin's main and #12's head failed")

    def test_a_failed_git_in_the_clone_is_exit_2_in_german(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        data = self.github(head, self.base)
        # A clone that cannot read its objects: every git after the fetch fails.
        for locale in LOCALES:
            with self.subTest(locale=locale):
                got = self.run_check(data, locale, args=[str(PR)])
                self.assertEqual(got.returncode, 0, got.stderr)
        pack = self.clone / ".git" / "objects"
        broken = self.tmp / "objects-moved"
        pack.rename(broken)
        self.addCleanup(lambda: broken.exists() and broken.rename(pack))
        for locale in LOCALES:
            with self.subTest(locale=locale, broken=True):
                got = self.run_check(data, locale)
                self.assertEqual(got.returncode, 2, got.stdout + got.stderr)

    def test_origin_on_another_host_is_asked_there(self) -> None:
        head = self.pull_request({"a.txt": lines("pr a")})
        data = self.github(head, self.base)
        url = "https://git.example.org/acme/widgets.git"
        self.git("config", "remote.origin.url", url)
        self.git("config", "--add", f"url.{self.origin}.insteadOf", url)
        # The stand-in answers github.com only, so gh is called with origin's host and fails.
        got = self.run_check(data)
        self.assert_stops(got, "of acme/widgets on git.example.org failed")


if __name__ == "__main__":
    unittest.main()
