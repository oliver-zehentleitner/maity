"""A Codex start stops the app-server daemon an earlier start left in the placement's
codex-home (runner/codexd.py, card tsk-n6sajs3gyh8h): `codex app-server daemon stop`, else on
this host the processes that name that CODEX_HOME; a failed stop is logged, never refused."""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from test_supervisor import (
    SESSION,
    Clock,
    FakeTmux,
    Reports,
    load,
    placement,
    recorded,
    settle,
    started,
)

from maity.runner import capabilities, codexd, supervisor


def fake_codex(path: Path, calls: Path, stop_exit: int = 0) -> None:
    """A codex that writes `$*|$CODEX_HOME` to `calls` for `app-server daemon stop` and exits
    `stop_exit` there; anything else exits 0 and writes nothing."""
    path.write_text(
        "#!/bin/sh\n"
        'if [ "$*" = "app-server daemon stop" ]; then\n'
        f"  printf '%s\\n' \"$*|$CODEX_HOME\" >> '{calls}'\n"
        f"  exit {stop_exit}\n"
        "fi\n"
        "exit 0\n"
    )
    path.chmod(0o755)


@pytest.fixture
def world(tmp_path: Path) -> Any:
    """test_supervisor's world, its codex probed at the fake above, and each session's start
    written to the same file as `launch|<its CODEX_HOME>`, so the order of the two shows."""
    cfg = load(tmp_path)
    clock, reports, backend = Clock(), Reports(), FakeTmux()
    logs: list[str] = []
    calls = tmp_path / "calls.log"
    fake_codex(tmp_path / "codex", calls)
    original = backend.start

    def start(name: str, cwd: Path, argv: Sequence[str], env: dict[str, str],
              placement: str, generation: int) -> None:  # fmt: skip
        with calls.open("a") as out:
            out.write(f"launch|{env.get('CODEX_HOME', '')}\n")
        original(name, cwd, argv, env, placement, generation)

    backend.start = start  # type: ignore[method-assign]
    probes = {
        "stub": capabilities.Probe(None, None, None),
        "codex": capabilities.Probe(str(tmp_path / "codex"), "0.40.0", None),
    }
    sup = supervisor.Supervisor(
        cfg, backend, reports, logs.append, probes, now=clock, rand=lambda: 0.5  # type: ignore[arg-type]
    )
    return sup, backend, reports, clock, logs


def restart(world: Any) -> None:
    """The session exits and the placement starts again after its backoff."""
    sup, backend, _, clock, _ = world
    backend.exit(SESSION, 0)
    sup.tick()
    clock.now += 600
    settle(sup)
    assert SESSION in backend.live and len(backend.started) == 2, sup.records


def codex_home(sup: supervisor.Supervisor) -> Path:
    assert sup.cfg.local is not None
    scratch = sup.cfg.local.workspaces.resolve() / ".scratch" / "maity" / "plc-0003"
    return scratch / "codex-home"


def test_a_codex_start_stops_the_daemon_left_in_its_codex_home(world: Any, tmp_path: Path) -> None:
    """The restart stops the daemon in this placement's codex-home before its session starts.
    The first start has no codex-home yet (the launch writes it), so nothing to stop: it says
    so and starts."""
    sup, backend, _, _, logs = world
    started(world)
    restart(world)
    home = codex_home(sup)
    assert backend.started[-1][2]["CODEX_HOME"] == str(home)  # the home the launch env names
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls == [f"launch|{home}", f"app-server daemon stop|{home}", f"launch|{home}"]
    assert logs.count("plc-0003: no codex-home yet, so no Codex app-server daemon to stop") == 1
    assert not any("`codex app-server daemon stop`" in line for line in logs), logs


def test_a_failing_daemon_stop_does_not_refuse_the_start(world: Any, tmp_path: Path) -> None:
    sup, _, reports, _, logs = world
    fake_codex(tmp_path / "codex", tmp_path / "calls.log", stop_exit=1)
    started(world)
    restart(world)
    home = codex_home(sup)
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls[-2:] == [f"app-server daemon stop|{home}", f"launch|{home}"]
    failed = [line for line in logs if "`codex app-server daemon stop` exited 1" in line]
    assert len(failed) == 1, logs
    assert failed[0].startswith("plc-0003: ") and failed[0].endswith("the start goes on")
    assert all(b["state"] != "failed" for _, b in reports.sent)


def test_a_non_codex_start_runs_no_daemon_stop(world: Any, tmp_path: Path) -> None:
    """A stub placement, restarted, in a world whose codex would write the stop: none."""
    sup, _, _, _, logs = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    restart(world)
    assert (tmp_path / "calls.log").read_text().splitlines() == ["launch|", "launch|"]
    assert not any("app-server daemon" in line for line in logs), logs


def test_a_stop_with_a_binary_outside_the_tests_tmp_dir_fails_the_test(
    tmp_path: Path, codex_guard: list[str]
) -> None:
    """conftest's guard: a real Codex never starts from a test. `stop_argv` only builds the
    command, so the raise is all there is to see; the record it leaves for the teardown's
    check is emptied, or this test would fail there."""
    with pytest.raises(pytest.fail.Exception):
        codexd.stop_argv("/usr/bin/codex", tmp_path / "h", tmp_path, "/usr/bin")
    assert codex_guard == ["/usr/bin/codex"]
    codex_guard.clear()


def _exec_done(pid: int, home: Path) -> None:
    """Wait until the child runs with its own environment: before its exec it has ours."""
    wanted = f"CODEX_HOME={home}".encode()
    deadline = time.monotonic() + 5
    while wanted not in Path(f"/proc/{pid}/environ").read_bytes():
        assert time.monotonic() < deadline, "the child never exec'd"
        time.sleep(0.01)


@pytest.mark.skipif(sys.platform != "linux", reason="the fallback reads /proc")
def test_the_fallback_signals_only_this_placements_daemon(tmp_path: Path) -> None:
    """Two processes of this uid, each in a group of its own: one with this placement's
    CODEX_HOME, one with another placement's home whose path starts with the same letters.
    Only the first is ended; the home is named through a link and still matches resolved."""
    mine, theirs = tmp_path / "a" / "codex-home", tmp_path / "a" / "codex-home-2"
    mine.mkdir(parents=True)
    theirs.mkdir()
    (tmp_path / "link").symlink_to(tmp_path / "a")
    sleep = shutil.which("sleep")
    assert sleep is not None
    children = [
        subprocess.Popen([sleep, "60"], env={"CODEX_HOME": str(home)}, start_new_session=True)
        for home in (mine, theirs)
    ]
    try:
        for child, home in zip(children, (mine, theirs), strict=True):
            _exec_done(child.pid, home)
        found = codexd.stop_by_home(str(tmp_path / "link" / "codex-home"), grace=0.2)
        assert children[0].wait(timeout=5) == -signal.SIGTERM
        assert children[1].poll() is None  # another placement's daemon runs on
        assert found == {"termed": 1, "killed": 0}
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
