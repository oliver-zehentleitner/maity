"""`maity runner install` and `uninstall`: the runner as a systemd system service.

`install` does the steps the shipped unit's header lists, as root: the `maity-runner`
system user and its directories, `/etc/maity-runner/runner.toml`, the unit with the path of
the `maity` that runs this command, pairing as that user, `systemctl enable`, and `maity
runner check`. Every call that touches the system goes through `Host`, so the tests run
without root or systemd (cli/context/runner.md).
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .. import hub, state
from . import config

SERVICE = "maity-runner"
USER = "maity-runner"
HOME = Path("/var/lib/maity-runner")
STATE_DIR = HOME / "state"
WORKSPACES = HOME / "workspaces"
CONFIG = Path("/etc/maity-runner/runner.toml")
UNIT_PATH = Path(f"/etc/systemd/system/{SERVICE}.service")
UNIT = f"{SERVICE}.service"
# What the shipped unit starts; install replaces it with the interpreter that runs this command.
SHIPPED_EXEC = "ExecStart=/usr/local/bin/maity runner serve --config /etc/maity-runner/runner.toml"


class Refused(Exception):
    """Refused before anything changed, or at a step that cannot go on (exit 2)."""


@dataclass
class Host:
    """The system calls behind install and uninstall. `root` prefixes every absolute path,
    so the tests write below a temporary directory."""

    root: Path = Path("/")

    def path(self, absolute: Path) -> Path:
        return self.root / absolute.relative_to("/")

    def platform(self) -> str:
        return sys.platform

    def euid(self) -> int:
        return os.geteuid()

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def systemd_running(self) -> bool:
        return self.path(Path("/run/systemd/system")).is_dir()

    def user_ids(self, name: str) -> tuple[int, int] | None:
        try:
            entry = pwd.getpwnam(name)
        except KeyError:
            return None
        return entry.pw_uid, entry.pw_gid

    def chown(self, path: Path, uid: int, gid: int) -> None:
        os.chown(path, uid, gid)

    def run(self, argv: Sequence[str], stdin: str | None = None) -> int:
        """Runs `argv`; its output goes to the terminal, as the person would see it."""
        return subprocess.run(list(argv), input=stdin, text=True, check=False).returncode

    def maity(self) -> list[str]:
        """The `maity` that runs this command: its interpreter, isolated from the cwd. A pipx
        install is not in /usr/local/bin, where the shipped unit looks."""
        return [sys.executable, "-I", "-m", "maity"]


def _as_runner(host: Host, argv: Sequence[str]) -> list[str]:
    """`argv` as the service user, with its own HOME (runuser keeps root's)."""
    return ["runuser", "-u", USER, "--", "env", f"HOME={HOME}", *host.maity(), *argv]


def starter_config(url: str) -> str:
    return (
        "# Written by `maity runner install`. Add [limits] and at least one [harness.<id>],\n"
        "# then `sudo systemctl restart maity-runner` and `maity runner check`\n"
        "# (every default: `maity runner check --explain`).\n"
        "[hub]\n"
        f"url = {json.dumps(url)}\n"
        f"state_dir = {json.dumps(str(STATE_DIR))}\n"
        "\n"
        "[backend.local]\n"
        f"workspaces = {json.dumps(str(WORKSPACES))}\n"
    )


def unit_text(host: Host) -> str:
    shipped = resources.files("maity.runner").joinpath(UNIT).read_text(encoding="utf-8")
    if SHIPPED_EXEC not in shipped:  # the shipped unit changed without this module
        raise Refused("the shipped unit has no ExecStart line this version can rewrite")
    command = " ".join([*host.maity(), "runner", "serve", "--config", str(CONFIG)])
    return shipped.replace(SHIPPED_EXEC, f"ExecStart={command}")


def _say(text: str) -> None:
    print(text, file=sys.stderr)


def _write(host: Host, absolute: Path, text: str, force: bool, mode: int) -> None:
    """Writes a file root owns; an existing different one is left alone unless `force`."""
    target = host.path(absolute)
    if target.exists():
        if target.read_text(encoding="utf-8") == text:
            _say(f"ok     {absolute}")
            return
        if not force:
            _say(f"kept   {absolute} (it differs; --force rewrites it)")
            return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    target.chmod(mode)
    _say(f"wrote  {absolute}")


def _preconditions(host: Host) -> None:
    if host.platform() != "linux":
        raise Refused("install sets up a systemd service: Linux only")
    if host.euid() != 0:
        raise Refused("install creates a system user and a system service: run it with sudo")
    if not host.systemd_running() or host.which("systemctl") is None:
        raise Refused("systemd is not running on this machine; run `maity runner serve` yourself")
    for tool in ("tmux", "runuser", "useradd"):
        if host.which(tool) is None:
            raise Refused(f"`{tool}` is not installed; the runner needs it")


def _user(host: Host) -> tuple[int, int]:
    ids = host.user_ids(USER)
    if ids is None:
        argv = ["useradd", "--system", "--create-home", "--home-dir", str(HOME)]
        if host.run([*argv, "--shell", "/usr/sbin/nologin", USER]) != 0:
            raise Refused(f"could not create the system user {USER}")
        ids = host.user_ids(USER)
        if ids is None:
            raise Refused(f"the system user {USER} was not created")
        _say(f"made   user {USER}")
    else:
        _say(f"ok     user {USER}")
    for directory in (HOME, STATE_DIR, WORKSPACES):
        path = host.path(directory)
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
        host.chown(path, *ids)
    return ids


def cmd_install(args: argparse.Namespace, host: Host | None = None) -> int:
    host = host or Host()
    _preconditions(host)
    base = hub.hub_base(args.url)
    hub.pair_token(args.url)  # a pairing URL, checked before anything changes
    paired = state.has_credential(host.path(STATE_DIR))
    code = None if paired else _code(args)
    _user(host)
    config_path = Path(args.config) if args.config else CONFIG
    _write(host, config_path, starter_config(base), args.force, 0o644)
    if host.run(_as_runner(host, ["--version"])) != 0:
        raise Refused(
            f"{USER} cannot run {host.maity()[0]}: install maity where every user can run it "
            "(`sudo pipx install --global maity`), then run install again"
        )
    _write(host, UNIT_PATH, unit_text(host), args.force, 0o644)
    if paired:
        _say(f"ok     already paired ({STATE_DIR} holds a credential)")
    else:
        pair = ["runner", "pair", args.url, "--code-file", "-", "--config", str(config_path)]
        if host.run(_as_runner(host, pair), stdin=code) != 0:
            raise Refused("pairing failed (above); nothing else was started")
    if host.run(["systemctl", "daemon-reload"]) != 0:
        raise Refused("`systemctl daemon-reload` failed")
    try:
        config.load(host.path(config_path))
    except config.ConfigError as exc:
        # A service started on this configuration exits 78 and is not restarted: enable it,
        # start it once the configuration is complete.
        if host.run(["systemctl", "enable", SERVICE]) != 0:
            raise Refused(f"`systemctl enable {SERVICE}` failed") from None
        _say(f"enabled {SERVICE}, not started: {config_path} is not complete yet:")
        for problem in exc.problems:
            _say(f"  {problem}")
        _say(
            f"next: add them to {config_path}, then `sudo systemctl start {SERVICE}` and "
            f"`sudo -u {USER} maity runner check --config {config_path}`"
        )
        return 0
    if host.run(["systemctl", "enable", "--now", SERVICE]) != 0:
        raise Refused(f"`systemctl enable --now {SERVICE}` failed")
    _say(f"started {SERVICE}")
    return host.run(_as_runner(host, ["runner", "check", "--config", str(config_path)]))


def cmd_uninstall(args: argparse.Namespace, host: Host | None = None) -> int:
    host = host or Host()
    if host.platform() != "linux":
        raise Refused("uninstall removes a systemd service: Linux only")
    if host.euid() != 0:
        raise Refused("uninstall removes a system service: run it with sudo")
    config_path = Path(args.config) if args.config else CONFIG
    unit = host.path(UNIT_PATH)
    if unit.exists():
        host.run(["systemctl", "disable", "--now", SERVICE])
        _say(f"stopped {SERVICE}")
    # The unit's KillMode=process leaves the agents running when the service stops; nothing
    # would supervise them once it is gone (cli/context/runner.md).
    if host.user_ids(USER) is not None and host.path(config_path).exists():
        stop = ["runner", "stop-all", "--config", str(config_path)]
        if host.run(_as_runner(host, stop)) != 0:
            _say(
                "could not stop every agent (above); `maity runner stop-all` as the user ends them"
            )
    if unit.exists():
        unit.unlink()
        _say(f"removed {UNIT_PATH}")
        host.run(["systemctl", "daemon-reload"])
    if not args.purge:
        _say(
            f"kept   {HOME} (state, credential, workspaces), {config_path} and user {USER}; "
            "--purge removes them"
        )
        return 0
    # The default configuration's directory is install's own; a file named by --config may
    # sit next to others, so only the file goes.
    for path in (HOME, CONFIG.parent if config_path == CONFIG else config_path):
        target = host.path(path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        else:
            continue
        _say(f"removed {path}")
    if host.user_ids(USER) is not None:
        if host.run(["userdel", USER]) != 0:
            raise Refused(f"could not remove the user {USER}")
        _say(f"removed user {USER}")
    _say("the hub still lists this runner: remove it under Runners in the dashboard")
    return 0


def _code(args: argparse.Namespace) -> str:
    if args.code_file is not None:
        if args.code_file == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.code_file).read_text(encoding="utf-8")
    else:
        text = args.code or ""
    code = text.strip()
    if not code:
        raise Refused(
            "the pairing code is empty (--code or --code-file; none is needed once paired)"
        )
    return code
