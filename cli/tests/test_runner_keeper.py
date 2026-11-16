"""The runner's tool keeper (§15.16): the first install at start, the daily check, the owner's
`Update now`, logins, and what `capabilities.tools` says; against a fake vendor."""

from __future__ import annotations

import argparse
import dataclasses
import tomllib
from pathlib import Path
from typing import Any

import pytest
from test_runner import MINIMAL, parse
from test_runner_tools import FakeInstaller

from maity import __version__
from maity.runner import adapters, capabilities, commands, config, keeper, supervisor, tools
from maity.runner.asuser import RUNNER

BASE = MINIMAL.format(url="https://hub.example", state_dir="/srv/runner-state")
DAY = 24 * 3600.0
T0 = 1_794_643_200.0  # 2026-11-14T00:00:00Z


class FakeClient:
    def __init__(self) -> None:
        self.view: dict[str, Any] = {"update_requests": []}
        self.reads = 0

    def call(self, method: str, path: str, **_: Any) -> Any:
        assert (method, path) == ("GET", "/runner")
        self.reads += 1
        return self.view


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeInstaller:
    installer = FakeInstaller()
    monkeypatch.setitem(tools.INSTALLERS, "codex", lambda: installer)
    return installer


def make(
    tmp_path: Path, harness: str, clock: list[float] | None = None
) -> tuple[keeper.Keeper, FakeClient, list[str]]:
    cfg = dataclasses.replace(parse(BASE + harness), tools_dir=tmp_path / "tools")
    client = FakeClient()
    probes = {h.id: capabilities.probe(h, "/nonexistent", RUNNER, cfg.tools_dir)
              for h in cfg.harnesses.values()}  # fmt: skip
    advertised = capabilities.build(cfg, probes)
    published: list[str] = []
    now = clock if clock is not None else [T0]
    keep = keeper.Keeper(
        cfg, client, published.append, probes, advertised, "/nonexistent", RUNNER,  # type: ignore[arg-type]
        advertise=lambda: published.append("PATCH"), now=lambda: now[0],
    )  # fmt: skip
    return keep, client, published


def tool(keep: keeper.Keeper, tool_id: str) -> dict[str, Any]:
    return next(e for e in keep.advertised["tools"] if e["id"] == tool_id)


def test_a_missing_tool_is_installed_at_start_and_offered(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    keep, client, published = make(tmp_path, "\n[harness.codex]\ninstall = true\n")
    assert keep.probes["codex"].reason == "binary_not_found"  # never the PATH's
    assert keep.entries()[0]["state"] == "installing"
    keep.step()
    found = keep.probes["codex"]
    assert (found.reason, found.version) == (None, "1.0.0")
    assert found.path == str(tools.binary(keep.cfg.tools_dir, "codex"))
    entry = tool(keep, "codex")
    assert (entry["version"], entry["state"], entry["install"], entry["update"]) == (
        "1.0.0", "current", True, "never",
    )  # fmt: skip
    harness = next(h for h in keep.advertised["harnesses"] if h["id"] == "codex")
    assert (harness["available"], harness["version"]) == (True, "1.0.0")
    assert "PATCH" in published
    fake.offered = "1.1.0"
    keep.step()  # update = "never": installed once, never looked at again
    assert fake.installed == ["1.0.0"]
    assert client.reads == 0  # nothing updates daily: Update now is never read


def test_the_daily_check_runs_once_a_day(tmp_path: Path, fake: FakeInstaller) -> None:
    clock = [T0]
    keep, _, _ = make(tmp_path, '\n[harness.codex]\ninstall = true\nupdate = "daily"\n', clock)
    keep.step()
    fake.offered = "1.1.0"
    clock[0] += DAY - 60
    keep.step()
    assert fake.installed == ["1.0.0"]
    clock[0] += 60
    keep.step()
    assert fake.installed == ["1.0.0", "1.1.0"]
    entry = tool(keep, "codex")
    assert (entry["version"], entry["previous_version"], entry["latest"]) == (
        "1.1.0", "1.0.0", "1.1.0",
    )  # fmt: skip


def test_update_now_is_carried_out_once_and_named_in_the_report(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    keep, client, _ = make(tmp_path, '\n[harness.codex]\ninstall = true\nupdate = "daily"\n')
    keep.step()
    fake.offered = "1.1.0"
    client.view = {
        "update_requests": [{"tool": "codex", "requested_at": "2026-11-14T09:00:00.123Z"}]
    }
    keep.step()
    entry = tool(keep, "codex")
    assert (entry["version"], entry["state"], entry["update_requested_at"]) == (
        "1.1.0", "current", "2026-11-14T09:00:00.123Z",
    )  # fmt: skip
    fake.offered = "1.2.0"
    keep.step()  # the same request, still standing until the hub reads the report
    assert fake.installed == ["1.0.0", "1.1.0"]
    client.view = {"update_requests": [{"tool": "codex", "requested_at": "2026-11-14T10:00:00Z"}]}
    keep.step()
    assert fake.installed == ["1.0.0", "1.1.0", "1.2.0"]


def test_a_tool_without_a_login_is_not_offered(
    tmp_path: Path, fake: FakeInstaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(keeper, "logged_in", lambda harness_id, binary, as_user: False)
    keep, _, _ = make(tmp_path, "\n[harness.codex]\ninstall = true\n")
    keep.step()
    assert keep.probes["codex"].reason == "login_needed"
    harness = next(h for h in keep.advertised["harnesses"] if h["id"] == "codex")
    assert (harness["available"], harness["reason"]) == (False, "login_needed")
    entry = tool(keep, "codex")
    assert (entry["state"], entry["reason"], entry["version"]) == ("login_needed", None, "1.0.0")


def test_unmanaged_tools_and_maity_are_reported_as_found(tmp_path: Path) -> None:
    keep, _, _ = make(tmp_path, "\n[harness.codex]\n")
    entries = {e["id"]: e for e in keep.entries()}
    assert entries["codex"]["state"] == "missing"
    assert (entries["codex"]["install"], entries["codex"]["update"]) == (False, "never")
    assert entries["maity"]["version"] == __version__
    assert entries["maity"]["update"] == "never"
    assert all(set(e) == set(entries["maity"]) for e in entries.values())


def test_a_rollback_on_the_machine_reaches_new_sessions_and_the_hub(
    tmp_path: Path, fake: FakeInstaller, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    keep, _, published = make(tmp_path, '\n[harness.codex]\ninstall = true\nupdate = "daily"\n')
    keep.step()
    fake.offered = "1.1.0"
    tools.take(keep.cfg.tools_dir, "codex", fake, "t")  # as the daily check would
    keep.step()
    newer = keep.probes["codex"].path
    monkeypatch.setattr(config, "load", lambda path: keep.cfg)
    args = argparse.Namespace(config=None, json=False, tools_action="rollback", tool="codex")
    assert commands.cmd_tools(args) == 0
    assert "new sessions start with 1.0.0; 1.1.0 stays" in capsys.readouterr().out
    published.clear()
    keep.step()
    assert keep.probes["codex"].version == "1.0.0" and keep.probes["codex"].path != newer
    assert tool(keep, "codex")["state"] == "rolled_back"
    assert "PATCH" in published
    listing = argparse.Namespace(config=None, json=False, tools_action=None)
    assert commands.cmd_tools(listing) == 0
    assert "codex: 1.0.0 (rolled_back); kept 1.1.0; latest 1.1.0" in capsys.readouterr().out
    other = argparse.Namespace(config=None, json=False, tools_action="rollback", tool="opencode")
    assert commands.cmd_tools(other) == 1


def test_a_managed_tool_never_updates_itself(tmp_path: Path) -> None:
    def ctx(harness_id: str, **managed: Any) -> adapters.Context:
        harness = config.Harness(harness_id, ("supervised",), "supervised", (), **managed)
        agent_dir = tmp_path / harness_id / str(len(managed)) / "agent"
        agent_dir.mkdir(parents=True)
        return adapters.Context(
            placement={"id": "plc-1", "mode": "interactive"}, harness=harness,
            binary="/opt/tool", clone=tmp_path / "clone", agent_dir=agent_dir,
            grant=config.RepositoryGrant(), restart=config.Restart(),
        )  # fmt: skip

    codex = tomllib.loads(adapters.codex_config(ctx("codex", update="daily")))
    assert codex["check_for_update_on_startup"] is False
    assert "check_for_update_on_startup" not in tomllib.loads(adapters.codex_config(ctx("codex")))
    on = adapters.launch(ctx("claude-code", install=True))
    assert on.env["DISABLE_UPDATES"] == "1"
    assert "DISABLE_UPDATES" not in adapters.launch(ctx("claude-code")).env


def test_sessions_on_an_older_binary_are_counted(tmp_path: Path) -> None:
    cfg = parse(BASE + "\n[harness.codex]\n[harness.claude-code]\n")
    sup = supervisor.Supervisor(cfg, None, None, lambda line: None, {})
    pairs = (("a", "codex"), ("b", "codex"), ("c", "codex"), ("d", "claude-code"))
    sup.desired = [{"id": p, "harness": h} for p, h in pairs]
    sup.records = {
        "a": supervisor.Record(state="running", binary="/t/codex/versions/1.1.0/bin/codex"),
        "b": supervisor.Record(state="running", binary="/t/codex/versions/1.0.0/bin/codex"),
        "c": supervisor.Record(state="exited", binary="/t/codex/versions/1.0.0/bin/codex"),
        "d": supervisor.Record(state="running", binary="/usr/bin/claude"),
    }
    assert sup.sessions_on("codex", "/t/codex/versions/1.1.0/bin/codex") == 1


def test_the_sandbox_follows_the_install_an_update_and_a_rollback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Claude Code's sandbox state (on, held for its version) is worked out again from the
    binary each install, update and rollback leaves, and reaches the target and the hub."""
    installer = FakeInstaller("1.0.0")  # older than CLAUDE_SANDBOX_MIN: held
    monkeypatch.setitem(tools.INSTALLERS, "claude-code", lambda: installer)
    monkeypatch.setattr(capabilities, "claude_sandbox_tools", lambda: ("bwrap", "socat"))
    monkeypatch.setattr(capabilities, "which", lambda name, path, as_user=RUNNER: f"/x/{name}")
    keep, _, published = make(
        tmp_path, '\n[harness.claude-code]\ninstall = true\nupdate = "daily"\n'
    )
    target_sandbox: dict[str, bool] = {"claude-code": False}
    target_held: set[str] = set()
    keep.sandbox, keep.held = target_sandbox, target_held  # the target's own, as serve passes

    def advertised() -> str:
        entry = next(h for h in keep.advertised["harnesses"] if h["id"] == "claude-code")
        return str(entry["sandbox"])

    def placed() -> tuple[bool, bool]:  # what the supervisor's refusal reads
        harness = keep.cfg.harnesses["claude-code"]
        on = target_sandbox["claude-code"]
        return on, capabilities.sandbox_refused(harness, on, "claude-code" in target_held)

    keep.step()  # the first install: 1.0.0
    assert (target_sandbox["claude-code"], target_held, advertised()) == (
        False, {"claude-code"}, "off",
    )  # fmt: skip
    assert placed() == (False, True)
    installer.offered = "2.1.300"
    keep.take(keep.cfg.harnesses["claude-code"])  # the update
    assert (target_sandbox["claude-code"], target_held, advertised()) == (True, set(), "on")
    assert placed() == (True, False)
    published.clear()
    assert tools.rollback(keep.cfg.tools_dir, "claude-code").version == "1.0.0"
    keep.step()  # the rollback on the machine, seen within a round
    assert (target_sandbox["claude-code"], target_held, advertised()) == (
        False, {"claude-code"}, "off",
    )  # fmt: skip
    assert "PATCH" in published


def test_a_managed_codex_is_sandbox_checked_as_its_own_binary(
    tmp_path: Path, fake: FakeInstaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never a codex the agents' PATH finds: the one new sessions start with."""
    on_path = tmp_path / "bin" / "codex"
    on_path.parent.mkdir()
    on_path.write_text("#!/bin/sh\n", encoding="utf-8")
    on_path.chmod(0o755)
    tried: list[str] = []

    def starts(binary: str, user: str | None = None) -> bool:
        tried.append(binary)
        return True

    monkeypatch.setattr(capabilities, "_codex_sandbox_starts", starts)
    cfg = dataclasses.replace(
        parse(BASE + "\n[harness.codex]\ninstall = true\n"), tools_dir=tmp_path / "tools"
    )
    harness = cfg.harnesses["codex"]
    path = str(on_path.parent)
    assert not capabilities.sandbox_available(harness, path, RUNNER, cfg.tools_dir)
    assert tried == []  # nothing installed yet: not the PATH's codex either
    tools.take(cfg.tools_dir, "codex", fake, "t")
    assert capabilities.sandbox_available(harness, path, RUNNER, cfg.tools_dir)
    assert tried == [str(tools.binary(cfg.tools_dir, "codex"))]
    entry = capabilities.harness_entry(harness, capabilities.Probe(None, "1.0.0", None), path,
                                       tools_dir=cfg.tools_dir)  # fmt: skip
    assert entry["sandbox"] == "on"
    unmanaged = parse(BASE + "\n[harness.codex]\n").harnesses["codex"]
    capabilities.sandbox_available(unmanaged, path, RUNNER, cfg.tools_dir)
    assert tried[-1] == str(on_path)  # an unmanaged codex is still the PATH's


def test_a_login_given_later_is_seen_within_a_round(
    tmp_path: Path, fake: FakeInstaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = [False]
    monkeypatch.setattr(keeper, "logged_in", lambda harness_id, binary, as_user: answer[0])
    keep, _, published = make(tmp_path, "\n[harness.codex]\ninstall = true\n")
    keep.step()
    assert keep.probes["codex"].reason == "login_needed"
    published.clear()
    keep.step()
    assert "PATCH" not in published  # asked again, nothing changed, nothing sent
    answer[0] = True  # the owner logged in on the machine
    keep.step()
    harness = next(h for h in keep.advertised["harnesses"] if h["id"] == "codex")
    assert (harness["available"], harness["reason"]) == (True, None)
    assert tool(keep, "codex")["state"] == "current"
    assert "PATCH" in published
    published.clear()
    keep.step()
    assert "PATCH" not in published  # logged in: not asked again


def test_install_false_never_installs_a_missing_tool(tmp_path: Path, fake: FakeInstaller) -> None:
    clock = [T0]
    keep, client, _ = make(tmp_path, '\n[harness.codex]\nupdate = "daily"\n', clock)
    keep.step()
    clock[0] += DAY
    keep.step()  # the daily check
    client.view = {"update_requests": [{"tool": "codex", "requested_at": "2026-11-14T09:00:00Z"}]}
    keep.step()  # Update now
    assert fake.installed == []
    assert tools.load(keep.cfg.tools_dir, "codex").version is None


def test_an_older_version_goes_once_no_session_runs_it(tmp_path: Path, fake: FakeInstaller) -> None:
    keep, _, published = make(tmp_path, '\n[harness.codex]\ninstall = true\nupdate = "daily"\n')
    keep.step()
    first = keep.probes["codex"].path
    assert first is not None
    for version in ("1.1.0", "1.2.0"):
        fake.offered = version
        keep.take(keep.cfg.harnesses["codex"])
    in_use: set[str] | None = {first}
    keep.binaries_in_use = lambda: in_use
    keep.step()
    assert Path(first).is_file()
    in_use = None  # a session whose binary is not known
    keep.step()
    assert Path(first).is_file()
    in_use = set()
    keep.step()
    assert not Path(first).exists()
    assert "tools: codex: 1.0.0 removed, no session uses it" in published


def test_update_now_for_a_tool_it_may_not_install_is_settled_at_once(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    """`install = false` and missing: Update now is not carried out, and the report names it,
    so the hub drops it instead of keeping it standing for good."""
    keep, client, published = make(tmp_path, '\n[harness.codex]\nupdate = "daily"\n')
    keep.step()
    client.view = {"update_requests": [{"tool": "codex", "requested_at": "2026-11-14T09:00:00Z"}]}
    keep.step()
    assert fake.installed == []
    entry = tool(keep, "codex")
    assert (entry["state"], entry["update_requested_at"]) == ("missing", "2026-11-14T09:00:00Z")
    assert "PATCH" in published
    published.clear()
    keep.step()  # the same request until the hub has read the report: not again
    assert not any("skipped" in line for line in published) and "PATCH" not in published
