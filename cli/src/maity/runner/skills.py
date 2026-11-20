"""The Keep the Why skill the runner gives its placements (docs/api.md §15.5, docs/runners.md).

The hub names the skill per placement as `keep_the_why: {source, commit}`: the release tree the
resume packet names, and the git commit of it. The runner fetches exactly that commit with its
own git, outside any sandbox, and keeps the skill's files in `skills_dir/keep-the-why/<key>/`
(`key`: the commit and a hash of the source), laid out as a Claude Code plugin
(`plugin/.claude-plugin/plugin.json`, `plugin/skills/keep-the-why/`), so a session loads it
with `--plugin-dir` and nothing goes into the agents' home. Git checks every object against
the commit id, so a moved tag changes nothing here. Only regular files are taken, bounded in
number and size, written 0644 in 0755 directories, and a `manifest.json` with each file's
SHA-256 written last marks a copy as complete. A copy is checked against its manifest every
time it is handed out. Nothing in the copy is ever run.

Why the runner and not the session: a placed session cannot write the harness's skills directory
and has no network for an installer (cli/context/runner.md, tsk-172s8y208whg).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from .. import proc

NAME = "keep-the-why"
COMMIT = re.compile(r"[0-9a-f]{40}")
MANIFEST = "manifest.json"
PLUGIN = "plugin"
MAX_FILES = 200
MAX_BYTES = 4 * 1024 * 1024  # the whole skill; 0.20.3 is well under 1 MiB
FETCH_TIMEOUT = 120.0
_BLOB_MODES = ("100644", "100755")  # links (120000) and submodules (160000) are refused
# Only https: the source is the hub's, the transport the runner's choice.
_TRANSPORTS = "https"


class Unavailable(Exception):
    """The skill could not be fetched or checked; the message is for the runner's log."""


KEY = re.compile(r"[0-9a-f]{40}-[0-9a-f]{16}")


def key(source: str, commit: str) -> str:
    """The cached copy's directory name: the commit and the source together, so one commit at
    another path of a tree is another copy (the review of #2056)."""
    return f"{commit}-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:16]}"


def plugin_root(skills_dir: Path, source: str, commit: str) -> Path:
    """What `--plugin-dir` names for this source at this commit."""
    return skills_dir / NAME / key(source, commit) / PLUGIN


def skill_dir(skills_dir: Path, source: str, commit: str) -> Path:
    """The skill itself (`SKILL.md` and its references), as `MAITY_KTW_SKILL_DIR` names it."""
    return plugin_root(skills_dir, source, commit) / "skills" / NAME


def named(placement: Mapping[str, Any]) -> tuple[str, str] | None:
    """The placement's `(source, commit)`, or None when it names no skill (a project without
    Keep the Why, or a hub from before the field). A malformed value is Unavailable."""
    given = placement.get("keep_the_why")
    if given is None:
        return None
    if not isinstance(given, dict):
        raise Unavailable("keep_the_why is not an object")
    source, commit = given.get("source"), given.get("commit")
    if not isinstance(source, str) or not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise Unavailable("keep_the_why does not name an https source and a 40-hex commit")
    return source, commit


def split_source(source: str) -> tuple[str, str]:
    """`(repository URL, path in the tree)` of a `<repository>/tree/<ref>/<path>` source, the
    form the hub derives its Git fallback from (ktw_skill.skill); the ref is not used, the
    commit is. GitLab's `/-/tree/` works too."""
    parts = urlsplit(source)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
        raise Unavailable("the skill's source is not a plain https URL")
    repository, _, tree = source.partition("/tree/")
    _ref, _, path = tree.partition("/")
    repository = repository.removesuffix("/-")
    inner = PurePosixPath(path.strip("/"))
    if not tree or not path.strip("/") or any(p in ("", ".", "..") for p in inner.parts):
        raise Unavailable("the skill's source names no path in a tree")
    return repository, str(inner)


def ensure(skills_dir: Path, source: str, commit: str) -> Path:
    """The plugin root for `commit`, fetched now when no checked copy is there. Unavailable when
    it cannot be fetched or a copy does not match its manifest."""
    final = skills_dir / NAME / key(source, commit)
    if os.path.lexists(final / MANIFEST):
        verify(final, source, commit)
        return final / PLUGIN
    repository, path = split_source(source)
    parent = skills_dir / NAME
    parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=parent) as work:
        staged = Path(work) / "copy"
        _fetch(Path(work) / "git", repository, commit, path, staged)
        _write_plugin(staged, source, commit)
        _write_manifest(staged, source, commit)
        os.chmod(staged, 0o755)  # noqa: S103 - read by the session, written by nobody but us
        try:
            os.rename(staged, final)
        except OSError:
            if not os.path.lexists(final / MANIFEST):  # not another start's finished copy
                raise Unavailable(f"cannot put the skill at {final}") from None
    verify(final, source, commit)
    return final / PLUGIN


MANIFEST_MAX = 64 * 1024


def verify(copy: Path, source: str, commit: str) -> None:
    """The copy of `source` at `commit`, as its manifest says, and every file the manifest
    names, with its hash, and nothing else: the copy, its plugin
    root and every directory below are real directories, the manifest and every file regular
    files, none a link, within the same bounds as at the fetch (the review of #2056). A file is
    opened without following a link and without waiting on a FIFO, and its type is checked on
    the open descriptor before anything is read."""
    for directory in (copy, copy / PLUGIN):
        _kind(directory, stat.S_ISDIR, "directory")
    try:
        manifest = json.loads(_read(copy / MANIFEST, MANIFEST_MAX).decode("utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        raise Unavailable(f"{copy / MANIFEST} is not a manifest the runner wrote") from None
    if manifest.get("source") != source or manifest.get("commit") != commit:
        raise Unavailable(f"the skill's copy at {copy} is not of {source} at {commit}")
    found: dict[str, str] = {}
    total = 0
    for dirpath, dirnames, filenames in os.walk(copy / PLUGIN, followlinks=False):
        for name in dirnames:
            _kind(Path(dirpath) / name, stat.S_ISDIR, "directory")
        for name in filenames:
            full = Path(dirpath) / name
            if len(found) >= MAX_FILES + 1:  # the skill's files and plugin.json
                raise Unavailable(f"the skill's copy at {copy} has too many files")
            data = _read(full, MAX_BYTES + MANIFEST_MAX - total)  # the plugin.json on top
            total += len(data)
            found[full.relative_to(copy).as_posix()] = hashlib.sha256(data).hexdigest()
    if found != files:
        raise Unavailable(f"the skill's copy at {copy} does not match its manifest")


def _kind(path: Path, test: Any, what: str) -> None:
    """`path` itself (never a link's target) is a `what`."""
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        raise Unavailable(f"{path} is missing from the skill's copy") from None
    if stat.S_ISLNK(mode) or not test(mode):
        raise Unavailable(f"{path} in the skill's copy is not a plain {what}")


def _read(path: Path, limit: int) -> bytes:
    """A regular file's bytes, at most `limit` of them; refused rather than waited on or
    followed. The type is checked on the descriptor, so nothing swapped in between counts."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        raise Unavailable(f"{path} in the skill's copy cannot be opened as a plain file") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise Unavailable(f"{path} in the skill's copy is not a plain file")
        if info.st_size > limit:
            raise Unavailable(f"the skill's copy is larger than {MAX_BYTES} bytes")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(fd, 65536):
            size += len(chunk)
            if size > limit:
                raise Unavailable(f"the skill's copy is larger than {MAX_BYTES} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError:
        raise Unavailable(f"{path} in the skill's copy cannot be read") from None
    finally:
        os.close(fd)


def _sha256(path: Path) -> str:
    return hashlib.sha256(_read(path, MAX_BYTES + MANIFEST_MAX)).hexdigest()


# What the runner's own environment may give git for the fetch: the basics, and the standard
# proxy and trust-root variables an operator sets for the runner's network (the review of #2056).
# Of git's own variables only the two trust-root ones, and no git configuration: the rest could
# change the transport or run something.
_KEPT_ENV = (
    "PATH", "HOME", "LANG",
    "https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY",
    "no_proxy", "NO_PROXY", "SSL_CERT_FILE", "SSL_CERT_DIR", "GIT_SSL_CAINFO", "GIT_SSL_CAPATH",
)  # fmt: skip


def _git(git_dir: Path, *args: str, binary: bool = False) -> Any:
    """git on the runner's own bare repository for this fetch: no prompt, no system or user
    configuration, no hooks, https only; the runner's proxy and trust roots as its environment
    names them (_KEPT_ENV)."""
    program = proc.program("git")
    if program is None:
        raise Unavailable("git is not installed for the runner")
    env = {
        **{k: v for k, v in os.environ.items() if k in _KEPT_ENV},
        **proc.NO_PROMPT,
        "GIT_ALLOW_PROTOCOL": proc.allowed(_TRANSPORTS),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_DIR": str(git_dir),
    }
    command = [program, "-c", f"core.hooksPath={os.devnull}", *args]
    try:
        done = subprocess.run(
            command, env=env, stdin=subprocess.DEVNULL, capture_output=True,
            timeout=FETCH_TIMEOUT, check=False,
        )  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Unavailable(f"git {args[0]} failed: {exc}") from None
    if done.returncode != 0:
        said = done.stderr.decode("utf-8", "replace").strip().splitlines()
        raise Unavailable(f"git {args[0]} exited {done.returncode}: {(said or [''])[-1][:200]}")
    return done.stdout if binary else done.stdout.decode("utf-8", "replace")


def _fetch(git_dir: Path, repository: str, commit: str, path: str, into: Path) -> None:
    """The files under `path` at `commit`, as git has them, into `into/plugin/skills/<NAME>`."""
    _git(git_dir, "init", "--quiet", "--bare", str(git_dir))
    _git(git_dir, "fetch", "--quiet", "--depth", "1", "--no-tags", "--", repository, commit)
    if _git(git_dir, "rev-parse", "--verify", f"{commit}^{{commit}}").strip() != commit:
        raise Unavailable(f"the fetch did not bring commit {commit}")
    listed = _git(git_dir, "ls-tree", "-r", "-l", "-z", commit, "--", f"{path}/")
    entries = [e for e in listed.split("\0") if e]
    if not entries:
        raise Unavailable(f"commit {commit} has no {path}/")
    if len(entries) > MAX_FILES:
        raise Unavailable(f"the skill has more than {MAX_FILES} files")
    target = into / PLUGIN / "skills" / NAME
    total = 0
    for entry in entries:
        meta, _, name = entry.partition("\t")
        mode, kind, blob, size = meta.split()
        relative = PurePosixPath(name).relative_to(path)
        if mode not in _BLOB_MODES or kind != "blob":
            raise Unavailable(f"the skill holds {name} as {mode} {kind}, not a plain file")
        if any(part in ("", ".", "..") or part.startswith(".git") for part in relative.parts):
            raise Unavailable(f"the skill holds a path the runner does not write: {name}")
        total += int(size)
        if total > MAX_BYTES:
            raise Unavailable(f"the skill is larger than {MAX_BYTES} bytes")
        data = _git(git_dir, "cat-file", "blob", blob, binary=True)
        out = target / relative.as_posix()
        out.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
        _write(out, data)
    if not (target / "SKILL.md").is_file():
        raise Unavailable(f"commit {commit} has no {path}/SKILL.md")


def _write(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    with os.fdopen(fd, "wb") as out:
        out.write(data)
    os.chmod(path, 0o644)  # whatever the umask


def _write_plugin(into: Path, source: str, commit: str) -> None:
    """The plugin's manifest, so Claude Code takes the directory with `--plugin-dir`."""
    meta = into / PLUGIN / ".claude-plugin"
    meta.mkdir(parents=True, exist_ok=True, mode=0o755)
    plugin = {
        "name": NAME,
        "version": commit[:12],
        "description": f"Keep the Why, delivered by maity runner from {source} at {commit}",
    }
    _write(meta / "plugin.json", (json.dumps(plugin, indent=2) + "\n").encode("utf-8"))
    for directory in [into / PLUGIN, *(p for p in (into / PLUGIN).rglob("*") if p.is_dir())]:
        os.chmod(directory, 0o755)  # noqa: S103 - read by the session, written by nobody but us


def _write_manifest(into: Path, source: str, commit: str) -> None:
    files = {
        p.relative_to(into).as_posix(): _sha256(p)
        for p in sorted((into / PLUGIN).rglob("*"))
        if p.is_file()
    }
    manifest = {"source": source, "commit": commit, "files": files}
    _write(into / MANIFEST, (json.dumps(manifest, indent=2) + "\n").encode("utf-8"))


def remove_unused(skills_dir: Path, keep: set[str]) -> list[str]:
    """The cached copies (`key`) no placement names any more, removed; returns them. For `gc`."""
    removed: list[str] = []
    parent = skills_dir / NAME
    if not parent.is_dir():
        return removed
    for entry in parent.iterdir():
        if entry.name in keep or entry.is_symlink() or not entry.is_dir():
            continue
        if KEY.fullmatch(entry.name) or entry.name.startswith(".fetch-"):
            shutil.rmtree(entry)
            removed.append(entry.name)
    return removed
