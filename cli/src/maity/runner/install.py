"""`maity runner install` and `uninstall`: the runner as a systemd system service.

`install` does the steps the shipped unit's header lists, as root: the `maity-runner`
system user and its directories, `/etc/maity-runner/runner.toml`, the unit with the path of
the `maity` that runs this command, pairing as that user, `systemctl enable`, and `maity
runner check`. Every call that touches the system goes through `Host`, so the tests run
without root or systemd (cli/context/runner.md).

Root works in directories the service user (and, in the `single` layout, every agent) can
write: nothing here follows a link there. Directories are opened with `O_NOFOLLOW` from the
parent's descriptor and changed through that descriptor; files are written to a temporary
file in a directory only root can write and renamed into place.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import tomllib
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


@dataclass(frozen=True)
class User:
    uid: int
    gid: int
    home: str


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

    def root_uid(self) -> int:
        """Who must own the directories install writes files into."""
        return 0

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def systemd_running(self) -> bool:
        return self.path(Path("/run/systemd/system")).is_dir()

    def user(self, name: str) -> User | None:
        import pwd  # POSIX only; the CLI imports this module on Windows too

        try:
            entry = pwd.getpwnam(name)
        except KeyError:
            return None
        return User(entry.pw_uid, entry.pw_gid, entry.pw_dir)

    def fchown(self, fd: int, uid: int, gid: int) -> None:
        os.fchown(fd, uid, gid)

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


def _systemd_word(word: str) -> str:
    """One `ExecStart=` argument, quoted for systemd: `\\` and `"` escaped, `%` (specifiers)
    and `$` (variables) doubled. A control character could end the line and add directives."""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in word):
        raise Refused(f"{word!r} has a control character; it cannot go into a unit")
    escaped = word.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped.replace("%", "%%").replace("$", "$$") + '"'


def unit_text(host: Host, config_path: Path) -> str:
    shipped = resources.files("maity.runner").joinpath(UNIT).read_text(encoding="utf-8")
    if SHIPPED_EXEC not in shipped:  # the shipped unit changed without this module
        raise Refused("the shipped unit has no ExecStart line this version can rewrite")
    words = [*host.maity(), "runner", "serve", "--config", str(config_path)]
    return shipped.replace(SHIPPED_EXEC, "ExecStart=" + " ".join(map(_systemd_word, words)))


def _say(text: str) -> None:
    print(text, file=sys.stderr)


def _config_path(args: argparse.Namespace) -> Path:
    """`--config`, absolute: the service and `runuser` start elsewhere, and `~` is root's."""
    if not args.config:
        return CONFIG
    path = Path(args.config)
    if not path.is_absolute():
        raise Refused(f"--config {args.config}: name it by its absolute path")
    return path


def _root_dir(host: Host, absolute: Path) -> Path:
    """The directory a root-owned file goes into: made if missing (0755), and refused when it
    is a link, not root's, or writable by others, who could swap the file after the write."""
    target = host.path(absolute)
    if not os.path.lexists(target):
        target.mkdir(parents=True)
        target.chmod(0o755)  # whatever root's umask is
    st = os.lstat(target)
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != host.root_uid():
        raise Refused(f"{absolute} is not a directory of root's; nothing was written into it")
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise Refused(f"{absolute} is writable by group or others; nothing was written into it")
    return target


def _write(host: Host, absolute: Path, text: str, force: bool) -> None:
    """Writes a root-owned file (0644); an existing different one is kept unless `force`.
    Never follows a link: a link or anything but a regular file there is refused."""
    directory = _root_dir(host, absolute.parent)
    target = directory / absolute.name
    if os.path.lexists(target):
        if not stat.S_ISREG(os.lstat(target).st_mode):
            raise Refused(f"{absolute} is a link or not a regular file; it was not touched")
        if target.read_text(encoding="utf-8") == text:
            _say(f"ok     {absolute}")
            return
        if not force:
            _say(f"kept   {absolute} (it differs; --force rewrites it)")
            return
    fd, temporary = tempfile.mkstemp(dir=directory, prefix=f".{absolute.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(text)
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
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


def _open_dir(name: str, parent_fd: int, shown: Path) -> int:
    """`name` below `parent_fd` as a directory descriptor, made 0700 if missing; a link or a
    file there is refused, so nothing below follows it."""
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
    except OSError:
        raise Refused(f"{shown} is a link or not a directory; move it away first") from None


def _user(host: Host) -> User:
    user = host.user(USER)
    if user is None:
        if os.path.lexists(host.path(HOME)):
            raise Refused(f"{HOME} exists, but the user {USER} does not; move it away first")
        argv = ["useradd", "--system", "--create-home", "--home-dir", str(HOME)]
        if host.run([*argv, "--shell", "/usr/sbin/nologin", USER]) != 0:
            raise Refused(f"could not create the system user {USER}")
        user = host.user(USER)
        if user is None:
            raise Refused(f"the system user {USER} was not created")
        _say(f"made   user {USER}")
    else:
        _say(f"ok     user {USER}")
    if user.home != str(HOME):
        raise Refused(f"the user {USER} has the home {user.home}, not {HOME}; not changed")
    # The parent of HOME is root's; HOME and below are the service user's, so every step
    # down goes through the descriptor of the one above it.
    parent = os.open(host.path(HOME.parent), os.O_RDONLY | os.O_DIRECTORY)
    try:
        home = _open_dir(HOME.name, parent, HOME)
    finally:
        os.close(parent)
    try:
        _own(host, home, user)
        for below in (STATE_DIR, WORKSPACES):
            fd = _open_dir(below.name, home, below)
            try:
                _own(host, fd, user)
            finally:
                os.close(fd)
    finally:
        os.close(home)
    return user


def _own(host: Host, fd: int, user: User) -> None:
    host.fchown(fd, user.uid, user.gid)
    os.fchmod(fd, 0o700)


def _configured_state_dir(host: Host, config_path: Path) -> Path:
    """`hub.state_dir` of an existing configuration (where pairing put the credential), or
    the one install writes."""
    target = host.path(config_path)
    if not os.path.lexists(target) or not stat.S_ISREG(os.lstat(target).st_mode):
        return STATE_DIR
    try:
        table = tomllib.loads(target.read_text(encoding="utf-8")).get("hub")
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError):
        return STATE_DIR
    value = table.get("state_dir") if isinstance(table, dict) else None
    return Path(value) if isinstance(value, str) and value.startswith("/") else STATE_DIR


def _incomplete(host: Host, config_path: Path) -> list[str]:
    """Why `serve` would refuse this configuration (exit 78), or nothing."""
    try:
        return config.unsupported(config.load(host.path(config_path)))
    except config.ConfigError as exc:
        return list(exc.problems)


def cmd_install(args: argparse.Namespace, host: Host | None = None) -> int:
    host = host or Host()
    _preconditions(host)
    config_path = _config_path(args)
    base = hub.hub_base(args.url)
    hub.pair_token(args.url)  # a pairing URL, checked before anything changes
    state_dir = _configured_state_dir(host, config_path)
    paired = state.has_credential(host.path(state_dir))
    code = None if paired else _code(args)
    unit = unit_text(host, config_path)  # refuses an unquotable path before any change
    _user(host)
    _write(host, config_path, starter_config(base), args.force)
    if host.run(_as_runner(host, ["--version"])) != 0:
        raise Refused(
            f"{USER} cannot run {host.maity()[0]}: install maity where every user can run it "
            "(`sudo pipx install --global maity`), then run install again"
        )
    _write(host, UNIT_PATH, unit, args.force)
    if paired:
        _say(f"ok     already paired ({state_dir} holds a credential)")
    else:
        pair = ["runner", "pair", args.url, "--code-file", "-", "--config", str(config_path)]
        if host.run(_as_runner(host, pair), stdin=code) != 0:
            raise Refused("pairing failed (above); nothing else was started")
    if host.run(["systemctl", "daemon-reload"]) != 0:
        raise Refused("`systemctl daemon-reload` failed")
    problems = _incomplete(host, config_path)
    if problems:
        # A service started on this configuration exits 78 and is not restarted: enable it,
        # start it once the configuration is complete.
        if host.run(["systemctl", "enable", SERVICE]) != 0:
            raise Refused(f"`systemctl enable {SERVICE}` failed")
        _say(f"enabled {SERVICE}, not started: {config_path} is not complete yet:")
        for problem in problems:
            _say(f"  {problem}")
        _say(
            f"next: fix them in {config_path}, then `sudo systemctl start {SERVICE}` and "
            f"`sudo -u {USER} maity runner check --config {config_path}`"
        )
        return 0
    if host.run(["systemctl", "enable", "--now", SERVICE]) != 0:
        raise Refused(f"`systemctl enable --now {SERVICE}` failed")
    _say(f"started {SERVICE}")
    return host.run(_as_runner(host, ["runner", "check", "--config", str(config_path)]))


def _remove(host: Host, absolute: Path, tree: bool) -> None:
    """Removes a directory tree (`tree`) or a regular file; a link is removed itself, never
    followed, and anything else is refused."""
    target = host.path(absolute)
    if not os.path.lexists(target):
        return
    mode = os.lstat(target).st_mode
    if stat.S_ISLNK(mode):
        target.unlink()
    elif tree and stat.S_ISDIR(mode):
        shutil.rmtree(target)  # does not follow links below it
    elif not tree and stat.S_ISREG(mode):
        target.unlink()
    else:
        raise Refused(f"{absolute} is not what install made; it was not removed")
    _say(f"removed {absolute}")


def cmd_uninstall(args: argparse.Namespace, host: Host | None = None) -> int:
    host = host or Host()
    if host.platform() != "linux":
        raise Refused("uninstall removes a systemd service: Linux only")
    if host.euid() != 0:
        raise Refused("uninstall removes a system service: run it with sudo")
    config_path = _config_path(args)
    user = host.user(USER)
    ours = user is not None and user.home == str(HOME)
    if args.purge and user is not None and not ours:
        raise Refused(f"the user {USER} has the home {user.home}, not {HOME}: not install's")
    unit = host.path(UNIT_PATH)
    if os.path.lexists(unit):
        host.run(["systemctl", "disable", "--now", SERVICE])
        _say(f"stopped {SERVICE}")
    # The unit's KillMode=process leaves the agents running when the service stops; nothing
    # would supervise them once it is gone (cli/context/runner.md).
    if ours and os.path.lexists(host.path(config_path)):
        try:
            config.load(host.path(config_path))
        except config.ConfigError:
            _say(
                f"{config_path} does not load, so `stop-all` cannot run: any agents the "
                "service started keep running until their tmux server ends"
            )
        else:
            stop = ["runner", "stop-all", "--config", str(config_path)]
            if host.run(_as_runner(host, stop)) != 0:
                _say("could not stop every agent (above); `maity runner stop-all` ends them")
    if os.path.lexists(unit):
        _remove(host, UNIT_PATH, tree=False)
        host.run(["systemctl", "daemon-reload"])
    if not args.purge:
        _say(
            f"kept   {HOME} (state, credential, workspaces), {config_path} and user {USER}; "
            "--purge removes them"
        )
        return 0
    _remove(host, HOME, tree=True)
    # The default configuration's directory is install's own; a file named by --config may
    # sit next to others, so only the file goes.
    if config_path == CONFIG:
        _remove(host, CONFIG.parent, tree=True)
    else:
        _remove(host, config_path, tree=False)
    if ours:
        if host.run(["userdel", USER]) != 0:
            raise Refused(f"could not remove the user {USER}")
        _say(f"removed user {USER}")
    _say("the hub still lists this runner: remove it under Runners in the dashboard")
    return 0


def _code(args: argparse.Namespace) -> str:
    try:
        if args.code_file == "-":
            text = sys.stdin.read()
        elif args.code_file is not None:
            text = Path(args.code_file).read_text(encoding="utf-8")
        else:
            text = args.code or ""
    except (OSError, UnicodeDecodeError) as exc:
        raise Refused(f"--code-file {args.code_file}: cannot be read ({exc})") from None
    code = text.strip()
    if not code:
        raise Refused(
            "the pairing code is empty (--code or --code-file; none is needed once paired)"
        )
    return code
