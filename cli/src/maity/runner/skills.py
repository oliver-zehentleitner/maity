"""The Keep the Why skill the runner gives its placements (docs/api.md §15.5, docs/runners.md).

The hub names the skill per placement as `keep_the_why: {source, commit}`: the release tree the
resume packet names, and the git commit of it. The runner fetches exactly that commit with its
own git, outside any sandbox, and keeps the skill's files in `skills_dir/keep-the-why/<key>/`
(`key`: the commit and a hash of the source), laid out as a Claude Code plugin
(`plugin/.claude-plugin/plugin.json`, `plugin/skills/keep-the-why/`), so a session loads it
with `--plugin-dir` and nothing goes into the harness's own settings or skills (where the
agents cannot read this directory, deliver puts the same files below their home, which no
harness loads on its own, tsk-7casfxb7cn49). Git checks every object against
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
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from .. import proc, state
from . import skillop
from .asuser import AsUser

# The skill's names and bounds, one set for the runner's copy and the agents' (skillop).
NAME, MANIFEST, PLUGIN = skillop.NAME, skillop.MANIFEST, skillop.PLUGIN
MAX_FILES, MAX_BYTES, MANIFEST_MAX = skillop.MAX_FILES, skillop.MAX_BYTES, skillop.MANIFEST_MAX
KEY, COMMIT = skillop.KEY, skillop.COMMIT
key = skillop.copy_key  # the cached copy's directory name
FETCH_TIMEOUT = 120.0
_BLOB_MODES = ("100644", "100755")  # links (120000) and submodules (160000) are refused
# Only https: the source is the hub's, the transport the runner's choice.
_TRANSPORTS = "https"


class Unavailable(Exception):
    """The skill could not be fetched or checked; the message is for the runner's log."""


def plugin_root(skills_dir: Path, source: str, commit: str) -> Path:
    """What `--plugin-dir` names for this source at this commit."""
    return skills_dir / NAME / key(source, commit) / PLUGIN


def skill_in(plugin: Path) -> Path:
    """The skill itself (`SKILL.md` and its references) in the plugin root `plugin`, as
    `MAITY_KTW_SKILL_DIR` names it (adapters.skill_env)."""
    return plugin / "skills" / NAME


def skill_dir(skills_dir: Path, source: str, commit: str) -> Path:
    """`skill_in` the runner's copy of this source at this commit."""
    return skill_in(plugin_root(skills_dir, source, commit))


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
    try:  # a bad authority (`https://[::1/…`) raises ValueError: unavailable, not a crash
        parts = urlsplit(source)
        hostname = parts.hostname
    except ValueError as exc:
        raise Unavailable(f"the skill's source is not a URL: {exc}") from None
    if parts.scheme != "https" or not hostname or parts.query or parts.fragment:
        raise Unavailable("the skill's source is not a plain https URL")
    if "@" in parts.netloc:  # no login in it, empty or not (the review of #2056)
        raise Unavailable("the skill's source names a login; the runner fetches without one")
    repository, _, tree = source.partition("/tree/")
    _ref, _, path = tree.partition("/")
    repository = repository.removesuffix("/-")
    inner = PurePosixPath(path.strip("/"))
    if not tree or not path.strip("/") or any(p in ("", ".", "..") for p in inner.parts):
        raise Unavailable("the skill's source names no path in a tree")
    return repository, str(inner)


ANCHORS = "skills.json"  # in the runner's state directory: {key: the manifest's SHA-256}
_anchors_lock = threading.Lock()


def ensure(skills_dir: Path, state_dir: Path, source: str, commit: str) -> Path:
    """The plugin root for `source` at `commit`, fetched now when no checked copy is there.

    A copy is handed out only when its manifest's SHA-256 is the one the runner recorded in its
    own state directory (ANCHORS) when it fetched it: the skills directory is beside the state
    directory, and a manifest rewritten there together with the files it names would pass
    `verify` alone (the review of #2056). Without a record (a state directory made anew), the
    commit is fetched again and the copy kept only when the fresh manifest is the same. Unavailable
    when it cannot be fetched, a copy does not match its manifest, or the manifest is not the
    recorded one."""
    name = key(source, commit)
    final = skills_dir / NAME / name
    recorded = _anchors(state_dir).get(name)
    if os.path.lexists(final / MANIFEST):
        digest = verify(final, source, commit)  # the manifest's SHA-256, as it read it
        if digest == recorded:
            return final / PLUGIN
        if recorded is not None:
            raise Unavailable(f"the skill's copy at {final} is not the one the runner fetched")
    repository, path = split_source(source)
    parent = skills_dir / NAME
    parent.mkdir(parents=True, exist_ok=True, mode=0o755)
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=parent) as work:
        staged = Path(work) / "copy"
        _fetch(Path(work) / "git", repository, commit, path, staged)
        _write_plugin(staged, source, commit)
        _write_manifest(staged, source, commit)
        fresh = _sha256(staged / MANIFEST)
        os.chmod(staged, 0o755)  # noqa: S103 - read by the session, written by nobody but us
        try:
            os.rename(staged, final)
        except OSError:
            if not os.path.lexists(final / MANIFEST):  # not another start's finished copy
                raise Unavailable(f"cannot put the skill at {final}") from None
    if verify(final, source, commit) != fresh:  # a copy that was there before: ours, or not
        raise Unavailable(f"the skill's copy at {final} is not what commit {commit} holds")
    _record(state_dir, name, fresh)
    return final / PLUGIN


def _anchors(state_dir: Path) -> dict[str, str]:
    try:
        found = state.load_state(state_dir, name=ANCHORS)
    except (OSError, ValueError, state.StateError):
        return {}
    return {k: v for k, v in found.items() if isinstance(k, str) and isinstance(v, str)}


def _record(state_dir: Path, name: str, digest: str) -> None:
    """Unavailable when the record cannot be written: the copy is then not handed out, rather
    than a StateError escaping the start (the review of #2056)."""
    with _anchors_lock:
        found = _anchors(state_dir)
        found[name] = digest
        try:
            state.save_state(state_dir, found, name=ANCHORS)
        except (OSError, state.StateError) as exc:
            raise Unavailable(f"cannot record the skill's copy in {state_dir}: {exc}") from None


def verify(copy: Path, source: str, commit: str) -> str:
    """The copy of `source` at `commit`, as its manifest says, and every file the manifest
    names, with its hash, and nothing else: the copy, its plugin
    root and every directory below are real directories, the manifest and every file regular
    files, none a link, within the same bounds as at the fetch (the review of #2056). A file is
    opened without following a link and without waiting on a FIFO, and its type is checked on
    the open descriptor before anything is read. One check for the runner's copy and the one on
    the agents' side (skillop.verify); the manifest's SHA-256."""
    try:
        return skillop.verify_path(copy, source, commit, MAX_FILES, MAX_BYTES, MANIFEST_MAX)
    except skillop.Mismatch as exc:
        raise Unavailable(str(exc)) from None


def deliver(
    as_user: AsUser, home: Path, skills_dir: Path, state_dir: Path, source: str, commit: str
) -> Path:
    """The plugin root of `source` at `commit` on the agents' side, below their `home`
    (skillop.AGENT_SKILLS), for a target whose agents cannot read the runner's own copy: the
    agent_user layout and an ssh host (tsk-7casfxb7cn49). The runner fetches and checks its own
    copy first (`ensure`); the agents' copy is handed out only when its manifest's SHA-256 is
    the one the runner recorded for it. A missing or different one is put again from the
    runner's copy, once. Unavailable for anything that keeps it from being had, so a start
    goes on without the skill and is never counted as a crash (the review of #2089): a failed
    op (OSError, scratchop.Unsupported for an ssh host's `maity` without the skill ops,
    skillop.OnTheWay for a link below the agents' home, a timeout), an answer that cannot be
    decoded (ValueError), and a cached file that turned unreadable since the check
    (skillop.Mismatch while packaging)."""
    root = ensure(skills_dir, state_dir, source, commit)
    name = key(source, commit)
    recorded = _anchors(state_dir).get(name)
    if recorded is None:  # ensure records every copy it hands out
        raise Unavailable(f"the runner holds no record of the skill's copy {name}")
    try:
        return _deliver(as_user, home, root, name, source, commit, recorded)
    except (OSError, ValueError, subprocess.SubprocessError, skillop.Mismatch) as exc:
        raise Unavailable(f"the skill's copy could not be put below {home}: {exc}") from None


def _deliver(
    as_user: AsUser, home: Path, root: Path, name: str, source: str, commit: str, recorded: str
) -> Path:
    copy = skillop.agent_copy(home, name)
    found = as_user.skill_check(home, name, source, commit)
    if found.get("result") == "ok" and found.get("digest") == recorded:
        return copy / PLUGIN
    put = as_user.skill_put(home, skillop.payload(root.parent, name))
    if put.get("digest") != recorded:
        raise Unavailable(f"the skill's copy put at {copy} is not the one the runner fetched")
    again = as_user.skill_check(home, name, source, commit)
    if again.get("result") != "ok" or again.get("digest") != recorded:
        why = again.get("why") or again.get("result")
        raise Unavailable(f"the skill's copy at {copy} does not hold after it was put: {why}")
    return copy / PLUGIN


def copies(skills_dir: Path, state_dir: Path) -> list[tuple[str, str, str, str]]:
    """The copies in the runner's skills directory, for `maity runner check`: (key, source,
    commit, state), the state `ok` (whole, and the manifest the runner recorded), `unrecorded`
    (no record: the next start fetches the commit again and compares) or `changed` with why
    (not handed out until fetched again). Nothing is fetched; the agents'-side copies are
    checked at every start against the same records."""
    found: list[tuple[str, str, str, str]] = []
    parent = skills_dir / NAME
    try:
        names = sorted(e.name for e in parent.iterdir() if KEY.fullmatch(e.name))
    except OSError:
        return found
    anchors = _anchors(state_dir)
    for name in names:
        copy = parent / name
        try:
            manifest = json.loads(_read(copy / MANIFEST, MANIFEST_MAX).decode("utf-8"))
            source, commit = str(manifest.get("source", "")), str(manifest.get("commit", ""))
        except (Unavailable, ValueError, AttributeError):
            found.append((name, "", "", "changed: no manifest the runner wrote"))
            continue
        try:
            digest = verify(copy, source, commit)
        except Unavailable as exc:
            found.append((name, source, commit, f"changed: {exc}"))
            continue
        recorded = anchors.get(name)
        if key(source, commit) != name:
            state_text = "changed: its manifest names another source or commit than its name"
        elif recorded is None:
            state_text = "unrecorded"
        elif recorded != digest:
            state_text = "changed: its manifest is not the one the runner recorded"
        else:
            state_text = "ok"
        found.append((name, source, commit, state_text))
    return found


def _read(path: Path, limit: int) -> bytes:
    """skillop.read_path: a regular file's bytes, at most `limit` of them, refused rather than
    waited on or followed; Unavailable otherwise."""
    try:
        return skillop.read_path(path, limit)
    except skillop.Mismatch as exc:
        raise Unavailable(str(exc)) from None


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
    target = skill_in(into / PLUGIN)
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


def forget(state_dir: Path, names: set[str]) -> None:
    """The records (ANCHORS) of removed copies dropped: a copy fetched again later is recorded
    anew, and the file does not grow with every pin the hub ever named."""
    if not names:
        return
    with _anchors_lock:
        found = _anchors(state_dir)
        kept = {k: v for k, v in found.items() if k not in names}
        if kept != found:
            state.save_state(state_dir, kept, name=ANCHORS)


def remove_unused(skills_dir: Path, keep: set[str], failed: list[str] | None = None) -> list[str]:
    """The cached copies (`key`) and `.fetch-` leftovers not in `keep`, removed; returns them.
    For `gc`. The directory holding them is opened without following a link (OSError for a
    link there), and each entry is removed as skillop removes the agents' copies: a link or
    file unlinked, never entered, a directory with the owner's access restored on every level
    (the review of #2093). An entry that cannot be removed goes into `failed`, and the others
    are still removed, so the caller can forget exactly the ones that went."""
    removed: list[str] = []
    try:
        parent = os.open(skills_dir / NAME, skillop.FOLDER | skillop.NOFOLLOW)
    except FileNotFoundError:
        return removed
    try:
        for name in sorted(os.listdir(parent)):
            if name in keep or not (KEY.fullmatch(name) or name.startswith(".fetch-")):
                continue
            try:
                skillop._remove_tree(parent, name)
            except OSError as exc:
                if failed is not None:
                    failed.append(f"{name} ({exc})")
                continue
            removed.append(name)
    finally:
        os.close(parent)
    return removed
