"""tools/overlap.sh: the open pull requests that change a branch's files, decided by git's exit
code in any locale, with a conflict that already exists against main named and not counted, and
never exit 0 from a check that did not run."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "overlap.sh"
LOCALES = {
    "de": {"LANGUAGE": "de", "LANG": "de_DE.UTF-8", "LC_ALL": "de_DE.UTF-8"},
    "en": {"LANGUAGE": "en", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
}


def installed(name: str) -> bool:
    """Whether the machine has the locale: without it bash warns and git speaks English, so a
    run "in German" would test nothing German."""
    probe = subprocess.run(
        ["bash", "-c", "true"], env={**os.environ, **LOCALES[name]}, capture_output=True, text=True
    )
    return "setlocale" not in probe.stderr
# A stand-in for gh: `gh api` of origin's repository, answering GitHub's REST list of open pull
# requests from prs.json next to it, 100 to a page, every page with --paginate, the first alone
# without; `head_repo` is the pull request's head repository (default origin's, None for a deleted
# fork), and `read` (1 or 2), if set, the one read of the list that names it (calls.txt counts the
# reads). The --jq filter must be exactly the script's; the stand-in does not run it (the machine
# may have no jq) but prints the lines it gives for such an answer. An entry `{"fail_page": n}`
# makes page n fail after the pages before it.
FAKE_GH = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, pathlib, sys
    here = pathlib.Path(__file__).parent
    prs = json.loads((here / "prs.json").read_text())
    repo = (here / "repo.txt").read_text().strip()
    args = sys.argv[1:]
    if args[:1] != ["api"]:
        sys.exit(3)
    args = args[1:]
    # The server asked: --hostname, else GH_HOST, else github.com. Another server than the one
    # in host.txt has a repository of the same name without open pull requests.
    host = os.environ.get("GH_HOST", "github.com")
    if "--hostname" in args:
        i = args.index("--hostname")
        host = args[i + 1]
        del args[i : i + 2]
    if host != (here / "host.txt").read_text().strip():
        sys.exit(0)
    paginate = "--paginate" in args
    jq = args[args.index("--jq") + 1]
    paths = [a for i, a in enumerate(args) if not a.startswith("-") and args[i - 1] != "--jq"]
    if paths != [f"repos/{repo}/pulls?state=open&per_page=100"]:
        sys.exit(4)
    if jq != (
        r'.[] | "\\(.number) \\(.head.sha) \\(.head.repo.full_name != .base.repo.full_name)'
        r' \\(.head.ref)"'
    ):
        sys.exit(5)
    calls = here / "calls.txt"
    read = len(calls.read_text().splitlines()) + 1 if calls.exists() else 1
    calls.write_text("call\\n" * read)
    fail = next((p["fail_page"] for p in prs if "fail_page" in p), None)
    prs = [p for p in prs if "fail_page" not in p and p.get("read", read) == read]
    pages = [prs[i : i + 100] for i in range(0, len(prs), 100)] or [[]]
    for number, page in enumerate(pages if paginate else pages[:1], 1):
        if number == fail:
            print("gh: HTTP 502", file=sys.stderr)
            sys.exit(1)
        for pr in page:
            # head.repo.full_name: a fork's, origin's own, or null for a deleted fork.
            head_repo = pr.get("head_repo", repo)
            print(pr["number"], pr["head"], str(head_repo != repo).lower(), pr["name"])
    """
)


def lines(*rows: str) -> str:
    return "".join(f"{row}\n" for row in rows)


BASE = {
    "a.txt": lines("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8"),
    "b.txt": lines("b1"),
    "c.txt": lines("c1"),
}


@unittest.skipIf(shutil.which("git") is None, "needs git")
class OverlapTest(unittest.TestCase):
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
            "MAITY_OVERLAP_NO_FETCH": "1",
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
        self.set_origin("https://github.com/acme/widgets.git")
        (self.bin / "repo.txt").write_text("acme/widgets")
        (self.bin / "host.txt").write_text("github.com")
        self.git("checkout", "-q", "-b", "main")
        self.base = self.commit(BASE, "base")
        self.git("push", "-q", "origin", "main")

    def set_origin(self, url: str) -> None:
        self.git("config", "remote.origin.url", url)
        self.git("config", "--add", f"url.{self.origin}.insteadOf", url)

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

    def commit(self, files: dict[str, str], message: str) -> str:
        for name, text in files.items():
            (self.clone / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def edit(self, name: str, row: int, text: str, source: dict[str, str] = BASE) -> dict[str, str]:
        rows = source[name].splitlines()
        rows[row] = text
        return {name: lines(*rows)}

    def pull_request(self, number: int, start: str, files: dict[str, str]) -> dict[str, object]:
        """A pull request's head as origin serves it (`refs/pull/N/head`), from `start`."""
        self.git("checkout", "-q", "--detach", start)
        head = self.commit(files, f"pr {number}")
        self.git("push", "-q", "origin", f"{head}:refs/pull/{number}/head")
        return {"number": number, "head": head, "name": f"pr-{number}"}

    def run_check(
        self,
        prs: list[dict[str, object]],
        locale: str,
        branch: str = "mine",
        extra: dict[str, str] | None = None,
    ):
        if not installed(locale):
            self.skipTest(f"locale {LOCALES[locale]['LC_ALL']} is not installed")
        (self.bin / "prs.json").write_text(json.dumps(prs))
        (self.bin / "calls.txt").unlink(missing_ok=True)
        return subprocess.run(
            ["bash", str(SCRIPT), branch],
            cwd=self.clone,
            stdin=subprocess.DEVNULL,
            env={**self.env, **LOCALES[locale], **(extra or {})},
            capture_output=True,
            text=True,
        )

    def scenario(self) -> list[dict[str, object]]:
        """mine edits a.txt row 1 and c.txt. #7 edits the same row of a.txt (a conflict mine
        adds), #8 only b.txt (no shared file), #9 another row of a.txt (clean). #10 changes
        a.txt row 7 and c.txt, and main changed c.txt after #10 started: #10 already conflicts
        with main in c.txt, mine changes nothing of that."""
        prs = [
            self.pull_request(7, self.base, self.edit("a.txt", 1, "seven")),
            self.pull_request(8, self.base, {"b.txt": lines("eight")}),
            self.pull_request(9, self.base, self.edit("a.txt", 5, "nine")),
            self.pull_request(
                10, self.base, {**self.edit("a.txt", 7, "ten"), "c.txt": lines("ten")}
            ),
        ]
        self.git("checkout", "-q", "main")
        moved = self.commit({"c.txt": lines("main")}, "main moves")
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")
        self.git("checkout", "-q", "-b", "mine", moved)
        self.commit(self.edit("a.txt", 1, "mine"), "mine")
        return prs

    def test_a_conflict_is_found_by_exit_code_in_german_and_english(self) -> None:
        prs = self.scenario()
        for locale in LOCALES:
            with self.subTest(locale=locale):
                got = self.run_check(prs, locale)
                self.assertEqual(got.returncode, 1, got.stderr)
                self.assertEqual(
                    got.stdout.splitlines(),
                    [
                        "#7 [a.txt]: CONFLICT in a.txt",
                        "#9 [a.txt]: clean",
                        "#10 [a.txt]: clean for this branch; conflicts with origin/main alone"
                        " in c.txt",
                    ],
                )
                self.assertNotIn("KONFLIKT", got.stdout)

    def test_no_conflict_the_branch_adds_exits_0_and_leaves_no_ref(self) -> None:
        prs = self.scenario()
        without_seven = [pr for pr in prs if pr["number"] != 7]
        for locale in LOCALES:
            with self.subTest(locale=locale):
                got = self.run_check(without_seven, locale)
                self.assertEqual(got.returncode, 0, got.stderr)
                self.assertIn("#9 [a.txt]: clean", got.stdout)
        self.assertEqual(self.git("for-each-ref", "refs/maity-overlap"), "")

    def test_the_branchs_own_pull_request_is_left_out(self) -> None:
        """By its head, and by its branch name while the pushed head is older than the branch."""
        self.scenario()
        pushed = self.git("rev-parse", "mine")
        self.git("push", "-q", "origin", f"{pushed}:refs/pull/11/head")
        self.commit(self.edit("a.txt", 2, "mine again"), "mine, not pushed")
        cases = {
            "head": {"number": 11, "head": self.git("rev-parse", "mine"), "name": "other"},
            "name": {"number": 11, "head": pushed, "name": "mine"},
        }
        for case, own in cases.items():
            with self.subTest(case=case):
                got = self.run_check([own], "en")
                self.assertEqual(got.returncode, 0, got.stderr)
                self.assertEqual(
                    got.stdout.strip(), "overlap: no open pull request changes a file of mine"
                )

    def test_a_forks_branch_of_the_same_name_is_checked(self) -> None:
        """Another's pull request from a fork, or from a fork deleted since, on a branch named like
        mine: not left out as own."""
        prs = self.scenario()
        for head_repo in ("someone/widgets", None):
            with self.subTest(head_repo=head_repo):
                seven = {**prs[0], "name": "mine", "head_repo": head_repo}
                got = self.run_check([seven], "en")
                self.assertEqual(got.returncode, 1, got.stderr)
                self.assertEqual(got.stdout.splitlines(), ["#7 [a.txt]: CONFLICT in a.txt"])

    def failing(self, program: str, when: str, output: str = "") -> None:
        """`program` fails (exit 4, its input unread, `output` on stdout) when its arguments
        contain `when`, else runs."""
        real = shutil.which(program)
        fake = self.bin / program
        fake.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env bash
                case " $* " in *{when}*) printf '%s' '{output}'; exit 4 ;; esac
                exec {real} "$@"
                """
            )
        )
        fake.chmod(0o755)

    def test_a_failing_step_between_git_and_the_answer_stops_the_check(self) -> None:
        """A helper that fails on the way from git's answer to the line, never an empty list read
        as "no file" or "clean": `sort` on the branch's files, `sed` on merge-tree's file list."""
        prs = self.scenario()
        for program, when in (("sort", "-u"), ("sed", "2,$p")):
            with self.subTest(program=program):
                self.failing(program, when)
                got = self.run_check(prs, "en")
                (self.bin / program).unlink()
                self.assertEqual(got.returncode, 2, got.stdout)
                self.assertNotIn("clean", got.stdout)

    def test_the_lists_are_compared_without_a_helper_that_could_fail_unseen(self) -> None:
        """The comparison of two lists runs in bash alone: a failing `tr` or `comm` (each once
        inside `<(...)`, outside pipefail) changes nothing, the conflict is still counted."""
        prs = self.scenario()
        expected = self.run_check(prs, "en")
        self.assertEqual(expected.returncode, 1, expected.stderr)
        for program in ("tr", "comm"):
            with self.subTest(program=program):
                self.failing(program, "")
                got = self.run_check(prs, "en")
                (self.bin / program).unlink()
                self.assertEqual((got.returncode, got.stdout), (1, expected.stdout))

    def test_a_pull_request_it_cannot_read_stops_the_check(self) -> None:
        """A head origin does not serve is an error (exit 2), never a "clean"."""
        self.scenario()
        missing = {"number": 12, "head": "0" * 40, "name": "pr-12"}
        got = self.run_check([missing], "en")
        self.assertEqual(got.returncode, 2)
        self.assertIn("fetching the heads of pull requests 12 failed", got.stderr)
        self.assertNotIn("clean", got.stdout)

    def test_a_head_origin_serves_other_than_gh_lists_stops_the_check(self) -> None:
        """gh may list another repository than origin, or the head moved after the list: the
        commit checked would be another change than the pull request listed. Exit 2."""
        prs = self.scenario()
        seven = next(pr for pr in prs if pr["number"] == 7)
        self.git("checkout", "-q", "--detach", self.base)
        other = self.commit({"b.txt": lines("other")}, "another change numbered 7")
        self.git("push", "-q", "origin", f"+{other}:refs/pull/7/head")
        self.git("checkout", "-q", "mine")
        got = self.run_check([seven], "en")
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn(
            f"pull request 7 is at {seven['head']} in gh's list but at {other} on origin",
            got.stderr,
        )
        self.assertEqual(got.stdout, "")

    def test_a_pull_request_without_common_history_stops_the_check(self) -> None:
        """Its files cannot be listed against main: exit 2, never a "clean" or "no file"."""
        self.scenario()
        self.git("checkout", "-q", "--orphan", "stranger")
        head = self.commit({"a.txt": lines("other")}, "unrelated")
        self.git("push", "-q", "origin", f"{head}:refs/pull/13/head")
        self.git("checkout", "-q", "mine")
        got = self.run_check([{"number": 13, "head": head, "name": "pr-13"}], "en")
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn("git diff", got.stderr)
        self.assertEqual(got.stdout, "")

    def test_a_branch_without_common_history_stops_the_check(self) -> None:
        """Its own files cannot be listed: exit 2, never "changes no file" (exit 0)."""
        prs = self.scenario()
        self.git("checkout", "-q", "--orphan", "stranger")
        self.commit({"a.txt": lines("other")}, "unrelated")
        for locale in LOCALES:
            with self.subTest(locale=locale):
                got = self.run_check(prs, locale, branch="stranger")
                self.assertEqual(got.returncode, 2, got.stdout)
                self.assertIn("git diff", got.stderr)
                self.assertEqual(got.stdout, "")

    def test_a_merge_git_cannot_compute_stops_the_check(self) -> None:
        """main joins two histories; the branch grows from one, the pull request from the other.
        Each has files against main, but the two share no history: merge-tree fails, exit 2."""
        self.git("checkout", "-q", "--orphan", "second")
        self.git("rm", "-q", "-rf", ".")
        root = self.commit({"z.txt": lines("z")}, "second root")
        self.git("checkout", "-q", "main")
        self.git("merge", "-q", "--allow-unrelated-histories", "-m", "join", root)
        self.git("push", "-q", "origin", "main")
        self.git("fetch", "-q", "origin")
        pr = self.pull_request(15, root, {"a.txt": lines("fifteen")})
        self.git("checkout", "-q", "-b", "mine", self.base)
        self.commit(self.edit("a.txt", 1, "mine"), "mine")
        got = self.run_check([pr], "en")
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn("git merge-tree", got.stderr)
        self.assertNotIn("clean", got.stdout)

    def many(self, prs: list[dict[str, object]], count: int = 250) -> list[dict[str, object]]:
        """`count` more open pull requests at main's base (changing nothing) ahead of `prs`; with
        250, these come on the third page of the list."""
        numbers = range(1000, 1000 + count)
        refs = [f"+{self.base}:refs/pull/{n}/head" for n in numbers]
        self.git("push", "-q", "origin", *refs)
        filler = [{"number": n, "head": self.base, "name": f"pr-{n}"} for n in numbers]
        return [*filler, *prs]

    def reads(self) -> int:
        return len((self.bin / "calls.txt").read_text().splitlines())

    def test_every_page_of_open_pull_requests_is_read(self) -> None:
        """#7 is on the third page of the list and still checked; a list of more than one page is
        read twice, one of a single page once."""
        prs = self.scenario()
        got = self.run_check(self.many([prs[0]]), "en")
        self.assertEqual(got.returncode, 1, got.stderr)
        self.assertEqual(got.stdout.splitlines(), ["#7 [a.txt]: CONFLICT in a.txt"])
        self.assertEqual(self.reads(), 2)
        got = self.run_check([prs[0]], "en")
        self.assertEqual(got.returncode, 1, got.stderr)
        self.assertEqual(self.reads(), 1)

    def test_a_pull_request_skipped_while_the_pages_are_read_stops_the_check(self) -> None:
        """Offset paging: #9 closes after the first page was read, so #7 moves onto that page and
        the first read misses it. The second read has #7 and not #9: exit 2, never a check
        without #7. A pull request opened or closed between the reads stops it the same way."""
        prs = self.scenario()
        nine, seven = prs[2], prs[0]
        cases = {
            "skipped": [{**nine, "read": 1}, *self.many([{**seven, "read": 2}])],
            "opened": self.many([{**seven, "read": 2}]),
            "closed": [{**nine, "read": 1}, *self.many([seven])],
            # 101 open, #9 closes after page 1: each read has exactly one page's worth, 100.
            "skipped at 100": [{**nine, "read": 1}, *self.many([{**seven, "read": 2}], 99)],
        }
        for case, listed in cases.items():
            with self.subTest(case=case):
                got = self.run_check(listed, "en")
                self.assertEqual(got.returncode, 2, got.stdout)
                self.assertIn("the list of open pull requests changed while it was read", got.stderr)
                self.assertEqual(got.stdout, "")

    def test_a_page_that_fails_stops_the_check(self) -> None:
        """The list ends at a failing page: exit 2, never a check of the pages before it alone."""
        prs = self.scenario()
        got = self.run_check([{"fail_page": 2}, *self.many([prs[0]])], "en")
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn("listing the open pull requests of acme/widgets on github.com failed", got.stderr)
        self.assertEqual(got.stdout, "")

    def test_a_list_of_another_shape_stops_the_check(self) -> None:
        """A line the list should not hold (a head that is no commit id, a branch name missing):
        exit 2, never fewer pull requests."""
        prs = self.scenario()
        for case, pr in (
            ("head", {**prs[0], "head": "null"}),
            ("short head", {**prs[0], "head": prs[0]["head"][:39]}),
            ("name", {**prs[0], "name": ""}),
        ):
            with self.subTest(case=case):
                got = self.run_check([pr], "en")
                self.assertEqual(got.returncode, 2, got.stdout)
                self.assertIn("unexpected line in the list of open pull requests", got.stderr)
                self.assertEqual(got.stdout, "")

    def test_the_repository_is_read_from_origins_url_in_each_form(self) -> None:
        """https with or without .git or a slash, ssh, and a proxy's path: each names acme/widgets
        (the stand-in answers nothing else). A URL without an owner stops the check."""
        prs = self.scenario()
        for url in (
            "https://github.com/acme/widgets",
            "https://github.com/acme/widgets/",
            "git@github.com:acme/widgets.git",
            "ssh://git@github.com/acme/widgets.git",
            "http://local_proxy@127.0.0.1:9/git/acme/widgets",
        ):
            with self.subTest(url=url):
                self.set_origin(url)
                got = self.run_check([prs[0]], "en")
                self.assertEqual(got.returncode, 1, got.stderr)
                self.assertEqual(got.stdout.splitlines(), ["#7 [a.txt]: CONFLICT in a.txt"])
        for url in ("widgets", "https://github.com//widgets", "https://github.com/ac me/widgets"):
            with self.subTest(url=url):
                self.set_origin(url)
                got = self.run_check([prs[0]], "en")
                self.assertEqual(got.returncode, 2, got.stdout)
                self.assertIn(
                    f"cannot read an owner and a repository from origin's URL {url}", got.stderr
                )

    def test_the_list_comes_from_origins_host(self) -> None:
        """gh is asked origin's host, whatever GH_HOST says: another server with an empty list of
        a repository of the same name would read as "no open pull request" (exit 0). A loopback
        proxy stands for github.com; a URL without a host stops the check."""
        prs = self.scenario()
        cases = {
            "https://github.com/acme/widgets.git": "github.com",
            "http://local_proxy@127.0.0.1:9/git/acme/widgets": "github.com",
            "ssh://git@ghe.example.com:2222/acme/widgets.git": "ghe.example.com",
            "git@ghe.example.com:acme/widgets.git": "ghe.example.com",
            "https://127.example.com/acme/widgets.git": "127.example.com",
            "http://127.0.0.1:9/git/acme/widgets": "github.com",
        }
        for url, host in cases.items():
            with self.subTest(url=url):
                self.set_origin(url)
                (self.bin / "host.txt").write_text(host)
                got = self.run_check([prs[0]], "en", extra={"GH_HOST": "other.example"})
                self.assertEqual(got.returncode, 1, got.stderr)
                self.assertEqual(got.stdout.splitlines(), ["#7 [a.txt]: CONFLICT in a.txt"])
        self.set_origin("/srv/git/acme/widgets.git")
        got = self.run_check([prs[0]], "en")
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn("cannot read a host from origin's URL /srv/git/acme/widgets.git", got.stderr)

    def test_an_empty_list_from_origins_host_exits_0(self) -> None:
        """No open pull request on the right server: nothing to check, exit 0."""
        self.scenario()
        got = self.run_check([], "en")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(
            got.stdout.strip(), "overlap: no open pull request changes a file of mine"
        )

    def test_a_file_the_pull_request_renames_is_shared(self) -> None:
        """mine edits b.txt, #16 renames it: the pull request is checked, not skipped."""
        self.git("checkout", "-q", "--detach", self.base)
        self.git("mv", "b.txt", "renamed.txt")
        self.git("commit", "-q", "-m", "pr 16")
        head = self.git("rev-parse", "HEAD")
        self.git("push", "-q", "origin", f"{head}:refs/pull/16/head")
        self.git("checkout", "-q", "-b", "mine", self.base)
        self.commit({"b.txt": lines("b1", "mine")}, "mine")
        got = self.run_check([{"number": 16, "head": head, "name": "pr-16"}], "en")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(got.stdout.splitlines(), ["#16 [b.txt]: clean"])

    def test_a_path_beyond_ascii_is_shared_and_named_as_it_is(self) -> None:
        pr = self.pull_request(17, self.base, {"grüße.txt": lines("seventeen")})
        self.git("checkout", "-q", "-b", "mine", self.base)
        self.commit({"grüße.txt": lines("mine")}, "mine")
        got = self.run_check([pr], "en")
        self.assertEqual(got.returncode, 1, got.stderr)
        self.assertEqual(got.stdout.splitlines(), ["#17 [grüße.txt]: CONFLICT in grüße.txt"])

    def test_paths_are_compared_bytewise_whatever_the_locale(self) -> None:
        """Paths whose order differs between a German collation and bytes (case, `-`, `_`)
        come out in byte order and without a word from `sort` or `comm`, in every locale."""
        names = ["web_b.txt", "Zeta.txt", "web-a.txt", "Web.txt"]
        theirs = {name: lines(name) for name in [*names, "b-only.txt", "Y_only.txt"]}
        pr = self.pull_request(14, self.base, theirs)
        self.git("checkout", "-q", "-b", "mine", self.base)
        own = {name: lines(f"{name} mine") for name in [*names, "A-only.txt", "x_only.txt"]}
        self.commit(own, "mine")
        for locale in LOCALES:
            with self.subTest(locale=locale):
                got = self.run_check([pr], locale)
                self.assertEqual(got.stderr, "")
                self.assertEqual(
                    got.stdout.splitlines(),
                    [
                        "#14 [Web.txt,Zeta.txt,web-a.txt,web_b.txt]: CONFLICT in"
                        " Web.txt,Zeta.txt,web-a.txt,web_b.txt"
                    ],
                )


if __name__ == "__main__":
    unittest.main()
