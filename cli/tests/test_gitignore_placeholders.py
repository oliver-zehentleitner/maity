"""The repository's .gitignore hides the placeholders Claude Code's sandbox leaves at the root
of a clone (adapters.CLAUDE_PLACEHOLDERS), so tools/guards.sh, which reads .gitignore files
alone, starts in a placed coder's clone. The two lists stay equal."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from maity.runner.adapters import CLAUDE_PLACEHOLDERS

GITIGNORE = Path(__file__).resolve().parents[2] / ".gitignore"
HEAD = "# The empty placeholders Claude Code's sandbox leaves at the root of a clone it runs in"


def _block() -> list[str]:
    """The placeholder lines of the repository's .gitignore, without their leading slash."""
    lines = GITIGNORE.read_text().splitlines()
    start = lines.index(HEAD)
    entries = [line for line in lines[start:] if line and not line.startswith("#")]
    out = []
    for line in entries:
        if not line.startswith("/"):
            break
        out.append(line[1:])
    return out


def test_the_gitignore_block_is_the_adapters_list() -> None:
    assert sorted(_block()) == sorted(CLAUDE_PLACEHOLDERS)


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_guards_listing_shows_none_of_the_placeholders(tmp_path: Path) -> None:
    """What tools/guards.sh's clean check lists (untracked files by .gitignore alone) is empty
    when the work tree holds only the placeholders, each an empty file as the sandbox makes them."""
    env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)}
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True, env=env)
    repo = tmp_path / "repo"
    shutil.copyfile(GITIGNORE, repo / ".gitignore")
    for name in CLAUDE_PLACEHOLDERS:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).touch()
    listed = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-per-directory=.gitignore"],
        cwd=repo, env=env, check=True, capture_output=True, text=True,
    ).stdout.split()  # fmt: skip
    assert listed == [".gitignore"]
