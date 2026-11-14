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
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__, clonecheck, ghpr, proc
from . import config, stub, trust
from .asuser import AsUser

START_PROMPT = (
    "This clone is a Maity project. Run `maity resume` now and follow it: your briefing "
    "comes first. Then work as `docs/agents.md` and the rules in the packet say."
)
# The clone's `.git/config` is not writable from Claude Code's or Codex's sandbox
# (GIT_PROTECTED, codex_config), so git's commands that store a setting there fail. The
# session's git needs none of them for the usual flow (SANDBOX_GIT_CONFIG); the prompt names
# the ones that still fail.
GIT_PROMPT = (
    " Git here cannot write `.git/config`: cut a branch with `git switch -c <branch> "
    "origin/<default branch>`, push it with `git push origin <branch>` and pull with `git pull "
    "origin <branch>`; never `push -u`, `--set-upstream`, `--track` or `branch -m`, which "
    "store an upstream or rename one and print an error. `maity report` needs no upstream."
)
# Claude Code's sandbox hides the clone's credential; `maity` runs outside it, and only as
# one plain call: the runner's hook (plaincall) refuses anything else on its line
# (cli/context/runner.md).
CLAUDE_MAITY_PROMPT = (
    " Run every `maity` command alone, as one plain call: a line that pipes, chains with `;`, "
    "`&&` or `||`, redirects, sends it to the background with `&`, uses `$(...)`, a heredoc "
    "or a `$` is refused. Pass longer text in a file in this clone (`--body-file`)."
)
# What a line that starts with `maity` may not hold in opencode's rules (opencode_config).
MAITY_NOT_PLAIN = (";", "&", "|", "<", ">", "`", "$", "\n")
# An interactive session the runner ended because its agent stopped listening (§15.14) starts
# again on the same conversation with this line, where the harness can resume one.
RESUME_PROMPT = (
    "The runner ended and resumed this session: you had stopped listening (no `maity wait` "
    "ran and nothing changed on screen). Run `maity resume`, then carry on with your work and "
    "your wait loop."
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
    "ls-files", "blame", "grep", "remote -v",
)  # fmt: skip
# Not `config user.name` or `config user.email`: the session's identity comes from the
# runner (git_identity), which wins over any configuration, and without a sandbox those
# would write `.git/config`.
GIT_DENIED = (
    "git -c *", "git --config-env*", "git --exec-path*", "git * --no-index*",
    "git * --upload-pack*", "git * --receive-pack*", "git * --exec=*", "git *.git/maity*",
)  # fmt: skip
# No session runs gh: the token is the operator's and reaches every repository it may, and no
# glob on a command line pins one (`-dR`, a URL). Agents open and read their pull requests
# with `maity gh`, which runs outside the sandbox with the repository fixed by the runner
# (cli/context/runner.md).
GH_DENIED = ("gh", "gh *")
# Where a repository's grant has `pull_requests = true`.
PULL_REQUEST_PROMPT = (
    " Open your pull request with `maity gh pr create --title <title> --body-file <file>` "
    "(a file in this clone) and read one with `maity gh pr view [<number>]`; `gh` itself "
    "does not run here."
)


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
# Only where the harness's sandbox keeps `.git/config` unwritable: `branch.autoSetupMerge=false`
# cuts a branch from a remote one without storing an upstream there (which fails), and
# `push.default=current` pushes the branch to its own name without one.
# `fetch.recurseSubmodules=false` keeps fetch from reading `.gitmodules`, which Claude Code's
# sandbox replaces with an unreadable placeholder when the repository has none. They override
# the clone's own values; a runner's clone is a plain one the clone check keeps free of
# other keys (cli/context/runner.md). Without a sandbox the clone's configuration stands.
SANDBOX_GIT_CONFIG = (
    ("branch.autoSetupMerge", "false"),
    ("push.default", "current"),
    ("fetch.recurseSubmodules", "false"),
)


def git_config(ctx: Context) -> dict[str, str]:
    """The session's `GIT_CONFIG_*`: SESSION_GIT_CONFIG, plus SANDBOX_GIT_CONFIG under a
    sandbox that keeps `.git/config` unwritable."""
    extra = SANDBOX_GIT_CONFIG if writes_denied(ctx) else ()
    env = dict(SESSION_GIT_CONFIG)
    first = int(SESSION_GIT_CONFIG["GIT_CONFIG_COUNT"])
    for index, (key, value) in enumerate(extra, start=first):
        env[f"GIT_CONFIG_KEY_{index}"], env[f"GIT_CONFIG_VALUE_{index}"] = key, value
    env["GIT_CONFIG_COUNT"] = str(first + len(extra))
    return env


def git_identity(ctx: Context) -> dict[str, str]:
    """Who the session commits as: the runner's `[git]`, author and committer alike. The
    variables win over every git configuration, so neither the agents' user's own (the
    operator's, in the `single` layout) nor one the agent sets is used (cli/context/runner.md)."""
    name, email = ctx.git.name, ctx.git.email
    return {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": email}  # fmt: skip


def writes_denied(ctx: Context) -> bool:
    """Whether the session's git cannot write `.git/config`: Claude Code's and Codex's
    sandboxes deny it (claude_settings, codex_config)."""
    return ctx.sandbox and ctx.harness.id in ("claude-code", "codex")


# What Claude Code's sandbox puts into the work tree's root where the path is missing, so that
# nothing can create it there: an empty placeholder each, which `git status` lists as
# untracked. Read from `git status` in a sandboxed run of 2.1.322. The runner hides those that
# are missing (or an empty directory) at the start in `.git/info/exclude`, which the agent
# cannot write (GIT_PROTECTED); a path with real content stays visible (hide_placeholders).
CLAUDE_PLACEHOLDERS = (
    ".bash_profile", ".bashrc", ".claude/agents", ".claude/commands", ".claude/hooks",
    ".claude/launch.json", ".claude/loop.md", ".claude/output-styles", ".claude/routines",
    ".claude/scheduled_tasks.json", ".claude/settings.local.json", ".claude/skills",
    ".claude/workflows", ".gitconfig", ".gitmodules", ".idea", ".mcp.json", ".profile",
    ".ripgreprc", ".vscode", ".zprofile", ".zshrc",
)  # fmt: skip
EXCLUDE_BEGIN = "# maity-runner: the sandbox's placeholders (begin)"
EXCLUDE_END = "# maity-runner: the sandbox's placeholders (end)"
# A clone's `.git/info/exclude` larger than this is left as it is, without the block.
EXCLUDE_MAX = 256 * 1024

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
    resume: bool = False  # interactive: continue the harness's last conversation (§15.14)
    git: config.GitIdentity = config.GitIdentity()  # who the session commits as (`[git]`)


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
        # (§15.11): no `maity wait`, a narrower wake set. Only where the loop wakes the
        # harness: an interactive session told not to wait would miss every later event.
        **({"MAITY_SUPERVISOR": f"maity-runner/{__version__}"} if headless(ctx) else {}),
        "GIT_COMMON_DIR": str(ctx.clone / ".git"),
        # A nested repository the agent registers as a submodule keeps its own configuration,
        # which the pin does not reach; git passes these settings on to it.
        **git_config(ctx),
        **git_identity(ctx),
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
    # The runner's records for maity are kept there too, outside the clone, whose files are
    # the agent's to write (clonecheck.runner_record).
    if ctx.harness.id == "codex":
        env[clonecheck.GIT_PRIVATE_ENV] = clonecheck.IN_CLONE
        records = ctx.clone / ".git" / "maity"
    else:
        records = ctx.agent_dir / "git"
        ctx.as_user.mkdir(records)
        env[clonecheck.GIT_PRIVATE_ENV] = str(records)
    # The git maity starts there: this one, found on the runner's PATH, not the agent's.
    git = proc.program("git")
    if git is not None:
        ctx.as_user.write(records / clonecheck.GIT_PATH.name, git + "\n")
    # What `maity gh` may do here: the repository it pins and the gh it starts, or nothing
    # (an empty record also clears one a former grant left).
    ctx.as_user.write(records / ghpr.PULL_REQUESTS, pull_requests_record(ctx))
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
    deny += [f"Bash({rule})" for rule in (*GIT_DENIED, *GH_DENIED)]
    if headless(ctx):
        # Nobody answers a headless run. `dontAsk` already denies the question tool, but it
        # stays in the model's context; the bare name takes it out of the model's context
        # (cli/context/runner.md).
        deny += ["AskUserQuestion"]
    settings: dict[str, Any] = {
        "permissions": {"allow": allow, "deny": deny, "defaultMode": "dontAsk"},
        # Agents write no attribution lines in commits or pull request bodies. Empty
        # strings, not `false`: a binary older than 2.1.281 rejects `false` and drops this
        # whole file, grant included (cli/context/runner.md).
        "attribution": {"commit": "", "pr": "", "sessionUrl": False},
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
        # `maity` runs outside the sandbox only as one plain call: the hook refuses a line
        # that starts with `maity` and holds anything else (plaincall). It runs for every
        # tool, outside the sandbox, from the runner's own code; a hook that fails or times
        # out refuses the call (`onFailure`, Claude Code 2.1.295 and later: the sandbox is not
        # switched on for an older one, capabilities.sandbox_version_ok). Shell form, so a
        # version that predates exec form runs it too; `|| exit 2` refuses on any version
        # when the hook cannot start or fails.
        module = " ".join(shlex.quote(word) for word in ctx.as_user.runner_module("plaincall"))
        hook = f"{module} || exit 2"
        settings["hooks"] = {
            "PreToolUse": [
                {"hooks": [{"type": "command", "command": hook, "timeout": 30,
                            "onFailure": "block"}]},
            ],
        }  # fmt: skip
        settings["disableAllHooks"] = False  # over a `true` in the agents' user settings
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


def pull_requests_record(ctx: Context) -> str:
    """The content of the runner's record `ghpr.PULL_REQUESTS`: the placement's repository
    and the gh on the runner's PATH when the grant has pull requests and gh is there, else
    empty."""
    if not ctx.grant.pull_requests:
        return ""
    gh = proc.program("gh")
    workspace = ctx.placement.get("workspace") or {}
    repository = config.normalise_repository(workspace.get("repository") or "")
    if gh is None or not repository:
        return ""
    return f"{repository}\n{gh}\n"


def _sandbox_prompt(ctx: Context) -> str:
    """What the start prompt adds: under the harness's sandbox the git commands that fail, and
    for Claude Code that `maity` runs alone; with the grant's pull requests, `maity gh`."""
    pulls = PULL_REQUEST_PROMPT if pull_requests_record(ctx) else ""
    if not writes_denied(ctx):
        return pulls
    return GIT_PROMPT + (CLAUDE_MAITY_PROMPT if ctx.harness.id == "claude-code" else "") + pulls


def hide_placeholders(ctx: Context) -> None:
    """Write the CLAUDE_PLACEHOLDERS that are missing in the clone, or an empty directory there,
    into its `.git/info/exclude`, as the agents' user, between markers: the sandbox puts a
    placeholder there, and nothing else can be. A path with content (a file, a link, a
    directory with entries) is left out, so real untracked content stays visible. The block is
    rebuilt at every start; a block from an earlier start is replaced, every other line stays."""
    path = ctx.clone / ".git" / "info" / "exclude"
    lines: list[str] = []
    if ctx.as_user.exists(path, "-f"):
        try:
            lines = (
                ctx.as_user.read_whole(path, EXCLUDE_MAX, under=ctx.clone)
                .decode("utf-8")
                .splitlines()
            )
        except (OSError, UnicodeDecodeError):  # rewriting it could change bytes not ours
            return
    kept, had_block = _without_block(lines)
    hidden = [name for name in CLAUDE_PLACEHOLDERS if _placeholder_only(ctx, ctx.clone / name)]
    if not hidden and not had_block:
        return
    block = [EXCLUDE_BEGIN, *(f"/{name}" for name in hidden), EXCLUDE_END] if hidden else []
    ctx.as_user.write(path, "\n".join([*kept, *block]) + "\n")


def _without_block(lines: list[str]) -> tuple[list[str], bool]:
    """`lines` without the runner's block, and whether there was one. A begin marker with no
    end marker after it is dropped alone, so the lines after it stay."""
    if EXCLUDE_BEGIN not in lines:
        return lines, False
    start = lines.index(EXCLUDE_BEGIN)
    if EXCLUDE_END not in lines[start:]:
        return lines[:start] + lines[start + 1 :], True
    end = lines.index(EXCLUDE_END, start)
    rest, _ = _without_block(lines[end + 1 :])
    return lines[:start] + rest, True


def _placeholder_only(ctx: Context, path: Path) -> bool:
    """Whether `path` holds nothing of its own: missing, or an empty directory (Claude Code
    makes some of them as real directories). A link, even a dangling one, is content."""
    if ctx.as_user.exists(path, "-L"):
        return False
    if not ctx.as_user.exists(path):
        return True
    if not ctx.as_user.exists(path, "-d"):
        return False
    try:
        return not ctx.as_user.tree(path)
    except OSError:  # unreadable: it may hold something, so it stays visible
        return False


def _claude_code(ctx: Context, env: dict[str, str]) -> Launch:
    assert ctx.binary is not None  # noqa: S101 - the supervisor checked the probe
    if ctx.sandbox:
        hide_placeholders(ctx)
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
        if ctx.resume:  # `--continue`: the clone's latest conversation, with its context
            return Launch([*base, "--continue", RESUME_PROMPT], env)
        return Launch([*base, START_PROMPT + _sandbox_prompt(ctx)], env)
    # Headless (`-p`) asks for no folder trust and records none: nothing to pre-accept.
    # No background command may hold a run open past its turn (§6.2).
    quiet = {**env, "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"}
    return _supervised(
        ctx,
        [*base, "-p", SUPERVISED_PROMPT + _sandbox_prompt(ctx)],
        [*base, "-p", SUPERVISED_PROMPT + _sandbox_prompt(ctx), "--continue"],
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
    prompt = START_PROMPT + _sandbox_prompt(ctx)
    if ctx.placement.get("mode") == "interactive":
        return Launch([ctx.binary, "-C", str(ctx.clone), *chosen, prompt], env)
    first = [ctx.binary, "exec", "-C", str(ctx.clone), *chosen, prompt]
    # `--last` is per working directory, and CODEX_HOME is per placement: never another's.
    again = [ctx.binary, "exec", "-C", str(ctx.clone), *chosen, "resume", "--last", prompt]
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
    # After the allows: the last match wins. A `maity` call only as one plain call, as the
    # Claude Code hook has it (plaincall): opencode checks each command its scanner finds,
    # and a redirect or a substitution on maity's line would pass `maity *`.
    bash.update({rule: "deny" for rule in (*GIT_DENIED, *GH_DENIED)})
    bash.update({f"maity *{char}*": "deny" for char in MAITY_NOT_PLAIN})
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
        prompt = START_PROMPT + _sandbox_prompt(ctx)
        return Launch([ctx.binary, str(ctx.clone), *chosen, "--prompt", prompt], env)
    prompt = START_PROMPT + _sandbox_prompt(ctx)
    first = [ctx.binary, "run", "--dir", str(ctx.clone), *chosen, prompt]
    again = [ctx.binary, "run", "--dir", str(ctx.clone), *chosen, "--continue", prompt]
    return _supervised(ctx, first, again, env)
