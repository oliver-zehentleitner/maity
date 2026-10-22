from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from maity.runner import adapters, config, loop, supervisor

pytestmark = pytest.mark.skipif(sys.version_info < (3, 11), reason="maity runner needs 3.11")

PLACEMENT = {"id": "plc-0003", "mode": "interactive", "model": "opus"}


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
    assert argv[0] == "/usr/bin/claude" and argv[-1] == adapters.START_PROMPT
    assert argv[argv.index("--setting-sources") + 1] == "user"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in argv and argv[argv.index("--model") + 1] == "opus"
    settings = Path(argv[argv.index("--settings") + 1])
    assert settings.parent == ctx.agent_dir  # the runner's, outside the clone
    assert json.loads(Path(argv[argv.index("--mcp-config") + 1]).read_text()) == {"mcpServers": {}}
    assert launch.env == {"MAITY_PLACEMENT": "plc-0003"}


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
    assert f"Edit(/{ws}/.git/**)" in deny and f"Write(/{ws}/.git/**)" in deny  # config, hooks
    assert not any(rule.startswith("WebFetch") for rule in allow)
    assert settings["permissions"]["defaultMode"] == "dontAsk"
    assert "sandbox" not in settings
    strict = adapters.claude_settings(
        context(tmp_path / "s", sandbox=True, hosts=("maity.team", "github.com"))
    )["sandbox"]
    assert strict["enabled"] and strict["failIfUnavailable"]
    assert strict["allowUnsandboxedCommands"] is False
    assert strict["autoAllowBashIfSandboxed"] is False  # the allowlist still decides
    assert strict["filesystem"]["denyRead"][0].endswith("/.git/maity")
    assert strict["filesystem"]["denyWrite"] == strict["filesystem"]["denyRead"]
    assert strict["excludedCommands"] == ["maity *"]  # it alone reads the credential
    assert strict["network"] == {
        "allowedDomains": ["github.com", "maity.team"],
        "strictAllowlist": True,
    }


def test_claude_code_supervised_runs_the_loop(tmp_path: Path) -> None:
    ctx = context(tmp_path, placement={**PLACEMENT, "mode": "supervised", "model": None})
    launch = adapters.launch(ctx)
    assert launch.argv[1:4] == ["-I", "-m", "maity.runner.loop"]
    spec = json.loads(Path(launch.argv[-1]).read_text())
    assert spec["first"][-2:] == ["-p", adapters.SUPERVISED_PROMPT]
    assert spec["again"][-1] == "--continue" and "--model" not in spec["first"]
    assert spec["env"]["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] == "1"
    assert spec["restart"]["crash_cap"] == 5


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
    supervisor.Supervisor._exited(sup, rec, session, 100.0)
    assert (rec.state, rec.reason, rec.detail) == expected


# --- Codex and opencode ----------------------------------------------------------------------


def test_codex_config(tmp_path: Path) -> None:
    ctx = context(tmp_path, harness_id="codex", binary="/usr/bin/codex",
                  hosts=("maity.team", "github.com"),
                  grant=config.RepositoryGrant(network=("pypi.org",)))  # fmt: skip
    found = config.require_tomllib().loads(adapters.codex_config(ctx))
    assert found["approval_policy"] == "never" and found["default_permissions"] == "maity"
    assert found["projects"][str(ctx.clone)]["trust_level"] == "untrusted"  # no .codex/ layers
    assert found["permissions"]["maity"]["extends"] == ":workspace"
    assert found["permissions"]["maity"]["filesystem"] == {str(ctx.clone / ".git"): "write"}
    domains = found["permissions"]["maity"]["network"]["domains"]
    assert set(domains) == {"maity.team", "github.com", "pypi.org", *adapters.CODEX_PROVIDER_HOSTS}


def test_codex_launch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    (home / "codex").mkdir(parents=True)
    (home / "codex" / "auth.json").write_text("{}")
    monkeypatch.setenv("CODEX_HOME", str(home / "codex"))  # the operator's own, wherever it is
    ctx = context(tmp_path, harness_id="codex", binary="/usr/bin/codex",
                  placement={**PLACEMENT, "mode": "supervised", "model": "gpt-5.5"})  # fmt: skip
    launch = adapters.launch(ctx)
    codex_home = Path(launch.env["CODEX_HOME"])
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
    assert list(rules["bash"])[-1] in adapters.GIT_DENIED  # denies last: the last match wins
    secret = f"{ctx.clone}/.git/maity/*"
    for tool in ("read", "edit"):
        assert rules[tool] == {"*": "allow", secret: "deny"}
    assert rules["webfetch"] == "deny" and rules["external_directory"] == "deny"
    assert settings["instructions"] == [str(ctx.clone / "AGENTS.md")]


def test_opencode_supervised(tmp_path: Path) -> None:
    ctx = context(tmp_path, harness_id="opencode", binary="/usr/bin/opencode",
                  placement={**PLACEMENT, "mode": "supervised"})  # fmt: skip
    spec = json.loads(Path(adapters.launch(ctx).argv[-1]).read_text())
    assert spec["first"][:4] == ["/usr/bin/opencode", "run", "--dir", str(ctx.clone)]
    assert "--continue" in spec["again"] and "--continue" not in spec["first"]


def test_codex_is_advertised_as_sandbox_confined() -> None:
    from maity.runner import capabilities

    codex = config.Harness("codex", ("supervised",), "supervised")
    entry = capabilities.harness_entry(codex, capabilities.Probe("/usr/bin/codex", "1.0", None))
    assert entry["confinement"] == "sandbox" and entry["sandbox"] == "on"
    assert capabilities.sandbox_available(codex)
