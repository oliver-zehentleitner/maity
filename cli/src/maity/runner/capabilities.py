"""What the runner advertises to the hub (docs/api.md §15.3, §15.8).

Advertised, never granted: the hub shows it for choosing and checks placements against it,
and the runner checks every placement against its own configuration again. Every string is
printable ASCII of at most 200 characters.
"""

from __future__ import annotations

import getpass
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import proc
from . import config

VERSION_TIMEOUT = 10.0
_VERSION = re.compile(r"\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.]+)?")
_UNPRINTABLE = re.compile(r"[^\x20-\x7e]")


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


def probe(harness: config.Harness, agent_path: str) -> Probe:
    """Resolve the harness binary on `agent_path` and read its version."""
    if harness.id == "stub":
        return Probe(None, None, None)
    found = shutil.which(harness.binary or "", path=agent_path)
    if found is None:
        return Probe(None, None, "binary_not_found")
    try:
        done = proc.run([found, "--version"], cwd=Path.home(), timeout=VERSION_TIMEOUT)
    except proc.ToolError:
        return Probe(found, None, "version_failed")
    lines = (done.stdout or done.stderr).strip().splitlines()
    if done.returncode != 0 or not lines:
        return Probe(found, None, "version_failed")
    match = _VERSION.search(lines[0])
    return Probe(found, ascii_text(match.group(0) if match else lines[0], 80), None)


def agent_path(cfg: config.Config, environ_path: str) -> str:
    return (cfg.local.agent_path if cfg.local else None) or environ_path


def harness_entry(harness: config.Harness, found: Probe) -> dict[str, Any]:
    return {
        "id": harness.id,
        "version": found.version,
        "available": found.available,
        "reason": found.reason,
        "modes": list(harness.modes),
        "default_mode": harness.default_mode,
        "models": [ascii_text(m) for m in harness.models],
        "targets": ["local"],
        "confinement": "none" if harness.id == "stub" else "allowlist",
        # No adapter switches a harness's own OS sandbox on yet (R5); claiming it would be a lie.
        "sandbox": "n/a" if harness.id == "stub" else "off",
    }


def build(cfg: config.Config, probes: dict[str, Probe], running: int = 0) -> dict[str, Any]:
    """The `capabilities` object of `hello` and `PATCH /runner`."""
    limits = cfg.limits
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
                    "kind": "shared_user",
                    "user": ascii_text(getpass.getuser()),
                    "runner_separate": False,
                },
            }
        ],
        "harnesses": [harness_entry(h, probes[h.id]) for h in cfg.harnesses.values()],
        "projects": list(limits.projects),
        "repositories": list(limits.repositories),
        "require_local_approval": limits.require_local_approval,
    }
