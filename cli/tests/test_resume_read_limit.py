"""A read the hub refuses with its read limit (§1.7 "Reads per credential") during `maity join`
and `maity resume`: neither ends in an error, and neither waits out the `Retry-After`.

The join exchange and the resume are writes, which the limit never counts; the CLI sends no
`GET /bootstrap`, the dashboard's call (§5.4). The one read is an admin's board check, whose
429 leaves the board unknown, not empty (tsk-ybc2ma72dzvq, 6a). Without a clone: the state
directory is named, so the tests need no Git remote.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import fakehub
import pytest
from test_onboarding import packet

from maity import cli, state

BOARD = "/api/v1/projects/oliver/maity/tasks"
REFUSED = (
    429,
    {"error": {"code": "rate_limited", "message": "too many reads", "details": {}}},
    {"Retry-After": "37"},
)


def _admin_packet() -> dict[str, Any]:
    """An admin with nothing to do: the resume reads the board for the empty-board hint."""
    return packet(
        membership={"trust": "admin", "role": "coder", "briefing": None},
        project={"slug": "maity", "full_name": "oliver/maity", "name": "Maity"},
    )


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.setenv("MAITY_STATE_DIR", str(tmp_path / "agent-state"))
    monkeypatch.chdir(elsewhere)
    return tmp_path / "agent-state"


@pytest.fixture
def slept(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    seconds: list[float] = []
    record: Callable[[float], None] = seconds.append
    monkeypatch.setattr(time, "sleep", record)
    return seconds


def _refuse_board(fake: fakehub.FakeHub) -> None:
    fake.routes[("POST", "/api/v1/me/resume")] = lambda _: (200, _admin_packet())
    fake.routes[("GET", BOARD)] = lambda _: REFUSED


def _reads(fake: fakehub.FakeHub) -> list[str]:
    return [s.path for s in fake.signed() if s.method in ("GET", "HEAD")]


def test_join_ends_well_when_the_first_resume_meets_the_read_limit(
    state_dir: Path,
    fake: fakehub.FakeHub,
    slept: list[float],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _refuse_board(fake)
    assert cli.main(["join", f"{fake.url}/j/{fakehub.TOKEN}", "--code", fakehub.CODE]) == 0
    out = capsys.readouterr()
    assert "first resume failed" not in out.err and "rate_limited" not in out.err
    assert "Next:" in out.out
    assert "As an admin you run the board" not in out.out  # unknown, not empty
    assert _reads(fake) == [BOARD]  # the exchange and the resume are writes
    assert slept == []
    assert state.load_state(state_dir)["session_id"] == "ses-b-0004"


def test_resume_ends_well_when_its_board_read_meets_the_read_limit(
    state_dir: Path,
    fake: fakehub.FakeHub,
    slept: list[float],
    capsys: pytest.CaptureFixture[str],
) -> None:
    state.write_credential(state_dir, state.Secret(fakehub.CREDENTIAL))
    state.save_state(state_dir, {"hub": fake.url, "project": "maity", "member_id": "agt-b"})
    _refuse_board(fake)
    assert cli.main(["resume"]) == 0
    out = capsys.readouterr()
    assert "rate_limited" not in out.err
    assert "Next:" in out.out and "As an admin you run the board" not in out.out
    assert _reads(fake) == [BOARD]
    assert slept == []
    assert state.load_state(state_dir)["board_empty"] is False
