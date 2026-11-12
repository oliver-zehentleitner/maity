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
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__, clonecheck, proc
from . import config, stub, trust
from .asuser import AsUser

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
# `--config-env` or `--exec-path` run arbitrary programs. `diff` still reads a file outside
# the work tree without `--no-index` (`git diff /dev/null <path>`), so these lists stop
# accidents and naive injection only; the boundary is the harness's OS sandbox and the OS
# user, see cli/context/runner.md.
GIT_SUBCOMMANDS = (
    "status", "diff", "log", "show", "add", "commit", "push", "pull", "fetch", "checkout",
    "switch", "branch", "merge", "rebase", "restore", "rm", "mv", "stash", "tag", "rev-parse",
    "ls-files", "blame", "grep", "remote -v", "config user.name", "config user.email",
)  # fmt: skip
GIT_DENIED = (
    "git -c *", "git --config-env*", "git --exec-path*", "git * --no-index*",
    "git * --upload-pack*", "git * --receive-pack*", "git * --exec=*", "git *.git/maity*",
)  # fmt: skip


# What in a clone's .git redirects git's configuration, hooks or object sources: never
# written by the agent. Not everything that can make git run something: a rebase state
# (`rebase-merge/`) the agent wrote runs on `rebase --continue` (cli/context/runner.md). The
# rest of .git (refs, index, objects, logs, FETCH_HEAD) is what commit, fetch and push need
# between them: a commit writes the index, a fetch FETCH_HEAD, both refs, objects and logs.
# Not `commondir`: GIT_COMMON_DIR pins the session's git to the real .git (below),
# and the sandbox's guard on a missing commondir leaves git unable to read it at all.
# Verified on a sandboxed Claude Code run (cli/context/runner.md).
# Not `objects/info/http-alternates`: only a dumb-HTTP fetch reads it (the forge speaks smart
# HTTP), clonecheck refuses it with content, and a deny on a missing file would leave one
# more placeholder that was not seen in a sandboxed run.
GIT_PROTECTED = ("config", "config.worktree", "hooks", "info", "objects/info/alternates")

READY = ("stub", "claude-code", "codex", "opencode")  # harnesses with an adapter
SESSION_GIT_CONFIG = {
    "GIT_CONFIG_COUNT": "2",
    "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "false",
    "GIT_CONFIG_KEY_1": "diff.ignoreSubmodules", "GIT_CONFIG_VALUE_1": "all",
}  # fmt: skip

# Exit codes that are a harness's provider limit, per harness: only what a real run verified.
LIMIT_EXITS: dict[str, tuple[int, ...]] = {}
LIMIT_FILE = "limit.json"


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
    private: tuple[Path, ...] = ()  # never readable from the sandbox: runner state, secrets
    workspaces: Path | None = None  # the root of every clone, for sandboxes that can carve
    as_user: AsUser = AsUser()  # who the agents run as (§7.6)
    agent_path: str = ""  # the agents' PATH, for the runner's own modules on an ssh host


@dataclass(frozen=True)
class Launch:
    argv: list[str]
    env: dict[str, str]


def launch(ctx: Context) -> Launch:
    # Every git in the session, the harness's own unsandboxed calls included, reads the
    # clone's real .git: a `.git/commondir` the agent writes from the sandbox redirects
    # nothing. The agent can unset it for its own commands, which stay in the sandbox.
    env = {
        "MAITY_PLACEMENT": ctx.placement["id"],
        # The agent's `maity resume` sends it, and the hub answers a supervised session
        # (§15.11): no `maity wait`, a narrower wake set.
        "MAITY_SUPERVISOR": f"maity-runner/{__version__}",
        "GIT_COMMON_DIR": str(ctx.clone / ".git"),
        # A nested repository the agent registers as a submodule keeps its own configuration,
        # which the pin does not reach; git passes these settings on to it.
        **SESSION_GIT_CONFIG,
        **ctx.extra_env,
    }
    # The mark that this clone runs under the runner: maity refuses its git here when the
    # session's variables are gone (clonecheck.placement_root), instead of trusting that.
    ctx.as_user.mkdir(ctx.clone / ".git" / "maity")
    ctx.as_user.write(ctx.clone / clonecheck.MARKER_PATH, ctx.placement["id"] + "\n")
    # Which directory `.git` is: the sandbox does not keep the agent from renaming it, so
    # maity outside the sandbox takes `.git` only as this one (clonecheck.opened_git).
    env[clonecheck.GIT_INODE_ENV] = str(ctx.as_user.inode(ctx.clone / ".git"))
    # git's own repository for each run maity starts, outside the clone, in the agent's
    # directory the sandbox hides (clonecheck._private_dir). Codex runs maity in its sandbox,
    # which cannot write there: named as the clone's `.git/maity`.
    if ctx.harness.id == "codex":
        env[clonecheck.GIT_PRIVATE_ENV] = clonecheck.IN_CLONE
    else:
        private = ctx.agent_dir / "git"
        ctx.as_user.mkdir(private)
        env[clonecheck.GIT_PRIVATE_ENV] = str(private)
    # The git maity starts there: this one, found on the runner's PATH, not the agent's.
    git = proc.program("git")
    if git is not None:
        ctx.as_user.write(ctx.clone / clonecheck.GIT_PATH, git + "\n")
    harness = ctx.harness
    if harness.id == "stub":
        return Launch(stub.argv(harness.stub_exit_code, harness.stub_run_seconds, ctx.as_user), env)
    if harness.id == "claude-code":
        return _claude_code(ctx, env)
    if harness.id == "codex":
        return _codex(ctx, env)
    if harness.id == "opencode":
        return _opencode(ctx, env)
    raise NotYet(f"no adapter for {harness.id}")


def headless(ctx: Context) -> bool:
    """A supervised placement: the harness runs without a person at the pane (§6.2)."""
    return ctx.placement.get("mode") != "interactive"


def _write(ctx: Context, path: Path, data: Any) -> Path:
    """A file for the agents' side, written as the agents' user (§7.6)."""
    return ctx.as_user.write(path, json.dumps(data, indent=2) + "\n")


def _supervised(ctx: Context, first: list[str], again: list[str], env: dict[str, str]) -> Launch:
    """The loop of §6.2 in the pane; what it runs comes from a spec file it cannot widen."""
    policy = ctx.restart
    spec = _write(ctx, ctx.agent_dir / "loop.json",
        {
            "first": first,
            "again": again,
            "env": env,
            "restart": {
                "initial": policy.initial, "factor": policy.factor, "max": policy.max,
                "crash_window": policy.crash_window, "crash_cap": policy.crash_cap,
                "quick_exit": policy.quick_exit,
            },
            # A provider limit, as the loop recognises it: none until a real run of the
            # harness has shown its signal (§15.7); until then a limit exits like a crash.
            "limit": {"exit_codes": list(LIMIT_EXITS.get(ctx.harness.id, ())),
                      "file": str(ctx.agent_dir / LIMIT_FILE)},
        },  # fmt: skip
    )
    return Launch([*ctx.as_user.runner_module("loop"), "--spec", str(spec)], env)


# --- Claude Code ------------------------------------------------------------------------------


def claude_settings(ctx: Context) -> dict[str, Any]:
    """The grant (§6.1): maity, git, the repository's own allow list, and file tools inside
    the clone only. Absolute paths take a double slash in Claude Code's rules. The clone's
    credential is neither readable nor writable through the file tools."""
    ws = str(ctx.clone)
    allow = ["Bash(maity *)", *(f"Bash(git {sub})" for sub in GIT_SUBCOMMANDS)]
    allow += [f"Bash(git {sub} *)" for sub in GIT_SUBCOMMANDS]
    allow += [f"Bash({cmd})" for cmd in ctx.grant.allow if config.plain_command(cmd)]
    allow += [f"{tool}(/{ws}/**)" for tool in ("Read", "Edit", "Write")]
    # Agents commit through git and never edit what makes git run something (GIT_PROTECTED).
    # Not all of .git: the sandbox turns an Edit deny into a write deny for every command, and
    # git could no longer fetch or commit. The credential is not readable through Read.
    # `Edit(…)` covers every file-editing tool; Claude Code ignores a `Write(…)` deny rule.
    git = f"{ws}/.git"
    deny = [f"Edit(/{git}/{name}{'/**' if name in ('hooks', 'info') else ''})"
            for name in GIT_PROTECTED]  # fmt: skip
    deny += [f"Edit(/{git}/maity/**)", f"Read(/{git}/maity/**)"]
    deny += [f"Bash({rule})" for rule in GIT_DENIED]
    if headless(ctx):
        # Nobody answers a headless run. `dontAsk` already denies the question tool, but it
        # stays in the model's context; the bare name takes it out of the model's context
        # (cli/context/runner.md).
        deny += ["AskUserQuestion"]
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
            # the clone's credential, other clones' or the runner's; `maity` alone, which
            # signs with it, runs outside.
            # Not the workspaces root: re-opening this clone inside it (`allowRead`) could
            # re-open its credential as well, and that order is unverified here.
            "filesystem": {"denyRead": [f"{git}/maity", *(str(p) for p in ctx.private)],
                           "denyWrite": [f"{git}/maity",
                                         *(f"{git}/{name}" for name in GIT_PROTECTED)]},
            "excludedCommands": ["maity *"],
        }  # fmt: skip
    return settings


def trust_clone(ctx: Context) -> None:
    """Record the clone as trusted for the agents' Claude Code (trust.py): without it, its
    first interactive start in a fresh clone waits at the folder-trust question and the agent
    never comes online. The owner's placement is the trust decision; only this clone's entry
    changes. Run where the agents are, as their user. A failure fails the start: a session
    waiting at the question would pass for `running`."""
    home = ctx.as_user.home()
    if ctx.as_user.direct:
        trust.record(home, ctx.clone)
        return
    done = ctx.as_user.run(
        [*ctx.as_user.runner_module("trust"), str(home), str(ctx.clone)],
        env={"PATH": ctx.agent_path} if ctx.agent_path and not ctx.as_user.here else None,
    )
    if done.returncode != 0:
        raise trust.TrustError(
            f"cannot record Claude Code's folder trust for {ctx.clone}: "
            f"{done.stderr.strip()[:200] or f'exit {done.returncode}'}"
        )


def _claude_code(ctx: Context, env: dict[str, str]) -> Launch:
    assert ctx.binary is not None  # noqa: S101 - the supervisor checked the probe
    settings = _write(ctx, ctx.agent_dir / "claude-settings.json", claude_settings(ctx))
    mcp = _write(ctx, ctx.agent_dir / "claude-mcp.json", {"mcpServers": {}})
    base = [
        ctx.binary,
        "--setting-sources", "user",  # the project's .claude/ is not loaded, hooks included
        "--settings", str(settings),
        "--permission-mode", "dontAsk",
        # `=`: `--mcp-config` takes several values, and in interactive mode the start
        # prompt comes next, which Claude Code would read as a second configuration file.
        "--strict-mcp-config", f"--mcp-config={mcp}",
    ]  # fmt: skip
    model = ctx.placement.get("model")
    if model:
        base += ["--model", model]
    if ctx.placement.get("mode") == "interactive":
        trust_clone(ctx)
        return Launch([*base, START_PROMPT], env)
    # Headless (`-p`) asks for no folder trust and records none: nothing to pre-accept.
    # No background command may hold a run open past its turn (§6.2).
    quiet = {**env, "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"}
    return _supervised(
        ctx,
        [*base, "-p", SUPERVISED_PROMPT],
        [*base, "-p", SUPERVISED_PROMPT, "--continue"],
        quiet,
    )


# --- Codex ------------------------------------------------------------------------------------

# Codex's own model endpoints, for the network rule; an operator adds more per repository.
CODEX_PROVIDER_HOSTS = ("api.openai.com", "chatgpt.com")


def codex_config(ctx: Context) -> str:
    """`config.toml` in the placement's own CODEX_HOME (§6.1): Codex's sandbox with the
    workspace profile, the clone's `.git` writable (commits need it), no approvals asked,
    network to the hub, the forge and the model provider only."""
    hosts = sorted({*ctx.hosts, *CODEX_PROVIDER_HOSTS, *ctx.grant.network})
    domains = "".join(f'{json.dumps(host)} = "allow"\n' for host in hosts)
    # Unreadable: other clones (the workspaces root), the runner's state and the secrets in
    # the agents' home. The clone's own rules are more specific and win; its credential
    # stays readable, since the agent's `maity` runs inside the sandbox.
    roots = (*((ctx.workspaces,) if ctx.workspaces else ()), *ctx.private)
    hidden = "".join(f'{json.dumps(str(path))} = "none"\n' for path in roots)
    return (
        'approval_policy = "never"\n'
        'default_permissions = "maity"\n\n'
        # The clone's own .codex/config.toml would override this profile; an untrusted
        # project's configuration layers are not loaded.
        f'[projects.{json.dumps(str(ctx.clone))}]\ntrust_level = "untrusted"\n\n'
        "[features]\nnetwork_proxy = true\n\n"
        '[permissions.maity]\nextends = ":workspace"\n\n'
        "[permissions.maity.filesystem]\n" + hidden + f'{json.dumps(str(ctx.clone))} = "write"\n'
        f"{json.dumps(str(ctx.clone / '.git'))} = \"write\"\n"
        # Commits need .git (lock files are created there, so the directory stays writable).
        # Its hooks and config are read-only; a `commondir` the agent writes is ignored by
        # every git outside the sandbox, which runs with GIT_COMMON_DIR set (launch()).
        f"{json.dumps(str(ctx.clone / '.git' / 'hooks'))} = \"read\"\n"
        f"{json.dumps(str(ctx.clone / '.git' / 'config'))} = \"read\"\n\n"
        "[permissions.maity.network]\nenabled = true\n\n"
        "[permissions.maity.network.domains]\n" + domains
        # Nobody answers a headless run: the question tool is not offered (cli/context/runner.md).
        + ("\n[tools.experimental_request_user_input]\nenabled = false\n" if headless(ctx) else "")
    )


def _codex(ctx: Context, env: dict[str, str]) -> Launch:
    assert ctx.binary is not None  # noqa: S101 - the supervisor checked the probe
    home = ctx.agent_dir / "codex-home"
    ctx.as_user.write(home / "config.toml", codex_config(ctx))
    # The login of whoever runs the agents (the operator, or the agents' user), linked so
    # that a token refresh lands in the original; a link left from an earlier launch that
    # points elsewhere, or nowhere, is replaced (AsUser.link).
    own = None if not ctx.as_user.direct else os.environ.get("CODEX_HOME")
    login = Path(own or ctx.as_user.home() / ".codex") / "auth.json"
    if ctx.as_user.exists(login, "-f"):
        ctx.as_user.link(login, home / "auth.json")
    ctx.as_user.mkdir(ctx.clone / ".git" / "maity")
    env = {**env, "CODEX_HOME": str(home)}
    model = ctx.placement.get("model")
    chosen = ["-m", model] if model else []
    if ctx.placement.get("mode") == "interactive":
        return Launch([ctx.binary, "-C", str(ctx.clone), *chosen, START_PROMPT], env)
    first = [ctx.binary, "exec", "-C", str(ctx.clone), *chosen, START_PROMPT]
    # `--last` is per working directory, and CODEX_HOME is per placement: never another's.
    again = [ctx.binary, "exec", "-C", str(ctx.clone), *chosen, "resume", "--last", START_PROMPT]
    return _supervised(ctx, first, again, env)


# --- opencode ---------------------------------------------------------------------------------


def opencode_config(ctx: Context) -> dict[str, Any]:
    """The catch-all deny comes first: opencode's last matching rule wins (§6.1). With the
    project's configuration switched off, `AGENTS.md` is named as an instruction."""
    bash = {"*": "deny", "maity *": "allow"}
    granted = [cmd for cmd in ctx.grant.allow if config.plain_command(cmd)]
    for cmd in (*(f"git {sub}" for sub in GIT_SUBCOMMANDS), *granted):
        bash[cmd] = "allow"
        bash[f"{cmd} *"] = "allow"
    bash.update({rule: "deny" for rule in GIT_DENIED})  # after the allows: the last match wins
    secret = f"{ctx.clone}/.git/maity/*"
    # The clone's credential is neither readable nor writable; nothing under .git is edited
    # (agents commit through git; its config and hooks would turn a git call into anything).
    read = {"*": "allow", secret: "deny"}
    edit = {"*": "allow", f"{ctx.clone}/.git/*": "deny"}
    return {
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "*": "deny",
            # grep and glob are asked about the pattern typed, not the path searched, so a path
            # rule cannot keep them off .git/maity: they are off.
            "read": read, "glob": "deny", "grep": "deny", "list": "allow",
            "edit": edit,
            "bash": bash,
            "webfetch": "deny",
            "external_directory": "deny",
        },
        "instructions": [str(ctx.clone / "AGENTS.md")],
    }  # fmt: skip


def _opencode(ctx: Context, env: dict[str, str]) -> Launch:
    assert ctx.binary is not None  # noqa: S101 - the supervisor checked the probe
    path = _write(ctx, ctx.agent_dir / "opencode.json", opencode_config(ctx))
    # Without the switch the repository's opencode.json wins over OPENCODE_CONFIG, and its
    # .opencode/ directories bring agents, commands and plugins.
    env = {**env, "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_CONFIG": str(path)}
    model = ctx.placement.get("model")
    chosen = ["--model", model] if model else []
    if ctx.placement.get("mode") == "interactive":
        return Launch([ctx.binary, str(ctx.clone), *chosen, "--prompt", START_PROMPT], env)
    first = [ctx.binary, "run", "--dir", str(ctx.clone), *chosen, START_PROMPT]
    again = [ctx.binary, "run", "--dir", str(ctx.clone), *chosen, "--continue", START_PROMPT]
    return _supervised(ctx, first, again, env)
