"""`scripts/with_postgres.sh`, with stand-ins for PostgreSQL's tools: it stops what it started."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")

SCRIPT = Path(__file__).parent.parent / "scripts" / "with_postgres.sh"
FAKE = """#!/bin/sh
echo "$(basename "$0") $*" >> "$FAKE_LOG"
case "$(basename "$0") $*" in
  "pg_ctl -D "*" status") [ -f "$FAKE_UP" ] ;;
  "pg_ctl "*" start") touch "$FAKE_UP" ;;
  "pg_ctl "*" stop") rm -f "$FAKE_UP" ;;
  initdb*) touch "$3/PG_VERSION" ;;
esac
"""


@pytest.fixture
def run(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("pg_ctl", "psql"):
        (bin_dir / tool).write_text(FAKE)
        (bin_dir / tool).chmod(0o755)
    data = tmp_path / "data"
    data.mkdir()
    (bin_dir / "initdb").write_text(FAKE.replace('touch "$3/PG_VERSION"', 'touch "$2/PG_VERSION"'))
    (bin_dir / "initdb").chmod(0o755)
    return {
        **os.environ,
        "MAITY_PG_BIN": str(bin_dir),
        "MAITY_PG_DIR": str(data),
        "FAKE_LOG": str(tmp_path / "log"),
        "FAKE_UP": str(tmp_path / "up"),
    }


def calls(env: dict[str, str], tool: str) -> list[str]:
    lines = Path(env["FAKE_LOG"]).read_text().splitlines()
    return [line for line in lines if line.startswith("pg_ctl") and line.endswith(tool)]


def test_it_stops_the_server_it_started(run: dict[str, str]) -> None:
    subprocess.run([SCRIPT, "true"], env=run, check=True)
    assert len(calls(run, "start")) == 1 and len(calls(run, "stop")) == 1
    assert not Path(run["FAKE_UP"]).exists()


def test_a_server_that_was_up_keeps_running(run: dict[str, str]) -> None:
    Path(run["FAKE_UP"]).touch()
    subprocess.run([SCRIPT, "true"], env=run, check=True)
    assert calls(run, "start") == [] and calls(run, "stop") == []
    assert Path(run["FAKE_UP"]).exists()


def test_the_last_run_stops_it_not_the_first(run: dict[str, str]) -> None:
    """A run ending while another still uses the server leaves it up."""
    gate = Path(run["FAKE_LOG"]).parent / "gate"
    first = subprocess.Popen(
        [SCRIPT, "sh", "-c", f"until [ -f {gate} ]; do sleep 0.05; done"], env=run
    )
    while not Path(run["FAKE_UP"]).exists():
        assert first.poll() is None
    subprocess.run([SCRIPT, "true"], env=run, check=True)
    assert calls(run, "stop") == []
    gate.touch()
    assert first.wait(timeout=30) == 0
    assert len(calls(run, "stop")) == 1


def test_the_commands_exit_status_is_kept(run: dict[str, str]) -> None:
    assert subprocess.run([SCRIPT, "false"], env=run).returncode == 1
