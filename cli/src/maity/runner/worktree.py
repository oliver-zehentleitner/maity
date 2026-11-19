"""Clearing a Claude Code subagent's leftover worktree from a placement's clone (§15.5).

Claude Code's worktree-isolation feature leaves a git worktree at `.claude/worktrees/agent-<id>`
inside the placement's clone. git registers its admin data under `.git/worktrees/<name>/`, so
`.git/worktrees` is no longer empty and the clone check reads the clone as unsupported
("Worktrees are"): `maity report` and the next placement start refuse before running git. Inside
the sandbox the agent cannot remove either the worktree or `.claude/worktrees/*` (protected
paths), so without help a session is stuck until a human cleans the host.

`prune_orphans` is the hygiene step the supervisor runs on every placement (re)start, before the
clone check would refuse a leftover — the one path that clears such a worktree. It runs no git —
the runner never runs git in an existing clone, which would run the agent's code as the runner —
so it removes by file operations only, and touches nothing outside this clone's own
`.claude/worktrees/`:

- The scope `.claude/worktrees` is opened from the clone root, each level without following a
  link. A link or non-directory on the way (a planted `.claude`) blocks the prune: nothing is
  removed and the clone stays unsupported until a person looks at it.
- A `.git/worktrees/<name>` admin entry is cleared only when its registered working tree reads,
  from a plain, bounded, single-line `gitdir` file (no link, no FIFO), as this clone's own
  `.claude/worktrees/<id>` with no `.`/`..` segment, and that `<id>` is a real directory opened
  as a direct child of the scope (or the scope is gone, leaving the admin entry dangling). The
  admin entry is removed through `.git`'s own descriptors, every component without following a
  link, and is reported removed only when it actually was.
- Every directory directly under `.claude/worktrees/` that is a real directory (opened without
  following a link) is removed, deepest first, following no link on the way down; a link there is
  left as the link, its target never entered or removed.

A registered worktree pointing out of the clone is left, so a planted redirect still refuses the
start. There is no in-session remover: a leftover is cleared when the placement next starts, which
discards any uncommitted work in it.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from .. import clonecheck

_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_OPEN_DIR = os.O_RDONLY | _DIRECTORY | _CLOEXEC
_OPEN_DIR_NOFOLLOW = _OPEN_DIR | _NOFOLLOW


def supported() -> bool:
    """Whether this system opens a directory from another without following a link (not
    Windows); the runner is POSIX-only, but the op fails closed where it is not."""
    return hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd


# --- the supervisor's hygiene step (no git) --------------------------------------------------


def prune_orphans(repo: str) -> dict[str, object]:
    """Remove the clone's leftover worktrees under `.claude/worktrees/` by file operations only,
    no git (see the module docstring for the scope): each `.git/worktrees/<name>` whose registered
    working tree is this clone's own `.claude/worktrees/<id>`, and every directory directly under
    `.claude/worktrees/`. A link or non-directory on the way to `.claude/worktrees` blocks the
    prune. Returns what was removed and what was left, both for the runner's log."""
    root = Path(repo)
    removed: list[str] = []
    left: list[str] = []
    if not supported():
        return {"result": "unsupported", "removed": removed, "left": left}
    state, scope = _worktrees_scope(root)
    try:
        admin_root = root / ".git" / "worktrees"
        for name in _names(admin_root):
            working = clonecheck._gitdir_working_tree(admin_root / name)
            # Remove the admin entry when the working tree is this clone's own, and either the
            # scope is gone (a dangling registration) or that `<id>` is a real directory opened
            # as a direct child of the scope (not a link).
            removable = (
                working is not None
                and clonecheck._under_claude_worktrees(root, working)
                and (
                    state == "absent"
                    or (state == "open" and scope is not None
                        and _is_real_dir(scope, working.name))  # fmt: skip
                )
            )
            if removable and _remove_admin(root, name):
                removed.append(f".git/worktrees/{name}")
            else:  # elsewhere, unreadable, planted, or already gone: left for a person
                left.append(f".git/worktrees/{name}")
        if scope is not None:  # the scope is a real directory (state == "open")
            for name in sorted(os.listdir(scope)):
                if _is_real_dir(scope, name) and _remove_tree(scope, name):
                    removed.append(f".claude/worktrees/{name}")
                else:  # a link, a file, a device, or a race: never followed, left for a person
                    left.append(f".claude/worktrees/{name}")
    finally:
        if scope is not None:
            os.close(scope)
    return {"result": "pruned", "removed": removed, "left": left}


def _names(directory: Path) -> list[str]:
    try:
        return sorted(os.listdir(directory))
    except OSError:
        return []


def _remove_admin(root: Path, name: str) -> bool:
    """Remove `.git/worktrees/<name>`, every component (`.git`, `worktrees`, `<name>`) reached
    from the clone without following a link. True only when the entry was actually removed, so a
    link or a vanished entry is not reported as cleared."""
    parent = _descend(root, (".git", "worktrees"))
    if parent is None:
        return False
    try:
        return _remove_tree(parent, name)
    finally:
        os.close(parent)


# --- descriptor-relative paths, no link followed ---------------------------------------------


def _worktrees_scope(root: Path) -> tuple[str, int | None]:
    """`.claude/worktrees` opened from the clone root, each level without following a link:
    `("open", fd)` when it is a real directory (the caller closes `fd`); `("absent", None)` when a
    level is missing (the worktree is gone, so a dangling admin entry may be cleared);
    `("blocked", None)` when a level is a link or not a directory — then nothing is pruned."""
    try:
        fd = os.open(root, _OPEN_DIR)
    except OSError:
        return ("blocked", None)
    for name in clonecheck.CLAUDE_WORKTREES:
        try:
            nxt = os.open(name, _OPEN_DIR_NOFOLLOW, dir_fd=fd)
        except FileNotFoundError:
            os.close(fd)
            return ("absent", None)
        except OSError:  # a link (ELOOP) or a non-directory (ENOTDIR)
            os.close(fd)
            return ("blocked", None)
        os.close(fd)
        fd = nxt
    return ("open", fd)


def _descend(root: Path, parts: tuple[str, ...]) -> int | None:
    try:
        fd = os.open(root, _OPEN_DIR)
    except OSError:
        return None
    for name in parts:
        try:
            nxt = os.open(name, _OPEN_DIR_NOFOLLOW, dir_fd=fd)
        except OSError:
            os.close(fd)
            return None
        os.close(fd)
        fd = nxt
    return fd


def _is_real_dir(parent_fd: int, name: str) -> bool:
    """Whether `name` in `parent_fd` is a directory, opened without following a link."""
    try:
        fd = os.open(name, _OPEN_DIR_NOFOLLOW, dir_fd=parent_fd)
    except OSError:
        return False
    os.close(fd)
    return True


def _remove_tree(parent_fd: int, name: str) -> bool:
    """Remove the directory `name` in `parent_fd` and everything under it, deepest first, each
    level reached from the one above without following a link (a link is removed, never
    entered). True only when `name` was a real directory and was removed."""
    try:
        fd = os.open(name, _OPEN_DIR_NOFOLLOW, dir_fd=parent_fd)
    except OSError:  # a link, a non-directory, or already gone: not removed
        return False
    try:
        for _top, dirs, files, top_fd in os.fwalk(".", dir_fd=fd, topdown=False,
                                                  follow_symlinks=False):  # fmt: skip
            for entry in files:
                with contextlib.suppress(FileNotFoundError):
                    os.unlink(entry, dir_fd=top_fd)
            for entry in dirs:
                try:
                    os.rmdir(entry, dir_fd=top_fd)
                except NotADirectoryError:  # a link to a directory: the link goes
                    os.unlink(entry, dir_fd=top_fd)
                except FileNotFoundError:
                    pass
    finally:
        os.close(fd)
    try:
        os.rmdir(name, dir_fd=parent_fd)
    except OSError:
        return False
    return True
