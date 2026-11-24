"""A Codex start stops the app-server daemon an earlier start left in the placement's
codex-home (runner/codexd.py, card tsk-n6sajs3gyh8h): `codex app-server daemon stop` within
one deadline; a failed stop is logged, never refused."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

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
from maity.runner.asuser import AsUser


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
    sup, backend, reports, _, logs = world
    fake_codex(tmp_path / "codex", tmp_path / "calls.log", stop_exit=1)
    started(world)
    restart(world)
    home = codex_home(sup)
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert calls[-2:] == [f"app-server daemon stop|{home}", f"launch|{home}"]
    failed = [line for line in logs if "`codex app-server daemon stop` exited 1" in line]
    assert len(failed) == 1, logs
    assert failed[0] == "plc-0003: `codex app-server daemon stop` exited 1; the start goes on"
    assert not any("fallback" in line for line in logs), logs  # nothing is signalled
    assert len(backend.started) == 2  # the start went on
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


def test_a_slow_home_check_is_bounded_and_does_not_refuse_the_start(
    world: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A home check that does not answer gets at most CHECK_TIMEOUT, then no stop is tried
    (the home's state is unknown) and the start goes on. Here, the runner's own side, the
    check is replaced; the agents' side's check is the next test."""
    sup, backend, _, _, logs = world
    asked: list[float] = []

    def slow(as_user: Any, home: Path, timeout: float) -> str:
        asked.append(timeout)
        raise subprocess.TimeoutExpired(["sh"], timeout)

    started(world)
    monkeypatch.setattr(codexd, "check_home", slow)
    restart(world)
    assert asked and all(t <= codexd.CHECK_TIMEOUT for t in asked)
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert not any(line.startswith("app-server daemon stop") for line in calls)
    assert len(backend.started) == 2
    said = [line for line in logs if "the codex-home cannot be checked (timeout)" in line]
    assert len(said) == 1 and said[0].endswith("the start goes on"), logs


def is_check(argv: Sequence[str], home: Path) -> bool:
    """Whether `argv` is the home check: one `sh -c` script, the home its one argument."""
    return list(argv[:2]) == ["sh", "-c"] and list(argv[3:]) == ["sh", str(home)]


def test_the_agents_side_home_check_is_a_bounded_sh(tmp_path: Path) -> None:
    """On the agents' side the check is one `sh` given the check's timeout, and a timeout
    there is raised on to `stop_codex_daemon`, which logs it."""

    def no_answer() -> tuple[int, str]:
        raise subprocess.TimeoutExpired(["sh"], codexd.CHECK_TIMEOUT)

    agents = AgentsSide(no_answer)
    with pytest.raises(subprocess.TimeoutExpired):
        codexd.check_home(cast(Any, agents), tmp_path / "h", codexd.CHECK_TIMEOUT)
    ((argv, timeout),) = agents.runs
    assert is_check(argv, tmp_path / "h") and timeout == codexd.CHECK_TIMEOUT


def test_a_check_whose_sudo_fails_is_not_an_absent_home(tmp_path: Path) -> None:
    """A sudo (or ssh) that fails exits non-zero with nothing on stdout: that is no answer,
    never an absent home, so nothing is said to be missing and nothing is stopped."""
    agents = AgentsSide(lambda: (1, ""))
    with pytest.raises(OSError, match="no answer"):
        codexd.check_home(cast(Any, agents), tmp_path / "h", codexd.CHECK_TIMEOUT)
    logs: list[str] = []
    codexd.stop_codex_daemon(cast(Any, agents), str(tmp_path / "codex"), tmp_path / "h",
                             tmp_path, "/usr/bin", logs.append)  # fmt: skip
    assert logs == ["the codex-home cannot be checked (OSError); no Codex app-server daemon "
                    "stopped, the start goes on"]  # fmt: skip
    assert all(is_check(argv, tmp_path / "h") for argv, _ in agents.runs)  # no stop ran


@pytest.mark.parametrize("kind", ["dir", "link", "other", "absent"])
def test_the_home_check_tells_a_link_from_a_directory(tmp_path: Path, kind: str) -> None:
    """The real script, as the runner's own user: a link to a directory is `link`, never
    followed to `dir`."""
    home, target = tmp_path / "codex-home", tmp_path / "elsewhere"
    target.mkdir()
    if kind == "dir":
        home.mkdir()
    elif kind == "link":
        home.symlink_to(target)
    elif kind == "other":
        home.write_text("")
    assert codexd.check_home(AsUser(), home, codexd.CHECK_TIMEOUT) == kind


def test_a_codex_home_that_is_a_link_is_not_stopped(world: Any, tmp_path: Path) -> None:
    """The agent may swap its codex-home for a link (to another placement's home, or the
    operator's `~/.codex`): the restart stops nothing through it and says so. The launch then
    refuses the link as before (scratch.write_codex_home), so this start fails and is retried
    after the backoff."""
    sup, backend, _, clock, logs = world
    started(world)
    home, other = codex_home(sup), tmp_path / "other-home"
    other.mkdir()
    shutil.rmtree(home)
    home.symlink_to(other)
    backend.exit(SESSION, 0)
    sup.tick()
    clock.now += 600
    settle(sup)
    calls = (tmp_path / "calls.log").read_text().splitlines()
    assert not any(line.startswith("app-server daemon stop") for line in calls)
    assert logs.count("plc-0003: the codex-home is a link (or not a directory); no Codex "
                      "app-server daemon stopped, the start goes on") == 1  # fmt: skip
    # What the launch does with the link today: it refuses to write through it, and the start
    # fails as a crash would, so no second session runs.
    assert len(backend.started) == 1
    assert any("start failed" in line for line in logs), logs


def test_the_daemon_stop_makes_no_directories(
    world: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stop names the agent's directory by its path alone: nothing is made or tightened
    outside its deadline (`agent_dir_for` and AsUser's mkdir stay out of it)."""
    sup, _, _, _, logs = world

    def made(*args: Any) -> Any:
        pytest.fail("the daemon stop made a directory")

    monkeypatch.setattr(supervisor, "agent_dir_for", made)
    monkeypatch.setattr(AsUser, "mkdir", made)
    monkeypatch.setattr(AsUser, "tighten", made)
    target = sup.targets["local"]
    p = placement(harness="codex")
    sup._stop_codex_daemon(p, sup.cfg.harnesses["codex"], target, tmp_path / "scratch", None)
    assert logs[-1:] == ["plc-0003: no codex-home yet, so no Codex app-server daemon to stop"]
    assert target.agent_files is not None
    assert not (target.agent_files / "agents" / "plc-0003").exists()


class AgentsSide:
    """An AsUser of the agents' side (not direct): `run` records each argv with its timeout,
    answers the home check through `check` (exit 0 and `dir` by default) and the stop with
    exit 0."""

    direct = False
    here = True

    def __init__(self, check: Callable[[], tuple[int, str]] = lambda: (0, "dir\n")) -> None:
        self.check = check
        self.runs: list[tuple[list[str], float]] = []

    def run(self, argv: Sequence[str], timeout: float = 60.0) -> subprocess.CompletedProcess[str]:
        self.runs.append((list(argv), timeout))
        code, out = self.check() if argv[0] == "sh" else (0, "")
        return subprocess.CompletedProcess(list(argv), code, out, "")


class FakeClock:
    def __init__(self) -> None:
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now


def stop_after_a_check_of(
    took: float, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AgentsSide, list[str]]:
    """`stop_codex_daemon` on the agents' side, its home check taking `took` seconds on a fake
    clock; the calls it made and its log."""
    clock = FakeClock()
    monkeypatch.setattr(codexd, "time", clock)

    def check() -> tuple[int, str]:
        clock.now += took
        return 0, "dir\n"

    agents = AgentsSide(check)
    logs: list[str] = []
    binary = tmp_path / "codex"  # under tmp_path: conftest's guard lets it through
    codexd.stop_codex_daemon(cast(Any, agents), str(binary), tmp_path / "h", tmp_path,
                             "/usr/bin", logs.append)  # fmt: skip
    return agents, logs


def test_the_stop_gets_what_is_left_of_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check and the stop share DEADLINE: a check that took 4.5 s leaves the stop 15.5 s."""
    took = codexd.CHECK_TIMEOUT - 0.5
    agents, logs = stop_after_a_check_of(took, tmp_path, monkeypatch)
    (check_argv, check_timeout), (stop_argv, stop_timeout) = agents.runs
    assert is_check(check_argv, tmp_path / "h") and check_timeout == codexd.CHECK_TIMEOUT
    assert stop_argv[-4:] == [str(tmp_path / "codex"), "app-server", "daemon", "stop"]
    assert stop_timeout == codexd.DEADLINE - took == 15.5
    assert logs == []


def test_no_stop_runs_once_the_check_used_the_whole_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A check that took longer than DEADLINE leaves nothing for the stop: none runs, and the
    log says the deadline was used up."""
    agents, logs = stop_after_a_check_of(codexd.DEADLINE + 30.0, tmp_path, monkeypatch)
    ((argv, _),) = agents.runs  # the check alone
    assert is_check(argv, tmp_path / "h")
    assert logs == ["the codex-home check used the whole deadline; no Codex app-server daemon "
                    "stopped, the start goes on"]  # fmt: skip


@dataclass(frozen=True)
class RecordingUser(AsUser):
    """The runner's own user (direct, `AsUser(None)`), each `run` recorded instead of run."""

    runs: list[tuple[list[str], float]] = field(default_factory=list)

    def run(
        self, argv: Sequence[str], env: dict[str, str] | None = None, input: str | None = None,
        cwd: Path | None = None, timeout: float = 60.0,
    ) -> subprocess.CompletedProcess[str]:  # fmt: skip
        self.runs.append((list(argv), timeout))
        return subprocess.CompletedProcess(list(argv), 0, "absent\n", "")


def test_the_direct_layout_home_check_is_bounded_too(tmp_path: Path) -> None:
    """In the `single` layout the check is the same bounded `sh` with CHECK_TIMEOUT, never a
    stat in the runner's own process, which a stuck mount could hold without a bound."""
    user = RecordingUser()
    assert user.direct
    assert codexd.check_home(user, tmp_path, codexd.CHECK_TIMEOUT) == "absent"
    ((argv, timeout),) = user.runs
    assert is_check(argv, tmp_path) and timeout == codexd.CHECK_TIMEOUT
