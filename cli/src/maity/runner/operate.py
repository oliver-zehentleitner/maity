"""The operator's commands on the runner host (runner design §10.1): `logs`, `approve`,
`stop-all`, `gc --revoked` and `workspace claim`. None of them asks the hub what to do;
`gc` asks it only whether a clone's credential is revoked, through the agent's own CLI.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .. import onboarding, state
from . import config, serve, supervisor, workspace

STOP_ALL_GRACE = 30
FOLLOW_EVERY = 1.0
# git run by the operator in an agent's clone: nothing the agent wrote may run (§7.5).
SAFE_GIT = [
    "git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
    "-c", "core.pager=cat", "-c", "diff.external=", "-c", "protocol.allow=never",
]  # fmt: skip


class Refused(Exception):
    """The command cannot run as asked; exit 2."""


def _status(cfg: config.Config) -> dict[str, Any]:
    if not cfg.state_dir.is_dir():
        return {}
    return state.load_state(cfg.state_dir, name=serve.STATUS_FILE)


def _placement_id(cfg: config.Config, which: str) -> str:
    """A placement id from an id, or from an agent handle the service last saw."""
    for placement in _status(cfg).get("placements") or []:
        if isinstance(placement, dict) and which in (placement.get("id"), placement.get("agent")):
            return str(placement["id"])
    if supervisor.PLACEMENT_ID.match(which):
        return which
    raise Refused(f"no placement {onboarding.inline(which)} on this runner")


# --- logs ------------------------------------------------------------------------------------


def cmd_logs(cfg: config.Config, args: argparse.Namespace) -> int:
    pid = _placement_id(cfg, args.which)
    path = cfg.state_dir / supervisor.LOGS / f"{pid}.log"
    if not path.is_file():
        raise Refused(f"no log for {pid} in {path.parent}")
    with path.open("rb") as fh:
        sys.stdout.buffer.write(fh.read())
        sys.stdout.flush()
        while args.follow:
            chunk = fh.read()
            if chunk:
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
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
        serve.hold_lock(cfg.state_dir).close()
    except serve.Fatal:
        raise Refused(
            "the runner service is running and would start the agents again; stop it first "
            "(systemctl stop maity-runner, or end `maity runner serve`)"
        ) from None
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
    CLI (the runner never holds the credential) and isolated from the clone's modules."""
    if not place.credential.is_file():
        return False
    env = {k: v for k, v in os.environ.items() if k != state.STATE_DIR_ENV}
    env[state.STATE_DIR_ENV] = str(place.credential.parent)
    done = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-I", "-m", "maity", "api", "GET", "/me"],
        cwd=Path.home(), env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    return done.returncode != 0 and "credential_revoked" in done.stderr


def unsaved_work(path: Path) -> list[str]:
    """Uncommitted files and commits on no remote, read with git defused (§7.5)."""
    lines: list[str] = []
    for command in (
        [*SAFE_GIT, "-C", str(path), "status", "--porcelain"],
        [*SAFE_GIT, "-C", str(path), "log", "--oneline", "--branches", "--not", "--remotes"],
    ):
        done = subprocess.run(  # noqa: S603 - fixed argv, a path the runner recorded
            command, capture_output=True, text=True, timeout=60, check=False
        )
        lines += [onboarding.inline(line) for line in done.stdout.splitlines() if line.strip()]
    return lines


def cmd_gc(cfg: config.Config, args: argparse.Namespace) -> int:
    if not args.revoked:
        raise Refused("gc removes only workspaces whose credential is revoked: pass --revoked")
    placed = {p.get("id") for p in _status(cfg).get("placements") or [] if isinstance(p, dict)}
    found = workspace.records(cfg.state_dir)
    gone: list[str] = []
    for path_text, record in sorted(found.items()):
        if not isinstance(record, dict) or record.get("placement_id") in placed:
            continue
        path = Path(path_text)
        place = workspace.Workspace(path, str(record.get("project")), path.name)
        if not path.is_dir() or not credential_revoked(place):
            continue
        work = unsaved_work(path)
        print(f"{path}  agent {onboarding.inline(record.get('agent'))}  credential revoked")
        for line in work:
            print(f"  {line}")
        if args.yes:
            shutil.rmtree(path)
            gone.append(path_text)
            print("  removed")
    if gone:
        for path_text in gone:
            found.pop(path_text, None)
        state.save_state(cfg.state_dir, found, name=workspace.RECORDS)
    elif not args.yes:
        print("nothing removed; pass --yes to remove the workspaces listed")
    return 0


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
