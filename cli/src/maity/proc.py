"""Running git and gh without ever waiting for a person.

An agent's harness may hand the command a terminal. A remote that answers 401 would then make
git or gh prompt for a username and hang until the harness kills it, so prompts are switched off,
stdin is closed, and every call has a timeout.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

TIMEOUT = 30.0
NO_PROMPT = {
    "GIT_TERMINAL_PROMPT": "0",  # git: no username/password prompt
    "GCM_INTERACTIVE": "never",  # Git Credential Manager: no dialog
    "GIT_ASKPASS": "",
    "SSH_ASKPASS": "",
    "GH_PROMPT_DISABLED": "1",  # gh: no interactive prompt
}


# Every git maity runs itself. A clone holds what an agent wrote: a nested repository it
# registered as a submodule carries its own configuration, which git reads for a plain
# `status` even when the clone's own is pinned. maity runs nothing from either.
# `os.devnull`: `/dev/null` on Windows is a path any user can create under the drive root.
GIT = (
    "git", "-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}",
    "-c", "diff.ignoreSubmodules=all",
)  # fmt: skip
# Transports git may use: the ones a forge remote uses, no remote helpers (`ext::`). An
# environment variable, not `-c protocol.allow`: a clone's own
# `protocol.<name>.allow` outranks that, and the variable outranks every configuration.
# A second line: what maity passes to git is checked first (gitfacts).
TRANSPORTS = "https:http:ssh:git:file"


class ToolError(Exception):
    """git or gh is missing, or did not answer in time."""


def allowed(transports: str) -> str:
    """`transports`, less any the environment's own `GIT_ALLOW_PROTOCOL` leaves out."""
    given = os.environ.get("GIT_ALLOW_PROTOCOL")
    if given is None:
        return transports
    theirs = set(given.split(":"))
    return ":".join(t for t in transports.split(":") if t in theirs)


def program(name: str) -> str | None:
    """The absolute path of `name` on PATH, or None. Only absolute PATH entries count, and
    never the current directory: Windows would otherwise start a `git.exe` lying in the
    directory maity runs in before the installed one. A name with a directory in it is a
    path the caller chose, used as given: on POSIX relative to the command's cwd, on Windows
    to maity's own current directory (how the OS resolves it)."""
    if os.path.isabs(name) or os.path.dirname(name):
        return name
    suffixes = [""]
    if os.name == "nt":
        listed = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD").split(os.pathsep)
        given = os.path.splitext(name)[1].lower()
        suffixes = ([""] if given else []) + [e for e in listed if e and not given]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        for suffix in suffixes:
            candidate = os.path.join(entry, name + suffix)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def run(
    cmd: list[str], cwd: Path, timeout: float = TIMEOUT, transports: str = TRANSPORTS
) -> subprocess.CompletedProcess[str]:
    """`transports`: what git may use, colon-separated; it replaces every protocol setting,
    a caller's narrower `-c protocol.*` included, so such a caller passes its own list. A
    `GIT_ALLOW_PROTOCOL` the operator set narrows it further, never the other way round."""
    env = {**os.environ, **NO_PROMPT, "GIT_ALLOW_PROTOCOL": allowed(transports)}
    if cmd[0] != "git":
        return _start(cmd, cwd, timeout, env)
    from maity import clonecheck  # imports onboarding, which imports this module

    try:
        with clonecheck.placement_git(cwd) as pinned:
            if pinned is None:
                return _start(cmd, cwd, timeout, env)
            kept = {**clonecheck.kept_env(os.environ), **NO_PROMPT}
            return _start(cmd, cwd, timeout, {**kept, "GIT_ALLOW_PROTOCOL": allowed(transports),
                                              **pinned.env}, pinned.git)  # fmt: skip
    except clonecheck.Refused as exc:
        raise ToolError(f"maity runs no git here: {exc}") from None


def _start(
    cmd: list[str], cwd: Path, timeout: float, env: dict[str, str], path: str | None = None
) -> subprocess.CompletedProcess[str]:
    """`path`: the program to start for `cmd[0]`, when the caller fixed it; else PATH's."""
    if os.name == "nt":
        # git and gh start programs of their own (ssh, credential helpers): not from cwd either.
        env["NoDefaultCurrentDirectoryInExePath"] = "1"
    path = path or program(cmd[0])
    if path is None:
        raise ToolError(f"{cmd[0]} is not installed")
    try:
        return subprocess.run(
            [path, *cmd[1:]],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            encoding="utf-8",  # what a file holds is not this machine's locale
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ToolError(f"{cmd[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"`{' '.join(cmd[:3])}` did not answer within {timeout:.0f}s") from exc
