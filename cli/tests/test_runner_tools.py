"""The runner's managed harness tools (docs/api.md §15.16): configuration, side-by-side
versions, the update check and rollback, against a fake vendor installer."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from test_runner import MINIMAL, parse, problems

from maity.runner import installers, tools

# The real installers register on import (config imports them lazily); imported first, so a
# test's fake replaces them and nothing here ever reaches a vendor.
assert installers.INSTALLERS_REGISTERED

BASE = MINIMAL.format(url="https://hub.example", state_dir="/srv/runner-state")


class FakeInstaller:
    """Writes a script that prints its version; `broken` versions print something else."""

    def __init__(self, latest: str = "1.0.0") -> None:
        self.offered = latest
        self.broken: set[str] = set()
        self.unreachable = False
        self.installed: list[str] = []

    def latest(self) -> str:
        if self.unreachable:
            raise tools.InstallError("network")
        return self.offered

    def install(self, version: str, into: Path) -> Path:
        self.installed.append(version)
        found = into / "bin" / "tool"
        found.parent.mkdir()
        answer = "garbage" if version in self.broken else version
        found.write_text(f"#!/bin/sh\necho {answer}\n", encoding="utf-8")
        found.chmod(found.stat().st_mode | stat.S_IXUSR)
        return found

    def version_of(self, binary: Path) -> str | None:
        text = binary.read_text(encoding="utf-8")
        return text.split("echo ", 1)[1].strip()


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> FakeInstaller:
    installer = FakeInstaller()
    monkeypatch.setitem(tools.INSTALLERS, "codex", lambda: installer)
    return installer


def test_install_and_update_are_off_by_default() -> None:
    cfg = parse(BASE + "\n[harness.codex]\n")
    assert (cfg.harnesses["codex"].install, cfg.harnesses["codex"].update) == (False, "never")
    assert cfg.maity_update == "never"


def test_the_configuration_names_install_and_update(fake: FakeInstaller) -> None:
    cfg = parse(
        BASE + '\n[harness.codex]\ninstall = true\nupdate = "daily"\n[maity]\nupdate = "daily"\n'
    )
    assert (cfg.harnesses["codex"].install, cfg.harnesses["codex"].update) == (True, "daily")
    assert cfg.maity_update == "daily"


def test_a_harness_without_an_installer_cannot_be_managed() -> None:
    found = problems(BASE + "\n[harness.opencode]\ninstall = true\n")
    assert any("no installer for this harness" in p for p in found), found


def test_a_managed_tool_takes_no_binary_of_the_operators(fake: FakeInstaller) -> None:
    found = problems(BASE + '\n[harness.codex]\nupdate = "daily"\nbinary = "/opt/codex"\n')
    assert any("binary" in p for p in found), found
    assert problems(BASE + '\n[harness.codex]\nupdate = "weekly"\n')
    assert problems(BASE + '\n[maity]\nupdate = "hourly"\n')


def test_the_first_install_and_an_update_keep_the_version_before(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    state = tools.take(tmp_path, "codex", fake, "2026-11-14T06:00:00Z")
    assert (state.version, state.previous_version, state.state) == ("1.0.0", None, "current")
    first = tools.binary(tmp_path, "codex")
    assert first is not None and first.is_file()
    fake.offered = "1.1.0"
    state = tools.take(tmp_path, "codex", fake, "2026-11-15T06:00:00Z")
    assert (state.version, state.previous_version) == ("1.1.0", "1.0.0")
    assert first.is_file()  # a session that started on it keeps running it
    assert tools.binary(tmp_path, "codex") != first
    fake.offered = "1.2.0"
    tools.take(tmp_path, "codex", fake, "2026-11-16T06:00:00Z")
    assert first.is_file()  # an install never removes a version: prune does
    assert tools.prune(tmp_path, "codex", set()) == ["1.0.0"]
    assert not first.exists()  # one kept version, not more
    assert tools.take(tmp_path, "codex", fake, "now").version == "1.2.0"  # nothing newer
    assert fake.installed == ["1.0.0", "1.1.0", "1.2.0"]


def test_prune_keeps_a_version_a_running_session_started_from(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    tools.take(tmp_path, "codex", fake, "t1")
    first = tools.binary(tmp_path, "codex")
    assert first is not None
    for version in ("1.1.0", "1.2.0"):
        fake.offered = version
        tools.take(tmp_path, "codex", fake, "t")
    assert tools.prune(tmp_path, "codex", {str(first)}) == []  # a session still runs it
    assert tools.prune(tmp_path, "codex", None) == []  # a session whose binary is unknown
    assert first.is_file()
    assert tools.prune(tmp_path, "codex", set()) == ["1.0.0"]  # it has ended
    assert sorted(p.name for p in (tmp_path / "codex" / "versions").iterdir()) == [
        "1.1.0", "1.2.0",
    ]  # fmt: skip


def test_a_rollback_while_an_update_runs_is_refused_and_overwrites_nothing(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    tools.take(tmp_path, "codex", fake, "t1")
    fake.offered = "1.1.0"
    tools.take(tmp_path, "codex", fake, "t2")
    seen: list[str] = []
    install = fake.install

    def install_with_a_rollback(version: str, into: Path) -> Path:
        # `maity runner tools rollback` from another shell, mid-install; a new open file,
        # so the lock is contended as from another process
        with pytest.raises(ValueError, match="an install or update is running"):
            tools.rollback(tmp_path, "codex")
        seen.append(str(tools.prune(tmp_path, "codex", set())))  # nor is anything removed
        return install(version, into)

    fake.install = install_with_a_rollback  # type: ignore[method-assign]
    fake.offered = "1.2.0"
    state = tools.take(tmp_path, "codex", fake, "t3")
    assert seen == ["[]"]
    assert (state.version, state.previous_version) == ("1.2.0", "1.1.0")
    assert tools.load(tmp_path, "codex").version == "1.2.0"
    assert (tmp_path / "codex" / "versions" / "1.0.0").is_dir()
    done = tools.rollback(tmp_path, "codex")  # once the update is done, it goes through
    assert (done.version, done.previous_version) == ("1.1.0", "1.2.0")


def test_a_version_that_does_not_run_is_removed_and_reported(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    tools.take(tmp_path, "codex", fake, "t1")
    fake.offered = "1.1.0"
    fake.broken.add("1.1.0")
    state = tools.take(tmp_path, "codex", fake, "t2")
    assert (state.version, state.state, state.reason) == ("1.0.0", "failed", "version_failed")
    assert not tools.version_dir(tmp_path, "codex", "1.1.0").exists()
    assert tools.take(tmp_path, "codex", fake, "t3").version == "1.0.0"  # not tried again
    assert fake.installed == ["1.0.0", "1.1.0"]


def test_an_unreachable_vendor_is_network(tmp_path: Path, fake: FakeInstaller) -> None:
    fake.unreachable = True
    state = tools.take(tmp_path, "codex", fake, "t1")
    assert (state.version, state.state, state.reason) == (None, "failed", "network")


def test_rollback_swaps_and_a_second_rollback_swaps_back(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    """The contract's example: 320 in use, 308 kept, latest 320 (§15.16)."""
    fake.offered = "2.1.308"
    tools.take(tmp_path, "codex", fake, "t1")
    fake.offered = "2.1.320"
    tools.take(tmp_path, "codex", fake, "t2")
    state = tools.rollback(tmp_path, "codex")
    assert (state.version, state.previous_version, state.state) == (
        "2.1.308",
        "2.1.320",
        "rolled_back",
    )
    again = tools.take(tmp_path, "codex", fake, "t3")  # the daily check finds 320 and leaves it
    assert (again.version, again.state) == ("2.1.308", "rolled_back")
    state = tools.rollback(tmp_path, "codex")
    assert (state.version, state.previous_version, state.state) == (
        "2.1.320",
        "2.1.308",
        "current",
    )
    tools.rollback(tmp_path, "codex")
    fake.offered = "2.1.321"  # a newer one ends rolled_back
    state = tools.take(tmp_path, "codex", fake, "t4")
    assert (state.version, state.previous_version, state.state) == (
        "2.1.321",
        "2.1.308",
        "current",
    )


def test_rollback_needs_a_kept_version(tmp_path: Path, fake: FakeInstaller) -> None:
    tools.take(tmp_path, "codex", fake, "t1")
    with pytest.raises(ValueError, match="no kept version"):
        tools.rollback(tmp_path, "codex")


def test_the_report_follows_the_contract(tmp_path: Path, fake: FakeInstaller) -> None:
    missing = tools.report(tmp_path, "codex", install=False, update="never", sessions_on_older=0)
    assert (missing["version"], missing["state"], missing["latest"]) == (None, "missing", None)
    tools.take(tmp_path, "codex", fake, "2026-11-14T06:00:00Z", requested_at="R1")
    entry = tools.report(tmp_path, "codex", install=True, update="daily", sessions_on_older=2)
    assert entry == {
        "id": "codex",
        "install": True,
        "update": "daily",
        "version": "1.0.0",
        "previous_version": None,
        "latest": "1.0.0",
        "state": "current",
        "reason": None,
        "checked_at": "2026-11-14T06:00:00Z",
        "updated_at": "2026-11-14T06:00:00Z",
        "sessions_on_older": 2,
        "update_requested_at": "R1",
    }
    assert set(entry) == {
        "id", "install", "update", "version", "previous_version", "latest", "state",
        "reason", "checked_at", "updated_at", "sessions_on_older", "update_requested_at",
    }  # fmt: skip


def test_an_installer_that_leaves_its_directory_is_refused(
    tmp_path: Path, fake: FakeInstaller, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "elsewhere"

    def install(version: str, into: Path) -> Path:
        outside.write_text("#!/bin/sh\necho 1.0.0\n", encoding="utf-8")
        return outside

    monkeypatch.setattr(fake, "install", install)
    monkeypatch.setattr(fake, "version_of", lambda binary: "1.0.0")
    state = tools.take(tmp_path, "codex", fake, "t1")
    assert (state.version, state.state, state.reason) == (None, "failed", "installer_failed")


def test_tools_are_managed_on_the_local_single_layout_only(fake: FakeInstaller) -> None:
    """§15.16 "Where": an ssh target is only reported on; the agent_user layout's agents could
    not reach the runner's private state_dir, so it is refused there for now."""
    managed = '\n[harness.codex]\nupdate = "daily"\n'
    shared = '\n[backend]\nkind = "local"\n[backend.local]\nlayout = "agent_user"\n'
    found = problems(BASE + shared + 'agent_user = "maity-agents"\n' + managed)
    assert any("not available in the agent_user layout" in p for p in found), found
    assert parse(BASE + shared + 'agent_user = "maity-agents"\n' + "\n[harness.codex]\n")


def test_an_installer_that_raises_anything_ends_as_failed(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    """A body cut short (IncompleteRead) or any other slip of an installer: the attempt is
    failed, nothing half-installed stays, and the next round does not see `installing`."""
    import http.client

    def cut_short(version: str, into: Path) -> Path:
        (into / "part").write_text("x")
        raise http.client.IncompleteRead(b"x", 10)

    fake.install = cut_short  # type: ignore[method-assign]
    state = tools.take(tmp_path, "codex", fake, "t1")
    assert (state.state, state.reason, state.version) == ("failed", "installer_failed", None)
    assert tools.load(tmp_path, "codex").state == "failed"
    assert list((tmp_path / "codex" / "versions").iterdir()) == []

    def no_answer() -> str:
        raise RuntimeError("the vendor's page changed")

    fake.latest = no_answer  # type: ignore[method-assign]
    assert tools.take(tmp_path, "codex", fake, "t2").reason == "installer_failed"


def test_a_binary_outside_its_directory_is_never_run(tmp_path: Path, fake: FakeInstaller) -> None:
    outside = tmp_path / "elsewhere"
    outside.write_text("#!/bin/sh\necho 1.0.0\n")
    asked: list[Path] = []
    fake.install = lambda version, into: outside  # type: ignore[method-assign]

    def answer(binary: Path) -> str:
        asked.append(binary)
        return "1.0.0"

    fake.version_of = answer  # type: ignore[method-assign]
    state = tools.take(tmp_path, "codex", fake, "t")
    assert (state.state, state.reason) == ("failed", "installer_failed")
    assert asked == []  # refused before its version answer runs it


def test_a_link_out_of_the_directory_is_neither_installed_nor_started(
    tmp_path: Path, fake: FakeInstaller
) -> None:
    outside = tmp_path / "elsewhere"
    outside.write_text("#!/bin/sh\necho 1.0.0\n")

    def linked(version: str, into: Path) -> Path:
        (into / "bin").mkdir()
        (into / "bin" / "tool").symlink_to(outside)  # inside as written, outside followed
        return into / "bin" / "tool"

    fake.install = linked  # type: ignore[method-assign]
    state = tools.take(tmp_path / "t", "codex", fake, "t")
    assert (state.state, state.reason) == ("failed", "installer_failed")
    # and one planted after the install is not started either
    good = FakeInstaller()
    tools.take(tmp_path, "codex", good, "t")
    found = tools.binary(tmp_path, "codex")
    assert found is not None
    found.unlink()
    found.symlink_to(outside)
    assert tools.binary(tmp_path, "codex") is None
