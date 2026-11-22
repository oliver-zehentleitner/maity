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

import errno
import json
import os
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
from typing import Any

from .. import state
from . import limitread, scratchop, skillop

TIMEOUT = 60.0
# A read on the agents' side: a few kilobytes, or a log's next chunk.
READ_TIMEOUT = 20.0
# `write` on the agents' side: $1 the directory, $2 the file; the text on stdin. A link at the
# path is removed first (`mv` would otherwise move into a linked directory), a directory there
# is refused, and the temporary file is removed when a step fails. Every `--` comes before the
# first operand: BSD tools read no options after it, so `chmod 600 -- f` names a file `--`.
_WRITE = (
    'mkdir -p -m 700 -- "$1" || exit 1; '
    'if [ -L "$2" ]; then rm -f -- "$2" || exit 1; '
    'elif [ -d "$2" ]; then echo "$2 is a directory" >&2; exit 1; fi; '
    't=$(mktemp "$2.XXXXXX") || exit 1; '
    'if cat > "$t" && chmod -- 600 "$t" && mv -f -- "$t" "$2"; then exit 0; fi; '
    'rm -f -- "$t"; exit 1'
)
REMOTE_HOME = re.compile(r"^/[A-Za-z0-9._/-]*$")
SSH_UNREACHABLE = 255  # ssh's own exit code when the connection fails


def shell_quote(word: str) -> str:
    """`shlex.quote`, and a word that starts with `=` quoted too: `shlex.quote` leaves it bare
    (`=` is safe in POSIX sh), but zsh expands a bare `=name` to the path of the command `name`
    and fails when there is none, so an exact tmux target (`=maity_p_c`) would not reach tmux."""
    if word.startswith("="):
        return "'" + word.replace("'", "'\"'\"'") + "'"
    return shlex.quote(word)


def shell_join(words: Sequence[str]) -> str:
    """`shlex.join` with `shell_quote`: one line for a POSIX shell or zsh."""
    return " ".join(shell_quote(word) for word in words)


class Unreachable(OSError):
    """An ssh target's host did not answer (ssh's exit 255)."""


# What a stat may answer for a path that is simply not there (none, a file on the way, a loop
# of links), as pathlib's predicates read it up to Python 3.13. Any other error, a directory
# that cannot be searched above all, is not "not there" (tsk-0tje3vzzedtx).
ABSENT = (errno.ENOENT, errno.ENOTDIR, errno.ELOOP)


def stat_mode(path: Path, *, follow: bool = True) -> int | None:
    """`st_mode` of `path` (through links with `follow`), None when nothing is there; every
    other OSError raises. A check that must fail closed decides with this, never with
    `is_dir()`/`exists()`/`is_symlink()`: from Python 3.14 those answer False for a path
    below a directory that cannot be searched instead of raising, and the check would take
    what it cannot see for absent (tsk-0tje3vzzedtx)."""
    try:
        return (os.stat if follow else os.lstat)(path).st_mode
    except OSError as exc:
        if exc.errno in ABSENT:
            return None
        raise


def present(path: Path, kind: str = "-e") -> bool:
    """`test -e` (`-f`, `-d`, `-L`) on the runner's own side, failing closed: absent is False,
    any other error raises (stat_mode)."""
    mode = stat_mode(path, follow=kind != "-L")
    if mode is None:
        return False
    check = {"-e": lambda m: True, "-f": stat.S_ISREG, "-d": stat.S_ISDIR, "-L": stat.S_ISLNK}
    return bool(check[kind](mode))


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
        import pwd  # POSIX only, and every maity command imports this module

        return Path(pwd.getpwnam(str(self.user)).pw_dir)

    def uid(self) -> int:
        """The uid the agents run as: the runner's own (`single`) or the agents' user's
        (`agent_user`). agy's scratch under `/tmp` is owned by and reachable only to this uid
        (scratchop.tmp_make). OSError when the host has no uid or the user is unknown."""
        if self.direct:
            getuid = getattr(os, "getuid", None)
            if getuid is None:
                raise OSError("this system has no uid; no /tmp scratch here")
            return int(getuid())
        import pwd  # POSIX only, and every maity command imports this module

        try:
            return pwd.getpwnam(str(self.user)).pw_uid
        except KeyError:
            raise OSError(f"the agents' user {self.user} is not known here") from None

    def write(self, path: Path, text: str) -> Path:
        """A file 0600 for the agents' side; the file's own directory is made 0700 if missing.
        Tools BSD, macOS and GNU all have (`sh`, `mkdir`, `mktemp`, `cat`, `chmod`, `mv`), and
        no `install`: GNU's `-D` (make the missing parents) is not the same everywhere; some
        BSD and macOS versions refuse `-D`, others give it another meaning. A temporary file
        next to the path is renamed over it. A link planted at the path, to a file or a
        directory, is replaced, not followed; a directory at the path is refused."""
        if self.direct:
            return state.write_file(path, text)
        done = self.run(["sh", "-c", _WRITE, "sh", str(path.parent), str(path)], input=text)
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

    def tighten(self, path: Path) -> None:
        """The directory `path` made 0700, also when it exists already with looser bits:
        `mkdir -p -m 700` and `Path.mkdir(mode=0o700, parents=True)` give the mode to the last
        directory only, and a parent made under a umask of 002 is 0775, which `maity gh`'s lead
        commands refuse (`ghpr.owned_layout`, review A1758 of #2054). Only a real directory:
        chmod follows a link, so a link in its place is refused first (security leg on #2054;
        owned_layout refuses one anyway, this keeps the chmod from touching what it names)."""
        if self.direct:
            if not stat.S_ISDIR(os.lstat(path).st_mode):
                raise OSError(f"cannot make {path} private for the agents: not a directory")
            os.chmod(path, 0o700)
            return
        # find's -type tests the entry itself, never what a link names.
        seen = self.run(["find", str(path), "-maxdepth", "0", "-type", "d"])
        if seen.returncode != 0 or seen.stdout.strip() != str(path):
            raise OSError(f"cannot make {path} private for the agents: not a directory")
        done = self.run(["chmod", "700", str(path)])
        if done.returncode != 0:
            raise OSError(f"cannot make {path} private for the agents: {done.stderr.strip()[:200]}")

    def read(self, path: Path, offset: int = 0, *, limit: int, under: Path) -> bytes:
        """At most `limit` bytes of the file from `offset` on: a regular file only, reached
        from `under` (the clone, the agents' files, their home) without following a link on
        the way, never waiting on a FIFO (limitread), within READ_TIMEOUT on the agents' side.
        OSError otherwise; limitread.Behind for an offset past the end."""
        if self.direct:
            return limitread.take(str(path), offset, limit, under=str(under))
        argv = [*self.runner_module("limitread"), "--under", str(under), "--bytes", str(limit),
                "--offset", str(offset), str(path)]  # fmt: skip
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv
                self.argv(argv, self.module_env()), capture_output=True,
                stdin=subprocess.DEVNULL, timeout=READ_TIMEOUT, check=False,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise OSError(f"reading {path} on the agents' side did not end in time") from None
        if done.returncode == limitread.BEHIND:
            raise limitread.Behind(f"{path} is shorter than {offset} bytes")
        if done.returncode != 0 or len(done.stdout) > limit:
            raise OSError(f"cannot read {path} on the agents' side")
        return done.stdout

    def read_whole(self, path: Path, limit: int, *, under: Path) -> bytes:
        """The whole file, as `read` reads it; OSError when it holds more than `limit` bytes."""
        data = self.read(path, limit=limit + 1, under=under)
        if len(data) > limit:
            raise OSError(f"{path} is larger than {limit} bytes")
        return data

    def module_env(self) -> dict[str, str] | None:
        """The environment the runner's own modules get on the agents' side: none here, where
        `runner_module` names this interpreter."""
        return None

    def tree(self, path: Path) -> list[tuple[str, str, int]]:
        """Everything under a directory on the agents' side, which may be closed to the
        runner: (path inside it, `f`/`d`/`l` or another `find -printf %y` letter, size).
        Links are listed, never followed."""
        if self.direct:
            found: list[tuple[str, str, int]] = []

            def unreadable(exc: OSError) -> None:
                raise exc  # an unlisted directory would look empty

            for root, dirs, files in os.walk(path, onerror=unreadable):  # no links followed
                for name in dirs + files:
                    full = Path(root) / name
                    mode = full.lstat()
                    kind = ("l" if stat.S_ISLNK(mode.st_mode) else "d" if stat.S_ISDIR(mode.st_mode)
                            else "f" if stat.S_ISREG(mode.st_mode) else "?")  # fmt: skip
                    found.append((full.relative_to(path).as_posix(), kind, mode.st_size))
            return found
        try:
            done = self.run(["find", str(path), "-mindepth", "1", "-printf", "%y %s %P\\0"])
        except subprocess.TimeoutExpired:
            raise OSError(f"listing {path} on the agents' side did not end in time") from None
        if done.returncode != 0:
            raise OSError(f"cannot list {path} on the agents' side")
        entries = []
        for item in filter(None, done.stdout.split("\0")):
            kind, size, where = item.split(" ", 2)
            entries.append((where, kind, int(size)))
        return entries

    def entries(self, path: Path, depth: int) -> list[tuple[str, str]]:
        """The entries exactly `depth` levels below a directory on the agents' side, which may
        be closed to the runner (the scratch holder is the agents' user's, 0700): (path inside
        it, `d`/`l`/`f`/`?`). Links are listed, never followed, and nothing deeper is read.
        OSError when a directory on the way cannot be listed: an unlisted one would look empty
        (gc's scratch listing, the review of #2112)."""
        if self.direct:
            level = [(path, "")]
            for step in range(depth):
                if step:  # only a real directory is gone into, never through a link
                    level = [(p, r) for p, r in level if stat.S_ISDIR(p.lstat().st_mode)]
                below: list[tuple[Path, str]] = []
                for at, rel in level:
                    with os.scandir(at) as listing:
                        below += [(Path(item.path), rel + item.name) for item in listing]
                level = [(p, r + "/") if step < depth - 1 else (p, r) for p, r in below]
            found = []
            for full, rel in level:
                mode = full.lstat().st_mode
                kind = ("l" if stat.S_ISLNK(mode) else "d" if stat.S_ISDIR(mode)
                        else "f" if stat.S_ISREG(mode) else "?")  # fmt: skip
                found.append((rel, kind))
            return found
        # A trailing `/`, so a start path that is itself a link (a linked workspaces root) is
        # gone into, as os.scandir does on the direct side; below it no link is (A2056).
        start = str(path) if str(path).endswith("/") else f"{path}/"
        argv = ["find", start, "-mindepth", str(depth), "-maxdepth", str(depth),
                "-printf", "%y %P\\0"]  # fmt: skip
        try:
            done = self.run(argv)
        except subprocess.TimeoutExpired:
            raise OSError(f"listing {path} on the agents' side did not end in time") from None
        if done.returncode != 0:
            raise OSError(f"cannot list {path} on the agents' side")
        listed = []
        for item in filter(None, done.stdout.split("\0")):
            kind, where = item.split(" ", 1)
            listed.append((where, kind if kind in ("d", "l", "f") else "?"))
        return listed

    def inode(self, path: Path) -> int:
        """The inode of `path` itself on the agents' side, a link not followed: `ls -di`,
        which BSD, macOS and GNU all print the same way (POSIX follows no link named as an
        operand without -H or -L)."""
        if self.direct:
            return os.lstat(path).st_ino
        done = self.run(["ls", "-di", "--", str(path)])
        number = done.stdout.split(maxsplit=1)[0] if done.stdout.strip() else ""
        if done.returncode != 0 or not number.isdigit():
            raise OSError(f"cannot read the inode of {path} on the agents' side")
        return int(number)

    def exists(self, path: Path, kind: str = "-e") -> bool:
        """`test -e` (or `-f`, `-d`, `-L`) on the agents' side, which may be closed to the
        runner. On the runner's own side with stat (`present`): absent is False, and a path it
        cannot look at raises, as pathlib's predicates did up to Python 3.13, so no caller
        takes what it cannot see for absent (tsk-0tje3vzzedtx)."""
        if self.direct:
            return present(path, kind)
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

    def scratch(self, op: str, under: Path, path: Path) -> dict[str, Any]:
        """A placement's scratch made, measured or removed on the agents' side (scratchop),
        every directory from `under` (the workspaces root) opened without following a link.
        scratchop.OnTheWay when one on the way is a link; OSError when it fails otherwise."""
        if self.direct:
            return scratchop.run(op, str(under), str(path))
        done = self.run([*self.runner_module("scratchop"), op, "--under", str(under), str(path)])
        if done.returncode == scratchop.LINK:
            raise scratchop.OnTheWay(f"{path}: a link or no directory on the way; nothing done")
        if done.returncode == 2 and op == "holder":  # a host's `maity` that predates the op
            raise scratchop.Unsupported(f"host maity has no holder op: {done.stderr.strip()[:200]}")
        if done.returncode != 0:
            raise OSError(f"scratch {op} {path} failed: {done.stderr.strip()[:200]}")
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            raise OSError(f"scratch {op} {path}: no answer") from None
        if not isinstance(answer, dict):
            raise OSError(f"scratch {op} {path}: no answer")
        return answer

    def pg(self, op: str, under: Path, path: Path) -> dict[str, Any]:
        """The test clusters' password holder or a placement's file in it, made (`make`) or
        removed (`remove`) on the agents' side (scratchop.pg_make, pg_remove), opened from
        `under` without following a link. scratchop.OnTheWay for a link or another user's
        holder; OSError when it fails otherwise, a host whose `maity` predates the op included."""
        if self.direct:
            return (scratchop.pg_make if op == "make" else scratchop.pg_remove)(
                str(under), str(path)
            )
        argv = [*self.runner_module("scratchop"), f"pg{op}", "--under", str(under), str(path)]
        done = self.run(argv)
        if done.returncode == scratchop.LINK:
            raise scratchop.OnTheWay(f"{path}: a link or another user's directory; not used")
        if done.returncode == 2:  # a host's `maity` that predates the op: it made none either
            raise scratchop.Unsupported(f"host maity has no pg ops: {done.stderr.strip()[:200]}")
        if done.returncode != 0:
            raise OSError(f"pg {op} {path} failed: {done.stderr.strip()[:200]}")
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            raise OSError(f"pg {op} {path}: no answer") from None
        if not isinstance(answer, dict):
            raise OSError(f"pg {op} {path}: no answer")
        return answer

    def tmp_scratch(self, op: str, path: Path) -> dict[str, Any]:
        """A placement's `/tmp` scratch (agy) made, measured or removed on the agents' side,
        or (`op` "parent") the per-user parent created or adopted: the per-user parent (0700,
        owned by the agents' user) and the per-placement leaf opened without following a link
        and checked owned by the uid the agents run as (os.getuid there). scratchop.OnTheWay for
        a link, a directory another user holds, or a leaf that already exists; OSError when it
        fails otherwise."""
        if self.direct:
            if op == "parent":
                return scratchop.tmp_parent_make(str(path))
            return scratchop.tmp_run(op, str(path))
        done = self.run([*self.runner_module("scratchop"), f"tmp{op}", str(path)])
        if done.returncode == scratchop.LINK:
            raise scratchop.OnTheWay(
                f"{path}: a link, a foreign-owned or pre-existing directory; nothing done"
            )
        if done.returncode != 0:
            raise OSError(f"tmp scratch {op} {path} failed: {done.stderr.strip()[:200]}")
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            raise OSError(f"tmp scratch {op} {path}: no answer") from None
        if not isinstance(answer, dict):
            raise OSError(f"tmp scratch {op} {path}: no answer")
        return answer

    def codex(self, under: Path, home: Path, config_text: str, auth_target: Path | None) -> None:
        """Codex's control files written inside the per-placement codex-home on the agents'
        side (scratchop.codex): config.toml and, when `auth_target` is given, the auth.json
        link. Every directory from `under` (the workspaces root) down to codex-home is opened
        without following a link, and codex-home itself is opened without following one, so a
        codex-home swapped for a link is refused rather than followed out of the scratch.
        scratchop.OnTheWay when it is a link; OSError when it fails otherwise."""
        target = str(auth_target) if auth_target is not None else None
        if self.direct:
            scratchop.codex(str(under), str(home), config_text, target)
            return
        argv = [*self.runner_module("scratchop"), "codex", "--under", str(under)]
        if target is not None:
            argv += ["--auth", target]
        done = self.run([*argv, str(home)], input=config_text)
        if done.returncode == scratchop.LINK:
            raise scratchop.OnTheWay(f"{home}: a link where codex-home must be; nothing written")
        if done.returncode == 2:
            # The op reaches an ssh host through its own `maity runner scratchop`. A host whose
            # `maity` has no `codex` op (older than this) rejects the subcommand as an argument
            # error (exit 2), distinct from LINK (4) and a genuine failure (1): refuse the
            # placement, do not crash-loop it. The runner always builds a well-formed argv.
            raise scratchop.Unsupported(
                f"host maity too old for codex placements: {done.stderr.strip()[:200]}"
            )
        if done.returncode != 0:
            raise OSError(f"codex home {home} failed: {done.stderr.strip()[:200]}")

    def skill_check(self, home: Path, key: str, source: str, commit: str) -> dict[str, Any]:
        """The delivered skill's copy `key` below the agents' `home` (skillop.check): `ok` with
        its manifest's SHA-256, `missing` or `mismatch`. skillop.OnTheWay when a directory
        below the home is a link; scratchop.Unsupported when an ssh host's `maity` has no skill
        ops; OSError otherwise."""
        if self.direct:
            return dict(skillop.check(str(home), key, source, commit))
        argv = [*self.runner_module("skillop"), "check", "--home", str(home), key, source, commit]
        return self._skill_answer(self.run(argv, env=self.module_env()), "check", key)

    def skill_put(self, home: Path, payload: str) -> dict[str, Any]:
        """The runner's checked copy (skillop.payload) put below the agents' `home`
        (skillop.put): `put` with its manifest's SHA-256. The document goes on stdin, at most
        the skill's own bound. Errors as for `skill_check`."""
        if self.direct:
            return dict(skillop.put(str(home), json.loads(payload)))
        argv = [*self.runner_module("skillop"), "put", "--home", str(home)]
        return self._skill_answer(self.run(argv, env=self.module_env(), input=payload), "put", "")

    def skill_codex(self, under: Path, home: Path, payload: str) -> dict[str, Any]:
        """The skill's own files from the runner's checked copy (skillop.payload) as
        `<home>/skills/keep-the-why/` of a Codex placement's CODEX_HOME in its scratch
        (skillop.codex_put), reached from the workspaces root `under`. Errors as for
        `skill_check`, scratchop.OnTheWay for a link on the way."""
        if self.direct:
            return dict(skillop.codex_put(str(under), str(home), json.loads(payload)))
        argv = [*self.runner_module("skillop"), "codex", "--under", str(under), str(home)]
        return self._skill_answer(self.run(argv, env=self.module_env(), input=payload), "codex", "")

    def skill_codex_clear(self, under: Path, home: Path) -> dict[str, Any]:
        """`<home>/skills/keep-the-why/` of a Codex placement's CODEX_HOME removed
        (skillop.codex_clear), for a launch that writes no skill there. Errors as for
        `skill_codex`."""
        if self.direct:
            return dict(skillop.codex_clear(str(under), str(home)))
        argv = [*self.runner_module("skillop"), "codexclear", "--under", str(under), str(home)]
        return self._skill_answer(self.run(argv, env=self.module_env()), "codexclear", "")

    def skill_remove(self, home: Path, keep: set[str]) -> list[str]:
        """The delivered copies below the agents' `home` that are not in `keep` removed
        (skillop.remove, `gc --skills`); their names. Errors as for `skill_check`."""
        if self.direct:
            answer = dict(skillop.remove(str(home), sorted(keep)))
        else:
            argv = [*self.runner_module("skillop"), "remove", "--home", str(home), *sorted(keep)]
            answer = self._skill_answer(self.run(argv, env=self.module_env()), "remove", "")
        names = answer.get("names")
        return [n for n in names if isinstance(n, str)] if isinstance(names, list) else []

    @staticmethod
    def _skill_answer(done: subprocess.CompletedProcess[str], op: str, key: str) -> dict[str, Any]:
        """A skill op's one JSON line (skillop.main): LINK (4) for a link below the home, 2 for
        a host `maity` without the ops (older than this one), as with scratchop's `codex`."""
        what = f"skill {op} {key}" if key else f"skill {op}"
        if done.returncode == skillop.LINK:
            raise skillop.OnTheWay(f"{what}: a link below the agents' home")
        if done.returncode == 2:
            raise scratchop.Unsupported(f"host maity has no skill ops: {done.stderr.strip()[:200]}")
        if done.returncode != 0:
            raise OSError(f"{what} failed: {done.stderr.strip()[:200]}")
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            raise OSError(f"{what}: no answer") from None
        if not isinstance(answer, dict):
            raise OSError(f"{what}: no answer")
        return answer

    def worktree_prune(self, repo: Path) -> dict[str, Any]:
        """Clear a Claude Code subagent's leftover worktree under the clone's `.claude/worktrees/`
        on placement start (worktree.prune_orphans), by file operations only, never git: the
        runner runs no git in an existing clone. For the runner's own user it runs in-process;
        through sudo or on an ssh host the op runs there (`maity runner worktree-prune --repo`)
        and prints one JSON line. OSError when it fails."""
        from . import worktree

        if self.direct:
            return worktree.prune_orphans(str(repo))
        argv = [*self.maity, "runner", "worktree-prune", "--repo", str(repo)]
        done = self.run(argv, env=self.module_env())
        if done.returncode != 0:
            raise OSError(f"worktree prune {repo} failed: {done.stderr.strip()[:200]}")
        try:
            answer = json.loads(done.stdout)
        except ValueError:
            raise OSError(f"worktree prune {repo}: no answer") from None
        if not isinstance(answer, dict):
            raise OSError(f"worktree prune {repo}: no answer")
        return answer

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
    agent_path: str = ""  # the host's PATH for its `maity` (targets.ssh_hosts)
    maity_path: str = "maity"  # the host's `maity`, absolute once connected (targets.pin_maity)

    @property
    def direct(self) -> bool:
        return False

    @property
    def here(self) -> bool:
        return False

    @property
    def maity(self) -> list[str]:
        return [self.maity_path]  # the host's own install

    def runner_module(self, name: str) -> list[str]:
        """The host's interpreter is not this one: its `maity`, through an internal
        subcommand (`maity runner loop`, `maity runner stub`)."""
        return [self.maity_path, "runner", name]

    def module_env(self) -> dict[str, str] | None:
        """The host's `maity` (`maity_path`) runs with the configured agents' PATH."""
        return {"PATH": self.agent_path} if self.agent_path else None

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
        return [*self.ssh(), "--", shell_join(words)]

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

    def uid(self) -> int:
        """An ssh host's agents run under a remote account whose uid the runner does not hold,
        so agy's `/tmp` scratch (keyed on that uid) is not made there."""
        raise OSError(f"{self.name}: a /tmp scratch is not made on an ssh host")

    def home(self) -> Path:
        done = self.run(["printenv", "HOME"])
        if done.returncode == SSH_UNREACHABLE:
            raise Unreachable(f"cannot reach {self.name}: {done.stderr.strip()[:200]}")
        home = done.stdout.strip()
        # The remote account is the agents': its shell start-up files can set HOME to
        # anything, and the runner builds paths and the attach hint from it.
        if done.returncode != 0 or not REMOTE_HOME.fullmatch(home) or ".." in home.split("/"):
            raise OSError(
                f"{self.name}: {self.login}'s home is not a plain absolute path "
                f"({home[:80]!r}); the runner refuses the host"
            )
        return Path(home)
