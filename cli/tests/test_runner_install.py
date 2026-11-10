"""`maity runner install` / `uninstall` against a fake host: no root, no systemd."""

from __future__ import annotations

import argparse
import os
import tomllib
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from maity import cli, state
from maity.runner import install

URL = "https://hub.example.org/r/tok-abc"

COMPLETE = """\
[hub]
url = "https://hub.example.org"
state_dir = "/var/lib/maity-runner/state"

[limits]
projects = ["oliver/maity"]
repositories = ["github.com/oliver-zehentleitner/maity"]

[harness.stub]
"""


@pytest.fixture(autouse=True)
def root_umask() -> Iterator[None]:
    """Root's usual umask: directories the tests make for the host are not group-writable."""
    previous = os.umask(0o022)
    yield
    os.umask(previous)


class FakeHost(install.Host):
    def __init__(
        self, root: Path, os: str = "linux", uid: int = 0, missing: frozenset[str] = frozenset()
    ) -> None:
        super().__init__(root)
        (root / "run/systemd/system").mkdir(parents=True)
        self.calls: list[tuple[list[str], str | None]] = []
        self.users: dict[str, install.User] = {}
        self.failing: set[str] = set()
        self.chowned: list[str] = []
        self.maity_words = ["/opt/pipx/venvs/maity/bin/python", "-I", "-m", "maity"]
        self.os = os
        self.uid = uid
        self.missing = missing

    def platform(self) -> str:
        return self.os

    def euid(self) -> int:
        return self.uid

    def which(self, name: str) -> str | None:
        return None if name in self.missing else f"/usr/bin/{name}"

    def root_uid(self) -> int:
        return os.getuid()

    def user(self, name: str) -> install.User | None:
        return self.users.get(name)

    def fchown(self, fd: int, uid: int, gid: int) -> None:
        self.chowned.append(os.readlink(f"/proc/self/fd/{fd}"))

    def maity(self) -> list[str]:
        return list(self.maity_words)

    def run(self, argv: Sequence[str], stdin: str | None = None) -> int:
        argv = list(argv)
        self.calls.append((argv, stdin))
        if argv[0] == "useradd":
            self.users[argv[-1]] = install.User(990, 990, str(install.HOME))
            self.path(install.HOME).mkdir(parents=True)
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
    path.write_text(COMPLETE)


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
        'ExecStart="/opt/pipx/venvs/maity/bin/python" "-I" "-m" "maity" "runner" "serve" '
        '"--config" "/etc/maity-runner/runner.toml"\n' in unit
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
    assert 'ExecStart="/opt/pipx' in host.path(install.UNIT_PATH).read_text()


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
    host.path(install.HOME).mkdir(parents=True)
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


def test_the_unit_names_the_configuration_given_and_quotes_every_word(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.maity_words = ['/opt/my tools/100%/$HOME/py\\th"on', "-I", "-m", "maity"]
    install.cmd_install(args(config="/etc/runners/main.toml"), host)
    line = next(
        x for x in host.path(install.UNIT_PATH).read_text().splitlines() if x.startswith("Exec")
    )
    assert line == (
        'ExecStart="/opt/my tools/100%%/$$HOME/py\\\\th\\"on" "-I" "-m" "maity" "runner" '
        '"serve" "--config" "/etc/runners/main.toml"'
    )


def test_a_control_character_in_a_path_is_refused_before_any_change(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.maity_words = ["/opt/py\nExecStartPre=/bin/evil", "-I", "-m", "maity"]
    with pytest.raises(install.Refused, match="control character"):
        install.cmd_install(args(), host)
    assert host.calls == []


@pytest.mark.parametrize("given", ["runner.toml", "~/runner.toml", "../x.toml"])
def test_a_relative_config_is_refused_before_any_change(tmp_path: Path, given: str) -> None:
    for command in (install.cmd_install, install.cmd_uninstall):
        host = FakeHost(tmp_path / command.__name__ / given.replace("/", "_"))
        with pytest.raises(install.Refused, match="absolute path"):
            command(args(config=given), host)
        assert host.calls == []


def test_a_link_in_the_service_users_home_is_not_followed(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    # The service user (or an agent) swaps its state directory for a link to root's files.
    victim = tmp_path / "etc" / "shadow-dir"
    victim.mkdir()
    victim.chmod(0o755)
    state_dir = host.path(install.STATE_DIR)
    for child in state_dir.iterdir():
        child.unlink()
    state_dir.rmdir()
    state_dir.symlink_to(victim)
    host.chowned.clear()
    with pytest.raises(install.Refused, match="is a link or not a directory"):
        install.cmd_install(args(), host)
    assert str(victim) not in host.chowned
    assert (victim.stat().st_mode & 0o777) == 0o755


def test_a_home_without_its_user_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.path(install.HOME).mkdir(parents=True)
    with pytest.raises(install.Refused, match="move it away"):
        install.cmd_install(args(), host)
    assert not any(line.startswith("useradd") for line in host.commands())


def test_a_link_at_the_configuration_is_refused_and_its_target_untouched(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    target = tmp_path / "elsewhere.txt"
    link = host.path(install.CONFIG)
    link.parent.mkdir(parents=True)
    link.symlink_to(target)  # dangling: exists() is False, but it would be followed
    with pytest.raises(install.Refused, match="link or not a regular file"):
        install.cmd_install(args(force=True), host)
    assert not target.exists()


def test_a_configuration_directory_others_can_write_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    directory = host.path(install.CONFIG.parent)
    directory.mkdir(parents=True)
    directory.chmod(0o777)
    with pytest.raises(install.Refused, match="writable by group or others"):
        install.cmd_install(args(), host)


def test_force_replaces_the_file_instead_of_writing_through_it(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    path = host.path(install.CONFIG)
    before = path.stat().st_ino
    path.write_text("# changed\n")
    install.cmd_install(args(code=None, force=True), host)
    assert path.stat().st_ino != before
    assert (path.stat().st_mode & 0o777) == 0o644
    assert not [p for p in path.parent.iterdir() if p.name.startswith(".")]


def test_an_unsupported_key_is_incomplete_too(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    path = host.path(install.CONFIG)
    path.write_text(path.read_text() + '\n[backend.local]\nmemory_max = "2G"\n')
    install.cmd_install(args(), host)
    assert "systemctl enable maity-runner" in host.commands()


def test_paired_is_read_from_the_configured_state_dir(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    config_path = Path("/etc/runners/main.toml")
    host.path(config_path).parent.mkdir(parents=True)
    host.path(config_path).write_text(
        COMPLETE.replace("/var/lib/maity-runner/state", "/srv/runner-state")
    )
    (host.path(Path("/srv/runner-state"))).mkdir(parents=True)
    (host.path(Path("/srv/runner-state")) / "credential").write_text("x")
    assert install.cmd_install(args(code=None, config=str(config_path)), host) == 0
    assert not any(" pair " in line for line in host.commands())


def test_an_unreadable_code_file_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    with pytest.raises(install.Refused, match="cannot be read"):
        install.cmd_install(args(code=None, code_file=str(tmp_path / "missing")), host)
    assert host.calls == []


def test_uninstall_does_not_run_stop_all_on_a_configuration_that_does_not_load(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)  # the starter configuration: no limits, no harness
    host.calls.clear()
    install.cmd_uninstall(args(), host)
    assert not any("stop-all" in line for line in host.commands())
    assert "does not load" in capsys.readouterr().err


def test_purge_removes_a_link_at_home_but_not_what_it_points_to(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    kept = tmp_path / "precious"
    kept.mkdir()
    (kept / "file").write_text("x")
    home = host.path(install.HOME)
    import shutil

    shutil.rmtree(home)
    home.symlink_to(kept)
    install.cmd_uninstall(args(purge=True), host)
    assert not os.path.lexists(home)
    assert (kept / "file").exists()


def test_purge_refuses_a_config_that_is_a_directory(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    directory = host.path(Path("/etc/runners"))
    directory.mkdir(parents=True)
    with pytest.raises(install.Refused, match="not what install made"):
        install.cmd_uninstall(args(purge=True, config="/etc/runners"), host)
    assert directory.is_dir()


def test_purge_leaves_a_user_install_did_not_make(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.users[install.USER] = install.User(990, 990, "/home/maity-runner")
    with pytest.raises(install.Refused, match="not install's"):
        install.cmd_uninstall(args(purge=True), host)
    assert host.calls == []
