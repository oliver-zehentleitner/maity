"""The runner's watch in the supervisor (docs/api.md §15.14, "The runner's watch"; §15.7, "A
finding"; tsk-bzmd0avm4yhb): the trigger, one reaction per cause, the cap, a person at the
pane, resting agents, and the finding on the report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_supervisor import CONFIG, Clock, FakeTmux, Reports, placement, recorded, settle, states

from maity.runner import capabilities, config, loop, supervisor, tmux, watch

T0 = 1_800_000_000.0  # Clock's start: the runner starts the harness then
NAME = "maity_maity_agent-3"
PID = "plc-0003"
GRACE = 15 * 60.0  # [limits.watch] defaults
JOIN = 10 * 60.0


def make(tmp_path: Path, extra: str = "") -> Any:
    path = tmp_path / "runner.toml"
    path.write_text(CONFIG.format(root=tmp_path, max_agents=2) + extra)
    (tmp_path / "st").mkdir(mode=0o700, exist_ok=True)
    cfg = config.load(path)
    clock, reports, backend = Clock(), Reports(), FakeTmux()
    logs: list[str] = []
    probes = {
        "stub": capabilities.Probe(None, None, None),
        "codex": capabilities.Probe("/usr/bin/codex", "0.40.0", None),
    }
    sup = supervisor.Supervisor(
        cfg, backend, reports, logs.append, probes, now=clock, rand=lambda: 0.5  # type: ignore[arg-type]
    )
    sup.login = lambda harness, binary, as_user: "ok"
    return sup, backend, reports, clock, logs


@pytest.fixture
def world(tmp_path: Path) -> Any:
    return make(tmp_path)


def watched(mode: str = "interactive", **session: Any) -> dict[str, Any]:
    facts = {
        "started_at": None, "not_listening_since": None, "paused": False, "dormant": False,
        **session,
    }  # fmt: skip
    return placement(mode=mode, session=facts)


def joined_then_quiet(**more: Any) -> dict[str, Any]:
    """Joined a minute after the start, not listening since the second minute."""
    return watched(
        started_at=watch.stamp(T0 + 60), not_listening_since=watch.stamp(T0 + 120), **more
    )


def running(sup: supervisor.Supervisor, clock: Clock, p: dict[str, Any]) -> None:
    recorded(sup.cfg)
    sup.update([p])
    settle(sup)
    clock.now += supervisor.RUNNING_AFTER
    sup.tick()
    assert sup.records[PID].state == "running"
    assert sup.records[PID].started_at == T0


def drain(sup: supervisor.Supervisor) -> None:
    """A pass that starts a diagnosis, its worker, and the pass that acts on its verdict."""
    sup.tick()
    for worker in list(sup.watching.values()):
        worker.join(5)
    sup.tick()


def last(reports: Reports) -> dict[str, Any]:
    body: dict[str, Any] = reports.sent[-1][1]
    return body


def with_findings(reports: Reports) -> list[dict[str, Any]]:
    return [body for _, body in reports.sent if "finding" in body]


QUIET_PAST_GRACE = T0 + 120 + GRACE


# --- one reaction per cause ------------------------------------------------------------------


def test_wait_deaf_ends_the_session_and_restarts_it_resuming(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE - 1
    drain(sup)
    assert backend.terminated == [] and sup.watching == {}  # not yet past the grace
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == [NAME]
    assert states(reports)[-1] == ("running", None, None)  # nothing reported until it is gone
    backend.exit(NAME, 143)
    sup.tick()
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("exited", "hung", "not_listening")
    assert body["exit_code"] == 143
    finding = body["finding"]
    assert finding["cause"] == "wait_deaf"
    assert finding["seen_at"] == watch.stamp(QUIET_PAST_GRACE)
    assert finding["signals"] == {
        "process": "alive", "exit_code": None, "below": "waiting", "pane_match": [],
        "login": "ok", "pickup_code": None,
    }  # fmt: skip
    assert any(
        e["line"].startswith(f"{PID}: not listening since ")
        and e["line"].endswith(", a maity wait runs: restart, resuming")
        for e in finding["log"]
    )
    rec = sup.records[PID]
    assert rec.resume and rec.watch_restarts == [QUIET_PAST_GRACE]
    assert rec.hung_exits == []  # not the own check's row
    clock.now += 11  # past the first backoff step
    settle(sup)
    body = last(reports)
    assert (body["state"], body["restarts"]) == ("starting", 1)
    assert len(backend.started) == 2
    assert len(with_findings(reports)) == 1  # the finding went once


def test_never_joined_ends_the_session_and_restarts_it(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, watched(mode="supervised"))
    clock.now = T0 + JOIN - 1
    drain(sup)
    assert backend.terminated == []
    clock.now = T0 + JOIN
    drain(sup)
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("exited", "hung", "never_joined")
    assert body["finding"]["cause"] == "never_joined"


def test_a_session_that_joined_earlier_than_this_run_never_joined(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, watched(mode="supervised", started_at=watch.stamp(T0 - 3600)))
    clock.now = T0 + JOIN
    drain(sup)
    assert backend.terminated == [NAME]


def test_not_waiting_nudges_once_per_quiet_spell_and_restarts_nothing(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.typed == [(NAME, supervisor.NUDGE_LINE)]
    assert backend.terminated == []
    body = last(reports)
    assert (body["state"], body["reason"]) == ("running", None)
    assert body["finding"]["cause"] == "not_waiting"
    assert body["finding"]["signals"]["below"] == "idle"
    sent = len(reports.sent)
    clock.now += supervisor.IDLE_EVERY
    drain(sup)
    assert len(backend.typed) == 1  # the same spell: no second line
    assert len(reports.sent) == sent  # and no second report


def test_not_waiting_types_nothing_with_someone_attached(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.attach = True
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.typed == []
    assert last(reports)["finding"]["cause"] == "not_waiting"


def test_usage_limit_waits_for_the_reset(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, watched(mode="supervised"))
    clock.now = T0 + JOIN
    backend.exit(NAME, loop.EXIT_RATE_LIMITED)
    drain(sup)
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("rate_limited", "quota",
                                                               "reset_unknown")  # fmt: skip
    assert body["retry_at"] is not None
    finding = body["finding"]
    assert finding["cause"] == "usage_limit"
    assert finding["signals"]["process"] == "gone"
    assert finding["signals"]["below"] == "unknown"
    assert sup.records[PID].watch_restarts == []  # not a restart cause


def test_login_invalid_ends_the_session_and_never_restarts(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    sup.login = lambda harness, binary, as_user: "needed"
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    body = last(reports)
    assert (body["state"], body["reason"]) == ("failed", "auth")
    assert body["finding"]["cause"] == "login_invalid"
    assert body["finding"]["signals"]["login"] == "needed"
    clock.now += 3600
    sup.tick()
    assert len(backend.started) == 1


def test_no_login_probe_is_never_a_gone_login(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    sup.login = lambda harness, binary, as_user: "unknown"
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    sup.tick()
    assert last(reports)["finding"]["cause"] == "wait_deaf"


def test_a_harness_that_exited_is_started_again(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    clock.now = QUIET_PAST_GRACE
    backend.exit(NAME, 1)
    drain(sup)
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("exited", "hung", "not_listening")
    assert body["exit_code"] == 1
    signals = body["finding"]["signals"]
    assert body["finding"]["cause"] == "harness_exited"
    assert (signals["process"], signals["exit_code"], signals["below"]) == ("gone", 1, "unknown")
    assert sup.records[PID].resume


def test_an_exit_without_a_trigger_stays_the_restart_policys(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.exit(NAME, 1)
    sup.tick()
    body = last(reports)
    assert (body["state"], body["reason"]) == ("exited", None)
    assert "finding" not in body


def test_a_watch_exit_at_the_crash_cap_is_a_crash_loop(tmp_path: Path) -> None:
    sup, backend, reports, clock, _ = make(
        tmp_path, "\n[limits.restart]\nquick_exit = 7200\ncrash_cap = 1\n"
    )
    running(sup, clock, joined_then_quiet())
    clock.now = QUIET_PAST_GRACE
    backend.exit(NAME, 1)
    drain(sup)
    body = last(reports)
    assert (body["state"], body["reason"]) == ("failed", "crash_loop")
    assert body["finding"]["cause"] == "harness_exited"


def test_work_below_counts_until_tool_call_max(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WORKING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == [] and with_findings(reports) == []
    clock.now = T0 + 120 + supervisor.TOOL_CALL_MAX_MINUTES * 60
    drain(sup)
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    assert last(reports)["finding"]["cause"] == "unknown"


def test_an_unreadable_process_tree_is_unknown(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = None
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    body = last(reports)
    assert body["finding"]["cause"] == "unknown"
    assert body["detail"] == "not_listening"


def test_a_session_that_ignores_term_is_killed(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    assert backend.killed[-1] == NAME
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("exited", "hung", "not_listening")


# --- the cap ---------------------------------------------------------------------------------


def test_the_second_failure_holds_the_placement(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    sup.tick()
    clock.now += 11
    settle(sup)
    clock.now += supervisor.RUNNING_AFTER
    sup.tick()
    started = sup.records[PID].started_at
    assert started is not None and started > T0
    # The new run joined; the hub still reports the earlier session's quiet spell.
    sup.update([
        watched(started_at=watch.stamp(started + 60), not_listening_since=watch.stamp(T0 + 120))
    ])  # fmt: skip
    clock.now = started + GRACE - 1
    drain(sup)
    assert backend.terminated == [NAME]  # only the first end: the grace counts from this run
    clock.now = started + GRACE
    drain(sup)
    assert backend.terminated == [NAME, NAME]
    backend.exit(NAME, 143)
    sup.tick()
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("failed", "hung", "not_listening")
    assert body["finding"]["cause"] == "wait_deaf"
    clock.now += 3600
    sup.tick()
    assert len(backend.started) == 2  # held until its generation moves


def test_auto_restarts_zero_holds_at_the_first_finding(tmp_path: Path) -> None:
    sup, backend, reports, clock, _ = make(tmp_path, "\n[limits.watch]\nauto_restarts = 0\n")
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    sup.tick()
    assert states(reports)[-1] == ("failed", "hung", "not_listening")


# --- a person at the pane --------------------------------------------------------------------


@pytest.mark.parametrize("attach", [True, None])
def test_a_person_at_the_pane_keeps_the_session(world: Any, attach: bool | None) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    backend.attach = attach
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == []
    body = last(reports)
    assert (body["state"], body["finding"]["cause"]) == ("running", "wait_deaf")
    sent = len(reports.sent)
    clock.now += supervisor.IDLE_EVERY
    drain(sup)
    assert len(reports.sent) == sent  # reported once
    backend.attach = False  # the last client left
    clock.now += supervisor.IDLE_EVERY
    drain(sup)
    assert backend.terminated == [NAME]


# --- resting agents --------------------------------------------------------------------------


@pytest.mark.parametrize("rest", [{"paused": True}, {"dormant": True}])
def test_a_resting_agent_is_left_alone(world: Any, rest: dict[str, bool]) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet(**rest))
    for _ in range(60):  # an hour, past the grace and the own check's 30 + 10 minutes
        clock.now += 60
        sup.tick()
    assert backend.typed == [] and backend.terminated == []
    assert sup.watching == {} and with_findings(reports) == []


# --- the finding on the report ---------------------------------------------------------------


def test_a_hub_without_session_gets_no_watch_and_no_finding(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, placement(mode="interactive"))
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert sup.watching == {} and backend.terminated == []
    assert with_findings(reports) == []


def test_the_body_carries_a_finding_only_to_a_hub_that_takes_it(world: Any) -> None:
    sup = world[0]
    rec = supervisor.Record(generation=1, state="running", finding={"cause": "unknown"})
    assert "finding" not in sup._body(rec)
    rec.reports_finding = True
    assert sup._body(rec)["finding"] == {"cause": "unknown"}


def test_a_finding_moves_the_reports_key_only_once_there_is_one() -> None:
    rec = supervisor.Record(generation=1, state="running")
    before = rec.key()
    assert len(before) == 5
    rec.finding_n = 1
    assert rec.key() == [*before, 1]


def test_the_clock_follows_the_hubs_server_time(world: Any) -> None:
    sup, _, _, clock, _ = world
    sup.clock(watch.stamp(clock.now + 3600))
    assert sup.hub_offset == 3600
    sup.clock("not a time")
    assert sup.hub_offset == 3600


def test_the_trigger_is_measured_in_hub_time(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    sup.clock(watch.stamp(clock.now + 3600))  # the hub's clock is an hour ahead
    hub = T0 + 3600
    running(sup, clock, watched(
        started_at=watch.stamp(hub + 60), not_listening_since=watch.stamp(hub + 120)
    ))  # fmt: skip
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE - 1
    drain(sup)
    assert backend.terminated == []
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == [NAME]
