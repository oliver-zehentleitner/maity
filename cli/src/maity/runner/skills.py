"""The Keep the Why skill the runner gives its placements (docs/api.md §15.5, docs/runners.md).

The hub names the skill per placement as `keep_the_why: {source, commit}`: the release tree the
resume packet names, and the git commit of it. The runner fetches exactly that commit with its
own git, outside any sandbox, and keeps the skill's files in `skills_dir/keep-the-why/<commit>/`,
laid out as a Claude Code plugin (`plugin/.claude-plugin/plugin.json`, `plugin/skills/
keep-the-why/`), so a session loads it with `--plugin-dir` and nothing goes into the agents'
home. Git checks every object against the commit id, so a moved tag changes nothing here; only
regular files are taken, bounded in number and size, written 0644 in 0755 directories, and a
`manifest.json` with each file's SHA-256 written last marks a copy as complete. A copy is
checked against its manifest every time it is handed out. Nothing in the copy is ever run.

Why the runner and not the session: a placed session cannot write the harness's skills directory
and has no network for an installer (cli/context/runner.md, tsk-172s8y208whg).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
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


def plugin_root(skills_dir: Path, commit: str) -> Path:
    """What `--plugin-dir` names for this commit."""
    return skills_dir / NAME / commit / PLUGIN


def skill_dir(skills_dir: Path, commit: str) -> Path:
    """The skill itself (`SKILL.md` and its references), as `MAITY_KTW_SKILL_DIR` names it."""
    return plugin_root(skills_dir, commit) / "skills" / NAME


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
    final = skills_dir / NAME / commit
    if (final / MANIFEST).is_file():
        verify(final)
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
            if not (final / MANIFEST).is_file():  # not another start's finished copy
                raise Unavailable(f"cannot put the skill at {final}") from None
    verify(final)
    return final / PLUGIN


def verify(copy: Path) -> None:
    """Every file the manifest names, with its hash, and nothing else; no link anywhere."""
    try:
        manifest = json.loads((copy / MANIFEST).read_text(encoding="utf-8"))
        files = manifest["files"]
        if not isinstance(files, dict):
            raise TypeError
    except (OSError, ValueError, KeyError, TypeError):
        raise Unavailable(f"{copy / MANIFEST} is not a manifest the runner wrote") from None
    found: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(copy / PLUGIN, followlinks=False):
        for entry in [*dirnames, *filenames]:
            if os.path.islink(os.path.join(dirpath, entry)):
                raise Unavailable(f"a link in the skill's copy: {os.path.join(dirpath, entry)}")
        for filename in filenames:
            full = Path(dirpath) / filename
            found[full.relative_to(copy).as_posix()] = _sha256(full)
    if found != files:
        raise Unavailable(f"the skill's copy at {copy} does not match its manifest")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(git_dir: Path, *args: str, binary: bool = False) -> Any:
    """git on the runner's own bare repository for this fetch: no prompt, no system or user
    configuration, no hooks, https only."""
    program = proc.program("git")
    if program is None:
        raise Unavailable("git is not installed for the runner")
    env = {
        **{k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG")},
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
    """The cached commits no placement names any more, removed; returns them. For `gc`."""
    removed: list[str] = []
    parent = skills_dir / NAME
    if not parent.is_dir():
        return removed
    for entry in parent.iterdir():
        if entry.name in keep or entry.is_symlink() or not entry.is_dir():
            continue
        if COMMIT.fullmatch(entry.name) or entry.name.startswith(".fetch-"):
            shutil.rmtree(entry)
            removed.append(entry.name)
    return removed
