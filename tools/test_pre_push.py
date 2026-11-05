"""tools/pre_push.py: the opt-in pre-push hook runs `make lint typecheck` for the packages a
push touches, only with the lock's tool versions and only when the working tree is what is
pushed."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "pre_push.py"
ZERO = "0" * 40
LOCK = (
    "black==26.10.1 \\\n    --hash=sha256:aa\n"
    "mypy==2.4.0 \\\n    --hash=sha256:bb\n"
    "ruff==0.17.1 \\\n    --hash=sha256:cc\n"
)
# Each package's lint and typecheck targets write what ran (and with which Python) to
# $HOOK_LOG; FAIL_<package>=1 makes its lint fail.
MAKEFILE = """\
lint:
\t@echo "{name} lint $({var})" >> "$$HOOK_LOG"
\t@[ "$$FAIL_{name}" != 1 ]
typecheck:
\t@echo "{name} typecheck $({var})" >> "$$HOOK_LOG"
"""


@unittest.skipIf(shutil.which("make") is None, "needs make")
class PrePushTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.log = self.tmp / "log"
        self.python = self.tmp / "python"
        self.versions = {"black": "26.10.1", "ruff": "0.17.1", "mypy": "2.4.0"}
        self.write_python()
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@example.org")
        self.git("config", "user.name", "t")
        for name, var in (("hub", "PYTHON"), ("cli", "PY")):
            (self.repo / name).mkdir()
            (self.repo / name / "Makefile").write_text(MAKEFILE.format(name=name, var=var))
        (self.repo / "hub" / "requirements").mkdir()
        (self.repo / "hub" / "requirements" / "dev.txt").write_text(LOCK)
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "a.md").write_text("a\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "base")
        self.base = self.git("rev-parse", "HEAD")
        self.git("update-ref", "refs/remotes/origin/main", self.base)

    def write_python(self) -> None:
        """A stand-in for the hub environment's Python: it answers the version query."""
        lines = "".join(f"echo {t} {v}\n" for t, v in self.versions.items())
        self.python.write_text(f"#!/bin/sh\n{lines}")
        self.python.chmod(0o755)

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.repo, check=True, capture_output=True, text=True
        ).stdout.strip()

    def commit(self, path: str) -> str:
        target = self.repo / path
        target.write_text(target.read_text() + "x\n" if target.exists() else "x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", path)
        return self.git("rev-parse", "HEAD")

    def push(self, *lines: str, **env: str) -> subprocess.CompletedProcess[str]:
        environ = {**os.environ, "HOOK_LOG": str(self.log), "MAITY_HOOK_PYTHON": str(self.python)}
        environ.update(env)
        return subprocess.run(
            ["python3", str(SCRIPT), "origin", "https://example.org/repo"],
            cwd=self.repo,
            input="".join(line + "\n" for line in lines),
            env=environ,
            capture_output=True,
            text=True,
        )

    def ran(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_a_push_outside_hub_and_cli_runs_nothing(self) -> None:
        sha = self.commit("docs/a.md")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), [])

    def test_only_the_touched_package_is_checked_with_the_hook_python(self) -> None:
        sha = self.commit("cli/x.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), [f"cli lint {self.python}", f"cli typecheck {self.python}"])

    def test_a_new_branch_is_compared_with_the_remote_main(self) -> None:
        sha = self.commit("hub/x.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {ZERO}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), [f"hub lint {self.python}", f"hub typecheck {self.python}"])

    def test_a_file_name_git_would_quote_still_counts_for_its_package(self) -> None:
        sha = self.commit("hub/\u00e9.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}", FAIL_hub="1")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.ran()[0], f"hub lint {self.python}")

    def test_an_annotated_tag_of_head_is_checked_as_its_commit(self) -> None:
        self.commit("hub/x.py")
        self.git("tag", "-a", "-m", "t", "t1")
        tag = self.git("rev-parse", "t1")
        result = self.push(f"refs/tags/t1 {tag} refs/tags/t1 {ZERO}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), [f"hub lint {self.python}", f"hub typecheck {self.python}"])

    def test_a_deletion_checks_nothing(self) -> None:
        result = self.push(f"(delete) {ZERO} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), [])

    def test_a_failing_lint_stops_the_push(self) -> None:
        sha = self.commit("hub/x.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}", FAIL_hub="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("lint or types failed in hub", result.stderr)

    def test_another_tool_version_than_the_lock_stops_before_any_check(self) -> None:
        self.versions["ruff"] = "0.17.3"
        self.write_python()
        sha = self.commit("hub/x.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("ruff 0.17.3 (lock: 0.17.1)", result.stderr)
        self.assertEqual(self.ran(), [])

    def test_an_uncommitted_change_in_a_touched_package_stops_it(self) -> None:
        sha = self.commit("hub/x.py")
        (self.repo / "hub" / "x.py").write_text("changed\n")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted changes in hub", result.stderr)
        self.assertEqual(self.ran(), [])

    def test_a_push_of_another_commit_than_head_stops_it(self) -> None:
        sha = self.commit("hub/x.py")
        self.commit("docs/a.md")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("HEAD is not the pushed commit", result.stderr)
        self.assertEqual(self.ran(), [])

    def test_a_missing_environment_says_how_to_make_it(self) -> None:
        sha = self.commit("hub/x.py")
        result = self.push(
            f"refs/heads/b {sha} refs/heads/b {self.base}",
            MAITY_HOOK_PYTHON=str(self.tmp / "nowhere" / "python"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("make -C hub install", result.stderr)


if __name__ == "__main__":
    unittest.main()
