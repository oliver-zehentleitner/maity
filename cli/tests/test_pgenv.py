"""`pgenv`: the session's command started with its own test cluster and password, or neither
(tsk-w7qtcbzcshn9, the review of #2032)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from conftest import posix

from maity.runner import pgenv, scratchop

pytestmark = [
    posix,
    pytest.mark.skipif(not scratchop.supported(), reason="no descriptor-relative open here"),
]


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """What pgenv would have exec'd: the command and the environment it would have had."""
    seen: list[dict[str, Any]] = []

    def execvp(file: str, args: list[str]) -> None:
        seen.append({"file": file, "args": list(args), "env": dict(os.environ)})
        raise SystemExit(0)  # an exec does not return

    monkeypatch.setattr(os, "execvp", execvp)
    for name in (pgenv.PASSWORD, pgenv.PG_DIR, pgenv.PLACEMENT):
        monkeypatch.delenv(name, raising=False)
    return seen


def _holder(tmp_path: Path) -> tuple[Path, Path, str]:
    root = tmp_path / "ws"
    root.mkdir()
    leaf = root / scratchop.PG_HOLDER / "plc-0003"
    assert scratchop.pg_make(str(root), str(leaf))["pg_pass"] is True
    return root, leaf, leaf.read_text().strip()


def _run(root: Path, leaf: Path, cluster: str = "/s/pg") -> None:
    with pytest.raises(SystemExit):
        pgenv.main([str(root), str(leaf), cluster, "--", "sh", "-c", "true"])


def test_the_own_placement_gets_its_cluster_and_password(
    tmp_path: Path, started: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    root, leaf, password = _holder(tmp_path)
    monkeypatch.setenv(pgenv.PLACEMENT, "plc-0003")
    _run(root, leaf)
    (call,) = started
    assert call["file"] == "sh" and call["args"] == ["sh", "-c", "true"]
    assert call["env"][pgenv.PASSWORD] == password and call["env"][pgenv.PG_DIR] == "/s/pg"
    assert password not in " ".join(call["args"])


@pytest.mark.parametrize("placed", ["plc-0004", "", None])
def test_another_or_no_placement_gets_neither(
    tmp_path: Path, started: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    placed: str | None,
) -> None:  # fmt: skip
    root, leaf, _ = _holder(tmp_path)
    if placed is not None:
        monkeypatch.setenv(pgenv.PLACEMENT, placed)
    _run(root, leaf)
    (call,) = started
    assert pgenv.PASSWORD not in call["env"] and pgenv.PG_DIR not in call["env"]


@pytest.mark.parametrize("planted", ["missing", "wide", "link", "odd"])
def test_a_password_file_not_vouched_for_gives_neither(
    tmp_path: Path, started: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch,
    planted: str,
) -> None:  # fmt: skip
    root, leaf, _ = _holder(tmp_path)
    if planted == "missing":
        leaf.unlink()
    elif planted == "wide":
        leaf.chmod(0o644)
    elif planted == "link":
        leaf.unlink()
        other = tmp_path / "other"
        other.write_text("b" * 64 + "\n")
        other.chmod(0o600)
        leaf.symlink_to(other)
    else:
        leaf.write_text("a b\n")
    monkeypatch.setenv(pgenv.PLACEMENT, "plc-0003")
    _run(root, leaf)
    (call,) = started
    assert pgenv.PASSWORD not in call["env"] and pgenv.PG_DIR not in call["env"]


def test_values_set_before_are_cleared_when_none_is_given(
    tmp_path: Path, started: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A MAITY_PG_DIR or password the launch environment carried never survives without the
    password pgenv read: a cluster dir without its password would be made with trust."""
    root, leaf, _ = _holder(tmp_path)
    monkeypatch.setenv(pgenv.PG_DIR, "/elsewhere/pg")
    monkeypatch.setenv(pgenv.PASSWORD, "planted")
    _run(root, leaf)  # no MAITY_PLACEMENT: nothing is read
    (call,) = started
    assert pgenv.PASSWORD not in call["env"] and pgenv.PG_DIR not in call["env"]


def test_a_malformed_call_starts_nothing(started: list[dict[str, Any]]) -> None:
    assert pgenv.main(["/w", "/w/.maity-pg/plc-0003", "/s/pg", "sh"]) == 2  # no `--`
    assert pgenv.main(["/w", "/w/.maity-pg/plc-0003", "/s/pg", "--"]) == 2  # no command
    assert started == []
