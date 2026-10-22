from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from maity import cli
from maity.runner import capabilities, config, operate, supervisor, tmux
from maity.runner.asuser import AsUser

CONFIG = """\
[hub]
url = "https://hub.example"
state_dir = "{root}/st"

[limits]
projects = ["maity"]
repositories = ["github.com/oliver-zehentleitner/*"]

[backend.local]
workspaces = "{root}/ws"
layout = "agent_user"
agent_user = "maity-agent"
tmux_socket = "{root}/agent-home/.maity-runner/tmux.sock"

[harness.stub]
"""


@pytest.fixture
def fake_sudo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A sudo that records its arguments and runs the command after `--` as ourselves."""
    bin_dir = tmp_path / "sbin"
    bin_dir.mkdir()
    log = tmp_path / "sudo.log"
    script = bin_dir / "sudo"
    script.write_text(
        f'#!/bin/sh\necho "$*" >> {log}\nwhile [ "$1" != "--" ]; do shift; done\nshift\n'
        'exec "$@"\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    return log


def load(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> config.Config:
    monkeypatch.setattr(config, "home_of", lambda user: tmp_path / "agent-home")
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(root=tmp_path))
    (tmp_path / "st").mkdir(mode=0o700, exist_ok=True)
    return config.load(path)


def test_the_agents_side_lives_in_the_agent_users_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load(tmp_path, monkeypatch)
    assert cfg.local is not None
    assert cfg.local.agent_files == tmp_path / "agent-home" / ".maity-runner"
    assert config.unsupported(cfg) == []


def test_commands_go_through_sudo_with_only_the_environment_they_need() -> None:
    as_user = AsUser("maity-agent")
    assert as_user.argv(["maity", "join"], {"MAITY_STATE_DIR": "/c/.git/maity"}) == [
        "sudo", "-n", "-u", "maity-agent", "--", "env", "MAITY_STATE_DIR=/c/.git/maity",
        "maity", "join",
    ]  # fmt: skip
    assert AsUser().argv(["true"]) == ["true"]


def test_tmux_runs_as_the_agents_user(tmp_path: Path, fake_sudo: Path) -> None:
    calls: list[list[str]] = []

    def run(argv: Sequence[str]) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return subprocess.CompletedProcess(list(argv), 0, "", "")

    home = tmp_path / "agent-home" / ".maity-runner"
    backend = tmux.Tmux(home / "tmux.sock", home / "tmux.conf", str(tmp_path / "agent-home"),
                        "/usr/bin:/bin", home / "logs", run=run,
                        as_user=AsUser("maity-agent"))  # fmt: skip
    backend.start("maity_maity_agent-3", tmp_path, ["stub"], {}, "plc-0003", 1)
    assert calls[0][:7] == ["sudo", "-n", "-u", "maity-agent", "--", "env", "-i"]
    assert all(call[:5] == ["sudo", "-n", "-u", "maity-agent", "--"] for call in calls)
    assert (home / "tmux.conf").read_text().startswith("set -g update-environment")
    assert "install -D -m 600 /dev/stdin" in fake_sudo.read_text()


def test_the_runner_files_stay_the_runners(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_sudo: Path
) -> None:
    """The agent files go to the agent's home; the credential and state stay in state_dir."""
    from test_supervisor import FakeTmux, placement

    cfg = load(tmp_path, monkeypatch)
    sup = supervisor.Supervisor(cfg, FakeTmux(), None, print, {})  # type: ignore[arg-type]
    assert sup.as_user.user == "maity-agent"
    ctx = sup._context(placement(), cfg.harnesses["stub"], workspace_for(cfg))
    assert ctx.agent_dir == tmp_path / "agent-home" / ".maity-runner" / "agents" / "plc-0003"
    assert ctx.agent_dir.is_dir() and ctx.as_user.user == "maity-agent"


def workspace_for(cfg: config.Config) -> Any:
    from maity.runner import workspace

    assert cfg.local is not None
    return workspace.locate(cfg.local.workspaces, "maity", "agent-3")


def test_the_join_runs_as_the_agents_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen["argv"], seen["env"], seen["cwd"] = command, kwargs["env"], kwargs["cwd"]
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("maity.runner.supervisor.subprocess.run", fake_run)
    from maity.runner import workspace

    place = workspace.Workspace(tmp_path / "c", "maity", "c")
    assert supervisor.run_join(place, "https://h/j/T", "C", tmp_path, AsUser("maity-agent")) == (
        True, None
    )  # fmt: skip
    argv = seen["argv"]
    assert argv[:5] == ["sudo", "-n", "-u", "maity-agent", "--"]
    assert argv[5:7] == ["env", f"MAITY_STATE_DIR={place.credential.parent}"]
    assert seen["env"] is None and seen["cwd"] == Path("/")  # sudo resets the environment


def test_capabilities_say_the_runner_is_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = load(tmp_path, monkeypatch)
    isolation = capabilities.build(cfg, {"stub": capabilities.Probe(None, None, None)})["targets"][
        0
    ]["isolation"]
    assert isolation == {"kind": "shared_user", "user": "maity-agent", "runner_separate": True}


def test_check_reports_a_missing_sudoers_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_sudo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    load(tmp_path, monkeypatch)
    (fake_sudo.parent / "sbin" / "sudo").write_text("#!/bin/sh\nexit 1\n")
    code = cli.main(["runner", "check", "--offline", "--config", str(tmp_path / "runner.toml")])
    assert code == 1
    assert "needs a sudoers rule" in capsys.readouterr().out


def test_check_passes_the_agent_user_prerequisites(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_sudo: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:  # fmt: skip
    load(tmp_path, monkeypatch)
    (tmp_path / "ws").mkdir()
    (tmp_path / "agent-home").mkdir()
    cli.main(["runner", "check", "--offline", "--config", str(tmp_path / "runner.toml")])
    out = capsys.readouterr().out
    assert "ok     sudo to maity-agent" in out
    assert "ok     maity-agent can run maity" in out
    assert f"ok     workspaces {tmp_path / 'ws'} (as maity-agent)" in out


def test_logs_are_read_as_the_agents_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_sudo: Path,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:  # fmt: skip
    from maity import state
    from maity.runner import serve

    cfg = load(tmp_path, monkeypatch)
    assert cfg.local is not None
    logs = cfg.local.agent_files / supervisor.LOGS
    logs.mkdir(parents=True)
    (logs / "plc-0003.log").write_bytes(b"hello\n")
    state.save_state(cfg.state_dir, {"placements": [{"id": "plc-0003", "agent": "agent-3"}]},
                     name=serve.STATUS_FILE)  # fmt: skip
    assert (
        operate.cmd_logs(cfg, type("A", (), {"which": "agent-3", "follow": False, "raw": True})())
        == 0
    )
    assert capsysbinary.readouterr().out == b"hello\n"
    assert "cat --" in fake_sudo.read_text()


def test_a_clones_git_directory_is_listed_as_the_agents_user(
    tmp_path: Path, fake_sudo: Path
) -> None:
    dot_git = tmp_path / "c" / ".git"
    (dot_git / "info").mkdir(parents=True)
    (dot_git / "config").write_text("[core]\n")
    (dot_git / "commondir").symlink_to("/elsewhere")
    as_user = AsUser("maity-agent")
    assert sorted(as_user.tree(dot_git)) == sorted(AsUser().tree(dot_git)) == [
        ("commondir", "l", len("/elsewhere")), ("config", "f", 7), ("info", "d", 4096),
    ]  # fmt: skip
    assert "find" in fake_sudo.read_text()
    assert operate.not_inspectable(tmp_path / "c", as_user) == ".git/commondir is a symlink"
