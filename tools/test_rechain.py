"""Tests for tools/rechain.py.

Standard library only, so CI runs them without installing anything:
    python3 -m unittest discover -s tools -p 'test_*.py'
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import rechain  # noqa: E402


def migration(revision: str, down: str | None, annotated: bool = True) -> str:
    value = f'"{down}"' if down else "None"
    line = f"down_revision: str | None = {value}" if annotated else f"down_revision = {value}"
    return (
        f'"""A step.\n\nRevision ID: {revision}\nRevises: {down}\nCreate Date: 2026-10-30\n"""\n\n'
        f'revision: str = "{revision}"\n{line}\n'
    )


class Repo:
    """A git repository with a `main` branch of migrations and a branch checked out on it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.versions = root / rechain.VERSIONS
        self.versions.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.org")
        self.git("config", "user.name", "t")

    def git(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.root, check=True, capture_output=True)

    def add(self, name: str, text: str) -> None:
        (self.versions / name).write_text(text)

    def commit(self, message: str) -> None:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def read(self, name: str) -> str:
        return (self.versions / name).read_text()


class RechainTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self._tmp.name))
        self.repo.add("0001_first.py", migration("0001", None))
        self.repo.add("0002_second.py", migration("0002", "0001", annotated=False))
        self.repo.commit("main")
        self.repo.git("checkout", "-q", "-b", "feature")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_tool(self, *args: str) -> tuple[int, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = rechain.main(["--root", str(self.repo.root), "--base", "main", *args])
        return code, out.getvalue() + err.getvalue()

    def test_the_new_migration_follows_mains_head_after_main_moved(self) -> None:
        self.repo.add("20261030102512_mine.py", migration("20261030102512_mine", "0002"))
        self.repo.commit("mine")
        self.repo.git("checkout", "-q", "main")
        self.repo.add("0003_theirs.py", migration("0003", "0002"))
        self.repo.commit("theirs")
        self.repo.git("checkout", "-q", "feature")
        self.repo.git("merge", "-q", "--no-edit", "main")
        code, said = self.run_tool("--check")
        self.assertEqual(code, 1)
        self.assertIn("2 heads (0003, 20261030102512_mine)", said)
        self.assertIn("python tools/rechain.py", said)
        code, said = self.run_tool()
        self.assertEqual(code, 0, said)
        text = self.repo.read("20261030102512_mine.py")
        self.assertIn('down_revision: str | None = "0003"', text)
        self.assertIn("Revises: 0003\n", text)
        self.assertEqual(self.run_tool("--check"), (0, "one migration head: 20261030102512_mine\n"))
        self.assertIn("already follows 0003", self.run_tool()[1])

    def test_a_branch_without_a_new_migration_has_nothing_to_chain(self) -> None:
        self.assertEqual(
            self.run_tool(), (0, "no new migration in this branch: nothing to chain\n")
        )

    def test_two_new_migrations_are_refused(self) -> None:
        self.repo.add("a.py", migration("a", "0002"))
        self.repo.add("b.py", migration("b", "a"))
        code, said = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("2 new migrations in this branch (a.py, b.py)", said)

    def test_a_branch_that_lacks_mains_migrations_is_told_to_merge_first(self) -> None:
        self.repo.add("mine.py", migration("mine", "0002"))
        self.repo.commit("mine")
        self.repo.git("checkout", "-q", "-b", "other", "main")
        self.repo.add("0003_theirs.py", migration("0003", "0002"))
        self.repo.commit("theirs")
        self.repo.git("branch", "-f", "main", "other")
        self.repo.git("checkout", "-q", "feature")
        code, said = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("lacks 1 migration(s) of main (0003_theirs.py): merge main first", said)
        self.assertIn('= "0002"', self.repo.read("mine.py"))  # nothing written


if __name__ == "__main__":
    unittest.main()
