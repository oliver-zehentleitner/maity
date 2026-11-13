from __future__ import annotations

import dataclasses
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

from maity import __version__, clonecheck
from maity.runner import adapters, config, loop, supervisor
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


def test_claude_code_grant(tmp_path: Path) -> None:
    ctx = context(tmp_path)
    settings = adapters.claude_settings(ctx)
    ws = str(ctx.clone)
    allow, deny = settings["permissions"]["allow"], settings["permissions"]["deny"]
    assert "Bash(maity *)" in allow and "Bash(make test)" in allow
    assert "Bash(git *)" not in allow  # `-c`, `--no-index` and friends run or read anything
    assert "Bash(git commit *)" in allow and "Bash(git push *)" in allow
    assert "Bash(git -c *)" in deny and "Bash(git * --no-index*)" in deny
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
    assert "sandbox" not in settings and "hooks" not in settings  # no exclusion, no hook
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
    }


def test_under_the_sandbox_every_tool_call_passes_the_plain_call_hook(tmp_path: Path) -> None:
    settings = adapters.claude_settings(context(tmp_path, sandbox=True))
    assert settings["disableAllHooks"] is False
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
    assert codex_home.parent == ctx.agent_dir
    assert (codex_home / "auth.json").resolve() == (home / "codex" / "auth.json").resolve()
    assert (ctx.clone / ".git" / "maity").is_dir()
    spec = json.loads(Path(launch.argv[-1]).read_text())
    assert spec["first"][:4] == ["/usr/bin/codex", "exec", "-C", str(ctx.clone)]
    assert spec["again"][-3:-1] == ["resume", "--last"] and "gpt-5.5" in spec["first"]
    assert spec["env"]["CODEX_HOME"] == str(codex_home)


def test_opencode_launch(tmp_path: Path) -> None:
    ctx = context(tmp_path, harness_id="opencode", binary="/usr/bin/opencode",
                  placement={**PLACEMENT, "mode": "interactive", "model": None})  # fmt: skip
    launch = adapters.launch(ctx)
    assert launch.env["OPENCODE_DISABLE_PROJECT_CONFIG"] == "1"
    assert launch.argv == ["/usr/bin/opencode", str(ctx.clone), "--prompt", adapters.START_PROMPT]
    settings = json.loads(Path(launch.env["OPENCODE_CONFIG"]).read_text())
    rules = settings["permission"]
    assert list(rules)[0] == "*" and rules["*"] == "deny"  # first: the last match wins
    assert rules["bash"]["*"] == "deny" and rules["bash"]["make test *"] == "allow"
    assert "git *" not in rules["bash"] and rules["bash"]["git commit *"] == "allow"
    denied = (*adapters.GIT_DENIED, *adapters.GH_DENIED)
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
    ctx = context(tmp_path, harness_id="opencode", binary="/usr/bin/opencode",
                  placement={**PLACEMENT, "mode": "supervised"})  # fmt: skip
    spec = json.loads(Path(adapters.launch(ctx).argv[-1]).read_text())
    assert spec["first"][:4] == ["/usr/bin/opencode", "run", "--dir", str(ctx.clone)]
    assert "--continue" in spec["again"] and "--continue" not in spec["first"]


def test_codex_is_advertised_as_sandbox_confined(monkeypatch: pytest.MonkeyPatch) -> None:
    from maity.runner import capabilities

    codex = config.Harness("codex", ("supervised",), "supervised", binary="codex")
    monkeypatch.setattr("shutil.which", lambda name, path=None: "/usr/bin/codex")
    monkeypatch.setattr(capabilities, "_codex_sandbox_starts", lambda binary, user=None: True)
    entry = capabilities.harness_entry(codex, capabilities.Probe("/usr/bin/codex", "1.0", None))
    assert entry["confinement"] == "sandbox" and entry["sandbox"] == "on"
    assert capabilities.sandbox_available(codex)


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


def test_claude_code_denies_reading_the_runner_state_and_home_secrets(tmp_path: Path) -> None:
    secrets = (tmp_path / "st", tmp_path / "home" / ".ssh")
    ctx = context(tmp_path, private=secrets, workspaces=tmp_path / "ws", sandbox=True)
    deny = adapters.claude_settings(ctx)["sandbox"]["filesystem"]["denyRead"]
    assert deny == [f"{ctx.clone}/.git/maity", *(str(p) for p in secrets)]
    assert str(tmp_path / "ws") not in deny  # it holds the clone; see the context entry


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
