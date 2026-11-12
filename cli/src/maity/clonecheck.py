"""Whether git may run in a clone an agent wrote, and where maity's git runs under the runner.

git runs programs named in a repository's configuration (filter drivers, gpg.program,
fsmonitor, pagers, aliases) and reads `.git/info/attributes`, submodules' own configuration
and wherever `.git/commondir` points. `not_inspectable` reads a `.git` only when it is made of
a plain clone's entries, with a configuration made of a plain clone's keys. The runner's
`gc` asks it before reading an agent's clone; maity asks it before its own git in a session
the runner started (`MAITY_PLACEMENT`), where the clone is the one the runner made.
"""

from __future__ import annotations

import contextlib
import os
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import NamedTuple, Protocol

from maity import onboarding, proc
from maity.redact import without_userinfo

PLACEMENT_ENV = "MAITY_PLACEMENT"
# Written by the runner into every clone it starts an agent in (adapters.launch), in the
# directory Claude Code's sandbox keeps the agent from writing.
MARKER_PATH = Path(".git", "maity", "placement")
# Beside it, the git the runner found: the one maity starts under the runner, not one the
# PATH of maity's command line picks.
GIT_PATH = Path(".git", "maity", "git")
# The inode of the clone's `.git` when the runner started the session (adapters.launch).
# The sandbox keeps the agent out of `.git/maity`, not from renaming `.git` itself, so a
# directory of the session's own could take its name; maity takes `.git` only as the one
# with this inode, opened once (opened_git).
GIT_INODE_ENV = "MAITY_GIT_INODE"
# What git under the runner gets from maity's own environment. PATH is not among them: git
# gets one of its own (git_path_env), so no variable set for maity
# (`GIT_SSH_COMMAND=… maity report`, `PATH=…`) picks a program git starts; HOME reaches git
# without its configuration (`GIT_CONFIG_GLOBAL`).
ENV_KEPT = ("HOME", "LANG", "TMPDIR")
ENV_KEPT_WINDOWS = (
    "SYSTEMROOT", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "TEMP",
    "TMP", "PATHEXT", "COMSPEC",
)  # fmt: skip
# The keys a plain clone's configuration holds: (section, key) without a subsection, or with
# one for `remote` and `branch`, whose subsection is any remote or branch name (`v1.0` too).
GIT_ALLOWED = {
    (None, "core"): frozenset({
        "repositoryformatversion", "filemode", "bare", "logallrefupdates", "ignorecase",
        "precomposeunicode", "symlinks",  # git for Windows writes `symlinks` on every clone
    }),
    (None, "user"): frozenset({"name", "email"}),
    ("named", "remote"): frozenset({"url", "fetch"}),
    ("named", "branch"): frozenset({"remote", "merge"}),
}  # fmt: skip
# What a clone's `.git` holds at its top level, and of which type (a file, or a directory).
# Anything else may change where git reads its configuration from (`commondir`,
# `config.worktree`) and is refused rather than understood.
GIT_FILES = frozenset({
    "AUTO_MERGE", "BISECT_LOG", "CHERRY_PICK_HEAD", "COMMIT_EDITMSG", "FETCH_HEAD", "HEAD",
    "MERGE_HEAD", "MERGE_MODE", "MERGE_MSG", "ORIG_HEAD", "REVERT_HEAD", "config",
    "description", "gc.log", "index", "index.lock", "packed-refs", "shallow",
})  # fmt: skip
GIT_DIRS = frozenset({
    "branches", "hooks", "info", "logs", "maity", "objects", "rebase-apply", "rebase-merge",
    "refs", "sequencer",
})  # fmt: skip
INFO_FILES = frozenset({"exclude", "refs"})
# Other object stores git would read from (and, over http, fetch from).
ALTERNATES = ("objects/info/alternates", "objects/info/http-alternates")
# Claude Code's sandbox leaves these in a clone it ran in, to guard the paths it protects:
# empty, they change nothing git does. Anything in them is refused as before.
SANDBOX_DIR = ".claude-sandbox-noreplace"  # an empty directory, wherever it appears
SANDBOX_EMPTY_FILES = frozenset({"config.worktree", *ALTERNATES})
SANDBOX_EMPTY_DIRS = frozenset({"remotes"})
CONFIG_MAX = 64 * 1024
# More entries than this in `.git` are refused rather than listed on every git run.
TREE_MAX = 20_000
# What the runner leaves a plain clone without, and maity under the runner does not support
# yet: (an entry in `.git`, or a configuration section or key prefix) -> what it is.
UNSUPPORTED = {
    "modules": "Submodules are", "submodule.": "Submodules are",
    "lfs": "Git LFS is", "lfs.": "Git LFS is", "filter.lfs.": "Git LFS is",
    "worktrees": "Worktrees are", "config.worktree": "Worktrees are",
    "info/sparse-checkout": "Sparse checkout is", "core.sparsecheckout": "Sparse checkout is",
    "core.sparsecheckoutcone": "Sparse checkout is", "index.sparse": "Sparse checkout is",
    "extensions.worktreeconfig": "Worktrees are", "extensions.partialclone": "Partial clones are",
    "extensions.": "Repository format extensions are",
}  # fmt: skip


# Keys of a named section (`remote.<name>.<key>`) that stand for such a feature: what
# `git clone --filter` writes, with no `extensions.` line.
UNSUPPORTED_KEYS = {
    ("remote", "promisor"): "Partial clones are",
    ("remote", "partialclonefilter"): "Partial clones are",
}  # fmt: skip


class Files(Protocol):
    """How a clone's files are read: here as this user, or the runner's AsUser for another."""

    def exists(self, path: Path, kind: str = "-e") -> bool: ...

    def tree(self, path: Path) -> list[tuple[str, str, int]]: ...

    def read(self, path: Path, offset: int = 0) -> bytes: ...


def bounded_tree(path: Path, limit: int) -> list[tuple[str, str, int]]:
    """Everything under a directory: (path inside it, `f`/`d`/`l`/`?`, size). Links are
    listed, never followed. A directory that cannot be read raises OSError: unlisted, it
    would look empty, and an empty directory is taken as a placeholder.
    Stops after `limit` + 1 entries, inside a directory too: one entry more is enough to
    refuse, and the rest is never listed or looked at."""
    found: list[tuple[str, str, int]] = []
    pending = [path]
    while pending:
        here = pending.pop()
        listing = os.scandir(here)
        with listing:
            for entry in listing:
                mode = entry.stat(follow_symlinks=False)
                kind = ("l" if stat.S_ISLNK(mode.st_mode) else "d" if stat.S_ISDIR(mode.st_mode)
                        else "f" if stat.S_ISREG(mode.st_mode) else "?")  # fmt: skip
                found.append((Path(entry.path).relative_to(path).as_posix(), kind, mode.st_size))
                if len(found) > limit:
                    return found
                if kind == "d":
                    pending.append(Path(entry.path))
    return found


class Local:
    """This process's own user, plain files."""

    def exists(self, path: Path, kind: str = "-e") -> bool:
        checks = {"-e": path.exists, "-f": path.is_file, "-d": path.is_dir,
                  "-L": path.is_symlink}  # fmt: skip
        return checks[kind]()

    def tree(self, path: Path) -> list[tuple[str, str, int]]:
        return bounded_tree(path, TREE_MAX)

    def read(self, path: Path, offset: int = 0) -> bytes:
        with path.open("rb") as fh:
            fh.seek(offset)
            return fh.read()


LOCAL = Local()


def not_inspectable(path: Path, files: Files = LOCAL) -> str | None:
    """Why git must not run in this clone, or None."""
    finding = _inspect(path, files)[0]
    return None if finding is None else finding.reason


class Finding(NamedTuple):
    """Why git must not run in a clone: the reason, and what it names (an entry in `.git`,
    a configuration key) when it names one."""

    reason: str
    item: str = ""
    setting: bool = False  # a configuration key, which `git config --unset` takes back


def _inspect(
    path: Path, files: Files, git: str | None = None
) -> tuple[Finding | None, list[tuple[str, str | None]]]:
    """Why git must not run in this clone (or None), and the configuration's entries as git
    reads them: the ones that finding was decided on, read once."""
    dot_git = path / ".git"
    if files.exists(dot_git, "-L") or not files.exists(dot_git, "-d"):
        return Finding("its .git is not a plain directory"), []
    try:
        tree = files.tree(dot_git)
    except OSError:
        return Finding("its .git cannot be listed in full"), []
    try:
        finding = _not_a_plain_git_dir(tree)
        if finding is not None:
            return finding, []
        data = files.read(dot_git / "config")
    except OSError:
        return Finding("its .git/config cannot be read"), []
    entries = config_entries(data, git)
    if entries is None:
        return Finding("its .git/config cannot be parsed"), []
    for name, _ in entries:
        section, _, rest = name.partition(".")
        subsection, _, key = rest.rpartition(".")
        if key not in GIT_ALLOWED.get(("named" if subsection else None, section), ()):
            # A section may be named by a URL (`[url "https://tok@…"]`): shown without a token.
            shown = onboarding.inline(without_userinfo(name))
            return Finding(f"its .git/config sets {shown}", name, setting=True), []
    return None, entries


def unsupported(finding: Finding) -> str | None:
    """The feature a finding stands for that the runner does not support yet ("Git LFS is"),
    or None."""
    if finding.setting:
        section, _, rest = finding.item.partition(".")
        feature = UNSUPPORTED_KEYS.get((section, rest.rpartition(".")[2]))
        if feature is not None:
            return feature
    for prefix, feature in UNSUPPORTED.items():
        if finding.item == prefix or finding.item.startswith(
            prefix if prefix.endswith(".") else prefix + "/"
        ):
            return feature
    return None


def config_names(data: bytes) -> list[str] | None:
    """The names of the entries in `data`, a git configuration, as git reads them, or None."""
    entries = config_entries(data)
    return None if entries is None else [name for name, _ in entries]


def config_entries(data: bytes, git: str | None = None) -> list[tuple[str, str | None]] | None:
    """The entries in `data`, a git configuration, as git itself reads them: (name, value),
    the value None for a key without one; None when git cannot read it. Parsed by git, not
    by maity: git's own reading is the one that counts (a header and a key can share a
    line). Read from stdin with includes off, outside any repository, with no system or
    global configuration, so nothing but `data` is read. `git`: the git to ask, with a PATH
    of its own (under the runner); else the one on PATH."""
    with tempfile.TemporaryDirectory() as empty:
        env = {
            "PATH": git_path_env(git)["PATH"] if git else os.environ.get("PATH", ""),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.path.join(empty, "none"),  # missing: no entries
            "GIT_CEILING_DIRECTORIES": str(Path(empty).parent),
            "HOME": empty,
        }
        if _windows():
            env["SYSTEMROOT"] = _windows_directory()  # the system's, not maity's environment's
            env["NoDefaultCurrentDirectoryInExePath"] = "1"
        git = git or proc.program(proc.GIT[0])
        if git is None:
            return None
        cmd = [*proc.GIT, "config", "--no-includes", "--file", "-", "--list", "-z"]
        try:
            done = subprocess.run(
                [git, *cmd[1:]],
                cwd=empty,
                env=env,
                input=data,
                capture_output=True,
                timeout=proc.TIMEOUT,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
    if done.returncode != 0:
        return None
    # Each entry: the name, then a newline and the value unless it has none, then NUL.
    found: list[tuple[str, str | None]] = []
    for entry in done.stdout.decode("utf-8", "replace").split("\0")[:-1]:
        name, newline, value = entry.partition("\n")
        found.append((name, value if newline else None))
    return found


def _not_a_plain_git_dir(entries: list[tuple[str, str, int]]) -> Finding | None:
    """Why a `.git` with these entries (path inside it, type, size) is not laid out like a
    plain clone's, or None: an entry git does not create, an entry of the wrong type,
    another object store, a configuration over CONFIG_MAX, or a symlink anywhere (git
    follows them, so a link would put any file in the place of one that was checked)."""
    if len(entries) > TREE_MAX:
        return Finding(f"its .git holds more than {TREE_MAX} entries (`git gc` packs them)")
    parents = {where.rpartition("/")[0] for where, _, _ in entries}
    # `git sparse-checkout` writes `config.worktree` too, which sorts first: named for what
    # the clone is set up for.
    for where, kind, size in sorted(entries, key=lambda e: (e[0] != "info/sparse-checkout", e)):
        top, _, rest = where.partition("/")
        shown = onboarding.inline(where)
        if kind == "l":
            return Finding(f".git/{shown} is a symlink", where)
        if kind not in ("f", "d"):  # a FIFO, a socket or a device: never in a plain clone
            return Finding(f".git/{shown} is not a regular file or directory", where)
        if SANDBOX_DIR in where.split("/")[:-1]:
            return Finding(f".git/{shown} is not a plain clone's", where)
        if _sandbox_placeholder(where, kind, size, parents):
            continue
        if not rest and kind != ("f" if top in GIT_FILES else "d" if top in GIT_DIRS else "?"):
            return Finding(f".git/{shown} is not a plain clone's", where)
        if top == "info" and rest and ("/" in rest or rest not in INFO_FILES):
            return Finding(f".git/{shown} is not a plain clone's", where)
        if where in ALTERNATES:
            return Finding(f".git/{where} exists", where)
        if where == "config" and size > CONFIG_MAX:
            return Finding(f"its .git/config is larger than {CONFIG_MAX // 1024} KiB")
    return None


def _sandbox_placeholder(where: str, kind: str, size: int, parents: set[str]) -> bool:
    """Whether an entry is one Claude Code's sandbox leaves, still empty."""
    if kind == "d" and where not in parents:
        return where.rpartition("/")[2] == SANDBOX_DIR or where in SANDBOX_EMPTY_DIRS
    return kind == "f" and size == 0 and where in SANDBOX_EMPTY_FILES


class Refused(Exception):
    """maity runs no git here; the message says why."""


def placement_root(cwd: Path | None = None) -> Path | None:
    """In a session the runner started: the runner's clone, the parent of `GIT_COMMON_DIR`
    as the runner set it, resolved; None outside such a session. Never the current
    directory, which could be any repository the agent made. Without `MAITY_PLACEMENT`,
    a clone above `cwd` that holds the runner's marker is refused: the variables were
    removed from the environment, not never set."""
    if not os.environ.get(PLACEMENT_ENV):
        marked = _runner_marked(cwd or Path.cwd())
        if marked is not None:
            raise Refused(
                f"{marked} is a clone the runner set up ({MARKER_PATH} is there), but"
                f" {PLACEMENT_ENV} is not set; maity's git runs there only in the session the"
                " runner started"
            )
        return None
    common = os.environ.get("GIT_COMMON_DIR")
    if not common:
        raise Refused(f"{PLACEMENT_ENV} is set without GIT_COMMON_DIR, so the clone is unknown")
    named = Path(common)
    if named.name != ".git":
        raise Refused("GIT_COMMON_DIR is not a clone's .git")
    if named.is_symlink():  # what it points to is not the runner's clone; checked as named
        raise Refused("the clone's .git is not a plain directory")
    try:
        return named.parent.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Refused(f"the clone named by GIT_COMMON_DIR cannot be resolved ({exc})") from None


def _runner_marked(cwd: Path) -> Path | None:
    """A clone holding the runner's marker that git would open from `cwd`, or None: the
    nearest at or above `cwd`, one a `.git` file there points into, and one `GIT_DIR` or
    `GIT_COMMON_DIR` names (each followed through a `commondir`). Plain file checks, no git:
    git is what is not yet trusted here."""
    try:
        here = cwd.resolve()
    except (OSError, RuntimeError):
        return None
    named = [here / value for key in ("GIT_DIR", "GIT_COMMON_DIR")
             if (value := os.environ.get(key))]  # fmt: skip
    # git follows a `.git` file that GIT_DIR names, as one it finds in a directory.
    named += [t for t in map(_gitfile_target, list(named)) if t is not None]
    for directory in (here, *here.parents):
        dot_git = directory / ".git"
        named.append(dot_git)
        target = _gitfile_target(dot_git)
        if target is not None:
            named.append(target)
    for git_dir in named:
        for candidate in (git_dir, _commondir(git_dir)):
            if candidate is None:
                continue
            try:
                candidate = candidate.resolve()
            except (OSError, RuntimeError):
                continue
            if _holds_marker(candidate):
                return candidate.parent if candidate.name == ".git" else candidate
    return None


def _holds_marker(git_dir: Path) -> bool:
    try:
        return (git_dir / MARKER_PATH.relative_to(".git")).is_file()
    except (OSError, ValueError):
        return False


def _gitfile_target(dot_git: Path) -> Path | None:
    """Where a `.git` file (`gitdir: …`) points, or None when `dot_git` is none."""
    try:
        if not dot_git.is_file():
            return None
        line = dot_git.read_bytes()[:4096].decode("utf-8", "replace").strip()
    except OSError:
        return None
    if not line.startswith("gitdir:"):
        return None
    return dot_git.parent / line.removeprefix("gitdir:").strip()


def _commondir(git_dir: Path) -> Path | None:
    """The common directory a git directory's `commondir` file names, or None."""
    try:
        value = (git_dir / "commondir").read_bytes()[:4096].decode("utf-8", "replace").strip()
    except OSError:
        return None
    return git_dir / value if value else None


def _within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


# The configuration keys maity passes on to git from the clone's own, under the runner: what
# report and the checks read (remotes, upstreams, who commits) and how the work tree is read.
# The repository's layout (`core.bare`, the format) is maity's, never the clone's.
PASSED_ON = frozenset({
    "filemode", "ignorecase", "precomposeunicode", "logallrefupdates", "symlinks",
})  # fmt: skip
# A loose ref or HEAD is one line; more than this many refs is not a clone maity copies.
REF_MAX = 4096
REFS_MAX = 20_000
PACKED_REFS_MAX = 32 * 1024 * 1024
NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)  # POSIX; placements are POSIX only


class Pinned(NamedTuple):
    """How maity starts one git run under the runner: which git, with what environment."""

    git: str
    env: dict[str, str]


@contextlib.contextmanager
def placement_git(cwd: Path) -> Iterator[Pinned | None]:
    """In a session the runner started: the environment for one git run on the runner's
    clone, after checking that clone and that `cwd` lies in it; None outside such a session.

    git does not read the clone's `.git` for its configuration, HEAD or refs: it reads a
    repository maity writes for this run under `.git/maity`: for Claude Code a directory
    its sandbox keeps the agent from writing; Codex runs maity inside its sandbox, with the
    agent's own rights. Its configuration is maity's own, with no system or global one and
    the clone's entries maity checked passed on through the environment, so a configuration
    changed after the check is never read. Objects, the index and the work tree are the
    clone's: data git reads, nothing it runs. The directory is removed after the run. git is
    the one the runner found (GIT_PATH), with a PATH of its own."""
    root = placement_root(cwd)
    if root is None:
        yield None
        return
    try:
        here = cwd.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Refused(f"the working directory cannot be resolved ({exc})") from None
    if not _within(here, root):
        raise Refused(f"{onboarding.inline(str(here))} is outside the clone {root}")
    dot_git = root / ".git"
    with opened_git(root) as top:
        program = _recorded_git(root, top)  # the config is read by the same git, not PATH's
        finding, entries = _inspect(root, LOCAL, program)
        if finding is not None:
            raise Refused(_refusal(root, finding))
        private = _private_dir(root, top)
        try:
            _copy_refs(dot_git, private, top)
            (private / "config").write_text(
                "[core]\n\trepositoryformatversion = 0\n\tbare = false\n"
            )
            yield Pinned(
                program,
                {
                    **git_path_env(program),
                    "GIT_DIR": str(private),
                    "GIT_COMMON_DIR": str(private),
                    "GIT_OBJECT_DIRECTORY": str(dot_git / "objects"),
                    "GIT_INDEX_FILE": str(dot_git / "index"),
                    "GIT_WORK_TREE": str(root),
                    "GIT_CEILING_DIRECTORIES": str(root.parent),
                    "GIT_OPTIONAL_LOCKS": "0",  # `status` writes no refreshed index
                    # No configuration but maity's own and the checked entries: not the
                    # system's, not HOME's (a missing file reads as empty).
                    "GIT_CONFIG_NOSYSTEM": "1",
                    "GIT_CONFIG_GLOBAL": str(private / "global"),
                    **_passed_on(entries, private / "none"),
                },
            )
        finally:
            shutil.rmtree(private, ignore_errors=True)


def _refusal(root: Path, finding: Finding) -> str:
    """Why maity runs no git in the runner's clone, and how to go on, where there is a way."""
    said = f"the clone {root} is not a plain clone: {finding.reason}."
    feature = unsupported(finding)
    if feature is not None:
        return (f"{said} {feature} not supported under the runner yet, so maity runs no git"
                " in this clone while that is set up")  # fmt: skip
    if finding.setting:
        key = onboarding.inline(without_userinfo(finding.item))
        return (f"{said} Under the runner maity's git runs only in a clone configured as"
                f" `git clone` leaves it: `git config --unset-all {key}`, then run the command"
                " again")  # fmt: skip
    return (f"{said} Under the runner maity's git runs only in a clone laid out as `git clone`"
            " leaves it; undo that change and run the command again")  # fmt: skip


def _passed_on(entries: list[tuple[str, str | None]], missing: Path) -> dict[str, str]:
    """The checked entries git should see, as `GIT_CONFIG_*`. The environment's own are not
    kept (`kept_env`); the pins the runner sets there are on maity's command line too. The
    ignore and attributes files git would read under HOME (`~/.config/git/`) are pointed at
    `missing`, a file that does not exist."""
    kept = [
        (name, "true" if value is None else value)
        for name, value in entries
        if not name.startswith("core.") or name.removeprefix("core.") in PASSED_ON
    ]
    kept += [("core.excludesfile", str(missing)), ("core.attributesfile", str(missing))]
    env = {"GIT_CONFIG_COUNT": str(len(kept))}
    for i, (name, value) in enumerate(kept):
        env[f"GIT_CONFIG_KEY_{i}"] = name
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return env


def _read_regular(name: str, dir_fd: int, limit: int) -> bytes:
    """A regular file in the directory `dir_fd`, never a link, at most `limit` bytes."""
    fd = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=dir_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise Refused(f".git/{onboarding.inline(name)} is not a regular file")
        data = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise Refused(f".git/{onboarding.inline(name)} is larger than maity copies")
    return data


def _copy_refs(dot_git: Path, private: Path, top: int | None) -> None:
    """HEAD, `packed-refs`, `shallow` and `refs/` of the clone into `private`, as regular
    files only: a link, or anything else, is refused rather than followed. Read through
    `top`, the descriptor of the `.git` the runner recorded (opened_git), so a `.git`
    replaced meanwhile is not read."""
    if top is None:
        _copy_refs_by_path(dot_git, private)
        return
    try:
        (private / "HEAD").write_bytes(_read_regular("HEAD", top, REF_MAX))
        for name in ("packed-refs", "shallow"):
            if name in os.listdir(top):
                (private / name).write_bytes(_read_regular(name, top, PACKED_REFS_MAX))
        if not stat.S_ISDIR(os.stat("refs", dir_fd=top, follow_symlinks=False).st_mode):
            raise Refused("the clone's .git/refs is not a directory")
        count = 0
        for here, _, files, fd in os.fwalk("refs", dir_fd=top, follow_symlinks=False):
            where = private / here
            where.mkdir(exist_ok=True)
            for name in files:  # a link, to a directory too, is listed here and refused
                count += 1
                if count > REFS_MAX:
                    raise Refused(f"the clone has more than {REFS_MAX} loose refs")
                (where / name).write_bytes(_read_regular(name, fd, REF_MAX))
    except OSError as exc:
        raise Refused(f"the clone's refs cannot be copied ({exc})") from None


def _plain_file(path: Path, limit: int) -> bytes:
    """A regular file that is no link or other reparse point, at most `limit` bytes."""
    mode = path.lstat()
    reparse = getattr(mode, "st_file_attributes", 0) & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
    if not stat.S_ISREG(mode.st_mode) or reparse or mode.st_size > limit:
        raise Refused(f"{onboarding.inline(path.name)} in the clone's .git is not a plain ref")
    with path.open("rb") as fh:
        return fh.read(limit + 1)[:limit]


def _copy_refs_by_path(dot_git: Path, private: Path) -> None:
    """`_copy_refs` where directories cannot be opened (Windows, local mode): each entry is
    checked with `lstat` before it is read. A file replaced between the two is read as it
    then is; local mode's sandbox is not verified there (runner.md, local mode)."""
    try:
        (private / "HEAD").write_bytes(_plain_file(dot_git / "HEAD", REF_MAX))
        for name in ("packed-refs", "shallow"):
            if (dot_git / name).exists():
                (private / name).write_bytes(_plain_file(dot_git / name, PACKED_REFS_MAX))
        refs = (dot_git / "refs").lstat()
        if not stat.S_ISDIR(refs.st_mode) or getattr(refs, "st_file_attributes", 0) & 0x400:
            raise Refused("the clone's .git/refs is not a directory")
        count = 0
        for here, dirs, files in os.walk(dot_git / "refs"):  # does not descend into links
            where = private / Path(here).relative_to(dot_git)
            where.mkdir(exist_ok=True)
            for name in dirs:
                mode = (Path(here) / name).lstat()
                if stat.S_ISLNK(mode.st_mode) or getattr(mode, "st_file_attributes", 0) & 0x400:
                    raise Refused(f".git/refs holds a link, {onboarding.inline(name)}")
            for name in files:
                count += 1
                if count > REFS_MAX:
                    raise Refused(f"the clone has more than {REFS_MAX} loose refs")
                (where / name).write_bytes(_plain_file(Path(here) / name, REF_MAX))
    except OSError as exc:
        raise Refused(f"the clone's refs cannot be copied ({exc})") from None


@contextlib.contextmanager
def opened_git(root: Path) -> Iterator[int | None]:
    """The clone's `.git` as the runner left it: opened once from the clone's root without
    following a link, and refused unless it is the directory whose inode the runner set in
    GIT_INODE_ENV at the session's start. Yields its descriptor, so what maity reads from it
    afterwards is not looked up through the name `.git` again; sandboxed code can rename
    `.git` and put a directory of its own there. Where directories cannot be opened (Windows,
    local mode) the inode is checked by name and None is yielded."""
    value = os.environ.get(GIT_INODE_ENV, "")
    if not value.isdigit():
        raise Refused(
            f"{GIT_INODE_ENV} is not set, so the clone's .git is unknown; the runner sets it"
            " when it starts a session: restart the placement"
        )
    replaced = Refused(
        "the clone's .git is not the directory it was when the session started (it was"
        " renamed or replaced); maity runs no git there"
    )
    if not _walks():
        try:
            here = os.lstat(root / ".git")
        except OSError:
            raise replaced from None
        if not stat.S_ISDIR(here.st_mode) or here.st_ino != int(value):
            raise replaced
        yield None
        return
    top = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fd = os.open(".git", os.O_RDONLY | NOFOLLOW | os.O_DIRECTORY, dir_fd=top)
    except OSError:
        raise replaced from None
    finally:
        os.close(top)
    try:
        if os.fstat(fd).st_ino != int(value):
            raise replaced
        yield fd
    finally:
        os.close(fd)


def _walks() -> bool:
    """Whether a name can be opened in a directory's descriptor without following a link."""
    return not _windows() and os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")


def _private_dir(root: Path, top: int | None) -> Path:
    """A new directory in the clone's `.git/maity`, for one git run's own repository: made
    through `.git`'s descriptor, with a name sandboxed code cannot read (`.git/maity` is
    hidden from it), so a `.git` replaced afterwards has no directory of that name."""
    own = root / ".git" / "maity"
    if top is None:
        if own.is_symlink() or not own.is_dir():
            raise Refused(f"the clone {root} has no .git/maity directory of maity's own")
        return Path(tempfile.mkdtemp(prefix="git-", dir=own))
    try:
        fd = os.open("maity", os.O_RDONLY | NOFOLLOW | os.O_DIRECTORY, dir_fd=top)
    except OSError:
        raise Refused(f"the clone {root} has no .git/maity directory of maity's own") from None
    try:
        name = f"git-{secrets.token_hex(8)}"
        os.mkdir(name, 0o700, dir_fd=fd)
    finally:
        os.close(fd)
    return own / name


def _recorded_git(root: Path, top: int | None) -> str:
    """The git the runner recorded for this clone (GIT_PATH): an absolute path to a program,
    read through `.git`'s descriptor `top` (by name where None)."""
    missing = Refused(f"the clone {root} has no git the runner recorded ({GIT_PATH})")
    try:
        if top is None:
            where = root / GIT_PATH
            mode = where.lstat()
            if not stat.S_ISREG(mode.st_mode) or mode.st_size > REF_MAX:
                raise OSError("not a plain file")
            data = where.read_bytes()
        else:
            fd = os.open("maity", os.O_RDONLY | NOFOLLOW | os.O_DIRECTORY, dir_fd=top)
            try:
                data = _read_regular("git", fd, REF_MAX)
            finally:
                os.close(fd)
        program = data.decode("utf-8").strip()
    except (OSError, UnicodeDecodeError, Refused):
        raise missing from None
    if not (os.path.isabs(program) and os.path.isfile(program) and os.access(program, os.X_OK)):
        raise Refused(f"the git the runner recorded for {root} is not a program here")
    return program


def git_path_env(program: str) -> dict[str, str]:
    """PATH for git under the runner: git's own directory and the system's, never the PATH
    of maity's command line, so a program git starts by name is not one placed there."""
    parts = [os.path.dirname(program)]
    if _windows():
        system = _windows_directory()
        parts += [os.path.join(system, "System32"), system]
        path = os.pathsep.join(dict.fromkeys(p for p in parts if p))
        return {"PATH": path, "SYSTEMROOT": system}  # not maity's SYSTEMROOT either
    parts += os.defpath.split(os.pathsep)
    return {"PATH": os.pathsep.join(dict.fromkeys(p for p in parts if p))}


def _windows() -> bool:
    return os.name == "nt"


def _windows_directory() -> str:
    """The Windows directory as the system reports it, not as `SYSTEMROOT` in maity's
    environment says."""
    if sys.platform == "win32":
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetWindowsDirectoryW(buffer, len(buffer)):
            return buffer.value
    return r"C:\Windows"


def kept_env(environ: Mapping[str, str]) -> dict[str, str]:
    """What git under the runner gets from `environ`: ENV_KEPT, and on Windows what a
    program needs to start there."""
    names = ENV_KEPT + (ENV_KEPT_WINDOWS if _windows() else ())
    return {name: environ[name] for name in names if name in environ}
