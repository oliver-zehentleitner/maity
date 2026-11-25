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

import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import __version__, clonecheck, ghpr, proc
from . import capabilities, config, scratch, skillop, skills, stub, trust
from .asuser import AsUser
from .workspace import SCRATCH, TMP_SCRATCH_HARNESSES

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
    "or a `$` outside single quotes is refused. Pass longer text in a file in this clone "
    "(`--body-file`)."
)
# Claude Code matches the allowlist against the command line as written, so a form that wraps an
# allowed command is refused (tsk-66zyvc4xnhtv). This tells the agent how to phrase its checks.
CLAUDE_COMMAND_PROMPT = (
    " Run one command per Bash call: a chain (`cd pkg && …`) is allowed only if every part is, "
    "so use `make -C <pkg>` and path arguments (`python3 -m pytest cli/tests`) instead of "
    "`cd <pkg> && …`, and do not prefix a command with a variable (`PYTHONPATH=… python3 …`)."
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

# git subcommands an agent needs for project work. Not `git *`: some git options run programs,
# and git can still read files outside the work tree, so these lists stop accidents and naive
# injection only; the boundary is the harness's OS sandbox and the OS user, see
# cli/context/runner.md.
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
# No worktree from the shell either, for the harnesses with a command allowlist (Claude Code,
# opencode): `git worktree` is not among GIT_SUBCOMMANDS, but a repository's grant could allow
# it, and a deny wins over an allow. A registered worktree stops maity's git in the clone, and
# one outside `.claude/worktrees/` is not cleared at the next start (worktree.py). A guard
# against accidents like the lists above, not a boundary. Kept apart from GIT_DENIED, which is
# about git running programs or reading configuration, and which agy's rules mirror.
# Only the subcommand itself: a pattern with a wildcard before `worktree` (`git * worktree *`,
# also `git -C * worktree *`) would deny ordinary commands that only mention the word
# (`git log --grep worktree`, a commit message), so it is not used. For Claude Code these
# denies are mirrored as `git -C <clone> worktree …` (claude_settings); `git -C <dir>` with any
# other directory matches no allow rule (cli/context/runner.md).
GIT_WORKTREE_DENIED = ("git worktree", "git worktree *")
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

# `maity runner` is the operator's and the runner's; no agent runs it from its shell. Its
# in-session commands (the loop, the pane's log, the hook) are started by the runner or by the
# harness itself, never through an agent's command tool (runner_own_file is the boundary).
MAITY_RUNNER_DENIED = ("maity runner", "maity runner *")

# A placed Claude Code session makes no git worktree in its clone: while one exists maity runs
# no git there (clonecheck, "Worktrees are"), so `maity report` and `maity gh` fail, and the
# session cannot remove it from its sandbox; only the next start clears it (worktree.py). The
# bare name takes EnterWorktree out of the model's context, as for AskUserQuestion; the
# WorktreeCreate hook replaces Claude Code's own worktree creation (subagents with
# `isolation: worktree` included) and fails it (cli/context/runner.md).
CLAUDE_WORKTREE_DENIED = ("EnterWorktree",)
# Shell form, like the plain-call hook; no runner module, so it cannot fail to start in a way
# that would let a worktree through. It prints no path, and exits 2. Written only for a version
# with the event; the bare deny goes in every file (a deny of a name a binary does not know is
# taken as harmless).
CLAUDE_WORKTREE_HOOK = (
    "echo 'git worktrees are off in a placement clone; work in the clone itself' >&2; exit 2"
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

# No OS UUID command is allowed: an agent makes its Keep-the-Why Ids with `maity uuid`, which runs
# wherever `maity` does. An exact `cat /proc/sys/kernel/random/uuid` allow was refused in every
# placed Claude Code session anyway: the path check on a read outside the working directories
# decides before the rule, and opencode's `external_directory: deny` gates the same path
# (cli/context/runner.md).

READY = ("stub", "claude-code", "codex", "opencode", "antigravity")  # harnesses with an adapter
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
    sandbox that keeps `.git/config` unwritable, and for agy, whose deny of `.git/config` to
    its file tools may or may not reach its sandbox (not seen in a run): the three settings
    work either way."""
    extra = SANDBOX_GIT_CONFIG if writes_denied(ctx) or ctx.harness.id == "antigravity" else ()
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
    # The workspace folder the harness starts in, holding the clone (§15.5); None: the clone.
    folder: Path | None = None
    # The placement's scratch (§15.5), made by the supervisor; None where the harness gets none
    # (workspace.SCRATCH_HARNESSES).
    scratch: Path | None = None
    # The agy per-user `/tmp` scratch parent, hidden from this placement's sandbox so it cannot
    # reach another placement's scratch there; set only for a placement whose sandbox hides it
    # (workspace.TMP_SCRATCH_PARENT_HIDERS: Claude Code, Codex). None for an agy placement, which
    # owns that parent, for one that hides nothing, and where there is no local `/tmp` scratch (an
    # ssh host, no uid).
    tmp_scratch_parent: Path | None = None
    # The placement's own short TMPDIR (`tmp` in a fresh leaf under that per-user `/tmp` parent),
    # made by the supervisor only where the scratch's own `tmp` leaves no room for a Unix socket
    # (scratch_tmpdir) and re-opened for this placement alone in its sandbox: Codex's whole leaf
    # (tsk-0zb9mgzmbwn4), and Claude Code's, its `tmp` re-opened and the leaf itself its
    # CLAUDE_CODE_TMPDIR (tsk-k7svzz2p4v7y; workspace.OWN_TMPDIR_HARNESSES).
    tmpdir: Path | None = None
    # The placement's test cluster password file in the holder every sandbox is denied
    # (scratchop.PG_HOLDER), when the runner vouched for it; without one the session gets no
    # test cluster (run_env). The session never reads it: `pgenv` does, before the session runs.
    pg_pass: Path | None = None
    # The harness's version as the runner probed it (capabilities.probe), for settings that a
    # version needs: Claude Code's worktree hook. None: unknown, and nothing version-gated.
    version: str | None = None
    # The Keep the Why skill the placement names, as the runner's checked copy (skills.py): the
    # plugin root Claude Code loads with `--plugin-dir`, read-only to the session. None when the
    # placement names none or it could not be fetched.
    skill: Path | None = None
    # The runner's own checked copy of that skill (skills.ensure, `<skills_dir>/keep-the-why/
    # <key>`), on the runner's machine whatever the target: the bytes a Codex placement's own
    # skills directory gets (codex_skill). None with `skill`.
    skill_source: Path | None = None
    # The dev venvs the runner built for this clone (`clone_venvs`, venvs.py), each under the
    # runner's venvs directory: read and run by the session, never written (claude_settings).
    venvs: tuple[Path, ...] = ()


def skill_env(ctx: Context) -> dict[str, str]:
    """MAITY_KTW_SKILL_DIR: where the delivered skill's `SKILL.md` lies, for every harness; the
    resume block names it instead of "<skills directory>" (onboarding)."""
    if ctx.skill is None:
        return {}
    return {"MAITY_KTW_SKILL_DIR": str(skills.skill_in(ctx.skill))}


# MAITY_RUN_NAME as tools/run_slot.sh and with_postgres.sh log it: `<handle>#<instance>`, both as
# the hub names them; anything else is left out rather than passed on.
_RUN_NAME_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")  # fullmatch: no `$`, no "\n"


def run_name(placement: dict[str, Any]) -> str | None:
    """Who the placement's runs are logged as: `<handle>#<instance>`, the handle alone while the
    hub has named no instance yet (before the first join), None without a usable handle."""
    agent = placement.get("agent")
    handle = agent.get("handle") if isinstance(agent, dict) else None
    if not isinstance(handle, str) or not _RUN_NAME_PART.fullmatch(handle):
        return None
    instance = placement.get("instance")
    if isinstance(instance, str) and _RUN_NAME_PART.fullmatch(instance):
        return f"{handle}#{instance}"
    return handle


# A Unix socket's path holds at most 107 bytes on Linux (`sun_path` is 108, with its NUL) and
# 103 on macOS and the BSDs (104). Tools put sockets under TMPDIR: Claude Code's sandbox binds
# `claude-socks-<16 hex>.sock` there (34 bytes) and does not start when the path is longer. A
# scratch deep in a workspaces root made that path 117 bytes, so every Claude Code placement lost
# its sandbox (cli 0.1.0a16).
def socket_path_max(platform: str = sys.platform) -> int:
    """The longest Unix socket path, in bytes, on `platform` (`sys.platform`'s form)."""
    return 107 if platform.startswith("linux") else 103


SOCKET_PATH_MAX = socket_path_max()
SOCKET_NAME_ROOM = len("claude-socks-0123456789abcdef.sock")


def scratch_tmpdir(scratch: Path | None) -> Path | None:
    """The TMPDIR inside the placement's scratch, or None when there is no scratch or when a
    socket named like Claude Code's under it would not fit a Unix socket path: then the session
    gets no TMPDIR at all (the runner starts it with a clean environment, so tools use their
    default, /tmp) and only `MAITY_SCRATCH` names the scratch. Under the default workspaces root
    `~/maity-workspaces` that is the usual case: a home longer than `/home/ab` leaves no room."""
    if scratch is None:
        return None
    tmp = scratch / "tmp"
    return tmp if fits_socket(tmp) else None


def fits_socket(tmp: Path, limit: int | None = None) -> bool:
    """Whether a socket named like Claude Code's fits under `tmp` within `limit` bytes (this
    platform's SOCKET_PATH_MAX by default)."""
    room = SOCKET_PATH_MAX if limit is None else limit
    return len(os.fsencode(tmp)) + 1 + SOCKET_NAME_ROOM <= room


def session_tmpdir(ctx: Context) -> Path | None:
    """The session's TMPDIR: `tmp` in its scratch where a socket fits under it, else the short
    one of its own the supervisor made under the per-user `/tmp` parent (Context.tmpdir), else
    none, and tools fall back to the system's (tsk-0zb9mgzmbwn4, tsk-k7svzz2p4v7y)."""
    own = scratch_tmpdir(ctx.scratch)
    if own is not None:
        return own
    return ctx.tmpdir if ctx.tmpdir is not None and fits_socket(ctx.tmpdir) else None


def own_tmpdir_in_use(ctx: Context) -> Path | None:
    """The placement's own TMPDIR under the per-user `/tmp` parent (Context.tmpdir) when it is
    the one the session gets (session_tmpdir), else None: the sandbox opens it, and the parent's
    write deny is lifted, only then."""
    return ctx.tmpdir if ctx.tmpdir is not None and session_tmpdir(ctx) == ctx.tmpdir else None


def private_tmpdir_refusal(ctx: Context) -> str | None:
    """Why a sandboxed Claude Code placement must not start, or None: it starts only with a
    TMPDIR of its own (session_tmpdir). Without one, Claude Code hands its sandboxed commands
    `/tmp/claude-<uid>`, one directory every Claude Code session of the OS user shares and can
    write, so the start fails closed instead (tsk-k7svzz2p4v7y; security's tsk-z5c3798r1ces). An
    unsandboxed placement is not refused: its commands already reach every file of the user.
    The text is for the runner's log only, with the cause and the remedy."""
    if ctx.harness.id != "claude-code" or not ctx.sandbox or session_tmpdir(ctx) is not None:
        return None
    where = "there is no scratch"
    if ctx.scratch is not None:
        where = f"{ctx.scratch / 'tmp'} is too long for a Unix socket"
    return (
        f"no private TMPDIR for this sandboxed Claude Code placement: {where}, "
        "and no short one could be made under the per-user /tmp parent (none is made on an ssh "
        "host). Its commands would share /tmp/claude-<uid> with every Claude Code session of "
        "this OS user, so it is not started. Set a short `workspaces` root on this host, such "
        "as /srv/mw"
    )


def scratch_refusal(ctx: Context) -> str | None:
    """Why a sandboxed Claude Code placement must not start, or None: it starts only with a
    scratch under a holder its sandbox denies (scratch_holder). That deny is what hides a
    scratch made after the session started (tsk-c7zzd440x8pn), and it is derived from the own
    scratch, so a start whose scratch could not be made would have none (the review of
    #2112, A2045). An unsandboxed placement, and every other harness, is not refused: Codex
    hides the whole workspaces root, and agy and opencode get no such deny. For the runner's
    log only, with the cause."""
    if ctx.harness.id != "claude-code" or not ctx.sandbox:
        return None
    if scratch_holder(ctx.scratch) is not None:
        return None
    return (
        "no scratch could be made for this sandboxed Claude Code placement, so its sandbox "
        "would not deny the scratch holder and a scratch made later would stay readable from "
        "it; it is not started (the cause is logged above)"
    )


def own_tmp_env(ctx: Context) -> dict[str, str]:
    """Claude Code's CLAUDE_CODE_TMPDIR in the leaf itself where the session's TMPDIR is the
    leaf's `tmp`: Claude Code's own temp files (`claude-<uid>/`) and its sandbox socket
    (`cc-socks/`) then sit beside the `tmp` its sandbox writes, and go with the leaf
    (tsk-k7svzz2p4v7y). Claude Code itself opens `claude-<uid>/` to the placement's sandbox
    for reading and writing, while `cc-socks/` stays hidden (live, Claude Code 2.1.329): both
    stay within the placement. Empty otherwise: where the scratch's `tmp` is the TMPDIR,
    Claude Code's own files follow it, as before."""
    own = own_tmpdir_in_use(ctx)
    if ctx.harness.id != "claude-code" or own is None:
        return {}
    return {"CLAUDE_CODE_TMPDIR": str(own.parent)}


# The test scripts' directories inside the placement's scratch (tsk-w7qtcbzcshn9): the run slots
# of tools/run_slot.sh and with_postgres.sh's cluster, whose defaults under `~/.local/state` no
# sandbox writes. Per placement, so the slots bound one placement's runs only; bounding them
# across placements is tsk-w7dx3h9mn8dp. The cluster's socket goes in its data directory
# (`-k "$MAITY_PG_DIR"`), named like `.s.PGSQL.<port>`, room taken for a five-digit port.
SLOTS, PG = "slots", "pg"
PG_SOCKET_ROOM = len(".s.PGSQL.65535")
# The harnesses whose sandbox refuses a Unix socket even in the placement's own scratch, so
# with_postgres.sh's cluster cannot start in their sessions: Claude Code's refuses
# socket(AF_UNIX) (a probe on #2032; allowAllUnixSockets stays off). They get no password file
# and no pgenv; the test slots work for them. A cluster over TCP on 127.0.0.1 for them is
# tsk-zk2cse7s2rf7. Codex is not probed yet and keeps the cluster.
NO_TEST_CLUSTER_HARNESSES = ("claude-code",)


def gets_test_cluster(harness_id: str) -> bool:
    """Whether a placement of this harness may get a test cluster (NO_TEST_CLUSTER_HARNESSES)."""
    return harness_id not in NO_TEST_CLUSTER_HARNESSES


def pg_dir(scratch: Path | None) -> Path | None:
    """MAITY_PG_DIR inside the scratch, or None without a scratch or when the cluster's socket
    would not fit a Unix socket path there: the session then gets no MAITY_PG_DIR, its script
    falls back to its default, which the sandbox refuses, and the runner's log says so."""
    if scratch is None:
        return None
    pg = scratch / PG
    if len(os.fsencode(pg)) + 1 + PG_SOCKET_ROOM > SOCKET_PATH_MAX:
        return None
    return pg


def run_env(scratch: Path | None) -> dict[str, str]:
    """MAITY_RUN_SLOTS_DIR inside the placement's scratch. The test cluster's MAITY_PG_DIR is
    not here: `pgenv` sets it together with its password (pg_launch), so a session never has
    one without the other and with_postgres.sh never makes a cluster with trust in the scratch."""
    if scratch is None:
        return {}
    return {"MAITY_RUN_SLOTS_DIR": str(scratch / SLOTS)}


def pg_launch(ctx: Context, launched: Launch, beside: bool = True) -> Launch:
    """`launched` started through `pgenv` where the session gets a test cluster: a scratch
    beside the clone whose cluster socket fits (pg_dir), and a password file the runner vouched
    for. The launcher reads the password from the holder outside the sandbox and sets
    MAITY_PG_DIR and MAITY_PG_PASSWORD in its own process environment for the session (the
    review of #2032): never on a command line, in `launched.env` (which tmux keeps in its
    session environment) or in the loop's spec."""
    pg = pg_dir(ctx.scratch) if beside and gets_test_cluster(ctx.harness.id) else None
    if ctx.pg_pass is None or pg is None or not ctx.as_user.here:
        return launched
    root = ctx.pg_pass.parent.parent
    # This interpreter's module, never `maity runner …`: an agent's `maity` runs outside its
    # sandbox, so pgenv is no `maity` subcommand (the review of #2032). An ssh host, whose
    # interpreter the runner does not know, gets no test cluster (above).
    argv = [sys.executable, "-I", "-m", "maity.runner.pgenv", str(root), str(ctx.pg_pass),
            str(pg), "--", *launched.argv]  # fmt: skip
    return Launch(argv, launched.env, launched.resumed)


@dataclass(frozen=True)
class Launch:
    argv: list[str]
    env: dict[str, str]
    # The start continues the harness's last conversation (`ctx.resume` where the harness
    # can); False: a fresh session, which `reported.sessions` counts (§15.7).
    resumed: bool = False


def launch(ctx: Context) -> Launch:
    # The test slots and cluster go in a scratch beside the clone only: agy's `/tmp` scratch is
    # read-only to it but for `tmp` (the review of #2032), so agy keeps the scripts' defaults.
    beside = ctx.harness.id not in TMP_SCRATCH_HARNESSES
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
        # Its scratch, and temporary files inside it, so a review's or a test's leftovers go
        # when the placement ends instead of piling up in the agents' home (§15.5).
        **({"MAITY_SCRATCH": str(ctx.scratch)} if ctx.scratch is not None else {}),
        **({"TMPDIR": str(tmp)} if (tmp := session_tmpdir(ctx)) is not None else {}),
        # Claude Code's own temp files and sandbox socket beside that `tmp` (own_tmp_env).
        **own_tmp_env(ctx),
        # The test slots and test cluster in the scratch, and who takes them (tools/run_slot.sh).
        **run_env(ctx.scratch if beside else None),
        **({"MAITY_RUN_NAME": name} if (name := run_name(ctx.placement)) is not None else {}),
        **skill_env(ctx),
    }
    # The mark that this clone runs under the runner: maity refuses its git here when the
    # session's variables are gone (clonecheck.placement_root), instead of trusting that.
    ctx.as_user.mkdir(ctx.clone / ".git" / "maity")
    ctx.as_user.write(ctx.clone / clonecheck.MARKER_PATH, ctx.placement["id"] + "\n")
    # Which directory `.git` is: the sandbox does not keep the agent from renaming it, so
    # maity outside the sandbox takes `.git` only as this one, by device and inode
    # (clonecheck.opened_git).
    device, inode = ctx.as_user.dev_inode(ctx.clone / ".git")
    env[clonecheck.GIT_DEVICE_ENV] = str(device)
    env[clonecheck.GIT_INODE_ENV] = str(inode)
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
    # Whether `maity gh`'s lead commands are granted here; the role is checked per call.
    ctx.as_user.write(records / ghpr.LEAD, lead_record(ctx))
    # Where maity also reads a file the agent names (inclone): its scratch, or nowhere.
    scratch_record = f"{ctx.scratch}\n" if ctx.scratch is not None else ""
    ctx.as_user.write(records / clonecheck.SCRATCH_RECORD, scratch_record)
    return pg_launch(ctx, _harness_launch(ctx, env), beside)


def _harness_launch(ctx: Context, env: dict[str, str]) -> Launch:
    harness = ctx.harness
    if harness.id == "stub":
        return Launch(stub.argv(harness.stub_exit_code, harness.stub_run_seconds, ctx.as_user), env)
    if harness.id == "claude-code":
        return _claude_code(ctx, env)
    if harness.id == "codex":
        return _codex(ctx, env)
    if harness.id == "opencode":
        return _opencode(ctx, env)
    if harness.id == "antigravity":
        return _antigravity(ctx, env)
    raise NotYet(f"no adapter for {harness.id}")


def headless(ctx: Context) -> bool:
    """A supervised placement: the harness runs without a person at the pane (§6.2)."""
    return ctx.placement.get("mode") != "interactive"


def _write(ctx: Context, path: Path, data: Any) -> Path:
    """A file for the agents' side, written as the agents' user (§7.6)."""
    return ctx.as_user.write(path, json.dumps(data, indent=2) + "\n")


def _supervised(
    ctx: Context,
    first: list[str],
    again: list[str],
    env: dict[str, str],
    *,
    reap: bool = False,
) -> Launch:
    """The loop of §6.2 in the pane; what it runs comes from a spec file it cannot widen. With
    `reap`, the loop runs each turn in a process group of its own and ends that group when the
    turn ends, so no background process the turn started outlives it (§6.2); it is scoped to
    that one run's group and reaches no other session's processes (loop.py)."""
    policy = ctx.restart
    spec = _write(ctx, ctx.agent_dir / "loop.json",
        {
            "first": first,
            "again": again,
            "env": env,
            "clone": str(ctx.clone),  # where `maity wait` runs: agy starts above it
            # Every turn in its own process group, ended when the turn ends: no background
            # task may hold a supervised run open past its turn, and the prompt that forbids
            # `maity wait` is not relied on (cli/context/runner.md).
            **({"reap_process_group": True} if reap else {}),
            # agy's workspace folder, checked before every run as before the start (§15.5).
            **({"folder": str(ctx.folder)} if ctx.folder is not None else {}),
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


def own_tmp_leaf(ctx: Context) -> Path | None:
    """The leaf of the placement's own TMPDIR under the per-user `/tmp` parent, to open again
    in its sandbox: only when that TMPDIR is the one the session gets (session_tmpdir), so the
    sandbox never opens a leaf the session does not use. Codex's profile opens the whole leaf;
    Claude Code's settings open its `tmp` (claude_settings); Claude Code keeps its own files in
    the leaf beside it (own_tmp_env)."""
    own = own_tmpdir_in_use(ctx)
    return None if own is None else own.parent


def scratch_holder(scratch: Path | None) -> Path | None:
    """The `.scratch` that holds `scratch` under the workspaces root (workspace.scratch_of): the
    one holder of every scratch, `<root>/.scratch` for `<root>/.scratch/<project>/<id>`
    (tsk-c7zzd440x8pn), or the project's own for the former `<root>/<project>/.scratch/<id>`
    (an ssh host whose `maity` has no holder op). None for no scratch or one elsewhere (agy's
    under `/tmp`)."""
    if scratch is None:
        return None
    if scratch.parent.name == SCRATCH:
        return scratch.parent
    if scratch.parent.parent.name == SCRATCH:
        return scratch.parent.parent
    return None


def _shared_tmp(ctx: Context) -> list[str]:
    """The agy per-user `/tmp` scratch parent to hide from this placement's sandbox, as a list
    for a deny rule; empty for an agy placement (which owns it) or where there is none."""
    return [str(ctx.tmp_scratch_parent)] if ctx.tmp_scratch_parent is not None else []


def python_tools_dirs(ctx: Context) -> tuple[str, ...]:
    """The grant's `python_tools` a Claude Code session gets as rules, or none. Only with the
    sandbox on, where the runner's PreToolUse hook runs, and only where that hook is this
    runner's own code (`as_user.here`): on an ssh host it is the host's `maity`, which may not
    know the arguments, and a hook that fails refuses every call (cli/context/runner.md)."""
    if not ctx.sandbox or not ctx.as_user.here:
        return ()
    return ctx.grant.python_tools


def claude_settings(ctx: Context) -> dict[str, Any]:
    """The grant (§6.1): maity, git, the repository's own allow list, and file tools inside
    the clone and the placement's scratch only. Absolute paths take a double slash in Claude
    Code's rules. The clone's credential is neither readable nor writable through the file
    tools."""
    ws = str(ctx.clone)
    allow = ["Bash(maity *)", *(f"Bash(git {sub})" for sub in GIT_SUBCOMMANDS)]
    allow += [f"Bash(git {sub} *)" for sub in GIT_SUBCOMMANDS]
    # The same subcommands through `git -C <clone>`, which agents working from a sibling
    # directory (a package subfolder, another clone's path) need. Scoped to this clone's exact
    # path, never `git -C *`: a free `-C` would point git at any repository. The `-C` form
    # carries the same denies as plain git (mirrored below), so it is gated no more and no less
    # than `git <sub>` (tsk-66zyvc4xnhtv).
    allow += [f"Bash(git -C {ws} {sub})" for sub in GIT_SUBCOMMANDS]
    allow += [f"Bash(git -C {ws} {sub} *)" for sub in GIT_SUBCOMMANDS]
    allow += [f"Bash({cmd})" for cmd in ctx.grant.allow if config.plain_command(cmd)]
    # The repository's own Python tools (`python_tools`): `python3 <dir>/<name>.py …` from the
    # clone's root. Claude Code's `*` also matches `..` or a second command, so the runner's
    # hook holds such a line to that exact form (plaincall.python_tool); hence only where the
    # hook runs with these directories (python_tools_dirs). The sandbox stays the boundary.
    for tool_dir in python_tools_dirs(ctx):
        allow += [f"Bash(python3 {tool_dir}/*.py)", f"Bash(python3 {tool_dir}/*.py *)"]
    allow += [f"{tool}(/{ws}/**)" for tool in ("Read", "Edit", "Write")]
    if ctx.scratch is not None:  # the placement's scratch (§15.5), for the file tools too
        allow += [f"{tool}(/{ctx.scratch}/**)" for tool in ("Read", "Edit", "Write")]
    if ctx.skill is not None:
        # The delivered skill's references (skills.py), read only: the skill sends the agent to
        # them, and without this rule a read outside the clone and the scratch is refused.
        allow += [f"Read(/{ctx.skill}/**)"]
    # The dev venvs the runner built (venvs.py): the clone's `<sub>/.venv` links to them.
    allow += [f"Read(/{venv}/**)" for venv in ctx.venvs]
    # Agents commit through git and never edit what makes git run something (GIT_PROTECTED).
    # Not all of .git: the sandbox turns an Edit deny into a write deny for every command, and
    # git could no longer fetch or commit. The credential is not readable through Read.
    # `Edit(…)` covers every file-editing tool; Claude Code ignores a `Write(…)` deny rule.
    git = f"{ws}/.git"
    deny = [f"Edit(/{git}/{name}{'/**' if name in ('hooks', 'info') else ''})"
            for name in GIT_PROTECTED]  # fmt: skip
    deny += [f"Edit(/{git}/maity/**)", f"Read(/{git}/maity/**)"]
    if ctx.skill is not None:  # never written from the session, whatever another rule allows
        deny += [f"Edit(/{ctx.skill}/**)"]
    # A venv the runner built is never written from the session: the runner builds the next one
    # beside it and runs nothing from a venv the session could have reached (venvs.py).
    deny += [f"Edit(/{venv}/**)" for venv in ctx.venvs]
    deny += [f"Bash({rule})" for rule in
             (*GIT_DENIED, *GIT_WORKTREE_DENIED, *GH_DENIED, *MAITY_RUNNER_DENIED)]  # fmt: skip
    # The same git escapes through `git -C <clone>` (the allow forms above), mirrored so a deny
    # wins over the `git -C <clone> <sub> *` allow: every git deny begins `git `, replaced here by
    # `git -C <clone> ` (tsk-66zyvc4xnhtv).
    deny += [f"Bash(git -C {ws} {rule[len('git '):]})" for rule in
             (*GIT_DENIED, *GIT_WORKTREE_DENIED)]  # fmt: skip
    deny += list(CLAUDE_WORKTREE_DENIED)  # every placement, with or without the sandbox
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
    hooks: dict[str, Any] = {}
    # No git worktree in the clone, sandbox or not (CLAUDE_WORKTREE_HOOK): a hook that fails or
    # gives no path fails the worktree's creation. Only for a version known to have the event
    # (capabilities.CLAUDE_WORKTREE_HOOK_MIN); without it the two denies above stand alone.
    if capabilities.worktree_hook_version_ok(ctx.version):
        hooks["WorktreeCreate"] = [
            {"hooks": [{"type": "command", "command": CLAUDE_WORKTREE_HOOK}]},
        ]
    if ctx.sandbox:
        # The placement's own TMPDIR in a leaf under the agy per-user `/tmp` parent, when it is
        # the session's (tsk-k7svzz2p4v7y): its `tmp` is re-opened for reading and writing, and
        # the parent is denied for reading only. A write deny on the parent mounts the re-opened
        # `tmp` read-only (Claude Code 2.1.329), and is not what keeps a sibling leaf out: under
        # the read deny's empty mount it does not exist in the sandbox, and a write there lands
        # in that mount alone (the ops probe P4, 2026-11-21).
        own = own_tmpdir_in_use(ctx)
        writable = [str(p) for p in (ctx.scratch, own) if p is not None]
        # The holder of every scratch, `<root>/.scratch`, the same way (tsk-07dwr3t80rg0,
        # tsk-c7zzd440x8pn): denied for reading only, its own scratch opened again, so a scratch
        # of any project made after this session started lies under the read deny's empty mount
        # instead of staying readable. Never in denyWrite (it would mount the re-opened scratch
        # read-only, as for the leaf); the holder is not writable from the sandbox anyway, since
        # writes are allowed only where allowWrite says. The former per-project `.scratch` and
        # the other entries are hidden whole (ctx.private); on a host with the former layout
        # the project's `.scratch` is the holder denied here.
        holder = scratch_holder(ctx.scratch)
        readable = [*([str(ctx.scratch)] if holder is not None else []),
                    *([str(own)] if own is not None else [])]  # fmt: skip
        settings["sandbox"] = {
            "enabled": True,
            "failIfUnavailable": True,  # never fall back to unsandboxed commands
            "allowUnsandboxedCommands": False,  # no dangerouslyDisableSandbox retry
            "autoAllowBashIfSandboxed": False,  # the allowlist above still decides
            # Unix sockets stay blocked (the seccomp step), pinned here: this file wins over the
            # agents' user's settings, which may not carry socket settings at all
            # (capabilities.SOCKET_SETTINGS).
            "network": {"allowedDomains": sorted({*ctx.hosts, *ctx.grant.network}),
                        "strictAllowlist": True, "allowAllUnixSockets": False},
            # Repository code run by an allowed build or test command cannot read or replace
            # the clone's credential, other clones' or the runner's; `maity` alone, which
            # signs with it, runs outside.
            # Not the workspaces root: re-opening this clone inside it (`allowRead`) could
            # re-open its credential as well, and that order is unverified here.
            # The agy per-user `/tmp` scratch parent is hidden, so a placement that is not its
            # owner cannot reach another placement's scratch there: from reading always, and from
            # writing too unless the placement's own TMPDIR is re-opened under it (above).
            "filesystem": {"denyRead": [f"{git}/maity", *(str(p) for p in ctx.private),
                                        *_shared_tmp(ctx),
                                        *([str(holder)] if holder is not None else [])],
                           # The private paths are not writable either: the runner's files
                           # (~/.maity-runner on an ssh host) are what `maity runner` takes.
                           "denyWrite": [f"{git}/maity",
                                         *(f"{git}/{name}" for name in GIT_PROTECTED),
                                         *(str(p) for p in ctx.private),
                                         *(_shared_tmp(ctx) if own is None else []),
                                         # The delivered skill (skills.py): read, never written.
                                         *([str(ctx.skill)] if ctx.skill is not None else []),
                                         # The dev venvs (venvs.py): read and run, never written.
                                         *(str(venv) for venv in ctx.venvs)],
                           # Commands write the placement's scratch besides the clone (§15.5),
                           # and its own TMPDIR; both are read again under their hidden parents.
                           **({"allowWrite": writable} if writable else {}),
                           **({"allowRead": readable} if readable else {})},
            "excludedCommands": ["maity *"],
        }  # fmt: skip
        # `maity` runs outside the sandbox only as one plain call: the hook refuses a line
        # that starts with `maity` and holds anything else (plaincall). It runs for every
        # tool, outside the sandbox, from the runner's own code; a hook that fails or times
        # out refuses the call (`onFailure`, Claude Code 2.1.295 and later: the sandbox is not
        # switched on for an older one, capabilities.sandbox_version_ok). Shell form, so a
        # version that predates exec form runs it too; `|| exit 2` refuses on any version
        # when the hook cannot start or fails.
        words = ctx.as_user.runner_module("plaincall")
        if python_tools_dirs(ctx):
            # What the hook holds a python3 tool line to: this clone, its tool directories, and
            # the paths the session may write besides it, where no accepted python3 may lie: the
            # scratch, and the whole leaf of its own TMPDIR (own_tmp_leaf), not only the `tmp`
            # in it, since Claude Code opens its own `claude-<uid>/` beside that `tmp` to the
            # session's commands (own_tmp_env).
            words += ["--clone", ws]
            for tool_dir in python_tools_dirs(ctx):
                words += ["--python-tools", tool_dir]
            for path in (ctx.scratch, own_tmp_leaf(ctx)):
                if path is not None:
                    words += ["--writable", str(path)]
        module = " ".join(shlex.quote(word) for word in words)
        hook = f"{module} || exit 2"
        hooks["PreToolUse"] = [
            {"hooks": [{"type": "command", "command": hook, "timeout": 30,
                        "onFailure": "block"}]},
        ]  # fmt: skip
    if hooks:
        settings["hooks"] = hooks
        # Over a `true` in the agents' user settings, which would leave the hooks unrun; it also
        # turns on that user's own hooks (cli/context/runner.md).
        settings["disableAllHooks"] = False
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


def codex_left_out(grant: config.RepositoryGrant) -> list[str]:
    """The parts of a repository's grant a Codex placement starts without, each with why
    (cli/context/runner.md): Codex has no command allowlist, and its `maity` runs inside its
    sandbox, not outside it as `maity gh` needs. Only with its sandbox on: without it, a
    grant with any of these parts refuses the start (supervisor `_refusal`)."""
    left = []
    if grant.allow:
        listed = ", ".join(repr(rule) for rule in grant.allow)
        left.append(
            f"allow {listed} is not applied to codex: Codex has no command allowlist, so "
            "every command runs in its sandbox, listed or not (refused without the sandbox)"
        )
    if grant.pull_requests:
        left.append(
            "pull_requests is not given to codex: its `maity` runs inside its sandbox, and "
            "the runner sets up `maity gh` only for a `maity` outside it"
        )
    if grant.lead:
        left.append("lead is not given to codex, for the same reason as pull_requests")
    return left


def pull_requests_record(ctx: Context) -> str:
    """The content of the runner's record `ghpr.PULL_REQUESTS`: the placement's repository
    and the runner's PATH (its absolute entries) when the grant has pull requests, else
    empty. Always empty for Codex (codex_left_out). `maity gh` looks gh up on that PATH at
    each call, so a gh installed after the session started is found without a restart
    (tsk-2k0jcaxfd0ja, point 15); the record, not the session's own PATH, says where."""
    if not ctx.grant.pull_requests or ctx.harness.id == "codex":
        return ""
    workspace = ctx.placement.get("workspace") or {}
    repository = config.normalise_repository(workspace.get("repository") or "")
    if not repository:
        return ""
    # Whole entries, in PATH's order, as many as fit the size `maity gh` reads
    # (ghpr.RECORD_MAX; review A2160 of #2125): the earlier ones are the ones that win.
    room = ghpr.RECORD_MAX - len(f"{repository}\n\n".encode())
    kept: list[str] = []
    for entry in (e for e in proc.search_path().split(os.pathsep) if e):
        if len(os.pathsep.join([*kept, entry]).encode()) > room:
            break
        kept.append(entry)
    return f"{repository}\n{os.pathsep.join(kept)}\n"


def lead_record(ctx: Context) -> str:
    """The content of the runner's record `ghpr.LEAD`: `lead` when the grant has `lead` and
    the pull-request record is written (`pull_requests_record`: never for Codex), else empty,
    which also clears one a former grant left. The member's role is the hub's, read by
    `maity gh` at each call, not decided here."""
    return "lead\n" if ctx.grant.lead and pull_requests_record(ctx) else ""


def _sandbox_prompt(ctx: Context) -> str:
    """What the start prompt adds. Claude Code's `dontAsk` allowlist is set for every placement
    (claude_settings), sandbox or not, so a claude-code session always gets the command-phrasing
    guidance; the git-config notice and the `maity`-alone hint are only about the sandbox (the
    unwritable `.git/config`, the plaincall hook); with the grant's pull requests, `maity gh`."""
    pulls = PULL_REQUEST_PROMPT if pull_requests_record(ctx) else ""
    is_claude = ctx.harness.id == "claude-code"
    command = CLAUDE_COMMAND_PROMPT if is_claude else ""
    if not writes_denied(ctx):
        return command + pulls
    maity = CLAUDE_MAITY_PROMPT if is_claude else ""
    return GIT_PROMPT + maity + command + pulls


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


def managed(ctx: Context) -> bool:
    """The runner installs or updates this harness's tool (§15.16)."""
    return ctx.harness.install or ctx.harness.update != "never"


def _claude_code(ctx: Context, env: dict[str, str]) -> Launch:
    assert ctx.binary is not None  # noqa: S101 - the supervisor checked the probe
    if managed(ctx):  # the runner swaps versions (§15.16); the tool never updates itself
        env = {**env, "DISABLE_UPDATES": "1"}
    # Claude Code's background-shell memory-pressure reaper would otherwise kill the interactive
    # placement's background `maity wait` under low memory, leaving the session running but no
    # longer listening until its lease expired (KtW b1e8643a-320b-481c-9fea-97303c6d3177). Set
    # on the base env so it reaches both the interactive and the supervised launch; older Claude
    # Code ignores the unknown variable, so it is unconditional. Harmless in headless, where
    # background tasks are already disabled (below) and there is no background shell to reap.
    env = {**env, "CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP": "1"}
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
    if ctx.skill is not None:  # the Keep the Why skill for this session only (skills.py)
        base += [f"--plugin-dir={ctx.skill}"]
    model = ctx.placement.get("model")
    if model:
        base += ["--model", model]
    if ctx.placement.get("mode") == "interactive":
        trust_clone(ctx)
        if ctx.resume:  # `--continue`: the clone's latest conversation, with its context
            return Launch([*base, "--continue", RESUME_PROMPT], env, resumed=True)
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


def outermost(paths: Sequence[Path], opened: Sequence[Path] = ()) -> tuple[Path, ...]:
    """`paths` without those another of them already hides, in their order. Codex's sandbox
    (bwrap) hides a path by mounting over it; a path inside one hidden before has nowhere to
    be mounted ("Can't create file … Read-only file system"), and every command fails. A
    path is dropped only when nothing in `opened` (a more specific rule that opens a
    directory again: the clone's, the scratch's) lies between it and the hidden one that
    contains it: there the outer path no longer hides it, and it stays listed. Compared as
    given: the runner lists them resolved where it can (supervisor.private_paths)."""
    unique = tuple(dict.fromkeys(paths))

    def hidden_by(p: Path, q: Path) -> bool:
        return q in p.parents and not any(
            q in r.parents and (r == p or r in p.parents) for r in opened
        )

    return tuple(p for p in unique if not any(hidden_by(p, q) for q in unique))


def codex_home(ctx: Context) -> Path:
    """Codex's per-placement CODEX_HOME. Inside the placement scratch (§15.5) when it has one,
    so it lies under the workspaces root the codex sandbox re-opens for this placement (and
    hides from every other placement): there Codex's own sandbox can read and run its
    per-command helper (`CODEX_HOME/tmp/arg0-linux`). The home is read-only to the session
    (the runner writes its control files once, below), so the sandbox reads and executes the
    helper, it does not create it. Under the runner's state directory the sandbox hides the
    home (bwrap mounts over it), and then Codex runs no command at all, so `maity resume`
    never starts (card tsk-hv7jbgy75zjt). Without a scratch (no workspaces root to carve, or
    one that could not be made) it stays in the runner's directory as before, where the
    sandbox hides it; `maity runner check` verifies from the local configuration that Codex is
    given a scratch and the workspaces root is outside the state directory, but does not catch
    a runtime fall-back to no scratch."""
    return codex_home_of(ctx.scratch, ctx.agent_dir)


def codex_home_of(scratch: Path | None, agent_dir: Path) -> Path:
    """`codex_home` from its two parts, for a caller without a Context: the start's daemon stop
    (codexd) names the same home the launch env then sets."""
    if scratch is not None:
        return scratch / "codex-home"
    return agent_dir / "codex-home"


def codex_config(ctx: Context) -> str:
    """`config.toml` in the placement's own CODEX_HOME (§6.1): Codex's sandbox with the
    workspace profile, the clone's `.git` writable (commits need it), no approvals asked,
    network to the hub, the forge and the model provider only."""
    hosts = sorted({*ctx.hosts, *CODEX_PROVIDER_HOSTS, *ctx.grant.network})
    domains = "".join(f'{json.dumps(host)} = "allow"\n' for host in hosts)
    # Unreadable: other clones (the workspaces root), the runner's state and the secrets in
    # the agents' home. The clone's own rules are more specific and win; its credential
    # stays readable, since the agent's `maity` runs inside the sandbox. Every directory
    # opened again below (the clone, the scratch) keeps a hidden path inside it listed.
    # The placement's own TMPDIR leaf (Context.tmpdir) is opened again under the hidden per-user
    # `/tmp` parent, as the scratch is under the hidden workspaces root (tsk-0zb9mgzmbwn4).
    own_tmp = own_tmp_leaf(ctx)
    reopened = (ctx.clone, *(p for p in (ctx.scratch, own_tmp) if p is not None))
    # The agy per-user `/tmp` scratch parent is hidden too (its own scratch sits beside the
    # clone, so Codex has no need to reach `/tmp`'s scratch of another placement of this user).
    shared = (ctx.tmp_scratch_parent,) if ctx.tmp_scratch_parent is not None else ()
    roots = outermost((*((ctx.workspaces,) if ctx.workspaces else ()), *ctx.private, *shared),
                      opened=reopened)  # fmt: skip
    hidden = "".join(f'{json.dumps(str(path))} = "none"\n' for path in roots)
    # The placement's effort, a top-level key before any table. In this file, not a `-c` flag:
    # a resume reads the same home, so the first start and every resume run the same level.
    effort = ctx.placement.get("effort")
    return (
        'approval_policy = "never"\n'
        'default_permissions = "maity"\n'
        # One poll covers Maity's 600-second wait with time for the response (docs/agents.md).
        "background_terminal_max_timeout = 660000\n"
        + (f"model_reasoning_effort = {json.dumps(effort)}\n" if effort else "")
        # A version the runner manages is never swapped by Codex itself (§15.16).
        + ("check_for_update_on_startup = false\n" if managed(ctx) else "") + "\n"
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
        f"{json.dumps(str(ctx.clone / '.git' / 'config'))} = \"read\"\n"
        # The placement's scratch (§15.5), under the hidden workspaces root, opened again.
        + (f'{json.dumps(str(ctx.scratch))} = "write"\n' if ctx.scratch is not None else "")
        # Its own TMPDIR leaf, under the hidden per-user `/tmp` parent, opened again.
        + (f'{json.dumps(str(own_tmp))} = "write"\n' if own_tmp is not None else "")
        # Codex's own CODEX_HOME sits inside that writable scratch (codex_home), so the profile
        # names it read, not write: a sandboxed command may read the home — its config.toml,
        # any rules file, the auth.json link, and the per-command helper under tmp, which it
        # also runs — but may write nothing there. The runner writes those control files once
        # before the session starts; the session cannot rewrite the configuration a later
        # restart reads. Read also keeps the home reachable (not hidden), so the helper stays
        # readable and runnable. The same single source builds the launch env's CODEX_HOME, so
        # the two never drift. Omitted when there is no scratch to carve: CODEX_HOME then stays
        # in the runner's directory, which this profile hides, and `maity runner check` verifies
        # the configuration before a placement starts (Codex is given a scratch, the workspaces
        # root is outside the state directory), though a runtime fall-back to no scratch is
        # beyond what it catches.
        + (f'{json.dumps(str(codex_home(ctx)))} = "read"\n' if ctx.scratch is not None else "")
        + "\n"
        "[permissions.maity.network]\nenabled = true\n\n"
        "[permissions.maity.network.domains]\n" + domains
        # Nobody answers a headless run: the question tool is not offered (cli/context/runner.md).
        + ("\n[tools.experimental_request_user_input]\nenabled = false\n" if headless(ctx) else "")
    )


def codex_skill(ctx: Context, home: Path) -> bool:
    """The delivered Keep the Why skill as `<CODEX_HOME>/skills/keep-the-why/`, which Codex
    loads as its own skill `keep-the-why` with no setting (ops, nte-nqs227hnpqzz, Codex 0.171.0),
    written from the runner's checked copy by skillop on the agents' side at every launch. The
    home is read-only to the session (codex_config), so the skill is too; Codex's own `.system/`
    beside it is left alone. Only with a scratch: without one the home lies in the runner's own
    directory, which the sandbox hides. Whether it was written: a failure leaves the session
    with `MAITY_KTW_SKILL_DIR` alone, which is how Codex had the skill before.

    A launch that writes no skill (none named, or one that could not be written) removes a copy
    an earlier launch left in a reused home, so Codex never loads a skill this launch did not
    hand it (the review of #2093). That removal is best effort: if it fails too, the earlier
    copy stays, one the runner wrote from a checked copy."""
    if ctx.scratch is None:
        return False
    errors = (OSError, ValueError, KeyError, subprocess.SubprocessError, skillop.Mismatch)
    if ctx.skill_source is not None:
        try:
            payload = skillop.payload(ctx.skill_source, ctx.skill_source.name)
            scratch.write_codex_skill(home, payload, ctx.as_user)
            return True
        except errors:
            pass
    with contextlib.suppress(*errors):
        scratch.clear_codex_skill(home, ctx.as_user)
    return False


def _codex(ctx: Context, env: dict[str, str]) -> Launch:
    assert ctx.binary is not None  # noqa: S101 - the supervisor checked the probe
    home = codex_home(ctx)
    config_text = codex_config(ctx)
    # The login of whoever runs the agents (the operator, or the agents' user), linked so
    # that a token refresh lands in the original; a link left from an earlier launch that
    # points elsewhere, or nowhere, is replaced. Linked only when there is a login to link.
    own = None if not ctx.as_user.direct else os.environ.get("CODEX_HOME")
    login = Path(own or ctx.as_user.home() / ".codex") / "auth.json"
    auth = login if ctx.as_user.exists(login, "-f") else None
    if ctx.scratch is not None:
        # The home sits in the agent-writable scratch: its control files are written to a
        # descriptor opened without following a link from the workspaces root, so a codex-home
        # swapped for a link is refused, never written through, out of the scratch.
        scratch.write_codex_home(home, config_text, auth, ctx.as_user)
        codex_skill(ctx, home)
    else:
        # No scratch to carve: the home stays in the runner's own directory, below no
        # agent-writable parent, so the plain writes are safe there.
        ctx.as_user.write(home / "config.toml", config_text)
        if auth is not None:
            ctx.as_user.link(auth, home / "auth.json")
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
    # After the allows: the last match wins. The rules are meant to allow `maity` only as one
    # plain call, as the Claude Code hook has it (plaincall). Without a sandbox these rules are
    # not a boundary, see cli/context/runner.md.
    for rule in (*GIT_DENIED, *GIT_WORKTREE_DENIED, *GH_DENIED, *MAITY_RUNNER_DENIED):
        bash.pop(rule, None)  # a grant's allow of the same pattern would keep its earlier place
        bash[rule] = "deny"
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
            # grep and glob cannot be scoped to a path here, so they are off.
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
    # No model on the placement: fall back to the harness default (config validates it is one
    # of `models`). Fail closed when the effective model is empty or not among `models`: with
    # no model, opencode runs its own default, a provider-`opencode`, opencode-hosted model,
    # so the clone's content would go to opencode's servers instead of the configured provider
    # (cli/context/runner.md, the opencode model fail-closed). Checked before anything is
    # written, for both modes.
    model = ctx.placement.get("model") or ctx.harness.default_model
    if not model or model not in ctx.harness.models:
        raise NotYet(
            f"opencode model {model!r} is not among the configured models "
            f"{ctx.harness.models!r}: refusing the start rather than letting opencode run its "
            f"own default, which would send the conversation to opencode's servers"
        )
    # The model is the configuration's top-level `model` for both modes: opencode 2.3's TUI
    # (no subcommand) has no `--model` and exits on it (tsk-daa6e0gfncg0). `opencode run`
    # still takes `--model`, so a supervised run carries it twice, the same value.
    path = _write(ctx, ctx.agent_dir / "opencode.json", {**opencode_config(ctx), "model": model})
    # Without the switch the repository's opencode.json wins over OPENCODE_CONFIG, and its
    # .opencode/ directories bring agents, commands and plugins.
    env = {**env, "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_CONFIG": str(path)}
    prompt = START_PROMPT + _sandbox_prompt(ctx)
    # The flags here are the ones `maity runner check` probes for (capabilities.OPENCODE_FLAGS).
    if ctx.placement.get("mode") == "interactive":
        # `--standalone`: without it 2.3's TUI attaches to the user's shared background service
        # (`opencode serve --service`), which has its own configuration, so neither
        # OPENCODE_CONFIG (the model, the rules) nor OPENCODE_DISABLE_PROJECT_CONFIG reaches it
        # (ops' live check, nte-mmnz3mk1247c).
        return Launch([ctx.binary, "--standalone", str(ctx.clone), "--prompt", prompt], env)
    # `opencode run` has no `--dir`: it works in its working directory, the clone, where the
    # session starts (a workspace.Workspace's `path`; opencode has no workspace folder) and the
    # loop's runs inherit it. `--continue` is that directory's last conversation.
    first = [ctx.binary, "run", "--model", model, prompt]
    again = [ctx.binary, "run", "--model", model, "--continue", prompt]
    return _supervised(ctx, first, again, env)


# --- Antigravity (agy) ------------------------------------------------------------------------

# agy starts in the workspace folder, one level above the clone, so it loads none of the
# clone's own agy configuration; the project's `AGENTS.md` is then not loaded either and is
# named here (§15.3, cli/context/runner.md).
AGY_FOLDER_PROMPT = (
    "You start in a workspace folder that holds the project's clone as `{repo}` and nothing "
    "else. Run `cd {repo}` first and work only in the clone: read `{repo}/AGENTS.md`, and run "
    "`maity`, `git` and every other command there. Leave nothing in this folder besides "
    "`{repo}`: the runner does not start you again while anything else is there. "
)
# `maity` may leave agy's sandbox only as the command its allow rule names; a chained line is
# refused outside the sandbox (the agy entry in cli/context/runner.md).
AGY_MAITY_PROMPT = (
    " Run every `maity` command alone, as one plain call, not piped or chained with other "
    "commands; pass longer text in a file in the clone (`--body-file`)."
)
# agy's sign-in, a file in its directory under the agents' home when there is no keyring. The
# rest of `~/.gemini` stays readable to agy's own sandbox, which keeps its scratch there.
AGY_LOGIN = Path(".gemini") / "antigravity-cli" / "antigravity-oauth-token"
# What agy's command rules match by prefix: GIT_DENIED without its globs, and gh.
AGY_DENIED_COMMANDS = ("git -c", "git --config-env", "git --exec-path", "gh", "maity runner")


# Why a command grant is not given to agy as a rule. agy does not match a `command(...)` rule
# the way Claude Code matches `Bash(...)`: it reads the invoked command from the line, past a
# leading environment assignment or command wrapper, before any rule is compared, so neither
# an exact entry nor a ` *` prefix entry can be reproduced for it the way Claude Code applies a
# grant. Both are left out and run in agy's sandbox like every unlisted command (the agy
# grants entry in cli/context/runner.md).
AGY_COMMAND_LEFT_OUT = "agy does not match a command grant the way Claude Code does"


@dataclass(frozen=True)
class AgyGrants:
    """The command grants mapped for agy: every one is left out with why. agy gets no
    `command(...)` allow from them; `maity runner check` names those it leaves out."""

    left_out: tuple[tuple[str, str], ...] = ()


def _agy_prefix(words: list[str]) -> list[str] | None:
    """The words before a closing ` *`, when no other word holds a `*`."""
    if len(words) > 1 and words[-1] == "*" and not any("*" in word for word in words[:-1]):
        return words[:-1]
    return None


def agy_grants(rules: Sequence[str]) -> AgyGrants:
    """agy reads the invoked command from a line, stepping over a leading environment
    assignment or command wrapper, before it compares any `command(...)` rule, so a rule
    cannot say what Claude Code's grant says. Neither an exact entry (`a b`) nor a ` *` prefix
    entry (`a b *`) is given to agy: each is left out, named by `maity runner check`, and runs
    in agy's sandbox like every unlisted command. An entry with another `*` (`a *.py`,
    `npm run test:*`) is left out without a word, since a rule word is matched on its own, so
    no rule says what it says. agy therefore gets no `command(...)` allow from a grant's
    command list; only `command(maity)` and the non-command grants stand."""
    left_out: list[tuple[str, str]] = []
    for rule in dict.fromkeys(rules):
        words = rule.split(" ")
        if "*" in rule and _agy_prefix(words) is None:
            continue  # another `*`, not a closing ` *`: left out without a word, as before
        left_out.append((rule, AGY_COMMAND_LEFT_OUT))
    return AgyGrants(tuple(left_out))


def _agy_private(path: Path) -> Path:
    """A path no file tool may touch: as given, but for agy's own directory only its login."""
    return path.parent / AGY_LOGIN if path.name == ".gemini" else path


def antigravity_settings(ctx: Context) -> dict[str, Any]:
    """The session's settings (`--settings`, never saved; §15.3): the agent mode `accept-edits`
    for an interactive start, so the file tools' edits are accepted without a prompt, and the
    empty default mode for a supervised one; never `auto`, whose reviewer may let a command
    leave the sandbox. Commands no rule names run in the sandbox without asking; the sandbox
    on; the workspace folder trusted, so an interactive start asks nothing. Allowed: `maity`,
    URLs of the hub, the forge and the grant's `network` hosts, and reads of the delivered
    skill; no `write_file` allow.
    A grant's `allow` command list is not given to agy (agy_grants):
    agy does not match a `command(...)` rule the way Claude Code does, so each such entry is
    left out and runs in agy's sandbox, named by `maity runner check`.

    Denied: the clone's credential (`.git/maity`), writing what makes git run something
    (GIT_PROTECTED), the other clones' credentials, the runner's private paths and writing the
    delivered skill. agy merges these with the agents' user's own settings
    (cli/context/runner.md)."""
    assert ctx.folder is not None  # noqa: S101 - the supervisor gives agy its folder
    git = ctx.clone / ".git"
    allow = ["command(maity)"]
    allow += [f"read_url({host})" for host in sorted({*ctx.hosts, *ctx.grant.network})]
    # agy's sandbox shows only what a rule mounts: a `read_file` allow mounts the delivered skill
    # read-only, and its write deny below still wins (the agy settings entry in
    # cli/context/runner.md). No `write_file` allow is given: the clone's `.git` stays as agy's
    # sandbox mounts it until a live probe shows its denies hold inside a writable mount.
    if ctx.skill is not None:  # the delivered skill, read through MAITY_KTW_SKILL_DIR, not written
        allow += [f"read_file({ctx.skill})"]
    denied = [git / "maity", *(_agy_private(path) for path in ctx.private)]
    deny = [f"{tool}({path})" for path in denied for tool in ("read_file", "write_file")]
    deny += [f"write_file({git / name})" for name in GIT_PROTECTED]
    if ctx.skill is not None:
        deny += [f"write_file({ctx.skill})"]
    deny += [f"command({cmd})" for cmd in AGY_DENIED_COMMANDS]
    return {
        # `accept-edits` auto-accepts the file tools' edits in interactive mode; supervised
        # runs headless and needs no auto-accept, so it keeps the empty default mode.
        "agentMode": "accept-edits" if not headless(ctx) else "",
        "toolPermission": "proceed-in-sandbox",
        "enableTerminalSandbox": True,
        "trustedWorkspaces": [str(ctx.folder)],
        "permissions": {"allow": allow, "deny": deny},
    }


def _antigravity(ctx: Context, env: dict[str, str]) -> Launch:
    assert ctx.binary is not None  # noqa: S101 - the supervisor checked the probe
    assert ctx.folder is not None  # noqa: S101 - the supervisor gives agy its folder
    settings = _write(ctx, ctx.agent_dir / "agy-settings.json", antigravity_settings(ctx))
    # agy takes the work tree from $PWD: the folder's real path (workspace.check_folder).
    env = {**env, "PWD": str(ctx.folder)}
    base = [ctx.binary, "--settings", str(settings)]
    model = ctx.placement.get("model")
    if model:
        base += ["--model", model]
    # In `base`, so the first command and every continued one run the same level. A model id
    # that carries an effort of its own is passed as it is beside it: agy decides (§15.5).
    effort = ctx.placement.get("effort")
    if effort:
        base += ["--effort", effort]
    folder = AGY_FOLDER_PROMPT.format(repo=ctx.clone.name)
    extra = AGY_MAITY_PROMPT + _sandbox_prompt(ctx)
    if ctx.placement.get("mode") == "interactive":
        if ctx.resume:  # `-c`: the folder's latest conversation, so this placement's
            return Launch([*base, "-c", "-i", RESUME_PROMPT], env, resumed=True)
        return Launch([*base, "-i", folder + START_PROMPT + extra], env)
    # `-c` continues the latest conversation of the working directory: the placement's own
    # folder, so never another placement's (cli/context/runner.md).
    prompt = folder + SUPERVISED_PROMPT + extra
    # agy has no setting or environment variable to keep a background task from outliving the
    # turn (unlike Claude Code's CLAUDE_CODE_DISABLE_BACKGROUND_TASKS); the loop ends the
    # turn's own process group instead (reap, §6.2).
    return _supervised(ctx, [*base, "-p", prompt], [*base, "-c", "-p", prompt], env, reap=True)
