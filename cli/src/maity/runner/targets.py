"""Where agents run: `local`, or one target per ssh host (runner design §5.4).

A target bundles what the supervisor needs for one place: who runs the agents' commands
there (`AsUser`, through sudo, or `Ssh`), the workspaces root, the directory for the
agents' tmux socket, configuration and logs, its tmux server, its agent limit and the
harnesses as found there. An ssh target learns its remote home, and with it that
directory, on its first connection; until then, and whenever the connection fails, it is
unreachable, and its placements keep their last reported state (§15.7: reachability is
not a reason).
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import capabilities, config
from .asuser import SSH_UNREACHABLE, AsUser, Ssh, Unreachable
from .tmux import Tmux, attach_words

LOGS = "logs"
AGENT_FILES = ".maity-runner"  # under the remote user's home on an ssh host
UNIX_PATH_MAX = 108  # sun_path, with its terminating NUL: ssh's ControlPath must fit
CONTROL_SUFFIX = 17  # `.` + 16 random characters: ssh binds the master's socket under this first
SANDBOX_TOOLS = ("bwrap", "socat")
# Each argument with where the host's PATH finds it (empty when nowhere); names are data.
# A path the runner puts into a command line and a settings file as it is.
REMOTE_PATH = re.compile(r"^/[A-Za-z0-9._/+-]*$")
WHICH = 'for b; do printf "%s\\t%s\\n" "$b" "$(command -v -- "$b")"; done'


@dataclass
class Target:
    name: str
    as_user: AsUser
    workspaces: Path
    agent_path: str
    max_agents: int
    agent_files: Path | None = None  # None until an ssh target has connected once
    tmux_socket: Path | None = None
    probes: dict[str, capabilities.Probe] = field(default_factory=dict)
    sandbox: dict[str, bool] = field(default_factory=dict)  # harness id -> its OS sandbox
    # Harnesses whose sandbox is off for their version alone (capabilities.sandbox_held).
    held: set[str] = field(default_factory=set)
    backend: Tmux | None = None
    reachable: bool = True
    unreachable_since: float | None = None
    log_keep: int = 10 * 1024 * 1024  # limits.log_keep_bytes

    @property
    def remote(self) -> bool:
        return isinstance(self.as_user, Ssh)

    @property
    def host(self) -> str:
        """The workspace records' host prefix: the target's name on ssh, "" here."""
        return self.name if self.remote else ""

    def attach_hint(self, session: str) -> str:
        assert self.backend is not None  # noqa: S101 - set once connected
        attach = attach_words(self.backend.socket, session, self.as_user)
        if isinstance(self.as_user, Ssh):
            ssh = self.as_user
            attach = ["ssh", "-t", "-p", str(ssh.port), f"{ssh.login}@{ssh.address}", *attach]
        return shlex.join(attach)  # every word quoted: a remote value cannot become a command

    def connect(self, harnesses: dict[str, config.Harness]) -> None:
        """For an ssh target: its home, tmux server and harnesses, on the first connection.
        `Unreachable` when the host does not answer."""
        if self.backend is not None:
            return
        home = self.as_user.home()  # Unreachable, or OSError for a host set up wrong
        self.agent_files = home / AGENT_FILES
        self.tmux_socket = self.agent_files / "tmux.sock"
        self.as_user = pin_maity(self.as_user, self.agent_path)
        self.probes, self.sandbox, self.held = probe_remote(
            self.as_user, harnesses, self.agent_path
        )
        self.backend = Tmux(
            socket=self.tmux_socket,
            conf=self.agent_files / "tmux.conf",
            home=str(home),
            agent_path=self.agent_path,
            logs=self.agent_files / LOGS,
            as_user=self.as_user,
            log_keep=self.log_keep,
        )


def local(
    cfg: config.Config, probes: dict[str, capabilities.Probe], backend: Tmux | None = None
) -> Target:
    """The `local` target of the local backend (both layouts); `backend` replaces its tmux
    server (tests, and `stop-all`'s own)."""
    assert cfg.local is not None  # noqa: S101 - config.parse guarantees it for kind = local
    as_user = AsUser(cfg.local.agent_user if cfg.local.layout == "agent_user" else None)
    path = capabilities.agent_path(cfg, os.environ.get("PATH", ""))
    tools = {h: capabilities.sandbox_available(cfg.harnesses[h], path, as_user)
             for h in cfg.harnesses}  # fmt: skip

    def version(harness_id: str) -> str | None:
        return probes[harness_id].version if harness_id in probes else None

    if backend is None:
        home = str(config.home_of(as_user.user)) if as_user.user else os.environ.get("HOME", "")
        backend = Tmux(
            socket=cfg.local.tmux_socket,
            conf=cfg.local.agent_files / "tmux.conf",
            home=home,
            agent_path=path,
            logs=cfg.local.agent_files / LOGS,
            as_user=as_user,
            log_keep=cfg.limits.log_keep_bytes,
        )
    return Target(
        name="local",
        as_user=as_user,
        workspaces=cfg.local.workspaces,
        agent_path=path,
        max_agents=cfg.limits.max_agents,
        agent_files=cfg.local.agent_files,
        tmux_socket=cfg.local.tmux_socket,
        probes=probes,
        sandbox={h: tools[h] and capabilities.sandbox_version_ok(h, version(h)) for h in tools},
        held={h for h in tools if capabilities.sandbox_held(h, tools[h], version(h))},
        backend=backend,
    )


def ssh_hosts(cfg: config.Config) -> list[Target]:
    """One target per configured host; none of them connected yet."""
    assert cfg.ssh is not None  # noqa: S101 - config.parse guarantees it for kind = ssh
    control = cfg.state_dir / "ssh"  # ssh cannot create the directory of its ControlPath
    try:
        control.mkdir(mode=0o700, exist_ok=True)
    except OSError:
        pass  # no state directory yet: every connection fails, and check says why
    return [
        Target(
            name=host.name,
            as_user=Ssh(
                name=host.name,
                address=host.address,
                login=host.user,
                port=host.port,
                known_hosts=cfg.ssh.known_hosts,
                identity=cfg.ssh.identity,
                control_dir=control,
                agent_path=host.agent_path,
            ),
            workspaces=host.workspaces,
            agent_path=host.agent_path,
            max_agents=host.max_agents,
            reachable=False,
            log_keep=cfg.limits.log_keep_bytes,
        )
        for host in cfg.ssh.hosts
    ]


def build(cfg: config.Config, probes: dict[str, capabilities.Probe]) -> list[Target]:
    if cfg.backend == "ssh":
        return ssh_hosts(cfg)
    return [local(cfg, probes)]


def pin_maity(as_user: AsUser, agent_path: str) -> AsUser:
    """An ssh target's `as_user` with `maity` as the absolute path the host's agent_path
    finds it at, once, on connecting: the hook and the loop then start that one, whatever
    else a session's PATH holds. OSError when the host has none (the host is set up wrong)."""
    if not isinstance(as_user, Ssh):
        return as_user  # here: this interpreter, by its absolute path (AsUser.maity)
    done = as_user.run(["sh", "-c", WHICH, "sh", "maity"], env={"PATH": agent_path})
    if done.returncode == SSH_UNREACHABLE:
        raise Unreachable(done.stderr.strip()[:200])
    paths = dict(line.split("\t", 1) for line in done.stdout.splitlines() if "\t" in line)
    found = paths.get("maity", "")
    if not found.startswith("/") or not REMOTE_PATH.match(found):
        raise OSError(f"{as_user.name}: `maity` is not on agent_path ({agent_path}) as a plain"
                      " absolute path; the runner refuses the host")  # fmt: skip
    return replace(as_user, maity_path=found)


def probe_remote(
    as_user: AsUser, harnesses: dict[str, config.Harness], agent_path: str
) -> tuple[dict[str, capabilities.Probe], dict[str, bool], set[str]]:
    """The harness binaries and sandbox tools as the host's own PATH finds them, through
    one fixed `sh -c` template whose arguments are the configured binary names; with the
    harnesses whose sandbox is off for their version alone (capabilities.sandbox_held)."""
    found: dict[str, capabilities.Probe] = {}
    names = sorted({h.binary for h in harnesses.values() if h.binary} | set(SANDBOX_TOOLS))
    done = as_user.run(["sh", "-c", WHICH, "sh", *names], env={"PATH": agent_path})
    if done.returncode == SSH_UNREACHABLE:
        raise Unreachable(done.stderr.strip()[:200])
    paths = dict(line.split("\t", 1) for line in done.stdout.splitlines() if "\t" in line)
    for harness in harnesses.values():
        if harness.id == "stub":
            found[harness.id] = capabilities.Probe(None, None, None)
            continue
        path = paths.get(harness.binary or "", "")
        if not path:
            found[harness.id] = capabilities.Probe(None, None, "binary_not_found")
            continue
        version = as_user.run([path, "--version"], env={"PATH": agent_path}, timeout=15)
        lines = (version.stdout or version.stderr).strip().splitlines()
        if version.returncode != 0 or not lines:
            found[harness.id] = capabilities.Probe(path, None, "version_failed")
            continue
        match = capabilities.VERSION.search(lines[0])
        text = capabilities.ascii_text(match.group(0) if match else lines[0], 80)
        found[harness.id] = capabilities.Probe(path, text, None)
    tools = all(paths.get(tool) for tool in SANDBOX_TOOLS)
    sandbox: dict[str, bool] = {}
    held: set[str] = set()
    for harness in harnesses.values():
        if harness.id == "codex":  # tried on the host, as the local target tries it here
            codex = found[harness.id].path
            sandbox[harness.id] = (
                codex is not None
                and as_user.run(
                    [codex, "sandbox", "--", "true"], env={"PATH": agent_path}, timeout=30
                ).returncode
                == 0
            )
        else:
            sandbox[harness.id] = (
                harness.id == "claude-code"
                and tools
                and capabilities.sandbox_version_ok(harness.id, found[harness.id].version)
            )
            if capabilities.sandbox_held(harness.id, tools, found[harness.id].version):
                held.add(harness.id)
    return found, sandbox, held
