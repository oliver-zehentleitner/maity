"""Where the agents' commands run (runner design §5.4, §7.6).

`AsUser()` is the runner's own user on this host (the `single` layout): everything runs
directly. `AsUser(user)` is the `agent_user` layout: every command goes through
`sudo -n -u <user> --`, which resets the environment (§7.5), and every file the agents'
side needs is written as that user, so the runner's state directory and credential stay
out of the agents' reach. `Ssh(...)` is a host of the ssh backend: every command is a fixed
template sent over one `ssh` connection, each word quoted.

Files written for the agents are theirs: the OS user (or the host account) is the boundary
there, and a harness setting an agent changes only widens what that same user could do.
"""

from __future__ import annotations

import os
import pwd
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import state

TIMEOUT = 60.0
REMOTE_HOME = re.compile(r"^/[A-Za-z0-9._/-]*$")
SSH_UNREACHABLE = 255  # ssh's own exit code when the connection fails


class Unreachable(OSError):
    """An ssh target's host did not answer (ssh's exit 255)."""


@dataclass(frozen=True)
class AsUser:
    user: str | None = None  # None: the runner's own user (the `single` layout)

    @property
    def direct(self) -> bool:
        """Runs here, as the runner's own user: plain calls, plain files."""
        return not self.user

    @property
    def here(self) -> bool:
        """On this host (pids and paths mean the same to the runner)."""
        return True

    @property
    def maity(self) -> list[str]:
        """How the agents' side starts `maity`: this interpreter, isolated from the cwd."""
        return [sys.executable, "-I", "-m", "maity"]

    def runner_module(self, name: str) -> list[str]:
        """How the agents' side starts the runner's `loop` or `stub`: this interpreter, as
        for `maity`."""
        return [sys.executable, "-I", "-m", f"maity.runner.{name}"]

    def argv(self, argv: Sequence[str], env: dict[str, str] | None = None) -> list[str]:
        """`argv` for the agents' side; `env` is passed explicitly where sudo resets it."""
        if self.direct:
            return list(argv)
        pairs = [f"{key}={value}" for key, value in (env or {}).items()]
        return ["sudo", "-n", "-u", str(self.user), "--", *(["env", *pairs] if pairs else []),
                *argv]  # fmt: skip

    def run(
        self,
        argv: Sequence[str],
        env: dict[str, str] | None = None,
        input: str | None = None,
        cwd: Path | None = None,
        timeout: float = TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        local_env = {**os.environ, **env} if self.direct and env is not None else None
        return subprocess.run(  # noqa: S603 - argv lists from fixed templates
            self.argv(argv, None if self.direct else env),
            env=local_env,
            input=input,
            # Never the runner's terminal: a prompt would wait on the operator's keyboard.
            stdin=subprocess.DEVNULL if input is None else None,
            cwd=cwd if cwd is not None else (None if self.direct else "/"),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def home(self) -> Path:
        if self.direct:
            return Path.home()
        return Path(pwd.getpwnam(str(self.user)).pw_dir)

    def write(self, path: Path, text: str) -> Path:
        """A file 0600 for the agents' side."""
        if self.direct:
            return state.write_file(path, text)
        done = self.run(["install", "-D", "-m", "600", "/dev/stdin", str(path)], input=text)
        if done.returncode != 0:
            raise OSError(f"cannot write {path} for the agents: {done.stderr.strip()[:200]}")
        return path

    def mkdir(self, path: Path) -> None:
        if self.direct:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            return
        done = self.run(["mkdir", "-p", "-m", "700", str(path)])
        if done.returncode != 0:
            raise OSError(f"cannot create {path} for the agents: {done.stderr.strip()[:200]}")

    def read(self, path: Path, offset: int = 0) -> bytes:
        """The file's bytes from `offset` on."""
        if self.direct:
            with path.open("rb") as fh:
                fh.seek(offset)
                return fh.read()
        done = subprocess.run(  # noqa: S603 - fixed argv
            self.argv(["tail", "-c", f"+{offset + 1}", "--", str(path)]), capture_output=True,
            stdin=subprocess.DEVNULL, timeout=TIMEOUT,
            check=False,
        )  # fmt: skip
        if done.returncode != 0:
            raise OSError(f"cannot read {path} on the agents' side")
        return done.stdout

    def tree(self, path: Path) -> list[tuple[str, str, int]]:
        """Everything under a directory on the agents' side, which may be closed to the
        runner: (path inside it, `f`/`d`/`l` or another `find -printf %y` letter, size).
        Links are listed, never followed."""
        if self.direct:
            found: list[tuple[str, str, int]] = []
            for root, dirs, files in os.walk(path):  # does not descend into links
                for name in dirs + files:
                    full = Path(root) / name
                    mode = full.lstat()
                    kind = ("l" if stat.S_ISLNK(mode.st_mode) else "d" if stat.S_ISDIR(mode.st_mode)
                            else "f" if stat.S_ISREG(mode.st_mode) else "?")  # fmt: skip
                    found.append((str(full.relative_to(path)), kind, mode.st_size))
            return found
        done = self.run(["find", str(path), "-mindepth", "1", "-printf", "%y %s %P\\0"])
        if done.returncode != 0:
            raise OSError(f"cannot list {path} on the agents' side")
        entries = []
        for item in filter(None, done.stdout.split("\0")):
            kind, size, where = item.split(" ", 2)
            entries.append((where, kind, int(size)))
        return entries

    def exists(self, path: Path, kind: str = "-e") -> bool:
        """`test -e` (or `-f`, `-d`, `-L`) on the agents' side, which may be closed to the
        runner."""
        if self.direct:
            checks = {"-e": path.exists, "-f": path.is_file, "-d": path.is_dir,
                      "-L": path.is_symlink}  # fmt: skip
            return checks[kind]()
        return self.run(["test", kind, str(path)]).returncode == 0

    def link(self, target: Path, link: Path) -> None:
        if self.direct:
            if link.is_symlink() and link.resolve() == target.resolve():
                return
            if link.is_symlink() or link.exists():  # stale, dangling or another file
                link.unlink()
            link.symlink_to(target)
            return
        self.run(["ln", "-sfn", "--", str(target), str(link)])

    def remove_tree(self, path: Path) -> None:
        if self.direct:
            shutil.rmtree(path)
            return
        if self.run(["rm", "-rf", "--", str(path)]).returncode != 0:
            raise OSError(f"cannot remove {path} on the agents' side")

    def terminate(self, pid: int) -> None:
        """SIGTERM to a process group of the agents' side."""
        if self.direct:
            os.killpg(pid, signal.SIGTERM)
            return
        self.run(["kill", "-TERM", "--", f"-{pid}"])


RUNNER = AsUser()  # the `single` layout: the runner's own user


@dataclass(frozen=True)
class Ssh(AsUser):
    """A host of the ssh backend. Only the hosts in the configuration, only the runner's own
    known_hosts file with strict checking, no agent or X11 forwarding, and the operator's ssh
    agent (or a key file) used for this connection alone (§5.4)."""

    name: str = ""
    address: str = ""
    login: str = ""  # the remote user
    port: int = 22
    known_hosts: Path = Path()
    identity: str = "agent"  # "agent": the operator's SSH_AUTH_SOCK; otherwise a key file
    control_dir: Path = Path()

    @property
    def direct(self) -> bool:
        return False

    @property
    def here(self) -> bool:
        return False

    @property
    def maity(self) -> list[str]:
        return ["maity"]  # the host's own install, on its PATH

    def runner_module(self, name: str) -> list[str]:
        """The host's interpreter is not this one: its `maity`, through an internal
        subcommand (`maity runner loop`, `maity runner stub`)."""
        return ["maity", "runner", name]

    def ssh(self) -> list[str]:
        command = [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", f"UserKnownHostsFile={self.known_hosts}", "-o", "GlobalKnownHostsFile=/dev/null",
            "-o", "ControlMaster=auto", "-o", "ControlPersist=300",
            "-o", f"ControlPath={self.control_dir}/%C", "-o", "ConnectTimeout=15",
            # A dead link or a stuck host ends a call within 30 s, not at the timeout.
            "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=2",
            # Whatever the operator's ssh configuration says: no port forwarding into the
            # operator's network, no local command, for every agent on the host to use.
            "-o", "ClearAllForwardings=yes", "-o", "PermitLocalCommand=no",
            "-a", "-x", "-p", str(self.port),
        ]  # fmt: skip
        if self.identity != "agent":
            command += ["-o", "IdentitiesOnly=yes", "-i", self.identity]
        return [*command, f"{self.login}@{self.address}"]

    def argv(self, argv: Sequence[str], env: dict[str, str] | None = None) -> list[str]:
        """One remote command line: every word quoted, `env` set explicitly."""
        pairs = [f"{key}={value}" for key, value in (env or {}).items()]
        words = [*(["env", *pairs] if pairs else []), *argv]
        return [*self.ssh(), "--", " ".join(shlex.quote(word) for word in words)]

    def run(
        self,
        argv: Sequence[str],
        env: dict[str, str] | None = None,
        input: str | None = None,
        cwd: Path | None = None,
        timeout: float = TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        # The local ssh process keeps the runner's environment for SSH_AUTH_SOCK alone; the
        # remote command gets only `env`.
        return subprocess.run(  # noqa: S603 - argv from fixed templates, words quoted
            self.argv(argv, env), input=input, capture_output=True, text=True,
            stdin=subprocess.DEVNULL if input is None else None,  # never the operator's tty
            timeout=timeout, check=False,
        )  # fmt: skip

    def home(self) -> Path:
        done = self.run(["printenv", "HOME"])
        if done.returncode == SSH_UNREACHABLE:
            raise Unreachable(f"cannot reach {self.name}: {done.stderr.strip()[:200]}")
        home = done.stdout.strip()
        # The remote account is the agents': its shell start-up files can set HOME to
        # anything, and the runner builds paths and the attach hint from it.
        if done.returncode != 0 or not REMOTE_HOME.match(home) or ".." in home.split("/"):
            raise OSError(
                f"{self.name}: {self.login}'s home is not a plain absolute path "
                f"({home[:80]!r}); the runner refuses the host"
            )
        return Path(home)
