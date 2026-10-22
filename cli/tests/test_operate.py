from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import git

from maity import cli, state
from maity.runner import config, operate, serve, supervisor, tmux, workspace

CONFIG = """\
[hub]
url = "https://hub.example"
state_dir = "{root}/st"

[limits]
projects = ["maity"]
repositories = ["github.com/oliver-zehentleitner/*"]
require_local_approval = {approval}

[backend.local]
workspaces = "{root}/ws"

[harness.stub]
"""


def setup(tmp_path: Path, approval: bool = False) -> Path:
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(root=tmp_path, approval=str(approval).lower()))
    (tmp_path / "st").mkdir(mode=0o700)
    state.save_state(
        tmp_path / "st",
        {"pid": 1, "placements": [{"id": "plc-0003", "project": "maity", "agent": "agent-f"}]},
        name=serve.STATUS_FILE,
    )
    return path


def test_logs_by_agent_handle(tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    path = setup(tmp_path)
    logs = tmp_path / "st" / supervisor.LOGS
    logs.mkdir()
    (logs / "plc-0003.log").write_bytes(b"maity stub: exit 0\n")
    assert cli.main(["runner", "logs", "agent-f", "--config", str(path)]) == 0
    assert capsysbinary.readouterr().out == b"maity stub: exit 0\n"


def test_logs_of_an_unknown_placement_is_refused(tmp_path: Path) -> None:
    path = setup(tmp_path)
    assert cli.main(["runner", "logs", "agent-z", "--config", str(path)]) == cli.EXIT_USAGE


def test_approve_needs_the_setting(tmp_path: Path) -> None:
    path = setup(tmp_path)
    assert cli.main(["runner", "approve", "plc-0003", "--config", str(path)]) == cli.EXIT_USAGE


def test_a_held_placement_starts_after_approve(tmp_path: Path) -> None:
    path = setup(tmp_path, approval=True)
    cfg = config.load(path)
    from test_supervisor import FakeTmux, placement, recorded

    backend = FakeTmux()
    sup = supervisor.Supervisor(cfg, backend, None, print, {})  # type: ignore[arg-type]
    recorded(cfg)
    sup.update([placement()])
    sup.tick()
    assert (sup.records["plc-0003"].state, sup.records["plc-0003"].reason) == (
        "pending", "awaiting_operator"
    )  # fmt: skip
    assert cli.main(["runner", "approve", "agent-f", "--config", str(path)]) == 0
    sup.tick()
    for task in list(sup.tasks.values()):
        task.join(5)
    assert len(backend.started) == 1


def test_stop_all_is_refused_while_the_service_runs(tmp_path: Path) -> None:
    path = setup(tmp_path)
    lock = serve.hold_lock(tmp_path / "st")
    try:
        assert cli.main(["runner", "stop-all", "--config", str(path)]) == cli.EXIT_USAGE
    finally:
        lock.close()


def test_stop_all_ends_every_agent_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from test_supervisor import FakeTmux

    path = setup(tmp_path)
    backend = FakeTmux()
    backend.live["maity_maity_agent-f"] = tmux.Session("maity_maity_agent-f", False, None, 9,
                                                       "plc-0003", 1)  # fmt: skip
    backend.live["maity_other"] = tmux.Session("maity_other", False, None, 8, None, None)
    monkeypatch.setattr(supervisor, "local_backend", lambda cfg: backend)

    def terminated(session: tmux.Session) -> None:
        backend.terminated.append(session.name)
        backend.exit(session.name, 143)

    monkeypatch.setattr(backend, "terminate", terminated)
    assert cli.main(["runner", "stop-all", "--grace", "2", "--config", str(path)]) == 0
    assert backend.terminated == ["maity_maity_agent-f"]  # an unlabelled session is not ours
    assert backend.killed == ["maity_maity_agent-f"]
    assert "ended maity_maity_agent-f" in capsys.readouterr().out


def test_gc_lists_and_only_removes_with_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = setup(tmp_path)
    cfg = config.load(path)
    assert cfg.local is not None
    place = workspace.locate(cfg.local.workspaces, "maity", "agent-g")
    place.path.mkdir(parents=True)
    git(place.path, "init", "-q")
    (place.path / "draft.txt").write_text("unsaved")
    workspace.record(cfg.state_dir, place, "agt-g", "plc-0007")  # no placement any more
    monkeypatch.setattr(operate, "credential_revoked", lambda p: True)
    assert cli.main(["runner", "gc", "--revoked", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "agent agt-g  credential revoked" in out and "?? draft.txt" in out
    assert place.path.exists()
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    assert not place.path.exists()
    assert str(place.path) not in workspace.records(cfg.state_dir)


def test_gc_runs_no_hook_of_the_clone(tmp_path: Path) -> None:
    clone = tmp_path / "c"
    clone.mkdir()
    git(clone, "init", "-q")
    marker = tmp_path / "ran"
    with (clone / ".git" / "config").open("a") as fh:
        fh.write(f"[core]\n\tfsmonitor = touch {marker}\n\tpager = touch {marker}\n")
    operate.unsaved_work(clone)
    assert not marker.exists()


def test_gc_needs_revoked(tmp_path: Path) -> None:
    path = setup(tmp_path)
    assert cli.main(["runner", "gc", "--config", str(path)]) == cli.EXIT_USAGE


def test_workspace_claim(tmp_path: Path) -> None:
    path = setup(tmp_path)
    cfg = config.load(path)
    assert cfg.local is not None
    clone = cfg.local.workspaces / "maity" / "agent-h"
    clone.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(clone)], check=True)
    code = cli.main(
        ["runner", "workspace", "claim", "maity/agent-h", "--agent", "agt-h", "--config", str(path)]
    )
    assert code == 0
    assert workspace.records(cfg.state_dir)[str(clone.resolve())]["agent"] == "agt-h"
    again = ["runner", "workspace", "claim", "maity/agent-h", "--agent", "agt-x",
             "--config", str(path)]  # fmt: skip
    assert cli.main(again) == cli.EXIT_USAGE
    assert cli.main([*again, "--force"]) == 0


def test_workspace_claim_refuses_a_path_outside(tmp_path: Path) -> None:
    path = setup(tmp_path)
    code = cli.main(
        ["runner", "workspace", "claim", "../x", "--agent", "agt-h", "--config", str(path)]
    )
    assert code == cli.EXIT_USAGE
