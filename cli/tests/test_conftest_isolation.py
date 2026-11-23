"""A test's git reaches only the repositories the test makes, whatever the shell sets."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from conftest import git, isolate_git


def test_no_test_sees_the_shells_git_variables() -> None:
    # In a runner placement this fails without isolate_git.
    names = sorted(n for n in os.environ if n.startswith("GIT_"))
    assert names == ["GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM"]


def test_a_tests_git_writes_into_its_own_repository_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The decoy stands for the session's clone. Without isolate_git, GIT_COMMON_DIR sends
    `init` and `config` to it, so this fails anywhere, CI included."""
    decoy = tmp_path / "decoy"
    git(tmp_path, "init", "--quiet", str(decoy))
    before = (decoy / ".git" / "config").read_bytes()
    # Aimed at the decoy the way a runner session is (runner/adapters.py).
    monkeypatch.setenv("GIT_COMMON_DIR", str(decoy / ".git"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(tmp_path / "hooks"))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'user.name=leak'")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))

    isolate_git(monkeypatch)
    remote = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(remote))
    git(remote, "config", "test.key", "value")

    assert (decoy / ".git" / "config").read_bytes() == before
    assert "key = value" in (remote / "config").read_text()
    assert git(remote, "config", "--get", "test.key") == "value"
    with pytest.raises(subprocess.CalledProcessError):
        git(remote, "config", "--get", "core.hooksPath")
    # GIT_CONFIG_PARAMETERS, which the sandbox sets, must not leak either.
    with pytest.raises(subprocess.CalledProcessError):
        git(remote, "config", "--get", "user.name")
    # GIT_DIR must not take a test's git to the decoy either.
    assert Path(git(remote, "rev-parse", "--absolute-git-dir")) == remote.resolve()
