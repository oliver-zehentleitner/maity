"""A Codex start stops the app-server daemon an earlier start left in the placement's
codex-home (runner/codexd.py, card tsk-n6sajs3gyh8h): `codex app-server daemon stop` within
one deadline; a failed stop is logged, never refused."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import types
from collections.abc import Callable, Iterator, Sequence
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

from maity.runner import capabilities, codexd, config, supervisor, workspace
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


def workspaces(sup: supervisor.Supervisor) -> Path:
    assert sup.cfg.local is not None
    return sup.cfg.local.workspaces.resolve()


def codex_home(sup: supervisor.Supervisor) -> Path:
    return workspaces(sup) / ".scratch" / "maity" / "plc-0003" / "codex-home"


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

    def slow(as_user: Any, root: Path, parts: Sequence[str], timeout: float) -> str:
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


def is_check(argv: Sequence[str], root: Path, *parts: str) -> bool:
    """Whether `argv` is the home check: one `sh -c` script, the root and the home's
    components below it its arguments."""
    return list(argv[:2]) == ["sh", "-c"] and list(argv[3:]) == ["sh", str(root), *parts]


def stop(agents: Any, tmp_path: Path, home: Path | None = None) -> list[str]:
    """`stop_codex_daemon` for `home` (`<tmp_path>/h`) below the root `tmp_path`; its log."""
    logs: list[str] = []
    codexd.stop_codex_daemon(cast(Any, agents), str(tmp_path / "codex"),
                             home or tmp_path / "h", tmp_path, tmp_path, "/usr/bin",
                             logs.append)  # fmt: skip
    return logs


def test_the_agents_side_home_check_is_a_bounded_sh(tmp_path: Path) -> None:
    """On the agents' side the check is one `sh` given the check's timeout, and a timeout
    there is raised on to `stop_codex_daemon`, which logs it."""

    def no_answer() -> tuple[int, str]:
        raise subprocess.TimeoutExpired(["sh"], codexd.CHECK_TIMEOUT)

    agents = AgentsSide(no_answer)
    with pytest.raises(subprocess.TimeoutExpired):
        codexd.check_home(cast(Any, agents), tmp_path, ("h",), codexd.CHECK_TIMEOUT)
    ((argv, timeout),) = agents.runs
    assert is_check(argv, tmp_path, "h") and timeout == codexd.CHECK_TIMEOUT


def test_a_check_whose_sudo_fails_is_not_an_absent_home(tmp_path: Path) -> None:
    """A sudo (or ssh) that fails exits non-zero with nothing on stdout: that is no answer,
    never an absent home, so nothing is said to be missing and nothing is stopped."""
    agents = AgentsSide(lambda: (1, ""))
    with pytest.raises(OSError, match="no answer"):
        codexd.check_home(cast(Any, agents), tmp_path, ("h",), codexd.CHECK_TIMEOUT)
    assert stop(agents, tmp_path) == ["the codex-home cannot be checked (OSError); no Codex "
                                      "app-server daemon stopped, the start goes on"]  # fmt: skip
    assert all(is_check(argv, tmp_path, "h") for argv, _ in agents.runs)  # no stop ran


@pytest.mark.parametrize("home", ["/elsewhere/codex-home", "{root}", "{root}/a/../codex-home"])
def test_a_home_outside_its_root_is_not_probed_or_stopped(tmp_path: Path, home: str) -> None:
    """A home that is not plainly below its root (elsewhere, the root itself, or with `..` on
    the way) is not checked and not stopped."""
    agents = AgentsSide()
    logs = stop(agents, tmp_path, Path(home.format(root=tmp_path)))
    assert agents.runs == []
    assert logs == ["the codex-home is not below its root; no Codex app-server daemon stopped, "
                    "the start goes on"]  # fmt: skip


def test_a_relative_root_is_not_probed_or_stopped(tmp_path: Path) -> None:
    agents = AgentsSide()
    logs: list[str] = []
    codexd.stop_codex_daemon(cast(Any, agents), str(tmp_path / "codex"), Path("ws/h"),
                             Path("ws"), tmp_path, "/usr/bin", logs.append)  # fmt: skip
    assert agents.runs == []
    assert logs == ["the codex-home is not below its root; no Codex app-server daemon stopped, "
                    "the start goes on"]  # fmt: skip


@pytest.mark.parametrize(
    "kind",
    ["dir", "link", "parent-link", "other", "parent-other", "absent", "root-link",
     "root-other", "root-absent"],
)  # fmt: skip
def test_the_home_check_tells_a_link_from_a_directory(tmp_path: Path, kind: str) -> None:
    """The real script, as the runner's own user, over `<root>/a/b/codex-home`: a link at the
    root, at the home or at any directory between them is `link`, never followed to `dir`. A
    root that is a file is `other`; a missing one `absent`."""
    root, elsewhere = tmp_path / "root", tmp_path / "elsewhere"
    (elsewhere / "a" / "b" / "codex-home").mkdir(parents=True)
    if kind.startswith("root-"):
        if kind == "root-link":
            root.symlink_to(elsewhere)  # a real tree behind it: only the root's check tells
        elif kind == "root-other":
            root.write_text("")
        found = codexd.check_home(AsUser(), root, ("a", "b", "codex-home"), codexd.CHECK_TIMEOUT)
        assert found == kind.removeprefix("root-")
        return
    root.mkdir()
    a = root / "a"
    elsewhere = elsewhere / "a"
    if kind == "parent-link":
        a.symlink_to(elsewhere)  # a real directory through it: only the walk tells
    elif kind == "parent-other":
        a.write_text("")
    elif kind != "absent":
        (a / "b").mkdir(parents=True)
        home = a / "b" / "codex-home"
        if kind == "dir":
            home.mkdir()
        elif kind == "link":
            home.symlink_to(elsewhere / "b" / "codex-home")
        else:
            home.write_text("")
    expected = {"parent-link": "link", "parent-other": "other"}.get(kind, kind)
    found = codexd.check_home(AsUser(), root, ("a", "b", "codex-home"), codexd.CHECK_TIMEOUT)
    assert found == expected


def test_a_codex_home_that_is_a_link_is_not_stopped(world: Any, tmp_path: Path) -> None:
    """A codex-home that is a link: the restart stops nothing through it and says so. The
    launch then refuses the link as before (scratch.write_codex_home), so this start fails and
    is retried after the backoff."""
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


@pytest.mark.parametrize("layout", ["scratch", "no scratch"])
def test_a_link_above_the_codex_home_is_not_stopped(
    world: Any, tmp_path: Path, layout: str
) -> None:
    """A link on the way from the runner's root to the codex-home (the project's directory in
    the scratch holder, or the placement's directory under the agents' files) stops nothing,
    though a real directory lies behind it. Called on the supervisor's own stop: a start does
    not get this far with a scratch, since making the scratch refuses a link on the way first
    (no scratch then, and the home moves to the agents' files)."""
    sup, _, _, _, logs = world
    target = sup.targets["local"]
    assert target.agent_files is not None
    behind = tmp_path / "behind"
    if layout == "scratch":
        (behind / "plc-0003" / "codex-home").mkdir(parents=True)
        holder = workspaces(sup) / ".scratch"
        holder.mkdir(parents=True, exist_ok=True)
        (holder / "maity").symlink_to(behind)
        scratch: Path | None = holder / "maity" / "plc-0003"
    else:
        (behind / "codex-home").mkdir(parents=True)
        agents = target.agent_files / "agents"
        agents.mkdir(parents=True, exist_ok=True)
        (agents / "plc-0003").symlink_to(behind)
        scratch = None
    sup._stop_codex_daemon(placement(harness="codex"), sup.cfg.harnesses["codex"], target,
                           scratch, None)  # fmt: skip
    assert logs[-1:] == ["plc-0003: the codex-home is a link (or not a directory); no Codex "
                         "app-server daemon stopped, the start goes on"]  # fmt: skip
    calls = tmp_path / "calls.log"
    assert not calls.exists() or "app-server daemon stop" not in calls.read_text()


@pytest.mark.parametrize("layout", ["scratch", "no scratch"])
def test_a_root_that_is_a_link_is_not_stopped(world: Any, tmp_path: Path, layout: str) -> None:
    """The root itself a link, with a real codex-home behind it: the workspaces root for a
    home in the scratch, the agents' files without one. Nothing is stopped."""
    sup, _, _, _, logs = world
    target = sup.targets["local"]
    behind, link = tmp_path / "behind", tmp_path / "root-link"
    if layout == "scratch":
        (behind / ".scratch" / "maity" / "plc-0003" / "codex-home").mkdir(parents=True)
        link.symlink_to(behind)
        scratch: Path | None = link / ".scratch" / "maity" / "plc-0003"
    else:
        (behind / "agents" / "plc-0003" / "codex-home").mkdir(parents=True)
        link.symlink_to(behind)
        target.agent_files = link
        scratch = None
    sup._stop_codex_daemon(placement(harness="codex"), sup.cfg.harnesses["codex"], target,
                           scratch, None)  # fmt: skip
    assert logs[-1:] == ["plc-0003: the codex-home is a link (or not a directory); no Codex "
                         "app-server daemon stopped, the start goes on"]  # fmt: skip
    calls = tmp_path / "calls.log"
    assert not calls.exists() or "app-server daemon stop" not in calls.read_text()


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
    scratch = workspaces(sup) / ".scratch" / "maity" / "plc-0003"
    sup._stop_codex_daemon(p, sup.cfg.harnesses["codex"], target, scratch, None)
    assert logs[-1:] == ["plc-0003: no codex-home yet, so no Codex app-server daemon to stop"]
    assert target.agent_files is not None
    assert not (target.agent_files / "agents" / "plc-0003").exists()


def test_the_agents_home_is_not_looked_up_before_the_deadline(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stop takes the agents' home the target found when it was set up: no account lookup
    (config.home_of) and no `_agents_home` at the start. A target that has none yet stops
    nothing and says so."""
    sup, _, _, _, logs = world

    def looked_up(*args: Any) -> Any:
        pytest.fail("the daemon stop looked the agents' home up")

    monkeypatch.setattr(config, "home_of", looked_up)
    monkeypatch.setattr(supervisor.Supervisor, "_agents_home", looked_up)
    target = sup.targets["local"]
    assert target.agents_home == Path.home()  # the single layout's, found by targets.local
    p, codex = placement(harness="codex"), sup.cfg.harnesses["codex"]
    scratch = workspaces(sup) / ".scratch" / "maity" / "plc-0003"
    sup._stop_codex_daemon(p, codex, target, scratch, None)
    assert logs[-1:] == ["plc-0003: no codex-home yet, so no Codex app-server daemon to stop"]
    target.agents_home = None
    sup._stop_codex_daemon(p, codex, target, scratch, None)
    assert logs[-1:] == ["plc-0003: the agents' home is not known; no Codex app-server daemon "
                         "stopped, the start goes on"]  # fmt: skip


def recorded_homes(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """The HOME each daemon stop is given, recorded around conftest's guarded `stop_argv`."""
    homes: list[Path] = []
    guarded = codexd.stop_argv

    def recording(binary: str, home: Path, agents_home: Path, agent_path: str) -> list[str]:
        homes.append(agents_home)
        return guarded(binary, home, agents_home, agent_path)

    monkeypatch.setattr(codexd, "stop_argv", recording)
    return homes


def test_a_changed_local_account_is_what_the_next_stop_uses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local agents' home is read when the service builds its target and stays for the
    life of the runner process: a changed account takes effect at the next start, whose new
    target (targets.local) carries the new home, and its stop gives that home without looking
    it up."""
    for name in ("first", "second"):
        (tmp_path / name).mkdir()
    cfg = load(tmp_path)
    probes = {"codex": capabilities.Probe(str(tmp_path / "codex"), "0.40.0", None)}
    fake_codex(tmp_path / "codex", tmp_path / "calls.log")
    monkeypatch.setenv("HOME", str(tmp_path / "first"))
    before = supervisor.Supervisor(cfg, FakeTmux(), None, [].append, probes)  # type: ignore[arg-type]
    assert before.targets["local"].agents_home == tmp_path / "first"
    monkeypatch.setenv("HOME", str(tmp_path / "second"))  # the account changed; a restart
    after = supervisor.Supervisor(cfg, FakeTmux(), None, [].append, probes)  # type: ignore[arg-type]
    target = after.targets["local"]
    assert target.agents_home == tmp_path / "second"

    def looked_up(*args: Any) -> Any:
        pytest.fail("the daemon stop looked the agents' home up")

    monkeypatch.setattr(config, "home_of", looked_up)
    monkeypatch.setattr(supervisor.Supervisor, "_agents_home", looked_up)
    homes = recorded_homes(monkeypatch)
    scratch = workspaces(after) / ".scratch" / "maity" / "plc-0003"
    (scratch / "codex-home").mkdir(parents=True)
    after._stop_codex_daemon(placement(harness="codex"), cfg.harnesses["codex"], target,
                             scratch, None)  # fmt: skip
    assert homes == [tmp_path / "second"]


class AgentsSide:
    """An AsUser of the agents' side (not direct): `run` records each argv with its timeout,
    answers the home check through `check` (exit 0 and `dir` by default), the updater step
    with `updater` (`absent` by default) and the stop with exit 0."""

    direct = False
    here = True

    def __init__(
        self, check: Callable[[], tuple[int, str]] = lambda: (0, "dir\n"),
        updater: str = "absent\n",
    ) -> None:  # fmt: skip
        self.check = check
        self.updater = updater
        self.runs: list[tuple[list[str], float]] = []
        self.envs: list[dict[str, str] | None] = []

    def runner_module(self, name: str) -> list[str]:
        return ["agents-python", "-I", "-m", f"maity.runner.{name}"]

    def module_env(self) -> dict[str, str]:
        return {"PATH": "/agents/bin"}  # the host's PATH for its `maity`

    def run(
        self, argv: Sequence[str], env: dict[str, str] | None = None, timeout: float = 60.0
    ) -> subprocess.CompletedProcess[str]:
        self.runs.append((list(argv), timeout))
        self.envs.append(env)
        if argv[0] == "sh":
            code, out = self.check()
        elif argv[0] == "agents-python":
            code, out = 0, self.updater
        else:
            code, out = 0, ""
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
    return agents, stop(agents, tmp_path)  # the fake under tmp_path: the guard lets it through


def test_the_stop_gets_what_is_left_of_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The check, the updater step and the stop share DEADLINE: a check that took 4.5 s leaves
    the stop 15.5 s, the updater step (instant here) taking none of it."""
    took = codexd.CHECK_TIMEOUT - 0.5
    agents, logs = stop_after_a_check_of(took, tmp_path, monkeypatch)
    (check_argv, check_timeout), (updater_argv, _), (stop_argv, stop_timeout) = agents.runs
    assert is_check(check_argv, tmp_path, "h") and check_timeout == codexd.CHECK_TIMEOUT
    assert updater_argv[-4:] == ["end-updater", str(tmp_path), str(tmp_path / "h"), "3"]
    assert agents.envs[1] == {"PATH": "/agents/bin"}  # the host's maity finds its python
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
    assert is_check(argv, tmp_path, "h")
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
    stat in the runner's own process."""
    user = RecordingUser()
    assert user.direct
    assert codexd.check_home(user, tmp_path, ("h",), codexd.CHECK_TIMEOUT) == "absent"
    ((argv, timeout),) = user.runs
    assert is_check(argv, tmp_path, "h") and timeout == codexd.CHECK_TIMEOUT


# --- slice 2: the updater loop ------------------------------------------------------------------

LOOP = (
    "import os, signal, sys, time\n"
    "def bye(*_):\n"
    "    time.sleep(float(os.environ.get('LOOP_DELAY', '0')))\n"
    "    with open(os.environ['LOOP_CALLS'], 'a') as out:\n"
    "        out.write('loop ended\\n')\n"
    "    sys.exit(0)\n"
    "signal.signal(signal.SIGTERM, bye)\n"
    "open(os.environ['LOOP_READY'], 'w').close()\n"
    "time.sleep(120)\n"
)
linux = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="pidfd and /proc")


@pytest.fixture
def spawn(tmp_path: Path) -> Iterator[Callable[..., subprocess.Popen[bytes]]]:
    """Start a stand-in for Codex's loop: its argv ends in the loop's words, CODEX_HOME is
    `home`, and on TERM it writes `loop ended` to `calls`. Every one is ended at the end."""
    started_: list[subprocess.Popen[bytes]] = []

    def start(
        home: Path, calls: Path, tail: Sequence[str] = codexd.UPDATER_ARGV,
        env_home: Path | None = None, delay: float = 0.0,
    ) -> subprocess.Popen[bytes]:  # fmt: skip
        ready = calls.with_name(f"ready-{len(started_)}")
        env = {**os.environ, "CODEX_HOME": str(env_home or home), "LOOP_CALLS": str(calls),
               "LOOP_READY": str(ready), "LOOP_DELAY": str(delay)}  # fmt: skip
        proc = subprocess.Popen([sys.executable, "-c", LOOP, *tail], env=env)
        started_.append(proc)
        for _ in range(500):  # its TERM handler is in place once it says so
            if ready.exists() or proc.poll() is not None:
                break
            time.sleep(0.01)
        assert ready.exists(), "the stand-in loop did not start"
        return proc

    yield start
    for proc in started_:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=10)


def record(home: Path, pid: int, ticks: int | None = None, boot: str | None = None) -> Path:
    """Codex's record of the loop in `home`, as 3yc2 measured it on 0.171."""
    if ticks is None:
        text = Path(f"/proc/{pid}/stat").read_text()
        ticks = int(text[text.rindex(")") + 2 :].split()[19])
    if boot is None:
        boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    folder = home / codexd.UPDATER_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / codexd.UPDATER_PID
    identity = {"bootId": boot, "startTicks": ticks}
    data = {"pid": pid, "processStartTime": "2026-11-24T00:00:00Z", "processIdentity": identity}
    path.write_text(json.dumps(data))
    return path


def wait_ended(proc: subprocess.Popen[bytes]) -> None:
    assert proc.wait(timeout=10) == 0


@linux
def test_the_recorded_loop_is_ended(tmp_path: Path, spawn: Any) -> None:
    home, calls = tmp_path / "h", tmp_path / "calls.log"
    loop = spawn(home, calls)
    record(home, loop.pid)
    assert codexd.end_updater(tmp_path, home) == "stopped"
    wait_ended(loop)
    assert calls.read_text() == "loop ended\n"


@linux
@pytest.mark.parametrize(
    "case",
    ["other argv", "other home", "other start", "other boot"],
)
def test_a_process_that_is_not_the_recorded_loop_is_never_signalled(
    tmp_path: Path, spawn: Any, case: str
) -> None:
    """A stale or reused pid: the process behind it is checked first, and any difference
    leaves it alone."""
    home, calls = tmp_path / "h", tmp_path / "calls.log"
    if case == "other argv":
        other = spawn(home, calls, tail=("sleep",))
        record(home, other.pid)
    elif case == "other home":
        other = spawn(home, calls, env_home=tmp_path / "elsewhere")
        record(home, other.pid)
    elif case == "other start":
        other = spawn(home, calls)
        text = Path(f"/proc/{other.pid}/stat").read_text()
        record(home, other.pid, ticks=int(text[text.rindex(")") + 2 :].split()[19]) + 1)
    else:
        other = spawn(home, calls)
        record(home, other.pid, boot="00000000-0000-0000-0000-000000000000")
    assert codexd.end_updater(tmp_path, home) == "mismatch"
    assert other.poll() is None  # still running
    assert not calls.exists()


@linux
def test_a_recorded_pid_that_is_gone_is_said_so(tmp_path: Path, spawn: Any) -> None:
    home = tmp_path / "h"
    loop = spawn(home, tmp_path / "calls.log")
    record(home, loop.pid)
    loop.kill()
    loop.wait(timeout=10)
    assert codexd.end_updater(tmp_path, home) == "gone"


@linux
@pytest.mark.parametrize("case", ["no home", "no folder", "no record", "garbage", "pid 1",
                                  "folder is a link", "record is a link"])  # fmt: skip
def test_no_usable_record_signals_nothing(tmp_path: Path, case: str) -> None:
    home = tmp_path / "h"
    expected = "absent"
    if case != "no home":
        home.mkdir()
    folder = home / codexd.UPDATER_DIR
    if case in ("no record", "garbage", "pid 1", "record is a link"):
        folder.mkdir()
    if case == "garbage":
        (folder / codexd.UPDATER_PID).write_text("not json")
        expected = "unreadable"
    elif case == "pid 1":
        record(home, os.getpid())
        data = json.loads((folder / codexd.UPDATER_PID).read_text())
        (folder / codexd.UPDATER_PID).write_text(json.dumps({**data, "pid": 1}))
        expected = "unreadable"
    elif case == "folder is a link":
        real = tmp_path / "real"
        real.mkdir()
        record(real.parent / "realhome", os.getpid())
        folder.symlink_to(real.parent / "realhome" / codexd.UPDATER_DIR)
        expected = "unreadable"
    elif case == "record is a link":
        elsewhere = record(tmp_path / "other", os.getpid())
        (folder / codexd.UPDATER_PID).symlink_to(elsewhere)
        expected = "unreadable"
    assert codexd.end_updater(tmp_path, home) == expected


def test_the_updater_step_comes_before_the_daemon_stop_and_says_why_it_failed(
    tmp_path: Path,
) -> None:
    """On the agents' side: the check, then the updater step, then the stop, so the loop
    cannot start a replacement app-server after the stop. A step that did not end the loop is
    logged, and the stop goes on."""
    agents = AgentsSide(updater="mismatch\n")
    logs = stop(agents, tmp_path)
    kinds = [argv[0] for argv, _ in agents.runs]
    assert kinds == ["sh", "agents-python", "env"]
    assert logs == ["the Codex updater loop was not ended (mismatch); the daemon stop goes on"]
    answer = AgentsSide(updater="something else\n")
    assert stop(answer, tmp_path) == [
        "the Codex updater loop was not ended (unreadable); the daemon stop goes on"
    ]


@linux
def test_a_restart_ends_the_loop_before_the_daemon_stop(
    world: Any, tmp_path: Path, spawn: Any
) -> None:
    """The loop the first start left is ended at the restart, before the daemon stop: so
    after the stop no loop is left to launch a replacement app-server."""
    sup, backend, _, _, logs = world
    calls = tmp_path / "calls.log"
    started(world)
    home = codex_home(sup)
    loop = spawn(home, calls)
    record(home, loop.pid)
    restart(world)
    wait_ended(loop)
    assert calls.read_text().splitlines() == [
        f"launch|{home}", "loop ended", f"app-server daemon stop|{home}", f"launch|{home}",
    ]  # fmt: skip
    assert not any("updater loop" in line for line in logs), logs


@linux
def test_a_closed_codex_placement_ends_its_loop_and_daemon_before_its_scratch_goes(
    world: Any, tmp_path: Path, spawn: Any
) -> None:
    """At close the CODEX_HOME goes with the scratch; its loop and daemon, detached from the
    session, are ended first, the loop before the daemon, or they would run on without it."""
    sup, backend, _, _, logs = world
    calls = tmp_path / "calls.log"
    started(world)
    home = codex_home(sup)
    loop = spawn(home, calls, delay=0.5)  # slow over its TERM: waited for before the removal
    record(home, loop.pid)
    backend.kill(SESSION)
    sup.update([])
    sup.closed([{"id": "plc-0003", "project_id": "maity", "active": False,
                 "closed_reason": "deleted", "harness": "codex"}])  # fmt: skip
    sup.tick()
    wait_ended(loop)
    assert not home.exists()  # the scratch went after the stop
    assert calls.read_text().splitlines() == [
        f"launch|{home}", "loop ended", f"app-server daemon stop|{home}",
    ]  # fmt: skip
    assert any("plc-0003: scratch removed on local" in line for line in logs), logs


# --- slice 2, round 1 (A2599) -------------------------------------------------------------------

CLOSED_CODEX = {"id": "plc-0003", "project_id": "maity", "active": False,
                "closed_reason": "deleted", "harness": "codex"}  # fmt: skip


@linux
def test_a_loop_slow_to_exit_is_waited_for_before_the_daemon_stop(
    world: Any, tmp_path: Path, spawn: Any
) -> None:
    """A loop that takes its time over the TERM (here 0.5 s) has exited before the daemon
    stop runs, so it cannot start a replacement between the two."""
    sup, *_ = world
    calls = tmp_path / "calls.log"
    started(world)
    home = codex_home(sup)
    record(home, spawn(home, calls, delay=0.5).pid)
    restart(world)
    lines = calls.read_text().splitlines()
    assert lines.index("loop ended") < lines.index(f"app-server daemon stop|{home}"), lines


@linux
def test_a_loop_that_does_not_exit_in_time_is_said_so_and_never_killed(
    tmp_path: Path, spawn: Any
) -> None:
    home, calls = tmp_path / "h", tmp_path / "calls.log"
    loop = spawn(home, calls, delay=5.0)
    record(home, loop.pid)
    assert codexd.end_updater(tmp_path, home, wait=0.2) == "running"
    assert loop.poll() is None  # TERMed, still in its handler: no KILL followed


@linux
def test_a_process_of_another_user_is_never_signalled(
    tmp_path: Path, spawn: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The process's uids must all be the agents' user's: here the hook runs as another."""
    home, calls = tmp_path / "h", tmp_path / "calls.log"
    loop = spawn(home, calls)
    record(home, loop.pid)
    me = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: me + 1)
    assert codexd.end_updater(tmp_path, home) == "mismatch"
    assert loop.poll() is None and not calls.exists()


@linux
def test_without_pidfds_nothing_is_signalled(
    tmp_path: Path, spawn: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, calls = tmp_path / "h", tmp_path / "calls.log"
    loop = spawn(home, calls)
    record(home, loop.pid)
    # codexd's own `os` without pidfd_open, never the os module itself: Python 3.15's
    # subprocess uses os.pidfd_open, so removing it there breaks the test's own processes.
    without = types.SimpleNamespace(**{k: getattr(os, k) for k in dir(os) if k != "pidfd_open"})
    monkeypatch.setattr("maity.runner.codexd.os", without)
    assert codexd.end_updater(tmp_path, home) == "unsupported"
    assert loop.poll() is None and not calls.exists()


@linux
def test_an_exited_loop_not_reaped_yet_is_gone_not_a_mismatch(tmp_path: Path, spawn: Any) -> None:
    """A zombie has no cmdline; it is gone, and nothing is logged for it."""
    home = tmp_path / "h"
    loop = spawn(home, tmp_path / "calls.log")
    record(home, loop.pid)
    os.kill(loop.pid, 9)
    stat_file = Path(f"/proc/{loop.pid}/stat")
    for _ in range(500):  # not waited for: it stays a zombie of this test
        text = stat_file.read_text()
        if text[text.rindex(")") + 2] == "Z":
            break
        time.sleep(0.01)
    assert codexd.end_updater(tmp_path, home) == "gone"


@linux
def test_the_agents_side_command_prints_one_token_and_refuses_other_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "h"
    assert codexd.main(["end-updater", str(tmp_path), str(home)]) == 0
    assert capsys.readouterr().out == "absent\n"
    for bad in (["end-updater", str(home)], ["end-updater", "rel", str(home)],
                ["end-updater", str(tmp_path), "rel"], ["stop", str(tmp_path), str(home)],
                ["end-updater", str(tmp_path), str(home), "x"],
                ["end-updater", str(tmp_path), str(home), "99"]):  # fmt: skip
        assert codexd.main(bad) == 2, bad


@pytest.mark.parametrize(("timeout", "wait"), [(5.0, "3"), (2.5, "1.5"), (1.0, "0"), (0.4, "0")])
def test_the_wait_is_clamped_to_what_the_deadline_leaves(
    tmp_path: Path, timeout: float, wait: str
) -> None:
    """The wait for the loop's exit is at most UPDATER_WAIT, and leaves a second of the step's
    timeout for the command around it; never below zero."""
    agents = AgentsSide()
    assert codexd._end_updater(cast(Any, agents), tmp_path, tmp_path / "h", timeout) == "absent"
    ((argv, given),) = agents.runs
    assert argv[-1] == wait and given == timeout


def test_a_home_not_below_the_root_is_unreadable(tmp_path: Path) -> None:
    assert codexd.end_updater(tmp_path / "root", tmp_path / "elsewhere" / "h") == "unreadable"


@linux
def test_a_link_on_the_way_from_the_root_is_never_followed(tmp_path: Path, spawn: Any) -> None:
    """The record is reached from the root one directory at a time, no link at any step."""
    real = tmp_path / "real"
    loop = spawn(real / "h", tmp_path / "calls.log")
    record(real / "h", loop.pid)
    (tmp_path / "root").mkdir()
    (tmp_path / "root" / "via").symlink_to(real)
    assert codexd.end_updater(tmp_path / "root", tmp_path / "root" / "via" / "h") == "unreadable"
    assert loop.poll() is None


@linux
def test_a_close_stops_before_the_tmpdir_goes_and_in_the_former_layout_too(
    world: Any, tmp_path: Path, spawn: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At close: the stop runs for the scratch of either layout (here the former one, beside
    the clone), and before the placement's own TMPDIR leaf is removed, as at a start."""
    sup, backend, *_ = world
    calls = tmp_path / "calls.log"
    started(world)
    target = next(iter(sup.targets.values()))
    old = workspace.scratch_of(target.workspaces, "maity", "plc-0003", target.host, former=True)
    home = old / "codex-home"
    loop = spawn(home, calls)
    record(home, loop.pid)
    monkeypatch.setattr(sup, "_host_layout", lambda target: "former")

    def tmpdir_removed(p: Any, target: Any) -> bool:
        with calls.open("a") as out:
            out.write("tmpdir removed\n")
        return True

    monkeypatch.setattr(sup, "_remove_tmpdir", tmpdir_removed)
    backend.kill(SESSION)
    sup.update([])
    sup.closed([CLOSED_CODEX])
    sup.tick()
    wait_ended(loop)
    lines = calls.read_text().splitlines()
    assert lines[1:] == ["loop ended", f"app-server daemon stop|{home}", "tmpdir removed"]
    assert not home.exists()


def test_a_close_where_the_hosts_layout_is_unknown_stops_nothing(
    world: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Where the host does not answer, nothing is asked of it this pass: no stop either, so a
    dead host costs no deadline every tick."""
    sup, backend, *_ = world
    started(world)
    monkeypatch.setattr(sup, "_host_layout", lambda target: "unknown")
    touched: list[str] = []

    def recorded_as(what: str) -> Callable[[Any, Any], bool]:
        def removal(p: Any, target: Any) -> bool:
            touched.append(what)
            return True

        return removal

    monkeypatch.setattr(sup, "_remove_tmpdir", recorded_as("tmpdir"))
    monkeypatch.setattr(sup, "_remove_stale", recorded_as("stale"))
    backend.kill(SESSION)
    sup.update([])
    sup.closed([CLOSED_CODEX])
    sup.tick()
    assert (tmp_path / "calls.log").read_text().splitlines() == [f"launch|{codex_home(sup)}"]
    assert touched == []  # nothing of the target this pass: a live loop keeps its TMPDIR
    assert "plc-0003" not in sup.scratch_cleared
    assert codex_home(sup).is_dir()
