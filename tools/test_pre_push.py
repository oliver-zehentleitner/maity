"""tools/pre_push.py: the opt-in pre-push hook runs `make lint typecheck` for the packages a
push touches and `ktw-lint` for the Keep the Why projects it touches, only with the versions CI
uses and only when the working tree is what is pushed."""

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
PIN = "0.20.3.1"
WORKFLOW = (
    "      - uses: oliver-zehentleitner/keep-the-why@1af21fcc16a52e2971083ffb96d92b0f1f008399"
    f" # lint-v{PIN}\n"
)
# A stand-in for ktw-lint: it answers --version with $KTW_VERSION (default the pin), logs
# every lint to $HOOK_LOG, and fails for the project named in $KTW_FAIL.
KTW_LINT = """\
#!/bin/sh
if [ "$1" = --version ]; then echo "ktw-lint ${KTW_VERSION:-@PIN@}"; exit 0; fi
echo "ktw $1" >> "$HOOK_LOG"
[ "$1" != "$KTW_FAIL" ] || { echo "ktw-lint: 1 error(s)"; exit 1; }
""".replace("@PIN@", PIN)


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
        self.ktw_lint = self.tmp / "ktw-lint"
        self.ktw_lint.write_text(KTW_LINT)
        self.ktw_lint.chmod(0o755)
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
        (self.repo / ".github" / "workflows").mkdir(parents=True)
        (self.repo / ".github" / "workflows" / "ktw-lint.yml").write_text(WORKFLOW)
        for project in ("", "hub/", "cli/", "web/"):
            (self.repo / f"{project}context").mkdir(parents=True)
            (self.repo / f"{project}context" / "index.md").write_text("i\n")
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
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(target.read_text() + "x\n" if target.exists() else "x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", path)
        return self.git("rev-parse", "HEAD")

    def push(self, *lines: str, **env: str) -> subprocess.CompletedProcess[str]:
        environ = {
            **os.environ,
            "HOOK_LOG": str(self.log),
            "MAITY_HOOK_PYTHON": str(self.python),
            "MAITY_HOOK_KTW_LINT": str(self.ktw_lint),
        }
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

    def test_a_push_outside_hub_and_cli_runs_only_ktw_lint_of_the_root(self) -> None:
        sha = self.commit("docs/a.md")
        result = self.push(
            f"refs/heads/b {sha} refs/heads/b {self.base}",
            MAITY_HOOK_PYTHON=str(self.tmp / "nowhere" / "python"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), ["ktw ."])

    def test_only_the_touched_package_is_checked_with_the_hook_python(self) -> None:
        sha = self.commit("cli/x.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.ran(), [f"cli lint {self.python}", f"cli typecheck {self.python}", "ktw cli"]
        )

    def test_a_new_branch_is_compared_with_the_remote_main(self) -> None:
        sha = self.commit("hub/x.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {ZERO}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.ran(), [f"hub lint {self.python}", f"hub typecheck {self.python}", "ktw hub"]
        )

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
        self.assertEqual(
            self.ran(), [f"hub lint {self.python}", f"hub typecheck {self.python}", "ktw hub"]
        )

    def test_a_deletion_checks_nothing(self) -> None:
        result = self.push(f"(delete) {ZERO} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), [])

    def test_a_failing_lint_stops_the_push(self) -> None:
        sha = self.commit("hub/x.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}", FAIL_hub="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed: lint or types in hub. Nothing was pushed.", result.stderr)
        self.assertIn("ktw hub", self.ran())

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

    # ktw-lint (tsk-nb0f9gq7qyrb).

    def test_a_failing_ktw_lint_stops_the_push_and_names_the_project(self) -> None:
        sha = self.commit("web/context/index.md")
        result = self.push(
            f"refs/heads/b {sha} refs/heads/b {self.base}",
            KTW_FAIL="web",
            MAITY_HOOK_PYTHON=str(self.tmp / "nowhere" / "python"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed: ktw-lint web. Nothing was pushed.", result.stderr)
        self.assertIn("ktw-lint: 1 error(s)", result.stdout)
        # web/'s context reaches the root (a family link is checked on both ends).
        self.assertEqual(self.ran(), ["ktw .", "ktw web"])

    def test_a_change_outside_context_lints_only_its_project(self) -> None:
        sha = self.commit("web/src/a.js")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), ["ktw web"])

    def test_the_root_s_context_reaches_every_child(self) -> None:
        sha = self.commit("context/index.md")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.ran(), ["ktw .", "ktw hub", "ktw cli", "ktw web"])

    def test_another_ktw_lint_version_stops_before_any_check(self) -> None:
        sha = self.commit("hub/x.py")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}", KTW_VERSION="0.20.3.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("found ktw-lint 0.20.3.0", result.stderr)
        self.assertIn(f"CI runs ktw-lint {PIN}", result.stderr)
        self.assertIn(f"pipx install --force keep-the-why-lint=={PIN}", result.stderr)
        self.assertEqual(self.ran(), [])

    def test_no_ktw_lint_stops_the_push(self) -> None:
        sha = self.commit("web/src/a.js")
        result = self.push(
            f"refs/heads/b {sha} refs/heads/b {self.base}",
            MAITY_HOOK_KTW_LINT=str(self.tmp / "nowhere" / "ktw-lint"),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("no ktw-lint that answers --version", result.stderr)
        self.assertEqual(self.ran(), [])

    def test_no_pin_in_the_workflow_stops_the_push(self) -> None:
        (self.repo / ".github" / "workflows" / "ktw-lint.yml").write_text("jobs: {}\n")
        sha = self.commit("web/src/a.js")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no `# lint-vX` pin", result.stderr)
        self.assertEqual(self.ran(), [])

    def test_an_uncommitted_context_change_stops_its_lint(self) -> None:
        sha = self.commit("web/src/a.js")
        (self.repo / "web" / "context" / "index.md").write_text("changed\n")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}")
        self.assertEqual(result.returncode, 1)
        self.assertIn("uncommitted changes in web/context, web/.keep-the-why", result.stderr)
        self.assertEqual(self.ran(), [])

    def test_the_pin_is_read_from_the_pushed_commit_not_the_working_tree(self) -> None:
        """Review R1 of #1508: an uncommitted edit of the workflow's pin chose the linter."""
        sha = self.commit("docs/a.md")
        workflow = self.repo / ".github" / "workflows" / "ktw-lint.yml"
        workflow.write_text(WORKFLOW.replace(PIN, "0.20.3.0"))
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}", KTW_VERSION="0.20.3.0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("found ktw-lint 0.20.3.0", result.stderr)
        self.assertIn(f"CI runs ktw-lint {PIN}", result.stderr)
        self.assertEqual(self.ran(), [])

    def test_a_file_moved_out_of_a_project_lints_the_project_it_left(self) -> None:
        """Review R1 of #1508: with rename detection only the destination counted."""
        (self.repo / "web" / "src").mkdir(parents=True)
        self.git("mv", "hub/context/index.md", "web/src/hub-index.md")
        self.git("commit", "-q", "-m", "move")
        sha = self.git("rev-parse", "HEAD")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {self.base}", KTW_FAIL="hub")
        self.assertEqual(result.returncode, 1)
        self.assertIn("failed: ktw-lint hub.", result.stderr)
        self.assertIn("ktw hub", self.ran())
        self.assertIn("ktw web", self.ran())

    def test_a_ktw_lint_that_vanishes_after_its_version_is_a_failure(self) -> None:
        sha = self.commit("web/src/a.js")
        vanishing = self.tmp / "vanishing"
        vanishing.write_text(
            f'#!/bin/sh\nif [ "$1" = --version ]; then echo "ktw-lint {PIN}"; rm -f "$0"; fi\n'
        )
        vanishing.chmod(0o755)
        result = self.push(
            f"refs/heads/b {sha} refs/heads/b {self.base}", MAITY_HOOK_KTW_LINT=str(vanishing)
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("ktw-lint web could not run", result.stderr)
        self.assertIn("failed: ktw-lint web.", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_new_branch_without_a_remote_main_checks_everything(self) -> None:
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        sha = self.commit("docs/a.md")
        result = self.push(f"refs/heads/b {sha} refs/heads/b {ZERO}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.ran(),
            [
                f"hub lint {self.python}",
                f"hub typecheck {self.python}",
                f"cli lint {self.python}",
                f"cli typecheck {self.python}",
                "ktw .",
                "ktw hub",
                "ktw cli",
                "ktw web",
            ],
        )


if __name__ == "__main__":
    unittest.main()
