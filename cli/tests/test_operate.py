from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

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
    monkeypatch.setattr(operate, "credential_revoked", lambda place, as_user: True)
    monkeypatch.setattr(operate, "_active", lambda cfg: (set(), set()))
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


# --- review round: gc never runs the clone's code, never removes what it could not read ----


def revoked_clone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str = "agent-g") -> Any:
    path = setup(tmp_path)
    cfg = config.load(path)
    assert cfg.local is not None
    place = workspace.locate(cfg.local.workspaces, "maity", name)
    place.path.mkdir(parents=True)
    git(place.path, "init", "-q")
    (place.path / "draft.txt").write_text("unsaved")
    workspace.record(cfg.state_dir, place, "agt-g", "plc-0007")
    monkeypatch.setattr(operate, "credential_revoked", lambda place, as_user: True)
    monkeypatch.setattr(operate, "_active", lambda cfg: (set(), set()))
    return path, place


@pytest.mark.parametrize(
    "plant",
    [
        "attributes",  # a filter driver, run by `git status`
        "gpg",  # gpg.program with log.showSignature, run by `git log`
        "alias",
        "include",
        "commondir",  # config and info/attributes read from wherever commondir points
        "config.worktree",
    ],
)
def test_a_clone_with_configuration_that_runs_code_is_not_inspected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    plant: str,
) -> None:  # fmt: skip
    path, place = revoked_clone(tmp_path, monkeypatch)
    marker = tmp_path / "ran"
    config_file = place.path / ".git" / "config"
    with config_file.open("a") as fh:
        if plant == "attributes":
            (place.path / ".git" / "info").mkdir(exist_ok=True)
            (place.path / ".git" / "info" / "attributes").write_text("* filter=x\n")
            fh.write(f'[filter "x"]\n\tclean = touch {marker}\n')
        elif plant == "gpg":
            fh.write(f"[log]\n\tshowSignature = true\n[gpg]\n\tprogram = touch {marker}\n")
        elif plant in ("commondir", "config.worktree"):
            other = tmp_path / "elsewhere"
            shutil.copytree(place.path / ".git", other)
            (other / "info" / "attributes").write_text("* filter=x\n")
            with (other / "config").open("a") as other_fh:
                other_fh.write(f'[filter "x"]\n\tclean = touch {marker}\n')
            (place.path / ".git" / plant).write_text(f"{other}\n")
        elif plant == "alias":
            fh.write(f"[alias]\n\tstatus = !touch {marker}\n")
        else:
            fh.write(f"[include]\n\tpath = {tmp_path}/evil\n")
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "not inspected" in out and "not removed" in out
    assert place.path.exists() and not marker.exists()


@pytest.mark.parametrize(
    "plant",
    [
        "config-symlink",  # the checked file is a link to one that sets a filter
        "info-symlink",  # info/ points at a directory with attributes
        "objects-symlink",  # an allowed name, but a link
        "hooks-file",  # an allowed name with the wrong type
        "alternates",  # another object store
        "huge-config",
    ],
)
def test_a_git_directory_not_laid_out_like_a_clone_is_not_inspected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    plant: str,
) -> None:  # fmt: skip
    path, place = revoked_clone(tmp_path, monkeypatch)
    dot_git = place.path / ".git"
    marker = tmp_path / "ran"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    if plant == "config-symlink":
        evil = elsewhere / "config"
        evil.write_text(
            (dot_git / "config").read_text() + f'[filter "x"]\n\tclean = touch {marker}\n'
        )
        (dot_git / "config").unlink()
        (dot_git / "config").symlink_to(evil)
    elif plant == "info-symlink":
        (elsewhere / "attributes").write_text("* filter=x\n")
        shutil.rmtree(dot_git / "info")
        (dot_git / "info").symlink_to(elsewhere)
    elif plant == "objects-symlink":
        shutil.move(str(dot_git / "objects"), str(elsewhere / "objects"))
        (dot_git / "objects").symlink_to(elsewhere / "objects")
    elif plant == "hooks-file":
        shutil.rmtree(dot_git / "hooks")
        (dot_git / "hooks").write_text("")
    elif plant == "alternates":
        (dot_git / "objects" / "info").mkdir(exist_ok=True)
        (dot_git / "objects" / "info" / "alternates").write_text(f"{elsewhere}\n")
    else:
        with (dot_git / "config").open("a") as fh:
            fh.write("# padding\n" * 8000)
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "not inspected" in out and "not removed" in out
    assert place.path.exists() and not marker.exists()


def test_the_operators_git_environment_does_not_hide_a_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, place = revoked_clone(tmp_path, monkeypatch)
    for key, value in {"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "status.showUntrackedFiles",
                       "GIT_CONFIG_VALUE_0": "no"}.items():  # fmt: skip
        monkeypatch.setenv(key, value)
    assert cli.main(["runner", "gc", "--revoked", "--config", str(path)]) == 0
    assert "?? draft.txt" in capsys.readouterr().out


def test_a_clone_without_head_is_not_read_as_its_parent_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, place = revoked_clone(tmp_path, monkeypatch)
    parent = place.path.parent.parent
    git(parent, "init", "-q")
    (parent / ".gitignore").write_text("*\n")  # the parent sees nothing to keep
    (place.path / ".git" / "HEAD").unlink()
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    assert "git failed" in capsys.readouterr().out and place.path.exists()


def test_a_git_failure_keeps_the_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path, place = revoked_clone(tmp_path, monkeypatch)
    (place.path / ".git" / "HEAD").write_text("garbage\n")  # git exits 128
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    assert "git failed" in capsys.readouterr().out and place.path.exists()


def test_a_record_pointing_outside_the_workspaces_is_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, _place = revoked_clone(tmp_path, monkeypatch)
    cfg = config.load(path)
    important = tmp_path / "operator-home" / "important"
    important.mkdir(parents=True)
    records = workspace.records(cfg.state_dir)
    records[str(important)] = {"project": "maity", "agent": "agt-z", "placement_id": "plc-9"}
    state.save_state(cfg.state_dir, records, name=workspace.RECORDS)
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    assert important.exists()


def test_a_clone_an_active_placement_continues_is_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, place = revoked_clone(tmp_path, monkeypatch)
    monkeypatch.setattr(operate, "_active", lambda cfg: ({("maity", "agent-g")}, set()))
    assert cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)]) == 0
    assert place.path.exists()


def test_gc_yes_is_refused_while_the_service_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path, place = revoked_clone(tmp_path, monkeypatch)
    lock = serve.hold_lock(tmp_path / "st")
    try:
        code = cli.main(["runner", "gc", "--revoked", "--yes", "--config", str(path)])
    finally:
        lock.close()
    assert code == cli.EXIT_USAGE and place.path.exists()


def test_logs_on_a_terminal_show_escapes_instead_of_running_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = setup(tmp_path)
    logs = tmp_path / "st" / supervisor.LOGS
    logs.mkdir()
    (logs / "plc-0003.log").write_bytes(b"ok\n\x1b]52;c;ZXZpbA==\x07\n")
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    assert cli.main(["runner", "logs", "plc-0003", "--config", str(path)]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\\x1b]52" in out


def test_an_exact_placement_id_wins_over_a_handle(tmp_path: Path) -> None:
    path = setup(tmp_path)
    state.save_state(
        tmp_path / "st",
        {"placements": [{"id": "plc-0003", "agent": "plc-0004"}, {"id": "plc-0004", "agent": "x"}]},
        name=serve.STATUS_FILE,
    )
    cfg = config.load(path)
    assert operate._placement_id(cfg, "plc-0004") == "plc-0004"


def test_only_an_exact_credential_revoked_code_counts(monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:  # fmt: skip
    place = workspace.Workspace(tmp_path, "maity", "c")
    (tmp_path / ".git" / "maity").mkdir(parents=True)
    (tmp_path / ".git" / "maity" / "credential").write_text("mty1.x.y")

    def answer(stderr: str) -> Any:
        return lambda *a, **k: subprocess.CompletedProcess([], 1, "", stderr)

    monkeypatch.setattr(
        "maity.runner.operate.subprocess.run",
        answer("maity: GET /api/v1/me: credential_revoked: revoked"),
    )
    assert operate.credential_revoked(place)
    monkeypatch.setattr(
        "maity.runner.operate.subprocess.run", answer("maity: hub says the credential_revoked flag")
    )
    assert not operate.credential_revoked(place)
