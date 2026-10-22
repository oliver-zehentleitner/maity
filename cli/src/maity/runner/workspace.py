"""A placement's clone (runner design §5.3).

The path is `<workspaces>/<project>/<clone>`, built from validated tokens and checked to stay
inside `<workspaces>`. Which agent a clone belongs to is the runner's record in
`<state_dir>/workspaces.json`, never a file in the clone, which the agent can write.

No git in an existing clone: the agent can write `.git/config` and `.git/hooks`, so any git
command run there by the runner would run the agent's code as the runner. `origin` is read by
parsing `.git/config`, a stale `index.lock` is a stat. The only git the runner runs is
`git clone` into a directory that does not exist yet.
"""

from __future__ import annotations

import configparser
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import proc, state
from . import config

TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
RECORDS = "workspaces.json"
CLONE_TIMEOUT = 600.0
STALE_LOCK = 600.0
PROTOCOLS = ("https", "ssh")
_lock = threading.Lock()


class Refused(Exception):
    """The workspace cannot be used: `reason` and `detail` as reported (§15.7)."""

    def __init__(self, reason: str, detail: str | None = None, exit_code: int | None = None):
        super().__init__(f"{reason}/{detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.exit_code = exit_code


@dataclass(frozen=True)
class Workspace:
    path: Path
    project: str
    clone: str

    @property
    def credential(self) -> Path:
        """Where the agent-side CLI keeps the clone's credential (its Git directory)."""
        return self.path / ".git" / "maity" / state.CREDENTIAL_FILE


def locate(root: Path, project: str, clone: str) -> Workspace:
    if not (TOKEN.match(project) and TOKEN.match(clone)):
        raise Refused("workspace_in_use", "workspace_unrecorded")
    base = root.resolve()
    path = (base / project / clone).resolve()
    if path.parent.parent != base:
        raise Refused("workspace_in_use", "workspace_unrecorded")
    return Workspace(path, project, clone)


def origin(path: Path) -> str | None:
    """`remote.origin.url` from `.git/config`, parsed, never through git."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read_string((path / ".git" / "config").read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, configparser.Error):
        return None
    try:
        return parser.get('remote "origin"', "url")
    except configparser.Error:
        return None


def stale_index_lock(path: Path, now: float | None = None) -> bool:
    lock = path / ".git" / "index.lock"
    try:
        return (now or time.time()) - lock.stat().st_mtime > STALE_LOCK
    except OSError:
        return False


def records(state_dir: Path) -> dict[str, Any]:
    if not state_dir.is_dir():
        return {}
    return state.load_state(state_dir, name=RECORDS)


def record(state_dir: Path, workspace: Workspace, agent: str, placement_id: str) -> None:
    with _lock:
        found = records(state_dir)
        found[str(workspace.path)] = {
            "project": workspace.project,
            "agent": agent,
            "placement_id": placement_id,
            "created_at": int(time.time()),
        }
        state.save_state(state_dir, found, name=RECORDS)


def inspect(
    cfg: config.Config,
    workspace: Workspace,
    repository: str,
    agent: str,
    placement_id: str | None = None,
) -> dict[str, Any]:
    """An existing clone's record, when it is `agent`'s (or was made for this placement,
    which covers the time between a join and the hub naming the new member) and points at
    `repository`; `Refused` otherwise. Reads the record and `.git/config` only."""
    found = records(cfg.state_dir).get(str(workspace.path))
    if not isinstance(found, dict):
        raise Refused("workspace_in_use", "workspace_unrecorded")
    if found.get("agent") != agent and (
        placement_id is None or found.get("placement_id") != placement_id
    ):
        raise Refused("workspace_in_use", "other_agent")
    url = origin(workspace.path)
    if url is None or config.normalise_repository(url) != config.normalise_repository(repository):
        raise Refused("workspace_in_use", "origin_mismatch")
    return found


def prepare(
    cfg: config.Config,
    workspace: Workspace,
    repository: str,
    agent: str,
    placement_id: str,
    branch: str | None = None,
) -> None:
    """Make sure the clone exists and belongs to `agent`; clone it when it is missing.
    `Refused` otherwise. `agent` is the agent's id, or its handle before the first join."""
    if workspace.path.exists():
        existing = inspect(cfg, workspace, repository, agent, placement_id)
        if existing.get("placement_id") != placement_id:
            record(cfg.state_dir, workspace, agent, placement_id)
        return
    workspace.path.parent.mkdir(parents=True, exist_ok=True)
    if not config.repository_url_ok(repository):
        raise Refused("repository_refused")
    # Only these transports, whatever the URL or a submodule says (no file://, no ext::).
    command = ["git", "-c", "protocol.allow=never"]
    for protocol in PROTOCOLS:
        command += ["-c", f"protocol.{protocol}.allow=always"]
    command += ["clone", "--quiet"]
    if branch:
        command += ["--branch", branch]
    command += ["--", repository, str(workspace.path)]
    try:
        done = proc.run(command, cwd=workspace.path.parent, timeout=CLONE_TIMEOUT)
    except proc.ToolError:
        raise Refused("clone_failed") from None
    if done.returncode != 0:
        raise Refused("clone_failed", exit_code=done.returncode)
    record(cfg.state_dir, workspace, agent, placement_id)


def rebind(state_dir: Path, workspace: Workspace, old: str, new: str) -> None:
    """After the first join the record moves from the handle to the agent's id."""
    with _lock:
        found = records(state_dir)
        entry = found.get(str(workspace.path))
        if entry and entry.get("agent") == old:
            entry["agent"] = new
            state.save_state(state_dir, found, name=RECORDS)
