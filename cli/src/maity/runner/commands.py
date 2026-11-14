"""`maity runner pair` and `maity runner check` (runner design §11, slice R1)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import stat
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

from .. import hub, onboarding, state
from . import (
    capabilities,
    config,
    install,
    limitread,
    loop,
    operate,
    plaincall,
    serve,
    stub,
    supervisor,
    targets,
    tools,
    trust,
)
from .asuser import RUNNER, AsUser

STATE_FILE = serve.RUNNER_FILE
UNIT = "maity-runner.service"
REVOKE = serve.REVOKE
HEALTH_TIMEOUT = 10.0


class Refused(Exception):
    """The command is refused before anything is sent; exits 2 like a usage error."""


# --- pair ------------------------------------------------------------------------------------


def _code(args: argparse.Namespace) -> str:
    if args.code_file is not None:
        source = sys.stdin if args.code_file == "-" else None
        text = source.read() if source else Path(args.code_file).read_text(encoding="utf-8")
    else:
        text = args.code or ""
    code = text.strip()
    if not code:
        raise Refused("the pairing code is empty")
    return code


def _hub_table(path: Path) -> tuple[str, Path]:
    """`hub.url` and `hub.state_dir` of an existing configuration; nothing else is read, so a
    configuration still missing its limits can be paired again after a revocation."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise config.ConfigError([f"{path}: not valid TOML ({exc})"]) from None
    table = raw.get("hub")
    url = table.get("url") if isinstance(table, dict) else None
    if not isinstance(url, str) or not url:
        raise config.ConfigError([f"{path}: hub.url: required"])
    state_dir = table.get("state_dir", config.DEFAULT_STATE_DIR) if isinstance(table, dict) else ""
    if not isinstance(state_dir, str) or not state_dir:
        raise config.ConfigError([f"{path}: hub.state_dir: expected a string"])
    return url, Path(state_dir).expanduser()


def starter_config(base: str) -> str:
    """What `pair` writes when no configuration exists: the hub, and nothing it could guess."""
    return (
        "# Written by `maity runner pair`. Add [limits] and at least one [harness.<id>],\n"
        "# then run `maity runner check` (every default: `maity runner check --explain`).\n"
        "[hub]\n"
        f"url = {json.dumps(base)}\n"
        f"state_dir = {json.dumps(config.DEFAULT_STATE_DIR)}\n"
    )


def cmd_pair(args: argparse.Namespace) -> int:
    base = hub.hub_base(args.url)
    token = hub.pair_token(args.url)
    code = _code(args)
    path = config.path_of(args.config)
    created = False
    if path.exists():
        configured, state_dir = _hub_table(path)
        if hub.hub_base(configured) != base:
            raise Refused(
                f"{path} is the configuration of the runner for {hub.safe_url(configured)}; "
                "name a new one with --config to pair with another hub"
            )
    else:
        state_dir = Path(config.DEFAULT_STATE_DIR).expanduser()
        created = True
    _preflight(state_dir, path if created else None)
    result = hub.pair_exchange(base, token, code)
    hub_url = hub.accept_hub(args.url, result.hub)  # before anything is kept
    # The credential first: once the exchange is done, the enrollment is spent, and the
    # credential is the one thing that cannot be had again.
    stored = state.write_credential(state_dir, result.credential)
    state.save_state(
        state_dir,
        {
            "hub": hub_url,
            "runner_id": result.runner_id,
            "credential_id": result.credential_id,
        },
        name=STATE_FILE,
    )
    attached = ", ".join(onboarding.inline(name) for name in result.attached) or "none yet"
    print(
        f"paired as runner {onboarding.inline(result.runner_id)}; attached to: {attached}; "
        f"credential {onboarding.inline(result.credential_id)} stored in {stored} "
        "(mode 0600, not printed)",
        file=sys.stderr,
    )
    if created:
        try:
            state.write_file(path, starter_config(hub_url))
        except OSError as exc:
            print(
                f"could not write {path} ({exc.strerror}); the credential is stored. Write the "
                f"configuration by hand, starting with:\n{starter_config(hub_url)}",
                file=sys.stderr,
            )
            return 1
        print(f"wrote {path}; add [limits] and a [harness.<id>] to it", file=sys.stderr)
    print("next: `maity runner check`", file=sys.stderr)
    return 0


def _writable(path: Path) -> bool:
    """Whether `path` can be written, or created below its nearest existing parent."""
    existing = path if path.exists() else _existing_parent(path)
    return existing.is_dir() and os.access(existing, os.W_OK | os.X_OK)


def _preflight(state_dir: Path, new_config: Path | None) -> None:
    """Everything that would make storing the result fail, checked before the code is
    spent: the exchange is single use, and its credential exists nowhere else."""
    if state.has_credential(state_dir):
        raise Refused(
            f"{state_dir} already holds a runner credential. To pair again, move that file "
            "away first (a re-pair revokes it at the exchange); to replace the runner, "
            f"{REVOKE}"
        )
    if state_dir.exists():
        try:
            state.check_private(state_dir, REVOKE)
        except state.StateError as exc:
            raise Refused(str(exc)) from None
    if not _writable(state_dir):
        raise Refused(f"state_dir {state_dir} cannot be created or written by this user")
    if new_config is not None and not _writable(new_config.parent):
        raise Refused(f"{new_config.parent} cannot be created or written by this user")


# --- check -----------------------------------------------------------------------------------


@dataclass
class Report:
    lines: list[tuple[str, str]] = field(default_factory=list)

    def ok(self, text: str) -> None:
        self.lines.append(("ok", text))

    def warn(self, text: str) -> None:
        self.lines.append(("warn", text))

    def error(self, text: str) -> None:
        self.lines.append(("error", text))

    @property
    def failed(self) -> bool:
        return any(level == "error" for level, _ in self.lines)

    def print(self) -> None:
        for level, text in self.lines:
            print(f"{level:5}  {onboarding.clean(text)}")


DEFAULTS = (
    ("hub.state_dir", config.DEFAULT_STATE_DIR),
    ("limits.max_agents", "4"),
    ("limits.stop_grace_max", "120 (seconds; caps a placement's stop_grace_seconds)"),
    ("limits.restart", "at most 5 exits in 1800 s; backoff from 10 s, factor 2, cap 300 s; "
                       "an exit within 60 s counts as a crash"),  # fmt: skip
    ("limits.log_keep_bytes", "10 MiB per placement"),
    ("limits.require_local_approval", "false"),
    ("backend.kind", "local"),
    ("backend.local.workspaces", config.DEFAULT_WORKSPACES),
    ("backend.local.tmux_socket", "<state_dir>/tmux.sock; agent_user: ~<user>/.maity-runner/"),
    ("backend.local.layout", "single"),
    ("backend.local.agent_path", "the service's own PATH at start"),
    ("backend.local.memory_max, cpu_quota", "unset (no limit)"),
    ("backend.ssh.known_hosts", "required; the only known_hosts file used"),
    ("backend.ssh.identity", '"agent" (the operator\'s SSH_AUTH_SOCK)'),
    ("backend.ssh.hosts[].port", "22"),
    ("backend.ssh.hosts[].max_agents", "4"),
    ("backend.ssh.hosts[].agent_path", "/usr/local/bin:/usr/bin:/bin"),
    ("backend.ssh.hosts[].isolation", "shared_user (own_user: not yet)"),
    ("harness.<id>.modes", '["supervised"]; default_mode: the first'),
    ("harness.<id>.binary", "the harness's usual command, resolved on agent_path"),
    (
        "harness.<id>.require_sandbox",
        "unset: claude-code with bwrap and socat refused below version 2.1.295 or unknown;"
        " false: never refused for the sandbox",
    ),
    ("harness.<id>.env_file", "unset"),
    (
        "git.name, git.email",
        f"{config.DEFAULT_GIT_NAME} <{config.DEFAULT_GIT_EMAIL}> "
        "(author and committer of every agent's commits)",
    ),
)

EXPLAIN = (
    "Required: hub.url, limits.projects, limits.repositories, one [harness.<id>].\n"
    'limits.repositories: "host/owner/name" or "host/owner/*"; a scheme, a trailing / and\n'
    ".git are dropped and the host lowercased, the same as for the project's repository.\n"
    "Unknown keys are refused. Defaults:\n"
)


def explain() -> str:
    width = max(len(key) for key, _ in DEFAULTS)
    return EXPLAIN + "".join(f"  {key:<{width}}  {value}\n" for key, value in DEFAULTS)


def _private(report: Report, path: Path, what: str) -> None:
    try:
        state.check_private(path, REVOKE)
    except state.StateError as exc:
        report.error(str(exc))
    else:
        report.ok(f"{what} {path} is private")


def _check_config_file(report: Report, path: Path) -> None:
    """The configuration decides what agents may touch: nobody else may change it."""
    st = path.stat()
    if st.st_uid not in (os.getuid(), 0):
        report.warn(f"{path} belongs to another user, who can change what this runner may do")
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        report.warn(
            f"{path} is writable by group or others, who can change what this runner may do; "
            f"run `chmod go-w {path}`"
        )


def _check_repositories(report: Report, cfg: config.Config) -> None:
    """A gh rule in a grant's `allow` is not applied: agents open their pull requests with
    `maity gh`, which `pull_requests = true` switches on (cli/context/runner.md). Said, never
    an error, so a restart before the table is edited keeps every placement running."""
    for name, grant in cfg.repositories.items():
        if grant.refused:
            listed = ", ".join(repr(rule) for rule in grant.refused)
            report.warn(
                f"repositories.{name}: allow {listed} is not applied: no session runs gh; "
                "remove it and set pull_requests = true to let agents open pull requests "
                "with `maity gh pr create`"
            )
        if grant.pull_requests and "api.github.com" in grant.network:
            report.warn(
                f"repositories.{name}: network api.github.com is not needed for pull requests "
                "(`maity gh` runs outside the sandbox) and lets repository code reach the API"
            )


def _check_git(report: Report, cfg: config.Config) -> None:
    """Every placed session commits as `[git]`; without it as the generic default, which no
    forge links to anyone. Said as a warning: a runner that only runs the stub commits
    nothing, and a default is a working configuration (cli/context/runner.md)."""
    if cfg.git.configured:
        report.ok(f"agents commit as {cfg.git.name} <{cfg.git.email}>")
    elif any(harness.id != "stub" for harness in cfg.harnesses.values()):
        report.warn(
            f"agents commit as the default {cfg.git.name} <{cfg.git.email}>; set name and "
            "email in [git] to the identity your agents should commit as"
        )


def _check_state(report: Report, cfg: config.Config) -> None:
    directory = cfg.state_dir
    if not directory.is_dir():
        report.error(f"state_dir {directory} does not exist; run `maity runner pair` first")
        return
    _private(report, directory, "state_dir")
    if state.has_credential(directory):
        _private(report, state.credential_path(directory), "credential")
    else:
        report.error(f"no runner credential in {directory}; run `maity runner pair` first")


def _check_local(report: Report, local: config.Local) -> None:
    if shutil.which("tmux") is None:
        report.error("tmux is not installed; the local backend runs every agent in tmux")
    else:
        report.ok("tmux found")
    if local.layout == "agent_user" and local.agent_user:
        _check_agent_user(report, local)
        return
    workspaces = local.workspaces
    existing = workspaces if workspaces.exists() else _existing_parent(workspaces)
    if not existing.is_dir() or not os.access(existing, os.W_OK | os.X_OK):
        report.error(f"workspaces {workspaces} cannot be created or written by this user")
    else:
        report.ok(f"workspaces {workspaces}")


def _check_agent_user(report: Report, local: config.Local) -> None:
    """What the agent_user layout needs (§7.6): sudo to the agents' user without a password,
    `maity` importable as that user, and the workspaces and the agents' files writable by it."""
    user = local.agent_user or ""
    as_user = AsUser(user)
    try:
        sudo = as_user.run(["true"], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        report.error("sudo is not installed; the agent_user layout runs every agent through it")
        return
    if sudo.returncode != 0:
        report.error(
            f"`sudo -n -u {user} -- true` fails; the agent_user layout needs a sudoers rule "
            f"like `{getpass.getuser()} ALL=({user}) NOPASSWD: ALL`"
        )
        return
    report.ok(f"sudo to {user}")
    importable = as_user.run([sys.executable, "-I", "-c", "import maity"], timeout=30)
    if importable.returncode != 0:
        report.error(
            f"{user} cannot run {sys.executable} with maity; install maity where both users "
            "can run it (pipx --global, or a system-wide virtual environment)"
        )
    else:
        report.ok(f"{user} can run maity")
    for what, path in (("workspaces", local.workspaces), ("agents' files", local.agent_files)):
        probe = path if as_user.exists(path) else _existing_parent(path)
        if as_user.run(["test", "-w", str(probe)]).returncode != 0:
            report.error(f"{what} {path} cannot be created or written by {user}")
        else:
            report.ok(f"{what} {path} (as {user})")


def _existing_parent(path: Path) -> Path:
    while not path.exists() and path != path.parent:
        path = path.parent
    return path


def _check_harness(
    report: Report,
    harness: config.Harness,
    agent_path: str,
    as_user: AsUser = RUNNER,
    tools_dir: Path | None = None,
) -> None:
    if harness.id == "stub":
        report.ok("harness stub (test adapter)")
        return
    found = capabilities.probe(harness, agent_path, as_user, tools_dir)
    if found.reason == "binary_not_found" and tools_dir is not None and harness.install:
        report.ok(f"harness {harness.id}: not installed yet; `serve` installs it (§15.16)")
        return
    if found.reason == "binary_not_found" and tools_dir is not None and harness.update != "never":
        report.error(
            f"harness {harness.id}: no version installed by the runner; set install = true"
        )
        return
    if found.reason == "binary_not_found":
        report.error(f"harness {harness.id}: `{harness.binary}` not found on {agent_path}")
        return
    if found.reason == "version_failed":
        report.error(f"harness {harness.id}: `{found.path} --version` failed")
        return
    report.ok(f"harness {harness.id}: {found.path} ({found.version})")
    warning = capabilities.unchecked(harness.id, found.version)
    if warning is not None:
        report.warn(warning)
    if harness.env_file is not None:
        if harness.env_file.is_file():
            _private(report, harness.env_file, f"harness {harness.id} env_file")
        else:
            report.error(f"harness {harness.id}: env_file {harness.env_file} does not exist")
    if harness.id == "claude-code":
        _check_claude_code(report, harness, as_user, agent_path, found.version)
    if harness.id == "codex":
        # The login of whoever runs the agents, as the adapter links it.
        own = None if as_user.user else os.environ.get("CODEX_HOME")
        home = config.home_of(as_user.user) if as_user.user else Path.home()
        login = Path(own or home / ".codex") / "auth.json"
        if not as_user.exists(login, "-f"):
            report.warn(f"harness codex: no login at {login}; agents would start without one")


def _check_claude_code(
    report: Report,
    harness: config.Harness,
    as_user: AsUser = RUNNER,
    agent_path: str = "",
    version: str | None = None,
) -> None:
    # On the agents' PATH, as their user finds it: that is where the sandbox starts.
    tools = capabilities.claude_sandbox_tools()
    missing = [t for t in tools or () if not capabilities.which(t, agent_path, as_user)]
    line = None
    held = tools is not None and not missing
    if tools is None:
        line = f"harness claude-code: no OS sandbox on {sys.platform}; agents run unsandboxed"
    elif missing:
        line = f"harness claude-code: no OS sandbox ({', '.join(missing)} missing)"
    elif not capabilities.sandbox_version_ok(harness.id, version):
        line = capabilities.sandbox_version_line(version)
    if line is not None:
        refused = capabilities.sandbox_refused(harness, False, held)
        (report.error if refused else report.warn)(line)
    else:
        report.ok(f"harness claude-code: OS sandbox ({', '.join(tools or ())})")
        _check_claude_hooks(report, as_user, "")
    _check_claude_settings(report, as_user, "")


def _check_claude_hooks(report: Report, as_user: AsUser, where: str) -> None:
    """With the sandbox on, the runner's hook must run: settings that switch hooks off
    refuse every start of a sandboxed agent (supervisor), so `check` says so as an error."""
    why = capabilities.claude_hooks_off(as_user)
    if why is None:
        report.ok(f"{where}harness claude-code: hooks are not switched off")
    else:
        report.error(f"{where}{capabilities.claude_hooks_line(why)}")


def _check_claude_settings(report: Report, as_user: AsUser, where: str) -> None:
    """The agents' user's own Claude Code settings (here, through sudo, or on a host):
    agents start with --setting-sources user, so they inherit its rules and hooks."""
    try:
        settings = _json_bytes(as_user.read(as_user.home() / ".claude" / "settings.json"))
    except (OSError, KeyError):
        settings = None
    if settings is None:
        return
    permissions = settings.get("permissions")
    allow = permissions.get("allow") if isinstance(permissions, dict) else None
    if isinstance(allow, list) and allow:
        report.warn(
            f"{where}harness claude-code: ~/.claude/settings.json allows {len(allow)} rule(s) "
            "of its own; every agent this runner starts inherits them"
        )
    if settings.get("hooks"):
        report.warn(f"{where}harness claude-code: ~/.claude/settings.json defines hooks; "
                    "agents run them")  # fmt: skip


def _check_ssh(report: Report, cfg: config.Config, only: str | None) -> None:
    """The runner's side of the ssh backend, then each host (§5.4): reached with the
    runner's own known_hosts only, so an unknown or changed host key fails here."""
    assert cfg.ssh is not None  # noqa: S101 - the caller checks it
    if shutil.which("ssh") is None:
        report.error("ssh is not installed; the ssh backend reaches every host through it")
        return
    known = cfg.ssh.known_hosts
    if not known.is_file():
        report.error(f"known_hosts {known} does not exist; add each host's key to it")
    else:
        _check_config_file(report, known)
        report.ok(f"known_hosts {known}")
    if cfg.ssh.identity == "agent":
        if not os.environ.get("SSH_AUTH_SOCK"):
            report.error('identity = "agent" needs an ssh agent (SSH_AUTH_SOCK is not set)')
    elif not Path(cfg.ssh.identity).expanduser().is_file():
        report.error(f"identity {cfg.ssh.identity} does not exist")
    else:
        _private(report, Path(cfg.ssh.identity).expanduser(), "identity")
    # ssh's %C is 40 hex characters, and ssh binds the master's socket first under a
    # temporary name: the path plus `.` and 16 random characters must fit as well.
    socket = cfg.state_dir / "ssh" / ("0" * 40)
    if len(str(socket).encode()) + targets.CONTROL_SUFFIX >= targets.UNIX_PATH_MAX:
        report.error(
            f"state_dir {cfg.state_dir} is too long for ssh's connection sockets "
            f"(<state_dir>/ssh/<40 hex> plus ssh's {targets.CONTROL_SUFFIX}-byte temporary "
            f"suffix must stay under {targets.UNIX_PATH_MAX} bytes); "
            "choose a shorter hub.state_dir"
        )
    hosts = [t for t in targets.ssh_hosts(cfg) if only is None or t.name == only]
    if not hosts:
        report.error(f"no host named {onboarding.inline(only or '')} in backend.ssh.hosts")
    for target in hosts:
        _check_host(report, cfg, target)


def _check_host(report: Report, cfg: config.Config, target: targets.Target) -> None:
    name, as_user = target.name, target.as_user
    try:
        as_user.home()
    except OSError as exc:
        report.error(f"{name}: {onboarding.inline(str(exc))[:200]}")
        return
    report.ok(f"{name}: reached, host key known")
    tools = ("tmux", "git", "maity")
    found = as_user.run(["sh", "-c", targets.WHICH, "sh", *tools],
                        env={"PATH": target.agent_path})  # fmt: skip
    paths = dict(line.split("\t", 1) for line in found.stdout.splitlines() if "\t" in line)
    for tool in tools:
        if paths.get(tool):
            report.ok(f"{name}: {tool} found on agent_path")
        else:
            report.error(f"{name}: `{tool}` is not on agent_path ({target.agent_path})")
    probes, sandbox, held = targets.probe_remote(as_user, cfg.harnesses, target.agent_path)
    for harness in cfg.harnesses.values():
        probe = probes[harness.id]
        if harness.id == "stub":
            report.ok(f"{name}: harness stub (test adapter)")
        elif probe.reason is not None:
            report.error(f"{name}: harness {harness.id}: {probe.reason.replace('_', ' ')}")
        else:
            report.ok(f"{name}: harness {harness.id}: {probe.path} ({probe.version})")
            warning = capabilities.unchecked(harness.id, probe.version)
            if warning is not None:
                report.warn(f"{name}: {warning}")
            if harness.id == "claude-code" and not sandbox.get(harness.id):
                if capabilities.sandbox_version_ok(harness.id, probe.version):
                    line = f"{name}: harness claude-code: no OS sandbox (bwrap or socat missing)"
                else:
                    line = f"{name}: {capabilities.sandbox_version_line(probe.version)}"
                refused = capabilities.sandbox_refused(harness, False, harness.id in held)
                (report.error if refused else report.warn)(line)
            elif harness.id == "claude-code":
                _check_claude_hooks(report, as_user, f"{name}: ")
    root = target.workspaces
    probe_dir = root if as_user.exists(root, "-d") else root.parent
    if as_user.run(["test", "-w", str(probe_dir)]).returncode != 0:
        report.error(f"{name}: workspaces {root} cannot be created or written")
    else:
        report.ok(f"{name}: workspaces {root}")
    if "claude-code" in cfg.harnesses:
        _check_claude_settings(report, as_user, f"{name}: ")
    if as_user.run(["sudo", "-n", "true"]).returncode == 0:
        report.warn(f"{name}: the remote user has sudo without a password; agents have it too")


def _json_bytes(raw: bytes) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _check_hub(report: Report, cfg: config.Config) -> None:
    try:
        base = hub.hub_base(cfg.hub_url)
        hub.get_text(f"{base}{hub.API}/health", timeout=HEALTH_TIMEOUT)
    except hub.HubError as exc:
        report.error(f"hub: {exc}")
        return
    report.ok(f"hub {base} answers")
    paired = state.load_state(cfg.state_dir, name=STATE_FILE) if cfg.state_dir.is_dir() else {}
    if paired.get("hub") and paired["hub"] != base:
        report.error(
            f"the credential in {cfg.state_dir} was issued by {hub.safe_url(paired['hub'])}, "
            f"not by {base}"
        )


def cmd_check(args: argparse.Namespace) -> int:
    if args.explain:
        print(explain(), end="")
        return 0
    path = config.path_of(args.config)
    report = Report()
    try:
        cfg = config.load(path)
    except config.ConfigError as exc:
        for problem in exc.problems:
            report.error(problem)
        report.print()
        return 1
    report.ok(f"configuration {path}")
    for problem in config.unsupported(cfg):
        report.error(problem)
    _check_config_file(report, path)
    _check_state(report, cfg)
    _check_repositories(report, cfg)
    _check_git(report, cfg)
    if cfg.ssh is not None:
        _check_ssh(report, cfg, getattr(args, "target", None))
    elif getattr(args, "target", None):
        report.error("--target is for the ssh backend")
    if cfg.local is not None:
        _check_local(report, cfg.local)
        agent_path = capabilities.agent_path(cfg, os.environ.get("PATH", ""))
        if shutil.which("maity", path=agent_path) is None:
            report.error(f"`maity` is not on agent_path ({agent_path}); every agent runs it")
        else:
            report.ok("maity found on agent_path")
        for harness in cfg.harnesses.values():
            _check_harness(report, harness, agent_path, supervisor.agents_user(cfg), cfg.tools_dir)
    if not args.offline:
        _check_hub(report, cfg)
    report.print()
    return 1 if report.failed else 0


# --- serve and status ------------------------------------------------------------------------


def cmd_unit(args: argparse.Namespace) -> int:
    """The systemd unit shipped in the package, to stdout."""
    print(resources.files("maity.runner").joinpath(UNIT).read_text(encoding="utf-8"), end="")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    return serve.serve(config.path_of(args.config))


def _alive(pid: Any) -> bool:
    """Whether `pid` is a running `maity runner serve`; a reused pid is not."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return True  # no /proc: the signal check is all there is
    return b"runner" in command and b"serve" in command


def cmd_tools(args: argparse.Namespace) -> int:
    """The tools this runner installs and updates (§15.16), from its tools directory only;
    `rollback` makes the kept version the one new sessions start with. Never contacts the
    hub: a running `serve` notices within a minute and tells the hub."""
    cfg = config.load(config.path_of(args.config))
    managed = {h.id: h for h in cfg.harnesses.values() if h.install or h.update != "never"}
    if getattr(args, "tools_action", None) == "rollback":
        if args.tool not in managed:
            print(f"{args.tool}: not a tool this runner installs or updates", file=sys.stderr)
            return 1
        try:
            done = tools.rollback(cfg.tools_dir, args.tool)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(
            f"{args.tool}: new sessions start with {done.version}; {done.previous_version} "
            "stays for a second rollback; running sessions keep the version they started with"
        )
        return 0
    rows = [
        tools.report(cfg.tools_dir, h.id, install=h.install, update=h.update,
                     sessions_on_older=0)  # fmt: skip
        for h in managed.values()
    ]
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no tool is installed or updated by this runner (harness install / update)")
    for row in rows:
        state_text = row["state"] + (f": {row['reason']}" if row["reason"] else "")
        print(
            f"{row['id']}: {row['version'] or '-'} ({state_text}); kept "
            f"{row['previous_version'] or '-'}; latest {row['latest'] or '-'}; "
            f"checked {row['checked_at'] or 'never'}"
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """The local view, from the state directory only; never contacts the hub."""
    cfg = config.load(config.path_of(args.config))
    paired = state.load_state(cfg.state_dir, name=STATE_FILE) if cfg.state_dir.is_dir() else {}
    current = (
        state.load_state(cfg.state_dir, name=serve.STATUS_FILE) if cfg.state_dir.is_dir() else {}
    )
    running = _alive(current.get("pid"))
    # The supervisor's own record of each placement: its state and, while one runs, the
    # line to attach to its session (the agents keep running without the service).
    actual = (
        state.load_state(cfg.state_dir, name=supervisor.ACTUAL_FILE)
        if cfg.state_dir.is_dir()
        else {}
    )
    placements = []
    for placement in current.get("placements") or []:
        if not isinstance(placement, dict):
            continue
        rec = actual.get(str(placement.get("id")))
        rec = rec if isinstance(rec, dict) else {}
        live = rec.get("state") in ("starting", "running")
        hint = rec.get("session_hint") if live else None
        placements.append({**placement, "state": rec.get("state"),
                           "attach": hint if isinstance(hint, str) else None})  # fmt: skip
    view: dict[str, Any] = {
        "hub": paired.get("hub"),
        "runner_id": paired.get("runner_id"),
        "service": "running" if running else "not running",
        "connected": bool(current.get("connected")) and running,
        **{k: current.get(k) for k in ("session_id", "error", "retry_at", "updated_at")},
        "placements": placements,
    }
    if args.json:
        print(json.dumps(view, indent=2))
        return 0
    show = onboarding.inline  # every string here came from the hub or a file it wrote
    print(f"runner   {show(view['runner_id'] or 'not paired')} on {show(view['hub'] or '-')}")
    connection = "connected" if view["connected"] else "not connected"
    print(f"service  {view['service']}, {connection} (as of {show(view['updated_at'] or '-')})")
    if view["error"]:
        retry = f"; next try {show(view['retry_at'])}" if view["retry_at"] and running else ""
        print(f"last     {show(view['error'])}{retry}")
    for placement in view["placements"]:
        print(
            f"placement {show(placement.get('id'))}  {show(placement.get('project'))}  "
            f"generation {show(placement.get('generation'))}  "
            f"desired {show(placement.get('desired'))}  "
            f"state {show(placement.get('state') or '-')}"
        )
        if placement["attach"]:
            print(f"  attach   {show(placement['attach'])}")
    return 0


def _seconds(value: str) -> int:
    seconds = int(value)
    if seconds < 0:
        raise argparse.ArgumentTypeError("0 or more seconds")
    return seconds


def _operate(name: str) -> Any:
    """A handler for one of `operate`'s commands: the configuration first, its refusals as
    this module's (exit 2)."""

    def handler(args: argparse.Namespace) -> int:
        cfg = config.load(config.path_of(args.config))
        try:
            result: int = getattr(operate, name)(cfg, args)
        except operate.Refused as exc:
            raise Refused(str(exc)) from None
        return result

    return handler


def _installer(command: Any) -> Any:
    """install/uninstall, their refusals as this module's (exit 2)."""

    def handler(args: argparse.Namespace) -> int:
        try:
            result: int = command(args)
        except install.Refused as exc:
            raise Refused(str(exc)) from None
        return result

    return handler


# --- parser ----------------------------------------------------------------------------------


def add_parser(sub: Any, fmt: type[argparse.HelpFormatter]) -> None:
    p = sub.add_parser(
        "runner",
        help="run agents on this machine for a hub (Python 3.11+)",
        description="The runner service: pair this machine with a hub, check its configuration, "
        "and start or stop agents on placements. Reads its own configuration "
        f"({config.DEFAULT_PATH}, or --config), never MAITY_STATE_DIR.",
        formatter_class=fmt,
    )
    rsub = p.add_subparsers(dest="runner_command", metavar="<action>", required=True)

    # Internal: what an agent's tmux pane runs on an ssh host, whose interpreter is not the
    # runner's (no `help`, so not listed).
    r = rsub.add_parser("loop")
    r.add_argument("--spec", required=True)
    r.set_defaults(handler=lambda a: loop.main(["--spec", a.spec]))
    # Internal too: the loop's limit file, read on the agents' side (limitread).
    r = rsub.add_parser("limitread")
    r.add_argument("path")
    r.set_defaults(handler=lambda a: limitread.main([a.path]))
    # Internal too: Claude Code's folder trust for a clone, recorded on the agents' side (trust).
    r = rsub.add_parser("trust")
    r.add_argument("home")
    r.add_argument("clone")
    r.set_defaults(handler=lambda a: trust.main([a.home, a.clone]))
    # Internal too: the hook a placed Claude Code session runs before each tool call
    # (plaincall), reading its input on stdin.
    r = rsub.add_parser("plaincall")
    r.set_defaults(handler=lambda a: plaincall.main([]))
    r = rsub.add_parser("stub")
    r.add_argument("--exit-code", type=int, default=0)
    r.add_argument("--run-seconds", type=int, default=30)
    r.set_defaults(
        handler=lambda a: stub.main(
            ["--exit-code", str(a.exit_code), "--run-seconds", str(a.run_seconds)]
        )
    )

    r = rsub.add_parser(
        "pair",
        help="exchange a pairing code for the runner's credential",
        description="Exchange the single-use pairing code for the runner's credential and store "
        "it under state_dir (0600, never printed). Without a configuration, writes one with the "
        "hub and the default state_dir. A configuration for another hub is refused.",
        formatter_class=fmt,
    )
    r.add_argument("url", help="the pairing URL (https://<hub>/r/<token>)")
    code = r.add_mutually_exclusive_group(required=True)
    code.add_argument("--code", help="the single-use pairing code")
    code.add_argument("--code-file", help="read the code from this file, or stdin with -")
    r.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
    r.set_defaults(handler=cmd_pair)

    r = rsub.add_parser(
        "check",
        help="validate the configuration and this machine; exits 1 on any error",
        description="Validate the configuration, the state directory, tmux and the workspaces, "
        "each harness's binary and version, sandbox prerequisites and the harness settings "
        "agents would inherit, then GET /health on the hub. On the ssh backend each host is "
        "reached and checked for tmux, git, maity, the harnesses and its workspaces. Nothing "
        "else is sent.",
        formatter_class=fmt,
    )
    r.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
    r.add_argument("--explain", action="store_true", help="print every key's default and stop")
    r.add_argument("--offline", action="store_true", help="do not contact the hub")
    r.add_argument("--target", help="ssh backend: check only this host")
    r.set_defaults(handler=cmd_check)

    r = rsub.add_parser(
        "serve",
        help="the runner service: connect to the hub and follow its placements",
        description="Say hello to the hub, hold the runner's event stream and re-read the "
        "placements on every wake. Logs to standard error. Exits 0 on SIGTERM (agents keep "
        f"running) and {serve.EXIT_CONFIG} on a revoked credential or a configuration the hub "
        "refuses, which the systemd unit does not restart.",
        formatter_class=fmt,
    )
    r.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
    r.set_defaults(handler=cmd_serve)

    r = rsub.add_parser(
        "status",
        help="the local view: service, connection, placements; does not contact the hub",
        description="Print what the running service last wrote to the state directory.",
        formatter_class=fmt,
    )
    r.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
    r.add_argument("--json", action="store_true", help="print it as JSON")
    r.set_defaults(handler=cmd_status)

    r = rsub.add_parser(
        "tools",
        help="the tools this runner installs and updates; `rollback <tool>` goes back",
        description="List the harness tools this runner installs or updates (harness "
        "install / update): the version new sessions start with, the one kept, the latest "
        "found. `rollback <tool>` swaps the two for new sessions; a second rollback swaps "
        "back. Reads the tools directory only; a running serve picks the change up.",
        formatter_class=fmt,
    )
    r.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
    r.add_argument("--json", action="store_true", help="print it as JSON")
    r.set_defaults(handler=cmd_tools)
    tsub = r.add_subparsers(dest="tools_action")
    rb = tsub.add_parser(
        "rollback",
        help="new sessions start with the kept version",
        description="Make the kept version the one new sessions start with (§15.16).",
        formatter_class=fmt,
    )
    rb.add_argument("tool", help="a harness id, e.g. codex")
    rb.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
    rb.set_defaults(handler=cmd_tools, json=False)

    r = rsub.add_parser(
        "unit",
        help="print the systemd unit for running serve as a service",
        description="Print the systemd unit shipped with this package; its comments say how "
        "to install it by hand (`maity runner unit > /etc/systemd/system/maity-runner.service`). "
        "`sudo maity runner install` does those steps.",
        formatter_class=fmt,
    )
    r.set_defaults(handler=cmd_unit)

    r = rsub.add_parser(
        "install",
        help="as root: set this machine up to run the runner as a systemd service",
        description=f"Linux with systemd and tmux, as root. Creates the {install.USER} system "
        f"user and {install.HOME} (state, workspaces), writes {install.CONFIG} and "
        f"{install.UNIT_PATH} with the path of this maity, pairs as {install.USER}, enables the "
        "service and runs `maity runner check`. Existing files are left as they are unless "
        "--force. While the configuration is not one serve would accept (no [limits] or "
        "[harness.<id>] yet), the service is enabled but not started, and what is missing is "
        "listed. Running it again is safe: it creates only what is missing and pairs only an "
        "unpaired runner; an already paired one needs no code. The paths are fixed; other paths "
        "are the manual steps of `maity runner unit`. Anything on those paths that is not as "
        "install would have made it (a link, another owner, a directory or a file of root's "
        "others can write) stops it before any change; a mode that only differs from "
        "install's is set back. The workspaces a kept configuration names are not checked.",
        formatter_class=fmt,
    )
    r.add_argument("url", help="the pairing URL (https://<hub>/r/<token>)")
    code = r.add_mutually_exclusive_group()
    code.add_argument("--code", help="the single-use pairing code")
    code.add_argument("--code-file", help="read the code from this file, or stdin with -")
    r.add_argument("--force", action="store_true", help="rewrite the configuration and the unit")
    r.set_defaults(handler=_installer(install.cmd_install))

    r = rsub.add_parser(
        "uninstall",
        help="as root: stop and remove the runner's systemd service",
        description=f"Stops and disables the service, ends the agents it started (`stop-all`) "
        f"and removes {install.UNIT_PATH}; when stopping fails, nothing is removed unless "
        f"--force. With --purge also {install.HOME} (state, credential, workspaces with any "
        f"unpushed work), {install.CONFIG.parent} and the {install.USER} user, if install made "
        f"them ({install.RECORD} says so); otherwise --purge refuses before any change "
        f"while either directory exists. When it cannot tell that the agents stopped (no "
        "configuration, one that does not load), it removes nothing either, and those are "
        "checked before the service is disabled. --purge removes the account first, so a "
        "failed userdel leaves the account, its files and the configuration for the next "
        "--purge; the unit is already gone by then. "
        "The hub keeps listing the runner until it is removed in the dashboard.",
        formatter_class=fmt,
    )
    r.add_argument("--purge", action="store_true", help="also remove state, workspaces and user")
    r.add_argument(
        "--force", action="store_true", help="go on when stopping the service or its agents fails"
    )
    r.set_defaults(handler=_installer(install.cmd_uninstall))

    def runner_cmd(name: str, summary: str, description: str) -> argparse.ArgumentParser:
        r: argparse.ArgumentParser = rsub.add_parser(
            name, help=summary, description=description, formatter_class=fmt
        )
        r.add_argument("--config", help=f"configuration file (default {config.DEFAULT_PATH})")
        return r

    r = runner_cmd(
        "logs",
        "an agent's session output, from this host",
        "Print a placement's log (<state_dir>/logs/<placement>.log); the placement is named by "
        "its id or by the agent's handle. Logs stay on the runner; the hub never sees them.",
    )
    r.add_argument("which", help="the placement id, or the agent's handle")
    r.add_argument("--follow", action="store_true", help="keep printing what is appended")
    r.add_argument(
        "--raw", action="store_true", help="the bytes as written, escape sequences included"
    )
    r.set_defaults(handler=_operate("cmd_logs"))

    r = runner_cmd(
        "approve",
        "let a held placement start (require_local_approval)",
        "With limits.require_local_approval, new placements wait as pending/awaiting_operator "
        "until approved here, on the runner host.",
    )
    r.add_argument("which", help="the placement id, or the agent's handle")
    r.set_defaults(handler=_operate("cmd_approve"))

    r = runner_cmd(
        "stop-all",
        "end every agent on this runner, without the hub",
        "For emergencies and decommissioning: SIGTERM to every agent session, then kill-session "
        "after --grace seconds. Refused while the service runs, since it would start them again.",
    )
    r.add_argument("--grace", type=_seconds, default=operate.STOP_ALL_GRACE, metavar="N")
    r.set_defaults(handler=_operate("cmd_stop_all"))

    r = runner_cmd(
        "gc",
        "list, and with --yes remove, workspaces whose credential is revoked",
        "For every recorded workspace without a placement whose credential the hub reports as "
        "revoked: its uncommitted files and the commits on no remote (git run with hooks, "
        "fsmonitor and pagers off). Removes only with --yes.",
    )
    r.add_argument("--revoked", action="store_true", help="required: the only kind gc knows")
    r.add_argument("--yes", action="store_true", help="remove the workspaces listed")
    r.set_defaults(handler=_operate("cmd_gc"))

    r = runner_cmd(
        "workspace",
        "record an existing clone for an agent",
        "`maity runner workspace claim <project id>/<clone> --agent <id>`: record a clone made by "
        "hand, or one left after a lost state directory, so the runner may use it.",
    )
    r.add_argument("action", choices=("claim",))
    r.add_argument("where", help="<project id>/<clone>, the project id as the hub names it (prj-…)")
    r.add_argument("--agent", required=True, help="the agent's member id")
    r.add_argument("--placement", help="the placement id, when one exists")
    r.add_argument("--force", action="store_true", help="record it again")
    r.set_defaults(handler=_operate("cmd_workspace_claim"))
