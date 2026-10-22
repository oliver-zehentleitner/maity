"""Running and writing as the agents' OS user (runner design §7.6, the `agent_user` layout).

In the `single` layout the agents are the runner's own user, and everything here runs
directly. In the `agent_user` layout every command for the agents goes through
`sudo -n -u <agent_user> --`, which resets the environment (§7.5), and every file the
agents' side needs is written as that user. The runner then owns its state directory and
credential alone: the agents, and any repository code they run, cannot read them.

Files written for the agents in that layout are theirs: the OS user is the boundary there,
and a harness setting an agent changes only widens what that same user could do anyway.
"""

from __future__ import annotations

import os
import pwd
import signal
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .. import state

TIMEOUT = 60.0


@dataclass(frozen=True)
class AsUser:
    user: str | None = None  # None: the runner's own user (the `single` layout)

    @property
    def prefix(self) -> list[str]:
        return ["sudo", "-n", "-u", self.user, "--"] if self.user else []

    def argv(self, argv: Sequence[str], env: dict[str, str] | None = None) -> list[str]:
        """`argv` as the agents' user; `env` is passed explicitly, since sudo resets it."""
        if not self.user:
            return list(argv)
        pairs = [f"{key}={value}" for key, value in (env or {}).items()]
        return [*self.prefix, *(["env", *pairs] if pairs else []), *argv]

    def run(
        self,
        argv: Sequence[str],
        env: dict[str, str] | None = None,
        input: str | None = None,
        cwd: Path | None = None,
        timeout: float = TIMEOUT,
    ) -> subprocess.CompletedProcess[str]:
        full_env = None
        if not self.user and env is not None:
            full_env = {**os.environ, **env}
        return subprocess.run(  # noqa: S603 - argv lists from fixed templates
            self.argv(argv, env if self.user else None),
            env=full_env,
            input=input,
            cwd=cwd if cwd is not None else ("/" if self.user else None),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def home(self) -> Path:
        if not self.user:
            return Path.home()
        return Path(pwd.getpwnam(self.user).pw_dir)

    def write(self, path: Path, text: str) -> Path:
        """A file 0600 for the agents' side: as the runner, or as the agents' user."""
        if not self.user:
            return state.write_file(path, text)
        done = self.run(["install", "-D", "-m", "600", "/dev/stdin", str(path)], input=text)
        if done.returncode != 0:
            raise OSError(f"cannot write {path} as {self.user}: {done.stderr.strip()[:200]}")
        return path

    def mkdir(self, path: Path) -> None:
        if not self.user:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            return
        done = self.run(["mkdir", "-p", "-m", "700", str(path)])
        if done.returncode != 0:
            raise OSError(f"cannot create {path} as {self.user}: {done.stderr.strip()[:200]}")

    def read(self, path: Path) -> bytes:
        if not self.user:
            return path.read_bytes()
        done = subprocess.run(  # noqa: S603 - fixed argv
            [*self.prefix, "cat", "--", str(path)],
            capture_output=True,
            timeout=TIMEOUT,
            check=False,
        )
        if done.returncode != 0:
            raise OSError(f"cannot read {path} as {self.user}")
        return done.stdout

    def tree(self, path: Path) -> list[tuple[str, str, int]]:
        """Everything under a directory on the agents' side, which may be closed to the
        runner: (path inside it, `f`/`d`/`l` or another `find -printf %y` letter, size).
        Links are listed, never followed."""
        if not self.user:
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

    def remove_tree(self, path: Path) -> None:
        if not self.user:
            import shutil

            shutil.rmtree(path)
            return
        done = self.run(["rm", "-rf", "--", str(path)])
        if done.returncode != 0:
            raise OSError(f"cannot remove {path} as {self.user}")

    def exists(self, path: Path, kind: str = "-e") -> bool:
        """`test -e` (or `-f`, `-d`) as the agents' user, who may own what the runner cannot
        look into."""
        if not self.user:
            checks = {"-e": path.exists, "-f": path.is_file, "-d": path.is_dir,
                      "-L": path.is_symlink}  # fmt: skip
            return checks[kind]()
        return self.run(["test", kind, str(path)]).returncode == 0

    def link(self, target: Path, link: Path) -> None:
        if not self.user:
            if link.is_symlink() and link.resolve() == target.resolve():
                return
            if link.is_symlink() or link.exists():  # stale, dangling or another file
                link.unlink()
            link.symlink_to(target)
            return
        self.run(["ln", "-sfn", "--", str(target), str(link)])

    def terminate(self, pid: int) -> None:
        """SIGTERM to a process group the agents' user owns."""
        if not self.user:
            os.killpg(pid, signal.SIGTERM)
            return
        self.run(["kill", "-TERM", "--", f"-{pid}"])


RUNNER = AsUser()  # the `single` layout: the runner's own user
