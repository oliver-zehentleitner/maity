"""A placement's scratch, made, measured and removed where the agents run (§15.5).

The scratch lies in `<workspaces>/<project_id>/.scratch/<placement id>`, and the agents can
write the project's directory: any directory on the way may have been replaced by a link.
Every operation is anchored at the workspaces root it is given (`under`), and works only
on a placement's scratch below it: that directory is opened, and each one below it is
opened from the one before without following a link, so a name swapped for a link after any
check is refused, never followed out. The last directory is held open by its descriptor for
the whole operation: what is made is made in it, what is measured or removed is reached from
it, each level below opened from the one above (`os.fwalk`). What is emptied is the
directory that was measured; its name is checked against that directory just before the
emptied directory is removed, and past that check at most an empty directory of the same
name could go in its place, never any content. The runner calls this in its own process
when the agents are its own user; through sudo or on an ssh host it starts this module
there (`python -I -m maity.runner.scratchop`, `maity runner scratchop`), which prints its
answer as one JSON line.

Only the standard library: the module runs with `-I` on the agents' side.
"""

from __future__ import annotations

import contextlib
import errno
import json
import os
import re
import secrets
import stat
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import PurePath

OPS = ("make", "size", "remove")
# agy's scratch under the host's shared temp directory (workspace.tmp_scratch_of): a per-user
# parent `maity-scratch-<uid>` (TMP_PARENT_MODE) owned by the user agy runs as, and a
# per-placement leaf (TMP_LEAF) owned private by that user (TMP_LEAF_MODE). The leaf name is a
# random token the runner records (TMP_LEAF), not the placement id, so a user's placements do
# not collide; it is not a secret and gives no separation between two placements of that user.
TMP_PARENT = re.compile(r"^maity-scratch-([0-9]+)$")
# The per-placement leaf's name: a random token the runner chose (secrets.token_hex), not the
# placement id. It only keeps a user's placements from colliding; the separation this scratch
# has is against other host users (file ownership, below) and against the sandboxed Codex and
# Claude Code placements the runner hides the parent from, not against other placements of the
# same user, which the name does not keep apart.
TMP_LEAF = re.compile(r"^[0-9a-f]{32,64}$")
# The per-user parent, owned 0700 by its owner (the user agy runs as): readable and writable by
# that user alone, so another host user cannot enter it. The leaf and all the runner makes in
# it stay private (0700) as well.
TMP_PARENT_MODE = 0o700
TMP_LEAF_MODE = 0o700
TMP_OPS = ("make", "size", "remove")
# A clone's or project's name as the runner takes it (workspace.locate).
TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# A placement's scratch (§15.5): `<workspaces>/<project_id>/.scratch/<placement id>`. A clone's
# name starts with a letter or digit (TOKEN), so `.scratch` is never one.
SCRATCH = ".scratch"
SCRATCH_ID = re.compile(r"^plc-[0-9a-z-]{1,60}$")  # a placement id, as the supervisor takes it
LINK = 4  # the exit code for a link (or no directory) on the way: nothing was done
_FOLDER = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
# A path descriptor opens a directory without needing read or search on it (O_PATH, Linux), so
# a 0000 directory a build tool left can still be reached, checked to be ours and widened; it is
# chmod'd by its /proc/self/fd entry. Both are Linux-only: where either is missing (macOS) a
# directory whose mode denies opening cannot be widened here, and the operation that needs to
# fails rather than silently taking a wrong path (`_open_below`).
_PATH_FD = getattr(os, "O_PATH", 0)
_WIDEN_LOCKED = bool(_PATH_FD) and os.path.isdir("/proc/self/fd")


class OnTheWay(OSError):
    """A name on the way is a link or not a directory: nothing was made or removed."""


class Unsupported(OSError):
    """An ssh host's `maity` has no `codex` op (older than this one): the caller turns this
    into a clean placement refusal, not a crash loop, so the operator upgrades the host."""


def supported() -> bool:
    """Whether this system opens a directory from another without following a link, removes a
    tree from a descriptor, and writes and links a name relative to one (not Windows)."""
    return (
        hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd and hasattr(os, "fwalk")
        # os.replace shares renameat with os.rename, which is the member listed for it.
        and os.rename in os.supports_dir_fd and os.symlink in os.supports_dir_fd
        and os.unlink in os.supports_dir_fd
    )  # fmt: skip


def _below(path: str, under: str) -> list[str]:
    """The names from `under` down to `path`, which must be a scratch's path and nothing
    else: `<under>/<project>/.scratch/<placement id>`."""
    try:
        names = PurePath(path).relative_to(PurePath(under)).parts
    except ValueError:
        raise OSError(f"{path} is not inside {under}") from None
    if not (len(names) == 3 and TOKEN.fullmatch(names[0]) and names[1] == SCRATCH
            and SCRATCH_ID.fullmatch(names[2])):  # fmt: skip
        raise OSError(f"{path} is not a placement's scratch under {under}")
    return list(names)


def _step(fd: int, name: str, make: int | None) -> int:
    """The directory `name` in `fd`, opened without following a link; created with mode
    `make` first when missing."""
    if make is not None:
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, make, dir_fd=fd)
    try:
        return os.open(name, _FOLDER | os.O_NOFOLLOW, dir_fd=fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
            raise OnTheWay(f"{name} is a link or not a directory; nothing done") from None
        raise


@contextlib.contextmanager
def _opened(under: str, names: Sequence[str], make: bool) -> Iterator[int]:
    """The descriptor of the directory `names` lead to from `under`, each opened from the one
    before (`make`: created when missing, the innermost one 0700)."""
    fd = os.open(under, _FOLDER)  # the root the runner was configured with
    try:
        for index, name in enumerate(names):
            mode = (0o700 if index == len(names) - 1 else 0o777) if make else None
            inner = _step(fd, name, mode)
            os.close(fd)
            fd = inner
        yield fd
    finally:
        os.close(fd)


def _size(fd: int) -> int:
    """The bytes under the open directory `fd` (files and directories, as `du -sb` counts
    them), never following a link."""
    total = os.fstat(fd).st_size
    for _top, dirs, files, top_fd in os.fwalk(".", dir_fd=fd, follow_symlinks=False):
        for name in [*dirs, *files]:
            # A restrictive directory a build tool left (a 0400/0000 module cache) denies the
            # stat of its entries; it is counted at what we can reach and emptied below, never
            # left to raise here (so a remove is not blocked before `_empty` widens it).
            with contextlib.suppress(FileNotFoundError, PermissionError):
                total += os.stat(name, dir_fd=top_fd, follow_symlinks=False).st_size
    return total


def make(under: str, path: str) -> dict[str, object]:
    """The scratch at `path` with `tmp` in it, made as needed below the workspaces root,
    which must be there (the runner makes it with the clone)."""
    names = _below(path, under)
    with _opened(under, [*names, "tmp"], make=True):
        pass
    with _opened(under, names, make=False) as scratch:
        # The scratch itself private too, not only its `tmp`: mkdir left it to the umask.
        if stat.S_IMODE(os.fstat(scratch).st_mode) != 0o700:
            os.fchmod(scratch, 0o700)
    return {"result": "made"}


# --- the test clusters' passwords (hub/scripts/with_postgres.sh, MAITY_PG_PASSWORD) -----------
#
# One holder under the workspaces root, `<root>/.maity-pg`, 0700 and owned by the agents' user,
# with one file per placement (`<holder>/<placement id>`, 0600, 64 hex digits, drawn once and
# kept across restarts, removed with the placement). The holder is outside every scratch and
# clone and its path never changes, so every sandbox is denied it from its first start; the
# session never reads the file: the runner's `pgenv` launcher reads it outside the sandbox and
# hands the value to the session in its process environment (the review of #2032).
PG_HOLDER = ".maity-pg"


def _pg_parts(path: str, under: str) -> list[str]:
    """`<under>/.maity-pg` or `<under>/.maity-pg/<placement id>`, and nothing else."""
    try:
        names = list(PurePath(path).relative_to(PurePath(under)).parts)
    except ValueError:
        raise OSError(f"{path} is not inside {under}") from None
    if (
        not names
        or names[0] != PG_HOLDER
        or len(names) > 2
        or (len(names) == 2 and not SCRATCH_ID.fullmatch(names[1]))
    ):
        raise OSError(f"{path} is not the test clusters' password holder or a file in it")
    return names


@contextlib.contextmanager
def _pg_holder(under: str, make: bool) -> Iterator[int]:
    """The holder's descriptor, opened from the workspaces root without following a link and
    checked to be a directory of this user, set to exactly 0700 (`make`: created when missing).
    OnTheWay for a link, not a directory, or another user's."""
    with _opened(under, [], make=False) as root:
        if make:
            with contextlib.suppress(FileExistsError):
                os.mkdir(PG_HOLDER, 0o700, dir_fd=root)
        fd = _step(root, PG_HOLDER, None)
        try:
            found = os.fstat(fd)
            if found.st_uid != _uid(None):
                raise OnTheWay(f"{PG_HOLDER} is another user's directory; not used")
            if make and stat.S_IMODE(found.st_mode) != 0o700:
                os.fchmod(fd, 0o700)
            yield fd
        finally:
            os.close(fd)


def _pg_vouched(dir_fd: int, name: str) -> bool:
    """Whether `name` in the open holder is a regular file of this user, 0600, with one link."""
    found = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    return (stat.S_ISREG(found.st_mode) and found.st_uid == _uid(None)
            and stat.S_IMODE(found.st_mode) == 0o600 and found.st_nlink == 1)  # fmt: skip


def pg_make(under: str, path: str) -> dict[str, object]:
    """The holder (`path` the holder itself) or the holder and the placement's password file
    in it (`path` the file): made 0600 without following a link when missing, a file already
    there kept as it is. `pg_pass`: whether the file is one this op vouches for (a link or
    anything else at the name is left untouched and gives False)."""
    names = _pg_parts(path, under)
    with _pg_holder(under, make=True) as holder:
        if len(names) == 1:
            return {"result": "made"}
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(names[1], flags, 0o600, dir_fd=holder)
        except FileExistsError:
            return {"result": "made", "pg_pass": _pg_vouched(holder, names[1])}
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)  # the mode asked for is subject to the umask
            handle.write(secrets.token_hex(32) + "\n")
        return {"result": "made", "pg_pass": True}


def pg_remove(under: str, path: str) -> dict[str, object]:
    """The placement's password file removed by its name in the holder (a link there goes, not
    what it points to); `missing` when there is none, or no holder."""
    names = _pg_parts(path, under)
    if len(names) != 2:
        raise OSError(f"{path} is not a password file")
    try:
        with _pg_holder(under, make=False) as holder:
            os.unlink(names[1], dir_fd=holder)
    except FileNotFoundError:
        return {"result": "missing"}
    return {"result": "removed"}


PG_PASSWORD = re.compile(r"[A-Za-z0-9._~-]{1,256}")


def pg_read(under: str, path: str) -> str | None:
    """The placement's password, read from the holder without following a link; None when the
    file is missing or not one pg_make would vouch for, or its first line is no password; also
    for a path that is not a placement's file in the holder, or a holder that is a link."""
    try:
        names = _pg_parts(path, under)
        if len(names) != 2:
            return None
        with _pg_holder(under, make=False) as holder:
            # Opened first, then checked on the descriptor itself: nothing swapped in between a
            # check and the open is read, and a FIFO planted at the name does not block.
            flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
            fd = os.open(names[1], flags | getattr(os, "O_CLOEXEC", 0), dir_fd=holder)
            try:  # the descriptor closed on every path, a directory planted at the name too
                found = os.fstat(fd)
                if not (stat.S_ISREG(found.st_mode) and found.st_uid == _uid(None)
                        and stat.S_IMODE(found.st_mode) == 0o600
                        and found.st_nlink == 1):  # fmt: skip
                    return None
                first = os.read(fd, 512).decode("ascii", "replace").split("\n", 1)[0]
            finally:
                os.close(fd)
    except OSError:
        return None
    return first if PG_PASSWORD.fullmatch(first) else None


def size(under: str, path: str) -> dict[str, object]:
    """The bytes under the scratch at `path`; `missing` when there is none."""
    names = _below(path, under)
    try:
        with _opened(under, names[:-1], make=False) as parent:
            fd = _step(parent, names[-1], None)
            try:
                return {"result": "size", "bytes": _size(fd)}
            finally:
                os.close(fd)
    except FileNotFoundError:  # no root, project or `.scratch` either: no scratch
        return {"result": "missing"}


def remove(under: str, path: str) -> dict[str, object]:
    """The scratch at `path` removed from its open parent, with its size before; `missing`
    when there is none."""
    names = _below(path, under)
    try:
        with _opened(under, names[:-1], make=False) as parent:
            return _remove_in(parent, names[-1])
    except FileNotFoundError:  # no root, project or `.scratch` either: no scratch
        return {"result": "missing"}


def _remove_in(parent: int, name: str, uid: int | None = None) -> dict[str, object]:
    """The directory `name` in the open `parent` removed, with its size before: measured and
    emptied through the one descriptor opened for it; `name` is checked against that
    directory just before it is removed (after the check, at most an empty directory of the
    same name could be removed instead, never content). `uid`, when given (the shared-temp
    scratch), is the user the leaf must belong to: it is checked owned by that user, but its
    mode is not required, so an agent that widened or narrowed its own leaf cannot block its own
    cleanup. With `uid` the leaf is opened through `_open_below`, so a leaf whose own mode denies
    opening it (a 0000/0400 directory) is still reached, checked to be this user's and removed,
    and a leaf another user holds is named as a clash (OnTheWay), not raised as a bare
    permission error."""
    try:
        fd = _open_below(parent, name, uid) if uid is not None else _step(parent, name, None)
    except FileNotFoundError:
        return {"result": "missing"}
    try:
        if uid is not None:
            _verify_dir(fd, name, uid)
        # Restore the owner's access on the leaf before measuring it: a leaf a build tool left
        # read-only or unsearchable (0400/0500) would otherwise fail `_size`'s walk of its own
        # entries. The subtree is widened level by level in `_empty` as it descends.
        _widen(fd, uid)
        before = _size(fd)
        _empty(fd, uid)
        held = os.fstat(fd)
        found = os.stat(name, dir_fd=parent, follow_symlinks=False)
        if (found.st_dev, found.st_ino) != (held.st_dev, held.st_ino):
            raise OnTheWay(f"{name} was replaced while it was removed; left as it is")
        os.rmdir(name, dir_fd=parent)
    finally:
        os.close(fd)
    return {"result": "removed", "bytes": before}


def _widen(fd: int, uid: int | None) -> None:
    """Give the owner read, write and search on the open directory `fd`, so a mode that denies
    them (a read-only or unsearchable directory a build tool leaves behind, for example a 0555
    module cache or a 0000 directory) does not block emptying it. Only a directory this `uid`
    owns is touched (when `uid` is given); a beside-clone scratch, under the runner's trusted
    root, passes `uid` None and every directory it holds is the agents' own."""
    found = os.fstat(fd)
    if uid is not None and found.st_uid != uid:
        return
    if stat.S_IMODE(found.st_mode) & 0o700 != 0o700:
        with contextlib.suppress(OSError):
            os.fchmod(fd, stat.S_IMODE(found.st_mode) | 0o700)


def _open_below(parent_fd: int, name: str, uid: int | None) -> int:
    """An open descriptor for the directory `name` in `parent_fd`, never following a link, even
    when its mode denies opening it for reading (a 0000 directory): such a one is reached by a
    path descriptor, which needs no permission, checked to be a directory this `uid` owns, and
    widened to its owner, then opened normally."""
    try:
        return _open_nofollow(parent_fd, name, uid)
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EPERM) or not _WIDEN_LOCKED:
            raise
    pfd = os.open(name, _PATH_FD | getattr(os, "O_DIRECTORY", 0) | os.O_NOFOLLOW, dir_fd=parent_fd)
    try:
        found = os.fstat(pfd)
        if not stat.S_ISDIR(found.st_mode) or (uid is not None and found.st_uid != uid):
            raise OnTheWay(f"{name} is not a directory this user owns; left as it is")
        os.chmod(f"/proc/self/fd/{pfd}", stat.S_IMODE(found.st_mode) | 0o700)
    finally:
        os.close(pfd)
    return _open_nofollow(parent_fd, name, uid)


_Frame = tuple[int, "str | None", int, "Iterator[str]"]


def _scan(parent_fd: int, name: str | None, fd: int, uid: int | None) -> _Frame:
    """A removal frame for the open directory `fd`: its owner's access is restored, its files
    are unlinked now (a link among them removed, never entered), and the frame keeps its
    subdirectory names for the loop to descend. `name` is None for the root, whose `fd` the
    caller keeps open."""
    _widen(fd, uid)
    subdirs: list[str] = []
    for entry in os.listdir(fd):
        try:
            found = os.lstat(entry, dir_fd=fd)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(found.st_mode):
            subdirs.append(entry)
        else:
            with contextlib.suppress(FileNotFoundError):
                os.unlink(entry, dir_fd=fd)
    return (parent_fd, name, fd, iter(subdirs))


def _empty(fd: int, uid: int | None = None) -> None:
    """Everything under the open directory `fd` removed, deepest first, each level reached from
    the one above it without following a link (a link is removed, never entered). The owner's
    access is restored on every directory before its entries go, so a mode that denies write or
    search does not leave the scratch undeletable; an explicit stack, not recursion, so Python's
    own recursion limit is not the bound (a tree deep enough to exhaust open descriptors, EMFILE,
    is still beyond it). Only directories this `uid` owns are touched when `uid` is given. The
    root `fd` is the caller's and is never closed here; every descriptor this walk opens is
    closed, on an exception mid-walk too (the finally below drops any still on the stack)."""
    stack: list[_Frame] = [_scan(-1, None, fd, uid)]
    try:
        while stack:
            parent_fd, name, directory, subdirs = stack[-1]
            child = next(subdirs, None)
            if child is None:
                stack.pop()
                if name is not None:
                    os.close(directory)
                    with contextlib.suppress(FileNotFoundError):
                        os.rmdir(name, dir_fd=parent_fd)
                continue
            try:
                child_fd = _open_below(directory, child, uid)
            except FileNotFoundError:
                continue
            try:
                stack.append(_scan(directory, child, child_fd, uid))
            except BaseException:
                os.close(child_fd)
                raise
    finally:
        # stack[0] holds the caller's root `fd` (name None); the rest are this walk's own
        # descriptors, left open only if an exception broke out of the loop above.
        for frame in stack[1:]:
            with contextlib.suppress(OSError):
                os.close(frame[2])


def codex(under: str, home: str, config_text: str, auth_target: str | None) -> dict[str, object]:
    """Codex's control files written inside the per-placement `home` (`<scratch>/codex-home`),
    each reached from the workspaces root `under` without following a link. The scratch is
    descended as make/size/remove descend it; the `codex-home` leaf is made 0700 and opened
    without following a link, so one swapped for a link (a directory link leading out of the
    scratch) fails the open and the whole operation is refused (OnTheWay), never written
    through. Holding that descriptor: `config.toml` is a temporary file renamed over the name
    (0600), and `auth.json`, when `auth_target` is given, is replaced by a fresh link to it.
    Both leaf names are acted on without following a link, so a link planted at either is
    replaced, not followed."""
    if not supported():
        raise OSError("this system cannot open a directory without following links")
    leaf = PurePath(home).name
    names = _below(str(PurePath(home).parent), under)  # the scratch, anchored as the others are
    with _opened(under, names, make=False) as scratch_fd:
        home_fd = _step(scratch_fd, leaf, 0o700)  # made if missing, then opened no-follow
        try:
            _write_leaf(home_fd, "config.toml", config_text)
            if auth_target is not None:
                _link_leaf(home_fd, "auth.json", auth_target)
        finally:
            os.close(home_fd)
    return {"result": "written"}


def _write_leaf(dir_fd: int, name: str, text: str) -> None:
    """`text` in `name` under the open `dir_fd`, 0600: a temporary file made there without
    following a link, its mode set, then renamed over the name, so a reader never sees a part
    of it and a link planted at the name is replaced, not followed."""
    temporary = f".{name}.{secrets.token_hex(6)}"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    # O_EXCL | O_NOFOLLOW: the open fails if the temporary name already exists (a foreign
    # entry, or a link planted there), and only a name this call created is ours to unlink.
    # So the cleanup sits past the open: a pre-existing entry at the name is never removed.
    fd = os.open(temporary, flags, 0o600, dir_fd=dir_fd)
    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
        os.replace(temporary, name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=dir_fd)
        raise


def _link_leaf(dir_fd: int, name: str, target: str) -> None:
    """A symlink `name` -> `target` under the open `dir_fd`, replacing whatever `name` is now
    (a stale link, a file). The name is removed and remade, each acting on the name itself,
    never on what a link there points to."""
    with contextlib.suppress(FileNotFoundError):
        os.unlink(name, dir_fd=dir_fd)
    os.symlink(target, name, dir_fd=dir_fd)


# --- agy's scratch under the host's shared temp directory (workspace.tmp_scratch_of) ----------
#
# The shared temp directory is writable by every user on the host, so a scratch there is made
# and read with the anti-hijack discipline the beside-clone scratch does not need: the per-user
# parent and the per-placement leaf are each opened without following a link and checked to be
# a directory owned by the user the agents run as (os.getuid where the op runs). A link, a
# directory another user holds, or a leaf that already exists is refused (OnTheWay), never
# written through. The parent (TMP_PARENT_MODE, 0700) and the leaf (TMP_LEAF_MODE, 0700) are
# owned by that user, so another host user cannot enter them; the leaf is made fresh (never
# reused), so nothing foreign sits inside it. The random leaf name (TMP_LEAF) keeps a user's
# own placements from colliding; it is not a secret and gives no separation between two
# placements of the same user, which share the parent and can reach each other's leaf by name.


def _uid(uid: int | None) -> int:
    """The uid the agents run as: the caller's own where the op runs (os.getuid), which under
    the runner is agy's user. `uid` is passed only by a test, to drive the owner check."""
    if uid is not None:
        return uid
    getuid = getattr(os, "getuid", None)
    if getuid is None:
        raise OSError("this system has no uid; no per-uid scratch here")
    return int(getuid())


def _tmp_parts(path: str, uid: int) -> tuple[str, str, str]:
    """`<root>/maity-scratch-<uid>/<leaf>` split into (root, parent, leaf), validated as
    `_below` validates a beside-clone scratch: `path` is absolute with no `..`, the parent
    names exactly this uid (its canonical spelling, so a leading-zero uid is refused), the leaf
    is a random name the runner chose (TMP_LEAF), and the root is a real directory that is
    its own realpath (so a relative, traversing or symlinked root is refused). A path that is
    not exactly `<real root>/maity-scratch-<uid>/<leaf>` is refused before anything is opened."""
    pure = PurePath(path)
    if not pure.is_absolute() or ".." in pure.parts:
        raise OSError(f"{path} is not an absolute scratch path without '..'")
    parent, leaf = pure.parent.name, pure.name
    match = TMP_PARENT.fullmatch(parent)
    if match is None or match.group(1) != str(uid):
        raise OSError(f"{path} is not a shared-temp scratch parent for uid {uid}")
    if not TMP_LEAF.fullmatch(leaf):
        raise OSError(f"{path} does not end in a placement's scratch leaf")
    root = str(pure.parent.parent)
    if root in ("", os.sep) or os.path.realpath(root) != root:
        raise OSError(f"{path} is not under a real (non-symlinked) root")
    return root, parent, leaf


def _open_nofollow(dir_fd: int, name: str, uid: int | None = None) -> int:
    """`name` in `dir_fd` opened as a directory without following a link; OnTheWay for a link
    or a non-directory, FileNotFoundError when it is missing. When opening is denied and `uid`
    is given, the name is a directory another user holds (its mode keeps us out): that is said
    as OnTheWay, so the operator sees a name clash rather than a bare permission error."""
    try:
        return os.open(name, _FOLDER | os.O_NOFOLLOW, dir_fd=dir_fd)
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
            raise OnTheWay(f"{name} is a link or not a directory; nothing done") from None
        if exc.errno in (errno.EACCES, errno.EPERM) and uid is not None:
            try:
                found = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            except OSError:
                found = None
            if found is not None and stat.S_ISDIR(found.st_mode) and found.st_uid != uid:
                raise OnTheWay(
                    f"{name} is held by another user (uid {found.st_uid}, not uid {uid}); not used"
                ) from None
        raise


def _verify_dir(fd: int, name: str, uid: int) -> None:
    """OnTheWay unless the open `fd` is a directory owned by `uid` (its mode is not checked
    here: a read or remove does not require a particular mode, only that it is ours)."""
    found = os.fstat(fd)
    if not stat.S_ISDIR(found.st_mode):
        raise OnTheWay(f"{name} is not a directory; not used")
    if found.st_uid != uid:
        raise OnTheWay(
            f"{name} is held by another user (uid {found.st_uid}, not uid {uid}); not used"
        )


def _verify_mode(fd: int, name: str, mode: int) -> None:
    """OnTheWay unless the open directory `fd` is exactly `mode`."""
    if stat.S_IMODE(os.fstat(fd).st_mode) != mode:
        raise OnTheWay(f"{name} is not mode {mode:#o} as a scratch must be; not used")


def _tmp_dir(dir_fd: int, name: str, uid: int, mode: int, *, fresh: bool) -> int:
    """The directory `name` in `dir_fd`, created `mode` when missing, opened without following
    a link and checked owned by `uid` and set to exactly `mode`. `fresh`: it must not already
    exist (the per-placement leaf and the `tmp` in it are never reused, so a planted or
    left-over one is refused). A directory that exists and this uid owns but whose mode differs
    (a per-user parent an earlier placement left, or one widened since) is brought to `mode`
    only after its ownership is confirmed, so the owner's layout is normalised, never another's.
    `mode` is set explicitly because mkdir is subject to the umask. The open goes through
    `_open_below`, so a directory this uid owns but whose mode denies opening it (a leftover
    parent narrowed below 0700, say) is still reached, checked and widened, rather than refused."""
    try:
        os.mkdir(name, mode, dir_fd=dir_fd)
    except FileExistsError:
        if fresh:
            raise OnTheWay(f"{name} already exists; a scratch is made fresh, not reused") from None
    fd = _open_below(dir_fd, name, uid)
    try:
        _verify_dir(fd, name, uid)
        if stat.S_IMODE(os.fstat(fd).st_mode) != mode:
            os.fchmod(fd, mode)
        _verify_mode(fd, name, mode)
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextlib.contextmanager
def _tmp_parent(root: str, parent: str, uid: int) -> Iterator[int | None]:
    """The per-user scratch parent `parent` under `root`, opened without following a link and
    checked owned by `uid`; None when it is not there. Its mode is not required here (a read or
    remove must work on a parent an agent has widened or narrowed); only ownership is. The open
    goes through `_open_below`, so a parent whose mode denies opening it but which this uid owns
    is still reached. Never created here: size and remove make no parent."""
    base_fd = os.open(root, _FOLDER)
    try:
        try:
            fd = _open_below(base_fd, parent, uid)
        except FileNotFoundError:
            yield None
            return
    finally:
        os.close(base_fd)
    try:
        _verify_dir(fd, parent, uid)
        yield fd
    finally:
        os.close(fd)


def _tmp_parent_part(path: str, uid: int) -> tuple[str, str]:
    """`<root>/maity-scratch-<uid>` split into (root, parent), validated as `_tmp_parts`
    validates a leaf path: absolute with no `..`, the parent names exactly this uid (its
    canonical spelling), and the root is a real directory that is its own realpath."""
    pure = PurePath(path)
    if not pure.is_absolute() or ".." in pure.parts:
        raise OSError(f"{path} is not an absolute scratch parent path without '..'")
    parent = pure.name
    match = TMP_PARENT.fullmatch(parent)
    if match is None or match.group(1) != str(uid):
        raise OSError(f"{path} is not a shared-temp scratch parent for uid {uid}")
    root = str(pure.parent)
    if root in ("", os.sep) or os.path.realpath(root) != root:
        raise OSError(f"{path} is not under a real (non-symlinked) root")
    return root, parent


def tmp_parent_make(path: str, uid: int | None = None) -> dict[str, object]:
    """The per-user agy scratch parent at `path` (`<root>/maity-scratch-<uid>`), created or
    adopted when already this uid's own and brought to TMP_PARENT_MODE (0700). The runner makes
    it before a non-agy placement that only hides it starts, so the deny path the sandbox is
    given is a real directory rather than a missing path a placeholder would stand in for; an
    agy placement of the same user then finds the parent, not a file. A link or a directory
    another user holds is refused (OnTheWay), never written through."""
    if not supported():
        raise OSError("this system cannot open a directory without following links")
    uid = _uid(uid)
    root, parent = _tmp_parent_part(path, uid)
    base_fd = os.open(root, _FOLDER)
    try:
        os.close(_tmp_dir(base_fd, parent, uid, TMP_PARENT_MODE, fresh=False))
    finally:
        os.close(base_fd)
    return {"result": "made"}


def tmp_make(path: str, uid: int | None = None) -> dict[str, object]:
    """The agy scratch at `path` under the shared temp directory with `tmp` in it: a per-user
    parent, created or adopted when already this uid's own (and brought to TMP_PARENT_MODE,
    0700), and a per-placement leaf made fresh (TMP_LEAF_MODE) with a fresh `tmp` inside it. A
    link, a directory another user holds, or a leaf (or `tmp`) that already exists is refused
    (OnTheWay), never written through."""
    if not supported():
        raise OSError("this system cannot open a directory without following links")
    uid = _uid(uid)
    root, parent, leaf = _tmp_parts(path, uid)
    base_fd = os.open(root, _FOLDER)
    try:
        parent_fd = _tmp_dir(base_fd, parent, uid, TMP_PARENT_MODE, fresh=False)
    finally:
        os.close(base_fd)
    try:
        leaf_fd = _tmp_dir(parent_fd, leaf, uid, TMP_LEAF_MODE, fresh=True)
        try:
            # The `tmp` in the leaf is made with the same fresh, no-follow, owner-and-mode
            # discipline, so a sibling of the same user that planted a link or a wrong-mode
            # directory at `<leaf>/tmp` between the leaf's creation and here is refused.
            os.close(_tmp_dir(leaf_fd, "tmp", uid, TMP_LEAF_MODE, fresh=True))
        finally:
            os.close(leaf_fd)
    finally:
        os.close(parent_fd)
    return {"result": "made"}


def tmp_size(path: str, uid: int | None = None) -> dict[str, object]:
    """The bytes under the agy scratch at `path`; `missing` when the parent or the leaf is not
    there. The parent and the leaf are each checked owned by `uid` before the leaf is
    measured."""
    if not supported():
        raise OSError("this system cannot open a directory without following links")
    uid = _uid(uid)
    root, parent, leaf = _tmp_parts(path, uid)
    with _tmp_parent(root, parent, uid) as parent_fd:
        if parent_fd is None:
            return {"result": "missing"}
        try:
            fd = _open_nofollow(parent_fd, leaf, uid)
        except FileNotFoundError:
            return {"result": "missing"}
        try:
            _verify_dir(fd, leaf, uid)
            return {"result": "size", "bytes": _size(fd)}
        finally:
            os.close(fd)


def tmp_remove(path: str, uid: int | None = None) -> dict[str, object]:
    """The agy scratch at `path` removed, with its size before; `missing` when there is none.
    The parent is checked owned by `uid`; the leaf is checked owned by `uid` (its mode is not
    required) and then it and all below it are removed from the parent's descriptor as `remove`
    does (`_remove_in`)."""
    if not supported():
        raise OSError("this system cannot open a directory without following links")
    uid = _uid(uid)
    root, parent, leaf = _tmp_parts(path, uid)
    with _tmp_parent(root, parent, uid) as parent_fd:
        if parent_fd is None:
            return {"result": "missing"}
        return _remove_in(parent_fd, leaf, uid=uid)


def tmp_run(op: str, path: str) -> dict[str, object]:
    if op not in TMP_OPS:
        raise OSError(f"unknown operation {op}")
    return {"make": tmp_make, "size": tmp_size, "remove": tmp_remove}[op](path)


def run(op: str, under: str, path: str) -> dict[str, object]:
    if op not in OPS:
        raise OSError(f"unknown operation {op}")
    if not supported():
        raise OSError("this system cannot open a directory without following links")
    return {"make": make, "size": size, "remove": remove}[op](under, path)


def _emit(call: Callable[[], dict[str, object]]) -> int:
    """Print one JSON line for `call`'s answer, or say `link` by the exit code; a failure goes
    to stderr with exit 1. `call` is a zero-argument callable returning the answer dict."""
    try:
        answer = call()
    except OnTheWay as exc:
        print(json.dumps({"result": "link", "why": str(exc)}))
        return LINK
    except OSError as exc:
        print(f"scratch: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(answer))
    return 0


def _main_codex(args: Sequence[str]) -> int:
    """`codex --under DIR [--auth TARGET] HOME`, the config.toml text on stdin."""
    under: str | None = None
    auth: str | None = None
    positional: list[str] = []
    rest = list(args)
    index = 0
    while index < len(rest):
        word = rest[index]
        if word == "--under" and index + 1 < len(rest):
            under, index = rest[index + 1], index + 2
        elif word == "--auth" and index + 1 < len(rest):
            auth, index = rest[index + 1], index + 2
        else:
            positional.append(word)
            index += 1
    if under is None or len(positional) != 1:
        print("usage: scratchop codex --under DIR [--auth TARGET] HOME", file=sys.stderr)
        return 2
    home = positional[0]
    config_text = sys.stdin.read()
    return _emit(lambda: codex(under, home, config_text, auth))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "codex":
        return _main_codex(args[1:])
    if args and args[0] in ("pgmake", "pgremove"):
        if len(args) != 4 or args[1] != "--under":
            print("usage: scratchop pgmake|pgremove --under DIR PATH", file=sys.stderr)
            return 2
        if not supported():
            print("scratch: this system cannot open a directory without following links",
                  file=sys.stderr)  # fmt: skip
            return 1
        pg_op = pg_make if args[0] == "pgmake" else pg_remove
        return _emit(lambda: pg_op(args[2], args[3]))
    if args and args[0] == "tmpparent":
        if len(args) != 2:
            print("usage: scratchop tmpparent PATH", file=sys.stderr)
            return 2
        return _emit(lambda: tmp_parent_make(args[1]))
    if args and args[0] in ("tmpmake", "tmpsize", "tmpremove"):
        if len(args) != 2:
            print("usage: scratchop tmpmake|tmpsize|tmpremove PATH", file=sys.stderr)
            return 2
        op = args[0].removeprefix("tmp")
        return _emit(lambda: tmp_run(op, args[1]))
    if len(args) != 4 or args[1] != "--under" or args[0] not in OPS:
        print("usage: scratchop make|size|remove --under DIR PATH", file=sys.stderr)
        return 2
    op, _flag, under, path = args
    return _emit(lambda: run(op, under, path))


if __name__ == "__main__":
    sys.exit(main())
