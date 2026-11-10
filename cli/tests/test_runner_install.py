"""`maity runner install` / `uninstall` against a fake host: no root, no systemd."""

from __future__ import annotations

import argparse
import tomllib
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from maity import cli, state
from maity.runner import install

URL = "https://hub.example.org/r/tok-abc"

COMPLETE = """\
[hub]
url = "https://hub.example.org"
state_dir = "{state_dir}"

[limits]
projects = ["oliver/maity"]
repositories = ["github.com/oliver-zehentleitner/maity"]

[harness.stub]
"""


class FakeHost(install.Host):
    def __init__(
        self, root: Path, os: str = "linux", uid: int = 0, missing: frozenset[str] = frozenset()
    ) -> None:
        super().__init__(root)
        (root / "run/systemd/system").mkdir(parents=True)
        self.calls: list[tuple[list[str], str | None]] = []
        self.users: dict[str, tuple[int, int]] = {}
        self.failing: set[str] = set()
        self.os = os
        self.uid = uid
        self.missing = missing

    def platform(self) -> str:
        return self.os

    def euid(self) -> int:
        return self.uid

    def which(self, name: str) -> str | None:
        return None if name in self.missing else f"/usr/bin/{name}"

    def user_ids(self, name: str) -> tuple[int, int] | None:
        return self.users.get(name)

    def chown(self, path: Path, uid: int, gid: int) -> None:
        pass

    def maity(self) -> list[str]:
        return ["/opt/pipx/venvs/maity/bin/python", "-I", "-m", "maity"]

    def run(self, argv: Sequence[str], stdin: str | None = None) -> int:
        argv = list(argv)
        self.calls.append((argv, stdin))
        if argv[0] == "useradd":
            self.users[argv[-1]] = (990, 990)
        if argv[0] == "userdel":
            self.users.pop(argv[-1], None)
        if "pair" in argv:
            # What the real pair does: the credential under the configured state_dir.
            (self.path(install.STATE_DIR) / "credential").write_text("x")
        return 1 if any(word in self.failing for word in argv) else 0

    def commands(self) -> list[str]:
        return [" ".join(argv) for argv, _ in self.calls]


def args(**kw: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "url": URL,
        "code": "K3PF-9QZD-1MWA",
        "code_file": None,
        "config": None,
        "force": False,
        "purge": False,
    }
    base.update(kw)
    return argparse.Namespace(**base)


def complete_config(host: FakeHost) -> None:
    path = host.path(install.CONFIG)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(COMPLETE.format(state_dir=host.path(install.STATE_DIR)))


def test_install_on_a_fresh_machine_does_every_step_in_order(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    assert install.cmd_install(args(), host) == 0
    run = host.commands()
    assert run[0].startswith("useradd --system --create-home --home-dir /var/lib/maity-runner")
    as_user = "runuser -u maity-runner -- env HOME=/var/lib/maity-runner "
    maity = "/opt/pipx/venvs/maity/bin/python -I -m maity"
    assert run[1:] == [
        f"{as_user}{maity} --version",
        f"{as_user}{maity} runner pair {URL} --code-file - --config /etc/maity-runner/runner.toml",
        "systemctl daemon-reload",
        "systemctl enable --now maity-runner",
        f"{as_user}{maity} runner check --config /etc/maity-runner/runner.toml",
    ]
    # The code goes to pair on stdin, never on a command line.
    assert host.calls[2][1] == "K3PF-9QZD-1MWA"
    assert all("K3PF" not in line for line in run)
    for directory in (install.HOME, install.STATE_DIR, install.WORKSPACES):
        assert (host.path(directory).stat().st_mode & 0o777) == 0o700


def test_the_unit_starts_the_maity_that_ran_install(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    unit = host.path(install.UNIT_PATH).read_text()
    assert (
        "ExecStart=/opt/pipx/venvs/maity/bin/python -I -m maity runner serve "
        "--config /etc/maity-runner/runner.toml\n" in unit
    )
    assert "/usr/local/bin/maity runner serve" not in unit.split("[Unit]")[1]
    assert "KillMode=process" in unit and "RestartPreventExitStatus=78" in unit
    assert "User=maity-runner" in unit


def test_an_incomplete_configuration_enables_but_does_not_start(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = FakeHost(tmp_path)
    assert install.cmd_install(args(), host) == 0
    written = tomllib.loads(host.path(install.CONFIG).read_text())
    assert written["hub"] == {"url": "https://hub.example.org", "state_dir": str(install.STATE_DIR)}
    assert written["backend"] == {"local": {"workspaces": str(install.WORKSPACES)}}
    run = host.commands()
    assert "systemctl enable maity-runner" in run
    assert not any("--now" in line or "runner check" in line for line in run)
    err = capsys.readouterr().err
    assert "not started" in err and "harness" in err and "systemctl start maity-runner" in err


def test_existing_files_are_kept_unless_force(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    before = host.path(install.CONFIG).read_text()
    host.path(install.UNIT_PATH).parent.mkdir(parents=True)
    host.path(install.UNIT_PATH).write_text("# the operator's own unit\n")
    install.cmd_install(args(), host)
    assert host.path(install.CONFIG).read_text() == before
    assert host.path(install.UNIT_PATH).read_text() == "# the operator's own unit\n"
    install.cmd_install(args(force=True), host)
    assert host.path(install.CONFIG).read_text() == install.starter_config(
        "https://hub.example.org"
    )
    assert "ExecStart=/opt/pipx" in host.path(install.UNIT_PATH).read_text()


def test_a_second_install_skips_what_is_done_and_needs_no_code(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    host.calls.clear()
    assert install.cmd_install(args(code=None), host) == 0
    run = host.commands()
    assert not any(line.startswith("useradd") or " pair " in line for line in run)
    assert "systemctl enable --now maity-runner" in run


@pytest.mark.parametrize(
    ("kw", "said"),
    [
        ({"os": "darwin"}, "Linux only"),
        ({"uid": 1000}, "run it with sudo"),
        ({"missing": frozenset({"systemctl"})}, "systemd is not running"),
        ({"missing": frozenset({"tmux"})}, "`tmux` is not installed"),
    ],
)
def test_install_refuses_before_changing_anything(
    tmp_path: Path, kw: dict[str, Any], said: str
) -> None:
    host = FakeHost(tmp_path, **kw)
    with pytest.raises(install.Refused, match=said):
        install.cmd_install(args(), host)
    assert host.calls == []
    assert not host.path(install.CONFIG).exists()


def test_a_maity_the_service_user_cannot_run_is_refused_before_pairing(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.failing = {"--version"}
    with pytest.raises(install.Refused, match="pipx install --global"):
        install.cmd_install(args(), host)
    assert not any(" pair " in line for line in host.commands())
    assert not host.path(install.UNIT_PATH).exists()


def test_a_failed_pairing_starts_nothing(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    host.failing = {"pair"}
    with pytest.raises(install.Refused, match="pairing failed"):
        install.cmd_install(args(), host)
    assert not any(line.startswith("systemctl") for line in host.commands())


def test_install_without_a_code_and_unpaired_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    with pytest.raises(install.Refused, match="pairing code is empty"):
        install.cmd_install(args(code=None), host)
    assert host.calls == []


def test_uninstall_keeps_state_and_user(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    host.calls.clear()
    assert install.cmd_uninstall(args(), host) == 0
    run = host.commands()
    assert run[0] == "systemctl disable --now maity-runner"
    assert "runner stop-all --config /etc/maity-runner/runner.toml" in run[1]
    assert run[2] == "systemctl daemon-reload"
    assert not host.path(install.UNIT_PATH).exists()
    assert state.has_credential(host.path(install.STATE_DIR))
    assert host.path(install.CONFIG).exists()
    assert "maity-runner" in host.users


def test_uninstall_purge_removes_state_configuration_and_user(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    assert install.cmd_uninstall(args(purge=True), host) == 0
    assert not host.path(install.HOME).exists()
    assert not host.path(install.CONFIG.parent).exists()
    assert "maity-runner" not in host.users
    assert host.commands()[-1] == "userdel maity-runner"


def test_purge_with_config_removes_only_that_file(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    other = Path("/etc/runners/mine.toml")
    neighbour = host.path(other.parent / "keep.toml")
    neighbour.parent.mkdir(parents=True)
    neighbour.write_text("")
    host.path(other).write_text("")
    install.cmd_uninstall(args(purge=True, config=str(other)), host)
    assert not host.path(other).exists()
    assert neighbour.exists()


def test_uninstall_refuses_without_root(tmp_path: Path) -> None:
    host = FakeHost(tmp_path, uid=1000)
    with pytest.raises(install.Refused, match="sudo"):
        install.cmd_uninstall(args(), host)


def test_the_cli_maps_a_refusal_to_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(install.Host, "euid", lambda self: 1000)
    monkeypatch.setattr(install.Host, "platform", lambda self: "linux")
    monkeypatch.setattr(install.Host, "systemd_running", lambda self: True)
    assert cli.main(["runner", "install", URL, "--code", "X"]) == 2
    assert "sudo" in capsys.readouterr().err
