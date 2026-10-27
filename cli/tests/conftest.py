from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import fakehub
import pytest

GIT = shutil.which("git")
GITHUB_URL = "https://github.com/acme/widget"


def git(cwd: Path, *args: str) -> str:
    assert GIT is not None
    proc = subprocess.run(
        [GIT, *args], cwd=cwd, capture_output=True, text=True, check=True, env=_git_env()
    )
    return proc.stdout.strip()


def _git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        GIT_AUTHOR_NAME="test",
        GIT_AUTHOR_EMAIL="test@example.invalid",
        GIT_COMMITTER_NAME="test",
        GIT_COMMITTER_EMAIL="test@example.invalid",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
    )
    return env


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test sees the developer's git config or a MAITY_STATE_DIR from the shell."""
    monkeypatch.delenv("MAITY_STATE_DIR", raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def bin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A PATH holding git and nothing else; tests add a fake gh to it when they need one."""
    assert GIT is not None, "the tests need git"
    path = tmp_path / "bin"
    path.mkdir()
    (path / "git").symlink_to(GIT)
    monkeypatch.setenv("PATH", str(path))
    return path


def fake_gh(bin_dir: Path, stdout: str, exit_code: int = 0, stderr: str = "") -> None:
    """A gh that answers every call with `stdout`; shell builtins only, PATH holds just git."""
    assert "'" not in stdout + stderr
    script = bin_dir / "gh"
    script.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' '{stdout}'\n"
        f"printf '%s\\n' '{stderr}' >&2\n"
        f"exit {exit_code}\n"
    )
    script.chmod(0o755)


@pytest.fixture
def clone(tmp_path: Path, bin_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A clone of a bare remote with one pushed commit on branch `work`, cwd set to it."""
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(remote))
    git(tmp_path, "clone", "--quiet", str(remote), str(work))
    # The remote reads as GitHub (what gh is asked about); git itself is sent to the bare repo.
    git(work, "remote", "set-url", "origin", GITHUB_URL)
    git(work, "config", f"url.{remote}.insteadOf", GITHUB_URL)
    git(work, "switch", "--quiet", "-c", "work")
    (work / "a.txt").write_text("one\n")
    git(work, "add", "a.txt")
    git(work, "commit", "--quiet", "-m", "one")
    git(work, "push", "--quiet", "-u", "origin", "work")
    monkeypatch.chdir(work)
    yield work


@pytest.fixture
def fake() -> Iterator[fakehub.FakeHub]:
    yield from fakehub.serve()


@pytest.fixture
def joined(clone: Path, fake: fakehub.FakeHub) -> Path:
    """`clone`, joined to the fake hub as agt-b in project maity."""
    from maity import state

    directory = state.resolve_state_dir()
    state.write_credential(directory, state.Secret(fakehub.CREDENTIAL))
    state.save_state(
        directory,
        {
            "hub": fake.url,
            "project": "oliver/maity",
            "project_id": "maity",
            "full_name": "oliver/maity",
            "member_id": "agt-b",
        },
    )
    return directory


@pytest.fixture(autouse=True)
def _home_secret(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The environment secret of the home (§5.3) goes to the test's own directory, never to
    the real ~/.local/state/maity."""
    from maity import environment

    monkeypatch.setattr(environment, "HOME_SECRET", tmp_path / "home-state" / "env-secret")
