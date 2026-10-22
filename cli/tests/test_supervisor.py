from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from maity import hub
from maity.runner import capabilities, config, restart, supervisor, tmux, workspace

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11), reason="maity runner needs 3.11")

REPO = "https://github.com/oliver-zehentleitner/maity"
CONFIG = """\
[hub]
url = "https://hub.example"
state_dir = "{root}/st"

[limits]
projects = ["maity"]
repositories = ["github.com/oliver-zehentleitner/*"]
max_agents = {max_agents}

[backend.local]
workspaces = "{root}/ws"

[harness.stub]
modes = ["supervised", "interactive"]
exit_code = 1
run_seconds = 5

[harness.codex]
"""


def load(root: Path, max_agents: int = 2) -> config.Config:
    path = root / "runner.toml"
    path.write_text(CONFIG.format(root=root, max_agents=max_agents))
    (root / "st").mkdir(mode=0o700, exist_ok=True)
    return config.load(path)


def placement(n: int = 3, **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": f"plc-000{n}", "project": "maity", "generation": 1, "desired": "running",
        "agent": {"id": f"agt-{n}", "handle": f"agent-{n}", "member": True,
                  "credential_expected": True},
        "harness": "stub", "mode": "supervised", "model": None, "target": None,
        "workspace": {"clone": f"agent-{n}", "branch": None, "repository": REPO},
        "rejoin": False, "stop_grace_seconds": 120, "seq": 0,
    }  # fmt: skip
    data.update(overrides)
    return data


@dataclass
class FakeTmux:
    socket: Path = Path("/run/maity/tmux.sock")
    live: dict[str, tmux.Session] = field(default_factory=dict)
    started: list[tuple[str, list[str], dict[str, str]]] = field(default_factory=list)
    terminated: list[str] = field(default_factory=list)
    killed: list[str] = field(default_factory=list)

    def sessions(self) -> dict[str, tmux.Session]:
        return dict(self.live)

    def start(self, name: str, cwd: Path, argv: Sequence[str], env: dict[str, str],
              placement: str, generation: int) -> None:  # fmt: skip
        self.started.append((name, list(argv), env))
        self.live[name] = tmux.Session(name, False, None, 4242, placement, generation)

    def terminate(self, session: tmux.Session) -> None:
        self.terminated.append(session.name)

    def kill(self, name: str) -> None:
        self.killed.append(name)
        self.live.pop(name, None)

    def exit(self, name: str, status: int) -> None:
        self.live[name] = replace(self.live[name], dead=True, exit_status=status)


class Reports:
    def __init__(self) -> None:
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.fail: list[Any] = []

    def call(self, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
        if self.fail:
            raise self.fail.pop(0)
        self.sent.append((path.split("/")[3], body))
        return {}


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def recorded(cfg: config.Config, n: int = 3, credential: bool = True) -> workspace.Workspace:
    """A clone the runner recorded, with `origin` set and (by default) a credential."""
    assert cfg.local is not None
    place = workspace.locate(cfg.local.workspaces, "maity", f"agent-{n}")
    (place.path / ".git").mkdir(parents=True)
    (place.path / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {REPO}.git\n')
    if credential:
        (place.path / ".git" / "maity").mkdir()
        (place.path / ".git" / "maity" / "credential").write_text("mty1.crd-x.y")
    workspace._record(cfg.state_dir, place, f"agt-{n}", f"plc-000{n}")
    return place


@pytest.fixture
def world(tmp_path: Path) -> Any:
    cfg = load(tmp_path)
    clock, reports, backend = Clock(), Reports(), FakeTmux()
    logs: list[str] = []
    probes = {
        "stub": capabilities.Probe(None, None, None),
        "codex": capabilities.Probe("/usr/bin/codex", "0.40.0", None),
    }
    sup = supervisor.Supervisor(
        cfg, backend, reports, logs.append, probes, now=clock, rand=lambda: 0.5  # type: ignore[arg-type]
    )
    return sup, backend, reports, clock, logs


def settle(sup: supervisor.Supervisor) -> None:
    """Tick, then wait for start tasks, then tick again so their result is reported."""
    sup.tick()
    for task in list(sup.tasks.values()):
        task.join(5)
    sup.tick()


def states(reports: Reports) -> list[tuple[Any, ...]]:
    return [(b["state"], b["reason"], b["detail"]) for _, b in reports.sent]


# --- start, run, restart, crash loop ---------------------------------------------------------


def test_a_stub_placement_starts_and_runs(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    ((name, argv, env),) = backend.started
    assert name == "maity-maity-agent-3" and env == {"MAITY_PLACEMENT": "plc-0003"}
    assert argv[1:3] == ["-m", "maity.runner.stub"] and argv[-3:] == ["1", "--run-seconds", "5"]
    clock.now += supervisor.RUNNING_AFTER
    sup.tick()
    assert states(reports) == [("starting", None, None), ("running", None, None)]
    first, second = (b for _, b in reports.sent)
    assert (first["seq"], second["seq"]) == (1, 2)
    assert second["session_hint"] == "tmux -S /run/maity/tmux.sock attach -t maity-maity-agent-3"
    assert second["target"] == "local" and second["observed_generation"] == 1


def test_reports_only_on_change_and_seq_continues_from_the_hub(world: Any) -> None:
    sup, _, reports, _, _ = world
    recorded(sup.cfg)
    sup.update([placement(seq=41)])
    settle(sup)
    sup.tick()
    sup.tick()
    assert [b["seq"] for _, b in reports.sent] == [42]


def test_quick_exits_back_off_then_end_in_a_crash_loop(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    gaps = []
    for _ in range(sup.cfg.limits.restart.crash_cap):
        settle(sup)
        clock.now += 1
        backend.exit("maity-maity-agent-3", 1)
        sup.tick()
        rec = sup.records["plc-0003"]
        if rec.state == "exited":
            gaps.append(round(rec.retry_at - clock.now))
            clock.now = rec.retry_at
    assert gaps == [10, 20, 40, 80]  # initial 10 × 2^n, rand 0.5 = no jitter
    last = reports.sent[-1][1]
    assert (last["state"], last["reason"], last["crash_count"]) == ("failed", "crash_loop", 5)
    assert last["crash_window_seconds"] == 1800 and last["restarts"] == 4
    exited = [b for _, b in reports.sent if b["state"] == "exited"]
    assert exited[0]["exit_code"] == 1 and exited[0]["retry_at"] is not None
    started = len(backend.started)
    clock.now += 10_000
    settle(sup)
    assert len(backend.started) == started  # nothing until the generation moves
    sup.update([placement(generation=2)])
    settle(sup)
    assert len(backend.started) == started + 1
    assert reports.sent[-1][1]["restarts"] == 0


def test_restart_policy_resets_after_a_long_run() -> None:
    policy = config.Restart()
    decision = restart.on_exit(policy, [1.0, 2.0], started_at=0.0, exited_at=100.0,
                               rand=lambda: 0.5)  # fmt: skip
    assert decision.crashes == [] and decision.retry_at == 110.0
    capped = restart.delay(policy, 10, rand=lambda: 1.0)
    assert capped == policy.max * 1.2


# --- stop ------------------------------------------------------------------------------------


def test_stop_waits_the_grace_then_terminates_then_kills(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    sup.update([placement(desired="stopped", stop_grace_seconds=60)])
    sup.tick()
    stopping = reports.sent[-1][1]
    assert stopping["state"] == "stopping" and stopping["deadline_at"] is not None
    clock.now += 59
    sup.tick()
    assert backend.terminated == []
    clock.now += 1
    sup.tick()
    assert backend.terminated == ["maity-maity-agent-3"]
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    sup.tick()
    assert "maity-maity-agent-3" in backend.killed
    assert states(reports)[-1] == ("stopped", "stopped_by_hub", None)


def test_a_process_ending_within_the_grace_is_stopped_at_once(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    sup.update([placement(desired="stopped")])
    sup.tick()
    backend.exit("maity-maity-agent-3", 0)
    sup.tick()
    assert backend.terminated == []
    assert states(reports)[-1] == ("stopped", "stopped_by_hub", None)


def test_stop_grace_is_capped_by_the_configuration(world: Any) -> None:
    sup, _, reports, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    sup.update([placement(desired="stopped", stop_grace_seconds=900)])
    sup.tick()
    assert sup.records["plc-0003"].deadline_at == clock.now + sup.cfg.limits.stop_grace_max


def test_a_stopped_placement_without_a_session_is_reported_once(world: Any) -> None:
    sup, backend, reports, _, _ = world
    sup.update([placement(desired="stopped")])
    sup.tick()
    sup.tick()
    assert states(reports) == [("stopped", "stopped_by_hub", None)]
    assert backend.started == []


def test_a_new_generation_restarts_a_running_session(world: Any) -> None:
    sup, backend, _, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    sup.update([placement(generation=2, stop_grace_seconds=0)])
    sup.tick()
    sup.tick()
    assert backend.terminated == ["maity-maity-agent-3"]
    backend.exit("maity-maity-agent-3", 143)
    settle(sup)
    assert backend.started[-1][0] == "maity-maity-agent-3"
    assert backend.live["maity-maity-agent-3"].generation == 2


# --- refusals --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"project": "other"}, ("project_refused", None)),
        ({"workspace": {"clone": "a", "repository": "https://github.com/x/y"}},
         ("repository_refused", None)),
        ({"harness": "claude-code"}, ("harness_refused", None)),
        ({"mode": "interactive", "harness": "codex"}, ("harness_refused", "mode_unsupported")),
        ({"model": "opus"}, ("harness_refused", "model_unsupported")),
    ],
)  # fmt: skip
def test_placements_outside_the_configuration_fail(
    world: Any, change: dict[str, Any], expected: tuple[str, str | None]
) -> None:
    sup, backend, reports, _, _ = world
    sup.update([placement(**change)])
    sup.tick()
    assert states(reports) == [("failed", *expected)]
    assert backend.started == []


def test_a_missing_harness_binary(world: Any) -> None:
    sup, _, reports, _, _ = world
    sup.probes["codex"] = capabilities.Probe(None, None, "binary_not_found")
    sup.update([placement(harness="codex")])
    sup.tick()
    assert states(reports) == [("failed", "harness_missing", "binary_not_found")]


def test_an_unrecorded_directory_is_not_used(world: Any) -> None:
    sup, backend, reports, _, _ = world
    place = workspace.locate(sup.cfg.local.workspaces, "maity", "agent-3")
    (place.path / ".git" / "maity").mkdir(parents=True)
    (place.path / ".git" / "maity" / "credential").write_text("mty1.crd-x.y")
    sup.update([placement()])
    settle(sup)
    assert states(reports)[-1] == ("failed", "workspace_in_use", "workspace_unrecorded")
    assert backend.live == {}


def test_a_credential_that_should_be_there_and_is_not(world: Any) -> None:
    sup, _, reports, _, _ = world
    recorded(sup.cfg, credential=False)
    sup.update([placement()])
    sup.tick()
    assert states(reports) == [("failed", "join_failed", "credential_missing")]


def test_a_placement_that_needs_a_join_waits_for_r4(world: Any) -> None:
    sup, backend, reports, _, logs = world
    agent = {"id": None, "handle": "agent-3", "member": False, "credential_expected": False}
    sup.update([placement(agent=agent)])
    sup.tick()
    sup.tick()
    assert reports.sent == [] and backend.started == []
    assert len([line for line in logs if "R4" in line]) == 1


def test_capacity(world: Any) -> None:
    sup, backend, reports, _, _ = world
    sup.cfg = replace(sup.cfg, limits=replace(sup.cfg.limits, max_agents=1))
    recorded(sup.cfg, 3)
    recorded(sup.cfg, 4)
    sup.update([placement(3), placement(4)])
    settle(sup)
    assert [s[0] for s in backend.started] == ["maity-maity-agent-3"]
    assert sup.records["plc-0004"].state == "pending"
    assert sup.records["plc-0004"].reason == "capacity"


# --- adopt and orphan ------------------------------------------------------------------------


def test_after_a_runner_restart_a_live_session_is_adopted(world: Any) -> None:
    sup, backend, reports, _, _ = world
    recorded(sup.cfg)
    backend.live["maity-maity-agent-3"] = tmux.Session(
        "maity-maity-agent-3", False, None, 99, "plc-0003", 1
    )
    sup.update([placement()])
    sup.tick()
    assert states(reports) == [("running", "adopted", None)]
    assert backend.started == []


def test_a_session_whose_placement_is_gone_ends_after_the_grace(world: Any) -> None:
    sup, backend, reports, clock, logs = world
    orphan = tmux.Session("maity-maity-agent-9", False, None, 77, "plc-0009", 2)
    backend.live[orphan.name] = orphan
    sup.tick()
    assert backend.terminated == []  # nothing known yet: never touched before the first read
    sup.update([])
    sup.tick()
    clock.now += sup.cfg.limits.stop_grace_max
    sup.tick()
    assert backend.terminated == [orphan.name]
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    assert orphan.name in backend.killed and reports.sent == []
    assert any("orphaned" in line for line in logs)


def test_unlabelled_sessions_are_never_touched(world: Any) -> None:
    sup, backend, _, clock, _ = world
    backend.live["maity-other"] = tmux.Session("maity-other", False, None, 5, None, None)
    sup.update([])
    clock.now += 10_000
    sup.tick()
    sup.tick()
    assert backend.terminated == [] and backend.killed == []


# --- reports and persistence -----------------------------------------------------------------


def test_a_report_the_hub_did_not_take_is_sent_again(world: Any) -> None:
    sup, _, reports, _, _ = world
    reports.fail = [hub.HubError("down", status=None)]
    sup.update([placement(desired="stopped")])
    sup.tick()
    assert reports.sent == []
    sup.tick()
    assert [b["seq"] for _, b in reports.sent] == [1]


def test_a_stale_generation_drops_the_report(world: Any) -> None:
    sup, _, reports, _, _ = world
    reports.fail = [hub.HubError("stale", code="stale_generation", status=409)]
    sup.update([placement(desired="stopped")])
    sup.tick()
    sup.tick()
    assert [b["seq"] for _, b in reports.sent] == [2]


def test_records_survive_a_restart(world: Any) -> None:
    sup, backend, _, _, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    again = supervisor.Supervisor(sup.cfg, backend, None, print, sup.probes)
    again.load()
    assert again.records["plc-0003"].seq == sup.records["plc-0003"].seq
    assert again.actual() == [
        {"placement_id": "plc-0003", "generation": 1, "state": "starting", "target": "local"}
    ]


# --- workspaces: clone, records, no git in an existing clone ---------------------------------


@pytest.fixture
def origin_repo(tmp_path: Path) -> Path:
    git = shutil.which("git")
    assert git is not None
    repo = tmp_path / "origin"
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "HOME": str(tmp_path)}
    subprocess.run([git, "init", "-q", "-b", "main", str(repo)], check=True, env=env)
    subprocess.run(
        [git, "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e.invalid",
         "commit", "-q", "--allow-empty", "-m", "init"],
        check=True, env=env,
    )  # fmt: skip
    return repo


def test_prepare_clones_and_records(tmp_path: Path, origin_repo: Path) -> None:
    cfg = load(tmp_path)
    assert cfg.local is not None
    place = workspace.locate(cfg.local.workspaces, "maity", "agent-3")
    workspace.prepare(cfg, place, str(origin_repo), "agt-3", "plc-0003")
    assert workspace.origin(place.path) == str(origin_repo)
    assert workspace.records(cfg.state_dir)[str(place.path)]["agent"] == "agt-3"
    with pytest.raises(workspace.Refused) as other:
        workspace.prepare(cfg, place, str(origin_repo), "agt-4", "plc-0004")
    assert other.value.detail == "other_agent"
    with pytest.raises(workspace.Refused) as moved:
        workspace.prepare(cfg, place, "https://github.com/x/y", "agt-3", "plc-0003")
    assert moved.value.detail == "origin_mismatch"


def test_a_failed_clone(tmp_path: Path) -> None:
    cfg = load(tmp_path)
    assert cfg.local is not None
    place = workspace.locate(cfg.local.workspaces, "maity", "agent-3")
    with pytest.raises(workspace.Refused) as failed:
        workspace.prepare(cfg, place, str(tmp_path / "missing"), "agt-3", "plc-0003")
    assert failed.value.reason == "clone_failed" and failed.value.exit_code


def test_hooks_and_fsmonitor_planted_in_a_clone_never_run(
    tmp_path: Path, origin_repo: Path
) -> None:
    cfg = load(tmp_path)
    assert cfg.local is not None
    place = workspace.locate(cfg.local.workspaces, "maity", "agent-3")
    workspace.prepare(cfg, place, str(origin_repo), "agt-3", "plc-0003")
    marker = tmp_path / "ran"
    hook = place.path / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    with (place.path / ".git" / "config").open("a") as fh:
        fh.write(f"[core]\n\tfsmonitor = touch {marker}\n\tpager = touch {marker}\n")
    workspace.prepare(cfg, place, str(origin_repo), "agt-3", "plc-0005")
    workspace.stale_index_lock(place.path)
    assert not marker.exists()


@pytest.mark.parametrize(("project", "clone"), [("../x", "a"), ("maity", ".."), ("Maity", "a")])
def test_workspace_paths_come_from_tokens_only(tmp_path: Path, project: str, clone: str) -> None:
    with pytest.raises(workspace.Refused):
        workspace.locate(tmp_path, project, clone)


# --- tmux commands ---------------------------------------------------------------------------


def test_tmux_starts_the_server_under_a_clean_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSH_AUTH_SOCK", "/run/user/0/agent.sock")
    calls: list[list[str]] = []

    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    backend = tmux.Tmux(tmp_path / "s.sock", tmp_path / "tmux.conf", "/home/agent",
                        "/usr/bin:/bin", tmp_path / "logs", run=run)  # fmt: skip
    backend.start("maity-maity-agent-3", tmp_path, ["stub", "--x"], {"MAITY_PLACEMENT": "p"},
                  "plc-0003", 4)  # fmt: skip
    new = calls[0]
    assert new[:2] == ["env", "-i"] and "SSH_AUTH_SOCK" not in " ".join(new)
    assert new[new.index("tmux") : new.index("tmux") + 3] == [
        "tmux",
        "-S",
        str(tmp_path / "s.sock"),
    ]
    assert new[-3:] == ["--", "stub", "--x"] and "MAITY_PLACEMENT=p" in new
    assert ["@maity_generation", "4"] == calls[2][-2:]
    assert 'update-environment ""' in (tmp_path / "tmux.conf").read_text()
    log = tmp_path / "logs" / "plc-0003.log"
    assert oct(log.stat().st_mode & 0o777) == "0o600"


def test_tmux_without_a_server_has_no_sessions(tmp_path: Path) -> None:
    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(argv), 1, "", "no server running on /x\n")

    backend = tmux.Tmux(tmp_path / "s", tmp_path / "c", "/h", "/bin", tmp_path, run=run)
    assert backend.sessions() == {}


def test_tmux_parses_panes(tmp_path: Path) -> None:
    out = "maity-maity-agent-3\t1\t2\t123\tplc-0003\t4\nother\t0\t\t5\t\t\n"

    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(argv), 0, out, "")

    backend = tmux.Tmux(tmp_path / "s", tmp_path / "c", "/h", "/bin", tmp_path, run=run)
    assert backend.sessions() == {
        "maity-maity-agent-3": tmux.Session("maity-maity-agent-3", True, 2, 123, "plc-0003", 4)
    }


# --- against a real tmux, where there is one -------------------------------------------------


@pytest.mark.skipif(shutil.which("tmux") is None, reason="needs tmux")
def test_real_tmux_session_has_no_runner_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSH_AUTH_SOCK", "/run/user/0/agent.sock")
    monkeypatch.setenv("MAITY_STATE_DIR", "/srv/agent-state")
    socket = tmp_path / "t.sock"
    backend = tmux.Tmux(socket, tmp_path / "tmux.conf", str(tmp_path), "/usr/bin:/bin",
                        tmp_path / "logs")  # fmt: skip
    try:
        backend.start("maity-maity-agent-3", tmp_path, ["sh", "-c", "env; sleep 30"],
                      {"MAITY_PLACEMENT": "plc-0003"}, "plc-0003", 2)  # fmt: skip
        found = backend.sessions()["maity-maity-agent-3"]
        assert (found.placement, found.generation, found.dead) == ("plc-0003", 2, False)
        env = backend.environment_of("maity-maity-agent-3")
        assert "SSH_AUTH_SOCK" not in env and "MAITY_STATE_DIR" not in env
        assert env.get("MAITY_PLACEMENT") == "plc-0003" and env["PATH"] == "/usr/bin:/bin"
    finally:
        subprocess.run(["tmux", "-S", str(socket), "kill-server"], check=False)
