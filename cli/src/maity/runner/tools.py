"""The harness tools the runner manages, and `maity` itself (docs/api.md §15.16).

Each managed tool lives under `<tools_dir>/<id>/` (config.Config.tools_dir): one
directory per installed version (`versions/<version>/`) and `state.json`, which names the
version new sessions start with, the one kept for a rollback, and what the last check
found. A session keeps the absolute binary path it started with, so switching the version
in use never touches a running session. A tool the configuration does not manage is looked
up on the agents' PATH as before.

The installers themselves (which vendor package belongs to which tool) are fixed in code
(`INSTALLERS`), never taken from the configuration or the hub.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

STATES = ("current", "rolled_back", "missing", "installing", "updating", "login_needed", "failed")
REASONS = ("installer_failed", "version_failed", "network", "no_space")
_VERSION = re.compile(r"^\d+(?:\.\d+){0,3}$")


class InstallError(Exception):
    """An installer that could not finish; `reason` is one of REASONS."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


class Installer(Protocol):
    """One tool's vendor package, pinned to an exact version."""

    def latest(self) -> str:
        """The newest version the vendor offers; InstallError("network") when unreachable."""

    def install(self, version: str, into: Path) -> Path:
        """Install exactly `version` into the empty directory `into`, verifying what the
        vendor lets us verify; return the binary's path. Raise InstallError, never fall back
        to an unverified download."""

    def version_of(self, binary: Path) -> str | None:
        """The tool's own version answer, or None when it does not run."""


# Filled by the installer modules: tool id -> factory. A harness without one cannot be
# configured with `install` or `update` (config.py refuses it at load).
INSTALLERS: dict[str, Callable[[], Installer]] = {}


def version_key(version: str) -> tuple[int, ...] | None:
    """A plain dotted version as numbers; None for anything else (never ordered)."""
    return tuple(int(part) for part in version.split(".")) if _VERSION.match(version) else None


def newer(candidate: str, than: str | None) -> bool:
    if than is None:
        return True
    a, b = version_key(candidate), version_key(than)
    return a is not None and b is not None and a > b


@dataclass
class ToolState:
    version: str | None = None
    previous_version: str | None = None
    latest: str | None = None
    state: str = "current"
    reason: str | None = None
    checked_at: str | None = None
    updated_at: str | None = None
    update_requested_at: str | None = None
    # Versions the runner does not take again on its own: the one a rollback left, and
    # ones that failed their version answer (§15.16 "Rollback").
    skipped: list[str] = field(default_factory=list)


BINARY_FILE = "binary.path"  # the binary's path inside its version directory
LOCK_FILE = "lock"


class Busy(Exception):
    """Another process (the runner's install, or `maity runner tools rollback`) holds the
    tool's lock."""


def root(tools_dir: Path, tool_id: str) -> Path:
    return tools_dir / tool_id


def load(tools_dir: Path, tool_id: str) -> ToolState:
    path = root(tools_dir, tool_id) / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ToolState()
    known = {k: v for k, v in data.items() if k in ToolState.__dataclass_fields__}
    return ToolState(**known)


def save(tools_dir: Path, tool_id: str, state: ToolState) -> None:
    folder = root(tools_dir, tool_id)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = folder / "state.json.tmp"
    tmp.write_text(json.dumps(asdict(state), indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, folder / "state.json")


@contextmanager
def locked(tools_dir: Path, tool_id: str, *, wait: bool = True) -> Iterator[None]:
    """The tool's lock across processes: `serve`'s install or update and a `rollback` from
    the command line never write `state.json` or remove a version at the same time. Without
    `wait`, Busy when another process holds it. The runner does not run on Windows
    (context/credentials.md), where nothing is locked."""
    if sys.platform == "win32":
        yield
        return
    import fcntl

    folder = root(tools_dir, tool_id)
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(folder / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if wait else fcntl.LOCK_NB))
        except BlockingIOError:
            raise Busy(f"{tool_id}: an install or update is running") from None
        yield
    finally:
        os.close(fd)  # closing it releases the lock


def version_dir(tools_dir: Path, tool_id: str, version: str) -> Path:
    return root(tools_dir, tool_id) / "versions" / version


def binary(tools_dir: Path, tool_id: str) -> Path | None:
    """The managed binary new sessions start with, or None when none is installed."""
    state = load(tools_dir, tool_id)
    if state.version is None:
        return None
    folder = version_dir(tools_dir, tool_id, state.version)
    try:
        relative = (folder / BINARY_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    found = folder / relative
    return found if relative and ".." not in Path(relative).parts and found.is_file() else None


def rollback(tools_dir: Path, tool_id: str) -> ToolState:
    """Swap the version in use with the kept one (§15.16); a second rollback swaps back.
    The version it leaves is not taken again on its own; a newer one ends that. ValueError
    while an install or update of the tool runs: it would overwrite the swap."""
    try:
        with locked(tools_dir, tool_id, wait=False):
            return _rollback(tools_dir, tool_id)
    except Busy as exc:
        raise ValueError(f"{exc}; try again when it is done") from None


def _rollback(tools_dir: Path, tool_id: str) -> ToolState:
    state = load(tools_dir, tool_id)
    if state.previous_version is None or state.version is None:
        raise ValueError(f"{tool_id}: no kept version to go back to")
    left = state.version
    state.version, state.previous_version = state.previous_version, left
    state.skipped = [v for v in state.skipped if v != state.version] + [left]
    state.state = (
        "rolled_back"
        if state.latest is not None and newer(state.latest, state.version)
        else "current"
    )
    state.reason = None
    save(tools_dir, tool_id, state)
    return state


def report(
    tools_dir: Path, tool_id: str, *, install: bool, update: str, sessions_on_older: int
) -> dict[str, Any]:
    """One entry of `capabilities.tools` (§15.16)."""
    state = load(tools_dir, tool_id)
    shown = state.state
    if state.version is None and shown == "current":
        shown = "missing"
    return {
        "id": tool_id,
        "install": install,
        "update": update,
        "version": state.version,
        "previous_version": state.previous_version,
        "latest": state.latest if update != "never" else None,
        "state": shown,
        "reason": state.reason if shown == "failed" else None,
        "checked_at": state.checked_at,
        "updated_at": state.updated_at,
        "sessions_on_older": sessions_on_older,
        "update_requested_at": state.update_requested_at,
    }


def take(
    tools_dir: Path,
    tool_id: str,
    installer: Installer,
    now: str,
    *,
    requested_at: str | None = None,
    started: Callable[[], None] = lambda: None,
) -> ToolState:
    """Look for a newer version and install it beside the one in use (§15.16). Used for the
    first install, the daily check and `Update now` alike. Holds the tool's lock throughout,
    so a rollback waits for it; `started` is called once `installing` or `updating` is
    saved. Never removes a version: older ones go in `prune`, once no session uses them."""
    with locked(tools_dir, tool_id):
        return _take(tools_dir, tool_id, installer, now, requested_at, started)


def _take(
    tools_dir: Path,
    tool_id: str,
    installer: Installer,
    now: str,
    requested_at: str | None,
    started: Callable[[], None],
) -> ToolState:
    state = load(tools_dir, tool_id)
    if requested_at is not None:
        state.update_requested_at = requested_at
    first = state.version is None
    state.state, state.reason = ("installing" if first else "updating"), None
    save(tools_dir, tool_id, state)
    started()
    try:
        latest = installer.latest()
    except InstallError as error:
        return _failed(tools_dir, tool_id, state, error.reason, now)
    except Exception:  # noqa: BLE001 - an installer's slip still ends the attempt as failed
        return _failed(tools_dir, tool_id, state, "installer_failed", now)
    state.latest, state.checked_at = latest, now
    if latest == state.version or latest in state.skipped or not newer(latest, state.version):
        state.state = "rolled_back" if latest in state.skipped and state.version else "current"
        save(tools_dir, tool_id, state)
        return state
    target = version_dir(tools_dir, tool_id, latest)
    staging = target.with_name(latest + ".partial")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, mode=0o700)
    try:
        found = installer.install(latest, staging)
    except InstallError as error:
        shutil.rmtree(staging, ignore_errors=True)
        return _failed(tools_dir, tool_id, state, error.reason, now)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        return _failed(tools_dir, tool_id, state, "no_space", now)
    except Exception:  # noqa: BLE001 - never left `installing` with a half-filled staging
        shutil.rmtree(staging, ignore_errors=True)
        return _failed(tools_dir, tool_id, state, "installer_failed", now)
    # Checked before anything runs it: a binary outside its directory is never started.
    if not found.is_relative_to(staging):  # an installer must stay in its directory
        shutil.rmtree(staging, ignore_errors=True)
        return _failed(tools_dir, tool_id, state, "installer_failed", now)
    try:
        answered = installer.version_of(found)
    except Exception:  # noqa: BLE001 - a binary that cannot answer did not answer
        answered = None
    if answered != latest:
        shutil.rmtree(staging, ignore_errors=True)
        state.skipped.append(latest)
        return _failed(tools_dir, tool_id, state, "version_failed", now)
    (staging / BINARY_FILE).write_text(str(found.relative_to(staging)) + "\n", encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    state.previous_version, state.version = state.version, latest
    state.updated_at, state.state, state.reason = now, "current", None
    state.skipped = [v for v in state.skipped if newer(v, latest)]
    save(tools_dir, tool_id, state)
    return state


def prune(tools_dir: Path, tool_id: str, in_use: set[str] | None) -> list[str]:
    """Remove the installed versions that are neither in use nor kept for a rollback, and
    that no running session started from: `in_use` holds those sessions' binaries, None
    when one of them is not known (nothing is removed then). Skipped while an install or
    rollback holds the lock; the next round tries again. Returns the versions removed."""
    if in_use is None:
        return []
    try:
        with locked(tools_dir, tool_id, wait=False):
            state = load(tools_dir, tool_id)
            keep = {state.version, state.previous_version}
            folder = root(tools_dir, tool_id) / "versions"
            removed = []
            for path in sorted(folder.iterdir()) if folder.is_dir() else []:
                if path.name in keep or any(Path(b).is_relative_to(path) for b in in_use):
                    continue
                shutil.rmtree(path, ignore_errors=True)
                removed.append(path.name)
            return removed
    except Busy:
        return []


def _failed(tools_dir: Path, tool_id: str, state: ToolState, reason: str, now: str) -> ToolState:
    state.state, state.reason, state.checked_at = "failed", reason, now
    save(tools_dir, tool_id, state)
    return state
