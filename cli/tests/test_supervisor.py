from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from maity import hub, state
from maity.runner import capabilities, config, restart, supervisor, tmux, workspace

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
        (place.path / ".git" / "maity").mkdir(mode=0o700)
        (place.path / ".git" / "maity" / "credential").write_text("mty1.crd-x.y")
    workspace.record(cfg.state_dir, place, f"agt-{n}", f"plc-000{n}")
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
    assert sup.cfg.local is not None
    clone = workspace.locate(sup.cfg.local.workspaces, "maity", "agent-3").path
    assert name == "maity_maity_agent-3"
    assert env == {"MAITY_PLACEMENT": "plc-0003", "GIT_COMMON_DIR": str(clone / ".git")}
    assert argv[1:4] == ["-I", "-m", "maity.runner.stub"]  # -I: nothing from the clone loads
    assert argv[-3:] == ["1", "--run-seconds", "5"]
    clock.now += supervisor.RUNNING_AFTER
    sup.tick()
    assert states(reports) == [("starting", None, None), ("running", None, None)]
    first, second = (b for _, b in reports.sent)
    assert (first["seq"], second["seq"]) == (1, 2)
    assert second["session_hint"] == "tmux -S /run/maity/tmux.sock attach -t maity_maity_agent-3"
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
        backend.exit("maity_maity_agent-3", 1)
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
    assert backend.terminated == ["maity_maity_agent-3"]
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    sup.tick()
    assert "maity_maity_agent-3" in backend.killed
    assert states(reports)[-1] == ("stopped", "stopped_by_hub", None)


def test_a_process_ending_within_the_grace_is_stopped_at_once(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    sup.update([placement(desired="stopped")])
    sup.tick()
    backend.exit("maity_maity_agent-3", 0)
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
    assert backend.terminated == ["maity_maity_agent-3"]
    backend.exit("maity_maity_agent-3", 143)
    settle(sup)
    assert backend.started[-1][0] == "maity_maity_agent-3"
    assert backend.live["maity_maity_agent-3"].generation == 2


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


class Pickups(Reports):
    """Reports, and the pickup: answers from a list (dict, or an exception to raise)."""

    def __init__(self, *answers: Any) -> None:
        super().__init__()
        self.answers = list(answers)
        self.pickups: list[dict[str, Any]] = []

    def call(self, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
        if path.endswith("/join"):
            self.pickups.append(body)
            answer = self.answers.pop(0)
            if isinstance(answer, BaseException):
                raise answer
            return answer
        return super().call(method, path, body=body)


PICKUP = {"join_url": "https://hub.example/j/tok", "code": "AAAA-BBBB-CCCC", "pickup": 1}
NEW = {"id": None, "handle": "agent-3", "member": False, "credential_expected": False}


def joining(
    monkeypatch: pytest.MonkeyPatch, result: tuple[bool, str | None] = (True, None)
) -> list[Any]:
    """Replace the child `maity join`: on success it writes what the real one would."""
    calls: list[Any] = []

    def fake(place: workspace.Workspace, url: str, code: str, cwd: Path) -> tuple[bool, str | None]:
        calls.append((place.path.name, url, code))
        if result[0]:
            state.write_credential(place.credential.parent, state.Secret("mty1.crd-x.y"))
            state.save_state(place.credential.parent, {"member_id": "agt-3"})
        return result

    monkeypatch.setattr(supervisor, "run_join", fake)
    return calls


def new_clone(cfg: config.Config) -> workspace.Workspace:
    """A clone recorded under the handle, before the first join (no credential)."""
    assert cfg.local is not None
    place = workspace.locate(cfg.local.workspaces, "maity", "agent-3")
    (place.path / ".git").mkdir(parents=True)
    (place.path / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {REPO}\n')
    workspace.record(cfg.state_dir, place, "agent-3", "plc-0003")
    return place


def test_a_new_agent_is_picked_up_joined_and_started(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, _, _, _ = world
    sup.client = Pickups(PICKUP)
    calls = joining(monkeypatch)
    place = new_clone(sup.cfg)
    sup.update([placement(agent=NEW)])
    settle(sup)
    assert sup.client.pickups == [{"observed_generation": 1}]
    assert calls == [("agent-3", PICKUP["join_url"], PICKUP["code"])]
    assert [s[0] for s in backend.started] == ["maity_maity_agent-3"]
    assert workspace.records(sup.cfg.state_dir)[str(place.path)]["agent"] == "agt-3"


def test_a_lost_pickup_answer_is_retried(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sup, backend, _, clock, _ = world
    sup.client = Pickups(hub.HubError("reset", status=None), PICKUP)
    joining(monkeypatch)
    new_clone(sup.cfg)
    sup.update([placement(agent=NEW)])
    settle(sup)
    assert backend.started == [] and sup.records["plc-0003"].state != "failed"
    clock.now += supervisor.PICKUP_RETRY
    settle(sup)
    assert len(sup.client.pickups) == 2 and len(backend.started) == 1


@pytest.mark.parametrize(
    ("pickup", "joined", "detail"),
    [
        (hub.HubError("used", code="pickup_used", status=409), (True, None), "pickup_used"),
        (hub.HubError("no", code="pickup_not_allowed", status=409), (True, None),
         "pickup_not_allowed"),
        (PICKUP, (False, "code_invalid"), "code_invalid"),
        (PICKUP, (False, None), None),
    ],
)  # fmt: skip
def test_a_join_that_fails_is_join_failed(
    world: Any, monkeypatch: pytest.MonkeyPatch, pickup: Any, joined: Any, detail: Any
) -> None:
    sup, backend, reports, _, _ = world
    sup.client = Pickups(pickup)
    joining(monkeypatch, joined)
    new_clone(sup.cfg)
    sup.update([placement(agent=NEW)])
    settle(sup)
    assert backend.started == []
    assert (sup.records["plc-0003"].state, sup.records["plc-0003"].reason) == (
        "failed", "join_failed"
    )  # fmt: skip
    assert sup.records["plc-0003"].detail == detail


def test_a_rejoin_removes_the_old_credential_first(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, _, _, _ = world
    sup.client = Pickups(PICKUP)
    place = recorded(sup.cfg)
    seen: list[bool] = []

    def fake(
        place_: workspace.Workspace, url: str, code: str, cwd: Path
    ) -> tuple[bool, str | None]:
        seen.append(place_.credential.exists())
        place_.credential.write_text("mty1.crd-new.y")
        return True, None

    monkeypatch.setattr(supervisor, "run_join", fake)
    sup.update([placement(rejoin=True)])
    settle(sup)
    assert seen == [False] and place.credential.read_text() == "mty1.crd-new.y"
    assert len(backend.started) == 1


def test_run_join_keeps_url_and_code_off_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"], seen["input"], seen["env"] = command, kwargs["input"], kwargs["env"]
        return subprocess.CompletedProcess(command, 1, "", "maity: join: code_invalid: wrong\n")

    monkeypatch.setattr("maity.runner.supervisor.subprocess.run", fake_run)
    monkeypatch.setenv("MAITY_STATE_DIR", "/elsewhere")
    place = workspace.Workspace(tmp_path / "c", "maity", "c")
    assert supervisor.run_join(place, "https://h/j/SECRET-TOKEN", "CODE-1234", tmp_path) == (
        False, "code_invalid"
    )  # fmt: skip
    assert not any("SECRET-TOKEN" in a or "CODE-1234" in a for a in seen["argv"])
    assert seen["input"] == "https://h/j/SECRET-TOKEN\nCODE-1234\n"
    assert seen["env"]["MAITY_STATE_DIR"] == str(place.credential.parent)
    assert "--no-resume" in seen["argv"] and "--join-file" in seen["argv"]


def test_run_join_against_a_hub(tmp_path: Path, fake: Any) -> None:
    import fakehub

    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    place = workspace.Workspace(clone, "maity", "clone")
    assert supervisor.run_join(place, f"{fake.url}/j/{fakehub.TOKEN}", fakehub.CODE, tmp_path) == (
        True, None
    )  # fmt: skip
    assert place.credential.read_text() == fakehub.CREDENTIAL
    assert state.load_state(place.credential.parent)["member_id"] == "agt-b"
    exchange = [s for s in fake.seen if s.method == "POST"][0]
    assert exchange.json()["client"].startswith("maity-runner/")


def test_capacity(world: Any) -> None:
    sup, backend, reports, _, _ = world
    sup.cfg = replace(sup.cfg, limits=replace(sup.cfg.limits, max_agents=1))
    recorded(sup.cfg, 3)
    recorded(sup.cfg, 4)
    sup.update([placement(3), placement(4)])
    settle(sup)
    assert [s[0] for s in backend.started] == ["maity_maity_agent-3"]
    assert sup.records["plc-0004"].state == "pending"
    assert sup.records["plc-0004"].reason == "capacity"


# --- adopt and orphan ------------------------------------------------------------------------


def test_after_a_runner_restart_a_live_session_is_adopted(world: Any) -> None:
    sup, backend, reports, _, _ = world
    recorded(sup.cfg)
    backend.live["maity_maity_agent-3"] = tmux.Session(
        "maity_maity_agent-3", False, None, 99, "plc-0003", 1
    )
    sup.update([placement()])
    sup.tick()
    assert states(reports) == [("running", "adopted", None)]
    assert backend.started == []


def test_a_session_whose_placement_is_gone_ends_after_the_grace(world: Any) -> None:
    sup, backend, reports, clock, logs = world
    orphan = tmux.Session("maity_maity_agent-9", False, None, 77, "plc-0009", 2)
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
    backend.live["maity_other"] = tmux.Session("maity_other", False, None, 5, None, None)
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
    sup.tick()
    assert reports.sent == []  # settled: not resent with a new seq every tick
    sup.update([placement(desired="stopped", generation=2)])
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
def origin_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A local repository; cloning it needs the file transport, which the runner refuses."""
    monkeypatch.setattr(workspace, "PROTOCOLS", ("https", "ssh", "file"))
    monkeypatch.setattr(config, "repository_url_ok", lambda url: True)
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


def test_a_failed_clone(tmp_path: Path, origin_repo: Path) -> None:
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
    backend.start("maity_maity_agent-3", tmp_path, ["stub", "--x"], {"MAITY_PLACEMENT": "p"},
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
    out = (
        "maity_maity_agent-3\t1\t2\t123\tplc-0003\t4\t0.0\n"
        "maity_maity_agent-3\t0\t\t999\tplc-0003\t4\t0.1\n"  # a pane added later masks nothing
        "other\t0\t\t5\t\t\t0.0\n"
    )

    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(list(argv), 0, out, "")

    backend = tmux.Tmux(tmp_path / "s", tmp_path / "c", "/h", "/bin", tmp_path, run=run)
    assert backend.sessions() == {
        "maity_maity_agent-3": tmux.Session("maity_maity_agent-3", True, 2, 123, "plc-0003", 4)
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
        backend.start("maity_maity_agent-3", tmp_path, ["sh", "-c", "env; sleep 30"],
                      {"MAITY_PLACEMENT": "plc-0003"}, "plc-0003", 2)  # fmt: skip
        found = backend.sessions()["maity_maity_agent-3"]
        assert (found.placement, found.generation, found.dead) == ("plc-0003", 2, False)
        env = backend.environment_of("maity_maity_agent-3")
        assert "SSH_AUTH_SOCK" not in env and "MAITY_STATE_DIR" not in env
        assert env.get("MAITY_PLACEMENT") == "plc-0003" and env["PATH"] == "/usr/bin:/bin"
    finally:
        subprocess.run(["tmux", "-S", str(socket), "kill-server"], check=False)


# --- review round ----------------------------------------------------------------------------


def test_session_names_cannot_collide() -> None:
    assert tmux.session_name("ab", "cd-ef") != tmux.session_name("ab-cd", "ef")


def test_two_placements_whose_names_would_have_collided_both_run(world: Any) -> None:
    sup, backend, _, clock, logs = world
    sup.cfg = replace(sup.cfg, limits=replace(sup.cfg.limits, projects=("ab", "ab-cd")))
    first = placement(3, project="ab", workspace={"clone": "cd-ef", "repository": REPO})
    second = placement(4, project="ab-cd", workspace={"clone": "ef", "repository": REPO})
    for p in (first, second):
        place = workspace.locate(sup.cfg.local.workspaces, p["project"], p["workspace"]["clone"])
        (place.path / ".git" / "maity").mkdir(parents=True)
        (place.path / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {REPO}\n')
        (place.path / ".git" / "maity" / "credential").write_text("mty1.crd-x.y")
        workspace.record(sup.cfg.state_dir, place, p["agent"]["id"], p["id"])
    sup.update([first, second])
    settle(sup)
    clock.now += 10_000
    for _ in range(5):
        sup.tick()
    assert len(backend.started) == 2 and backend.terminated == [] and backend.killed == []


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "../../escaped"},
        {"id": "plc-0003/x"},
        {"project": "../x"},
        {"generation": "4"},
        {"generation": True},
        {"workspace": {"clone": "a/b", "repository": REPO}},
        {"workspace": None},
        {"desired": "maybe"},
    ],
)
def test_a_malformed_placement_is_dropped_and_the_rest_runs(
    world: Any, bad: dict[str, Any]
) -> None:
    sup, backend, reports, _, logs = world
    recorded(sup.cfg, 4)
    sup.update([placement(3, **bad), placement(4)])
    settle(sup)
    assert [s[0] for s in backend.started] == ["maity_maity_agent-4"]
    assert {path for path, _ in reports.sent} == {"plc-0004"}
    assert any("malformed" in line for line in logs)


def test_a_placement_missing_a_key_does_not_stop_the_tick(world: Any) -> None:
    sup, backend, _, _, _ = world
    recorded(sup.cfg, 4)
    broken = placement(3)
    del broken["project"]
    sup.update([broken, placement(4)])
    settle(sup)
    assert [s[0] for s in backend.started] == ["maity_maity_agent-4"]


def test_adoption_waits_for_the_first_read_of_the_placements(world: Any) -> None:
    sup, backend, reports, _, _ = world
    recorded(sup.cfg)
    backend.live["maity_maity_agent-3"] = tmux.Session(
        "maity_maity_agent-3", False, None, 99, "plc-0003", 1
    )
    sup.records["plc-0003"] = supervisor.Record(generation=1, state="running", since=1.0)
    sup.tick()  # serve has not said hello yet: nothing desired
    sup.update([placement()])
    sup.tick()
    assert states(reports) == [("running", "adopted", None)]
    assert backend.started == []


def test_a_live_session_without_a_record_is_adopted(world: Any) -> None:
    sup, backend, reports, _, _ = world
    sup.update([placement()])
    sup.tick()
    sup.first_tick = False
    del sup.records["plc-0003"]
    backend.live["maity_maity_agent-3"] = tmux.Session(
        "maity_maity_agent-3", False, None, 99, "plc-0003", 1
    )
    sup.tick()
    assert states(reports)[-1] == ("running", "adopted", None)


def test_an_adopted_session_that_exits_is_not_a_quick_crash(world: Any) -> None:
    sup, backend, _, clock, _ = world
    recorded(sup.cfg)
    backend.live["maity_maity_agent-3"] = tmux.Session(
        "maity_maity_agent-3", False, None, 99, "plc-0003", 1
    )
    sup.update([placement()])
    sup.tick()
    clock.now += 1
    backend.exit("maity_maity_agent-3", 1)
    sup.tick()
    assert sup.records["plc-0003"].crashes == []


def test_capacity_counts_starts_in_flight(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    sup, backend, _, _, _ = world
    sup.cfg = replace(sup.cfg, limits=replace(sup.cfg.limits, max_agents=1))
    recorded(sup.cfg, 3)
    recorded(sup.cfg, 4)
    gate = threading.Event()
    real = workspace.prepare

    def slow(*args: Any, **kwargs: Any) -> None:
        gate.wait(5)
        real(*args, **kwargs)

    monkeypatch.setattr(workspace, "prepare", slow)
    sup.update([placement(3), placement(4)])
    sup.tick()
    sup.tick()  # the first start is still in flight
    gate.set()
    for task in list(sup.tasks.values()):
        task.join(5)
    sup.tick()
    assert [s[0] for s in backend.started] == ["maity_maity_agent-3"]
    assert sup.records["plc-0004"].reason == "capacity"


def test_a_stop_during_a_start_does_not_start(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    sup, backend, reports, _, _ = world
    recorded(sup.cfg)
    gate = threading.Event()
    real = workspace.prepare

    def slow(*args: Any, **kwargs: Any) -> None:
        gate.wait(5)
        real(*args, **kwargs)

    monkeypatch.setattr(workspace, "prepare", slow)
    sup.update([placement()])
    sup.tick()
    sup.update([placement(desired="stopped")])
    gate.set()
    for task in list(sup.tasks.values()):
        task.join(5)
    sup.tick()
    assert backend.started == []
    assert states(reports)[-1] == ("stopped", "stopped_by_hub", None)


def test_a_session_that_cannot_be_labelled_is_killed(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        failing = "set-option" in argv
        return subprocess.CompletedProcess(list(argv), 1 if failing else 0, "", "boom")

    backend = tmux.Tmux(tmp_path / "s", tmp_path / "c", "/h", "/bin", tmp_path / "logs", run=run)
    with pytest.raises(tmux.TmuxError):
        backend.start("maity_p_c", tmp_path, ["x"], {}, "plc-0003", 1)
    assert calls[-1][-3:] == ["kill-session", "-t", "maity_p_c"]


def test_a_tmux_failure_at_start_backs_off_instead_of_failing_for_good(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, reports, _, _ = world
    recorded(sup.cfg)

    def broken(*args: Any, **kwargs: Any) -> None:
        raise tmux.TmuxError("timed out")

    monkeypatch.setattr(backend, "start", broken)
    sup.update([placement()])
    settle(sup)
    rec = sup.records["plc-0003"]
    assert rec.state == "exited" and rec.retry_at is not None


def test_exit_code_does_not_outlive_its_generation(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    backend.exit("maity_maity_agent-3", 7)
    sup.tick()
    sup.update([placement(generation=2, harness="claude-code")])
    sup.tick()
    last = reports.sent[-1][1]
    assert last["reason"] == "harness_refused" and last["exit_code"] is None


def test_workspace_in_use_comes_before_credential_missing(world: Any) -> None:
    sup, _, reports, _, _ = world
    place = workspace.locate(sup.cfg.local.workspaces, "maity", "agent-3")
    place.path.mkdir(parents=True)
    sup.update([placement()])
    sup.tick()
    assert states(reports) == [("failed", "workspace_in_use", "workspace_unrecorded")]


def test_terminate_never_signals_the_runners_own_group(tmp_path: Path) -> None:
    import os

    backend = tmux.Tmux(tmp_path / "s", tmp_path / "c", "/h", "/bin", tmp_path)
    backend.terminate(tmux.Session("x", False, None, os.getpgrp(), "plc-1", 1))
    backend.terminate(tmux.Session("x", False, None, os.getpid(), "plc-1", 1))  # not a leader
    backend.terminate(tmux.Session("x", False, None, 1, "plc-1", 1))


def test_running_is_advertised_when_it_changes(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    patches: list[dict[str, Any]] = []

    class Client(Reports):
        def call(self, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
            if method == "PATCH":
                patches.append(body)
                return {}
            return super().call(method, path, body=body)

    sup.client = Client()
    sup.capabilities = {"running": 0, "targets": [{"name": "local", "running": 0}]}
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    assert patches[-1]["capabilities"]["running"] == 1
    assert patches[-1]["capabilities"]["targets"][0]["running"] == 1
    sup.tick()
    assert len(patches) == 1


def test_unsupported_settings_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(
        CONFIG.format(root=tmp_path, max_agents=2).replace(
            "[backend.local]\n",
            '[backend.local]\nlayout = "agent_user"\nagent_user = "a"\n' 'memory_max = "4G"\n',
        )
    )
    found = config.unsupported(config.load(path))
    assert any("agent_user" in f for f in found) and any("memory_max" in f for f in found)


def test_a_relative_tmux_socket_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(
        CONFIG.format(root=tmp_path, max_agents=2).replace(
            "[backend.local]\n", '[backend.local]\ntmux_socket = "maity"\n'
        )
    )
    with pytest.raises(config.ConfigError, match="absolute"):
        config.load(path)


def test_the_stub_does_not_spin_on_a_failing_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity.runner import stub

    (tmp_path / ".git" / "maity").mkdir(parents=True)
    (tmp_path / ".git" / "maity" / "credential").write_text("mty1.crd-x.y")
    monkeypatch.chdir(tmp_path)
    now = [0.0]
    calls: list[tuple[str, ...]] = []

    def fake_maity(*args: str, timeout: float) -> int:
        calls.append(args)
        return 2

    monkeypatch.setattr(stub, "_maity", fake_maity)
    monkeypatch.setattr("maity.runner.stub.time.monotonic", lambda: now[0])
    monkeypatch.setattr("maity.runner.stub.time.sleep", lambda s: now.__setitem__(0, now[0] + s))
    assert stub.main(["--exit-code", "3", "--run-seconds", "30"]) == 3
    assert len([c for c in calls if c[0] == "wait"]) <= 7  # one per 5 s, not millions


def test_serve_refuses_unsupported_settings_with_78(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from maity import cli
    from maity.runner import serve

    path = tmp_path / "runner.toml"
    path.write_text(
        CONFIG.format(root=tmp_path, max_agents=2).replace(
            "[backend.local]\n", '[backend.local]\ncpu_quota = "200%"\n'
        )
    )
    assert cli.main(["runner", "serve", "--config", str(path)]) == serve.EXIT_CONFIG
    assert "cpu_quota" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad",
    [{"seq": "41"}, {"seq": -1}, {"stop_grace_seconds": 901}, {"stop_grace_seconds": "x"},
     {"agent": "agt-3"}, {"agent": {"id": 5}}],
)  # fmt: skip
def test_more_malformed_placements_are_dropped(world: Any, bad: dict[str, Any]) -> None:
    sup, backend, reports, _, _ = world
    recorded(sup.cfg, 4)
    sup.update([placement(3, **bad), placement(4)])
    settle(sup)
    assert {path for path, _ in reports.sent} == {"plc-0004"}


def test_a_start_that_ends_between_snapshot_and_step_is_not_doubled(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, _, _, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    sup.tick()
    task = sup.tasks["plc-0003"]
    task.join(5)
    stale = dict(backend.live)
    backend.live.clear()  # the snapshot of the next tick predates the new session

    def snapshot() -> dict[str, Any]:
        backend.live.update(stale)
        return {}

    monkeypatch.setattr(backend, "sessions", snapshot)
    sup.tick()
    assert len(backend.started) == 1


# --- #121 review round -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:18777#@github.com/oliver-zehentleitner/maity",
        "http://127.0.0.1:18777?@github.com/oliver-zehentleitner/maity",
        "https://127.0.0.1#@github.com/oliver-zehentleitner/maity",
        "file:///srv/github.com/oliver-zehentleitner/maity",
        "ext::sh -c touch% /tmp/x",
        "https://github.com/oliver-zehentleitner/maity%2F..",
        "https://user:pw@github.com/oliver-zehentleitner/maity",
        "https://user@github.com/oliver-zehentleitner/maity",
        "https://github.com/oliver-zehentleitner\\maity",
        "https://github.com/oliver-zehentleitner/maity extra",
        "https://github.com/oliver-zehentleitner/maity/tree",
    ],
)
def test_repository_urls_that_could_be_read_two_ways_are_refused(url: str) -> None:
    assert not config.repository_url_ok(url)
    assert not config.repository_allowed(url, ("github.com/oliver-zehentleitner/*",))


@pytest.mark.parametrize(
    "url",
    ["https://github.com/oliver-zehentleitner/maity.git",
     "ssh://git@github.com/oliver-zehentleitner/maity.git"],
)  # fmt: skip
def test_https_and_ssh_repository_urls_pass(url: str) -> None:
    assert config.repository_allowed(url, ("github.com/oliver-zehentleitner/*",))


def test_a_bypass_url_is_refused_before_anything_runs(world: Any) -> None:
    sup, backend, reports, _, _ = world
    bad = "http://127.0.0.1:18777#@github.com/oliver-zehentleitner/maity"
    sup.update([placement(workspace={"clone": "agent-3", "repository": bad})])
    sup.tick()
    assert states(reports) == [("failed", "repository_refused", None)]


def test_the_clone_allows_only_https_and_ssh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load(tmp_path)
    assert cfg.local is not None
    seen: list[list[str]] = []

    def fake_run(command: list[str], cwd: Path, timeout: float) -> Any:
        seen.append(command)
        return subprocess.CompletedProcess(command, 128, "", "")

    monkeypatch.setattr("maity.runner.workspace.proc.run", fake_run)
    place = workspace.locate(cfg.local.workspaces, "maity", "agent-3")
    with pytest.raises(workspace.Refused):
        workspace.prepare(cfg, place, REPO, "agt-3", "plc-0003")
    command = seen[0]
    assert command[:3] == ["git", "-c", "protocol.allow=never"]
    assert "protocol.https.allow=always" in command and "protocol.file.allow=always" not in command


def test_run_join_imports_nothing_from_the_clone(tmp_path: Path, fake: Any) -> None:
    import fakehub

    clone = tmp_path / "clone"
    (clone / ".git").mkdir(parents=True)
    marker = tmp_path / "planted-ran"
    for name in ("json.py", "maity.py"):
        (clone / name).write_text(f"open({str(marker)!r}, 'w').close()\n")
    place = workspace.Workspace(clone, "maity", "clone")
    runner_dir = tmp_path / "state"
    runner_dir.mkdir()
    url = f"{fake.url}/j/{fakehub.TOKEN}"
    assert supervisor.run_join(place, url, fakehub.CODE, runner_dir) == (True, None)
    assert not marker.exists()


def test_the_next_start_after_a_join_accepts_its_own_clone(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, _, _, _ = world
    sup.client = Pickups(PICKUP)
    joining(monkeypatch)
    new_clone(sup.cfg)
    sup.update([placement(agent=NEW)])
    settle(sup)
    backend.exit("maity_maity_agent-3", 0)
    sup.tick()
    sup.records["plc-0003"].retry_at = None
    settle(sup)  # the hub has not named the new member yet: agent.id is still None
    assert len(backend.started) == 2
    assert sup.records["plc-0003"].reason != "workspace_in_use"


def test_a_rejoin_happens_once_per_generation(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    sup, backend, _, _, _ = world
    sup.client = Pickups(PICKUP, PICKUP)
    calls = joining(monkeypatch)
    recorded(sup.cfg)
    sup.update([placement(rejoin=True, generation=2)])
    settle(sup)
    backend.exit("maity_maity_agent-3", 0)
    sup.tick()
    sup.records["plc-0003"].retry_at = None
    settle(sup)  # the hub has not cleared `rejoin` yet
    assert len(calls) == 1 and len(backend.started) == 2


def test_codex_is_refused_where_the_repository_grants_commands(world: Any) -> None:
    sup, backend, reports, _, _ = world
    sup.cfg = replace(
        sup.cfg,
        repositories={"github.com/oliver-zehentleitner/maity": config.RepositoryGrant(
            allow=("make test",))},
    )  # fmt: skip
    sup.update([placement(harness="codex")])
    sup.tick()
    assert states(reports) == [("failed", "harness_refused", None)]
