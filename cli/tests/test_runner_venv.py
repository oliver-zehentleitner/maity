"""The shared dev venv the runner builds per placement (maity.runner.venv, docs/runners.md)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from maity.runner import venv
from maity.runner.asuser import AsUser

LOCK = "pytest==8.0.0 \\\n    --hash=sha256:" + "0" * 64 + "\n"


def _fake_run(into: Path, runs: list[list[str]]) -> Any:
    """Stand in for `AsUser.run`: `python -m venv` makes the interpreter the real build would,
    `pip install` succeeds; everything is recorded."""

    def run(self: AsUser, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        runs.append(list(argv))
        if "venv" in argv:
            (into / "bin").mkdir(parents=True, exist_ok=True)
            (into / "bin" / "python").write_text("#!/bin/sh\n")
        return subprocess.CompletedProcess(argv, 0, "", "")

    return run


def _lock(tmp_path: Path, text: str = LOCK) -> tuple[Path, Path]:
    clone = tmp_path / "clone"
    requirements = clone / "requirements" / "dev.txt"
    requirements.parent.mkdir(parents=True)
    requirements.write_text(text)
    return clone, requirements


def test_the_venv_is_built_from_the_locked_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone, requirements = _lock(tmp_path)
    into = tmp_path / "agent" / "venv"
    runs: list[list[str]] = []
    monkeypatch.setattr(AsUser, "run", _fake_run(into, runs))

    bin_dir = venv.ensure(AsUser(), into, requirements, clone)

    assert bin_dir == into / "bin"
    # A venv is created, then the lock is installed with its hashes required.
    assert ["-m", "venv"] == [runs[0][runs[0].index("-m")], "venv"]
    install = next(r for r in runs if "pip" in r)
    assert "--require-hashes" in install and str(requirements) in install
    # The marker records what it was built for, so a later start can reuse it.
    assert json.loads((into / venv.MARKER).read_text())["key"] == venv.key(
        requirements.read_bytes(), __import__("sys").executable
    )


def test_an_identical_build_is_reused_not_rebuilt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clone, requirements = _lock(tmp_path)
    into = tmp_path / "agent" / "venv"
    runs: list[list[str]] = []
    monkeypatch.setattr(AsUser, "run", _fake_run(into, runs))

    venv.ensure(AsUser(), into, requirements, clone)
    runs.clear()
    assert venv.ensure(AsUser(), into, requirements, clone) == into / "bin"
    assert runs == []  # nothing rebuilt: the marker matched


def test_a_changed_lock_rebuilds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clone, requirements = _lock(tmp_path)
    into = tmp_path / "agent" / "venv"
    runs: list[list[str]] = []
    monkeypatch.setattr(AsUser, "run", _fake_run(into, runs))

    venv.ensure(AsUser(), into, requirements, clone)
    runs.clear()
    requirements.write_text("ruff==0.6.0 \\\n    --hash=sha256:" + "1" * 64 + "\n")
    venv.ensure(AsUser(), into, requirements, clone)
    assert any("venv" in r for r in runs)  # the key changed, so it was built again


def test_a_failed_pip_install_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clone, requirements = _lock(tmp_path)
    into = tmp_path / "agent" / "venv"

    def run(self: AsUser, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "venv" in argv:
            (into / "bin").mkdir(parents=True, exist_ok=True)
            (into / "bin" / "python").write_text("#!/bin/sh\n")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 1, "", "hash mismatch")

    monkeypatch.setattr(AsUser, "run", run)
    with pytest.raises(venv.VenvError):
        venv.ensure(AsUser(), into, requirements, clone)
    # No marker is left, so the next start builds again rather than reusing a half-built venv.
    assert not (into / venv.MARKER).exists()
