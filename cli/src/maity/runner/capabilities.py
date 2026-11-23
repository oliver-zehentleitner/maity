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
import platform as _platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import proc, state
from . import config, tools
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
CHECKED = {"claude-code": "2.1.325"}
# The machines (Claude Code's names) Claude Code supports its seccomp step on, the step that
# keeps a sandboxed command from opening a Unix socket on Linux: x64 and arm64, read from the
# 2.1.328 and 2.1.329 binaries (ia32 is named unsupported, any other machine too). Elsewhere
# no helper resolves and every sandboxed command runs with Unix sockets open, without a word
# (`claude_seccomp`). Read again from the binary whenever CHECKED moves.
CLAUDE_SECCOMP_ARCHES = frozenset({"x64", "arm64"})


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
    return claude_at_least(version, CLAUDE_SANDBOX_MIN)


# The oldest Claude Code with the `WorktreeCreate` hook event, which the runner's worktree hook
# needs (adapters.claude_settings). Claude Code's hooks documentation names no version; this
# one rests on Claude Code's v2.1.50 release notes, as cited in review A1808; not verified
# against a live binary.
CLAUDE_WORKTREE_HOOK_MIN = (2, 1, 50)


def worktree_hook_version_ok(version: str | None) -> bool:
    """Whether a Claude Code of this version has the WorktreeCreate event: CLAUDE_WORKTREE_HOOK_MIN
    or later, read as the sandbox gate reads it; an unknown or unreadable version is not."""
    return claude_at_least(version, CLAUDE_WORKTREE_HOOK_MIN)


def claude_at_least(version: str | None, minimum: tuple[int, int, int]) -> bool:
    """Whether a probed Claude Code version is `minimum` or later. Only a SemVer version counts;
    a prerelease sorts before its release (SemVer §11); build metadata does not count."""
    match = _RELEASE.fullmatch(version or "")
    if match is None:
        return False
    release = tuple(int(part) for part in match.groups()[:3])
    if match.group(4) is not None:  # a prerelease of `release`
        return release > minimum
    return release >= minimum


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
    """`test` on the agents' side; anything but a clear yes or no is an OSError. On the
    runner's own side `AsUser.exists` already raises for a path it cannot look at (stat, not
    pathlib's predicates, which stop raising from Python 3.14; tsk-0tje3vzzedtx)."""
    if as_user.direct:
        return as_user.exists(path, kind)
    done = as_user.run(["test", kind, str(path)])
    if done.returncode not in (0, 1):
        raise OSError(f"{path} cannot be checked (exit {done.returncode})")
    return done.returncode == 0


def _claude_settings_files(
    as_user: AsUser, platform: str | None
) -> list[tuple[Path, bool, Path]] | str:
    """The Claude Code settings files the agents' Claude Code merges: the managed settings (the
    file, and each `*.json` in `managed-settings.d/` beside it), then the agents' user's own.
    Each with whether it is managed and the directory it is read from (limitread). A string
    says why they cannot be listed."""
    if as_user.here:
        platform = sys.platform if platform is None else platform
    else:
        platform = "linux"
    managed = next((p for key, p in CLAUDE_MANAGED.items() if platform.startswith(key)), None)
    files: list[tuple[Path, bool, Path]] = []
    try:
        if managed is not None:
            if _present(as_user, managed):
                files.append((managed, True, managed.parent))
            drop_ins = managed.parent / "managed-settings.d"
            if _present(as_user, drop_ins, "-d"):
                done = as_user.run(["sh", "-c", _DROP_INS, "sh", str(drop_ins)])
                if done.returncode != 0:
                    return f"{drop_ins} cannot be listed"
                listed = sorted(done.stdout.splitlines())
                files += [(Path(line), True, managed.parent) for line in listed]
        home = as_user.home()
        user = home / ".claude" / "settings.json"
        if _present(as_user, user):
            files.append((user, False, home))
    except (OSError, KeyError) as exc:
        return f"the Claude Code settings cannot be checked ({ascii_text(str(exc), 120)})"
    return files


def _settings_object(as_user: AsUser, path: Path, under: Path) -> dict[str, Any] | str:
    """A settings file as a JSON object, or why it is none."""
    try:
        data = json.loads(as_user.read_whole(path, SETTINGS_MAX, under=under))
    except (OSError, KeyError, ValueError):
        return f"{path} cannot be read as JSON"
    if not isinstance(data, dict):
        return f"{path} is not a JSON object"
    return data


def claude_hooks_off(as_user: AsUser = RUNNER, platform: str | None = None) -> str | None:
    """Why the runner's hook would not run for the agents' Claude Code, or None. Managed
    settings (the file, and each `*.json` in `managed-settings.d/` beside it) that set
    `disableAllHooks` or `allowManagedHooksOnly`, or that cannot be read as JSON: unknown
    counts as off. In the agents' user settings only `allowManagedHooksOnly` counts; the
    runner's own settings file sets `disableAllHooks` back to false over theirs."""
    files = _claude_settings_files(as_user, platform)
    if isinstance(files, str):
        return files
    for path, is_managed, under in files:
        data = _settings_object(as_user, path, under)
        if isinstance(data, str):
            return data
        switches = HOOK_SWITCHES if is_managed else ("allowManagedHooksOnly",)
        on = [key for key in switches if data.get(key) is not False and key in data]
        if on:
            return f"{path} sets {' and '.join(on)}"
    return None


# The settings that decide which Unix sockets a sandboxed command may open. The placement's
# settings file pins `allowAllUnixSockets` off (adapters.claude_settings); the agents' user's
# own settings are merged in (`--setting-sources user`) and the managed settings win over the
# placement's file, so a start is refused while either carries any of these, whatever the
# value (cli/context/runner.md).
SOCKET_SETTINGS = (
    ("sandbox", "network", "allowAllUnixSockets"),
    ("sandbox", "network", "allowUnixSockets"),
    ("sandbox", "seccompConfig"),
)


def claude_socket_settings(as_user: AsUser = RUNNER, platform: str | None = None) -> str | None:
    """Why the managed or the agents' user's Claude Code settings could change the placement's
    socket settings, or None: a file carries a key of SOCKET_SETTINGS, or cannot be listed or
    read as a JSON object (unknown counts as set, as for the hook switches)."""
    files = _claude_settings_files(as_user, platform)
    if isinstance(files, str):
        return files
    for path, _, under in files:
        data = _settings_object(as_user, path, under)
        if isinstance(data, str):
            return data
        found = []
        for keys in SOCKET_SETTINGS:
            node: Any = data
            for key in keys[:-1]:
                node = node.get(key) if isinstance(node, dict) else None
            if isinstance(node, dict) and keys[-1] in node:
                found.append(".".join(keys))
        if found:
            return f"{path} sets {' and '.join(found)}"
    return None


def claude_socket_settings_line(why: str) -> str:
    """Why a sandboxed Claude Code agent is not started, for `check` and the log."""
    return (f"harness claude-code: {why}; the placement pins its Unix socket settings and"
            " takes none from the managed or the user's settings, so its sandboxed agents are"
            " not started until the setting is removed")  # fmt: skip


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


def probe(
    harness: config.Harness,
    agent_path: str,
    as_user: AsUser = RUNNER,
    tools_dir: Path | None = None,
) -> Probe:
    """Resolve the harness binary on `agent_path` and read its version, as the agents' user:
    a binary that user cannot run is not available, whatever the runner can run. A tool the
    runner manages (§15.16) is never looked up on the PATH: the version new sessions start
    with, from `tools_dir`, or none."""
    if harness.id == "stub":
        return Probe(None, None, None)
    if tools_dir is not None and (harness.install or harness.update != "never"):
        managed = tools.binary(tools_dir, harness.id)
        found = str(managed) if managed is not None else None
    else:
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
    harness: config.Harness,
    path: str | None = None,
    as_user: AsUser = RUNNER,
    tools_dir: Path | None = None,
) -> bool:
    """Whether the harness's own OS sandbox can be switched on for the agents: Claude Code's
    needs its tools (`claude_sandbox_tools`, §6.1) found on the agents' PATH. Codex's is
    tried once per binary (`codex sandbox -- true`): a host where it cannot start is not
    advertised as sandboxed. agy's is reported off until the runner has a bounded check
    that sees agy's own sandbox start (§15.3, `agy_sandbox`). Nothing else is switched on
    yet. A Codex the runner manages (§15.16) is tried as the binary its sessions start with,
    from `tools_dir`, never one the PATH finds, as `probe` does."""
    if harness.id == "codex":
        if tools_dir is not None and (harness.install or harness.update != "never"):
            managed = tools.binary(tools_dir, harness.id)
            binary = str(managed) if managed is not None else None
        else:
            binary = which(harness.binary or "codex", path, as_user)
        return binary is not None and _codex_sandbox_starts(binary, as_user.user)
    if harness.id == "antigravity":
        return False  # not seen starting: the namespaces it needs are a diagnostic only
    needed = claude_sandbox_tools()
    if harness.id != "claude-code" or needed is None:
        return False
    return all(which(tool, path, as_user) for tool in needed)


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


# agy's terminal sandbox on Linux runs each command in kernel namespaces of its own, which
# needs unprivileged user namespaces; where they are blocked agy runs the command without it,
# and without saying so (§15.3). The contract reports the sandbox on only once the runner has
# seen agy's sandbox start, and agy has no command that starts its sandbox alone (as `codex
# sandbox` does) while a headless run costs the operator's model quota and needs the sign-in.
# So the capability stays off (`sandbox_available`), and the runner only tries the namespaces
# agy's sandbox needs, as the agents' user: user, mount, pid and network. That they start says
# agy's sandbox could, never that it did (cli/context/runner.md).
AGY_NAMESPACES = ("--user", "--map-root-user", "--mount", "--pid", "--fork", "--net", "true")
# Where those namespaces are refused, agy may still get its own: AppArmor's restriction of
# unprivileged user namespaces (Ubuntu) is lifted per profile, and an operator can load one for
# agy that grants `userns`. An unprivileged process cannot run the probe under that profile (it
# only stacks it, `agy//&unconfined`, and stays restricted), and a profile's `attach` reads
# `<unknown>` without privilege, so only the names of the loaded profiles can be read
# (tsk-xjy2d5617sar, cli/context/runner.md).
APPARMOR_PROFILES = "/sys/kernel/security/apparmor/policy/profiles"
AGY_PROFILE_NAME = "agy"
# What `agy_sandbox` answers: the namespaces start; the mapping write is refused but a profile
# named for agy is loaded (not verified); the mapping write is refused and nothing lifts that;
# the unshare call itself is refused, which no profile for agy lifts; it cannot tell.
AGY_STARTS, AGY_PROFILE, AGY_CANNOT, AGY_UNKNOWN = "starts", "profile", "cannot", "unknown"
AGY_REFUSED = "refused"
# The answers that say agy runs its commands unsandboxed there: `check` reports an error, and a
# start that `require_sandbox` lets through says so in the log.
AGY_UNSANDBOXED = (AGY_CANNOT, AGY_REFUSED)
# A refusal of the namespaces, one whole line of stderr as unshare words it under LC_ALL=C: the
# mapping write AppArmor's userns restriction refuses (a profile granting agy `userns` lifts
# that), or the unshare call itself (the kernel or a container's seccomp refuses user
# namespaces, which a profile for agy does not lift). Any other line beside it, or any other
# failure (a translated message, ENOMEM, ENOSPC, EINVAL), tells nothing (the review of #2119).
_MAPPING_REFUSED = re.compile(
    r"(?:unshare: )?write failed /proc/self/(?:uid_map|gid_map|setgroups): "
    r"Operation not permitted"
)
# util-linux's unshare reports its own failure, a refused call or write included, with this
# status (`err()`, EXIT_FAILURE); a refusal is read from stderr only then.
UNSHARE_FAILED = 1
_UNSHARE_REFUSED = re.compile(r"(?:unshare: )?unshare failed: Operation not permitted")
# Every command of the probe is looked up here, never on the agents' PATH, which a directory
# they can write to could hold: an unshare of theirs that exits 0 would hide the error, and a
# `realpath` or `cat` of theirs could name any profile (the review of #2119).
SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_SYSTEM_ENV = {"PATH": SYSTEM_PATH, "LC_ALL": "C"}
# As the agents' user: 3 no AppArmor (a part of the path is missing under a directory that can
# be searched), 4 the list cannot be read (a part cannot be reached, or is no directory), 5 a
# name unreadable. Every entry is listed, hidden ones too, as `os.listdir` does on the direct
# side, so an entry whose name cannot be read is never skipped unseen (the review of #2119).
_PROFILE_NAMES = (
    "d=$1; p=; r=${d#/}; "
    "while :; do c=${r%%/*}; p=$p/$c; "
    'if [ ! -e "$p" ] && [ ! -L "$p" ]; then q=${p%/*}; '
    '[ -d "${q:-/}" ] && [ -x "${q:-/}" ] && exit 3; exit 4; fi; '
    '[ "$r" = "$c" ] && break; r=${r#*/}; done; '
    '[ -d "$d" ] && [ -r "$d" ] && [ -x "$d" ] || exit 4; rc=0; '
    'for e in "$d"/* "$d"/.[!.]* "$d"/..?*; do [ -e "$e" ] || [ -L "$e" ] || continue; '
    'if [ -r "$e/name" ] && n=$(cat -- "$e/name"); then printf \'%s\\n\' "$n"; else rc=5; fi; '
    "done; exit $rc"
)


def agy_sandbox_platform(platform: str | None = None) -> bool:
    """Where the runner knows what agy's sandbox needs: Linux only."""
    return (sys.platform if platform is None else platform).startswith("linux")


def unshare_refusal(stderr: str) -> str | None:
    """Which refusal unshare's `stderr` is: `AGY_CANNOT` for the mapping write, `AGY_REFUSED`
    for the unshare call; None for anything else. It must be exactly one line, a recognised
    one, so a refusal beside another failure is not read as the refusal alone (#2119)."""
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if len(lines) != 1:
        return None
    if _MAPPING_REFUSED.fullmatch(lines[0]):
        return AGY_CANNOT
    if _UNSHARE_REFUSED.fullmatch(lines[0]):
        return AGY_REFUSED
    return None


def agy_sandbox(as_user: AsUser = RUNNER, binary: str | None = None) -> str:
    """Whether agy's terminal sandbox can start for the agents' user, as far as an unprivileged
    check can tell (`AGY_*`): the namespaces it needs start (`unshare`); the mapping write is
    refused but an AppArmor profile named `agy`, or after agy's `binary` as found or with its
    symlinks resolved, is loaded, which may lift the refusal for agy (not verified); the
    mapping write is refused and no such profile is loaded, so agy runs commands unsandboxed;
    the unshare call itself is refused, by the kernel or a container, which no profile for agy
    lifts; or it cannot tell (no `unshare`, a failure of the lookup or the run, a failure that
    is no permission refusal or comes with other lines, the profile list unreadable or read
    only in part, agy's path not resolvable). It never turns the capability on. Only a
    definite refusal is `cannot` or `refused`, `cannot` with a complete list only, so the
    check can only err towards a warning. Every command runs with `SYSTEM_PATH`, never the
    agents' PATH (the review of #2119)."""
    try:
        unshare = which("unshare", SYSTEM_PATH, as_user)
        if unshare is None:
            return AGY_UNKNOWN
        done = as_user.run([unshare, *AGY_NAMESPACES], env=dict(_SYSTEM_ENV),
                           cwd=Path.home() if as_user.direct else None, timeout=30)  # fmt: skip
    except (proc.ToolError, subprocess.SubprocessError, OSError, ValueError):
        return AGY_UNKNOWN
    if done.returncode == 0:
        return AGY_STARTS
    if done.returncode != UNSHARE_FAILED:
        # A signal (negative), ssh's transport error (255) or any other code is no refusal
        # unshare reported, whatever stderr holds (the review of #2119). sudo's own refusal
        # exits 1 too; its line is no unshare refusal line, so unshare_refusal turns it away.
        return AGY_UNKNOWN
    refusal = unshare_refusal(done.stderr or "")
    if refusal is None:
        return AGY_UNKNOWN
    if refusal == AGY_REFUSED:
        return AGY_REFUSED  # refused before AppArmor's userns rule is asked: no profile lifts it
    listed = apparmor_profiles(as_user)
    if listed is None:
        return AGY_UNKNOWN
    names, complete = listed
    if names & {AGY_PROFILE_NAME, *([binary] if binary else [])}:
        return AGY_PROFILE
    if binary:
        # A profile without a name of its own is named after the path it attaches to, agy's
        # real one; `which` gives the path on the PATH, maybe a symlink (the review of #2119).
        real = resolved(binary, as_user)
        if real in names:
            return AGY_PROFILE
        complete = complete and real is not None  # its real path's profile not looked for
    return AGY_CANNOT if complete else AGY_UNKNOWN  # an unread name may be agy's


def resolved(path: str, as_user: AsUser = RUNNER) -> str | None:
    """`path` with every symlink resolved, as the agents' user sees it (on an ssh host, there);
    None where it cannot be (gone, unreadable, no `realpath`)."""
    try:
        if as_user.direct:
            return os.path.realpath(path, strict=True)
        # -e: every part must exist, as `strict=True` asks on the direct side (#2119).
        done = as_user.run(["realpath", "-e", "--", path], env=dict(_SYSTEM_ENV), timeout=30)
    except (proc.ToolError, subprocess.SubprocessError, OSError, ValueError):
        return None
    real = (done.stdout or "").strip()
    return real if done.returncode == 0 and real else None


def apparmor_profiles(as_user: AsUser = RUNNER) -> tuple[set[str], bool] | None:
    """The names of the loaded AppArmor profiles, as the agents' user reads them, and whether
    every one could be read: (empty, True) where there is no AppArmor, None where the list
    cannot be read at all."""
    if as_user.direct:
        try:
            entries = os.listdir(APPARMOR_PROFILES)
        except FileNotFoundError:
            return set(), True
        except OSError:
            return None
        names: set[str] = set()
        complete = True
        for entry in entries:
            try:
                text = Path(APPARMOR_PROFILES, entry, "name").read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                complete = False
                continue
            names.add(text.strip())
        return names, complete
    try:
        done = as_user.run(["sh", "-c", _PROFILE_NAMES, "sh", APPARMOR_PROFILES],
                           env=dict(_SYSTEM_ENV), timeout=30)  # fmt: skip
    except (proc.ToolError, subprocess.SubprocessError, OSError, ValueError):
        return None
    if done.returncode == 3:
        return set(), True
    if done.returncode not in (0, 5):
        return None
    found = {line.strip() for line in (done.stdout or "").splitlines() if line.strip()}
    return found, done.returncode == 0


# The flags the opencode adapter passes (adapters._opencode), by the command that must take
# them: the TUI (no subcommand) for an interactive placement, `run` for a supervised one.
# OpenCode 2.3 dropped `--model` from the TUI, and every interactive start exited on it; its
# `run` has no `--dir` (tsk-daa6e0gfncg0). `maity runner check` reads each command's `--help`
# for these, so the next such change shows before a start (cli/context/runner.md, the opencode
# model fail-closed).
OPENCODE_FLAGS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "interactive": ((), ("--standalone", "--prompt")),
    "supervised": (("run",), ("--model", "--continue")),
}


def opencode_missing_flags(
    binary: str, path: str, modes: tuple[str, ...], as_user: AsUser = RUNNER
) -> dict[str, tuple[str, ...] | None]:
    """A diagnostic for `maity runner check`: per mode of `modes`, the OPENCODE_FLAGS its
    command's `--help` does not name, as the agents' user; None where the help could not be
    read (a failed or timed-out call). It starts no session and needs no sign-in."""
    missing: dict[str, tuple[str, ...] | None] = {}
    for mode in modes:
        if mode not in OPENCODE_FLAGS:
            continue
        command, flags = OPENCODE_FLAGS[mode]
        try:
            done = as_user.run([binary, *command, "--help"], env={"PATH": path, "LC_ALL": "C"},
                               timeout=VERSION_TIMEOUT)  # fmt: skip
        except (subprocess.TimeoutExpired, OSError):
            missing[mode] = None
            continue
        text = f"{done.stdout or ''}\n{done.stderr or ''}"
        if done.returncode != 0 or not text.strip():
            missing[mode] = None
            continue
        missing[mode] = tuple(
            flag for flag in flags if not re.search(rf"(?<![\w-]){re.escape(flag)}(?![\w-])", text)
        )
    return missing


# Claude Code's Linux sandbox runs each command under bubblewrap in a user namespace, and its
# seccomp step (`apply-seccomp`) opens a second user namespace inside that one and maps the user
# there. Ubuntu (seen on 26.04) ships the AppArmor profile `bwrap-userns-restrict`, which denies
# every capability to what bwrap starts: the nested step then fails ("write /proc/self/setgroups
# ... caller must provide CAP_SYS_ADMIN") and so does every sandboxed command, a subagent's
# included, while the session itself starts. Checking bwrap and socat alone says nothing about
# it, so `maity runner check` starts the same nesting once (cli/context/runner.md).
CLAUDE_NESTED_USERNS = ("--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc",
                        "--unshare-user", "--unshare-pid", "--")  # fmt: skip
# The refusal itself: unshare could create the inner namespace but not map the user in it.
# Read under LC_ALL=C, so the message is util-linux's English one.
NESTED_REFUSED = ("/proc/self/uid_map", "/proc/self/setgroups", "/proc/self/gid_map")


@dataclass(frozen=True)
class NestedUserns:
    """The nested-namespace probe's answer: `ok`, `refused` (the mapping inside bubblewrap was
    denied, the one outcome that means sandboxed commands fail), `inconclusive` (the probe
    could not tell: a timeout, a launch error, another failure) or `missing` (a tool is not
    on the agents' PATH). `detail` says which, for `check`'s line."""

    outcome: str
    detail: str = ""


def claude_nested_userns(path: str, as_user: AsUser = RUNNER) -> NestedUserns:
    """A diagnostic for `maity runner check`, Linux only: whether a user namespace with the
    user mapped starts inside bubblewrap, as the agents' user, with their PATH and every
    command by its absolute path. It never changes a capability."""
    found = {name: which(name, path, as_user) for name in ("bwrap", "unshare", "true")}
    missing = [name for name, where in found.items() if where is None]
    if missing:
        return NestedUserns("missing", ", ".join(missing))
    argv = [str(found["bwrap"]), *CLAUDE_NESTED_USERNS, str(found["unshare"]),
            "--user", "--map-root-user", str(found["true"])]  # fmt: skip
    try:
        done = as_user.run(argv, env={"PATH": path, "LC_ALL": "C"}, timeout=30)
    except subprocess.TimeoutExpired:
        return NestedUserns("inconclusive", "the probe timed out")
    except OSError as exc:
        return NestedUserns("inconclusive", f"the probe did not start: {exc.strerror or exc}")
    if done.returncode == 0:
        return NestedUserns("ok")
    said = (done.stderr or "").strip().splitlines()
    last = ascii_text(said[-1], 160) if said else f"exit {done.returncode}"
    if done.returncode == 1 and any(mark in (done.stderr or "") for mark in NESTED_REFUSED):
        return NestedUserns("refused", last)
    return NestedUserns("inconclusive", last)


# Claude Code's Linux sandbox keeps a sandboxed command from opening any Unix socket with a
# seccomp step (`apply-seccomp`, built into the binary) inside bubblewrap. Every placement runs
# as the same OS user, so that step is what keeps one placement's commands away from another
# placement's sockets; read-only paths do not stop a connect. Where the step cannot run, Claude
# Code still runs the command in bubblewrap, with Unix sockets open, and `failIfUnavailable`
# does not catch it (it covers the sandbox as a whole). Its warning then goes to a debug log
# that writes nothing by default, so nothing a session shows says so. The runner therefore
# checks, before a sandboxed Claude Code placement starts and in `check`, what the step needs
# from the host: a machine Claude Code ships the helper for (CLAUDE_SECCOMP_ARCHES) and a kernel
# with seccomp filtering. Linux only: Seatbelt (macOS) has no such step. On a supported machine
# the step still depends on Claude Code handing in its built-in helper, which this does not
# see and `check`'s headless probe does (`claude_socket_probe`, cli/context/runner.md).
# `uname -m` as Claude Code names the machine, compared in lower case; any other name is no
# supported machine, Claude Code's own names included.
SECCOMP_MACHINES = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}
PROC_STATUS = Path("/proc/self/status")
# `Seccomp:` is in a task's status with CONFIG_SECCOMP, `Seccomp_filters:` with
# CONFIG_SECCOMP_FILTER from Linux 5.9 on; before 5.9 only the first one can be read. Their
# values are the task's own mode and filter count (0 for an unconfined shell): only whether
# the lines are there says what the kernel supports.
SECCOMP_FILTERS_FROM = (5, 9)
# Bytes outside printable ASCII in the status (a task's name may hold any) become `?` on the
# agents' side, as `errors="replace"` does for a direct read: only the ASCII keys are read.
_SECCOMP_HOST = "uname -m && uname -r && LC_ALL=C tr -c '\\11\\12\\40-\\176' '?' < \"$1\""
_RELEASE_HEAD = re.compile(r"(\d+)\.(\d+)")


@dataclass(frozen=True)
class ClaudeSeccomp:
    """The seccomp preflight's answer: `ok`, `unsupported_arch` (no helper is shipped for the
    machine), `no_seccomp` (the kernel has no seccomp filtering) or `inconclusive` (what it
    needs could not be read). Only `ok` starts a sandboxed Claude Code placement. `arch` is
    the machine as Claude Code names it; `detail` says why, for `check` and the log."""

    outcome: str
    arch: str = ""
    detail: str = ""


def claude_seccomp_applies(as_user: AsUser = RUNNER, platform: str | None = None) -> bool:
    """Where Claude Code's sandbox has the seccomp step: Linux, which every ssh host is; not
    under Seatbelt."""
    if not as_user.here:
        return True
    return (sys.platform if platform is None else platform).startswith("linux")


def _seccomp_host(as_user: AsUser) -> tuple[str, str, str] | None:
    """The machine, the kernel release and a task's status, as the agents' user sees them;
    None when they cannot be read."""
    if as_user.direct:
        try:
            status = PROC_STATUS.read_text(encoding="utf-8", errors="replace")
            return _platform.machine(), _platform.release(), status
        except OSError:
            return None
    try:
        done = as_user.run(["sh", "-c", _SECCOMP_HOST, "sh", str(PROC_STATUS)],
                           timeout=VERSION_TIMEOUT)  # fmt: skip
    except (OSError, subprocess.TimeoutExpired, UnicodeDecodeError):
        return None
    lines = done.stdout.split("\n", 2)
    if done.returncode != 0 or len(lines) < 3:
        return None
    return lines[0], lines[1], lines[2]


def claude_seccomp(as_user: AsUser = RUNNER) -> ClaudeSeccomp:
    """Whether the host gives Claude Code's seccomp step what it needs, as the agents' user:
    a machine in CLAUDE_SECCOMP_ARCHES, and a kernel that has seccomp (`Seccomp:` in
    /proc/self/status) with filters (`Seccomp_filters:`, from Linux 5.9 on). Anything that
    cannot be read is `inconclusive`, which starts nothing either."""
    host = _seccomp_host(as_user)
    if host is None:
        return ClaudeSeccomp("inconclusive", detail=f"{PROC_STATUS} or uname could not be read")
    machine, release, status = (part.strip() for part in host)
    if not machine:
        return ClaudeSeccomp("inconclusive", detail="uname gave no machine")
    arch = SECCOMP_MACHINES.get(machine.lower())
    if arch is None or arch not in CLAUDE_SECCOMP_ARCHES:
        named = ascii_text(machine, 40)
        return ClaudeSeccomp("unsupported_arch", arch or named, f"machine {named}")
    fields = dict(
        (key.strip(), value.strip())
        for key, sep, value in (line.partition(":") for line in status.splitlines())
        if sep
    )
    if "Seccomp" not in fields:
        return ClaudeSeccomp("no_seccomp", arch, f"no Seccomp line in {PROC_STATUS}")
    if not fields["Seccomp"].isdigit():
        return ClaudeSeccomp("inconclusive", arch, f"an unreadable Seccomp line in {PROC_STATUS}")
    if "Seccomp_filters" in fields:
        if not fields["Seccomp_filters"].isdigit():
            return ClaudeSeccomp(
                "inconclusive", arch, f"an unreadable Seccomp_filters line in {PROC_STATUS}"
            )
        return ClaudeSeccomp("ok", arch)
    head = _RELEASE_HEAD.match(release)
    if head is None:
        return ClaudeSeccomp("inconclusive", arch, f"kernel release {ascii_text(release, 40)!r}")
    if (int(head.group(1)), int(head.group(2))) >= SECCOMP_FILTERS_FROM:
        return ClaudeSeccomp("no_seccomp", arch, f"no Seccomp_filters line in {PROC_STATUS}")
    return ClaudeSeccomp("ok", arch)


def claude_seccomp_line(found: ClaudeSeccomp) -> str:
    """Why sandboxed Claude Code placements are not started on a host, for `check` and the log.
    No `sandbox` in it: `check`'s sandbox line is the one that names the sandbox."""
    if found.outcome == "unsupported_arch":
        why = (f"Claude Code ships no seccomp helper for {found.arch} ({found.detail}), so its "
               "commands would run with Unix sockets open")  # fmt: skip
    elif found.outcome == "no_seccomp":
        why = (f"the kernel has no seccomp filtering ({found.detail}), so its commands would "
               "run with Unix sockets open")  # fmt: skip
    else:
        why = f"whether the seccomp step can run could not be read ({found.detail})"
    return f"harness claude-code: {why}; its placements are not started"


# The static preflight above sees what the host gives the seccomp step, not whether Claude Code
# hands its built-in helper in. `maity runner check` (never a placement start: it spends one
# small prompt on the agents' Claude login) therefore runs the installed Claude Code once
# headless, with the sandbox on as a placement has it (socket blocking on, no
# allowAllUnixSockets) and the sandbox runtime's debug log on, and reads its standard error
# for the runtime's own lines. Only these lines are kept, never the model's answer.
SOCKET_PROBE_APPLIED = "Applying seccomp filter for Unix socket blocking"
SOCKET_PROBE_MISSING = "apply-seccomp binary not available"
SOCKET_PROBE_COMMAND = "echo maity-socket-probe"
SOCKET_PROBE_PROMPT = (
    f"Run exactly this one shell command with the Bash tool, then stop: {SOCKET_PROBE_COMMAND}"
)
SOCKET_PROBE_SETTINGS = {
    "permissions": {"allow": [f"Bash({SOCKET_PROBE_COMMAND})"], "defaultMode": "dontAsk"},
    "sandbox": {"enabled": True, "failIfUnavailable": True, "allowUnsandboxedCommands": False,
                "autoAllowBashIfSandboxed": False, "network": {"allowAllUnixSockets": False}},
}  # fmt: skip
SOCKET_PROBE_TIMEOUT = 180


@dataclass(frozen=True)
class SocketProbe:
    """The headless probe's answer: `ok` (the runtime applied the filter), `off` (it found no
    helper, so Unix sockets stay open) or `inconclusive` (a timeout, a launch error, a non-zero
    exit, neither line: a missing login among them). `detail` says which."""

    outcome: str
    detail: str = ""


def claude_socket_probe(binary: str, path: str, as_user: AsUser = RUNNER) -> SocketProbe:
    """One headless Claude Code run as the agents' user, Linux only, for `maity runner check`:
    whether its sandbox applies the seccomp filter that blocks Unix sockets. Never at a start."""
    argv = [binary, "--setting-sources", "user",
            "--settings", json.dumps(SOCKET_PROBE_SETTINGS, separators=(",", ":")),
            "--permission-mode", "dontAsk",
            "--strict-mcp-config", '--mcp-config={"mcpServers":{}}',
            "-p", SOCKET_PROBE_PROMPT]  # fmt: skip
    env = {"PATH": path, "SRT_DEBUG": "1", "DISABLE_UPDATES": "1",
           "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"}  # fmt: skip
    try:
        done = as_user.run(argv, env=env, cwd=Path.home() if as_user.direct else None,
                           timeout=SOCKET_PROBE_TIMEOUT)  # fmt: skip
    except subprocess.TimeoutExpired:
        return SocketProbe("inconclusive", f"no answer within {SOCKET_PROBE_TIMEOUT} s")
    except OSError as exc:
        return SocketProbe("inconclusive", f"Claude Code did not start: {exc.strerror or exc}")
    except ValueError:  # UnicodeDecodeError included: output that is not text
        return SocketProbe("inconclusive", "Claude Code's output could not be read")
    if not isinstance(done.stderr, str | None):
        return SocketProbe("inconclusive", "Claude Code's output could not be read")
    said = (done.stderr or "").splitlines()
    if any(SOCKET_PROBE_MISSING in line for line in said):
        return SocketProbe("off", "Claude Code found no seccomp helper")
    if done.returncode != 0:
        return SocketProbe("inconclusive", f"Claude Code exited {done.returncode} (its login?)")
    if any(SOCKET_PROBE_APPLIED in line for line in said):
        return SocketProbe("ok")
    return SocketProbe("inconclusive", "the debug log named neither outcome")


# The Claude Code version whose probe last passed, per target, in the state directory: `check`
# writes it, the service reads it at each sandboxed Claude Code start and only warns when the
# installed version differs (the runner installs Claude Code itself; cli/context/runner.md).
PROBE_FILE = "claude-probe.json"


def probe_passed(state_dir: Path, target: str) -> str | None:
    """The version whose probe last passed on `target`, or None (none recorded, or the record
    cannot be read: that only warns)."""
    try:
        found = state.load_state(state_dir, name=PROBE_FILE).get(target)
    except (state.StateError, OSError):
        return None
    return found if isinstance(found, str) else None


def record_probe(state_dir: Path, target: str, version: str | None) -> None:
    """Keep `version` as the one whose probe passed on `target`; None forgets it (the probe
    did not pass). OSError and StateError reach the caller."""
    data = state.load_state(state_dir, name=PROBE_FILE)
    if version is None:
        if data.pop(target, None) is None:
            return
    else:
        data[target] = version
    state.save_state(state_dir, data, name=PROBE_FILE)


def probe_stale_line(passed: str | None, installed: str | None) -> str | None:
    """The warning for a start or `check` whose installed Claude Code is not the one whose
    probe last passed on that target, or None."""
    if passed is not None and passed == installed:
        return None
    before = f"last passed with {passed}" if passed else "has not passed on this target"
    return (f"harness claude-code: the Unix socket probe {before}, installed "
            f"{installed or 'an unknown version'}; run `maity runner check`")  # fmt: skip


def agy_login(as_user: AsUser = RUNNER) -> Path:
    """Where agy keeps its sign-in for the agents' user without a keyring (never read)."""
    return as_user.home() / ".gemini" / "antigravity-cli" / "antigravity-oauth-token"


def agent_path(cfg: config.Config, environ_path: str) -> str:
    return (cfg.local.agent_path if cfg.local else None) or environ_path


def harness_entry(
    harness: config.Harness,
    found: Probe,
    path: str | None = None,
    targets: list[str] | None = None,
    sandbox: bool | None = None,
    as_user: AsUser = RUNNER,
    tools_dir: Path | None = None,
) -> dict[str, Any]:
    if sandbox is None:
        sandbox = sandbox_available(harness, path, as_user, tools_dir) and sandbox_version_ok(
            harness.id, found.version
        )
    on = sandbox
    entry: dict[str, Any] = {
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
    if harness.efforts:
        # Only when configured: a hub from before `efforts` refuses the key in a strict
        # hello, so a runner without efforts sends exactly what that hub takes (§15.3).
        entry["efforts"] = list(harness.efforts)
    return entry


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
    # `running` (top-level and per target) is the starting count; the supervisor refreshes both
    # after every `PATCH /runner`, so each target begins at 0 like the ssh ones, not at the total.
    return {
        "backend": cfg.backend,
        "max_agents": limits.max_agents,
        "running": running,
        "targets": [
            {
                "name": "local",
                "max_agents": limits.max_agents,
                "running": 0,
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
                          as_user=AsUser(agents_user), tools_dir=cfg.tools_dir)  # fmt: skip
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
