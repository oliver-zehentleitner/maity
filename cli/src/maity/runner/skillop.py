"""The delivered Keep the Why skill on the agents' side: put there and checked (skills.py).

The runner fetches the skill and checks it in its own skills directory (skills.ensure). Where
the agents cannot read that directory (the agent_user layout, an ssh host), it hands the
checked files to this module, run as the agents' user, which keeps them under that user's
`~/.local/share/maity-runner/skills/keep-the-why/<key>/` (AGENT_SKILLS): the runner's own
default path, in no sandbox's deny list (tsk-7casfxb7cn49). Every directory from the agents'
home down is opened from the one before without following a link, so a name swapped for a
link is refused (OnTheWay), never written through. A copy is written whole into a fresh
staging directory, its manifest last, and renamed into place; the runner compares the
manifest's SHA-256 with the one it recorded (skills.ANCHORS) at every start, so a copy changed
on the agents' side is put again or not handed out.

`verify` is the one check of a copy, the runner's own included: every directory, the manifest
and every file are reached from a descriptor without following a link, each file opened without
waiting on a FIFO and its type checked on the descriptor before anything is read, within the
bounds the fetch holds.

Imports only the standard library and scratchop (its removal of a tree that may hold restrictive
directories), which does the same: like scratchop it runs with `-I` on the agents' side, through
sudo as `python -I -m maity.runner.skillop`, and on an ssh host as `maity runner skillop`.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import errno
import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from maity.runner import scratchop

NAME = "keep-the-why"
MANIFEST = "manifest.json"
PLUGIN = "plugin"
MAX_FILES = 200  # the skill's own files; plugin.json comes on top
MAX_BYTES = 4 * 1024 * 1024
MANIFEST_MAX = 64 * 1024
KEY = re.compile(r"[0-9a-f]{40}-[0-9a-f]{16}")
COMMIT = re.compile(r"[0-9a-f]{40}")
# Below the agents' home: the runner's own default skills directory (config.DEFAULT_SKILLS_DIR),
# here for the agents' user. Not under `~/.maity-runner` (agent_files), which every sandbox is
# denied, so the session's existing read rule reaches it without a wider allow.
AGENT_SKILLS = (".local", "share", "maity-runner", "skills")
STAGING = ".put-"
_FOLDER = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_FILE = os.O_RDONLY | _NOFOLLOW | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


class Mismatch(Exception):
    """The copy is not what it must be; the message says what, for the runner's log."""


class OnTheWay(OSError):
    """A directory between the agents' home and the copy is a link or no directory."""


def agent_root(home: Path) -> Path:
    """The agents' skills directory below their `home`, as AGENT_SKILLS names it."""
    return home.joinpath(*AGENT_SKILLS)


def agent_copy(home: Path, key: str) -> Path:
    """The copy `key` on the agents' side; its plugin root is `/ PLUGIN`."""
    return agent_root(home) / NAME / key


# --- checking a copy ----------------------------------------------------------------------------


def verify_path(
    copy: Path, source: str, commit: str, max_files: int = MAX_FILES, max_bytes: int = MAX_BYTES,
    manifest_max: int = MANIFEST_MAX,
) -> str:  # fmt: skip
    """`verify` on the copy at `copy`, the directory itself opened without following a link;
    the manifest's SHA-256."""
    try:
        fd = os.open(copy, _FOLDER | _NOFOLLOW)
    except OSError:
        raise Mismatch(f"{copy} in the skill's copy is not a plain directory") from None
    try:
        return verify(fd, copy, source, commit, max_files, max_bytes, manifest_max)
    finally:
        os.close(fd)


def verify(
    copy_fd: int, copy: Path, source: str, commit: str, max_files: int = MAX_FILES,
    max_bytes: int = MAX_BYTES, manifest_max: int = MANIFEST_MAX,
) -> str:  # fmt: skip
    """The open copy `copy_fd` (named `copy` in messages) holds `source` at `commit` as its
    manifest says: every file the manifest names, with its hash, and nothing else, none of them
    a link, within the bounds. Every directory below the plugin root must be one a named file
    lies in, and one that cannot be opened and listed is a mismatch, never skipped: whatever
    could lie in it is not checked (the review of #2089). The manifest's SHA-256; Mismatch
    otherwise."""
    raw = _read_at(copy_fd, MANIFEST, manifest_max, copy / MANIFEST, max_bytes)
    try:
        manifest = json.loads(raw.decode("utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise Mismatch(f"{copy / MANIFEST} is not a manifest the runner wrote") from None
    if manifest.get("source") != source or manifest.get("commit") != commit:
        raise Mismatch(f"the skill's copy at {copy} is not of {source} at {commit}")
    # The directories the named files need: each file's parents below the plugin root.
    needed = {str(p) for name in files for p in PurePosixPath(str(name)).parents}
    plugin_fd = _dir_at(copy_fd, PLUGIN, copy / PLUGIN)
    found: dict[str, str] = {}
    total = 0

    def unreadable(exc: OSError) -> None:
        raise Mismatch(f"a directory in the skill's copy at {copy} cannot be read") from None

    try:
        walk = os.fwalk(".", dir_fd=plugin_fd, follow_symlinks=False, onerror=unreadable)
        for top, dirs, names, top_fd in walk:
            where = PurePosixPath(PLUGIN, top)
            for name in dirs:
                _kind_at(top_fd, name, stat.S_ISDIR, "directory", copy / where / name)
                if str(where / name) not in needed:
                    raise Mismatch(f"{copy / where / name} is not a directory of the skill")
            for name in names:
                if len(found) >= max_files + 1:  # the skill's files and plugin.json
                    raise Mismatch(f"the skill's copy at {copy} has too many files")
                path = copy / where / name
                data = _read_at(top_fd, name, max_bytes + manifest_max - total, path, max_bytes)
                total += len(data)
                found[(where / name).as_posix()] = hashlib.sha256(data).hexdigest()
    finally:
        os.close(plugin_fd)
    if found != files:
        raise Mismatch(f"the skill's copy at {copy} does not match its manifest")
    return hashlib.sha256(raw).hexdigest()


def _dir_at(fd: int, name: str, path: Path) -> int:
    try:
        return os.open(name, _FOLDER | _NOFOLLOW, dir_fd=fd)
    except FileNotFoundError:
        raise Mismatch(f"{path} is missing from the skill's copy") from None
    except OSError:
        raise Mismatch(f"{path} in the skill's copy is not a plain directory") from None


def _kind_at(fd: int, name: str, test: Any, what: str, path: Path) -> None:
    try:
        mode = os.lstat(name, dir_fd=fd).st_mode
    except OSError:
        raise Mismatch(f"{path} is missing from the skill's copy") from None
    if stat.S_ISLNK(mode) or not test(mode):
        raise Mismatch(f"{path} in the skill's copy is not a plain {what}")


def _read_at(fd: int, name: str, limit: int, path: Path, max_bytes: int) -> bytes:
    """A regular file's bytes, at most `limit`; refused rather than followed or waited on. The
    type is checked on the descriptor, so nothing swapped in between counts."""
    try:
        file_fd = os.open(name, _FILE, dir_fd=fd)
    except OSError:
        raise Mismatch(f"{path} in the skill's copy cannot be opened as a plain file") from None
    try:
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise Mismatch(f"{path} in the skill's copy is not a plain file")
        if info.st_size > limit:
            raise Mismatch(f"the skill's copy is larger than {max_bytes} bytes")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(file_fd, 65536):
            size += len(chunk)
            if size > limit:
                raise Mismatch(f"the skill's copy is larger than {max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        raise Mismatch(f"{path} in the skill's copy cannot be read") from None
    finally:
        os.close(file_fd)


# --- the payload the runner sends ---------------------------------------------------------------


def payload(copy: Path, key: str) -> str:
    """The runner's checked copy at `copy` as one JSON document for `put`: the key, the manifest
    and every file it names, as base64. Read from descriptors without following a link, as
    `verify` reads them; the caller checked the copy just before. Mismatch for a copy that
    changed since into something that is no copy (the review of #2089)."""
    try:
        fd = os.open(copy, _FOLDER | _NOFOLLOW)
    except OSError:
        raise Mismatch(f"{copy} in the skill's copy is not a plain directory") from None
    try:
        raw = _read_at(fd, MANIFEST, MANIFEST_MAX, copy / MANIFEST, MAX_BYTES)
        try:
            manifest = json.loads(raw.decode("utf-8"))
            names = sorted(str(n) for n in manifest["files"])
        except (ValueError, KeyError, TypeError):
            raise Mismatch(f"{copy / MANIFEST} is not a manifest the runner wrote") from None
        files: dict[str, str] = {}
        for name in names:
            parts = PurePosixPath(name).parts
            parent = fd
            opened: list[int] = []
            try:
                for part in parts[:-1]:
                    parent = _dir_at(parent, part, copy / name)
                    opened.append(parent)
                data = _read_at(parent, parts[-1], MAX_BYTES, copy / name, MAX_BYTES)
            finally:
                for held in opened:
                    os.close(held)
            files[name] = base64.b64encode(data).decode("ascii")
    finally:
        os.close(fd)
    document = {"key": key, "manifest": base64.b64encode(raw).decode("ascii"), "files": files}
    return json.dumps(document)


def _decoded(document: Mapping[str, Any]) -> tuple[str, bytes, dict[str, Any], dict[str, bytes]]:
    """The key, the manifest's bytes and contents, and the files of a `put` document, each file
    checked against the manifest, the paths against what the runner writes, within the bounds;
    Mismatch otherwise. Nothing is written before this has passed."""
    key = document.get("key")
    if not isinstance(key, str) or not KEY.fullmatch(key):
        raise Mismatch("the skill's key is not one the runner makes")
    try:
        raw = base64.b64decode(str(document["manifest"]), validate=True)
        manifest = json.loads(raw.decode("utf-8"))
        named = manifest["files"]
        sent = document["files"]
        if not (isinstance(named, dict) and isinstance(sent, dict)):
            raise TypeError
    except (KeyError, TypeError, ValueError, binascii.Error):
        raise Mismatch("the skill's payload is not one the runner sends") from None
    if len(raw) > MANIFEST_MAX:
        raise Mismatch("the skill's manifest is too large")
    commit, source = manifest.get("commit"), manifest.get("source")
    if not (isinstance(commit, str) and COMMIT.fullmatch(commit) and isinstance(source, str)):
        raise Mismatch("the skill's manifest names no source and commit")
    if not key.startswith(f"{commit}-") or key != _key(source, commit):
        raise Mismatch("the skill's key is not the one of its source and commit")
    if set(named) != set(sent):
        raise Mismatch("the skill's payload does not hold exactly the files its manifest names")
    if not named:
        raise Mismatch("the skill's payload holds no files")
    if len(named) > MAX_FILES + 1:
        raise Mismatch("the skill has too many files")
    files: dict[str, bytes] = {}
    total = 0
    for name, encoded in sorted(sent.items()):
        parts = PurePosixPath(name).parts
        if ("\0" in name or len(parts) < 2 or parts[0] != PLUGIN
                or name != PurePosixPath(*parts).as_posix()
                or any(p in ("", ".", "..") or p.startswith(".git") for p in parts)):  # fmt: skip
            raise Mismatch(f"the skill holds a path the runner does not write: {name[:200]}")
        try:
            data = base64.b64decode(str(encoded), validate=True)
        except (ValueError, binascii.Error):
            raise Mismatch(f"the skill's file {name[:200]} is not base64") from None
        total += len(data)
        if total > MAX_BYTES + MANIFEST_MAX:
            raise Mismatch(f"the skill is larger than {MAX_BYTES} bytes")
        if hashlib.sha256(data).hexdigest() != named[name]:
            raise Mismatch(f"the skill's file {name[:200]} does not match its manifest")
        files[name] = data
    return key, raw, manifest, files


def _key(source: str, commit: str) -> str:
    """skills.key, here without importing it (standard library only)."""
    return f"{commit}-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}"


# --- the agents' side ---------------------------------------------------------------------------


@contextlib.contextmanager
def _holder(home: str, make: bool) -> Iterator[int]:
    """The open `keep-the-why` directory below the agents' `home`, each level opened from the
    one before without following a link; made 0755 where missing when `make`. FileNotFoundError
    when it is missing and not made; OnTheWay for a link or no directory on the way."""
    fd = os.open(home, _FOLDER)  # the agents' home, as the runner read it
    try:
        for name in (*AGENT_SKILLS, NAME):
            if make:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(name, 0o755, dir_fd=fd)
            try:
                inner = os.open(name, _FOLDER | _NOFOLLOW, dir_fd=fd)
            except OSError as exc:
                if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EMLINK):
                    raise OnTheWay(f"{name} below {home} is a link or no directory") from None
                raise
            os.close(fd)
            fd = inner
        yield fd
    finally:
        os.close(fd)


def check(home: str, key: str, source: str, commit: str) -> dict[str, object]:
    """The copy `key` below the agents' `home`: `ok` with its manifest's SHA-256, `missing`, or
    `mismatch` with why. The runner hands it out only when the digest is the one it recorded."""
    if not KEY.fullmatch(key):
        raise OSError("the skill's key is not one the runner makes")
    try:
        with _holder(home, make=False) as holder:
            try:
                copy_fd = os.open(key, _FOLDER | _NOFOLLOW, dir_fd=holder)
            except FileNotFoundError:
                return {"result": "missing"}
            except OSError:
                return {"result": "mismatch", "why": f"{key} is not a plain directory"}
            try:
                digest = verify(copy_fd, agent_copy(Path(home), key), source, commit)
            except Mismatch as exc:
                return {"result": "mismatch", "why": str(exc)}
            finally:
                os.close(copy_fd)
    except FileNotFoundError:
        return {"result": "missing"}
    return {"result": "ok", "digest": digest}


def put(home: str, document: Mapping[str, Any]) -> dict[str, object]:
    """The copy the runner sent (`payload`) written below the agents' `home`: checked whole
    first (`_decoded`), then written into a fresh staging directory (0644 files in 0755
    directories, the manifest last) and renamed into place; a copy already there under the key
    is replaced. `put` with the manifest's SHA-256."""
    try:
        key, raw, manifest, files = _decoded(document)
    except Mismatch as exc:
        raise OSError(str(exc)) from None
    staging = f"{STAGING}{secrets.token_hex(8)}"
    with _holder(home, make=True) as holder:
        os.mkdir(staging, 0o700, dir_fd=holder)
        try:
            staged = os.open(staging, _FOLDER | _NOFOLLOW, dir_fd=holder)
            try:
                for name, data in files.items():
                    _write_into(staged, PurePosixPath(name).parts, data)
                _write_file(staged, MANIFEST, raw)
                # Each directory 0755 through its own descriptor: no chmod by name, which would
                # need follow_symlinks=False, not supported for chmod on Linux.
                for _top, _dirs, _names, top_fd in os.fwalk(".", dir_fd=staged,
                                                            follow_symlinks=False):  # fmt: skip
                    os.fchmod(top_fd, 0o755)  # noqa: S103 - read by the session only
                os.fchmod(staged, 0o755)  # noqa: S103 - read by the session, written by nobody
                try:
                    digest = verify(staged, Path(staging), str(manifest["source"]),
                                    str(manifest["commit"]))  # fmt: skip
                except Mismatch as exc:
                    raise OSError(f"the staged copy does not hold: {exc}") from None
            finally:
                os.close(staged)
            _replace(holder, staging, key)
        except BaseException:
            with contextlib.suppress(OSError):
                _remove_tree(holder, staging)
            raise
    return {"result": "put", "digest": digest}


def _write_into(root_fd: int, parts: Sequence[str], data: bytes) -> None:
    """`data` at `parts` below the open `root_fd`, its directories made on the way (never
    following a link: the staging directory is fresh and private until the rename)."""
    fd = root_fd
    opened: list[int] = []
    try:
        for part in parts[:-1]:
            with contextlib.suppress(FileExistsError):
                os.mkdir(part, 0o700, dir_fd=fd)
            fd = os.open(part, _FOLDER | _NOFOLLOW, dir_fd=fd)
            opened.append(fd)
        _write_file(fd, parts[-1], data)
    finally:
        for held in opened:
            os.close(held)


def _write_file(dir_fd: int, name: str, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(name, flags, 0o644, dir_fd=dir_fd)
    with os.fdopen(fd, "wb") as out:
        os.fchmod(out.fileno(), 0o644)  # whatever the umask
        out.write(data)


def _replace(holder: int, staging: str, key: str) -> None:
    """The staged copy renamed to `key`. A copy already there is first renamed aside, then
    removed: the name never holds a part of either."""
    try:
        os.rename(staging, key, src_dir_fd=holder, dst_dir_fd=holder)
        return
    except OSError as exc:
        if exc.errno not in (errno.EEXIST, errno.ENOTEMPTY, errno.EISDIR, errno.ENOTDIR):
            raise
    aside = f"{STAGING}old-{secrets.token_hex(8)}"
    os.rename(key, aside, src_dir_fd=holder, dst_dir_fd=holder)
    os.rename(staging, key, src_dir_fd=holder, dst_dir_fd=holder)
    # The new copy is in place: removing the old one is best effort, never a failed put. What
    # is left keeps its `.put-` name, which `gc --skills` removes (the review of #2089).
    with contextlib.suppress(OSError):
        _remove_tree(holder, aside)


def _remove_tree(parent: int, name: str) -> None:
    """The directory `name` in the open `parent` and all below it, each level reached without
    following a link (a link is removed, never entered), the owner's access restored on every
    level first, a 0000 one included, as a placement's scratch is removed (scratchop._remove_in,
    the review of #2089); a non-directory there is unlinked."""
    try:
        found = os.lstat(name, dir_fd=parent)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(found.st_mode):
        os.unlink(name, dir_fd=parent)
        return
    # Only directories of the user the op runs as (the agents') are widened and removed: one
    # another user holds is left, as scratchop leaves it.
    scratchop._remove_in(parent, name, os.getuid())


# --- the entry point on the agents' side ----------------------------------------------------------

LINK = 4  # the exit code for a link below the agents' home, as scratchop.LINK: nothing was done
# The document `put` reads from stdin: the skill's own bound in base64 (4/3), its manifest, and
# room for the JSON around them.
DOCUMENT_MAX = 8 * 1024 * 1024
USAGE = "usage: skillop check --home HOME KEY SOURCE COMMIT | put --home HOME (document on stdin)"


def supported() -> bool:
    """Whether this system opens a directory from another without following a link and
    renames and removes relative to one (not Windows), as scratchop.supported asks."""
    return (
        hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd
        and os.rmdir in os.supports_dir_fd and hasattr(os, "fwalk")
        and os.rename in os.supports_dir_fd and os.unlink in os.supports_dir_fd
    )  # fmt: skip


def main(argv: Sequence[str] | None = None) -> int:
    """`check --home HOME KEY SOURCE COMMIT` or `put --home HOME`, the runner's document on
    stdin: one JSON line on stdout, LINK for a link below the home, 1 for a failure, 2 for a
    usage error (what a host `maity` without these ops answers too)."""
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    document: object = None
    if len(args) == 6 and args[0] == "check" and args[1] == "--home":
        _op, _flag, home, key, source, commit = args
    elif len(args) == 3 and args[0] == "put" and args[1] == "--home":
        home = args[2]
        try:  # a read or decoding error is an answer too, never a traceback (the review of #2089)
            text = sys.stdin.read(DOCUMENT_MAX + 1)  # the skill's bounds, base64, with room
            document = json.loads(text) if len(text) <= DOCUMENT_MAX else None
        except (OSError, ValueError):
            document = None
        if not isinstance(document, dict):
            print("skillop: the skill's document is not a JSON object within its bound",
                  file=sys.stderr)  # fmt: skip
            return 1
    else:
        print(USAGE, file=sys.stderr)
        return 2
    if not supported():
        print("skillop: this system cannot open a directory without following links",
              file=sys.stderr)  # fmt: skip
        return 1
    try:
        if isinstance(document, dict):
            answer = put(home, document)
        else:
            answer = check(home, key, source, commit)
    except (OnTheWay, scratchop.OnTheWay) as exc:
        print(json.dumps({"result": "link", "why": str(exc)}))
        return LINK
    except (OSError, ValueError, Mismatch) as exc:  # an answer, never a traceback (#2089)
        print(f"skillop: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(answer))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
