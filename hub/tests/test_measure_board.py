"""hub/scripts/measure_board.py runs against the hub's current routes: a path change that
breaks it breaks this test, not only the script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load() -> Any:
    spec = importlib.util.spec_from_file_location("measure_board", SCRIPTS / "measure_board.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_tiny_board_is_measured_on_the_project_paths(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The script reads the project under its full name (§6.25); each request must answer
    # 200, or its own assert stops the run.
    script = load()
    argv = ["measure_board.py", "--cards", "5", "--members", "2", "--events", "10"]
    monkeypatch.setattr(sys, "argv", [*argv, "--rounds", "1"])
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "/projects/maintainer/measure/tasks?status=all&limit=200" in out
    assert "/projects/maintainer/measure/events?after=0&limit=200" in out
