"""`scripts/with_postgres.sh`, with stand-ins for PostgreSQL's tools: it stops what it started,
keeps a server started for everyone, and runs in a run slot that the server does not hold."""

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
  "pg_ctl "*" start")
    touch "$FAKE_UP"; echo "$$" > "$MAITY_PG_DIR/postmaster.pid"
    if [ -e /proc/$$/fd/7 ]; then echo "server holds fd 7" >> "$FAKE_LOG"; fi ;;
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
    env = {key: value for key, value in os.environ.items() if key != "MAITY_RUN_SLOT"}
    return {
        **env,
        "MAITY_RUN_SLOTS_DIR": str(tmp_path / "slots"),
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
    else:  # the deadline passed: a hung script must not hang the run with it
        os.kill(pid, signal.SIGKILL)
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


def test_start_leaves_the_server_up_for_everyone(run: dict[str, str]) -> None:
    subprocess.run([SCRIPT, "--start"], env=run, check=True)
    subprocess.run([SCRIPT, "true"], env=run, check=True)
    assert len(calls(run, "start")) == 1 and calls(run, "stop") == []
    assert Path(run["FAKE_UP"]).exists()


def test_start_keeps_a_server_a_running_run_started(run: dict[str, str]) -> None:
    gate = Path(run["FAKE_LOG"]).parent / "gate"
    first = subprocess.Popen(
        [SCRIPT, "sh", "-c", f"until [ -f {gate} ]; do sleep 0.05; done"], env=run
    )
    while not Path(run["FAKE_UP"]).exists():
        assert first.poll() is None
    subprocess.run([SCRIPT, "--start"], env=run, check=True)
    gate.touch()
    assert first.wait(timeout=30) == 0
    assert calls(run, "stop") == []


def test_stop_waits_for_no_run_and_refuses_while_one_runs(run: dict[str, str]) -> None:
    subprocess.run([SCRIPT, "--start"], env=run, check=True)
    gate = Path(run["FAKE_LOG"]).parent / "gate"
    ready = Path(run["FAKE_LOG"]).parent / "ready"
    first = subprocess.Popen(
        [SCRIPT, "sh", "-c", f"touch {ready}; until [ -f {gate} ]; do sleep 0.05; done"], env=run
    )
    while not ready.exists():
        assert first.poll() is None
    refused = subprocess.run([SCRIPT, "--stop"], env=run, capture_output=True, text=True)
    assert refused.returncode == 1 and "still uses the server" in refused.stderr
    assert calls(run, "stop") == []
    gate.touch()
    assert first.wait(timeout=30) == 0
    subprocess.run([SCRIPT, "--stop"], env=run, check=True)
    assert len(calls(run, "stop")) == 1 and not Path(run["FAKE_UP"]).exists()


def test_the_database_is_named_after_who_runs_it(run: dict[str, str]) -> None:
    run = {**run, "MAITY_RUN_NAME": "Coder-7#ab12"}
    out = subprocess.run(
        [SCRIPT, "sh", "-c", 'echo "$MAITY_TEST_DATABASE_URL"'],
        env=run,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert out.startswith("postgresql://postgres@/maity_test_coder_7_ab12_")


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="needs /proc")
def test_the_run_holds_a_slot_and_the_server_does_not(run: dict[str, str]) -> None:
    out = subprocess.run(
        [SCRIPT, "sh", "-c", 'echo "slot=$MAITY_RUN_SLOT"'],
        env=run,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert out.strip() == "slot=0"
    assert "server holds fd 7" not in Path(run["FAKE_LOG"]).read_text()


def test_stop_leaves_the_server_up_under_a_command_whose_wrapper_was_killed(
    run: dict[str, str], tmp_path: Path
) -> None:
    """A memory reap kills the wrapper with SIGKILL; its command lives on and uses the server."""
    subprocess.run([SCRIPT, "--start"], env=run, check=True)
    child_pid = tmp_path / "child"
    wrapper = subprocess.Popen(
        [SCRIPT, "sh", "-c", f"echo $$ > {child_pid}; exec sleep 60"], env=run
    )
    while not child_pid.exists() or not child_pid.read_text().strip():
        assert wrapper.poll() is None
    child = int(child_pid.read_text())
    try:
        wrapper.kill()
        wrapper.wait(timeout=30)
        os.kill(child, 0)  # the command outlived its wrapper
        refused = subprocess.run([SCRIPT, "--stop"], env=run, capture_output=True, text=True)
        assert refused.returncode == 1 and "still uses the server" in refused.stderr
        assert calls(run, "stop") == []
    finally:
        os.kill(child, signal.SIGKILL)
    deadline = time.monotonic() + 30
    while subprocess.run([SCRIPT, "--stop"], env=run, capture_output=True).returncode != 0:
        assert time.monotonic() < deadline, "the server stays held after the command ended"
        time.sleep(0.05)
    assert len(calls(run, "stop")) == 1


def test_stop_on_a_stopped_server_starts_nothing(run: dict[str, str]) -> None:
    """Neither a stopped server nor a missing data directory (a mistyped MAITY_PG_DIR) is started
    or created by --stop just to be stopped again."""
    subprocess.run([SCRIPT, "--stop"], env=run, check=True)
    (Path(run["MAITY_PG_DIR"]) / "PG_VERSION").touch()
    subprocess.run([SCRIPT, "--stop"], env=run, check=True)
    log = Path(run["FAKE_LOG"]).read_text() if Path(run["FAKE_LOG"]).exists() else ""
    assert "initdb" not in log and calls(run, "start") == [] and calls(run, "stop") == []


def test_the_cleanup_matches_its_own_databases_only(run: dict[str, str]) -> None:
    """`_` in the run's name is a wildcard in LIKE; the cleanup compares the prefix instead."""
    subprocess.run([SCRIPT, "true"], env={**run, "MAITY_RUN_NAME": "a_b"}, check=True)
    lines = Path(run["FAKE_LOG"]).read_text().splitlines()
    (query,) = [line for line in lines if line.startswith("psql") and "select datname" in line]
    assert " like " not in query.lower()
    assert "left(datname, length('maity_test_a_b_" in query
