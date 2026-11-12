"""`maity runner install` / `uninstall` against a fake host: no root, no systemd."""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterator, Sequence
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
            comment = argv[argv.index("--comment") + 1]
            uid, gid = os.getuid(), os.getgid()  # what the test can own, standing in for 990
            self.users[argv[-1]] = install.User(uid, gid, str(install.HOME), comment)
            self.path(install.HOME).mkdir(parents=True)
        if argv[0] == "userdel" and "userdel" not in self.failing:
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
        "runuser -u maity-runner -- test -r /etc/maity-runner/runner.toml",
        f"{as_user}{maity} runner pair {URL} --code-file - --config /etc/maity-runner/runner.toml",
        "systemctl daemon-reload",
        "systemctl enable --now maity-runner",
        f"{as_user}{maity} runner check --config /etc/maity-runner/runner.toml",
    ]
    # The code goes to pair on stdin, never on a command line.
    assert host.calls[3][1] == "K3PF-9QZD-1MWA"
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
    # ProtectSystem=strict leaves /tmp read-only unless named: harnesses write there.
    assert "ProtectSystem=strict" in unit
    assert "\nReadWritePaths=/var/lib/maity-runner /tmp\n" in unit
    assert "PrivateTmp" not in unit.split("[Service]")[1].replace("# No PrivateTmp", "")


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
        ({"os": "darwin"}, "Linux only; elsewhere, macOS included, run `maity runner serve`"),
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


def test_the_unit_quotes_every_word(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.maity_words = ['/opt/my tools/100%/$HOME/py\\th"on', "-I", "-m", "maity"]
    install.cmd_install(args(), host)
    line = next(
        x for x in host.path(install.UNIT_PATH).read_text().splitlines() if x.startswith("Exec")
    )
    assert line == (
        'ExecStart="/opt/my tools/100%%/$$HOME/py\\\\th\\"on" "-I" "-m" "maity" "runner" '
        '"serve" "--config" "/etc/maity-runner/runner.toml"'
    )


def test_a_control_character_in_a_path_is_refused_before_any_change(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.maity_words = ["/opt/py\nExecStartPre=/bin/evil", "-I", "-m", "maity"]
    with pytest.raises(install.Refused, match="control character"):
        install.cmd_install(args(), host)
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


@pytest.mark.parametrize("code", [None, "K3PF-9QZD-1MWA"])
def test_a_credential_linked_to_a_root_file_is_refused_not_read(
    tmp_path: Path, code: str | None
) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    sentinel = tmp_path / "root-only" / "secret"
    sentinel.parent.mkdir(mode=0o700)
    sentinel.write_text("root's")
    credential = host.path(install.STATE_DIR) / "credential"
    credential.unlink()
    credential.symlink_to(sentinel)
    host.calls.clear()
    with pytest.raises(install.Refused, match="credential is a link"):
        install.cmd_install(args(code=code), host)
    assert host.calls == []
    assert sentinel.read_text() == "root's"


def test_a_linked_state_dir_without_a_code_is_refused_as_a_link(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()  # no credential there: a plain read would ask for a code instead
    state_dir = host.path(install.STATE_DIR)
    (state_dir / "credential").unlink()
    state_dir.rmdir()
    state_dir.symlink_to(elsewhere)
    host.calls.clear()
    with pytest.raises(install.Refused, match="is a link or not a directory"):
        install.cmd_install(args(code=None), host)
    assert host.calls == []


def test_uninstall_refuses_a_linked_configuration_and_never_reads_it(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    target = tmp_path / "operators.toml"
    target.write_text(COMPLETE)
    config_file = host.path(install.CONFIG)
    config_file.unlink()
    config_file.symlink_to(target)
    host.calls.clear()
    with pytest.raises(install.Refused, match="is a link, not a regular file"):
        install.cmd_uninstall(args(purge=True), host)
    assert host.calls == []
    # --force goes on without reading it: no stop-all on it, the link goes, not its target.
    assert install.cmd_uninstall(args(purge=True, force=True), host) == 0
    assert not any("stop-all" in line for line in host.commands())
    assert not os.path.lexists(config_file) and target.read_text() == COMPLETE


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
    with pytest.raises(install.Refused, match="not a regular file of root's"):
        install.cmd_install(args(force=True), host)
    assert not target.exists()
    assert host.calls == []


@pytest.mark.parametrize("directory", ["/etc", "/etc/maity-runner", "/var/lib"])
def test_a_directory_on_the_way_others_can_write_is_refused(tmp_path: Path, directory: str) -> None:
    host = FakeHost(tmp_path)
    for made in ("/etc/maity-runner", "/var/lib"):
        host.path(Path(made)).mkdir(parents=True)
    host.path(Path(directory)).chmod(0o777)
    with pytest.raises(install.Refused, match="writable by group or others"):
        install.cmd_install(args(), host)
    assert host.calls == []
    assert not host.path(install.CONFIG).exists()


@pytest.mark.parametrize("directory", ["/etc/maity-runner", "/var/lib", "/etc/systemd"])
def test_a_link_on_the_way_is_refused_before_any_change(tmp_path: Path, directory: str) -> None:
    host = FakeHost(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    link = host.path(Path(directory))
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(elsewhere)
    with pytest.raises(install.Refused, match="is a link or not a directory"):
        install.cmd_install(args(), host)
    assert host.calls == []
    assert list(elsewhere.iterdir()) == []


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


def srv_state(host: FakeHost) -> None:
    """A kept configuration whose credential is under /srv."""
    host.path(install.CONFIG).parent.mkdir(parents=True)
    host.path(install.CONFIG).write_text(
        COMPLETE.replace("/var/lib/maity-runner/state", "/srv/runner-state")
    )
    (host.path(Path("/srv/runner-state"))).mkdir(parents=True)
    (host.path(Path("/srv/runner-state")) / "credential").write_text("x")


def test_a_kept_configuration_with_another_state_dir_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    srv_state(host)
    with pytest.raises(install.Refused, match="install uses only /var/lib/maity-runner/state"):
        install.cmd_install(args(code=None), host)
    assert host.calls == []


def test_a_forced_configuration_is_paired_against_its_own_state_dir(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    srv_state(host)
    # --force writes install's own configuration, whose state_dir holds no credential.
    with pytest.raises(install.Refused, match="pairing code is empty"):
        install.cmd_install(args(code=None, force=True), host)
    assert host.calls == []
    assert "/srv/runner-state" in host.path(install.CONFIG).read_text()


def test_a_state_dir_under_home_is_resolved_as_serve_does(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)  # paired: the credential is in /var/lib/maity-runner/state
    host.path(install.CONFIG).write_text(
        COMPLETE.replace('"/var/lib/maity-runner/state"', '"~/state"')
    )
    host.calls.clear()
    assert install.cmd_install(args(code=None), host) == 0
    assert not any(" pair " in line for line in host.commands())


def test_a_relative_state_dir_is_refused_before_any_change(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.path(install.CONFIG).parent.mkdir(parents=True)
    host.path(install.CONFIG).write_text(COMPLETE.replace('"/var/lib/maity-runner/state"', '"st"'))
    with pytest.raises(install.Refused, match="not absolute"):
        install.cmd_install(args(), host)
    assert host.calls == []


@pytest.mark.parametrize(
    "url, refusal",
    [
        ('"https://other.example.org"', "is for the hub https://other.example.org"),
        ('"ftp://hub.example.org"', "hub.url is not a hub URL"),
        (None, "names no hub.url"),
    ],
    ids=["another-hub", "not-a-hub-url", "no-url"],
)
def test_a_kept_configuration_for_another_hub_is_refused_before_any_change(
    tmp_path: Path, url: str | None, refusal: str
) -> None:
    """Found at `pair` it would come after the account, the record and the unit."""
    host = FakeHost(tmp_path)
    host.path(install.CONFIG).parent.mkdir(parents=True)
    old = 'url = "https://hub.example.org"\n'
    host.path(install.CONFIG).write_text(
        COMPLETE.replace(old, "" if url is None else f"url = {url}\n")
    )
    with pytest.raises(install.Refused, match=refusal):
        install.cmd_install(args(), host)
    assert host.calls == []
    assert not host.path(install.RECORD).exists()
    assert not host.path(install.UNIT_PATH).exists()


def test_force_does_not_pair_over_another_hub_s_credential(tmp_path: Path) -> None:
    """--force writes this hub's configuration, but a paired runner keeps its credential:
    serve would then refuse one another hub issued, so install refuses first."""
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)  # paired with hub.example.org
    host.calls.clear()
    other = args(url="https://other.example.org/r/tok-xyz", force=True)
    with pytest.raises(install.Refused, match="--force does not pair over it"):
        install.cmd_install(other, host)
    assert host.calls == []
    assert "https://hub.example.org" in host.path(install.CONFIG).read_text()


def test_a_url_that_is_not_utf_8_is_refused_before_any_change(tmp_path: Path) -> None:
    """What Python makes of invalid UTF-8 on argv: a lone surrogate, which no file takes."""
    host = FakeHost(tmp_path)
    with pytest.raises(install.Refused, match="not valid UTF-8"):
        install.cmd_install(args(url="https://h\udcff.example/r/tok-abc"), host)
    assert host.calls == []
    assert not host.path(install.RECORD).exists()


def test_the_starter_configuration_quotes_any_url_as_toml_reads_it() -> None:
    """`json.dumps` would write the non-BMP character as a surrogate pair, which TOML refuses."""
    url = 'https://h\U0001f600.example/a"b\\c\x7f'
    assert tomllib.loads(install.starter_config(url))["hub"]["url"] == url


def test_a_purge_without_install_s_account_or_record_keeps_etc_maity_runner(
    tmp_path: Path,
) -> None:
    """Nothing shows install made /etc/maity-runner: refused before any change, as for HOME."""
    host = FakeHost(tmp_path)
    complete_config(host)
    other = host.path(install.CONFIG.parent / "other.conf")
    other.write_text("someone else's\n")
    with pytest.raises(install.Refused, match="/etc/maity-runner exists, but install made no"):
        install.cmd_uninstall(args(purge=True), host)
    assert host.calls == []
    assert other.read_text() == "someone else's\n"
    assert host.path(install.CONFIG).is_file()


def test_an_unreadable_code_file_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    with pytest.raises(install.Refused, match="cannot be read"):
        install.cmd_install(args(code=None, code_file=str(tmp_path / "missing")), host)
    assert host.calls == []


@pytest.mark.parametrize("broken", ["missing", "does not load"])
def test_agents_that_cannot_be_stopped_stop_the_removal(tmp_path: Path, broken: str) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    if broken == "missing":
        host.path(install.CONFIG).unlink()
    else:
        host.path(install.CONFIG).write_text("[hub]\n")
    host.calls.clear()
    with pytest.raises(install.Refused, match=f"{broken}.*nothing was removed"):
        install.cmd_uninstall(args(purge=True), host)
    # Known before the first change: the service is not even disabled (e5kk R3 F1).
    assert host.calls == []
    assert host.path(install.UNIT_PATH).exists() and host.path(install.HOME).is_dir()
    assert install.USER in host.users
    # --force goes on, as after a failed stop-all.
    assert install.cmd_uninstall(args(purge=True, force=True), host) == 0
    assert not host.path(install.HOME).exists()


def test_purge_refuses_a_link_at_home_and_leaves_what_it_points_to(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    kept = tmp_path / "precious"
    kept.mkdir()
    (kept / "file").write_text("x")
    home = host.path(install.HOME)
    import shutil

    shutil.rmtree(home)
    home.symlink_to(kept)
    host.calls.clear()
    with pytest.raises(install.Refused, match="is a link or not a directory"):
        install.cmd_uninstall(args(purge=True), host)
    assert host.calls == []
    assert (kept / "file").exists()


def test_purge_refuses_a_config_that_is_a_directory(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    directory = host.path(install.CONFIG)
    directory.mkdir(parents=True)
    host.path(install.UNIT_PATH).parent.mkdir(parents=True)
    host.path(install.UNIT_PATH).write_text("unit")
    with pytest.raises(install.Refused, match="not a regular file of root's"):
        install.cmd_uninstall(args(purge=True), host)
    assert directory.is_dir()
    assert host.calls == []  # refused before the service was touched
    assert host.path(install.UNIT_PATH).exists()


def test_purge_leaves_a_user_install_did_not_make(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.users[install.USER] = install.User(990, 990, "/home/maity-runner", "")
    with pytest.raises(install.Refused, match="not made by install"):
        install.cmd_uninstall(args(purge=True), host)
    assert host.calls == []


def test_an_account_without_root_s_record_is_not_taken_over(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    # install's home and the comment an earlier version took as proof, which an account's
    # owner can set where users may change their full name: still not install's.
    forged = "Maity runner (made by maity runner install)"
    host.users[install.USER] = install.User(990, 990, str(install.HOME), forged)
    host.path(install.HOME).mkdir(parents=True)
    with pytest.raises(install.Refused, match="install did not make"):
        install.cmd_install(args(), host)
    with pytest.raises(install.Refused, match="not made by install"):
        install.cmd_uninstall(args(purge=True), host)
    assert not any(line.startswith("userdel") for line in host.commands())
    assert host.path(install.HOME).is_dir()


def test_install_records_the_account_it_makes(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    record = json.loads(host.path(install.RECORD).read_text())
    assert record["uid"] == host.users[install.USER].uid and record["home"] == str(install.HOME)
    assert (host.path(install.RECORD).stat().st_mode & 0o777) == 0o644
    install.cmd_uninstall(args(purge=True, force=True), host)
    assert not host.path(install.RECORD).exists()


def test_a_record_for_another_uid_does_not_make_an_account_install_s(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    user = host.users[install.USER]
    host.users[install.USER] = install.User(user.uid + 1, user.gid, user.home, user.gecos)
    with pytest.raises(install.Refused, match="not made by install"):
        install.cmd_uninstall(args(purge=True), host)


def test_a_directory_of_another_user_in_home_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    # Root's record and the account name another uid than the one owning HOME.
    uid = os.getuid() + 1
    user = host.users[install.USER]
    host.users[install.USER] = install.User(uid, user.gid, user.home, user.gecos)
    record = json.loads(host.path(install.RECORD).read_text())
    host.path(install.RECORD).write_text(json.dumps({**record, "uid": uid}))
    host.calls.clear()
    with pytest.raises(install.Refused, match="does not belong to maity-runner"):
        install.cmd_install(args(code=None), host)
    assert host.calls == []


def test_the_cli_imports_without_pwd_and_without_posix_open_flags() -> None:
    """Windows has no `pwd`, `O_NOFOLLOW` or `O_DIRECTORY`; the CLI imports this module there
    too (cli-windows, join-windows)."""
    probe = (
        "import os, sys\n"
        "sys.modules['pwd'] = None\n"
        "del os.O_NOFOLLOW, os.O_DIRECTORY\n"
        "import maity.cli, maity.runner.install\n"
        "print('imported')\n"
    )
    src = str(Path(install.__file__).parents[2])
    done = subprocess.run(
        [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {src!r})\n{probe}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "imported"


def test_install_and_uninstall_take_no_config_path() -> None:
    for argv in (["install", URL, "--code", "X"], ["uninstall"]):
        with pytest.raises(SystemExit):
            cli.main(["runner", *argv, "--config", "/etc/runners/main.toml"])


@pytest.mark.parametrize("failing", ["disable", "stop-all"])
def test_a_failed_stop_removes_nothing(tmp_path: Path, failing: str) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    host.failing = {failing}
    with pytest.raises(install.Refused, match="nothing was removed"):
        install.cmd_uninstall(args(purge=True), host)
    assert host.path(install.UNIT_PATH).exists()
    assert host.path(install.HOME).is_dir()
    assert install.USER in host.users


def test_force_goes_on_after_a_failed_stop(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    host.failing = {"disable", "stop-all"}
    assert install.cmd_uninstall(args(force=True), host) == 0
    assert not host.path(install.UNIT_PATH).exists()


def test_a_failed_reload_after_uninstall_exits_1(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    host.failing = {"daemon-reload"}
    assert install.cmd_uninstall(args(), host) == 1


def test_a_restrictive_umask_leaves_the_configuration_readable(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    directory = host.path(install.CONFIG.parent)
    directory.mkdir(parents=True)
    directory.chmod(0o700)  # what umask 077 makes
    install.cmd_install(args(), host)
    assert (directory.stat().st_mode & 0o777) == 0o755
    assert (host.path(install.CONFIG).stat().st_mode & 0o777) == 0o644


def test_install_s_own_text_with_another_mode_is_put_right(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    host.path(install.CONFIG).chmod(0o600)
    install.cmd_install(args(code=None), host)
    assert (host.path(install.CONFIG).stat().st_mode & 0o777) == 0o644


def test_a_configuration_the_service_user_cannot_read_is_refused(tmp_path: Path) -> None:
    host = FakeHost(tmp_path)
    host.failing = {"-r"}
    with pytest.raises(install.Refused, match="cannot read"):
        install.cmd_install(args(), host)
    assert not any(" pair " in line for line in host.commands())


@pytest.mark.parametrize("name", ["RECORD", "CONFIG", "UNIT_PATH"])
def test_a_file_of_root_s_others_can_write_is_refused(tmp_path: Path, name: str) -> None:
    """A record others can write may name any account (4hv7 R3): install and uninstall trust
    none of root's files that the service user could have rewritten."""
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    host.path(getattr(install, name)).chmod(0o666)
    host.calls.clear()
    for run, kwargs in ((install.cmd_install, {"code": None}), (install.cmd_uninstall, {})):
        with pytest.raises(install.Refused, match="writable by (group or )?others"):
            run(args(**kwargs), host)
    with pytest.raises(install.Refused, match="writable by (group or )?others|not made by install"):
        install.cmd_uninstall(args(purge=True), host)
    assert host.calls == []
    assert host.path(install.HOME).is_dir()


def test_the_record_is_checked_on_the_file_that_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The record's mode is read from the opened file, not from a lookup by name before it."""
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    real = os.fstat

    def fstat(fd: int) -> os.stat_result:
        st = real(fd)
        if stat.S_ISREG(st.st_mode):
            return os.stat_result((st.st_mode | 0o002, *tuple(st)[1:]))
        return st

    monkeypatch.setattr(os, "fstat", fstat)
    with pytest.raises(install.Refused, match="writable by group or others"):
        install._ours(host, host.users[install.USER])


def test_a_plain_uninstall_after_an_unedited_install_changes_nothing(tmp_path: Path) -> None:
    """The starter configuration does not load, so `stop-all` could not find the agents: the
    refusal comes before `systemctl disable` (e5kk R3 F1)."""
    host = FakeHost(tmp_path)
    install.cmd_install(args(), host)
    host.calls.clear()
    with pytest.raises(install.Refused, match="does not load"):
        install.cmd_uninstall(args(), host)
    assert host.calls == []


def test_a_failed_userdel_leaves_everything_for_the_next_purge(tmp_path: Path) -> None:
    """The account goes first: a userdel that fails removes nothing else, and the next
    --purge finishes without --force (e5kk R3 F1)."""
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    host.failing = {"userdel"}
    with pytest.raises(install.Refused, match="could not remove the user"):
        install.cmd_uninstall(args(purge=True), host)
    assert host.path(install.HOME).is_dir() and host.path(install.CONFIG).is_file()
    assert host.path(install.RECORD).is_file() and install.USER in host.users
    host.failing = set()
    assert install.cmd_uninstall(args(purge=True), host) == 0
    assert install.USER not in host.users
    for path in (install.HOME, install.CONFIG.parent, install.RECORD):
        assert not host.path(path).exists()


def test_a_purge_finishes_after_the_user_alone_is_gone(tmp_path: Path) -> None:
    """Root's record names install's account, which is gone: the rest is install's to remove."""
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    # Where an earlier --purge stopped after its userdel: the unit is gone too.
    del host.users[install.USER]
    host.path(install.UNIT_PATH).unlink()
    host.calls.clear()
    assert install.cmd_uninstall(args(purge=True), host) == 0
    assert not any(line.startswith("userdel") for line in host.commands())
    for path in (install.HOME, install.CONFIG.parent, install.RECORD):
        assert not host.path(path).exists()


def _left(tmp_path: Path) -> FakeHost:
    """install's account gone, root's record and the unit still there."""
    host = FakeHost(tmp_path)
    complete_config(host)
    install.cmd_install(args(), host)
    del host.users[install.USER]
    host.calls.clear()
    return host


def _set_record(host: FakeHost, **kw: object) -> None:
    path = host.path(install.RECORD)
    record = json.loads(path.read_text())
    record.update(kw)
    path.write_text(json.dumps(record))


def _home_to_link(host: FakeHost) -> None:
    home = host.path(install.HOME)
    home.rename(home.with_name("elsewhere"))
    home.symlink_to(home.with_name("elsewhere"))


@pytest.mark.parametrize(
    "change, refusal",
    [
        (lambda h: _set_record(h, uid=os.getuid() + 1), "does not belong to maity-runner"),
        (_home_to_link, "is a link or not a directory"),
        (lambda h: h.path(install.STATE_DIR).chmod(0o770), "is writable by others"),
        (lambda h: h.path(install.HOME).chmod(0o702), "is writable by others"),
    ],
    ids=["another-uid", "home-a-link", "state-group-writable", "home-other-writable"],
)
def test_a_purge_after_the_user_is_gone_checks_its_directories_first(
    tmp_path: Path, change: Callable[[FakeHost], None], refusal: str
) -> None:
    """The account is gone, its directories keep its uid: they are checked against the uid in
    root's record, before the service is touched (e5kk R4 F1)."""
    host = _left(tmp_path)
    change(host)
    with pytest.raises(install.Refused, match=refusal):
        install.cmd_uninstall(args(purge=True, force=True), host)
    assert host.calls == []
    for path in (install.UNIT_PATH, install.CONFIG, install.RECORD):
        assert host.path(path).is_file()
    assert host.path(install.HOME).exists()


@pytest.mark.parametrize("uid", [None, True, "1000"])
def test_a_record_without_a_usable_uid_is_no_leftover(tmp_path: Path, uid: object) -> None:
    """Read as `_ours` reads it: without the uid, the home is nobody's install made."""
    host = _left(tmp_path)
    _set_record(host, uid=uid)
    with pytest.raises(install.Refused, match="install made no user"):
        install.cmd_uninstall(args(purge=True, force=True), host)
    assert host.calls == [] and host.path(install.HOME).is_dir()


def test_the_configuration_is_read_only_through_its_checked_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """install and uninstall parse the text `_read_root` checked, never the path again."""
    from maity.runner import config

    def by_name(path: Path) -> None:
        raise AssertionError(f"read by name: {path}")

    monkeypatch.setattr(config, "load", by_name)
    host = FakeHost(tmp_path)
    complete_config(host)
    assert install.cmd_install(args(), host) == 0
    assert install.cmd_uninstall(args(purge=True), host) == 0
