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
