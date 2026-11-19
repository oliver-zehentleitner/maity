"""Clearing a Claude Code subagent's leftover worktree from a placement's clone (§15.5).

Claude Code's worktree-isolation feature leaves a git worktree at `.claude/worktrees/agent-<id>`
inside the placement's clone. git registers its admin data under `.git/worktrees/<name>/`, so
`.git/worktrees` is no longer empty and the clone check reads the clone as unsupported
("Worktrees are"): `maity report` and the next placement start refuse before running git. Inside
the sandbox the agent cannot remove either the worktree or `.claude/worktrees/*` (protected
paths), so without help a session is stuck until a human cleans the host.

Two ways out, both scoped to the clone's own `.claude/worktrees/` and both refusing anything that
points elsewhere (a worktree pointing out of the clone stays genuinely unsupported — never
touched):

- `clean` is the agent-callable op (`maity runner worktree-clean`), run from inside the placed
  session by `maity`, which runs outside the harness sandbox as the clone's owner and so has the
  rights the sandbox denies the agent's own `git`/`rm`. It runs `git worktree remove` +
  `git worktree prune` through the pinned git `clonecheck.worktree_git` hands it (the recorded
  git, the clone's configuration checked plain, hooks and fsmonitor off), so git starts no program
  the agent chose. It keeps a worktree that has uncommitted changes unless `--force` is passed.

- `prune_orphans` is the hygiene step the supervisor runs on every placement (re)start, before the
  clone check would refuse a leftover. It runs no git — the runner never runs git in an existing
  clone, which would run the agent's code as the runner — and so removes by file operations only,
  each directory opened from the one above without following a link. Having no git, it cannot read
  whether a leftover holds uncommitted changes, so it always clears an in-scope one; the live,
  work-preserving guard is `clean`'s, for the session that is still running.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from pathlib import Path

from .. import clonecheck, proc

_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_OPEN_DIR = os.O_RDONLY | _DIRECTORY | _CLOEXEC
_OPEN_DIR_NOFOLLOW = _OPEN_DIR | _NOFOLLOW
STATUS_TIMEOUT = 30.0
REMOVE_TIMEOUT = 120.0


class Refused(Exception):
    """The op clears nothing and says why (an out-of-scope worktree, or uncommitted changes
    without `--force`)."""


def supported() -> bool:
    """Whether this system opens a directory from another without following a link (not
    Windows); the runner is POSIX-only, but the op fails closed where it is not."""
    return hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd


# --- the agent-callable op (git) -------------------------------------------------------------


def clean(root: Path, pinned: clonecheck.Pinned, *, force: bool) -> dict[str, object]:
    """Clear the clone's leftover worktrees under `.claude/worktrees/` with the pinned git,
    returning the clone to a plain state. Refuses, touching nothing, when a registered worktree
    points anywhere else, or when an in-scope one has uncommitted changes and `--force` was not
    passed. `pinned` is `clonecheck.worktree_git`'s git and environment."""
    if not supported():
        raise Refused("this system cannot clear a worktree without following links")
    registered = _registered(root)
    if not registered:
        return {"result": "clean", "removed": []}
    in_scope, elsewhere = _partition(root, registered)
    if elsewhere:
        shown = ", ".join(str(w) for w in elsewhere)
        raise Refused(
            f"the clone has a worktree that does not resolve under .claude/worktrees/: {shown};"
            " maity leaves it alone — a worktree pointing elsewhere is not a Claude Code"
            " subagent's leftover and stays unsupported until a person looks at it"
        )
    if not force:
        dirty = [w for w in in_scope if _is_dirty(pinned, w)]
        if dirty:
            shown = ", ".join(str(w) for w in dirty)
            raise Refused(
                f"the worktree under .claude/worktrees/ has uncommitted changes: {shown}; pass"
                " --force to discard them, or commit or merge the work from that worktree first"
            )
    removed: list[str] = []
    for working in in_scope:
        _run_git(pinned, root, "worktree", "remove", "--force", str(working))
        removed.append(str(working))
    _run_git(pinned, root, "worktree", "prune")
    return {"result": "cleared", "removed": removed}


def _registered(root: Path) -> list[tuple[str, Path | None]]:
    """Each `.git/worktrees/<name>` and the working tree it registers (None when unreadable)."""
    admin_root = root / ".git" / "worktrees"
    try:
        names = sorted(os.listdir(admin_root))
    except OSError:
        return []
    return [(name, clonecheck._gitdir_working_tree(admin_root / name)) for name in names]


def _partition(
    root: Path, registered: list[tuple[str, Path | None]]
) -> tuple[list[Path], list[Path]]:
    """The registered worktrees split into those whose working tree resolves (no link on the
    way) under this clone's `.claude/worktrees/` and those that do not. A missing working tree,
    one pointing elsewhere, or one reached through a link counts as the second kind."""
    in_scope: list[Path] = []
    elsewhere: list[Path] = []
    scope = _scope_fd(root)
    try:
        for name, working in registered:
            if (
                working is not None
                and clonecheck._under_claude_worktrees(root, working)
                and scope is not None
                and _is_real_dir(scope, working.name)
            ):
                in_scope.append(working)
            else:
                elsewhere.append(
                    working if working is not None else root / ".git" / "worktrees" / name
                )
    finally:
        if scope is not None:
            os.close(scope)
    return in_scope, elsewhere


def _is_dirty(pinned: clonecheck.Pinned, working: Path) -> bool:
    """Whether the worktree has staged, unstaged or untracked changes, read with the pinned
    git. A git that cannot answer is treated as dirty, so nothing is discarded on a doubt."""
    done = _git(pinned, working, "status", "--porcelain", "--untracked-files=all")
    return done.returncode != 0 or bool(done.stdout.strip())


def _run_git(pinned: clonecheck.Pinned, cwd: Path, *args: str) -> None:
    done = _git(pinned, cwd, *args)
    if done.returncode != 0:
        tail = (done.stderr or done.stdout or "").strip().splitlines()
        why = tail[-1] if tail else f"git exited {done.returncode}"
        raise Refused(f"`git {args[0]} {args[1] if len(args) > 1 else ''}`".rstrip() + f": {why}")


def _git(pinned: clonecheck.Pinned, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """One git run for the op: the pinned git with the worktree pins, the pinned environment,
    no inherited one, stdin closed and a timeout, so it never waits on a person."""
    timeout = STATUS_TIMEOUT if args[0] == "status" else REMOVE_TIMEOUT
    return subprocess.run(  # noqa: S603 - pinned git, fixed argv
        [pinned.git, *clonecheck.WORKTREE_GIT_PINS, *args],
        cwd=cwd,
        env={**pinned.env, **proc.NO_PROMPT},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


# --- the supervisor's hygiene step (no git) --------------------------------------------------


def prune_orphans(repo: str) -> dict[str, object]:
    """Remove the clone's leftover worktrees under `.claude/worktrees/` by file operations only,
    no git: each `.git/worktrees/<name>` that registers a working tree under `.claude/worktrees/`,
    and every directory directly under `.claude/worktrees/`. A registered worktree pointing
    elsewhere is left (`.git/worktrees/<name>` and whatever it names are untouched), so a planted
    redirect out of the clone still refuses the start. Every directory is opened from the one
    above without following a link, and a link under `.claude/worktrees/` is left, never entered
    or followed. Returns what was removed and what was left, both for the runner's log."""
    root = Path(repo)
    removed: list[str] = []
    left: list[str] = []
    if not supported():
        return {"result": "unsupported", "removed": removed, "left": left}
    admin_root = root / ".git" / "worktrees"
    for name in _names(admin_root):
        working = clonecheck._gitdir_working_tree(admin_root / name)
        if working is not None and clonecheck._under_claude_worktrees(root, working):
            _remove_admin(root, name)
            removed.append(f".git/worktrees/{name}")
        else:
            left.append(f".git/worktrees/{name}")
    scope = _scope_fd(root)
    if scope is not None:
        try:
            for name in sorted(os.listdir(scope)):
                if _is_real_dir(scope, name):
                    _remove_tree(scope, name)
                    removed.append(f".claude/worktrees/{name}")
                else:  # a link, a file, a device: never followed, left for a person
                    left.append(f".claude/worktrees/{name}")
        finally:
            os.close(scope)
    return {"result": "pruned", "removed": removed, "left": left}


def _names(directory: Path) -> list[str]:
    try:
        return sorted(os.listdir(directory))
    except OSError:
        return []


def _remove_admin(root: Path, name: str) -> None:
    """Remove `.git/worktrees/<name>`, reached from the clone without following a link."""
    parent = _descend(root, (".git", "worktrees"))
    if parent is None:
        return
    try:
        _remove_tree(parent, name)
    finally:
        os.close(parent)


# --- descriptor-relative paths, no link followed ---------------------------------------------


def _scope_fd(root: Path) -> int | None:
    """The descriptor of `<root>/.claude/worktrees`, each level opened from the one above
    without following a link; None when a level is missing or is a link."""
    return _descend(root, clonecheck.CLAUDE_WORKTREES)


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


def _remove_tree(parent_fd: int, name: str) -> None:
    """Remove the directory `name` in `parent_fd` and everything under it, deepest first, each
    level reached from the one above without following a link (a link is removed, never
    entered)."""
    try:
        fd = os.open(name, _OPEN_DIR_NOFOLLOW, dir_fd=parent_fd)
    except OSError:
        return
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
    with contextlib.suppress(OSError):
        os.rmdir(name, dir_fd=parent_fd)
