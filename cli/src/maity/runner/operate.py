"""The operator's commands on the runner host (runner design §10.1): `logs`, `approve`,
`stop-all`, `gc --revoked` and `workspace claim`. None of them asks the hub what to do;
`gc` asks it only whether a clone's credential is revoked, through the agent's own CLI.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .. import hub, onboarding, state
from . import config, serve, supervisor, workspace

STOP_ALL_GRACE = 30
FOLLOW_EVERY = 1.0
# git run by the operator in an agent's clone: nothing the agent wrote may run (§7.5). The
# overrides below are a second line; the first is `not_inspectable`.
SAFE_GIT = [
    "git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
    "-c", "core.pager=cat", "-c", "diff.external=", "-c", "protocol.allow=never",
    "-c", "log.showSignature=false", "-c", "gpg.program=false", "-c", "core.attributesFile=",
]  # fmt: skip
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
REVOKED = re.compile(r": credential_revoked:")


class Refused(Exception):
    """The command cannot run as asked; exit 2."""


def _status(cfg: config.Config) -> dict[str, Any]:
    if not cfg.state_dir.is_dir():
        return {}
    return state.load_state(cfg.state_dir, name=serve.STATUS_FILE)


def _placement_id(cfg: config.Config, which: str) -> str:
    """A placement id: `which` itself when it is one the service last saw, else the one
    placement of the agent with that handle; never a guess between two."""
    known = [
        p for p in _status(cfg).get("placements") or []
        if isinstance(p, dict) and isinstance(p.get("id"), str)
        and supervisor.PLACEMENT_ID.match(p["id"])
    ]  # fmt: skip
    if any(p["id"] == which for p in known):
        return which
    by_agent = [p["id"] for p in known if p.get("agent") == which]
    if len(by_agent) > 1:
        raise Refused(f"{onboarding.inline(which)} names more than one placement; use the id")
    if by_agent:
        return str(by_agent[0])
    if supervisor.PLACEMENT_ID.match(which):
        return which
    raise Refused(f"no placement {onboarding.inline(which)} on this runner")


# --- logs ------------------------------------------------------------------------------------


def cmd_logs(cfg: config.Config, args: argparse.Namespace) -> int:
    pid = _placement_id(cfg, args.which)
    path = cfg.state_dir / supervisor.LOGS / f"{pid}.log"
    if not path.is_file():
        raise Refused(f"no log for {pid} in {path.parent}")
    # A terminal acts on escape sequences the agent printed (an OSC 52 writes the operator's
    # clipboard): shown, not executed, unless --raw.
    raw = args.raw or not sys.stdout.isatty()

    def emit(chunk: bytes) -> None:
        if raw:
            sys.stdout.buffer.write(chunk)
        else:
            sys.stdout.write(onboarding.clean(chunk.decode("utf-8", errors="replace")))
        sys.stdout.flush()

    with path.open("rb") as fh:
        emit(fh.read())
        while args.follow:
            chunk = fh.read()
            if chunk:
                emit(chunk)
            else:
                time.sleep(FOLLOW_EVERY)
    return 0


# --- approve ---------------------------------------------------------------------------------


def cmd_approve(cfg: config.Config, args: argparse.Namespace) -> int:
    if not cfg.limits.require_local_approval:
        raise Refused("limits.require_local_approval is off: placements start without approval")
    pid = _placement_id(cfg, args.which)
    found = supervisor.approved(cfg.state_dir)
    found[pid] = int(time.time())
    state.save_state(cfg.state_dir, found, name=supervisor.APPROVED_FILE)
    print(f"approved {pid}; the service starts it on its next tick")
    return 0


# --- stop-all --------------------------------------------------------------------------------


def cmd_stop_all(cfg: config.Config, args: argparse.Namespace) -> int:
    """Ends every agent session of this runner without the hub. The service must be stopped
    first: it would start every placement whose desired state is still `running` again."""
    if cfg.local is None:
        raise Refused("stop-all is for the local backend")
    try:
        lock = serve.hold_lock(cfg.state_dir)  # held to the end: no restart in between
    except serve.Fatal:
        raise Refused(
            "the runner service is running and would start the agents again; stop it first "
            "(systemctl stop maity-runner, or end `maity runner serve`)"
        ) from None
    try:
        return _stop_all(cfg, args)
    finally:
        lock.close()


def _stop_all(cfg: config.Config, args: argparse.Namespace) -> int:
    backend = supervisor.local_backend(cfg)
    sessions = {n: s for n, s in backend.sessions().items() if s.placement and not s.dead}
    if not sessions:
        print("no agent sessions are running")
        return 0
    for session in sessions.values():
        backend.terminate(session)
    deadline = time.monotonic() + args.grace
    while time.monotonic() < deadline:
        alive = {n for n, s in backend.sessions().items() if n in sessions and not s.dead}
        if not alive:
            break
        time.sleep(1.0)
    for name in sessions:
        backend.kill(name)
        print(f"ended {name}")
    return 0


# --- gc --revoked ----------------------------------------------------------------------------


def credential_revoked(place: workspace.Workspace) -> bool:
    """Whether the hub refuses the clone's credential as revoked, asked by the agent's own
    CLI (the runner never holds the credential) and isolated from the clone's modules. Any
    other answer, or none, is "not known to be revoked"."""
    if not place.credential.is_file():
        return False
    env = {k: v for k, v in os.environ.items() if k != state.STATE_DIR_ENV}
    env[state.STATE_DIR_ENV] = str(place.credential.parent)
    try:
        done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
            [sys.executable, "-I", "-m", "maity", "api", "GET", "/me"],
            cwd=Path.home(), env=env, capture_output=True, text=True, timeout=60, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired:
        return False
    return done.returncode != 0 and REVOKED.search(done.stderr) is not None


def not_inspectable(path: Path) -> str | None:
    """Why git must not run in this clone, or None. git runs programs named in its
    configuration (filter drivers, gpg.program, fsmonitor, pagers, aliases) and reads
    `.git/info/attributes`, submodules' own configuration and wherever `.git/commondir`
    points; the agent wrote all of them. Only a `.git` made of a plain clone's entries, with a
    configuration made of a plain clone's keys, is read."""
    dot_git = path / ".git"
    if dot_git.is_symlink() or not dot_git.is_dir():
        return "its .git is not a plain directory"
    try:
        reason = _not_a_plain_git_dir(dot_git)
        if reason is None and (dot_git / "config").lstat().st_size > CONFIG_MAX:
            reason = f"its .git/config is larger than {CONFIG_MAX // 1024} KiB"
        if reason is not None:
            return reason
        text = (dot_git / "config").read_text(encoding="utf-8")
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
            return f"its .git/config sets {onboarding.inline(section)}.{onboarding.inline(key)}"
    return None


def _not_a_plain_git_dir(dot_git: Path) -> str | None:
    """Why `dot_git` is not laid out like a plain clone's, or None: an entry git does not
    create, an entry of the wrong type, another object store, or a symlink anywhere (git
    follows them, so a link would put any file in the place of one that was checked)."""
    for entry in dot_git.iterdir():
        mode = entry.lstat().st_mode
        expected = stat.S_ISREG if entry.name in GIT_FILES else stat.S_ISDIR
        if entry.name not in GIT_FILES | GIT_DIRS or not expected(mode):
            return f".git/{onboarding.inline(entry.name)} is not a plain clone's"
    for entry in (dot_git / "info").iterdir() if (dot_git / "info").is_dir() else ():
        if entry.name not in INFO_FILES:
            return f".git/info/{onboarding.inline(entry.name)} is not a plain clone's"
    for name in ALTERNATES:
        if os.path.lexists(dot_git / name):
            return f".git/{name} exists"
    for root, dirs, files in os.walk(dot_git):  # os.walk does not descend into links
        for name in dirs + files:
            if os.path.islink(os.path.join(root, name)):
                where = os.path.relpath(os.path.join(root, name), dot_git)
                return f".git/{onboarding.inline(where)} is a symlink"
    return None


def unsaved_work(path: Path) -> list[str] | None:
    """Uncommitted files and commits on no remote, or None when git could not tell: then
    nothing may be removed. Neither the operator's own git configuration nor the clone's
    hooks, filters, signatures or submodules take part."""
    # The operator's GIT_* would point git elsewhere or hide files; the repository is pinned,
    # so a broken one fails instead of git walking up to a parent repository.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null", GIT_DIR=str(path / ".git"),
        GIT_COMMON_DIR=str(path / ".git"), GIT_WORK_TREE=str(path),
        GIT_CEILING_DIRECTORIES=str(path.parent),
    )  # fmt: skip
    lines: list[str] = []
    for command in (
        [*SAFE_GIT, "-C", str(path), "status", "--porcelain", "--ignore-submodules=all"],
        [*SAFE_GIT, "-C", str(path), "log", "--oneline", "--no-show-signature", "--branches",
         "--not", "--remotes"],
    ):  # fmt: skip
        try:
            done = subprocess.run(  # noqa: S603 - fixed argv, a path the runner recorded
                command, env=env, capture_output=True, text=True, timeout=60, check=False
            )
        except subprocess.TimeoutExpired:
            return None
        if done.returncode != 0:
            return None
        lines += [onboarding.inline(line) for line in done.stdout.splitlines() if line.strip()]
    return lines


def _active(cfg: config.Config) -> tuple[set[tuple[str, str]], set[str]]:
    """(project, clone) pairs and agents of every active placement, asked of the hub: a
    clone a new placement continues names an old placement in its record until it starts."""
    runner_state = state.load_state(cfg.state_dir, name=serve.RUNNER_FILE)
    try:
        service = serve.open_service(cfg, runner_state)
        answer = service.client.call("GET", "/runner/placements")
    except (serve.Fatal, hub.HubError) as exc:
        raise Refused(f"cannot ask the hub which placements are active ({exc})") from None
    pairs: set[tuple[str, str]] = set()
    agents: set[str] = set()
    for p in (answer.get("items") if isinstance(answer, dict) else None) or []:
        if not supervisor.valid(p):
            continue
        pairs.add((p["project"], p["workspace"]["clone"]))
        agent = p.get("agent") or {}
        agents.update(v for v in (agent.get("id"), agent.get("handle")) if isinstance(v, str))
    return pairs, agents


def cmd_gc(cfg: config.Config, args: argparse.Namespace) -> int:
    if not args.revoked:
        raise Refused("gc removes only workspaces whose credential is revoked: pass --revoked")
    if cfg.local is None:
        raise Refused("gc is for the local backend")
    # Removing holds the service's lock: nothing starts in a clone while it goes.
    try:
        lock = serve.hold_lock(cfg.state_dir) if args.yes else None
    except serve.Fatal:
        raise Refused(
            "the runner service is running; stop it before removing workspaces, or run gc "
            "without --yes to list them"
        ) from None
    try:
        pairs, agents = _active(cfg)
        found = workspace.records(cfg.state_dir)
        gone: list[str] = []
        try:
            for path_text, record in sorted(found.items()):
                if _collect(cfg, path_text, record, pairs, agents, args.yes):
                    gone.append(path_text)
        finally:
            if gone:
                for path_text in gone:
                    found.pop(path_text, None)
                state.save_state(cfg.state_dir, found, name=workspace.RECORDS)
        if not args.yes:
            print("nothing removed; pass --yes to remove the workspaces listed as removable")
    except serve.Fatal as exc:
        raise Refused(str(exc)) from None
    finally:
        if lock is not None:
            lock.close()
    return 0


def _collect(
    cfg: config.Config,
    path_text: str,
    record: Any,
    pairs: set[tuple[str, str]],
    agents: set[str],
    remove: bool,
) -> bool:
    """One workspace: listed when its credential is revoked; removed (True) only when its
    path is the one its record implies, no placement uses it, and git could say what is in
    it."""
    assert cfg.local is not None  # noqa: S101 - cmd_gc checks it
    if not isinstance(record, dict):
        return False
    path = Path(path_text)
    try:
        expected = workspace.locate(cfg.local.workspaces, str(record.get("project")), path.name)
    except workspace.Refused:
        return False
    if str(expected.path) != path_text or path.is_symlink() or not path.is_dir():
        return False  # a record pointing anywhere else is never followed
    if (expected.project, expected.clone) in pairs or record.get("agent") in agents:
        return False  # a placement uses it, or will
    if not credential_revoked(expected):
        return False
    print(f"{path}  agent {onboarding.inline(record.get('agent'))}  credential revoked")
    reason = not_inspectable(path)
    work = None if reason else unsaved_work(path)
    if reason or work is None:
        print(f"  not inspected ({reason or 'git failed'}); not removed")
        return False
    for line in work:
        print(f"  {line}")
    if not remove:
        return False
    try:
        shutil.rmtree(path)
    except OSError as exc:
        print(f"  not removed: {exc}")
        return False
    print("  removed")
    return True


# --- workspace claim -------------------------------------------------------------------------


def cmd_workspace_claim(cfg: config.Config, args: argparse.Namespace) -> int:
    """Record an existing clone for an agent: after a lost state directory, or a clone made
    by hand. The record is the runner's; nothing in the clone is touched."""
    if cfg.local is None:
        raise Refused("workspaces are the local backend's")
    project, _, clone = args.where.partition("/")
    try:
        place = workspace.locate(cfg.local.workspaces, project, clone)
    except workspace.Refused:
        raise Refused(f"not <project>/<clone>: {onboarding.inline(args.where)}") from None
    if not (place.path / ".git").is_dir():
        raise Refused(f"{place.path} is not a clone")
    if str(place.path) in workspace.records(cfg.state_dir) and not args.force:
        raise Refused(f"{place.path} is recorded already; --force to record it again")
    workspace.record(cfg.state_dir, place, args.agent, args.placement or "")
    origin = workspace.origin(place.path)
    print(f"recorded {place.path} for {onboarding.inline(args.agent)} (origin {origin})")
    return 0
