"""A placement's clone (runner design §5.3).

The path is `<workspaces>/<project_id>/<clone>` (§15.5): keyed on the project's fixed id, so a
renamed or transferred project (§6.25) finds its clone again. A workspace recorded before the
namespace under `<workspaces>/<slug>/<clone>` is taken over in place (`find`). The path is
built from validated tokens and checked to stay
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
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import proc, state
from . import config
from .asuser import RUNNER, AsUser

TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# A project as the hub names it since the namespace (§6.25): `<owner>/<slug>`.
FULL_NAME = re.compile(r"^([a-z0-9][a-z0-9-]{0,62})/([a-z0-9][a-z0-9-]{0,62})$")
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
    host: str = ""  # the ssh target; "" on this machine

    @property
    def key(self) -> str:
        """The record's key: the path, prefixed with the host for a clone on an ssh host."""
        return f"{self.host}:{self.path}" if self.host else str(self.path)

    @property
    def credential(self) -> Path:
        """Where the agent-side CLI keeps the clone's credential (its Git directory)."""
        return self.path / ".git" / "maity" / state.CREDENTIAL_FILE


def locate(root: Path, project: str, clone: str, host: str = "") -> Workspace:
    """The clone's path under `root`. On an ssh host `root` is a remote path, validated by
    the configuration and never resolved here; the tokens cannot leave it either way."""
    if not (TOKEN.match(project) and TOKEN.match(clone)):
        raise Refused("workspace_in_use", "workspace_unrecorded")
    if host:
        return Workspace(root / project / clone, project, clone, host)
    base = root.resolve()
    path = (base / project / clone).resolve()
    if path.parent.parent != base:
        raise Refused("workspace_in_use", "workspace_unrecorded")
    return Workspace(path, project, clone)


def find(
    state_dir: Path,
    root: Path,
    project_id: str,
    names: list[str],
    clone: str,
    agents: set[str],
    host: str = "",
) -> Workspace:
    """The workspace of a placement: `<root>/<project_id>/<clone>`, or the clone recorded
    before the project namespace under the slug of one of the project's `names` (its full
    name and aliases) for one of `agents` (the agent's id and handle). Such a clone is taken
    over in place, once: its record is rewritten to the project id, and it is never moved,
    since the agent may be running in it (§15.5)."""
    current = locate(root, project_id, clone, host)
    with _lock:
        found = records(state_dir)
        if current.key in found:
            return current
        for key, rec in found.items():
            if isinstance(rec, dict) and rec.get("project") == project_id:
                taken = _legacy(root, key, clone, host)
                if taken is not None:
                    return Workspace(taken, project_id, clone, host)
        for name in names:
            full = FULL_NAME.match(name)
            if full is None:
                continue
            try:
                legacy = locate(root, full[2], clone, host)
            except Refused:
                continue
            rec = found.get(legacy.key)
            if (
                isinstance(rec, dict)
                and rec.get("project") == full[2]
                and rec.get("agent") in agents
            ):
                found[legacy.key] = {**rec, "project": project_id, "legacy_slug": full[2]}
                state.save_state(state_dir, found, name=RECORDS)
                return Workspace(legacy.path, project_id, clone, host)
    return current


def _legacy(root: Path, key: str, clone: str, host: str) -> Path | None:
    """The path of a taken-over record's key, when it is `<root>/<slug>/<clone>` on `host`."""
    prefix = f"{host}:" if host else ""
    if not key.startswith(prefix):
        return None
    path = Path(key[len(prefix) :])
    base = root if host else root.resolve()
    if path.name != clone or path.parent.parent != base or not TOKEN.match(path.parent.name):
        return None
    if not host and path.resolve() != path:
        return None  # replaced by a link since the takeover: as `locate`, it may not leave
    return path


def origin(path: Path, as_user: AsUser = RUNNER) -> str | None:
    """`remote.origin.url` from `.git/config`, parsed, never through git."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read_string(as_user.read(path / ".git" / "config").decode("utf-8"))
    except (OSError, UnicodeDecodeError, configparser.Error):
        return None
    try:
        return parser.get('remote "origin"', "url")
    except configparser.Error:
        return None


def stale_index_lock(path: Path, now: float | None = None, as_user: AsUser = RUNNER) -> bool:
    if not as_user.direct:
        return False  # a hint only, and the lock's mtime is the agents' user's to read
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
        entry: dict[str, Any] = {
            "project": workspace.project,
            "agent": agent,
            "placement_id": placement_id,
            "created_at": int(time.time()),
        }
        # A taken-over clone keeps its location across placements: gc finds it by it.
        earlier = found.get(workspace.key)
        if isinstance(earlier, dict) and earlier.get("legacy_slug"):
            entry["legacy_slug"] = earlier["legacy_slug"]
        found[workspace.key] = entry
        state.save_state(state_dir, found, name=RECORDS)


def inspect(
    cfg: config.Config,
    workspace: Workspace,
    repository: str,
    agent: str,
    placement_id: str | None = None,
    as_user: AsUser = RUNNER,
) -> dict[str, Any]:
    """An existing clone's record, when it is `agent`'s (or was made for this placement,
    which covers the time between a join and the hub naming the new member) and points at
    `repository`; `Refused` otherwise. Reads the record and `.git/config` only."""
    found = records(cfg.state_dir).get(workspace.key)
    if not isinstance(found, dict):
        raise Refused("workspace_in_use", "workspace_unrecorded")
    if found.get("agent") != agent and (
        placement_id is None or found.get("placement_id") != placement_id
    ):
        raise Refused("workspace_in_use", "other_agent")
    url = origin(workspace.path, as_user)
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
    as_user: AsUser = RUNNER,
) -> None:
    """Make sure the clone exists and belongs to `agent`; clone it when it is missing.
    `Refused` otherwise. `agent` is the agent's id, or its handle before the first join."""
    if as_user.exists(workspace.path):
        existing = inspect(cfg, workspace, repository, agent, placement_id, as_user)
        if existing.get("placement_id") != placement_id:
            record(cfg.state_dir, workspace, agent, placement_id)
        return
    as_user.mkdir(workspace.path.parent)
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
        if not as_user.direct:
            # The clone is the agents'; no prompt for a login, as proc.run says for ours.
            done = as_user.run(command, env=dict(proc.NO_PROMPT), timeout=CLONE_TIMEOUT)
        else:
            done = proc.run(command, cwd=workspace.path.parent, timeout=CLONE_TIMEOUT)
    except (proc.ToolError, subprocess.TimeoutExpired):
        raise Refused("clone_failed") from None
    if done.returncode != 0:
        raise Refused("clone_failed", exit_code=done.returncode)
    record(cfg.state_dir, workspace, agent, placement_id)


def rebind(state_dir: Path, workspace: Workspace, old: str, new: str) -> None:
    """After the first join the record moves from the handle to the agent's id."""
    with _lock:
        found = records(state_dir)
        entry = found.get(workspace.key)
        if entry and entry.get("agent") == old:
            entry["agent"] = new
            state.save_state(state_dir, found, name=RECORDS)
