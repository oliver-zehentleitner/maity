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
from collections.abc import Callable
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
    The version it leaves is not taken again on its own; a newer one ends that."""
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
) -> ToolState:
    """Look for a newer version and install it beside the one in use (§15.16). Used for the
    first install, the daily check and `Update now` alike. Never removes the version in use;
    keeps one previous version and removes older ones."""
    state = load(tools_dir, tool_id)
    if requested_at is not None:
        state.update_requested_at = requested_at
    first = state.version is None
    state.state, state.reason = ("installing" if first else "updating"), None
    save(tools_dir, tool_id, state)
    try:
        latest = installer.latest()
    except InstallError as error:
        return _failed(tools_dir, tool_id, state, error.reason, now)
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
    answered = installer.version_of(found)
    if answered != latest:
        shutil.rmtree(staging, ignore_errors=True)
        state.skipped.append(latest)
        return _failed(tools_dir, tool_id, state, "version_failed", now)
    if not found.is_relative_to(staging):  # an installer must stay in its directory
        shutil.rmtree(staging, ignore_errors=True)
        return _failed(tools_dir, tool_id, state, "installer_failed", now)
    (staging / BINARY_FILE).write_text(str(found.relative_to(staging)) + "\n", encoding="utf-8")
    shutil.rmtree(target, ignore_errors=True)
    staging.rename(target)
    older = state.previous_version
    state.previous_version, state.version = state.version, latest
    state.updated_at, state.state, state.reason = now, "current", None
    state.skipped = [v for v in state.skipped if newer(v, latest)]
    save(tools_dir, tool_id, state)
    if older is not None and older not in (state.version, state.previous_version):
        shutil.rmtree(version_dir(tools_dir, tool_id, older), ignore_errors=True)
    return state


def _failed(tools_dir: Path, tool_id: str, state: ToolState, reason: str, now: str) -> ToolState:
    state.state, state.reason, state.checked_at = "failed", reason, now
    save(tools_dir, tool_id, state)
    return state
