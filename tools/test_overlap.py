"""tools/overlap.sh: the open pull requests that change a branch's files, decided by git's exit
code in any locale, with a conflict that already exists against main named and not counted."""

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
# A stand-in for gh: the open pull requests and their files from prs.json next to it.
FAKE_GH = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, pathlib, sys
    prs = json.loads((pathlib.Path(__file__).parent / "prs.json").read_text())
    args = sys.argv[1:]
    if args[:2] == ["pr", "list"]:
        for pr in prs:
            print(pr["number"], pr["head"])
    elif args[:2] == ["pr", "view"]:
        number = int(args[2])
        for pr in prs:
            if pr["number"] == number:
                print("\\n".join(pr["files"]))
                break
        else:
            sys.exit(1)
    else:
        sys.exit(3)
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
        self.git("checkout", "-q", "-b", "main")
        self.base = self.commit(BASE, "base")
        self.git("push", "-q", "origin", "main")

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
        return {"number": number, "head": head, "files": sorted(files)}

    def run_check(self, prs: list[dict[str, object]], locale: str, branch: str = "mine"):
        (self.bin / "prs.json").write_text(json.dumps(prs))
        return subprocess.run(
            ["bash", str(SCRIPT), branch],
            cwd=self.clone,
            env={**self.env, **LOCALES[locale]},
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
        prs = self.scenario()
        own = {"number": 11, "head": self.git("rev-parse", "mine"), "files": ["a.txt"]}
        got = self.run_check([own], "en")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(
            got.stdout.strip(), "overlap: no open pull request changes a file of mine"
        )
        del prs

    def test_a_pull_request_it_cannot_read_stops_the_check(self) -> None:
        """A head origin does not serve is an error (exit 2), never a "clean"."""
        self.scenario()
        missing = {"number": 12, "head": "0" * 40, "files": ["a.txt"]}
        got = self.run_check([missing], "de")
        self.assertEqual(got.returncode, 2)
        self.assertIn("fetching pull request 12 failed", got.stderr)
        self.assertNotIn("clean", got.stdout)

    def test_a_merge_git_cannot_compute_stops_the_check(self) -> None:
        """A pull request without common history makes merge-tree fail: exit 2, never a "clean"."""
        self.scenario()
        self.git("checkout", "-q", "--orphan", "stranger")
        head = self.commit({"a.txt": lines("other")}, "unrelated")
        self.git("push", "-q", "origin", f"{head}:refs/pull/13/head")
        self.git("checkout", "-q", "mine")
        got = self.run_check([{"number": 13, "head": head, "files": ["a.txt"]}], "de")
        self.assertEqual(got.returncode, 2, got.stdout)
        self.assertIn("git merge-tree", got.stderr)
        self.assertNotIn("clean", got.stdout)

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
