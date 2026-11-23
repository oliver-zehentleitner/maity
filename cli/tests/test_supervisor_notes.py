"""The runner's own lines about each placement (`Supervisor.note`, watch.Notes): what a
finding's `log` may take (docs/api.md §15.7, "The runner's log lines"; tsk-bzmd0avm4yhb)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_supervisor import Clock, FakeTmux, Reports, load, placement, recorded, settle

from maity import hub
from maity.runner import capabilities, supervisor, watch, workspace


@pytest.fixture
def world(tmp_path: Path) -> Any:
    cfg = load(tmp_path)
    clock, reports, backend = Clock(), Reports(), FakeTmux()
    logs: list[str] = []
    probes = {
        "stub": capabilities.Probe(None, None, None),
        "codex": capabilities.Probe("/usr/bin/codex", "0.40.0", None),
    }
    sup = supervisor.Supervisor(
        cfg, backend, reports, logs.append, probes, now=clock, rand=lambda: 0.5  # type: ignore[arg-type]
    )
    # No daemon stop: the probe names `/usr/bin/codex`, which no test may start (conftest's
    # `codex_guard`); the stop is tested with a fake codex in test_codex_daemon.py.
    sup._stop_codex_daemon = lambda *args: None  # type: ignore[method-assign]
    return sup, backend, reports, clock, logs


def lines(sup: supervisor.Supervisor, pid: str = "plc-0003") -> list[str]:
    return [line for _, line in sup.notes.entries(pid)]


def test_a_start_and_an_exit_are_noted_for_their_placement_only(world: Any) -> None:
    sup, backend, _, clock, logs = world
    recorded(sup.cfg)
    recorded(sup.cfg, 4)
    sup.update([placement(), placement(4)])
    settle(sup)
    clock.now += supervisor.RUNNING_AFTER
    sup.tick()
    backend.exit("maity_maity_agent-3", 1)
    sup.tick()
    mine = lines(sup)
    assert mine and all(line.startswith("plc-0003: ") for line in mine)
    started = "plc-0003: started stub (supervised) on local, generation 1, "
    assert any(line.startswith(started) for line in mine)
    assert "plc-0003: starting (generation 1)" in mine
    assert "plc-0003: running (generation 1)" in mine
    assert "plc-0003: the harness exited with code 1" in mine
    assert "plc-0003: exited (generation 1)" in mine
    theirs = lines(sup, "plc-0004")
    assert theirs and all(line.startswith("plc-0004: ") for line in theirs)
    assert not any("exited" in line for line in theirs)
    # A state change is the same line in the service log as before.
    assert "plc-0003: starting (generation 1)" in logs


def test_notes_carry_no_agent_side_values(
    world: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sup, backend, _, _, logs = world
    recorded(sup.cfg)

    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError(f"cannot start in {tmp_path}/ws on branch feature/secret-x")

    monkeypatch.setattr(backend, "start", boom)
    sup.update([placement()])
    settle(sup)
    mine = lines(sup)
    assert "plc-0003: start failed: <error>" in mine
    text = "\n".join(mine)
    assert str(tmp_path) not in text
    assert "feature/secret-x" not in text
    assert "maity_maity_agent-3" not in text  # the session's name is not the placement's id
    # The service log keeps its own line, with the exception's text, as before.
    assert any("feature/secret-x" in line for line in logs)


def test_a_refused_pickup_is_noted_with_its_code_only(world: Any) -> None:
    sup, _, _, _, logs = world

    class Refusing:
        def call(self, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
            raise hub.HubError(
                "refused: https://hub.example/j/tok-secret", code="pickup_used", status=409
            )

    sup.client = Refusing()
    assert sup.cfg.local is not None
    place = workspace.locate(sup.cfg.local.workspaces, "maity", "agent-3")
    with pytest.raises(workspace.Refused):
        sup._join(placement(), place, "agt-3", False)
    line = "plc-0003: warning: join pickup refused: pickup_used (reason -, why -)"
    assert lines(sup) == [line]
    assert logs[-1] == line  # the same line as the service log has always written


def test_note_writes_the_service_log_unless_told_not_to(world: Any) -> None:
    sup, _, _, _, logs = world
    sup.note("plc-0003", "one")
    sup.note("plc-0003", "two", log=False)
    assert logs == ["plc-0003: one"]
    assert lines(sup) == ["plc-0003: one", "plc-0003: two"]


def test_notes_stay_bounded(world: Any) -> None:
    sup = world[0]
    for n in range(watch.LOG_LINES_MAX + 50):
        sup.note("plc-0003", f"line {n}", log=False)
    kept = lines(sup)
    assert len(kept) == watch.LOG_LINES_MAX
    assert kept[0] == "plc-0003: line 50"


def test_notes_are_dropped_when_the_placement_is_closed(world: Any) -> None:
    sup, _, _, _, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    assert lines(sup)
    sup.update([])
    sup.tick()
    assert lines(sup) == []
