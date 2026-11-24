"""tools/guards.sh: which Python it tests with. HUB_PYTHON when it is set; unset, the work
tree's own hub/.venv/bin/python where one is there, else python3 from PATH, as before.

Each case runs guards.sh in a fresh git work tree whose PATH holds stand-ins for make, node
and python3. The Python it picked then fails its import check, and the refusal (exit 2) names
that Python, so the choice is read without running any step."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "guards.sh"
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@invalid"}


def stand_in(path: Path) -> Path:
    """An executable that answers nothing and fails: a Python that cannot import the hub."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 1\n")
    path.chmod(0o755)
    return path


@unittest.skipIf(shutil.which("git") is None, "needs git")
class GuardsPythonTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.bin = self.tmp / "bin"
        for name in ("make", "node", "python3"):
            stand_in(self.bin / name)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        env = {"PATH": os.environ.get("PATH", ""), "HOME": str(self.tmp), **IDENTITY}
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, env=env)
        # The venv is ignored, as the repository's own .gitignore ignores it, so the work tree
        # is clean and guards.sh goes on to choose its Python.
        (self.repo / ".gitignore").write_text(".venv/\n")
        subprocess.run(["git", "-C", str(self.repo), "add", ".gitignore"], check=True, env=env)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", "init"], check=True, env=env)

    def guards(self, **extra: str) -> subprocess.CompletedProcess[str]:
        path = f"{self.bin}:{os.environ.get('PATH', '')}"
        env = {"PATH": path, "HOME": str(self.tmp), **extra}
        return subprocess.run(["bash", str(SCRIPT)], cwd=self.repo, env=env, capture_output=True, text=True)

    def test_unset_it_is_the_work_trees_hub_venv_where_there_is_one(self) -> None:
        venv = stand_in(self.repo / "hub" / ".venv" / "bin" / "python")
        done = self.guards()
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(f"HUB_PYTHON={venv} cannot import pytest", done.stderr)

    def test_unset_and_without_a_hub_venv_it_is_python3_as_before(self) -> None:
        done = self.guards()
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn(f"HUB_PYTHON={self.bin / 'python3'} cannot import pytest", done.stderr)

    def test_a_set_hub_python_wins_over_the_hub_venv(self) -> None:
        stand_in(self.repo / "hub" / ".venv" / "bin" / "python")
        done = self.guards(HUB_PYTHON="/nonexistent/python")
        self.assertEqual(done.returncode, 2, done.stderr)
        self.assertIn("HUB_PYTHON=/nonexistent/python is not an executable file", done.stderr)


if __name__ == "__main__":
    unittest.main()
