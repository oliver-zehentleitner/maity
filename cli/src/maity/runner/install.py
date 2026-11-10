"""`maity runner install` and `uninstall`: the runner as a systemd system service.

`install` does the steps the shipped unit's header lists, as root: the `maity-runner`
system user and its directories, `/etc/maity-runner/runner.toml`, the unit with the path of
the `maity` that runs this command, pairing as that user, `systemctl enable`, and `maity
runner check`. Every call that touches the system goes through `Host`, so the tests run
without root or systemd (cli/context/runner.md).

The paths are fixed: other paths are the manual steps of `maity runner unit`; the workspaces
a kept configuration names are the service user's and not checked. Root refuses what someone
else may have set up and puts only modes right. Every directory on the way to a file it writes
or removes must be a real directory of root's that nobody else can write, opened from `/` one
component at a time without following a link, and root's files there regular files of root's
that nobody else can write, checked on the descriptor they are read from; the service user's
directories must be real directories of that user's. Whatever is not as install would have
made it stops the command before any change; a mode that only differs is set back.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tomllib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
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
# Root's record that install made the account: outside the account's home, so neither the
# account nor anything running as it can write it. The account's comment is only a label.
RECORD = Path("/var/lib/maity-runner-install.json")
COMMENT = "Maity runner"
# What the shipped unit starts; install replaces it with the interpreter that runs this command.
SHIPPED_EXEC = "ExecStart=/usr/local/bin/maity runner serve --config /etc/maity-runner/runner.toml"


def _dir_flags() -> int:
    """A directory, opened without following a link. POSIX only, like everything that calls
    it: the CLI imports this module on Windows too, which has neither flag."""
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


class Refused(Exception):
    """Refused before anything changed, or at a step that cannot go on (exit 2)."""


@dataclass(frozen=True)
class User:
    uid: int
    gid: int
    home: str
    gecos: str


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
        return User(entry.pw_uid, entry.pw_gid, entry.pw_dir, entry.pw_gecos)

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


def unit_text(host: Host) -> str:
    shipped = resources.files("maity.runner").joinpath(UNIT).read_text(encoding="utf-8")
    if SHIPPED_EXEC not in shipped:  # the shipped unit changed without this module
        raise Refused("the shipped unit has no ExecStart line this version can rewrite")
    words = [*host.maity(), "runner", "serve", "--config", str(CONFIG)]
    return shipped.replace(SHIPPED_EXEC, "ExecStart=" + " ".join(map(_systemd_word, words)))


def _say(text: str) -> None:
    print(text, file=sys.stderr)


# Paths: a directory chain of root's from `/`, and the entries at its end.


@contextmanager
def _root_dir(host: Host, absolute: Path, create: bool) -> Iterator[int | None]:
    """A descriptor of `absolute`, opened from `/` one component at a time without following
    a link. Every component must be a directory of root's that group and others cannot write,
    so nobody else can rename or swap anything on the way. A missing one is made (0755) when
    `create`, else the descriptor is `None`. `/etc/maity-runner` is install's own and always
    0755, whatever root's umask made it, so the service user can read its configuration."""
    fd = os.open(host.root, os.O_RDONLY | os.O_DIRECTORY)
    shown = Path("/")
    try:
        for part in absolute.relative_to("/").parts:
            shown /= part
            made = False
            if create:
                try:
                    os.mkdir(part, 0o755, dir_fd=fd)
                    made = True
                except FileExistsError:
                    made = False
            try:
                below = os.open(part, _dir_flags(), dir_fd=fd)
            except FileNotFoundError:
                os.close(fd)
                fd = -1
                yield None
                return
            except OSError:
                raise Refused(
                    f"{shown} is a link or not a directory; nothing was changed"
                ) from None
            os.close(fd)
            fd = below
            st = os.fstat(fd)
            if st.st_uid != host.root_uid():
                raise Refused(f"{shown} is not a directory of root's; nothing was changed")
            if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH) and not made:
                raise Refused(f"{shown} is writable by group or others; nothing was changed")
            if create and (made or shown == CONFIG.parent):
                os.fchmod(fd, 0o755)
        yield fd
    finally:
        if fd >= 0:
            os.close(fd)


def _entry(fd: int | None, name: str) -> os.stat_result | None:
    if fd is None:
        return None
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _check_root_file(host: Host, st: os.stat_result, absolute: Path) -> None:
    """A file install trusts: a regular file of root's that group and others cannot write.
    A writable one may have been rewritten by anyone, the service user included."""
    if not stat.S_ISREG(st.st_mode) or st.st_uid != host.root_uid():
        raise Refused(f"{absolute} is not a regular file of root's; nothing was changed")
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise Refused(f"{absolute} is writable by group or others; nothing was changed")


def _root_file(host: Host, absolute: Path) -> bool:
    """Whether `absolute` exists; refused unless it is a file install trusts below a chain
    of root's."""
    with _root_dir(host, absolute.parent, create=False) as fd:
        st = _entry(fd, absolute.name)
    if st is None:
        return False
    _check_root_file(host, st, absolute)
    return True


def _read_root(host: Host, absolute: Path) -> str | None:
    """The text of a file install trusts, or `None` when there is none. Opened through its
    directory's descriptor without following a link or waiting on a pipe, and checked on the
    opened file itself, so what is read is what was checked."""
    with _root_dir(host, absolute.parent, create=False) as fd:
        if fd is None:
            return None
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            opened = os.open(absolute.name, flags, dir_fd=fd)
        except FileNotFoundError:
            return None
        except OSError:
            raise Refused(f"{absolute} is a link or cannot be read; nothing was changed") from None
        with os.fdopen(opened, encoding="utf-8") as f:
            _check_root_file(host, os.fstat(f.fileno()), absolute)
            try:
                return f.read()
            except UnicodeDecodeError:
                return ""


def _write(host: Host, absolute: Path, text: str, force: bool) -> None:
    """Writes a root-owned file (0644) through its directory's descriptor: a temporary file
    made there, renamed over the name. An existing different one is kept unless `force`."""
    with _root_dir(host, absolute.parent, create=True) as fd:
        if fd is None:  # checked above; gone since
            raise Refused("a directory install checked has gone; nothing more was changed")
        st = _entry(fd, absolute.name)
        if st is not None:
            current = _read_root(host, absolute)
            same = current == text
            if same and stat.S_IMODE(st.st_mode) == 0o644:
                _say(f"ok     {absolute}")
                return
            if not same and not force:
                _say(f"kept   {absolute} (it differs; --force rewrites it)")
                return
        temporary = f".{absolute.name}.{secrets.token_hex(6)}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        try:
            with os.fdopen(os.open(temporary, flags, 0o644, dir_fd=fd), "w") as handle:
                os.fchmod(handle.fileno(), 0o644)
                handle.write(text)
            os.replace(temporary, absolute.name, src_dir_fd=fd, dst_dir_fd=fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=fd)
            except FileNotFoundError:
                pass
            raise
    _say(f"wrote  {absolute}")


def _remove(host: Host, absolute: Path, tree: bool) -> None:
    """Removes a regular file of root's, or (`tree`) the directory `absolute`, through the
    descriptor of its parent; a tree is removed without following a link below it."""
    with _root_dir(host, absolute.parent, create=False) as fd:
        st = _entry(fd, absolute.name)
        if fd is None or st is None:
            return
        if tree and stat.S_ISDIR(st.st_mode):
            shutil.rmtree(absolute.name, dir_fd=fd)
        elif not tree and stat.S_ISREG(st.st_mode):
            os.unlink(absolute.name, dir_fd=fd)
        else:
            raise Refused(f"{absolute} is not what install made; nothing more was removed")
    _say(f"removed {absolute}")


# The service user: its account, root's record of it, its directories.


def _ours(host: Host, user: User) -> bool:
    """Made by install: root's record names this account's uid and home."""
    text = _read_root(host, RECORD)
    if text is None:
        return False
    try:
        record = json.loads(text)
    except ValueError:
        return False
    return (
        isinstance(record, dict)
        and record.get("user") == USER
        and record.get("uid") == user.uid
        and record.get("home") == str(HOME) == user.home
    )


def _check_user(host: Host) -> User | None:
    """The account and its directories as install would have made them, or no account and
    no home; refused otherwise. Changes nothing."""
    user = host.user(USER)
    with _root_dir(host, HOME.parent, create=False) as parent:
        home = _entry(parent, HOME.name)
        if user is None:
            if home is not None:
                raise Refused(f"{HOME} exists, but the user {USER} does not; move it away first")
            return None
        if not _ours(host, user):
            raise Refused(
                f"a user {USER} exists that install did not make (no record in {RECORD}); "
                "remove or rename it first, install does not take over an account"
            )
        if home is None:
            return user
        _their_dir(host, home, HOME, user)
        if parent is None:  # checked above; gone since
            raise Refused("a directory install checked has gone; nothing more was changed")
        fd = os.open(HOME.name, _dir_flags(), dir_fd=parent)
        try:
            for below in (STATE_DIR, WORKSPACES):
                st = _entry(fd, below.name)
                if st is not None:
                    _their_dir(host, st, below, user)
        finally:
            os.close(fd)
    return user


def _their_dir(host: Host, st: os.stat_result, shown: Path, user: User) -> None:
    if not stat.S_ISDIR(st.st_mode):
        raise Refused(f"{shown} is a link or not a directory; move it away first")
    if st.st_uid != user.uid:
        raise Refused(f"{shown} does not belong to {USER}; nothing was changed")


def _make_user(host: Host) -> User:
    argv = ["useradd", "--system", "--create-home", "--home-dir", str(HOME)]
    argv += ["--comment", COMMENT, "--shell", "/usr/sbin/nologin", USER]
    if host.run(argv) != 0:
        raise Refused(f"could not create the system user {USER}")
    user = host.user(USER)
    if user is None:
        raise Refused(f"the system user {USER} was not created")
    record = {
        "user": USER,
        "uid": user.uid,
        "home": str(HOME),
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _write(host, RECORD, json.dumps(record) + "\n", force=True)
    _say(f"made   user {USER}")
    return user


def _dirs(host: Host, user: User) -> None:
    """HOME, its state and workspaces: each opened from the one above without following a
    link, made if missing, and set to the user and 0700 through its own descriptor."""
    with _root_dir(host, HOME.parent, create=False) as parent:
        if parent is None:  # checked above; gone since
            raise Refused("a directory install checked has gone; nothing more was changed")
        home = _open_dir(host, HOME.name, parent, HOME, user)
    try:
        for below in (STATE_DIR, WORKSPACES):
            os.close(_open_dir(host, below.name, home, below, user))
    finally:
        os.close(home)


def _open_dir(host: Host, name: str, parent_fd: int, shown: Path, user: User) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
        made = True
    except FileExistsError:
        made = False
    try:
        fd = os.open(name, _dir_flags(), dir_fd=parent_fd)
    except OSError:
        raise Refused(f"{shown} is a link or not a directory; move it away first") from None
    try:
        if made:
            host.fchown(fd, user.uid, user.gid)
        else:
            _their_dir(host, os.fstat(fd), shown, user)
        os.fchmod(fd, 0o700)
    except BaseException:
        os.close(fd)
        raise
    return fd


# install


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


def _check_state_dir(host: Host, base: str, force: bool) -> None:
    """The configuration install leaves in place, its own (written now) or the existing one
    kept, must keep the credential in the fixed state directory: install pairs and checks
    there, and nowhere else. Resolved as `serve` resolves it for the service user: `~` is
    that user's HOME, the default as config.py has it."""
    text = _read_root(host, CONFIG)
    if text is None:
        return
    if force or text == starter_config(base):
        return
    try:
        table = tomllib.loads(text).get("hub")
    except tomllib.TOMLDecodeError:
        raise Refused(f"{CONFIG} does not parse; fix it, or --force writes install's own") from None
    value = table.get("state_dir") if isinstance(table, dict) else None
    value = config.DEFAULT_STATE_DIR if value is None else value
    if not isinstance(value, str):
        raise Refused(f"{CONFIG}: hub.state_dir is not a path; fix it, or --force")
    if value == "~" or value.startswith("~/"):
        resolved = HOME / value[2:]
    elif value.startswith("/"):
        resolved = Path(value)
    else:
        raise Refused(f"{CONFIG}: hub.state_dir {value!r} is not absolute; fix it, or --force")
    if resolved != STATE_DIR:
        raise Refused(
            f"{CONFIG} keeps the credential in {resolved}; install uses only {STATE_DIR} "
            "(--force writes its own configuration; other paths are the manual steps of "
            "`maity runner unit`)"
        )


def _paired(host: Host, user: User | None) -> bool:
    """Whether the fixed state directory holds a credential, read as everything here is:
    each directory opened without following a link, the credential a regular file of the
    service user's. A link or another owner there stops install before any change."""
    if user is None:
        return False  # no account, no home (_check_user): nothing paired
    with _root_dir(host, HOME.parent, create=False) as parent:
        home = _entry(parent, HOME.name)
        if parent is None or home is None:
            return False
        fd = os.open(HOME.name, _dir_flags(), dir_fd=parent)
    try:
        if _entry(fd, STATE_DIR.name) is None:
            return False
        try:
            below = os.open(STATE_DIR.name, _dir_flags(), dir_fd=fd)
        except OSError:
            raise Refused(f"{STATE_DIR} is a link or not a directory; move it away first") from None
        try:
            st = _entry(below, state.CREDENTIAL_FILE)
        finally:
            os.close(below)
    finally:
        os.close(fd)
    if st is None:
        return False
    if not stat.S_ISREG(st.st_mode) or st.st_uid != user.uid:
        shown = STATE_DIR / state.CREDENTIAL_FILE
        raise Refused(f"{shown} is a link or not a file of {USER}'s; nothing was changed")
    return True


def _incomplete(host: Host) -> list[str]:
    """Why `serve` would refuse this configuration (exit 78), or nothing."""
    try:
        return config.unsupported(config.load(host.path(CONFIG)))
    except config.ConfigError as exc:
        return list(exc.problems)


def cmd_install(args: argparse.Namespace, host: Host | None = None) -> int:
    host = host or Host()
    _preconditions(host)
    base = hub.hub_base(args.url)
    hub.pair_token(args.url)  # a pairing URL, checked before anything changes
    # Everything below is checked before the first change.
    unit = unit_text(host)  # refuses an unquotable path
    for path in (CONFIG, UNIT_PATH, RECORD):
        _root_file(host, path)
    user = _check_user(host)
    _check_state_dir(host, base, args.force)
    paired = _paired(host, user)
    code = None if paired else _code(args)
    if user is None:
        user = _make_user(host)
    else:
        _say(f"ok     user {USER}")
    _dirs(host, user)
    _write(host, CONFIG, starter_config(base), args.force)
    if host.run(_as_runner(host, ["--version"])) != 0:
        raise Refused(
            f"{USER} cannot run {host.maity()[0]}: install maity where every user can run it "
            "(`sudo pipx install --global maity`), then run install again"
        )
    if host.run(["runuser", "-u", USER, "--", "test", "-r", str(CONFIG)]) != 0:
        raise Refused(f"{USER} cannot read {CONFIG}; let it traverse that directory")
    _write(host, UNIT_PATH, unit, args.force)
    if paired:
        _say(f"ok     already paired ({STATE_DIR} holds a credential)")
    else:
        pair = ["runner", "pair", args.url, "--code-file", "-", "--config", str(CONFIG)]
        if host.run(_as_runner(host, pair), stdin=code) != 0:
            raise Refused("pairing failed (above); nothing else was started")
    if host.run(["systemctl", "daemon-reload"]) != 0:
        raise Refused("`systemctl daemon-reload` failed")
    problems = _incomplete(host)
    if problems:
        # A service started on this configuration exits 78 and is not restarted: enable it,
        # start it once the configuration is complete.
        if host.run(["systemctl", "enable", SERVICE]) != 0:
            raise Refused(f"`systemctl enable {SERVICE}` failed")
        _say(f"enabled {SERVICE}, not started: {CONFIG} is not complete yet:")
        for problem in problems:
            _say(f"  {problem}")
        _say(
            f"next: fix them in {CONFIG}, then `sudo systemctl start {SERVICE}` and "
            f"`sudo -u {USER} maity runner check --config {CONFIG}`"
        )
        return 0
    if host.run(["systemctl", "enable", "--now", SERVICE]) != 0:
        raise Refused(f"`systemctl enable --now {SERVICE}` failed")
    _say(f"started {SERVICE}")
    return host.run(_as_runner(host, ["runner", "check", "--config", str(CONFIG)]))


# uninstall


def cmd_uninstall(args: argparse.Namespace, host: Host | None = None) -> int:
    host = host or Host()
    if host.platform() != "linux":
        raise Refused("uninstall removes a systemd service: Linux only")
    if host.euid() != 0:
        raise Refused("uninstall removes a system service: run it with sudo")
    # Checked before anything changes: only what install manages, as install would have it.
    user = host.user(USER)
    ours = user is not None and _ours(host, user)
    if args.purge and user is not None and not ours:
        raise Refused(f"the user {USER} was not made by install; --purge changes nothing")
    has_unit = _root_file(host, UNIT_PATH)
    has_config = _usable_config(host, args.force)
    # A user install made whose userdel succeeded on an earlier --purge that stopped later:
    # root's record still names it, so this --purge may finish removing what install made.
    leftover = user is None and _record_left(host)
    if ours:
        _check_user(host)
    elif args.purge and not leftover:
        with _root_dir(host, HOME.parent, create=False) as parent:
            if _entry(parent, HOME.name) is not None:
                raise Refused(f"{HOME} exists, but install made no user {USER}; nothing changed")
    # The unit's KillMode=process leaves the agents running when the service stops; nothing
    # would supervise them once it is gone (cli/context/runner.md). Not knowing whether any
    # run stops the removal as a failed stop-all does, and is known before the first change.
    stop_agents = (has_unit or ours) and _can_stop_agents(args, host, ours, has_config)
    if has_unit:
        if host.run(["systemctl", "disable", "--now", SERVICE]) != 0:
            _halt(args, f"`systemctl disable --now {SERVICE}` failed")
        else:
            _say(f"stopped {SERVICE}")
    if stop_agents:
        if host.run(_as_runner(host, ["runner", "stop-all", "--config", str(CONFIG)])) != 0:
            _halt(args, "`maity runner stop-all` could not stop every agent (above)")
        else:
            _say("stopped the agents")
    failed = False
    if has_unit:
        _remove(host, UNIT_PATH, tree=False)
        if host.run(["systemctl", "daemon-reload"]) != 0:
            _say("`systemctl daemon-reload` failed; run it once more")
            failed = True
    if not args.purge:
        _say(
            f"kept   {HOME} (state, credential, workspaces), {CONFIG} and user {USER}; "
            "--purge removes them"
        )
        return 1 if failed else 0
    # The account first: a userdel that fails (a process of the user's still running) leaves
    # everything as it was, and the next --purge starts over.
    if ours:
        if host.run(["userdel", USER]) != 0:
            raise Refused(f"could not remove the user {USER}; nothing more was removed")
        _say(f"removed user {USER}")
    _remove(host, HOME, tree=True)
    _remove(host, CONFIG.parent, tree=True)
    if ours or leftover:
        _remove(host, RECORD, tree=False)
    _say("the hub still lists this runner: remove it under Runners in the dashboard")
    return 1 if failed else 0


def _record_left(host: Host) -> bool:
    """Root's record of install's account, with no such account any more."""
    text = _read_root(host, RECORD)
    try:
        record = json.loads(text) if text is not None else None
    except ValueError:
        return False
    return (
        isinstance(record, dict) and record.get("user") == USER and record.get("home") == str(HOME)
    )


def _can_stop_agents(args: argparse.Namespace, host: Host, ours: bool, has_config: bool) -> bool:
    """Whether `stop-all` can run, checked before any change: when it cannot, uninstall stops
    here, or with `--force` goes on without it."""
    if not ours:
        _halt(args, f"no user {USER} of install's, so `stop-all` cannot run as it")
    elif not has_config:
        _halt(args, f"{CONFIG} is missing or not usable, so `stop-all` cannot find the agents")
    elif not _loads(host):
        _halt(
            args,
            f"{CONFIG} does not load, so `stop-all` cannot find the agents (if the service "
            "never ran, there are none)",
        )
    else:
        return True
    return False


def _usable_config(host: Host, force: bool) -> bool:
    """Whether the configuration is there to read: a regular file of root's that group and
    others cannot write. Anything else at its path stops uninstall before any change, or with
    `--force` is never read."""
    with _root_dir(host, CONFIG.parent, create=False) as fd:
        st = _entry(fd, CONFIG.name)
    if st is None:
        return False
    if (
        stat.S_ISREG(st.st_mode)
        and st.st_uid == host.root_uid()
        and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        return True
    what = f"{CONFIG} is a link, not a regular file of root's, or writable by others"
    if not force:
        raise Refused(f"{what}; nothing was changed (--force goes on without reading it)")
    _say(f"{what}; going on without reading it (--force)")
    return False


def _loads(host: Host) -> bool:
    try:
        config.load(host.path(CONFIG))
    except config.ConfigError:
        return False
    return True


def _halt(args: argparse.Namespace, what: str) -> None:
    """The agents may still run: removing the unit or the state now would leave them on files
    that are gone. `--force` goes on anyway."""
    if not args.force:
        raise Refused(f"{what}; nothing was removed (--force removes it anyway)")
    _say(f"{what}; going on (--force)")


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
