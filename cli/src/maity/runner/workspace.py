"""A placement's clone (runner design §5.3).

The path is `<workspaces>/<project_id>/<clone>` (§15.5): keyed on the project's fixed id, so a
renamed or transferred project (§6.25) finds its clone again. The path is built from validated
tokens and checked to stay inside `<workspaces>`. Which agent a clone belongs to is the runner's
record in `<state_dir>/workspaces.json`, never a file in the clone, which the agent can write.

For a harness in FOLDER_HARNESSES (`antigravity`) that path is the placement's workspace folder
and the clone is `repo` in it (§15.5): the harness starts in the folder, never in the clone,
whose own harness configuration it would load (cli/context/runner.md). The record names the
layout, and no clone moves between the two.

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
import os
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
# The harnesses that start in a workspace folder holding the clone as REPO (§15.5).
FOLDER_HARNESSES = ("antigravity",)
REPO = "repo"
FOLDER, CLONE = "folder", "clone"  # the layouts, as the record names them
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
    path: Path  # the clone, or for a folder layout the workspace folder that holds it
    project: str
    clone: str
    host: str = ""  # the ssh target; "" on this machine
    folder: bool = False  # `path` is a workspace folder with the clone as REPO in it

    @property
    def key(self) -> str:
        """The record's key: the path, prefixed with the host for a clone on an ssh host."""
        return f"{self.host}:{self.path}" if self.host else str(self.path)

    @property
    def repo(self) -> Path:
        """The clone itself: `path`, or REPO in the workspace folder."""
        return self.path / REPO if self.folder else self.path

    @property
    def layout(self) -> str:
        return FOLDER if self.folder else CLONE

    @property
    def credential(self) -> Path:
        """Where the agent-side CLI keeps the clone's credential (its Git directory)."""
        return self.repo / ".git" / "maity" / state.CREDENTIAL_FILE


def uses_folder(harness_id: str) -> bool:
    """Whether a placement of the harness gets a workspace folder with the clone in it."""
    return harness_id in FOLDER_HARNESSES


def locate(root: Path, project: str, clone: str, host: str = "", folder: bool = False) -> Workspace:
    """The clone's path under `root` (for `folder`, the workspace folder's). On an ssh host
    `root` is a remote path, validated by the configuration and never resolved here; the
    tokens cannot leave it either way."""
    if not (TOKEN.match(project) and TOKEN.match(clone)):
        raise Refused("workspace_in_use", "workspace_unrecorded")
    if host:
        return Workspace(root / project / clone, project, clone, host, folder)
    base = root.resolve()
    path = (base / project / clone).resolve()
    if path.parent.parent != base:
        raise Refused("workspace_in_use", "workspace_unrecorded")
    return Workspace(path, project, clone, folder=folder)


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
        if workspace.folder:  # a record without it is a clone, as every record before it
            entry["layout"] = FOLDER
        found[workspace.key] = entry
        state.save_state(state_dir, found, name=RECORDS)


def owned(
    cfg: config.Config, workspace: Workspace, agent: str, placement_id: str | None = None
) -> dict[str, Any]:
    """The runner's record of an existing clone, when it is `agent`'s (or was made for this
    placement, which covers the time between a join and the hub naming the new member) and
    of the workspace's layout; `Refused` otherwise. A path recorded in the other layout is
    not this one: no clone moves between a plain clone and a workspace folder (§15.5).
    Reads the runner's own record only, nothing in the clone."""
    found = records(cfg.state_dir).get(workspace.key)
    if not isinstance(found, dict):
        raise Refused("workspace_in_use", "workspace_unrecorded")
    if found.get("agent") != agent and (
        placement_id is None or found.get("placement_id") != placement_id
    ):
        raise Refused("workspace_in_use", "other_agent")
    if found.get("layout", CLONE) != workspace.layout:
        layout = found.get("layout", CLONE)
        why = f"{workspace.path} is recorded as a {layout}, not a {workspace.layout}"
        raise Refused("workspace_in_use", "workspace_unrecorded", why=why)
    return found


def recorded_layout(record: Any) -> bool:
    """Whether a record names the folder layout."""
    return isinstance(record, dict) and record.get("layout") == FOLDER


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
    url = origin(workspace.repo, as_user)
    if url is None or config.normalise_repository(url) != config.normalise_repository(repository):
        raise Refused("workspace_in_use", "origin_mismatch")
    return found


def plain(workspace: Workspace, as_user: AsUser = RUNNER) -> None:
    """`Refused` when the clone's `.git` is not a plain clone's (clonecheck): an earlier
    session of the agent may have planted what git follows elsewhere (a `commondir`,
    `worktrees/`), so nothing starts in such a clone, and neither the agent nor a person's
    later git in it lands where the plant points (§15.7)."""
    finding = clonecheck.not_inspectable(workspace.repo, as_user)
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
    if as_user.exists(workspace.repo):
        existing = inspect(cfg, workspace, repository, agent, placement_id, as_user)
        if existing.get("placement_id") != placement_id:
            record(cfg.state_dir, workspace, agent, placement_id)
        return
    if workspace.folder and as_user.exists(workspace.path):
        # A folder without its clone: one an earlier start made before its clone failed, a
        # person's, or the other layout's. Only an empty one of this agent's (or nobody's)
        # takes the clone; nothing in it is deleted.
        if workspace.key in records(cfg.state_dir):
            owned(cfg, workspace, agent, placement_id)
        found = entries(workspace.path, as_user)
        if found:
            raise Refused("workspace_in_use", "workspace_not_bare", why=_named(found))
    as_user.mkdir(workspace.path if workspace.folder else workspace.path.parent)
    if not config.repository_url_ok(repository):
        raise Refused("repository_refused")
    # Only these transports, whatever the URL or a submodule says (no file://, no ext::).
    command = ["git", "-c", "protocol.allow=never"]
    for protocol in PROTOCOLS:
        command += ["-c", f"protocol.{protocol}.allow=always"]
    command += ["clone", "--quiet"]
    if branch:
        command += ["--branch", branch]
    command += ["--", repository, str(workspace.repo)]
    try:
        if not as_user.direct:
            # The clone is the agents'; no prompt for a login, as proc.run says for ours.
            done = as_user.run(command, env=dict(proc.NO_PROMPT), timeout=CLONE_TIMEOUT)
        else:
            done = proc.run(
                command, cwd=workspace.repo.parent, timeout=CLONE_TIMEOUT,
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


# --- the workspace folder (§15.3, §15.5) ------------------------------------------------------

# One listing of a workspace folder on the agents' side ($1, absolute): its physical path, its
# entries (names only, hidden ones included), what REPO is, and each directory from its parent
# up to `/` that has an entry `.git`, a dangling link included. NUL-separated records.
_FOLDER = (
    'cd -P -- "$1" || exit 3; printf "real\\t%s\\0" "$(pwd -P)"; '
    'for e in "$1"/* "$1"/.[!.]* "$1"/..?*; do '
    'if [ -e "$e" ] || [ -L "$e" ]; then printf "entry\\t%s\\0" "${e##*/}"; fi; done; '
    'if [ -L "$1/repo" ]; then printf "repo\\tlink\\0"; '
    'elif [ -d "$1/repo" ]; then printf "repo\\tdir\\0"; fi; '
    'p=$(dirname -- "$1"); while :; do '
    'if [ -e "$p/.git" ] || [ -L "$p/.git" ]; then printf "git\\t%s\\0" "$p"; fi; '
    '[ "$p" = / ] && break; p=$(dirname -- "$p"); done'
)


@dataclass(frozen=True)
class Folder:
    """A workspace folder as found: its real path, its entries, whether REPO is a directory
    of its own (not a link), and the directories above it that have a `.git`."""

    real: str
    names: tuple[str, ...]
    repo_dir: bool
    in_repository: tuple[str, ...]


def read_folder(path: Path, as_user: AsUser = RUNNER) -> Folder:
    """`path` as the agents' user sees it; OSError when it cannot be read."""
    if as_user.direct:
        names = tuple(sorted(os.listdir(path)))
        repo = path / REPO
        above = tuple(str(d) for d in path.parents if os.path.lexists(d / ".git"))
        return Folder(os.path.realpath(path), names, repo.is_dir() and not repo.is_symlink(),
                      above)  # fmt: skip
    done = as_user.run(["sh", "-c", _FOLDER, "sh", str(path)])
    if done.returncode != 0:
        raise OSError(f"cannot list {path} on the agents' side")
    real, repo_dir = "", False
    listed: list[str] = []
    gits: list[str] = []
    for item in filter(None, done.stdout.split("\0")):
        kind, _, value = item.partition("\t")
        if kind == "real":
            real = value
        elif kind == "entry":
            listed.append(value)
        elif kind == "repo":
            repo_dir = value == "dir"
        elif kind == "git":
            gits.append(value)
    return Folder(real, tuple(sorted(listed)), repo_dir, tuple(gits))


def entries(path: Path, as_user: AsUser = RUNNER) -> list[str]:
    """Every entry in a workspace folder; an unreadable folder is refused as not bare, since
    it may hold anything."""
    try:
        return list(read_folder(path, as_user).names)
    except OSError as exc:
        raise Refused("workspace_in_use", "workspace_not_bare", why=str(exc)) from None


def beside(place: Workspace, as_user: AsUser = RUNNER) -> list[str] | None:
    """The entries of a workspace folder besides its clone, which git in the clone cannot see
    and which count as unsaved work before a removal (§15.5); a REPO that is a link or no
    directory counts too. None when the folder cannot be read; [] for a plain clone."""
    if not place.folder:
        return []
    try:
        found = read_folder(place.path, as_user)
    except OSError:
        return None
    return [n for n in found.names if n != REPO or not found.repo_dir]


def check_folder(place: Workspace, as_user: AsUser = RUNNER) -> None:
    """Before every start in a workspace folder (§15.3, §15.5): its path is its real path, no
    directory above it up to `/` has an entry `.git`, and it holds nothing but the clone,
    a directory REPO. agy would load what is there or above. `Refused` otherwise, with the
    entries or the directory named for the runner's log only; nothing is deleted."""
    if not place.folder:
        return
    try:
        found = read_folder(place.path, as_user)
    except OSError as exc:
        raise Refused("workspace_in_use", "workspace_not_bare", why=str(exc)) from None
    if found.real != str(place.path):
        why = f"{place.path} is not its real path ({_printable(found.real)})"
        raise Refused("workspace_in_use", "workspace_in_repository", why=why)
    if found.in_repository:
        where = ", ".join(_printable(d) for d in found.in_repository)
        why = f"{place.path} lies inside a git work tree: {where} has an entry .git"
        raise Refused("workspace_in_use", "workspace_in_repository", why=why)
    extra = [n for n in found.names if n != REPO or not found.repo_dir]
    if extra or REPO not in found.names:
        why = _named(extra) if extra else f"{place.path} holds no clone {REPO}"
        raise Refused("workspace_in_use", "workspace_not_bare", why=why)


def _printable(text: str) -> str:
    return "".join(ch if ch.isprintable() else "?" for ch in text)


def _named(names: list[str], limit: int = 20) -> str:
    """The entries for the log: names only, printable, at most `limit` of them."""
    shown = [_printable(n)[:100] for n in names[:limit]]
    more = f" and {len(names) - limit} more" if len(names) > limit else ""
    return "the workspace folder holds " + ", ".join(shown) + more + f" besides {REPO}"
