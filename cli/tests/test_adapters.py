from __future__ import annotations

import dataclasses
import fnmatch
import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest
from conftest import OPENCODE_23_RUN, OPENCODE_23_TUI, opencode_23_flags

from maity import __version__, clonecheck, ghpr
from maity.runner import adapters, config, loop, scratch, scratchop, supervisor
from maity.runner.asuser import AsUser, Ssh

PLACEMENT = {"id": "plc-0003", "mode": "interactive", "model": "opus"}
# Under the sandbox: the git commands that fail, and `maity` alone.
SANDBOXED = adapters.GIT_PROMPT + adapters.CLAUDE_MAITY_PROMPT


def context(tmp_path: Path, harness_id: str = "claude-code", **overrides: Any) -> adapters.Context:
    harness = config.Harness(harness_id, ("interactive", "supervised"), "interactive", ("opus",))
    agent_dir = tmp_path / "st" / "agents" / "plc-0003"
    agent_dir.mkdir(parents=True, mode=0o700)
    data: dict[str, Any] = {
        "placement": PLACEMENT, "harness": harness, "binary": "/usr/bin/claude",
        "clone": tmp_path / "ws" / "maity" / "agent-3", "agent_dir": agent_dir,
        "grant": config.RepositoryGrant(allow=("make test",)), "restart": config.Restart(),
        "version": "2.1.325",  # a probed Claude Code with the WorktreeCreate event
    }  # fmt: skip
    data.update(overrides)
    return adapters.Context(**data)


def test_claude_code_interactive(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    launch = adapters.launch(ctx)
    argv = launch.argv
    assert argv[0] == "/usr/bin/claude"
    assert argv[-1] == adapters.START_PROMPT  # no sandbox: nothing about git or `maity` alone
    assert argv[argv.index("--setting-sources") + 1] == "user"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in argv and argv[argv.index("--model") + 1] == "opus"
    settings = Path(argv[argv.index("--settings") + 1])
    assert settings.parent == ctx.agent_dir  # the runner's, outside the clone
    mcp = [a for a in argv if a.startswith("--mcp-config")]
    assert len(mcp) == 1 and mcp[0].startswith("--mcp-config=")
    assert json.loads(Path(mcp[0].split("=", 1)[1]).read_text()) == {"mcpServers": {}}
    # No MAITY_SUPERVISOR: nothing wakes an interactive session, so the hub must not tell it
    # to stop waiting (the first runner test of 0.1.0a8: the agents went away after each turn).
    assert launch.env == {
        "MAITY_PLACEMENT": "plc-0003", "GIT_COMMON_DIR": str(ctx.clone / ".git"),
        clonecheck.GIT_INODE_ENV: str(os.lstat(ctx.clone / ".git").st_ino),
        clonecheck.GIT_PRIVATE_ENV: str(ctx.agent_dir / "git"),
        # The reaper opt-out is on every claude-code placement (test below for both modes).
        "CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP": "1",
        **adapters.SESSION_GIT_CONFIG,
        **adapters.git_identity(ctx),  # `[git]`, here its default (test_session_identity.py)
    }  # fmt: skip


def test_claude_code_interactive_resumes_its_conversation_after_hung(tmp_path: Path) -> None:
    launch = adapters.launch(context(tmp_path, resume=True))
    assert launch.argv[-2:] == ["--continue", adapters.RESUME_PROMPT]
    assert adapters.START_PROMPT not in launch.argv


def test_claude_code_interactive_without_a_model_ends_the_mcp_option_before_the_prompt(
    tmp_path: Path,
) -> None:
    """Claude Code's `--mcp-config` takes several values. Given as a separate argument, the
    start prompt right after it (no `--model` between) was read as a second configuration file,
    and Claude Code exited 1 at once (2.1.319, the first runner test)."""
    ctx = context(tmp_path, placement={"id": "plc-0003", "mode": "interactive"})
    argv = adapters.launch(ctx).argv
    assert argv[-1] == adapters.START_PROMPT and "--model" not in argv
    assert argv[-2].startswith("--mcp-config=") and "--mcp-config" not in argv


def test_claude_code_interactive_records_the_clone_as_trusted_and_nothing_else(
    tmp_path: Path,
) -> None:
    """Claude Code 2.1.319 asked "Is this a project you created or one you trust?" on its first
    start in a fresh clone and waited, so the agent never ran `maity resume` (the first runner
    test, 2026-11-09). The placement is the trust decision: the clone's entry is recorded in
    the agents' Claude Code configuration, the rest of the file stays as it was."""
    home = Path.home()  # the test's own (conftest)
    before = {"numStartups": 3, "projects": {"/other": {"hasTrustDialogAccepted": False}}}
    (home / ".claude.json").write_text(json.dumps(before))
    ctx = context(tmp_path)
    ctx.clone.mkdir(parents=True)
    adapters.launch(ctx)
    after = json.loads((home / ".claude.json").read_text())
    assert after == {**before, "projects": {
        "/other": {"hasTrustDialogAccepted": False},
        str(ctx.clone.resolve()): {"hasTrustDialogAccepted": True},
    }}  # fmt: skip


def test_claude_code_supervised_records_no_trust(tmp_path: Path) -> None:
    """Headless (`-p`), Claude Code 2.1.319 asks for no folder trust and records none."""
    ctx = context(tmp_path, placement={**PLACEMENT, "mode": "supervised"})
    adapters.launch(ctx)
    assert not (Path.home() / ".claude.json").exists()


def test_claude_code_does_not_start_when_the_trust_cannot_be_recorded(tmp_path: Path) -> None:
    """A session waiting at the trust question would pass for `running`: the start fails
    instead, with the cause in the runner's log, and the file is left as it was."""
    (Path.home() / ".claude.json").write_text("not json")
    with pytest.raises(OSError, match="not JSON"):
        adapters.launch(context(tmp_path))
    assert (Path.home() / ".claude.json").read_text() == "not json"


def test_no_harness_gets_a_granted_rule_with_something_in_front(tmp_path: Path) -> None:
    """A grant that reached the adapters without the configuration's check: of its rules,
    only the plain command reaches either harness's settings."""
    refused = ("FOO=1 make test", "FOO+=1 make test", "env make test",
               "/usr/bin/env FOO=1 make test", "make test; maity *", '"maity" *', "maity:*",
               "maity.exe *", "xargs /tmp/tools:local/maity",
               "cmd /c C:/tools/maity.exe")  # fmt: skip
    plain = dataclasses.replace(context(tmp_path), grant=config.RepositoryGrant())
    ctx = dataclasses.replace(plain, grant=config.RepositoryGrant(allow=("make test", *refused)))
    claude = adapters.claude_settings(ctx)["permissions"]["allow"]
    claude_base = adapters.claude_settings(plain)["permissions"]["allow"]
    opencode = adapters.opencode_config(ctx)["permission"]["bash"]
    opencode_base = adapters.opencode_config(plain)["permission"]["bash"]
    assert [r for r in claude if r not in claude_base] == ["Bash(make test)"]
    assert [r for r in opencode if r not in opencode_base] == ["make test", "make test *"]


def test_no_os_uuid_command_is_allowed_maity_uuid_makes_the_ids(tmp_path: Path) -> None:
    """Keep-the-Why Ids come from `maity uuid`, which runs wherever `maity` does. The exact
    `cat /proc/sys/kernel/random/uuid` allow is gone: placed Claude Code sessions refused it
    all the same (a read outside the working directories), and opencode's
    `external_directory: deny` gates that path too (cli/context/runner.md). With and without
    the sandbox, and with an empty grant, neither harness's list names a UUID source."""
    plain = dataclasses.replace(context(tmp_path), grant=config.RepositoryGrant())
    sandboxed = dataclasses.replace(
        context(tmp_path / "s", sandbox=True), grant=config.RepositoryGrant()
    )
    opencode = dataclasses.replace(
        context(tmp_path / "o", harness_id="opencode"), grant=config.RepositoryGrant()
    )
    claude_rules = [
        *adapters.claude_settings(plain)["permissions"]["allow"],
        *adapters.claude_settings(sandboxed)["permissions"]["allow"],
    ]
    bash = adapters.opencode_config(opencode)["permission"]["bash"]
    # Not a bare "uuid": tmp_path carries this test's name, and so do the file tools' rules.
    for rule in (*claude_rules, *bash):
        assert "kernel/random" not in rule and "uuidgen" not in rule, rule
    assert not hasattr(adapters, "UUID_COMMAND")

    # `maity uuid` is what replaces it: one plain `maity` call, allowed in both lists.
    def resolve(command: str) -> str:
        verdict = "deny"
        for pattern, value in bash.items():
            if fnmatch.fnmatchcase(command, pattern):
                verdict = value
        return verdict

    # In each mode on its own, not only in the two lists together (A1919).
    for ctx in (plain, sandboxed):
        assert "Bash(maity *)" in adapters.claude_settings(ctx)["permissions"]["allow"]
    assert resolve("maity uuid") == "allow"
    assert resolve("cat /proc/sys/kernel/random/uuid") == "deny"


def test_claude_code_grant(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    settings = adapters.claude_settings(ctx)
    ws = str(ctx.clone)
    allow, deny = settings["permissions"]["allow"], settings["permissions"]["deny"]
    assert "Bash(maity *)" in allow and "Bash(make test)" in allow
    assert "Bash(git *)" not in allow  # `-c`, `--no-index` and friends run or read anything
    assert "Bash(git commit *)" in allow and "Bash(git push *)" in allow
    assert "Bash(git -c *)" in deny and "Bash(git * --no-index*)" in deny
    assert "Bash(maity runner)" in deny and "Bash(maity runner *)" in deny  # S201/S202
    assert f"Edit(/{ws}/**)" in allow and f"Read(/{ws}/**)" in allow
    assert allow[-1].startswith("Write(//")  # absolute paths take the double slash
    assert f"Read(/{ws}/.git/maity/**)" in deny
    # What makes git run something, never all of .git: the sandbox makes an Edit deny a write
    # deny, and git could no longer fetch or commit (tsk-2zz5tjpbt28n).
    assert [rule for rule in deny if "/.git/" in rule] == [
        f"Edit(/{ws}/.git/config)",
        f"Edit(/{ws}/.git/config.worktree)",
        f"Edit(/{ws}/.git/hooks/**)",
        f"Edit(/{ws}/.git/info/**)",
        f"Edit(/{ws}/.git/objects/info/alternates)",
        f"Edit(/{ws}/.git/maity/**)",
        f"Read(/{ws}/.git/maity/**)",
    ]
    assert not any(rule.startswith("Write(") for rule in deny)  # Claude Code ignores those
    assert not any(rule.startswith("WebFetch") for rule in allow)
    assert settings["permissions"]["defaultMode"] == "dontAsk"
    assert "sandbox" not in settings  # no exclusion
    # Without the sandbox, the worktree hook alone: no plain-call hook.
    assert settings["hooks"] == {
        "WorktreeCreate": [
            {"hooks": [{"type": "command", "command": adapters.CLAUDE_WORKTREE_HOOK}]},
        ],
    }  # fmt: skip
    assert settings["disableAllHooks"] is False
    strict = adapters.claude_settings(
        context(tmp_path / "s", sandbox=True, hosts=("maity.team", "github.com"))
    )["sandbox"]
    assert strict["enabled"] and strict["failIfUnavailable"]
    assert strict["allowUnsandboxedCommands"] is False
    assert strict["autoAllowBashIfSandboxed"] is False  # the allowlist still decides
    assert strict["filesystem"]["denyRead"][0].endswith("/.git/maity")
    sandboxed = str(tmp_path / "s" / "ws" / "maity" / "agent-3" / ".git")
    assert strict["filesystem"]["denyWrite"] == [
        f"{sandboxed}/{name}"
        for name in (
            "maity",
            "config",
            "config.worktree",
            "hooks",
            "info",
            "objects/info/alternates",
        )
    ]
    assert not any(path.endswith("commondir") for path in strict["filesystem"]["denyWrite"])
    assert strict["excludedCommands"] == ["maity *"]  # it alone reads the credential
    assert strict["network"] == {
        "allowedDomains": ["github.com", "maity.team"],
        "strictAllowlist": True,
        "allowAllUnixSockets": False,  # pinned: the user's settings cannot open Unix sockets
    }
    assert strict["network"]["allowAllUnixSockets"] is False


def test_under_the_sandbox_every_tool_call_passes_the_plain_call_hook(tmp_path: Path) -> None:
    settings = adapters.claude_settings(context(tmp_path, sandbox=True))
    assert settings["disableAllHooks"] is False
    assert set(settings["hooks"]) == {"WorktreeCreate", "PreToolUse"}
    (entry,) = settings["hooks"]["PreToolUse"]
    assert "matcher" not in entry  # every tool, not only Bash
    (hook,) = entry["hooks"]
    assert hook["type"] == "command" and hook["onFailure"] == "block"
    # The runner's own interpreter and module, isolated from the session's environment.
    module = [sys.executable, "-I", "-m", "maity.runner.plaincall"]
    # A hook that cannot start or fails refuses the call on any version, not only with onFailure.
    assert shlex.split(hook["command"]) == [*module, "||", "exit", "2"]
    assert "args" not in hook  # shell form: also runs on a version without exec form
    remote = Ssh(name="b", address="b.lan", login="m", known_hosts=tmp_path / "k")
    remote_hook = adapters.claude_settings(context(tmp_path / "r", sandbox=True, as_user=remote))
    command = remote_hook["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    assert command == "maity runner plaincall || exit 2"  # the host's maity, as for the loop


@pytest.mark.parametrize(
    ("harness_id", "version", "ok"),
    [("claude-code", "2.1.294", False), ("claude-code", "2.1.295", True),
     ("claude-code", "2.2.0", True), ("claude-code", "3.0.0-beta", True),
     ("claude-code", "2.1.295-rc.1", False), ("claude-code", "2.1.295-dev", False),
     ("claude-code", "2.1.295+build", True), ("claude-code", "2.1.296-rc.1", True),
     ("claude-code", "2.1.295-rc.1+build.7", False), ("claude-code", "2.1.295.1", False),
     ("claude-code", "2.1.295--rc", False), ("claude-code", "2.1.295-x-y", False),
     ("claude-code", "02.1.295", False), ("claude-code", "2.1.0295", False),
     ("claude-code", "2.1.296-01", False), ("claude-code", "2.1.296-rc..1", False),
     ("claude-code", "2.1.295+", False), ("claude-code", "2.1.295+b..1", False),
     ("claude-code", "2.1.296-0.rc-1+b-2", True),
     ("claude-code", None, False), ("claude-code", "2.1", False), ("claude-code", "x", False),
     ("codex", None, True)],
)  # fmt: skip
def test_claude_codes_sandbox_needs_the_hook_failure_policy(
    harness_id: str, version: str | None, ok: bool
) -> None:
    from maity.runner import capabilities

    assert capabilities.sandbox_version_ok(harness_id, version) is ok


@pytest.mark.parametrize("mode", ["interactive", "supervised"])
@pytest.mark.parametrize("sandbox", [False, True])
def test_a_placed_claude_code_session_makes_no_git_worktree(
    tmp_path: Path, mode: str, sandbox: bool
) -> None:
    """While a worktree is in the clone maity runs no git there, and the session cannot remove
    it (tsk-d5e4d9s95ytj). Every placement: EnterWorktree denied by its bare name, and a
    WorktreeCreate hook that fails, which fails a subagent's `isolation: worktree` too. No
    `Agent(isolation:…)` parameter rule: not verified on the hosted Claude Code yet, and a rule
    a binary cannot read could cost the whole file (cli/context/runner.md)."""
    ctx = context(tmp_path, placement={**PLACEMENT, "mode": mode}, sandbox=sandbox)
    adapters.launch(ctx)
    written = json.loads((ctx.agent_dir / "claude-settings.json").read_text())
    assert written == adapters.claude_settings(ctx)
    deny = written["permissions"]["deny"]
    assert "EnterWorktree" in deny
    assert {"Bash(git worktree)", "Bash(git worktree *)"} <= set(deny)  # from the shell too
    assert not any(rule.startswith("Agent(") for rule in deny)
    assert written["disableAllHooks"] is False  # the agents' user settings cannot turn it off
    (entry,) = written["hooks"]["WorktreeCreate"]
    assert "matcher" not in entry
    (hook,) = entry["hooks"]
    assert hook == {"type": "command", "command": adapters.CLAUDE_WORKTREE_HOOK}
    # Claude Code takes the hook's stdout as the worktree's path: it must fail and print none.
    payload = json.dumps({"hook_event_name": "WorktreeCreate", "name": "agent-x"})
    done = subprocess.run(["sh", "-c", hook["command"]], input=payload, capture_output=True,
                          text=True, check=False, timeout=60)  # fmt: skip
    assert done.returncode != 0 and done.stdout == ""
    assert "worktree" in done.stderr


@pytest.mark.parametrize(
    "version", [None, "2.1.40", "2.1.49", "2.1.50-rc.1", "dev build"]
)  # fmt: skip
@pytest.mark.parametrize("sandbox", [False, True])
def test_claude_code_without_the_worktree_event_gets_the_denies_alone(
    tmp_path: Path, version: str | None, sandbox: bool
) -> None:
    """The WorktreeCreate event is there from 2.1.50 (its release notes, as cited in review
    A1808; not verified against a live binary): an older or
    unknown version gets no hook, only the two denies, which a binary that does not know the
    name takes as harmless. Without the sandbox no hook is left, so `disableAllHooks` is not
    written either, and the agents' user's own switch stands as before."""
    settings = adapters.claude_settings(context(tmp_path, version=version, sandbox=sandbox))
    deny = settings["permissions"]["deny"]
    assert "EnterWorktree" in deny and "Bash(git worktree *)" in deny
    assert "WorktreeCreate" not in settings.get("hooks", {})
    if sandbox:
        assert list(settings["hooks"]) == ["PreToolUse"] and settings["disableAllHooks"] is False
    else:
        assert "hooks" not in settings and "disableAllHooks" not in settings
    floor = adapters.claude_settings(context(tmp_path / "f", version="2.1.50"))
    assert "WorktreeCreate" in floor["hooks"]


def test_no_other_harness_gets_the_worktree_rules(tmp_path: Path) -> None:
    """The tool deny and the hook are Claude Code's alone. `git worktree` is denied for the
    harnesses with a command allowlist, Claude Code and opencode, also over a grant that allows
    it; codex and agy have none to add it to."""
    codex = adapters.codex_config(context(tmp_path / "x", harness_id="codex"))
    # A second allow after it: without moving the denies to the end, `make check`'s allows would
    # come after the `git worktree` deny in opencode's map.
    worktree_grant = config.RepositoryGrant(allow=("git worktree", "make check"))
    o_ctx = context(tmp_path / "o", harness_id="opencode", grant=worktree_grant)
    bash = adapters.opencode_config(o_ctx)["permission"]["bash"]
    a_ctx = context(tmp_path / "a", "antigravity", folder=tmp_path / "a" / "ws" / "folder")
    agy = json.dumps(adapters.antigravity_settings(a_ctx))
    for text in (codex, json.dumps(bash), agy):
        assert "EnterWorktree" not in text and "WorktreeCreate" not in text
    assert "git worktree" not in codex and "git worktree" not in agy
    order = list(bash)
    for rule in adapters.GIT_WORKTREE_DENIED:  # denied, after every allow: the last match wins
        assert bash[rule] == "deny"
        assert all(bash[key] == "deny" for key in order[order.index(rule) :])

    def resolve(rules: dict[str, str], command: str) -> str:  # opencode: the last match wins
        verdict = "deny"
        for pattern, value in rules.items():
            if fnmatch.fnmatchcase(command, pattern):  # `*` matches spaces too, as opencode's
                verdict = value
        return verdict

    for command in ("git worktree add x", "git worktree"):
        assert resolve(bash, command) == "deny", command
    assert resolve(bash, "make check") == "allow" and resolve(bash, "git status") == "allow"
    claude = adapters.claude_settings(context(tmp_path / "c", grant=worktree_grant))
    assert "Bash(git worktree)" in claude["permissions"]["allow"]  # the grant, as written
    assert "Bash(git worktree)" in claude["permissions"]["deny"]  # and the deny, which wins


def test_the_worktree_deny_matches_only_the_subcommand(tmp_path: Path) -> None:
    """The known gap and its cover: the deny does not match `git -C <dir> worktree …`, but with
    no grant nothing allows that line either (opencode's default deny; no Claude Code allow rule,
    and dontAsk refuses the rest). And a line that only mentions the word stays allowed: a
    wildcard before `worktree` in the deny would have refused it (review A1807)."""

    def patterns(rules: list[str]) -> list[str]:
        return [rule[len("Bash(") : -1] for rule in rules if rule.startswith("Bash(")]

    def resolve(rules: dict[str, str], command: str) -> str:  # opencode: the last match wins
        verdict = "deny"
        for pattern, value in rules.items():
            if fnmatch.fnmatchcase(command, pattern):
                verdict = value
        return verdict

    no_grant = config.RepositoryGrant()
    claude = adapters.claude_settings(context(tmp_path / "c", grant=no_grant))["permissions"]
    allow, deny = patterns(claude["allow"]), patterns(claude["deny"])
    o_ctx = context(tmp_path / "o", harness_id="opencode", grant=no_grant)
    bash = adapters.opencode_config(o_ctx)["permission"]["bash"]
    assert claude["defaultMode"] == "dontAsk"

    gap = "git -C . worktree add x"
    assert not any(fnmatch.fnmatchcase(gap, pattern) for pattern in deny)  # the gap
    assert not any(fnmatch.fnmatchcase(gap, pattern) for pattern in allow)  # refused anyway
    assert [key for key in bash if fnmatch.fnmatchcase(gap, key)] == ["*"]  # the default alone
    assert resolve(bash, gap) == "deny"

    for command, allowed_by in (
        ("git log --grep worktree --all", "git log *"),
        ('git commit -m "runner: no git worktree in its clone"', "git commit *"),
    ):
        assert not any(fnmatch.fnmatchcase(command, pattern) for pattern in deny), command
        assert allowed_by in allow and fnmatch.fnmatchcase(command, allowed_by)
        assert resolve(bash, command) == "allow", command


def test_the_hook_refuses_when_it_cannot_start(tmp_path: Path) -> None:
    """The shell form's `|| exit 2`: a missing module or interpreter is exit 2, a refusal."""
    hook = adapters.claude_settings(context(tmp_path, sandbox=True))["hooks"]["PreToolUse"]
    command = hook[0]["hooks"][0]["command"].replace("maity.runner.plaincall", "maity.nowhere")
    done = subprocess.run(["sh", "-c", command], input="{}", capture_output=True, text=True,
                          check=False, timeout=60)  # fmt: skip
    assert done.returncode == 2


def test_the_plain_call_hook_is_a_runner_command(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    import io

    from maity import cli

    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": "maity a | x"}})
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(payload.encode())))
    assert cli.main(["runner", "plaincall"]) == 2
    assert "one plain call" in capsys.readouterr().err


def test_claude_code_supervised_runs_the_loop(tmp_path: Path) -> None:
    ctx = context(tmp_path, placement={**PLACEMENT, "mode": "supervised", "model": None})
    launch = adapters.launch(ctx)
    assert launch.argv[1:4] == ["-I", "-m", "maity.runner.loop"]
    spec = json.loads(Path(launch.argv[-1]).read_text())
    assert spec["first"][-2:] == ["-p", adapters.SUPERVISED_PROMPT]
    assert spec["env"]["MAITY_SUPERVISOR"] == f"maity-runner/{__version__}"
    assert spec["again"][-1] == "--continue" and "--model" not in spec["first"]
    assert spec["env"]["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert spec["restart"]["crash_cap"] == 5


def test_claude_code_disables_the_bg_shell_pressure_reaper_for_both_modes(tmp_path: Path) -> None:
    # The reaper would kill the interactive placement's background `maity wait` under low memory,
    # so the start env carries the opt-out for both the interactive and the supervised launch.
    interactive = adapters.launch(context(tmp_path))
    assert interactive.env["CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP"] == "1"
    sup = adapters.launch(context(tmp_path / "s", placement={**PLACEMENT, "mode": "supervised"}))
    spec = json.loads(Path(sup.argv[-1]).read_text())
    assert spec["env"]["CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP"] == "1"
    # Scoped to Claude Code: another harness's start env does not carry it.
    codex = context(tmp_path / "c", harness_id="codex", binary="/usr/bin/codex")
    assert "CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP" not in adapters.launch(codex).env


def test_the_sandboxed_session_prompt_and_git_settings(tmp_path: Path) -> None:
    ctx = context(tmp_path, sandbox=True, placement={**PLACEMENT, "mode": "supervised"})
    launch = adapters.launch(ctx)
    spec = json.loads(Path(launch.argv[-1]).read_text())
    assert spec["first"][-1] == adapters.SUPERVISED_PROMPT + SANDBOXED
    assert spec["env"]["GIT_CONFIG_COUNT"] == "5"
    keys = {spec["env"][f"GIT_CONFIG_KEY_{i}"]: spec["env"][f"GIT_CONFIG_VALUE_{i}"]
            for i in range(5)}  # fmt: skip
    assert keys == {"core.fsmonitor": "false", "diff.ignoreSubmodules": "all",
                    "branch.autoSetupMerge": "false", "push.default": "current",
                    "fetch.recurseSubmodules": "false"}  # fmt: skip
    codex = context(tmp_path / "c", harness_id="codex", binary="/usr/bin/codex", sandbox=True)
    assert adapters.launch(codex).argv[-1] == adapters.START_PROMPT + adapters.GIT_PROMPT


def test_without_a_sandbox_the_clone_git_configuration_stands(tmp_path: Path) -> None:
    """Without a sandbox `.git/config` is writable, and the session leaves the repository's
    own tracking, push and submodule settings alone (review of #1663)."""
    clone = tmp_path / "clone"
    subprocess.run(["git", "init", "-q", str(clone)], check=True, capture_output=True)
    for key, value in (("branch.autoSetupMerge", "true"), ("push.default", "simple"),
                       ("fetch.recurseSubmodules", "on-demand")):  # fmt: skip
        subprocess.run(["git", "-C", str(clone), "config", key, value], check=True)
    env = {**os.environ, **adapters.launch(context(tmp_path, clone=clone)).env}
    for key, value in (("branch.autoSetupMerge", "true"), ("push.default", "simple"),
                       ("fetch.recurseSubmodules", "on-demand")):  # fmt: skip
        got = subprocess.run(["git", "-C", str(clone), "config", "--get", key], env=env,
                             capture_output=True, text=True, check=True)  # fmt: skip
        assert got.stdout.strip() == value


def test_the_session_git_needs_no_configuration_write(tmp_path: Path) -> None:
    """The sandbox keeps `.git/config` unwritable (config.lock is held), so tracking a remote
    branch on `switch -c` failed and an upstream could not be stored (the first runner test of
    0.1.0a8). With the session's settings a branch is cut, committed and pushed without one."""
    remote, clone = tmp_path / "remote.git", tmp_path / "clone"
    sandboxed = context(tmp_path, sandbox=True)
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@b", "GIT_COMMITTER_NAME": "a",
           "GIT_COMMITTER_EMAIL": "a@b"}  # fmt: skip

    def git(*args: str, cwd: Path = clone, session: bool = True) -> None:
        extra = adapters.git_config(sandboxed) if session else {}
        subprocess.run(["git", *args], cwd=cwd, env={**env, **extra}, check=True,
                       capture_output=True)  # fmt: skip

    git("init", "-q", "--bare", str(remote), cwd=tmp_path, session=False)
    git("clone", "-q", str(remote), str(clone), cwd=tmp_path, session=False)
    git("commit", "-q", "--allow-empty", "-m", "one", session=False)
    git("push", "-q", "origin", "HEAD:refs/heads/main", session=False)
    git("fetch", "-q", "origin", session=False)
    before = (clone / ".git" / "config").read_text()
    (clone / ".git" / "config.lock").write_text("")
    if os.name != "nt":  # the sandbox's unreadable placeholder; fetch must not read it
        (clone / ".gitmodules").write_text("")
        (clone / ".gitmodules").chmod(0)
    done = subprocess.run(["git", "fetch", "origin"], cwd=clone,
                          env={**env, **adapters.git_config(sandboxed)},
                          capture_output=True, text=True, check=True)  # fmt: skip
    assert ".gitmodules" not in done.stderr
    git("switch", "-q", "-c", "work", "origin/main")
    git("commit", "-q", "--allow-empty", "-m", "two")
    git("push", "-q")
    assert (clone / ".git" / "config").read_text() == before
    assert (remote / "refs" / "heads" / "work").is_file()


def test_the_sandbox_placeholders_are_hidden_and_other_lines_kept(tmp_path: Path) -> None:
    ctx = context(tmp_path, sandbox=True)
    exclude = ctx.clone / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text("# git's own comment\n*.tmp\n")
    (ctx.clone / ".claude" / "agents").mkdir(parents=True)  # empty: Claude Code makes these
    adapters.launch(ctx)
    adapters.launch(ctx)  # a second start replaces the block, it does not add another
    lines = exclude.read_text().splitlines()
    assert lines[:2] == ["# git's own comment", "*.tmp"]
    assert lines.count(adapters.EXCLUDE_BEGIN) == 1
    assert lines[3:-1] == [f"/{name}" for name in adapters.CLAUDE_PLACEHOLDERS]


def test_real_content_at_a_placeholder_path_stays_visible(tmp_path: Path) -> None:
    """Untracked files of the agent's own at those paths are not placeholders, and hiding
    them would hide real work (review of #1663). A block from an earlier start is rebuilt, so
    content that appeared since shows again."""
    ctx = context(tmp_path, sandbox=True)
    clone = ctx.clone
    subprocess.run(["git", "init", "-q", str(clone)], check=True, capture_output=True)
    adapters.launch(ctx)  # nothing there yet: every path is hidden
    assert "/.gitmodules" in (clone / ".git" / "info" / "exclude").read_text()
    (clone / ".gitmodules").write_text("[submodule]\n")
    (clone / ".mcp.json").write_text("{}\n")
    (clone / ".claude" / "skills").mkdir(parents=True)
    (clone / ".claude" / "skills" / "real.md").write_text("a skill\n")
    adapters.launch(ctx)
    lines = (clone / ".git" / "info" / "exclude").read_text().splitlines()
    assert {"/.gitmodules", "/.mcp.json", "/.claude/skills"}.isdisjoint(lines)
    assert "/.bashrc" in lines
    status = subprocess.run(["git", "-C", str(clone), "status", "--porcelain",
                             "--untracked-files=all"], capture_output=True, text=True,
                            check=True).stdout  # fmt: skip
    assert {"?? .gitmodules", "?? .mcp.json", "?? .claude/skills/real.md"} <= set(
        status.splitlines()
    )


def test_without_a_sandbox_the_exclude_file_is_left_alone(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    exclude = ctx.clone / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text("*.tmp\n")
    adapters.launch(ctx)
    assert exclude.read_text() == "*.tmp\n"


def test_extra_environment_reaches_the_session(tmp_path: Path) -> None:
    ctx = context(tmp_path, extra_env={"MAITY_MACHINE": "m-1"})
    assert adapters.launch(ctx).env["MAITY_MACHINE"] == "m-1"


def test_harnesses_without_an_adapter_yet(tmp_path: Path) -> None:
    with pytest.raises(adapters.NotYet):
        adapters.launch(context(tmp_path, harness_id="pi"))


# --- the supervised loop ---------------------------------------------------------------------


class Script:
    def __init__(self, runs: list[int], waits: list[tuple[int, str, str]]) -> None:
        self.runs, self.waits = list(runs), list(waits)
        self.ran: list[list[str]] = []
        self.clock = 0.0
        self.slept: list[float] = []

    def run(self, argv: list[str], env: dict[str, str]) -> int:
        self.ran.append(argv)
        self.clock += 5
        return self.runs.pop(0)

    def wait(self) -> tuple[int, str, str]:
        if not self.waits:
            raise SystemExit(99)
        return self.waits.pop(0)

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.clock += seconds


SPEC = {"first": ["first"], "again": ["again"], "env": {},
        "restart": {"initial": 10, "factor": 2.0, "max": 300, "crash_window": 1800,
                    "crash_cap": 3, "quick_exit": 60}}  # fmt: skip


def event(seq: int) -> tuple[int, str, str]:
    return (0, json.dumps({"seq": seq}), "")


def run(script: Script) -> int:
    looped = loop.Loop(
        SPEC,
        script.run,
        script.wait,
        sleep=script.sleep,
        now=lambda: script.clock,
        rand=lambda: 0.5,
        log=lambda line: None,
    )
    try:
        return looped.main()
    except SystemExit as stop:
        return int(stop.code or 0)


def test_a_quick_clean_answer_is_progress() -> None:
    script = Script([0, 0, 0], [event(5), (3, "", ""), event(6)])
    assert run(script) == 99
    assert script.ran == [["first"], ["again"], ["again"]]
    assert script.slept == [loop.SETTLE, loop.SETTLE]


def test_runs_that_leave_their_event_unread_end_in_a_hot_loop() -> None:
    script = Script([0] * 5, [event(5), event(5), event(5), event(5)])
    assert run(script) == loop.EXIT_HOT_LOOP


def test_failing_runs_back_off_and_end_in_a_hot_loop() -> None:
    script = Script([1, 1, 1], [])
    assert run(script) == loop.EXIT_HOT_LOOP
    assert script.slept[0] == 10  # the runner's backoff, not a spin
    assert script.ran == [["first"], ["again"], ["again"]]


def test_a_failed_run_is_run_again_without_waiting_for_an_event() -> None:
    script = Script([1, 0], [])
    assert run(script) == 99
    assert script.ran == [["first"], ["again"]]


def test_a_long_outage_does_not_overflow_the_backoff() -> None:
    script = Script([0], [(1, "", "cannot reach")] * 2000)
    assert run(script) == 99
    assert max(script.slept) <= 60


def test_a_revoked_credential_ends_the_loop() -> None:
    script = Script([0], [(1, "", "maity: GET …: credential_revoked: revoked")])
    assert run(script) == loop.EXIT_REVOKED


def test_an_unreachable_hub_backs_off_without_counting() -> None:
    script = Script([0, 0], [(1, "", "cannot reach"), (1, "", "cannot reach"), event(7)])
    assert run(script) == 99
    assert script.ran == [["first"], ["again"]]


# --- what the runner makes of the loop's exits -----------------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (loop.EXIT_REVOKED, ("failed", "agent_credential_revoked", None)),
        (loop.EXIT_HOT_LOOP, ("failed", "crash_loop", "hot_loop")),
    ],
)
def test_loop_exits_map_to_reasons(code: int, expected: tuple[Any, ...]) -> None:
    rec = supervisor.Record(generation=1, state="running", started_at=0.0)
    cfg: Any = type("Cfg", (), {"limits": config.Limits(projects=(), repositories=())})()
    sup: Any = type("Sup", (), {"cfg": cfg, "rand": staticmethod(lambda: 0.5),
                                "log": staticmethod(lambda line: None)})()  # fmt: skip
    sup.backend = type("B", (), {"kill": staticmethod(lambda name: None)})()
    session: Any = type("S", (), {"name": "maity_p_c", "exit_status": code})()
    supervisor.Supervisor._exited(sup, rec, session, 100.0, sup.backend)
    assert (rec.state, rec.reason, rec.detail) == expected


# --- Codex and opencode ----------------------------------------------------------------------


def test_codex_config(tmp_path: Path) -> None:
    ctx = context(tmp_path, harness_id="codex", binary="/usr/bin/codex",
                  hosts=("maity.team", "github.com"),
                  grant=config.RepositoryGrant(network=("pypi.org",)))  # fmt: skip
    found = tomllib.loads(adapters.codex_config(ctx))
    assert found["approval_policy"] == "never" and found["default_permissions"] == "maity"
    assert found["projects"][str(ctx.clone)]["trust_level"] == "untrusted"  # no .codex/ layers
    assert found["permissions"]["maity"]["extends"] == ":workspace"
    assert found["permissions"]["maity"]["filesystem"] == {
        str(ctx.clone): "write",
        str(ctx.clone / ".git"): "write",
        str(ctx.clone / ".git" / "hooks"): "read",
        str(ctx.clone / ".git" / "config"): "read",
    }
    domains = found["permissions"]["maity"]["network"]["domains"]
    assert set(domains) == {"maity.team", "github.com", "pypi.org", *adapters.CODEX_PROVIDER_HOSTS}


def test_codex_writes_the_placements_effort_into_its_own_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§15.5 (tsk-0fr0xzy2ce95): `model_reasoning_effort` in the placement's config.toml, a
    top-level key, never a `-c` flag: the resume reads the same home, so it keeps the level."""
    effort = {**PLACEMENT, "mode": "supervised", "effort": "medium"}
    ctx = context(tmp_path, harness_id="codex", binary="/usr/bin/codex", placement=effort)
    found = tomllib.loads(adapters.codex_config(ctx))
    assert found["model_reasoning_effort"] == "medium"
    home = tmp_path / "home"
    (home / "codex").mkdir(parents=True)
    (home / "codex" / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(home / "codex"))
    launch = adapters.launch(ctx)
    written = tomllib.loads((Path(launch.env["CODEX_HOME"]) / "config.toml").read_text())
    assert written["model_reasoning_effort"] == "medium"
    spec = json.loads(Path(launch.argv[-1]).read_text())
    assert not any("effort" in arg for arg in (*spec["first"], *spec["again"]))
    # No effort: no key, so Codex runs its own default.
    plain = context(tmp_path / "plain", harness_id="codex", binary="/usr/bin/codex")
    assert "model_reasoning_effort" not in tomllib.loads(adapters.codex_config(plain))


def test_a_headless_placement_is_offered_no_question_tool(tmp_path: Path) -> None:
    supervised = {**PLACEMENT, "mode": "supervised"}
    claude = adapters.claude_settings(context(tmp_path / "c", placement=supervised))
    assert "AskUserQuestion" in claude["permissions"]["deny"]  # bare: out of the context
    codex = tomllib.loads(
        adapters.codex_config(context(tmp_path / "x", harness_id="codex", placement=supervised))
    )
    assert codex["tools"]["experimental_request_user_input"] == {"enabled": False}


def test_an_interactive_placement_keeps_the_question_tool(tmp_path: Path) -> None:
    # A person is at the pane; what the permission mode does with the tool stays as it was.
    claude = adapters.claude_settings(context(tmp_path / "c"))
    assert "AskUserQuestion" not in claude["permissions"]["deny"]
    codex = tomllib.loads(adapters.codex_config(context(tmp_path / "x", harness_id="codex")))
    assert "tools" not in codex


@pytest.mark.parametrize("mode", ["interactive", "supervised"])
@pytest.mark.parametrize("sandbox", [False, True])
def test_claude_code_writes_no_attribution_lines(tmp_path: Path, mode: str, sandbox: bool) -> None:
    """Every placement: no commit trailer, no pull request line, no session link. Empty
    strings, not `false`, which a binary older than 2.1.281 rejects with the whole file."""
    ctx = context(tmp_path, placement={**PLACEMENT, "mode": mode}, sandbox=sandbox)
    adapters.launch(ctx)  # a supervised one names the file in the loop's spec, not in argv
    written = json.loads((ctx.agent_dir / "claude-settings.json").read_text())
    assert written["attribution"] == {"commit": "", "pr": "", "sessionUrl": False}
    assert "includeCoAuthoredBy" not in written  # deprecated; ignored once this is set


def test_codex_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    (home / "codex").mkdir(parents=True)
    (home / "codex" / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(home / "codex"))  # the operator's own, wherever it is
    ctx = context(tmp_path, harness_id="codex", binary="/usr/bin/codex",
                  placement={**PLACEMENT, "mode": "supervised", "model": "gpt-5.5"})  # fmt: skip
    launch = adapters.launch(ctx)
    codex_home = Path(launch.env["CODEX_HOME"])
    # Codex runs maity inside its sandbox, which cannot write the runner's directory: git's own
    # repository stays in `.git/maity`, named so, never by leaving the variable out.
    assert launch.env[clonecheck.GIT_PRIVATE_ENV] == clonecheck.IN_CLONE
    # No scratch on this context: CODEX_HOME falls back to the runner's directory, as before.
    assert codex_home.parent == ctx.agent_dir
    assert (codex_home / "auth.json").resolve() == (home / "codex" / "auth.json").resolve()
    assert (ctx.clone / ".git" / "maity").is_dir()
    spec = json.loads(Path(launch.argv[-1]).read_text())
    assert spec["first"][:4] == ["/usr/bin/codex", "exec", "-C", str(ctx.clone)]
    assert spec["again"][-3:-1] == ["resume", "--last"] and "gpt-5.5" in spec["first"]
    assert spec["env"]["CODEX_HOME"] == str(codex_home)


def _effective_rule(filesystem: dict[str, str], path: Path) -> str | None:
    """The rule the codex sandbox applies to `path`: that of the nearest ancestor of `path`
    (or `path` itself) among the filesystem keys, the longest prefix winning; None if none
    match."""
    best: tuple[int, str] | None = None
    for key, rule in filesystem.items():
        anchor = Path(key)
        if path == anchor or anchor in path.parents:
            depth = len(anchor.parts)
            if best is None or depth > best[0]:
                best = (depth, rule)
    return best[1] if best else None


def test_codex_home_lies_in_the_reopened_scratch_not_the_hidden_state_dir(tmp_path: Path) -> None:
    """The invariant the incident broke (card tsk-hv7jbgy75zjt): a codex placement's CODEX_HOME
    is under no path the codex sandbox hides, and the profile re-opens (does not hide) the
    placement's own codex-home, so Codex's per-command helper can be created and run. Red before
    the fix, when CODEX_HOME sat in agent_dir under the hidden state directory."""
    workspaces = tmp_path / "ws"
    place_scratch = workspaces / ".scratch" / "proj" / "plc-0003"
    place_scratch.mkdir(parents=True)
    state_dir = tmp_path / "st"  # the fixture's agent_dir lives under it
    ctx = context(
        tmp_path, harness_id="codex", binary="/usr/bin/codex",
        clone=workspaces / "proj" / "agent-3",
        workspaces=workspaces, scratch=place_scratch, private=(state_dir,),
        placement={**PLACEMENT, "mode": "supervised"},
    )  # fmt: skip
    home = Path(adapters.launch(ctx).env["CODEX_HOME"])
    # Under no hidden path, and reachable: it lies under the workspaces root the sandbox
    # re-opens for this placement.
    assert not any(home == p or p in home.parents for p in ctx.private)
    assert ctx.workspaces in home.parents
    # The profile hides the workspaces root from other placements but re-opens this codex-home
    # read: the sandboxed commands may read it and run the per-command helper under home/tmp,
    # but may write nothing in it. Read also keeps it reachable so the helper stays runnable.
    filesystem = tomllib.loads(adapters.codex_config(ctx))["permissions"]["maity"]["filesystem"]
    assert filesystem[str(ctx.workspaces)] == "none"
    assert _effective_rule(filesystem, home) == "read"
    assert _effective_rule(filesystem, home / "tmp") == "read"


def test_a_placements_profile_hides_another_placements_codex_home(tmp_path: Path) -> None:
    """A placement re-opens only its own scratch (and the codex-home inside it); another
    placement's codex-home, under the shared workspaces root this profile hides, is not
    reachable from it."""
    workspaces = tmp_path / "ws"
    mine = workspaces / ".scratch" / "proj" / "plc-0003"
    mine.mkdir(parents=True)
    ctx = context(
        tmp_path, harness_id="codex", binary="/usr/bin/codex",
        clone=workspaces / "proj" / "agent-3",
        workspaces=workspaces, scratch=mine, private=(tmp_path / "st",),
        placement={**PLACEMENT, "mode": "supervised"},
    )  # fmt: skip
    filesystem = tomllib.loads(adapters.codex_config(ctx))["permissions"]["maity"]["filesystem"]
    other = workspaces / ".scratch" / "other" / "plc-9999" / "codex-home"
    assert _effective_rule(filesystem, other) == "none"
    assert _effective_rule(filesystem, adapters.codex_home(ctx)) == "read"
    assert _effective_rule(filesystem, adapters.codex_home(ctx) / "tmp") == "read"


def test_the_agy_shared_tmp_parent_is_hidden_from_a_non_agy_sandbox(tmp_path: Path) -> None:
    """The agy per-user `/tmp` scratch parent is hidden from a non-agy placement's sandbox, so
    it cannot reach another placement's scratch there: Codex names it `none`, and Claude Code
    denies both reading and writing it."""
    parent = tmp_path / "shared-tmp" / "maity-scratch-1002"
    # Codex: the parent is among the profile's hidden (`none`) roots.
    codex = context(
        tmp_path, harness_id="codex", binary="/usr/bin/codex",
        clone=tmp_path / "ws" / "proj" / "agent-3", workspaces=tmp_path / "ws",
        private=(tmp_path / "st",), tmp_scratch_parent=parent,
        placement={**PLACEMENT, "mode": "supervised"},
    )  # fmt: skip
    filesystem = tomllib.loads(adapters.codex_config(codex))["permissions"]["maity"]["filesystem"]
    assert filesystem[str(parent)] == "none"
    assert _effective_rule(filesystem, parent / "maity-anything") == "none"
    # Claude Code: the parent is denied both read and write.
    claude = adapters.claude_settings(
        context(tmp_path / "c", sandbox=True, tmp_scratch_parent=parent)
    )["sandbox"]["filesystem"]
    assert str(parent) in claude["denyRead"] and str(parent) in claude["denyWrite"]


def test_a_placements_own_tmpdir_leaf_is_opened_again_and_its_siblings_stay_hidden(
    tmp_path: Path,
) -> None:
    """tsk-0zb9mgzmbwn4: a Codex placement's own TMPDIR leaf under the hidden per-user `/tmp`
    parent is opened again for it alone (`write` within `none`), and a sibling leaf stays
    hidden. Claude Code's settings open only the leaf's `tmp` and deny the parent for reading
    alone (tsk-k7svzz2p4v7y, below). Paths only, nothing is made: short, as the runner's."""
    parent = Path("/tmp/maity-scratch-1002")  # noqa: S108 - a path only
    own, sibling = parent / ("a" * 32), parent / ("b" * 32)

    def codex_fs(base: Path, **extra: Any) -> dict[str, str]:  # a directory of its own per call
        ctx = context(
            base, harness_id="codex", binary="/usr/bin/codex",
            clone=base / "ws" / "proj" / "agent-3", workspaces=base / "ws",
            private=(base / "st",), tmp_scratch_parent=parent, tmpdir=own / "tmp",
            placement={**PLACEMENT, "mode": "supervised"}, **extra,
        )  # fmt: skip
        fs: dict[str, str] = tomllib.loads(adapters.codex_config(ctx))["permissions"]["maity"][
            "filesystem"
        ]
        return fs

    filesystem = codex_fs(tmp_path / "x")
    assert filesystem[str(parent)] == "none" and filesystem[str(own)] == "write"
    assert _effective_rule(filesystem, own / "tmp" / "pytest-1") == "write"
    assert _effective_rule(filesystem, sibling / "tmp") == "none"
    # Where the scratch's own `tmp` fits, that is the TMPDIR, and the leaf is not opened.
    room = Path("/srv/ws/proj/.scratch/plc-0003")
    assert adapters.scratch_tmpdir(room) is not None
    assert str(own) not in codex_fs(tmp_path / "y", scratch=room)


def test_a_scratch_without_room_for_a_socket_gets_the_short_tmpdir_the_runner_made(
    tmp_path: Path,
) -> None:
    """tsk-0zb9mgzmbwn4: where the scratch's own `tmp` leaves no room for a socket, TMPDIR is
    the placement's own short one; where the scratch's `tmp` fits, that one is kept."""
    deep = Path("/") / ("w" * 60) / "maity" / ".scratch" / "plc-0000000000000003"
    own = Path("/tmp/maity-scratch-1002") / ("a" * 32) / "tmp"  # noqa: S108 - a path only
    launched = adapters.launch(context(tmp_path / "d", "stub", scratch=deep, tmpdir=own))
    assert launched.env["TMPDIR"] == str(own) and launched.env["MAITY_SCRATCH"] == str(deep)
    room = Path("/srv/ws/maity/.scratch/plc-0003")
    launched = adapters.launch(context(tmp_path / "r", "stub", scratch=room, tmpdir=own))
    assert launched.env["TMPDIR"] == str(room / "tmp")


def test_claude_codes_own_tmpdir_is_the_leafs_tmp_and_its_own_files_sit_beside_it(
    tmp_path: Path,
) -> None:
    """tsk-k7svzz2p4v7y, the live probes of 2026-11-21 (Claude Code 2.1.329). With the parent
    denied for reading only, the sandbox writes the re-opened `tmp` and a sibling leaf does not
    exist in it (P4); with the parent also denied for writing, the `tmp` is mounted read-only
    (P3). So with no room under the scratch: TMPDIR is the leaf's `tmp`, opened for reading and
    writing, the parent denied for reading alone, and Claude Code's own files and socket in the
    leaf itself (CLAUDE_CODE_TMPDIR), which the runner's settings do not open (Claude Code
    itself opens its own `claude-<uid>/` there, live 2.1.329)."""
    deep = Path("/") / ("w" * 60) / "maity" / ".scratch" / "plc-0000000000000003"
    parent = Path("/tmp/maity-scratch-1002")  # noqa: S108 - a path only
    leaf, sibling = parent / ("a" * 32), parent / ("b" * 32)
    own = leaf / "tmp"
    ctx = context(tmp_path / "d", sandbox=True, scratch=deep, tmpdir=own, tmp_scratch_parent=parent)
    env = adapters.launch(ctx).env
    assert env["TMPDIR"] == str(own) and env["CLAUDE_CODE_TMPDIR"] == str(leaf)
    filesystem = adapters.claude_settings(ctx)["sandbox"]["filesystem"]
    assert str(parent) in filesystem["denyRead"] and str(parent) not in filesystem["denyWrite"]
    assert filesystem["allowRead"] == [str(deep), str(own)]  # the scratch too (tsk-07dwr3t80rg0)
    assert filesystem["allowWrite"] == [str(deep), str(own)]
    opened = [*filesystem["allowRead"], *filesystem["allowWrite"]]
    assert str(leaf) not in opened and not any(str(sibling) in path for path in opened)
    # Where the scratch's own `tmp` fits, it is the TMPDIR, the leaf is not opened, and the
    # parent stays denied for writing too.
    room = Path("/srv/ws/maity/.scratch/plc-0003")
    ctx = context(tmp_path / "r", sandbox=True, scratch=room, tmpdir=own, tmp_scratch_parent=parent)
    env = adapters.launch(ctx).env
    assert env["TMPDIR"] == str(room / "tmp") and "CLAUDE_CODE_TMPDIR" not in env
    filesystem = adapters.claude_settings(ctx)["sandbox"]["filesystem"]
    assert str(parent) in filesystem["denyWrite"] and filesystem["allowRead"] == [str(room)]
    assert filesystem["allowWrite"] == [str(room)]
    # Without a leaf (an ssh host, or none could be made): neither variable, the parent denied.
    ctx = context(tmp_path / "n", sandbox=True, scratch=deep, tmp_scratch_parent=parent)
    env = adapters.launch(ctx).env
    assert "TMPDIR" not in env and "CLAUDE_CODE_TMPDIR" not in env
    filesystem = adapters.claude_settings(ctx)["sandbox"]["filesystem"]
    assert str(parent) in filesystem["denyWrite"] and filesystem["allowRead"] == [str(deep)]
    # Codex: the leaf's `tmp` is its TMPDIR as before, with no CLAUDE_CODE_TMPDIR. Its launch
    # writes its CODEX_HOME into the scratch, so that scratch is made, still with no room for a
    # socket.
    made = tmp_path / "c" / ("w" * 60) / ".scratch" / "maity" / "plc-0000000000000003"
    made.mkdir(parents=True)
    assert adapters.scratch_tmpdir(made) is None
    codex = context(
        tmp_path / "c", harness_id="codex", binary="/usr/bin/codex", scratch=made, tmpdir=own
    )
    env = adapters.launch(codex).env
    assert env["TMPDIR"] == str(own) and "CLAUDE_CODE_TMPDIR" not in env


def test_a_sandboxed_claude_code_placement_without_a_tmpdir_of_its_own_is_refused(
    tmp_path: Path,
) -> None:
    """tsk-k7svzz2p4v7y, security's condition: a sandboxed Claude Code placement starts only
    with a TMPDIR of its own, else its commands would share /tmp/claude-<uid>. The leaf's `tmp`
    or the scratch's own `tmp` will do; neither (no leaf could be made, an ssh host) refuses,
    with the cause and the remedy. Unsandboxed, or another harness: not refused."""
    deep = Path("/") / ("w" * 60) / "maity" / ".scratch" / "plc-0000000000000003"
    room = Path("/srv/ws/maity/.scratch/plc-0003")
    own = Path("/tmp/maity-scratch-1002") / ("a" * 32) / "tmp"  # noqa: S108 - a path only
    refusal = adapters.private_tmpdir_refusal
    assert refusal(context(tmp_path / "l", sandbox=True, scratch=deep, tmpdir=own)) is None
    assert refusal(context(tmp_path / "r", sandbox=True, scratch=room)) is None
    why = refusal(context(tmp_path / "d", sandbox=True, scratch=deep))
    assert why is not None and str(deep / "tmp") in why and "workspaces" in why
    assert "/tmp/claude-<uid>" in why  # noqa: S108 - text only
    assert refusal(context(tmp_path / "s", sandbox=True)) is not None  # no scratch at all
    assert refusal(context(tmp_path / "u", sandbox=False, scratch=deep)) is None
    codex = context(tmp_path / "c", harness_id="codex", binary="/usr/bin/codex", scratch=deep)
    assert refusal(codex) is None


def test_the_short_tmpdir_fits_a_socket_at_its_longest() -> None:
    """The leaf the runner draws is 32 hex digits (`secrets.token_hex(16)`); with the largest
    uid the path still leaves room for Claude Code's socket on Linux. On macOS, under the
    resolved `/private/tmp`, a uid of up to four digits fits (macOS gives users 501 and up);
    a longer one does not, and the runner then starts the session without one (`_tmpdir`)."""
    linux = Path("/tmp") / f"maity-scratch-{2**32 - 1}" / ("f" * 32) / "tmp"  # noqa: S108
    assert adapters.fits_socket(linux, adapters.socket_path_max("linux"))
    mac = Path("/private/tmp") / "maity-scratch-9999" / ("f" * 32) / "tmp"
    assert adapters.fits_socket(mac, adapters.socket_path_max("darwin"))
    longer = Path("/private/tmp") / "maity-scratch-99999" / ("f" * 32) / "tmp"
    assert not adapters.fits_socket(longer, adapters.socket_path_max("darwin"))
    # Claude Code's sandbox socket under its CLAUDE_CODE_TMPDIR, `cc-socks/<pid>.sock` (live
    # 2026-11-21), with the largest Linux pid, takes no more room than the name checked above.
    assert len("cc-socks/4194304.sock") <= adapters.SOCKET_NAME_ROOM


def test_without_a_scratch_codex_home_stays_in_the_runner_directory(tmp_path: Path) -> None:
    """No workspaces root to carve (so no scratch): CODEX_HOME keeps today's location in the
    runner's directory rather than crashing. `maity runner check` reports that case."""
    ctx = context(tmp_path, harness_id="codex", binary="/usr/bin/codex",
                  placement={**PLACEMENT, "mode": "supervised"})  # fmt: skip
    assert adapters.codex_home(ctx) == ctx.agent_dir / "codex-home"
    # The profile emits no codex-home rule to a hidden path when there is no scratch.
    filesystem = tomllib.loads(adapters.codex_config(ctx))["permissions"]["maity"]["filesystem"]
    assert not any("codex-home" in key for key in filesystem)


def _codex_scratch_context(tmp_path: Path) -> adapters.Context:
    workspaces = tmp_path / "ws"
    place_scratch = workspaces / ".scratch" / "proj" / "plc-0003"
    return context(
        tmp_path, harness_id="codex", binary="/usr/bin/codex",
        clone=workspaces / "proj" / "agent-3",
        workspaces=workspaces, scratch=place_scratch, private=(tmp_path / "st",),
        placement={**PLACEMENT, "mode": "supervised"},
    )  # fmt: skip


def test_the_profile_gives_codex_home_and_its_control_files_read_not_write(tmp_path: Path) -> None:
    """A sandboxed command may read Codex's control files but write none of them: codex-home,
    its config.toml, any rules file, the auth.json link and the per-command helper under tmp
    are `read`, never `write`. Red on bc753a79, where codex-home was granted `write` and a
    sandboxed command could rewrite the configuration a later supervised restart reads."""
    ctx = _codex_scratch_context(tmp_path)
    ctx.scratch.mkdir(parents=True)  # type: ignore[union-attr]
    filesystem = tomllib.loads(adapters.codex_config(ctx))["permissions"]["maity"]["filesystem"]
    home = adapters.codex_home(ctx)
    for under_home in (home, home / "config.toml", home / "rules", home / "rules" / "x.rules",
                       home / "auth.json", home / "tmp", home / "tmp" / "arg0-linux"):  # fmt: skip
        assert _effective_rule(filesystem, under_home) == "read", under_home
    assert not any(rule == "write" and "codex-home" in key for key, rule in filesystem.items())


def test_the_launch_prep_refuses_a_codex_home_swapped_for_a_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real launch preparation (adapters driving a real scratch) writes Codex's control
    files only below the scratch it holds open: a codex-home that is a link to a directory
    outside the scratch is refused and nothing outside is written. Red on bc753a79, where the
    plain writes resolved the parent normally and wrote through the link."""
    ctx = _codex_scratch_context(tmp_path)
    (tmp_path / "ws").mkdir()
    scratch.make(ctx.scratch)  # type: ignore[arg-type]
    login = tmp_path / "home" / "codex"
    login.mkdir(parents=True)
    (login / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(login))  # the operator's own login to link
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "config.toml").write_text("SENTINEL-config")
    (victim / "auth.json").write_text("SENTINEL-auth")
    (ctx.scratch / "codex-home").symlink_to(victim)  # type: ignore[operator]
    with pytest.raises(scratchop.OnTheWay):
        adapters.launch(ctx)
    assert (victim / "config.toml").read_text() == "SENTINEL-config"
    assert (victim / "auth.json").read_text() == "SENTINEL-auth"
    assert (ctx.scratch / "codex-home").is_symlink()  # type: ignore[operator]


def test_the_launch_prep_writes_land_inside_the_scratch_past_leaf_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real codex-home with a link planted at config.toml (a leaf): the launch prep replaces
    it in place, the real config.toml lands inside the scratch, and the file the leaf link
    pointed at outside the scratch is untouched. The leaf case stays safe."""
    ctx = _codex_scratch_context(tmp_path)
    (tmp_path / "ws").mkdir()
    scratch.make(ctx.scratch)  # type: ignore[arg-type]
    home = ctx.scratch / "codex-home"  # type: ignore[operator]
    home.mkdir()
    login = tmp_path / "home" / "codex"
    login.mkdir(parents=True)
    (login / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(login))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "c").write_text("keep-c")
    (home / "config.toml").symlink_to(outside / "c")
    adapters.launch(ctx)
    assert (outside / "c").read_text() == "keep-c"  # the leaf link was not followed
    assert not (home / "config.toml").is_symlink()
    assert "approval_policy" in (home / "config.toml").read_text()
    assert os.readlink(home / "auth.json") == str(login / "auth.json")


OPENCODE_HARNESS = config.Harness(
    "opencode", ("interactive", "supervised"), "interactive",
    ("xai/grok-4.7", "opus"), "xai/grok-4.7",
)  # fmt: skip


def flags(argv: list[str]) -> set[str]:
    return {word for word in argv if word.startswith("-")}


def test_opencode_launch(tmp_path: Path) -> None:
    # No model on the placement: the harness default (xai/grok-4.7) reaches opencode, not
    # opencode's own free default. OpenCode 2.3's TUI has no `--model` and exits on it
    # (tsk-daa6e0gfncg0), so the interactive start names the model in its opencode.json, and
    # starts `--standalone`: otherwise the TUI attaches to the user's shared background
    # service, which reads neither that file nor the project-config switch (nte-mmnz3mk1247c).
    ctx = context(tmp_path, harness=OPENCODE_HARNESS, binary="/usr/bin/opencode",
                  placement={**PLACEMENT, "mode": "interactive", "model": None})  # fmt: skip
    launch = adapters.launch(ctx)
    assert launch.env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert launch.argv == ["/usr/bin/opencode", "--standalone", str(ctx.clone), "--prompt",
                           adapters.START_PROMPT]  # fmt: skip
    assert "--model" not in launch.argv and "-m" not in launch.argv
    assert flags(launch.argv) <= opencode_23_flags(OPENCODE_23_TUI)
    settings = json.loads(Path(launch.env["OPENCODE_CONFIG"]).read_text())
    assert settings["model"] == "xai/grok-4.7"
    rules = settings["permission"]
    assert list(rules)[0] == "*" and rules["*"] == "deny"  # first: the last match wins
    assert rules["bash"]["*"] == "deny" and rules["bash"]["make test *"] == "allow"
    assert "git *" not in rules["bash"] and rules["bash"]["git commit *"] == "allow"
    denied = (*adapters.GIT_DENIED, *adapters.GIT_WORKTREE_DENIED, *adapters.GH_DENIED,
              *adapters.MAITY_RUNNER_DENIED)  # fmt: skip
    maity = [f"maity *{char}*" for char in adapters.MAITY_NOT_PLAIN]
    # Denies last: the last match wins. `maity` only as one plain call, as for Claude Code.
    assert list(rules["bash"])[-len(maity) - len(denied) :] == [*denied, *maity]
    assert all(rules["bash"][rule] == "deny" for rule in maity)
    assert {"maity *>*", "maity *|*", "maity *;*", "maity *&*", "maity *$*", "maity *<*",
            "maity *`*", "maity *\n*"} == set(maity)  # fmt: skip
    assert rules["read"] == {"*": "allow", f"{ctx.clone}/.git/maity/*": "deny"}
    assert rules["edit"] == {"*": "allow", f"{ctx.clone}/.git/*": "deny"}
    assert rules["webfetch"] == "deny" and rules["external_directory"] == "deny"
    assert settings["instructions"] == [str(ctx.clone / "AGENTS.md")]


def test_opencode_supervised(tmp_path: Path) -> None:
    # A model-less supervised placement carries the harness default in both the first run and
    # the continuation: `opencode run` takes `--model` on 2.3, and the configuration names the
    # same model. 2.3's `run` has no `--dir` (nte-mmnz3mk1247c): it runs in the clone, the
    # working directory the session starts in and the loop's runs inherit.
    ctx = context(tmp_path, harness=OPENCODE_HARNESS, binary="/usr/bin/opencode",
                  placement={**PLACEMENT, "mode": "supervised", "model": None})  # fmt: skip
    launch = adapters.launch(ctx)
    spec = json.loads(Path(launch.argv[-1]).read_text())
    assert spec["first"] == ["/usr/bin/opencode", "run", "--model", "xai/grok-4.7",
                             adapters.START_PROMPT]  # fmt: skip
    assert spec["again"] == ["/usr/bin/opencode", "run", "--model", "xai/grok-4.7",
                             "--continue", adapters.START_PROMPT]  # fmt: skip
    assert "--dir" not in spec["first"] + spec["again"]
    run = opencode_23_flags(OPENCODE_23_RUN)
    assert flags(spec["first"]) <= run and flags(spec["again"]) <= run
    assert json.loads(Path(launch.env["OPENCODE_CONFIG"]).read_text())["model"] == "xai/grok-4.7"
    # Its working directory: the session starts in the placement's workspace path
    # (supervisor: `backend.start(name, place.path, …)`), which is the clone itself for a
    # harness without a workspace folder, and the loop runs each `opencode run` there.
    from maity.runner import workspace

    assert not workspace.uses_folder("opencode")
    assert spec["clone"] == str(ctx.clone)


def test_opencode_placement_model_reaches_both_launch_forms(tmp_path: Path) -> None:
    # A placement's own model (one of `models`) wins over the default in either form.
    for mode in ("interactive", "supervised"):
        ctx = context(tmp_path / mode, harness=OPENCODE_HARNESS, binary="/usr/bin/opencode",
                      placement={**PLACEMENT, "mode": mode, "model": "opus"})  # fmt: skip
        launch = adapters.launch(ctx)
        assert json.loads(Path(launch.env["OPENCODE_CONFIG"]).read_text())["model"] == "opus"
        if mode == "supervised":
            spec = json.loads(Path(launch.argv[-1]).read_text())
            assert spec["first"][2:4] == ["--model", "opus"]


def test_the_check_probes_every_flag_the_opencode_launch_passes(tmp_path: Path) -> None:
    # `maity runner check` reads `--help` for capabilities.OPENCODE_FLAGS: a flag the adapter
    # passes but the probe does not look for would let the next tsk-daa6e0gfncg0 through.
    from maity.runner import capabilities

    for mode in ("interactive", "supervised"):
        ctx = context(tmp_path / mode, harness=OPENCODE_HARNESS, binary="/usr/bin/opencode",
                      placement={**PLACEMENT, "mode": mode, "model": None})  # fmt: skip
        argv = adapters.launch(ctx).argv
        if mode == "supervised":
            spec = json.loads(Path(argv[-1]).read_text())
            argv = [*spec["first"], *spec["again"]]
        command, probed = capabilities.OPENCODE_FLAGS[mode]
        assert argv[1 : 1 + len(command)] == list(command)
        assert flags(argv) == set(probed), mode


@pytest.mark.parametrize("mode", ["interactive", "supervised"])
def test_opencode_refuses_a_model_that_is_not_configured(tmp_path: Path, mode: str) -> None:
    # Fail closed in both forms: a placement model outside the harness's `models` (here
    # opencode's own free default) would send the conversation to opencode's servers, so the
    # start is refused, before an opencode.json naming it is written.
    ctx = context(tmp_path, harness=OPENCODE_HARNESS, binary="/usr/bin/opencode",
                  placement={**PLACEMENT, "mode": mode,
                             "model": "opencode/hy4-flash-free"})  # fmt: skip
    with pytest.raises(adapters.NotYet):
        adapters.launch(ctx)
    assert not (ctx.agent_dir / "opencode.json").exists()


@pytest.mark.parametrize("mode", ["interactive", "supervised"])
def test_opencode_refuses_when_no_model_can_be_resolved(tmp_path: Path, mode: str) -> None:
    # No placement model and no harness default (a harness configured without `models`): nothing
    # safe to pass, so the start is refused rather than left to opencode's free default, in
    # both forms; no opencode.json without a `model` is left for a later start either.
    harness = config.Harness("opencode", ("interactive", "supervised"), "interactive")
    ctx = context(tmp_path, harness=harness, binary="/usr/bin/opencode",
                  placement={**PLACEMENT, "mode": mode, "model": None})  # fmt: skip
    with pytest.raises(adapters.NotYet):
        adapters.launch(ctx)
    assert not (ctx.agent_dir / "opencode.json").exists()


def test_codex_is_advertised_as_sandbox_confined(monkeypatch: pytest.MonkeyPatch) -> None:
    from maity.runner import capabilities

    codex = config.Harness("codex", ("supervised",), "supervised", binary="codex")
    monkeypatch.setattr("shutil.which", lambda name, path=None: "/usr/bin/codex")
    monkeypatch.setattr(capabilities, "_codex_sandbox_starts", lambda binary, user=None: True)
    entry = capabilities.harness_entry(codex, capabilities.Probe("/usr/bin/codex", "1.0", None))
    assert entry["confinement"] == "sandbox" and entry["sandbox"] == "on"
    assert capabilities.sandbox_available(codex)


def test_efforts_are_advertised_only_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """§15.3 (tsk-0fr0xzy2ce95): a hub from before `efforts` refuses the key in a strict
    hello, so a harness without efforts sends exactly what that hub takes."""
    from maity.runner import capabilities

    monkeypatch.setattr("shutil.which", lambda name, path=None: "/usr/bin/codex")
    monkeypatch.setattr(capabilities, "_codex_sandbox_starts", lambda binary, user=None: True)
    probe = capabilities.Probe("/usr/bin/codex", "1.0", None)
    plain = config.Harness("codex", ("supervised",), "supervised", binary="codex")
    # Exactly the keys of a hello from before `efforts`, which a strict older hub takes.
    assert set(capabilities.harness_entry(plain, probe)) == {
        "id", "version", "available", "reason", "modes", "default_mode", "models", "targets",
        "confinement", "sandbox",
    }  # fmt: skip
    with_efforts = dataclasses.replace(plain, efforts=("low", "medium"))
    assert capabilities.harness_entry(with_efforts, probe)["efforts"] == ["low", "medium"]


def test_codex_whose_sandbox_cannot_start_is_not_advertised_as_sandboxed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from maity.runner import capabilities

    codex = config.Harness("codex", ("supervised",), "supervised", binary="codex")
    monkeypatch.setattr("shutil.which", lambda name, path=None: "/usr/bin/codex")
    monkeypatch.setattr(capabilities, "_codex_sandbox_starts", lambda binary, user=None: False)
    entry = capabilities.harness_entry(codex, capabilities.Probe("/usr/bin/codex", "1.0", None))
    assert entry["sandbox"] == "off" and not capabilities.sandbox_available(codex)


# --- confinement after the post-merge re-verification ----------------------------------------


@pytest.mark.parametrize("harness_id", ["claude-code", "codex", "opencode", "stub"])
def test_every_session_pins_the_clones_git_directory(tmp_path: Path, harness_id: str) -> None:
    ctx = context(tmp_path, harness_id, binary=None if harness_id == "stub" else "/usr/bin/x")
    (ctx.clone / ".git").mkdir(parents=True)
    assert adapters.launch(ctx).env["GIT_COMMON_DIR"] == str(ctx.clone / ".git")


def test_codex_hides_other_clones_the_runner_state_and_home_secrets(tmp_path: Path) -> None:
    secrets = (tmp_path / "st", tmp_path / "home" / ".ssh")
    ctx = context(tmp_path, "codex", private=secrets, workspaces=tmp_path / "ws")
    text = adapters.codex_config(ctx)
    for path in (tmp_path / "ws", *secrets):
        assert f'{json.dumps(str(path))} = "none"' in text
    assert f'{json.dumps(str(ctx.clone))} = "write"' in text  # more specific: it wins
    assert f'{json.dumps(str(ctx.clone / ".git" / "maity"))}' not in text  # its maity reads it


def test_codex_hides_no_path_inside_one_it_hides_already(tmp_path: Path) -> None:
    """Layout `single`: the runner's configuration file lies in `.config/maity-runner`, a
    home secret. Hiding it again inside the hidden directory broke Codex's bwrap ("Can't
    create file … Read-only file system"), and every command of a supervised run failed."""
    home = tmp_path / "home"
    runner_dir = home / ".config" / "maity-runner"
    others = tmp_path / "ws" / "p" / "agent-4" / ".git" / "maity"
    secrets = (tmp_path / "st", runner_dir, home / ".claude.json", runner_dir / "runner.toml",
               others, tmp_path / "st")  # fmt: skip
    ctx = context(tmp_path, "codex", private=secrets, workspaces=tmp_path / "ws")
    hidden = [path for path, level in tomllib.loads(adapters.codex_config(ctx))["permissions"]
              ["maity"]["filesystem"].items() if level == "none"]  # fmt: skip
    assert hidden == [str(tmp_path / "ws"), str(tmp_path / "st"), str(runner_dir),
                      str(home / ".claude.json")]  # fmt: skip
    assert adapters.outermost((Path("/a/b"), Path("/a"), Path("/ab"))) == (Path("/a"), Path("/ab"))


def test_codex_keeps_a_hidden_path_inside_its_own_clone_hidden(tmp_path: Path) -> None:
    """The clone is opened inside the hidden workspaces root, so a hidden path inside the
    clone is not hidden by the root and stays listed."""
    inner = tmp_path / "ws" / "maity" / "agent-3" / "sub" / ".git" / "maity"  # in its clone
    ctx = context(
        tmp_path,
        "codex",
        workspaces=tmp_path / "ws",
        private=(inner, tmp_path / "ws" / "maity" / "agent-4" / ".git" / "maity"),
    )
    assert inner.is_relative_to(ctx.clone)
    hidden = [path for path, level in tomllib.loads(adapters.codex_config(ctx))["permissions"]
              ["maity"]["filesystem"].items() if level == "none"]  # fmt: skip
    assert hidden == [str(tmp_path / "ws"), str(inner)]
    assert adapters.outermost((Path("/w"), Path("/w/c/x"), Path("/w/c/x/y"), Path("/w/d")),
                              opened=(Path("/w/c"),)) == (Path("/w"), Path("/w/c/x"))  # fmt: skip


@pytest.mark.parametrize("root", ["clone", "scratch"])
def test_a_hidden_path_inside_every_reopened_directory_stays_listed(
    tmp_path: Path, root: str
) -> None:
    """The clone and the scratch are both opened again inside the hidden workspaces root: a
    hidden path inside either is not hidden by the root and stays listed."""
    room = tmp_path / "ws" / "maity" / ".scratch" / "plc-0003"
    clone = tmp_path / "ws" / "maity" / "agent-3"  # context()'s clone
    inner = (clone if root == "clone" else room) / "sub" / ".git" / "maity"
    ctx = context(tmp_path, "codex", sandbox=True, scratch=room, workspaces=tmp_path / "ws",
                  private=(inner,))  # fmt: skip
    assert ctx.clone == clone
    hidden = [path for path, level in tomllib.loads(adapters.codex_config(ctx))["permissions"]
              ["maity"]["filesystem"].items() if level == "none"]  # fmt: skip
    assert hidden == [str(tmp_path / "ws"), str(inner)]


def test_the_home_secrets_are_listed_under_the_home_resolved(tmp_path: Path) -> None:
    """A home reached through a link: its secrets and the runner's configuration (resolved)
    must be seen as one inside the other, or Codex's profile would list both."""
    real = tmp_path / "real-home"
    (real / ".config" / "maity-runner").mkdir(parents=True)
    (real / ".config" / "maity-runner" / "runner.toml").write_text("")
    (tmp_path / "home").symlink_to(real)
    clone = tmp_path / "ws" / "p" / "agent-3"
    found = supervisor.private_paths(
        None, tmp_path / "home", clone,
        extra=(tmp_path / "home" / ".config" / "maity-runner" / "runner.toml",),
    )  # fmt: skip
    assert real / ".config" / "maity-runner" in found
    assert adapters.outermost(found).count(real / ".config" / "maity-runner" / "runner.toml") == 0


def test_claude_code_denies_reading_the_runner_state_and_home_secrets(tmp_path: Path) -> None:
    secrets = (tmp_path / "st", tmp_path / "home" / ".ssh")
    ctx = context(tmp_path, private=secrets, workspaces=tmp_path / "ws", sandbox=True)
    fs = adapters.claude_settings(ctx)["sandbox"]["filesystem"]
    deny = fs["denyRead"]
    assert deny == [f"{ctx.clone}/.git/maity", *(str(p) for p in secrets)]
    assert str(tmp_path / "ws") not in deny  # it holds the clone; see the context entry
    # Not writable either: the runner's files on the agents' side are among them (S201/S202).
    assert all(str(p) in fs["denyWrite"] for p in secrets)


def test_other_clones_credentials_are_private_as_they_stand_at_start(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    own = ws / "maity" / "agent-3"
    for clone in (own, ws / "maity" / "agent-4", ws / "other" / "agent-5"):
        (clone / ".git" / "maity").mkdir(parents=True)
    (ws / "maity" / "agent-6" / ".git").mkdir(parents=True)  # never joined: nothing to hide
    others = supervisor.other_credentials(ws, own, AsUser())
    found = supervisor.private_paths(tmp_path / "st", tmp_path / "home", own, others,
                                     (tmp_path / "runner.toml",))  # fmt: skip
    assert ws / "maity" / "agent-4" / ".git" / "maity" in found
    assert ws / "other" / "agent-5" / ".git" / "maity" in found
    assert own / ".git" / "maity" not in found  # its own maity reads it
    assert tmp_path / "runner.toml" in found
    assert not any("agent-6" in str(p) for p in found)


def test_private_paths_never_hide_the_clone(tmp_path: Path) -> None:
    clone = tmp_path / "home" / "ws" / "maity" / "agent-3"
    found = supervisor.private_paths(tmp_path / "home", tmp_path / "home", clone)
    assert tmp_path / "home" not in found  # the state dir here contains the clone
    assert tmp_path / "home" / ".ssh" in found and tmp_path / "home" / ".codex" in found


def test_opencode_search_tools_are_off(tmp_path: Path) -> None:
    """opencode asks about grep and glob by the pattern typed, not the path searched: a path
    rule cannot keep them off the credential, so they are denied outright."""
    ctx = context(tmp_path, "opencode")
    permission = adapters.opencode_config(ctx)["permission"]
    assert permission["grep"] == permission["glob"] == "deny"
    assert permission["read"][f"{ctx.clone}/.git/maity/*"] == "deny"


def test_a_dangling_login_link_is_replaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    login = tmp_path / "codex-login" / "auth.json"
    login.parent.mkdir()
    login.write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(login.parent))
    ctx = context(tmp_path, "codex", binary="/usr/bin/codex")
    (ctx.clone / ".git").mkdir(parents=True)
    home = ctx.agent_dir / "codex-home"
    home.mkdir(mode=0o700)
    (home / "auth.json").symlink_to(tmp_path / "gone" / "auth.json")
    adapters.launch(ctx)
    assert (home / "auth.json").resolve() == login.resolve()


@pytest.mark.parametrize("harness_id", ["claude-code", "codex", "stub"])
def test_launch_marks_the_clone_as_the_runners(tmp_path: Path, harness_id: str) -> None:
    """maity refuses its git in a marked clone whose session variables are gone. The git
    maity starts is recorded in the runner's directory for the agent, which the sandbox
    hides, never in the clone (only Codex, whose maity runs in its sandbox, keeps it there)."""
    ctx = context(tmp_path, harness_id)
    (ctx.clone / ".git").mkdir(parents=True)
    launch = adapters.launch(ctx)
    assert (ctx.clone / ".git" / "maity" / "placement").read_text() == "plc-0003\n"
    if harness_id == "codex":
        where = ctx.clone / ".git" / "maity"
    else:
        where = Path(launch.env[clonecheck.GIT_PRIVATE_ENV])
        assert where == ctx.agent_dir / "git"
        assert not (ctx.clone / ".git" / "maity" / "git").exists()
        assert not (ctx.clone / ".git" / "maity" / "pull_requests").exists()
    recorded = (where / "git").read_text().strip()
    assert recorded == shutil.which("git") and os.path.isabs(recorded)


REPOSITORY = "https://github.com/oliver-zehentleitner/maity.git"
PULLS = config.RepositoryGrant(allow=("make test",), pull_requests=True)


def fake_gh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\nexit 0\n")
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    return str(gh)


def test_no_placed_session_runs_gh_even_with_pull_requests(tmp_path: Path) -> None:
    """The settings test for 9f43804d: gh is denied in every session, a grant with pull
    requests adds no gh rule and no forge API host to the sandbox, so a sandboxed
    `gh pr create` is denied and only `maity gh` remains."""
    ctx = context(tmp_path, sandbox=True, grant=PULLS, hosts=("github.com", "maity.team"),
                  placement={**PLACEMENT, "workspace": {"repository": REPOSITORY}})  # fmt: skip
    settings = adapters.claude_settings(ctx)
    assert adapters.GH_DENIED == ("gh", "gh *")
    assert {"Bash(gh)", "Bash(gh *)"} <= set(settings["permissions"]["deny"])
    assert not any("gh" in rule.split("(", 1)[1].split()[0] for rule in
                   settings["permissions"]["allow"] if rule.startswith("Bash("))  # fmt: skip
    assert "api.github.com" not in settings["sandbox"]["network"]["allowedDomains"]
    o_ctx = context(tmp_path / "o", "opencode", grant=PULLS)
    bash = adapters.opencode_config(o_ctx)["permission"]["bash"]
    assert all(bash[rule] == "deny" for rule in adapters.GH_DENIED)
    assert list(bash)[-1] in (*adapters.GIT_DENIED, *adapters.GH_DENIED,
                              *(f"maity *{c}*" for c in adapters.MAITY_NOT_PLAIN))  # fmt: skip


def test_launch_records_the_repository_and_gh_for_a_grant_with_pull_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gh = fake_gh(tmp_path, monkeypatch)
    ctx = context(tmp_path, sandbox=True, grant=PULLS,
                  placement={**PLACEMENT, "workspace": {"repository": REPOSITORY}})  # fmt: skip
    (ctx.clone / ".git").mkdir(parents=True)
    launch = adapters.launch(ctx)
    record = (ctx.agent_dir / "git" / "pull_requests").read_text()
    assert record == f"github.com/oliver-zehentleitner/maity\n{gh}\n"
    assert not (ctx.clone / ".git" / "maity" / "pull_requests").exists()
    assert launch.argv[-1] == adapters.START_PROMPT + SANDBOXED + adapters.PULL_REQUEST_PROMPT
    assert "maity gh pr create" in adapters.PULL_REQUEST_PROMPT


def test_without_pull_requests_the_record_is_empty_and_the_prompt_silent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An earlier launch's record is overwritten: a grant taken back is taken back."""
    fake_gh(tmp_path, monkeypatch)
    ctx = context(tmp_path, sandbox=True,
                  placement={**PLACEMENT, "workspace": {"repository": REPOSITORY}})  # fmt: skip
    (ctx.clone / ".git" / "maity").mkdir(parents=True)
    (ctx.agent_dir / "git").mkdir(parents=True)
    (ctx.agent_dir / "git" / "pull_requests").write_text("github.com/o/other\n/bin/gh\n")
    launch = adapters.launch(ctx)
    assert (ctx.agent_dir / "git" / "pull_requests").read_text() == ""
    assert launch.argv[-1] == adapters.START_PROMPT + SANDBOXED


def test_codex_gets_no_pull_requests_record_and_no_word_of_maity_gh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex's `maity` runs inside its sandbox; `maity gh` is set up only outside one: the
    grant's pull requests are left out for it (adapters.codex_left_out)."""
    fake_gh(tmp_path, monkeypatch)
    placed = {**PLACEMENT, "workspace": {"repository": REPOSITORY}}
    assert adapters.pull_requests_record(context(tmp_path / "c", grant=PULLS, placement=placed))
    ctx = context(tmp_path, "codex", grant=PULLS, placement=placed)
    assert adapters.pull_requests_record(ctx) == ""
    assert "maity gh" not in adapters._sandbox_prompt(ctx)
    assert adapters.codex_left_out(PULLS) == [
        "allow 'make test' is not applied to codex: Codex has no command allowlist, so every"
        " command runs in its sandbox, listed or not (refused without the sandbox)",
        "pull_requests is not given to codex: its `maity` runs inside its sandbox, and the"
        " runner sets up `maity gh` only for a `maity` outside it",
    ]
    assert adapters.codex_left_out(config.RepositoryGrant(network=("pypi.org",))) == []


LEAD = config.RepositoryGrant(pull_requests=True, lead=True)


def test_the_lead_record_needs_lead_and_the_pull_request_record_and_is_cleared_without(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`lead = true` writes `lead` beside the pull-request record, in the runner's directory
    for the agent; without it (or without pull_requests, or for Codex) the record is empty,
    and a former launch's is overwritten. The role is not decided here: `maity gh` reads it
    from the hub at each call."""
    fake_gh(tmp_path, monkeypatch)
    placed = {**PLACEMENT, "workspace": {"repository": REPOSITORY}}
    ctx = context(tmp_path, sandbox=True, grant=LEAD, placement=placed)
    (ctx.clone / ".git").mkdir(parents=True)
    adapters.launch(ctx)
    assert (ctx.agent_dir / "git" / ghpr.LEAD).read_text() == "lead\n"
    assert not (ctx.clone / ".git" / "maity" / ghpr.LEAD).exists()
    adapters.launch(dataclasses.replace(ctx, grant=PULLS))  # the grant taken back
    assert (ctx.agent_dir / "git" / ghpr.LEAD).read_text() == ""
    alone = config.RepositoryGrant(lead=True)
    assert adapters.lead_record(context(tmp_path / "a", grant=alone, placement=placed)) == ""
    codex = context(tmp_path / "c", "codex", grant=LEAD, placement=placed)
    assert adapters.lead_record(codex) == ""
    assert adapters.codex_left_out(LEAD)[-1] == (
        "lead is not given to codex, for the same reason as pull_requests"
    )


def test_pull_requests_without_gh_on_the_path_record_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    ctx = context(tmp_path, grant=PULLS,
                  placement={**PLACEMENT, "workspace": {"repository": REPOSITORY}})  # fmt: skip
    assert adapters.pull_requests_record(ctx) == ""


def test_an_unclosed_block_drops_only_its_marker_and_a_foreign_encoding_is_left(
    tmp_path: Path,
) -> None:
    ctx = context(tmp_path, sandbox=True)
    exclude = ctx.clone / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True)
    exclude.write_text(f"a\n{adapters.EXCLUDE_BEGIN}\nb\n")
    adapters.launch(ctx)
    lines = exclude.read_text().splitlines()
    assert lines[:2] == ["a", "b"] and lines.count(adapters.EXCLUDE_BEGIN) == 1
    exclude.write_bytes(b"caf\xe9\n")  # not UTF-8: rewriting could change it
    adapters.launch(ctx)
    assert exclude.read_bytes() == b"caf\xe9\n"


def test_codex_under_its_sandbox_gets_the_git_line_and_not_the_maity_line(tmp_path: Path) -> None:
    ctx = context(tmp_path, harness_id="codex", binary="/usr/bin/codex", sandbox=True)
    prompt = adapters.launch(ctx).argv[-1]
    assert adapters.GIT_PROMPT in prompt and adapters.CLAUDE_MAITY_PROMPT not in prompt
    bare = context(tmp_path / "b", harness_id="codex", binary="/usr/bin/codex")
    assert adapters.launch(bare).argv[-1] == adapters.START_PROMPT


# --- settings that switch the runner's hook off (capabilities.claude_hooks_off) --------------


def _managed(capabilities: Any) -> Path:
    path: Path = capabilities.CLAUDE_MANAGED["linux"]
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize(
    ("text", "off"),
    [('{"disableAllHooks": true}', "sets disableAllHooks"),
     ('{"allowManagedHooksOnly": true}', "sets allowManagedHooksOnly"),
     ('{"allowManagedHooksOnly": "yes"}', "sets allowManagedHooksOnly"),
     ('{"disableAllHooks": false, "allowManagedHooksOnly": false}', None),
     ('{"permissions": {}}', None), ("{not json", "cannot be read as JSON"),
     ("[]", "is not a JSON object")],
)  # fmt: skip
def test_managed_settings_that_switch_hooks_off_are_named(text: str, off: str | None) -> None:
    from maity.runner import capabilities

    _managed(capabilities).write_text(text)
    why = capabilities.claude_hooks_off(AsUser(), "linux")
    assert (why is None) if off is None else (why is not None and off in why)


# No `os.geteuid` on Windows, and test_trust imports this module there (tsk-0tje3vzzedtx).
@pytest.mark.skipif(getattr(os, "geteuid", lambda: -1)() == 0, reason="root searches any directory")
@pytest.mark.parametrize("quiet", [False, True])
def test_managed_settings_that_cannot_be_looked_at_are_named_not_taken_for_absent(
    monkeypatch: pytest.MonkeyPatch, quiet: bool
) -> None:
    """A managed settings file below a directory the runner cannot search could switch the
    hook off: the check names it, never takes it for absent. Also where pathlib's predicates
    answer False instead of raising, as from Python 3.14 (tsk-0tje3vzzedtx, A1943)."""
    from maity.runner import capabilities

    if quiet:
        for name in ("is_dir", "is_file", "exists", "is_symlink"):
            original = getattr(Path, name)

            def answer(self: Path, *args: Any, _original: Any = original, **kw: Any) -> bool:
                try:
                    return bool(_original(self, *args, **kw))
                except PermissionError:
                    return False

            monkeypatch.setattr(Path, name, answer)
    managed = _managed(capabilities)
    managed.write_text('{"disableAllHooks": true}')
    managed.parent.chmod(0)
    try:
        why = capabilities.claude_hooks_off(AsUser(), "linux")
    finally:
        managed.parent.chmod(0o700)
    assert why is not None and "cannot be checked" in why


def test_no_managed_settings_switch_no_hook_off() -> None:
    from maity.runner import capabilities

    assert capabilities.claude_hooks_off(AsUser(), "linux") is None
    assert capabilities.claude_hooks_off(AsUser(), "win32") is None  # no managed path known


def test_a_managed_drop_in_counts_like_the_file() -> None:
    from maity.runner import capabilities

    drop_ins = _managed(capabilities).parent / "managed-settings.d"
    drop_ins.mkdir()
    (drop_ins / "10-team.json").write_text('{"permissions": {}}')
    assert capabilities.claude_hooks_off(AsUser(), "linux") is None
    (drop_ins / "20-hooks.json").write_text('{"disableAllHooks": true}')
    why = capabilities.claude_hooks_off(AsUser(), "linux")
    assert why is not None and "20-hooks.json sets disableAllHooks" in why


def test_the_agents_user_settings_count_only_for_managed_hooks_only() -> None:
    """The runner's settings file sets `disableAllHooks` back to false over the user's;
    `allowManagedHooksOnly` it cannot."""
    from maity.runner import capabilities

    user = Path.home() / ".claude" / "settings.json"
    user.parent.mkdir()
    user.write_text('{"disableAllHooks": true}')
    assert capabilities.claude_hooks_off(AsUser(), "linux") is None
    user.write_text('{"allowManagedHooksOnly": true}')
    why = capabilities.claude_hooks_off(AsUser(), "linux")
    assert why is not None and str(user) in why


@pytest.mark.parametrize(
    ("text", "why"),
    [('{"sandbox": {"network": {"allowAllUnixSockets": true}}}',
      "sets sandbox.network.allowAllUnixSockets"),
     ('{"sandbox": {"network": {"allowAllUnixSockets": false}}}',
      "sets sandbox.network.allowAllUnixSockets"),  # presence counts, whatever the value
     ('{"sandbox": {"network": {"allowUnixSockets": []}}}',
      "sets sandbox.network.allowUnixSockets"),
     ('{"sandbox": {"seccompConfig": {}}}', "sets sandbox.seccompConfig"),
     ('{"sandbox": {"enabled": true, "network": {"allowedDomains": []}}, "permissions": {}}',
      None),
     ('{"sandbox": "x"}', None), ("{not json", "cannot be read as JSON"),
     ("[]", "is not a JSON object")],
)  # fmt: skip
def test_the_agents_user_settings_may_carry_no_unix_socket_setting(
    text: str, why: str | None
) -> None:
    """Each key of SOCKET_SETTINGS in the agents' user's settings is named, whatever its
    value; a file that cannot be read as a JSON object counts as set, as for the hooks."""
    from maity.runner import capabilities

    assert capabilities.claude_socket_settings(AsUser(), "linux") is None  # no file
    user = Path.home() / ".claude" / "settings.json"
    user.parent.mkdir()
    user.write_text(text)
    found = capabilities.claude_socket_settings(AsUser(), "linux")
    assert (found is None) if why is None else (found is not None and why in found)
    if found is not None:
        assert str(user) in found


@pytest.mark.parametrize(
    ("text", "why"),
    [('{"sandbox": {"seccompConfig": {}}}', "sets sandbox.seccompConfig"),
     ('{"sandbox": {"network": {"allowAllUnixSockets": true}}}',
      "sets sandbox.network.allowAllUnixSockets"),
     ('{"sandbox": {"network": {"allowUnixSockets": []}}}',
      "sets sandbox.network.allowUnixSockets"),
     ('{"permissions": {}}', None), ("{not json", "cannot be read as JSON"),
     ("[]", "is not a JSON object")],
)  # fmt: skip
def test_managed_settings_may_carry_no_unix_socket_setting_either(
    text: str, why: str | None
) -> None:
    """The managed settings win over the placement's file: a key there, or a file that cannot
    be read as a JSON object, counts as the user's would; a drop-in counts like the file."""
    from maity.runner import capabilities

    managed = _managed(capabilities)
    managed.write_text(text)
    found = capabilities.claude_socket_settings(AsUser(), "linux")
    assert (found is None) if why is None else (found is not None and why in found)
    if found is not None:
        assert str(managed) in found
    managed.write_text('{"permissions": {}}')
    drop_ins = managed.parent / "managed-settings.d"
    drop_ins.mkdir()
    (drop_ins / "20-net.json").write_text(text)
    found = capabilities.claude_socket_settings(AsUser(), "linux")
    assert (found is None) if why is None else (found is not None and "20-net.json" in found)


@pytest.mark.parametrize(
    ("require", "on", "held", "refused"),
    [(None, True, False, False), (None, False, True, True), (None, False, False, False),
     (True, False, False, True), (True, True, False, False), (False, False, True, False)],
)  # fmt: skip
def test_the_sandbox_refusal(require: bool | None, on: bool, held: bool, refused: bool) -> None:
    """Unset: refused when only the version keeps the sandbox off; `false` is the opt-out."""
    from maity.runner import capabilities

    harness = config.Harness("claude-code", ("supervised",), "supervised", require_sandbox=require)
    assert capabilities.sandbox_refused(harness, on, held) is refused


@pytest.mark.parametrize(
    ("printed", "version"),
    [("2.1.295 (Claude Code)", "2.1.295"), ("v2.1.296", "2.1.296"),
     ("codex-cli 0.40.0", "0.40.0"), ("2.1.295--rc (Claude Code)", "2.1.295--rc"),
     ("2.1.295+ (Claude Code)", None), ("2.1.295-_dev", None), ("x2.1.295", None),
     ("2.1.295.", None)],
)  # fmt: skip
def test_a_version_is_a_token_of_its_own(printed: str, version: str | None) -> None:
    from maity.runner import capabilities

    found = capabilities.VERSION.search(printed)
    assert (found.group(0) if found else None) == version


def test_the_scratch_is_told_to_the_session_and_opened_in_both_sandboxes(tmp_path: Path) -> None:
    room = tmp_path / "ws" / "maity" / ".scratch" / "plc-0003"
    claude = context(tmp_path / "c", sandbox=True, scratch=room)
    settings = adapters.claude_settings(claude)
    assert settings["sandbox"]["filesystem"]["allowWrite"] == [str(room)]
    assert {f"{tool}(/{room}/**)" for tool in ("Read", "Edit", "Write")} <= set(
        settings["permissions"]["allow"]
    )
    codex = context(tmp_path / "x", "codex", sandbox=True, scratch=room,
                    workspaces=tmp_path / "ws")  # fmt: skip
    toml = adapters.codex_config(codex)
    hidden, opened = f'"{tmp_path / "ws"}" = "none"', f'"{room}" = "write"'
    assert hidden in toml and opened in toml  # the root stays hidden, its scratch opened again
    short = Path("/srv/ws/maity/.scratch/plc-0003")  # room for a socket under its tmp
    launched = adapters.launch(context(tmp_path / "s", "stub", scratch=short))
    assert launched.env["MAITY_SCRATCH"] == str(short)
    assert launched.env["TMPDIR"] == str(short / "tmp")


@pytest.mark.parametrize("layout", ["holder", "former"])
def test_the_own_projects_scratch_holder_is_denied_for_reading_and_only_the_scratch_reopened(
    tmp_path: Path, layout: str
) -> None:
    """tsk-07dwr3t80rg0 (the #2032 residual), tsk-c7zzd440x8pn: a scratch made after this
    session started must not be readable. The holder (every scratch's `<root>/.scratch`, or the
    project's own on a host with the former layout) goes in denyRead only (a write deny on it
    would mount the re-opened scratch read-only, as P3 showed for the leaf), and the allows
    name exactly the own scratch, with nothing denied for reading inside it."""
    ws = tmp_path / "ws"
    if layout == "holder":
        holder = ws / ".scratch"
        room, sibling = holder / "maity" / "plc-0003", holder / "maity" / "plc-0004"
        other = holder / "other"  # another project's directory, named whole by the supervisor
    else:
        holder = ws / "maity" / ".scratch"
        room, sibling = holder / "plc-0003", holder / "plc-0004"
        other = ws / "other" / ".scratch"  # another project's holder, named whole
    assert adapters.scratch_holder(room) == holder
    pg = ws / ".maity-pg"
    ctx = context(tmp_path / "c", sandbox=True, scratch=room, private=(sibling, other, pg))
    filesystem = adapters.claude_settings(ctx)["sandbox"]["filesystem"]
    assert str(holder) in filesystem["denyRead"] and str(holder) not in filesystem["denyWrite"]
    assert filesystem["allowRead"] == [str(room)] and filesystem["allowWrite"] == [str(room)]
    # What the sandbox may not read stays outside what it opens again: the clone and its
    # credential, the other scratches, the password holder.
    denied = [*filesystem["denyRead"], *filesystem["denyWrite"]]
    for path in denied:
        if path != str(holder):
            assert not Path(path).is_relative_to(room), path
    assert not ctx.clone.is_relative_to(room) and not room.is_relative_to(ctx.clone)
    assert {str(sibling), str(other), str(pg)} <= set(filesystem["denyRead"])
    # A scratch elsewhere (agy's under `/tmp`) or none: no holder denied, nothing opened again.
    agy = Path("/tmp/maity-scratch-1002") / ("a" * 32)  # noqa: S108 - a path only
    assert adapters.scratch_holder(agy) is None and adapters.scratch_holder(None) is None
    bare = adapters.claude_settings(context(tmp_path / "n", sandbox=True))["sandbox"]["filesystem"]
    assert "allowRead" not in bare and "allowWrite" not in bare
    assert not any(p.endswith("/.scratch") for p in bare["denyRead"])


def test_a_scratch_too_deep_for_a_socket_keeps_the_hosts_tmpdir(tmp_path: Path) -> None:
    # Claude Code binds its sandbox socket `claude-socks-<16 hex>.sock` under TMPDIR; a scratch
    # whose `tmp` leaves no room for it under the 107-byte Unix socket path broke every Claude
    # Code placement's sandbox (cli 0.1.0a16). Such a scratch is still named, TMPDIR is not.
    deep = Path("/") / ("w" * 60) / "maity" / ".scratch" / "plc-0000000000000003"
    assert len(str(deep / "tmp")) + 1 + adapters.SOCKET_NAME_ROOM > adapters.SOCKET_PATH_MAX
    launched = adapters.launch(context(tmp_path / "s", "stub", scratch=deep))
    assert launched.env["MAITY_SCRATCH"] == str(deep)
    assert "TMPDIR" not in launched.env
    room = Path("/srv/ws/maity/.scratch/plc-0003")
    assert adapters.scratch_tmpdir(room) == room / "tmp"
    longest = Path("/" + "x" * (adapters.SOCKET_PATH_MAX - adapters.SOCKET_NAME_ROOM - 6))
    assert len(str(longest / "tmp")) + 1 + adapters.SOCKET_NAME_ROOM == adapters.SOCKET_PATH_MAX
    assert adapters.scratch_tmpdir(longest) == longest / "tmp"  # exactly at the limit fits
    assert adapters.scratch_tmpdir(Path(str(longest) + "x")) is None
    assert adapters.scratch_tmpdir(None) is None


def test_the_socket_limit_is_pinned_per_platform_and_counted_in_bytes() -> None:
    assert adapters.socket_path_max("linux") == 107
    assert adapters.socket_path_max("darwin") == 103
    assert adapters.socket_path_max("freebsd14") == 103
    # Bytes, not characters: a non-ASCII name takes more room than its length says.
    room = adapters.SOCKET_PATH_MAX - adapters.SOCKET_NAME_ROOM - 1 - len("/tmp")  # noqa: S108
    ascii_fits = Path("/" + "a" * (room - 1))
    assert adapters.scratch_tmpdir(ascii_fits) == ascii_fits / "tmp"
    wide = Path("/" + "ä" * (room - 1))  # same number of characters, twice the bytes
    assert adapters.scratch_tmpdir(wide) is None


def test_the_test_slots_and_cluster_go_in_the_placements_own_scratch(tmp_path: Path) -> None:
    """tsk-w7qtcbzcshn9: the scripts' defaults under `~/.local/state` no sandbox writes, so the
    slots and the cluster go in the scratch, per placement; no path is opened beyond it."""
    room = Path("/srv/ws/maity/.scratch/plc-0003")
    passfile = Path("/srv/ws/.maity-pg/plc-0003")
    bare = adapters.launch(context(tmp_path / "b", "stub", scratch=room))
    launched = adapters.launch(context(tmp_path / "s", "stub", scratch=room, pg_pass=passfile))
    assert launched.env["MAITY_RUN_SLOTS_DIR"] == str(room / "slots")
    # The cluster and its password come from `pgenv`, outside the sandbox, never in the launch's
    # env (tmux keeps that in its session environment) or the loop's spec (the review of #2032).
    assert not {"MAITY_PG_DIR", "MAITY_PG_PASSWORD"} & set(launched.env)
    pgenv = [*AsUser().runner_module("pgenv"), "/srv/ws", str(passfile), str(room / "pg"), "--"]
    assert launched.argv == [*pgenv, *bare.argv]
    # Without a password file the runner vouched for, no cluster: it would be made with trust.
    assert bare.env["MAITY_RUN_SLOTS_DIR"] == str(room / "slots")
    assert "MAITY_PG_DIR" not in bare.env and "maity.runner.pgenv" not in bare.argv
    claude = context(tmp_path / "c", sandbox=True, scratch=room)
    assert adapters.claude_settings(claude)["sandbox"]["filesystem"]["allowWrite"] == [str(room)]
    codex = context(tmp_path / "x", "codex", sandbox=True, scratch=room,
                    workspaces=Path("/srv/ws"))  # fmt: skip
    written = [line for line in adapters.codex_config(codex).splitlines()
               if line.endswith('= "write"')]  # fmt: skip
    assert written == [f'"{tmp_path / "x" / "ws" / "maity" / "agent-3"}" = "write"',
                       f'"{tmp_path / "x" / "ws" / "maity" / "agent-3" / ".git"}" = "write"',
                       f'"{room}" = "write"']  # fmt: skip


def test_an_ssh_hosts_session_gets_no_test_cluster(tmp_path: Path) -> None:
    """pgenv is a module of the runner's own interpreter, never a `maity` subcommand (an agent's
    `maity` runs outside its sandbox): a host whose interpreter the runner does not know gets
    no cluster, and nothing is started through `maity runner`."""

    class Elsewhere(AsUser):
        @property
        def here(self) -> bool:
            return False

    room = Path("/srv/ws/maity/.scratch/plc-0003")
    ctx = context(tmp_path / "r", "stub", scratch=room, as_user=Elsewhere(),
                  pg_pass=Path("/srv/ws/.maity-pg/plc-0003"))  # fmt: skip
    launched = adapters.pg_launch(ctx, adapters.Launch(["stub"], {}))
    assert launched.argv == ["stub"]


def test_a_claude_code_placement_gets_the_test_slots_but_no_cluster(tmp_path: Path) -> None:
    """Claude Code's sandbox refuses socket(AF_UNIX) even in the placement's own scratch (a
    probe on #2032), so with_postgres.sh's cluster cannot start there: no pgenv, even with a
    password file, while the slots stay (tsk-zk2cse7s2rf7 brings the cluster over TCP)."""
    room = Path("/srv/ws/maity/.scratch/plc-0003")
    passfile = Path("/srv/ws/.maity-pg/plc-0003")
    assert adapters.pg_dir(room) is not None  # the socket would fit: only the harness decides
    assert not adapters.gets_test_cluster("claude-code")
    assert adapters.gets_test_cluster("codex") and adapters.gets_test_cluster("stub")
    ctx = context(tmp_path / "c", scratch=room, pg_pass=passfile)
    assert adapters.pg_launch(ctx, adapters.Launch(["claude"], {})).argv == ["claude"]
    launched = adapters.launch(ctx)
    assert launched.argv[0] == "/usr/bin/claude" and "maity.runner.pgenv" not in launched.argv
    assert launched.env["MAITY_RUN_SLOTS_DIR"] == str(room / "slots")
    assert not {"MAITY_PG_DIR", "MAITY_PG_PASSWORD"} & set(launched.env)
    # Codex is not probed yet and keeps the cluster.
    codex = context(tmp_path / "x", "codex", scratch=room, pg_pass=passfile)
    assert adapters.pg_launch(codex, adapters.Launch(["codex"], {})).argv[1:4] == [
        "-I", "-m", "maity.runner.pgenv"]  # fmt: skip


SKILL = Path("/home/op/.local/share/maity-runner/skills/keep-the-why/" + "a" * 40 + "/plugin")


def test_a_claude_code_session_gets_the_skill_as_a_plugin_it_reads_and_never_writes(
    tmp_path: Path,
) -> None:
    """tsk-172s8y208whg: the delivered Keep the Why skill for this session only (`--plugin-dir`),
    its files readable through Read (the skill sends the agent to its references) and nowhere
    writable: an Edit deny and the sandbox's denyWrite, whatever the clone's rules say."""
    ctx = context(tmp_path, sandbox=True, skill=SKILL)
    launched = adapters.launch(ctx)
    assert f"--plugin-dir={SKILL}" in launched.argv
    assert launched.argv.index(f"--plugin-dir={SKILL}") < len(launched.argv) - 1  # not the prompt
    assert launched.env["MAITY_KTW_SKILL_DIR"] == str(SKILL / "skills" / "keep-the-why")
    settings = adapters.claude_settings(ctx)
    allow, deny = settings["permissions"]["allow"], settings["permissions"]["deny"]
    assert f"Read(/{SKILL}/**)" in allow
    assert not [r for r in allow if str(SKILL) in r and not r.startswith("Read(")]
    assert f"Edit(/{SKILL}/**)" in deny
    assert str(SKILL) in settings["sandbox"]["filesystem"]["denyWrite"]
    assert str(SKILL) not in settings["sandbox"]["filesystem"].get("allowWrite", [])


def test_in_the_agent_user_layout_the_agents_copy_is_read_and_never_written(
    tmp_path: Path,
) -> None:
    """tsk-7casfxb7cn49: the copy the runner puts below the agents' user's home is reached by
    the same rules, no wider: Read on it, an Edit deny and the sandbox's denyWrite, and it lies
    under none of the paths the sandbox denies reading (not under the agents' files,
    `~/.maity-runner`, which every sandbox is denied), so no allow has to re-open it."""
    home = Path("/home/agents")
    skill = home / ".local/share/maity-runner/skills/keep-the-why" / ("a" * 40 + "-" + "b" * 16)
    skill = skill / "plugin"
    clone = tmp_path / "ws" / "maity" / "agent-3"
    extra = (tmp_path / "runner.toml", home / ".maity-runner")  # the config and agent_files
    private = supervisor.private_paths(tmp_path / "st", home, clone, (), extra)
    ctx = context(tmp_path, sandbox=True, skill=skill, as_user=AsUser("agents"), private=private)
    settings = adapters.claude_settings(ctx)
    allow, deny = settings["permissions"]["allow"], settings["permissions"]["deny"]
    filesystem = settings["sandbox"]["filesystem"]
    assert f"Read(/{skill}/**)" in allow and f"Edit(/{skill}/**)" in deny
    assert str(skill) in filesystem["denyWrite"]
    assert not [p for p in filesystem["denyRead"] if Path(p) == skill or Path(p) in skill.parents]
    assert "allowRead" not in filesystem and str(skill) not in filesystem.get("allowWrite", [])
    # agy's write_file deny for the same copy: test_antigravity.py.


def test_without_a_delivered_skill_nothing_of_it_is_set(tmp_path: Path) -> None:
    ctx = context(tmp_path, sandbox=True)
    launched = adapters.launch(ctx)
    assert not [a for a in launched.argv if a.startswith("--plugin-dir")]
    assert "MAITY_KTW_SKILL_DIR" not in launched.env
    settings = adapters.claude_settings(ctx)
    assert not [r for r in settings["permissions"]["allow"] if "skills" in r]


def test_every_harness_is_told_where_the_delivered_skill_lies(tmp_path: Path) -> None:
    # Codex has no plugin flag the runner uses yet: the variable, which the resume block names.
    codex = context(tmp_path, "codex", skill=SKILL)
    expected = str(SKILL / "skills" / "keep-the-why")
    assert adapters.skill_env(codex) == {"MAITY_KTW_SKILL_DIR": expected}
    assert adapters.skill_env(context(tmp_path / "n", "codex")) == {}


def test_an_agy_placement_gets_no_test_slots_or_cluster(tmp_path: Path) -> None:
    """agy's scratch under `/tmp` is read-only to it but for `tmp` (the review of #2032), so a
    slot directory or cluster there could not be written: it keeps the scripts' defaults."""
    room = Path("/tmp/maity-scratch-1000/" + "a" * 32)  # noqa: S108 - a path, nothing written
    folder = tmp_path / "g" / "ws"
    ctx = context(tmp_path / "g", "antigravity", scratch=room,
                  pg_pass=Path("/srv/ws/.maity-pg/plc-0003"))  # fmt: skip
    launched = adapters.launch(dataclasses.replace(ctx, folder=folder))
    assert launched.env["MAITY_SCRATCH"] == str(room)
    assert not {"MAITY_RUN_SLOTS_DIR", "MAITY_PG_DIR"} & set(launched.env)
    assert "maity.runner.pgenv" not in launched.argv


def test_a_cluster_whose_socket_would_not_fit_gets_no_pg_dir(tmp_path: Path) -> None:
    # with_postgres.sh binds `<MAITY_PG_DIR>/.s.PGSQL.<port>`; past the Unix socket limit the
    # server cannot start, so the session gets no MAITY_PG_DIR (the slots still go there).
    room = adapters.SOCKET_PATH_MAX - adapters.PG_SOCKET_ROOM - 1 - len("/pg")
    fits = Path("/" + "s" * (room - 1))
    assert len(str(fits / "pg")) + 1 + adapters.PG_SOCKET_ROOM == adapters.SOCKET_PATH_MAX
    assert adapters.pg_dir(fits) == fits / "pg"  # exactly at the limit fits
    deep = Path(str(fits) + "s")
    assert adapters.pg_dir(deep) is None
    launched = adapters.launch(context(tmp_path / "s", "stub", scratch=deep,
                                      pg_pass=Path("/w/.maity-pg/plc-0003")))  # fmt: skip
    assert "MAITY_PG_DIR" not in launched.env and "maity.runner.pgenv" not in launched.argv
    assert launched.env["MAITY_RUN_SLOTS_DIR"] == str(deep / "slots")
    assert adapters.pg_dir(None) is None and adapters.run_env(None) == {}


def test_the_run_name_is_handle_and_instance(tmp_path: Path) -> None:
    placement = {**PLACEMENT, "agent": {"id": "agt-b", "handle": "maity-coder-7"},
                 "instance": "xpde"}  # fmt: skip
    launched = adapters.launch(context(tmp_path / "s", "stub", placement=placement))
    assert launched.env["MAITY_RUN_NAME"] == "maity-coder-7#xpde"
    assert adapters.run_name({**placement, "instance": None}) == "maity-coder-7"  # before a join
    for bad in ("a b", "a\tb", "#x", "", None, "x" * 65, "agent\n", "a\nb"):
        assert adapters.run_name({**placement, "agent": {"handle": bad}}) is None
        assert adapters.run_name({**placement, "instance": bad}) == "maity-coder-7"
    assert adapters.run_name({"id": "plc-0003"}) is None
    assert adapters.run_name({"agent": "maity-coder-7"}) is None


def test_without_a_scratch_nothing_names_one(tmp_path: Path) -> None:
    ctx = context(tmp_path, sandbox=True)
    assert "allowWrite" not in adapters.claude_settings(ctx)["sandbox"]["filesystem"]
    assert ".scratch" not in adapters.codex_config(context(tmp_path / "x", "codex", sandbox=True))
    launched = adapters.launch(context(tmp_path / "s", "stub"))
    assert "MAITY_SCRATCH" not in launched.env and "TMPDIR" not in launched.env
    assert not {"MAITY_RUN_SLOTS_DIR", "MAITY_PG_DIR", "MAITY_PG_PASSWORD",
                "MAITY_RUN_NAME"} & set(launched.env)  # fmt: skip
