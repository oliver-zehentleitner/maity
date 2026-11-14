"""A placed session commits as the runner's `[git]` identity and runs the checks its grant
names (tsk-z27pwcfr03wm, cli/context/runner.md). Run against the permission lists the
adapters really write (`claude_settings`, `opencode_config`) and a real git."""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import pytest

from maity.runner import adapters, config

DOCS = Path(__file__).resolve().parents[2] / "docs" / "runners.md"
TEAM = config.GitIdentity("Your Team", "team@example.org", configured=True)
PLACEMENT = {"id": "plc-0007", "mode": "supervised"}  # headless: no folder trust in HOME


def context(tmp_path: Path, harness_id: str = "claude-code", **overrides: Any) -> adapters.Context:
    harness = config.Harness(harness_id, ("interactive", "supervised"), "supervised")
    agent_dir = tmp_path / "st" / "agents" / "plc-0007"
    agent_dir.mkdir(parents=True, mode=0o700)
    data: dict[str, Any] = {
        "placement": PLACEMENT, "harness": harness, "binary": f"/usr/bin/{harness_id}",
        "clone": tmp_path / "ws" / "demo" / "agent-7", "agent_dir": agent_dir,
        "grant": config.RepositoryGrant(), "restart": config.Restart(), "git": TEAM,
    }  # fmt: skip
    data.update(overrides)
    return adapters.Context(**data)


def claude_allows(settings: dict[str, Any], command: str) -> bool:
    """Claude Code's Bash rules as its documentation describes them: `*` stands for any text,
    a trailing ` *` also for no arguments at all, and a matching deny wins over any allow."""

    def matches(rule: str) -> bool:
        if not (rule.startswith("Bash(") and rule.endswith(")")):
            return False
        pattern, tail = rule[5:-1], ""
        if pattern.endswith(" *"):
            pattern, tail = pattern[:-2], "( .*)?"
        regex = ".*".join(re.escape(part) for part in pattern.split("*")) + tail
        return re.fullmatch(regex, command, re.DOTALL) is not None

    rules = settings["permissions"]
    return not any(map(matches, rules["deny"])) and any(map(matches, rules["allow"]))


def opencode_allows(cfg: dict[str, Any], command: str) -> bool:
    """opencode's bash rules: `*` stands for any text, and the last matching rule wins."""
    verdict = "deny"
    for pattern, action in cfg["permission"]["bash"].items():
        regex = ".*".join(re.escape(part) for part in pattern.split("*"))
        if re.fullmatch(regex, command, re.DOTALL):
            verdict = action
    return verdict == "allow"


def git(*args: str, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)


def placed_clone(tmp_path: Path, gitconfig: str) -> tuple[adapters.Context, dict[str, str]]:
    """A clone the runner started a sandboxed Claude Code session in, and the environment
    that session's git sees: an agents' home whose `.gitconfig` is `gitconfig`, no system
    configuration, and `.git/config` locked as the sandbox keeps it."""
    home, remote = tmp_path / "home", tmp_path / "remote.git"
    home.mkdir()
    (home / ".gitconfig").write_text(gitconfig)
    base = {"PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
            "LANG": "C", "LC_ALL": "C"}  # fmt: skip
    seed = {**base, "GIT_AUTHOR_NAME": "seed", "GIT_AUTHOR_EMAIL": "seed@example.org",
            "GIT_COMMITTER_NAME": "seed", "GIT_COMMITTER_EMAIL": "seed@example.org"}  # fmt: skip
    ctx = context(tmp_path, sandbox=True)
    ctx.clone.parent.mkdir(parents=True)
    for args in (
        ("init", "-q", "--bare", str(remote)),
        ("clone", "-q", str(remote), str(ctx.clone)),
    ):
        assert git(*args, cwd=tmp_path, env=seed).returncode == 0
    assert (
        git("commit", "-q", "--allow-empty", "-m", "seed", cwd=ctx.clone, env=seed).returncode == 0
    )
    assert (
        git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=ctx.clone, env=seed).returncode == 0
    )
    env = {**base, **adapters.launch(ctx).env}
    (ctx.clone / ".git" / "config.lock").write_text("")  # the sandbox: no write to .git/config
    return ctx, env


# --- 1. the session's git identity comes from the runner ------------------------------------


@pytest.mark.parametrize("harness_id", ["claude-code", "codex", "opencode"])
def test_every_session_gets_the_runners_identity_as_author_and_committer(
    tmp_path: Path, harness_id: str
) -> None:
    env = adapters.launch(context(tmp_path, harness_id)).env
    assert {key: env.get(key) for key in adapters.git_identity(context(tmp_path / "x"))} == {
        "GIT_AUTHOR_NAME": "Your Team", "GIT_AUTHOR_EMAIL": "team@example.org",
        "GIT_COMMITTER_NAME": "Your Team", "GIT_COMMITTER_EMAIL": "team@example.org",
    }  # fmt: skip


def test_the_runners_identity_wins_over_the_agents_users_own(tmp_path: Path) -> None:
    """In the `single` layout the agents' home is the operator's, and its `.gitconfig` names
    the operator. A placed session commits as `[git]` all the same, author and committer."""
    personal = "[user]\n\tname = Operator Person\n\temail = operator@example.com\n"
    ctx, env = placed_clone(tmp_path, personal)
    done = git("commit", "-q", "--allow-empty", "-m", "work", cwd=ctx.clone, env=env)
    assert done.returncode == 0, done.stderr
    who = git("log", "-1", "--format=%an <%ae>|%cn <%ce>", cwd=ctx.clone, env=env).stdout.strip()
    assert who == "Your Team <team@example.org>|Your Team <team@example.org>"


def test_without_a_git_table_the_session_commits_as_the_generic_default(tmp_path: Path) -> None:
    ctx = context(tmp_path, git=config.GitIdentity())
    env = adapters.launch(ctx).env
    assert (env["GIT_AUTHOR_NAME"], env["GIT_AUTHOR_EMAIL"]) == (
        "Maity agent",
        "maity-agent@invalid",
    )
    assert (env["GIT_COMMITTER_NAME"], env["GIT_COMMITTER_EMAIL"]) == (
        "Maity agent", "maity-agent@invalid",
    )  # fmt: skip


# --- 2. plain commit and the push to a named branch work ------------------------------------


def test_plain_commit_and_push_to_a_named_branch_work_in_a_placed_session(tmp_path: Path) -> None:
    """The runner VM's agents' user has no git identity at all (cbt4, 2026-11-11: "empty ident
    name"); `useConfigOnly` stands in for that here, so git guesses none. Both commands are
    allowed by the lists the adapters write, and both run with the session's environment."""
    ctx, env = placed_clone(tmp_path, "[user]\n\tuseConfigOnly = true\n")
    commit = "git commit -m work"
    push = "git push origin HEAD:refs/heads/agent-7/work"
    settings, opencode = adapters.claude_settings(ctx), adapters.opencode_config(ctx)
    for command in (commit, push):
        assert claude_allows(settings, command), command
        assert opencode_allows(opencode, command), command
    done = git("commit", "-q", "--allow-empty", "-m", "work", cwd=ctx.clone, env=env)
    assert done.returncode == 0, done.stderr
    done = git("push", "-q", "origin", "HEAD:refs/heads/agent-7/work", cwd=ctx.clone, env=env)
    assert done.returncode == 0, done.stderr
    pushed = git("log", "-1", "--format=%an", "agent-7/work", cwd=tmp_path / "remote.git", env=env)
    assert pushed.stdout.strip() == "Your Team"


# --- 3. the agent cannot pick an identity of its own ----------------------------------------


@pytest.mark.parametrize("sandbox", [False, True])
def test_git_config_user_is_not_granted(tmp_path: Path, sandbox: bool) -> None:
    """The identity is the runner's; without a sandbox these would write `.git/config`."""
    ctx = context(tmp_path, sandbox=sandbox)
    settings, opencode = adapters.claude_settings(ctx), adapters.opencode_config(ctx)
    for command in ("git config user.name Someone", "git config user.email a@example.org",
                    "git config user.name"):  # fmt: skip
        assert not claude_allows(settings, command), command
        assert not opencode_allows(opencode, command), command
    assert claude_allows(settings, "git status") and opencode_allows(opencode, "git status")


# --- 4. the checks docs/runners.md grants a Python repository -------------------------------


def docs_grant() -> dict[str, Any]:
    """The `[repositories."…"]` example of docs/runners.md that grants a Python repository's
    checks, parsed as TOML."""
    blocks = re.findall(r"```toml\n(.*?)```", DOCS.read_text(encoding="utf-8"), re.DOTALL)
    found = [block for block in blocks if "[repositories." in block and "pytest" in block]
    assert len(found) == 1, "docs/runners.md: one TOML example granting a repository's checks"
    return tomllib.loads(found[0])


def test_the_python_checks_in_the_runner_docs_reach_both_allowlists(tmp_path: Path) -> None:
    raw = {
        "hub": {"url": "https://hub.example", "state_dir": "/srv/state"},
        "limits": {"projects": ["you/demo"], "repositories": ["github.com/you/demo"]},
        "harness": {"claude-code": {}},
        **docs_grant(),
    }
    cfg = config.parse(raw, Path("runner.toml"))
    (grant,) = cfg.repositories.values()
    assert {"python3 -m pytest *", "ktw-lint *", "black *", "ruff *", "mypy *"} <= set(grant.allow)
    ctx = context(tmp_path, grant=grant)
    settings, opencode = adapters.claude_settings(ctx), adapters.opencode_config(ctx)
    for command in ("python3 -m pytest -q tests", "ktw-lint .", "black --check src tests",
                    "ruff check src", "mypy src"):  # fmt: skip
        assert claude_allows(settings, command), command
        assert opencode_allows(opencode, command), command
    # A grant names a check, not the interpreter: plain `python3` stays refused.
    assert not claude_allows(settings, "python3 -c print(1)")
    assert not opencode_allows(opencode, "python3 -c print(1)")
