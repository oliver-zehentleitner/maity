"""A placement's clone (runner design §5.3).

The path is `<workspaces>/<project_id>/<clone>` (§15.5): keyed on the project's fixed id, so a
renamed or transferred project (§6.25) finds its clone again. The path is built from validated
tokens and checked to stay inside `<workspaces>`. Which agent a clone belongs to is the runner's
record in `<state_dir>/workspaces.json`, never a file in the clone, which the agent can write.

No git in an existing clone: the agent can write `.git/config` and `.git/hooks`, so any git
command run there by the runner would run the agent's code as the runner. `origin` is read by
parsing `.git/config`, a stale `index.lock` is a stat. The only git the runner runs is
`git clone` into a directory that does not exist yet.

Nothing in a clone is read while the supervisor holds its lock: `owned` reads the runner's own
record only, and `prepare`, in the start task, reads the clone after `clonecheck` found it
plain, the way `AsUser.read` reads every file on the agents' side (limitread).
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

from .. import clonecheck, proc, redact, state
from . import config
from .asuser import RUNNER, AsUser

TOKEN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# A project as the hub names it since the namespace (§6.25): `<owner>/<slug>`.
FULL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}/[a-z0-9][a-z0-9-]{0,62}$")
RECORDS = "workspaces.json"
CLONE_TIMEOUT = 600.0
STALE_LOCK = 600.0
PROTOCOLS = ("https", "ssh")
_lock = threading.Lock()


class Refused(Exception):
    """The workspace cannot be used: `reason` and `detail` as reported (§15.7). `why` is
    for the runner's own log only, never for the hub: the report carries codes, and a
    tool's message is no code."""

    def __init__(
        self,
        reason: str,
        detail: str | None = None,
        exit_code: int | None = None,
        why: str | None = None,
    ):
        super().__init__(f"{reason}/{detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.exit_code = exit_code
        self.why = why


def said(text: str) -> str | None:
    """The last line a tool wrote, for the runner's log: printable, at most 300 characters,
    with the userinfo taken out of every URL in it. An https repository URL carries none,
    an ssh one at most a user name, but a redirect or a helper's message could carry more."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    line = "".join(ch if ch.isprintable() else "?" for ch in lines[-1])
    return redact.without_userinfo(line)[:300]


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


def origin(path: Path, as_user: AsUser = RUNNER) -> str | None:
    """`remote.origin.url` from `.git/config`, parsed, never through git."""
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        data = as_user.read_whole(path / ".git" / "config", clonecheck.CONFIG_MAX, under=path)
        parser.read_string(data.decode("utf-8"))
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
        found[workspace.key] = entry
        state.save_state(state_dir, found, name=RECORDS)


def owned(
    cfg: config.Config, workspace: Workspace, agent: str, placement_id: str | None = None
) -> dict[str, Any]:
    """The runner's record of an existing clone, when it is `agent`'s (or was made for this
    placement, which covers the time between a join and the hub naming the new member);
    `Refused` otherwise. Reads the runner's own record only, nothing in the clone."""
    found = records(cfg.state_dir).get(workspace.key)
    if not isinstance(found, dict):
        raise Refused("workspace_in_use", "workspace_unrecorded")
    if found.get("agent") != agent and (
        placement_id is None or found.get("placement_id") != placement_id
    ):
        raise Refused("workspace_in_use", "other_agent")
    return found


def inspect(
    cfg: config.Config,
    workspace: Workspace,
    repository: str,
    agent: str,
    placement_id: str | None = None,
    as_user: AsUser = RUNNER,
) -> dict[str, Any]:
    """`owned`, and then whether the clone is plain (`clonecheck`) and its origin is
    `repository`; `Refused` otherwise. Reads the record, the clone's `.git` listing and its
    `.git/config`: never under the supervisor's lock."""
    found = owned(cfg, workspace, agent, placement_id)
    plain(workspace, as_user)
    url = origin(workspace.path, as_user)
    if url is None or config.normalise_repository(url) != config.normalise_repository(repository):
        raise Refused("workspace_in_use", "origin_mismatch")
    return found


def plain(workspace: Workspace, as_user: AsUser = RUNNER) -> None:
    """`Refused` when the clone's `.git` is not a plain clone's (clonecheck): an earlier
    session of the agent may have planted what git follows elsewhere (a `commondir`,
    `worktrees/`), so nothing starts in such a clone, and neither the agent nor a person's
    later git in it lands where the plant points (§15.7)."""
    finding = clonecheck.not_inspectable(workspace.path, as_user)
    if finding is not None:
        raise Refused("workspace_in_use", "not_a_plain_clone", why=finding)


def prepare(
    cfg: config.Config,
    workspace: Workspace,
    repository: str,
    agent: str,
    placement_id: str,
    branch: str | None = None,
    as_user: AsUser = RUNNER,
) -> None:
    """Make sure the clone exists, is plain and belongs to `agent`; clone it when it is
    missing. `Refused` otherwise. `agent` is the agent's id, or its handle before the first
    join. Runs in the start task, never under the supervisor's lock (`inspect`)."""
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
            done = proc.run(
                command, cwd=workspace.path.parent, timeout=CLONE_TIMEOUT,
                transports=":".join(PROTOCOLS),
            )  # fmt: skip
    except proc.ToolError as exc:
        raise Refused("clone_failed", why=said(str(exc))) from None
    except subprocess.TimeoutExpired:
        why = f"git clone did not end within {CLONE_TIMEOUT:.0f} s"
        raise Refused("clone_failed", why=why) from None
    if done.returncode != 0:
        why = said(done.stderr or "") or f"git clone exited {done.returncode}"
        raise Refused("clone_failed", exit_code=done.returncode, why=why)
    record(cfg.state_dir, workspace, agent, placement_id)
    plain(workspace, as_user)


def rebind(state_dir: Path, workspace: Workspace, old: str, new: str) -> None:
    """After the first join the record moves from the handle to the agent's id."""
    with _lock:
        found = records(state_dir)
        entry = found.get(workspace.key)
        if entry and entry.get("agent") == old:
            entry["agent"] = new
            state.save_state(state_dir, found, name=RECORDS)
