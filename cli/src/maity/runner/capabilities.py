"""What the runner advertises to the hub (docs/api.md §15.3, §15.8).

Advertised, never granted: the hub shows it for choosing and checks placements against it,
and the runner checks every placement against its own configuration again. Every string is
printable ASCII of at most 200 characters.
"""

from __future__ import annotations

import functools
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import proc
from . import config
from .asuser import RUNNER, AsUser

VERSION_TIMEOUT = 10.0
# A version as a harness prints it, whole: its prerelease and build metadata may hold `-`
# (`2.1.295--rc`), so neither is cut short into a release. It is a token of its own: after
# the start, a blank, `(` or `v`, and before the end, a blank, `)`, `,` or `;`. A token with
# anything else (`2.1.295+`, `2.1.295-_dev`) is no version here; the probe keeps the whole
# line, which no gate reads as a version. Both probes read with it (local here, ssh in
# targets).
VERSION = re.compile(
    r"(?<![^\s(v])\d+(?:\.\d+)+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?(?![^\s),;])"
)
_UNPRINTABLE = re.compile(r"[^\x20-\x7e]")
# The harness versions whose sandbox behaviour was checked for a call with something placed
# in front of `maity` (runner.md, the adapters entry). Another version still runs; the runner
# says that it was not checked.
CHECKED = {"claude-code": "2.1.318"}


# The oldest Claude Code whose hooks refuse the call when they fail or time out
# (`onFailure: "block"`): the runner's sandboxed sessions rely on it (adapters.claude_settings),
# so its sandbox is switched on only from this version (cli/context/runner.md).
CLAUDE_SANDBOX_MIN = (2, 1, 295)
# A SemVer 2.0.0 version: MAJOR.MINOR.PATCH without leading zeros, an optional prerelease
# (`-…`, dot-separated identifiers, a numeric one without a leading zero) and build metadata
# (`+…`); no identifier is empty. Anything else is no version the gate reads.
_NUMBER = r"(?:0|[1-9]\d*)"
_PRE_ID = rf"(?:{_NUMBER}|\d*[A-Za-z-][0-9A-Za-z-]*)"
_BUILD_ID = r"[0-9A-Za-z-]+"
_RELEASE = re.compile(
    rf"({_NUMBER})\.({_NUMBER})\.({_NUMBER})"
    rf"(-{_PRE_ID}(?:\.{_PRE_ID})*)?(\+{_BUILD_ID}(?:\.{_BUILD_ID})*)?"
)


def sandbox_version_ok(harness_id: str, version: str | None) -> bool:
    """Whether the runner may switch the harness's sandbox on at this version: for Claude Code
    CLAUDE_SANDBOX_MIN or later, read from the probed version; an unknown or unreadable
    version is not, nor is any other shape. A prerelease sorts before its release (SemVer
    §11), so `2.1.295-rc.1` is below the minimum; build metadata (`+…`) does not count.
    Other harnesses: always."""
    if harness_id != "claude-code":
        return True
    match = _RELEASE.fullmatch(version or "")
    if match is None:
        return False
    release = tuple(int(part) for part in match.groups()[:3])
    if match.group(4) is not None:  # a prerelease of `release`
        return release > CLAUDE_SANDBOX_MIN
    return release >= CLAUDE_SANDBOX_MIN


def sandbox_version_line(version: str | None) -> str:
    """Why Claude Code's sandbox stays off at this version, for `check` and the log."""
    oldest = ".".join(str(part) for part in CLAUDE_SANDBOX_MIN)
    return (
        f"harness claude-code: version {version or 'unknown'} is older than {oldest} or"
        " unknown; its sandbox is not switched on (the runner's hook needs `onFailure`)"
    )


def sandbox_held(harness_id: str, tools: bool, version: str | None) -> bool:
    """Claude Code whose sandbox tools are there, at a version the gate does not take (older
    than CLAUDE_SANDBOX_MIN, or unknown): its sandbox is off for the version alone."""
    return harness_id == "claude-code" and tools and not sandbox_version_ok(harness_id, version)


def sandbox_refused(harness: config.Harness, on: bool, held: bool) -> bool:
    """Whether a start of `harness` is refused for its sandbox: never while it is on; with
    `require_sandbox = true` whenever it is off; unset (the default) when it is off for the
    version alone (`sandbox_held`); never with an explicit `require_sandbox = false`, the
    opt-out for a host where the agents run unsandboxed on purpose."""
    if on:
        return False
    if harness.require_sandbox is None:
        return held
    return harness.require_sandbox


# Where Claude Code reads its managed settings, which no `--settings` file overrides: a
# switch there that turns hooks off would leave a sandboxed agent's `maity` line unchecked.
# Hosts of the ssh backend are Linux (bwrap and socat).
CLAUDE_MANAGED = {
    "linux": Path("/etc/claude-code/managed-settings.json"),
    "darwin": Path("/Library/Application Support/ClaudeCode/managed-settings.json"),
}
HOOK_SWITCHES = ("disableAllHooks", "allowManagedHooksOnly")
SETTINGS_MAX = 1024 * 1024  # a Claude Code settings file read for its hook switches
_DROP_INS = 'for f in "$1"/*.json; do if [ -f "$f" ]; then printf "%s\\n" "$f"; fi; done'


def _present(as_user: AsUser, path: Path, kind: str = "-e") -> bool:
    """`test` on the agents' side; anything but a clear yes or no is an OSError."""
    if as_user.direct:
        return as_user.exists(path, kind)
    done = as_user.run(["test", kind, str(path)])
    if done.returncode not in (0, 1):
        raise OSError(f"{path} cannot be checked (exit {done.returncode})")
    return done.returncode == 0


def claude_hooks_off(as_user: AsUser = RUNNER, platform: str | None = None) -> str | None:
    """Why the runner's hook would not run for the agents' Claude Code, or None. Managed
    settings (the file, and each `*.json` in `managed-settings.d/` beside it) that set
    `disableAllHooks` or `allowManagedHooksOnly`, or that cannot be read as JSON: unknown
    counts as off. In the agents' user settings only `allowManagedHooksOnly` counts; the
    runner's own settings file sets `disableAllHooks` back to false over theirs."""
    if as_user.here:
        platform = sys.platform if platform is None else platform
    else:
        platform = "linux"
    managed = next((p for key, p in CLAUDE_MANAGED.items() if platform.startswith(key)), None)
    # Each file with its switches and the directory it is read from (limitread): the managed
    # settings' own directory, the agents' user's home.
    files: list[tuple[Path, tuple[str, ...], Path]] = []
    try:
        if managed is not None:
            if _present(as_user, managed):
                files.append((managed, HOOK_SWITCHES, managed.parent))
            drop_ins = managed.parent / "managed-settings.d"
            if _present(as_user, drop_ins, "-d"):
                done = as_user.run(["sh", "-c", _DROP_INS, "sh", str(drop_ins)])
                if done.returncode != 0:
                    return f"{drop_ins} cannot be listed"
                listed = sorted(done.stdout.splitlines())
                files += [(Path(line), HOOK_SWITCHES, managed.parent) for line in listed]
        home = as_user.home()
        user = home / ".claude" / "settings.json"
        if _present(as_user, user):
            files.append((user, ("allowManagedHooksOnly",), home))
    except (OSError, KeyError) as exc:
        return f"the Claude Code settings cannot be checked ({ascii_text(str(exc), 120)})"
    for path, switches, under in files:
        try:
            data = json.loads(as_user.read_whole(path, SETTINGS_MAX, under=under))
        except (OSError, KeyError, ValueError):
            return f"{path} cannot be read as JSON"
        if not isinstance(data, dict):
            return f"{path} is not a JSON object"
        on = [key for key in switches if data.get(key) is not False and key in data]
        if on:
            return f"{path} sets {' and '.join(on)}"
    return None


def claude_hooks_line(why: str) -> str:
    """Why a sandboxed Claude Code agent is not started, for `check` and the log."""
    return (f"harness claude-code: {why}, so the runner's hook would not run; its sandboxed"
            " agents are not started until the setting is removed")  # fmt: skip


def unchecked(harness_id: str, version: str | None) -> str | None:
    """A warning when `version` of the harness is not the one its sandbox was checked with,
    or None."""
    checked = CHECKED.get(harness_id)
    if checked is None or version == checked:
        return None
    return (f"harness {harness_id}: its sandbox was checked with {checked}, this is"
            f" {version or 'an unknown version'}; whether a call with something in front of"
            " `maity` stays in the sandbox is not checked for it")  # fmt: skip


def ascii_text(value: str, limit: int = 200) -> str:
    """Printable ASCII only, cut at `limit` characters."""
    return _UNPRINTABLE.sub("", value)[:limit]


@dataclass(frozen=True)
class Probe:
    """A harness binary as found on this machine."""

    path: str | None
    version: str | None
    reason: str | None  # binary_not_found, version_failed

    @property
    def available(self) -> bool:
        return self.reason is None


def probe(harness: config.Harness, agent_path: str, as_user: AsUser = RUNNER) -> Probe:
    """Resolve the harness binary on `agent_path` and read its version, as the agents' user:
    a binary that user cannot run is not available, whatever the runner can run."""
    if harness.id == "stub":
        return Probe(None, None, None)
    found = which(harness.binary or "", agent_path, as_user)
    if found is None:
        return Probe(None, None, "binary_not_found")
    try:
        if as_user.user:
            done = as_user.run([found, "--version"], env={"PATH": agent_path},
                               timeout=VERSION_TIMEOUT)  # fmt: skip
        else:
            done = proc.run([found, "--version"], cwd=Path.home(), timeout=VERSION_TIMEOUT)
    except (proc.ToolError, subprocess.TimeoutExpired):
        return Probe(found, None, "version_failed")
    lines = (done.stdout or done.stderr).strip().splitlines()
    if done.returncode != 0 or not lines:
        return Probe(found, None, "version_failed")
    match = VERSION.search(lines[0])
    return Probe(found, ascii_text(match.group(0) if match else lines[0], 80), None)


def claude_sandbox_tools(platform: str | None = None) -> tuple[str, ...] | None:
    """What Claude Code's OS sandbox needs on the agents' PATH on this platform: bubblewrap
    and socat on Linux, Seatbelt's `sandbox-exec` on macOS (part of the system). None where
    Claude Code has no OS sandbox, so its agents run unsandboxed (cli/context/runner.md)."""
    platform = sys.platform if platform is None else platform
    if platform.startswith("linux"):
        return ("bwrap", "socat")
    if platform == "darwin":
        return ("sandbox-exec",)
    return None


def sandbox_available(
    harness: config.Harness, path: str | None = None, as_user: AsUser = RUNNER
) -> bool:
    """Whether the harness's own OS sandbox can be switched on for the agents: Claude Code's
    needs its tools (`claude_sandbox_tools`, §6.1) found on the agents' PATH. Codex's is
    tried once per binary (`codex sandbox -- true`): a host where it cannot start is not
    advertised as sandboxed. Nothing else is switched on yet."""
    if harness.id == "codex":
        binary = which(harness.binary or "codex", path, as_user)
        return binary is not None and _codex_sandbox_starts(binary, as_user.user)
    tools = claude_sandbox_tools()
    if harness.id != "claude-code" or tools is None:
        return False
    return all(which(tool, path, as_user) for tool in tools)


def which(name: str, path: str | None, as_user: AsUser = RUNNER) -> str | None:
    """`name` on the agents' PATH as the agents' user finds it: a binary under that user's
    home, or one only it may run, is found the way its sessions find it."""
    if not as_user.user:
        return shutil.which(name, path=path)
    done = as_user.run(["sh", "-c", 'command -v -- "$1"', "sh", name],
                       env={"PATH": path or ""}, timeout=VERSION_TIMEOUT)  # fmt: skip
    return done.stdout.strip() or None if done.returncode == 0 else None


@functools.lru_cache(maxsize=8)
def _codex_sandbox_starts(binary: str, user: str | None = None) -> bool:
    """Once per binary path and agents' user for the service's lifetime: after upgrading
    Codex in place, or when the host's sandbox support changes, restart the runner. Tried as
    the user the agents run as, whose namespaces are the ones that count."""
    try:
        if user:
            done = AsUser(user).run([binary, "sandbox", "--", "true"], timeout=30)
        else:
            done = proc.run([binary, "sandbox", "--", "true"], cwd=Path.home(), timeout=30)
    except (proc.ToolError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def agent_path(cfg: config.Config, environ_path: str) -> str:
    return (cfg.local.agent_path if cfg.local else None) or environ_path


def harness_entry(
    harness: config.Harness,
    found: Probe,
    path: str | None = None,
    targets: list[str] | None = None,
    sandbox: bool | None = None,
    as_user: AsUser = RUNNER,
) -> dict[str, Any]:
    if sandbox is None:
        sandbox = sandbox_available(harness, path, as_user) and sandbox_version_ok(
            harness.id, found.version
        )
    on = sandbox
    return {
        "id": harness.id,
        "version": found.version,
        "available": found.available,
        "reason": found.reason,
        "modes": list(harness.modes),
        "default_mode": harness.default_mode,
        "models": [ascii_text(m) for m in harness.models],
        "targets": targets if targets is not None else ["local"],
        # Codex has no per-command allowlist of its own: its sandbox is the boundary.
        "confinement": {"stub": "none", "codex": "sandbox"}.get(harness.id, "allowlist"),
        "sandbox": "n/a" if harness.id == "stub" else "on" if on else "off",
    }


def build(
    cfg: config.Config,
    probes: dict[str, Probe],
    running: int = 0,
    targets: list[Any] | None = None,
) -> dict[str, Any]:
    """The `capabilities` object of `hello` and `PATCH /runner`. With `targets` (the ssh
    backend's hosts), one entry per host: a harness is offered on the hosts where it was
    found, and a host not reached yet is advertised unreachable, its harnesses unknown."""
    limits = cfg.limits
    if targets is not None and cfg.ssh is not None:
        return {
            "backend": cfg.backend,
            "max_agents": limits.max_agents,
            "running": running,
            "targets": [_ssh_target(t) for t in targets],
            "harnesses": [_ssh_harness(h, targets) for h in cfg.harnesses.values()],
            "projects": list(limits.projects),
            "repositories": list(limits.repositories),
            "require_local_approval": limits.require_local_approval,
        }
    local = cfg.local
    agents_user = local.agent_user if local and local.layout == "agent_user" else None
    return {
        "backend": cfg.backend,
        "max_agents": limits.max_agents,
        "running": running,
        "targets": [
            {
                "name": "local",
                "max_agents": limits.max_agents,
                "running": running,
                "reachable": True,
                "unreachable_since": None,
                "isolation": {
                    "kind": "shared_user",  # every agent of the target as one OS user
                    "user": ascii_text(agents_user or getpass.getuser()),
                    "runner_separate": agents_user is not None,
                },
            }
        ],
        "harnesses": [
            harness_entry(h, probes[h.id], agent_path(cfg, os.environ.get("PATH", "")),
                          as_user=AsUser(agents_user))  # fmt: skip
            for h in cfg.harnesses.values()
        ],
        "projects": list(limits.projects),
        "repositories": list(limits.repositories),
        "require_local_approval": limits.require_local_approval,
    }


def _ssh_target(target: Any) -> dict[str, Any]:
    return {
        "name": target.name,
        "max_agents": target.max_agents,
        "running": 0,
        "reachable": target.reachable,
        "unreachable_since": None,
        # One remote user per host; the runner is on another machine altogether.
        "isolation": {"kind": "shared_user", "user": ascii_text(target.as_user.login),
                      "runner_separate": True},  # fmt: skip
    }


def _ssh_harness(harness: config.Harness, targets: list[Any]) -> dict[str, Any]:
    reached = [t for t in targets if t.probes]
    where = [t.name for t in reached if t.probes[harness.id].available]
    found = next((t.probes[harness.id] for t in reached if t.name in where), None)
    if found is None:  # nowhere yet: the reason of the first host reached, if any
        found = reached[0].probes[harness.id] if reached else Probe(None, None, None)
    sandbox = bool(where) and all(
        t.sandbox.get(harness.id, False) for t in reached if t.name in where
    )
    return harness_entry(harness, found, targets=where, sandbox=sandbox)
