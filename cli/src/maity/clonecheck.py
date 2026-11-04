"""Whether git may run in a clone an agent wrote, and where maity's git runs under the runner.

git runs programs named in a repository's configuration (filter drivers, gpg.program,
fsmonitor, pagers, aliases) and reads `.git/info/attributes`, submodules' own configuration
and wherever `.git/commondir` points. `not_inspectable` reads a `.git` only when it is made of
a plain clone's entries, with a configuration made of a plain clone's keys. The runner's
`gc` asks it before reading an agent's clone; maity asks it before its own git in a session
the runner started (`MAITY_PLACEMENT`), where the clone is the one the runner made.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Protocol

from maity import onboarding
from maity.redact import without_userinfo

PLACEMENT_ENV = "MAITY_PLACEMENT"
GIT_SECTION = re.compile(r'^\[\s*([A-Za-z0-9.-]+)\s*(?:"([^"]*)")?\s*\]$')
GIT_ALLOWED = re.compile(
    r"^(core\.(repositoryformatversion|filemode|bare|logallrefupdates|ignorecase"
    r"|precomposeunicode)|remote\.[^.]+\.(url|fetch)|branch\.[^.]+\.(remote|merge)"
    r"|user\.(name|email))$"
)
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
CONFIG_MAX = 64 * 1024


class Files(Protocol):
    """How a clone's files are read: here as this user, or the runner's AsUser for another."""

    def exists(self, path: Path, kind: str = "-e") -> bool: ...

    def tree(self, path: Path) -> list[tuple[str, str, int]]: ...

    def read(self, path: Path, offset: int = 0) -> bytes: ...


class Local:
    """This process's own user, plain files."""

    def exists(self, path: Path, kind: str = "-e") -> bool:
        checks = {"-e": path.exists, "-f": path.is_file, "-d": path.is_dir,
                  "-L": path.is_symlink}  # fmt: skip
        return checks[kind]()

    def tree(self, path: Path) -> list[tuple[str, str, int]]:
        found: list[tuple[str, str, int]] = []
        for root, dirs, files in os.walk(path):  # does not descend into links
            for name in dirs + files:
                full = Path(root) / name
                mode = full.lstat()
                kind = ("l" if stat.S_ISLNK(mode.st_mode) else "d" if stat.S_ISDIR(mode.st_mode)
                        else "f" if stat.S_ISREG(mode.st_mode) else "?")  # fmt: skip
                found.append((Path(full.relative_to(path)).as_posix(), kind, mode.st_size))
        return found

    def read(self, path: Path, offset: int = 0) -> bytes:
        with path.open("rb") as fh:
            fh.seek(offset)
            return fh.read()


LOCAL = Local()


def not_inspectable(path: Path, files: Files = LOCAL) -> str | None:
    """Why git must not run in this clone, or None."""
    dot_git = path / ".git"
    if files.exists(dot_git, "-L") or not files.exists(dot_git, "-d"):
        return "its .git is not a plain directory"
    try:
        reason = _not_a_plain_git_dir(files.tree(dot_git))
        if reason is not None:
            return reason
        text = files.read(dot_git / "config").decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return "its .git/config cannot be read"
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        header = GIT_SECTION.match(line)
        if header:
            section = header.group(1).lower() + (f".{header.group(2)}" if header.group(2) else "")
            continue
        key = line.split("=", 1)[0].strip().lower()
        if not GIT_ALLOWED.match(f"{section}.{key}"):
            # A section may be named by a URL (`[url "https://tok@…"]`): shown without a token.
            shown = onboarding.inline(without_userinfo(section))
            return f"its .git/config sets {shown}.{onboarding.inline(key)}"
    return None


def _not_a_plain_git_dir(entries: list[tuple[str, str, int]]) -> str | None:
    """Why a `.git` with these entries (path inside it, type, size) is not laid out like a
    plain clone's, or None: an entry git does not create, an entry of the wrong type,
    another object store, a configuration over CONFIG_MAX, or a symlink anywhere (git
    follows them, so a link would put any file in the place of one that was checked)."""
    for where, kind, size in sorted(entries):
        top, _, rest = where.partition("/")
        if kind == "l":
            return f".git/{onboarding.inline(where)} is a symlink"
        if not rest and kind != ("f" if top in GIT_FILES else "d" if top in GIT_DIRS else "?"):
            return f".git/{onboarding.inline(where)} is not a plain clone's"
        if top == "info" and rest and ("/" in rest or rest not in INFO_FILES):
            return f".git/{onboarding.inline(where)} is not a plain clone's"
        if where in ALTERNATES:
            return f".git/{where} exists"
        if where == "config" and size > CONFIG_MAX:
            return f"its .git/config is larger than {CONFIG_MAX // 1024} KiB"
    return None


class Refused(Exception):
    """maity runs no git here; the message says why."""


def placement_root() -> Path | None:
    """In a session the runner started: the runner's clone, the parent of `GIT_COMMON_DIR`
    as the runner set it, resolved; None outside such a session. Never the current
    directory, which could be any repository the agent made."""
    if not os.environ.get(PLACEMENT_ENV):
        return None
    common = os.environ.get("GIT_COMMON_DIR")
    if not common:
        raise Refused(f"{PLACEMENT_ENV} is set without GIT_COMMON_DIR, so the clone is unknown")
    try:
        dot_git = Path(common).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Refused(f"the clone named by GIT_COMMON_DIR cannot be resolved ({exc})") from None
    if dot_git.name != ".git":
        raise Refused("GIT_COMMON_DIR is not a clone's .git")
    return dot_git.parent


def _within(path: Path, directory: Path) -> bool:
    return path == directory or directory in path.parents


def placement_git(cwd: Path) -> dict[str, str] | None:
    """In a session the runner started: the environment that pins git to the runner's clone,
    after checking that clone and that `cwd` lies in it. None outside such a session."""
    root = placement_root()
    if root is None:
        return None
    try:
        here = cwd.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise Refused(f"the working directory cannot be resolved ({exc})") from None
    if not _within(here, root):
        raise Refused(f"{onboarding.inline(str(here))} is outside the clone {root}")
    reason = not_inspectable(root)
    if reason is not None:
        raise Refused(f"the clone {root} is not a plain clone: {reason}")
    dot_git = str(root / ".git")
    return {
        "GIT_DIR": dot_git,
        "GIT_COMMON_DIR": dot_git,
        "GIT_WORK_TREE": str(root),
        "GIT_CEILING_DIRECTORIES": str(root.parent),
    }
