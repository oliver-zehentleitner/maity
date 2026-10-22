"""Harness adapters (runner design §6): what the runner starts for a placement.

An adapter turns a placement into a launch: the argv for tmux, the environment added to the
session's clean one, and the files it needs, written by the runner outside the workspace
(`<state_dir>/agents/<placement>/`) so the agent cannot change them. It takes nothing from
the hub but the validated tokens of the placement; the prompt is a fixed text.

`interactive`: the harness's own UI in the tmux pane, started with the prompt. `supervised`:
`maity.runner.loop` in the pane, which runs the harness headless on each event (§6.2); the
loop is the same for every harness and reads what to run from a spec file.

The project's own harness configuration is never loaded (§6.1): a committed settings file
could widen the grant, bring hooks or plugins, and change with a `git checkout`.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import state
from . import config, stub

START_PROMPT = (
    "This clone is a Maity project. Run `maity resume` now and follow it: your briefing "
    "comes first. Then work as `docs/agents.md` and the rules in the packet say."
)
# Supervised runs end with the turn: the loop starts the next one on the next event.
SUPERVISED_PROMPT = (
    START_PROMPT + " Handle what is waiting for you, checkpoint what you hold, then end your "
    "turn; do not run `maity wait`: you are started again on the next event."
)

# git subcommands an agent needs for project work. Not `git *`: options such as `-c`,
# `--config-env` or `--exec-path` run arbitrary programs, and `diff --no-index` reads any
# file, the clone's credential included. The list stops accidents and naive injection; the
# boundary is the OS user (and Claude Code's sandbox), see cli/context/runner.md.
GIT_SUBCOMMANDS = (
    "status", "diff", "log", "show", "add", "commit", "push", "pull", "fetch", "checkout",
    "switch", "branch", "merge", "rebase", "restore", "rm", "mv", "stash", "tag", "rev-parse",
    "ls-files", "blame", "grep", "remote -v", "config user.name", "config user.email",
)  # fmt: skip
GIT_DENIED = (
    "git -c *", "git --config-env*", "git --exec-path*", "git * --no-index*",
    "git * --upload-pack*", "git * --receive-pack*", "git * --exec=*", "git *.git/maity*",
)  # fmt: skip


READY = ("stub", "claude-code")  # harnesses with an adapter in this version


class NotYet(Exception):
    """This version has no adapter for the harness (or the mode) yet."""


@dataclass(frozen=True)
class Context:
    placement: dict[str, Any]
    harness: config.Harness
    binary: str | None  # the probed absolute path; None for stub
    clone: Path
    agent_dir: Path  # <state_dir>/agents/<placement>, the runner's, never the agent's
    grant: config.RepositoryGrant
    restart: config.Restart
    sandbox: bool = False  # the harness's own OS sandbox can be switched on here
    hosts: tuple[str, ...] = ()  # the hub's and the forge's, for network rules
    extra_env: dict[str, str] = field(default_factory=dict)  # e.g. declared machine ids


@dataclass(frozen=True)
class Launch:
    argv: list[str]
    env: dict[str, str]


def launch(ctx: Context) -> Launch:
    env = {"MAITY_PLACEMENT": ctx.placement["id"], **ctx.extra_env}
    harness = ctx.harness
    if harness.id == "stub":
        return Launch(stub.argv(harness.stub_exit_code, harness.stub_run_seconds), env)
    if harness.id == "claude-code":
        return _claude_code(ctx, env)
    raise NotYet(f"the {harness.id} adapter arrives with R5b")


def _write(path: Path, data: Any) -> Path:
    state.write_file(path, json.dumps(data, indent=2) + "\n")
    return path


def _supervised(ctx: Context, first: list[str], again: list[str], env: dict[str, str]) -> Launch:
    """The loop of §6.2 in the pane; what it runs comes from a spec file it cannot widen."""
    policy = ctx.restart
    spec = _write(
        ctx.agent_dir / "loop.json",
        {
            "first": first,
            "again": again,
            "env": env,
            "restart": {
                "initial": policy.initial, "factor": policy.factor, "max": policy.max,
                "crash_window": policy.crash_window, "crash_cap": policy.crash_cap,
                "quick_exit": policy.quick_exit,
            },
        },  # fmt: skip
    )
    return Launch([sys.executable, "-I", "-m", "maity.runner.loop", "--spec", str(spec)], env)


# --- Claude Code ------------------------------------------------------------------------------


def claude_settings(ctx: Context) -> dict[str, Any]:
    """The grant (§6.1): maity, git, the repository's own allow list, and file tools inside
    the clone only. Absolute paths take a double slash in Claude Code's rules. The clone's
    credential is neither readable nor writable through the file tools."""
    ws = str(ctx.clone)
    allow = ["Bash(maity *)", *(f"Bash(git {sub})" for sub in GIT_SUBCOMMANDS)]
    allow += [f"Bash(git {sub} *)" for sub in GIT_SUBCOMMANDS]
    allow += [f"Bash({cmd})" for cmd in ctx.grant.allow]
    allow += [f"{tool}(/{ws}/**)" for tool in ("Read", "Edit", "Write")]
    # Agents commit through git and never edit .git: its config and hooks would turn an
    # allowed `git status` into anything. The credential is not readable through Read.
    deny = [f"{tool}(/{ws}/.git/**)" for tool in ("Edit", "Write")]
    deny += [f"Read(/{ws}/.git/maity/**)"]
    deny += [f"Bash({rule})" for rule in GIT_DENIED]
    settings: dict[str, Any] = {
        "permissions": {"allow": allow, "deny": deny, "defaultMode": "dontAsk"},
    }
    if ctx.sandbox:
        settings["sandbox"] = {
            "enabled": True,
            "failIfUnavailable": True,  # never fall back to unsandboxed commands
            "allowUnsandboxedCommands": False,  # no dangerouslyDisableSandbox retry
            "autoAllowBashIfSandboxed": False,  # the allowlist above still decides
            "network": {"allowedDomains": sorted({*ctx.hosts, *ctx.grant.network}),
                        "strictAllowlist": True},
            # Repository code run by an allowed build or test command cannot read or replace
            # the clone's credential; `maity` alone, which signs with it, runs outside.
            "filesystem": {"denyRead": [f"{ws}/.git/maity"], "denyWrite": [f"{ws}/.git/maity"]},
            "excludedCommands": ["maity *"],
        }  # fmt: skip
    return settings


def _claude_code(ctx: Context, env: dict[str, str]) -> Launch:
    assert ctx.binary is not None  # noqa: S101 - the supervisor checked the probe
    settings = _write(ctx.agent_dir / "claude-settings.json", claude_settings(ctx))
    mcp = _write(ctx.agent_dir / "claude-mcp.json", {"mcpServers": {}})
    base = [
        ctx.binary,
        "--setting-sources", "user",  # the project's .claude/ is not loaded, hooks included
        "--settings", str(settings),
        "--permission-mode", "dontAsk",
        "--strict-mcp-config", "--mcp-config", str(mcp),
    ]  # fmt: skip
    model = ctx.placement.get("model")
    if model:
        base += ["--model", model]
    if ctx.placement.get("mode") == "interactive":
        return Launch([*base, START_PROMPT], env)
    # Headless: no background command may hold a run open past its turn (§6.2).
    quiet = {**env, "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"}
    return _supervised(
        ctx,
        [*base, "-p", SUPERVISED_PROMPT],
        [*base, "-p", SUPERVISED_PROMPT, "--continue"],
        quiet,
    )
