"""hub/scripts/measure_arenas.py reports what failed, also when everything did."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load() -> Any:
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location(
            "measure_arenas", SCRIPTS / "measure_arenas.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def result(**more: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "arenas": "default",
        "rss_before_mib": 100.0,
        "rss_after_mib": 101.0,
        "wall_s": 2.0,
        "per_s": 0.0,
        "p50_ms": None,
        "p95_ms": None,
        "p99_ms": None,
        "n": 0,
        "growth": [101.0],
        "errors": {"warm-up": ["HTTP 503"] * 4, "burst": ["HTTP 503"] * 8},
    }
    return base | more


def test_a_run_where_every_request_failed_is_reported_invalid_not_a_crash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load()
    monkeypatch.setattr(script, "run_setting", lambda *args: result())
    monkeypatch.setattr(sys, "argv", ["measure_arenas.py", "--arenas", "default"])
    assert script.main() == 1  # invalid
    out = capsys.readouterr().out
    assert "failed: 12" in out and "n/a" in out
    assert "INVALID" in out and "warm-up: HTTP 503 x4" in out and "burst: HTTP 503 x8" in out


def test_a_clean_run_exits_zero_and_says_no_request_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    script = load()
    clean = result(
        per_s=140.0, p50_ms=10.0, p95_ms=200.0, p99_ms=800.0, n=2400, errors={"burst": []}
    )
    monkeypatch.setattr(script, "run_setting", lambda *args: clean)
    monkeypatch.setattr(sys, "argv", ["measure_arenas.py", "--arenas", "default"])
    assert script.main() == 0
    out = capsys.readouterr().out
    assert "failed: 0" in out and "INVALID" not in out and "p50 10 ms" in out
