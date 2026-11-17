"""tools/guards.sh: the HUB_PYTHON default resolves to the work tree's own hub venv."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

GUARDS = Path(__file__).resolve().parents[2] / "tools" / "guards.sh"


def test_hub_python_defaults_to_the_clone_hub_venv(tmp_path: Path) -> None:
    """With HUB_PYTHON unset, guards.sh defaults it to `hub/.venv/bin/python` resolved from
    the work tree root (what the runner builds a placed coder, and `make -C hub dev` builds),
    so a plain `tools/guards.sh` needs no env prefix. Absent, it dies naming that path — not
    `python3`, the old default."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = {"PATH": os.environ.get("PATH", "")}  # no HUB_PYTHON
    done = subprocess.run(["bash", str(GUARDS)], cwd=repo, env=env, capture_output=True, text=True)
    assert done.returncode == 2
    assert "hub/.venv/bin/python is not an executable file" in done.stderr
    assert "python3" not in done.stderr  # the default is no longer a bare python3


def test_an_explicit_hub_python_is_still_honoured(tmp_path: Path) -> None:
    """A set HUB_PYTHON still wins over the default."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = {"PATH": os.environ.get("PATH", ""), "HUB_PYTHON": "/nonexistent/python"}
    done = subprocess.run(["bash", str(GUARDS)], cwd=repo, env=env, capture_output=True, text=True)
    assert done.returncode == 2
    assert "/nonexistent/python is not an executable file" in done.stderr
