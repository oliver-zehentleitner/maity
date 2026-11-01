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
GIT = (
    "git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
    "-c", "diff.ignoreSubmodules=all",
)  # fmt: skip


class ToolError(Exception):
    """git or gh is missing, or did not answer in time."""


def run(cmd: list[str], cwd: Path, timeout: float = TIMEOUT) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **NO_PROMPT}
    try:
        return subprocess.run(
            cmd,
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
