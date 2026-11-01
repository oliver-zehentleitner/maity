"""`scripts/with_postgres.sh`, with stand-ins for PostgreSQL's tools: it stops what it started."""

from __future__ import annotations

import os
import pty
import select
import shutil
import signal
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("flock") is None, reason="needs util-linux flock")

SCRIPT = Path(__file__).parent.parent / "scripts" / "with_postgres.sh"
FAKE = """#!/bin/sh
echo "$(basename "$0") $*" >> "$FAKE_LOG"
case "$(basename "$0") $*" in
  "pg_ctl -D "*" status") [ -f "$FAKE_UP" ] ;;
  "pg_ctl "*" start") touch "$FAKE_UP"; echo "$$" > "$MAITY_PG_DIR/postmaster.pid" ;;
  "pg_ctl "*" stop") rm -f "$FAKE_UP" "$MAITY_PG_DIR/postmaster.pid" ;;
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


def test_a_mark_left_by_a_killed_run_stops_no_later_server(run: dict[str, str]) -> None:
    data = Path(run["MAITY_PG_DIR"])
    (data / "PG_VERSION").touch()
    (data.parent / "data.locks").mkdir()
    (data.parent / "data.locks" / "started-by-script").write_text("1\n")
    (data / "postmaster.pid").write_text("2\n")
    Path(run["FAKE_UP"]).touch()
    subprocess.run([SCRIPT, "true"], env=run, check=True)
    assert calls(run, "stop") == []


@pytest.mark.parametrize("sent", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_a_signal_reaches_the_command_and_the_cleanup_waits_for_it(
    run: dict[str, str], tmp_path: Path, sent: signal.Signals
) -> None:
    ended = tmp_path / "ended"
    ready = tmp_path / "ready"
    command = f"trap 'sleep 0.3; touch {ended}; exit 7' {sent.name[3:]}; touch {ready}; "
    command += "while :; do sleep 0.05; done"
    script = subprocess.Popen([SCRIPT, "sh", "-c", command], env=run)
    while not ready.exists():
        assert script.poll() is None
    script.send_signal(sent)
    assert script.wait(timeout=30) == 7
    assert ended.exists() and len(calls(run, "stop")) == 1


def at_a_terminal(env: dict[str, str], command: str, typed: bytes) -> tuple[int, bytes]:
    """Runs the script on a terminal of its own, types once the command is up; status, output."""
    pid, terminal = pty.fork()
    if pid == 0:
        os.execve(str(SCRIPT), [str(SCRIPT), "sh", "-c", command], env)
    seen = b""
    deadline = time.monotonic() + 30
    sent = False
    while time.monotonic() < deadline:
        if select.select([terminal], [], [], 0.1)[0]:
            try:
                chunk = os.read(terminal, 1024)
            except OSError:  # the terminal's other end closed
                break
            if not chunk:
                break
            seen += chunk
        if not sent and b"up" in seen:
            os.write(terminal, typed)
            sent = True
    os.close(terminal)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status), seen


def test_at_a_terminal_the_command_can_read(run: dict[str, str]) -> None:
    status, seen = at_a_terminal(run, 'echo up; read line; echo "got $line"', b"hello\n")
    assert status == 0 and b"got hello" in seen
    assert len(calls(run, "stop")) == 1


def test_at_a_terminal_ctrl_c_ends_the_command_and_cleans_up(run: dict[str, str]) -> None:
    status, _ = at_a_terminal(run, "echo up; while :; do sleep 0.05; done", b"\x03")
    assert status != 0
    assert len(calls(run, "stop")) == 1


def test_the_commands_exit_status_is_kept(run: dict[str, str]) -> None:
    assert subprocess.run([SCRIPT, "false"], env=run).returncode == 1
