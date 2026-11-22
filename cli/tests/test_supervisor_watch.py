"""The runner's watch in the supervisor (docs/api.md §15.14, "The runner's watch"; §15.7, "A
finding"; tsk-bzmd0avm4yhb): the trigger, one reaction per cause, the cap, a person at the
pane, resting agents, and the finding on the report."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from test_supervisor import CONFIG, Clock, FakeTmux, Reports, placement, recorded, settle, states

from maity import hub
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
    sup.login = lambda harness, binary, as_user, agent_path: "ok"
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


def reread(sup: supervisor.Supervisor) -> None:
    """The placements read anew from the hub, as serve does after the poll that follows the
    watch's request: the read starts `FRESH_MARGIN` after the tick's moment, so a trigger
    that began at this tick's time already counts it as fresh."""
    sup.update(list(sup.desired), read_at=sup.now() + supervisor.FRESH_MARGIN)


def drain(sup: supervisor.Supervisor) -> None:
    """A fresh read, a pass that starts a diagnosis, its worker, and the pass that acts on its
    verdict; when that decided an end, the read it asks for and the pass that sends the TERM."""
    reread(sup)
    sup.tick()
    for worker in list(sup.watching.values()):
        worker.join(5)
    sup.tick()
    if any(r.watch_end and not r.watch_end.get("termed", True) for r in sup.records.values()):
        reread(sup)
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
    sup.login = lambda harness, binary, as_user, agent_path: "needed"
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
    sup.login = lambda harness, binary, as_user, agent_path: "unknown"
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


# --- a session adopted after the runner's own restart (the lead, seq 189230) ------------------


def adopt(sup: supervisor.Supervisor, backend: FakeTmux, p: dict[str, Any]) -> supervisor.Record:
    """The runner restarted (an upgrade) and finds the placement's session still running."""
    backend.live[NAME] = tmux.Session(NAME, False, None, 4242, PID, 1)
    sup.update([p])
    sup.tick()
    rec = sup.records[PID]
    assert (rec.state, rec.reason, rec.started_at) == ("running", "adopted", None)
    return rec


def test_an_adopted_session_counts_the_grace_from_the_adoption(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    backend.below = tmux.WAITING
    # Quiet for an hour already when the runner comes back: no restart wave at once.
    rec = adopt(sup, backend, watched(
        started_at=watch.stamp(T0 - 7200), not_listening_since=watch.stamp(T0 - 3600)
    ))  # fmt: skip
    assert rec.watch_since == T0
    drain(sup)
    assert backend.terminated == [] and sup.watching == {}
    clock.now = T0 + GRACE - 1
    drain(sup)
    assert backend.terminated == [] and with_findings(reports) == []
    clock.now = T0 + GRACE  # one grace after the adoption
    drain(sup)
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    assert states(reports)[-1] == ("exited", "hung", "not_listening")


def test_an_adopted_session_never_gets_never_joined(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    adopt(sup, backend, watched(mode="supervised"))  # the hub knows no session of it
    for hours in (1, 24):
        clock.now = T0 + hours * 3600
        drain(sup)
    assert backend.terminated == [] and sup.watching == {}
    assert with_findings(reports) == []


def test_watch_since_is_kept_in_actual_json(world: Any) -> None:
    sup = world[0]
    sup.records[PID] = supervisor.Record(generation=1, state="running", watch_since=T0)
    sup.save()
    again = supervisor.Supervisor(
        sup.cfg, FakeTmux(), Reports(), lambda line: None, {}  # type: ignore[arg-type]
    )
    again.load()
    assert again.records[PID].watch_since == T0
    assert supervisor.Record().watch_since is None  # a record from before reads as unknown


def test_a_run_the_runner_started_is_watched_from_its_start(world: Any) -> None:
    sup, _, _, clock, _ = world
    running(sup, clock, joined_then_quiet())
    rec = sup.records[PID]
    assert rec.watch_since == rec.started_at == T0


# --- Codex review A1940 ----------------------------------------------------------------------


@pytest.mark.parametrize("change", ["paused", "dormant", "cleared", "attached"])
def test_a_verdict_whose_facts_changed_is_dropped(world: Any, change: str) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    reread(sup)
    sup.tick()  # the diagnosis starts
    for worker in list(sup.watching.values()):
        worker.join(5)
    assert sup.records[PID].watch_verdict is not None
    if change == "attached":
        backend.attach = True
    elif change == "cleared":  # it listens again
        sup.update([watched(started_at=watch.stamp(T0 + 60))])
    else:
        sup.update([joined_then_quiet(**{change: True})])
    sup.tick()  # acting time
    assert backend.terminated == []
    assert with_findings(reports) == []
    assert sup.records[PID].watch_verdict is None


def test_someone_attaching_during_the_end_keeps_the_session(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == [NAME]  # TERM sent; the harness ignores it
    backend.attach = True  # someone attaches before the kill
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    assert NAME not in backend.killed
    body = last(reports)
    assert (body["state"], body["finding"]["cause"]) == ("running", "wait_deaf")
    assert sup.records[PID].watch_end is None
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    assert NAME not in backend.killed  # and nothing is ended while they stay


def test_a_dead_harness_at_both_caps_is_a_crash_loop(tmp_path: Path) -> None:
    sup, backend, reports, clock, _ = make(
        tmp_path,
        "\n[limits.restart]\nquick_exit = 7200\ncrash_cap = 1\n"
        "\n[limits.watch]\nauto_restarts = 0\n",
    )
    running(sup, clock, joined_then_quiet())
    clock.now = QUIET_PAST_GRACE
    backend.exit(NAME, 1)
    drain(sup)
    body = last(reports)
    assert (body["state"], body["reason"]) == ("failed", "crash_loop")
    assert body["finding"]["cause"] == "harness_exited"


def test_a_session_started_in_the_runs_second_counts_as_joined(tmp_path: Path) -> None:
    sup, backend, _, clock, _ = make(tmp_path)
    clock.now = T0 + 0.6
    recorded(sup.cfg)
    # The hub's wire form has whole seconds: the session started in the run's own second.
    sup.update([watched(mode="supervised", started_at=watch.stamp(T0 + 0.6))])
    settle(sup)
    clock.now += supervisor.RUNNING_AFTER
    sup.tick()
    assert sup.records[PID].started_at == T0 + 0.6
    clock.now = T0 + 0.6 + JOIN
    drain(sup)
    assert backend.terminated == [] and sup.watching == {}


def test_a_join_seen_once_keeps_never_joined_off_for_the_run(world: Any) -> None:
    sup, backend, _, clock, _ = world
    running(sup, clock, watched(mode="supervised", started_at=watch.stamp(T0 + 30)))
    sup.tick()  # the watch sees this run's session
    assert sup.records[PID].watch_joined
    # A later read names an earlier session (an edge of a second, a lagging read): still joined.
    sup.update([watched(mode="supervised", started_at=watch.stamp(T0 - 1))])
    clock.now = T0 + JOIN
    drain(sup)
    assert backend.terminated == [] and sup.watching == {}


@pytest.mark.parametrize(
    ("code", "outcome"),
    [
        (loop.EXIT_REVOKED, ("failed", "agent_credential_revoked", None)),
        (loop.EXIT_HOT_LOOP, ("failed", "crash_loop", "hot_loop")),
    ],
)
def test_a_terminal_exit_stays_with_the_exit_handling(
    world: Any, code: int, outcome: tuple[str, str, str | None]
) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, watched(mode="supervised"))
    clock.now = T0 + JOIN  # never_joined holds
    backend.exit(NAME, code)
    drain(sup)
    assert states(reports)[-1] == outcome
    assert last(reports)["finding"]["cause"] == "harness_exited"  # the finding goes with it
    assert sup.records[PID].watch_restarts == []
    clock.now += 3600
    sup.tick()
    assert len(backend.started) == 1  # no watch restart


def test_a_finding_whose_report_got_no_answer_goes_again_before_the_next_state(
    world: Any,
) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    reports.fail.append(hub.HubError("no answer"))
    sup.tick()  # exited/hung with the finding: no answer
    assert with_findings(reports) == []
    clock.now += 11
    settle(sup)  # the same report goes again first; `starting` follows it
    carried = with_findings(reports)
    assert len(carried) == 1
    assert (carried[0]["state"], carried[0]["finding"]["cause"]) == ("exited", "wait_deaf")
    assert states(reports)[-1] == ("starting", None, None)
    clock.now += supervisor.RUNNING_AFTER
    sup.tick()
    assert len(with_findings(reports)) == 1  # and once only


def test_a_finding_the_hub_refused_is_carried_on_once(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    reports.fail.append(hub.HubError("refused", code="invalid", status=400))
    sup.tick()  # the hub answered and did not take it
    assert with_findings(reports) == []
    clock.now += 11
    settle(sup)  # the restart's `starting` carries the finding on
    carried = with_findings(reports)
    assert len(carried) == 1
    assert (carried[0]["state"], carried[0]["finding"]["cause"]) == ("starting", "wait_deaf")


def test_an_authentication_refusal_keeps_the_findings_own_seq(world: Any) -> None:
    """Only a validated `invalid` says the body was refused; a refusal such as a clock skew
    says nothing about it, so the same body goes again with its seq (Codex A1965)."""
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    for _ in range(2):
        reports.fail.append(hub.HubError("skew", code="timestamp_skew", status=401))
    sup.tick()
    clock.now += 11
    sup.tick()  # refused twice: neither drops the finding nor moves it to a new seq
    clock.now += 11
    settle(sup)
    carried = with_findings(reports)
    assert len(carried) == 1
    assert (carried[0]["state"], carried[0]["finding"]["cause"]) == ("exited", "wait_deaf")


# --- Gemini review A1941 ---------------------------------------------------------------------


def test_a_pane_that_died_before_the_nudge_goes_to_the_exit(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())  # nothing below: not_waiting
    clock.now = QUIET_PAST_GRACE
    reread(sup)
    sup.tick()  # the diagnosis starts while the harness is alive
    for worker in list(sup.watching.values()):
        worker.join(5)
    backend.exit(NAME, 1)  # and dies before the verdict is acted on
    sup.tick()
    assert backend.typed == []  # no line into a dead pane
    for worker in list(sup.watching.values()):
        worker.join(5)
    sup.tick()
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("exited", "hung", "not_listening")
    assert body["finding"]["cause"] == "harness_exited"


def test_an_exit_soon_after_a_look_is_still_the_watchs(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WORKING
    clock.now = QUIET_PAST_GRACE
    drain(sup)  # work below: looked at, nothing done
    assert backend.terminated == [] and with_findings(reports) == []
    clock.now += 10  # well within a minute of that look
    backend.exit(NAME, 1)
    drain(sup)
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("exited", "hung", "not_listening")
    assert body["finding"]["cause"] == "harness_exited"
    rec = sup.records[PID]
    assert rec.resume and rec.watch_restarts == [clock.now]


def test_a_session_gone_during_the_end_enters_the_end_and_starts_nothing(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    sup.login = lambda harness, binary, as_user, agent_path: "needed"
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == [NAME]
    backend.live.pop(NAME)  # gone, without a dead pane to read
    sup.tick()
    body = last(reports)
    assert (body["state"], body["reason"]) == ("failed", "auth")
    assert body["finding"]["cause"] == "login_invalid"
    clock.now += 3600
    sup.tick()
    assert len(backend.started) == 1


def test_the_quiet_span_counts_from_the_adoption_too(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    backend.below = tmux.WORKING  # a long build
    # Quiet for three hours by the hub's count, from before the runner's restart.
    adopt(sup, backend, watched(
        started_at=watch.stamp(T0 - 4 * 3600), not_listening_since=watch.stamp(T0 - 3 * 3600)
    ))  # fmt: skip
    clock.now = T0 + GRACE
    drain(sup)
    assert backend.terminated == []  # 15 min of quiet in this watch, not 3 h 15
    clock.now = T0 + supervisor.TOOL_CALL_MAX_MINUTES * 60
    drain(sup)
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    assert last(reports)["finding"]["cause"] == "unknown"


# --- Codex delta review A1957 ----------------------------------------------------------------


def ended_by_term(sup: supervisor.Supervisor, backend: FakeTmux, clock: Clock) -> None:
    """A deaf `maity wait`, ended with TERM, which the harness survives."""
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    assert backend.terminated == [NAME] and sup.records[PID].watch_end is not None


@pytest.mark.parametrize("change", ["paused", "dormant", "cleared"])
def test_the_kill_is_called_off_when_the_facts_changed(world: Any, change: str) -> None:
    sup, backend, reports, clock, _ = world
    ended_by_term(sup, backend, clock)
    if change == "cleared":  # it listens again
        sup.update([watched(started_at=watch.stamp(T0 + 60))])
    else:
        sup.update([joined_then_quiet(**{change: True})])
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    assert NAME not in backend.killed
    rec = sup.records[PID]
    assert rec.watch_end is None and rec.watch_restarts == []
    body = last(reports)
    assert (body["state"], body["finding"]["cause"]) == ("running", "wait_deaf")


@pytest.mark.parametrize("rest", ["paused", "dormant"])
def test_a_session_the_term_ends_after_a_pause_is_no_watch_restart(world: Any, rest: str) -> None:
    sup, backend, reports, clock, _ = world
    ended_by_term(sup, backend, clock)
    sup.update([joined_then_quiet(**{rest: True})])
    backend.exit(NAME, 143)  # the TERM ended it after all
    sup.tick()
    rec = sup.records[PID]
    assert rec.watch_end is None and rec.watch_restarts == []  # nothing counted
    body = last(reports)
    # Not the watch's `exited`/`hung` relaunch: the exit is handled as any other exit.
    assert (body["state"], body["reason"]) == ("exited", None)
    assert body["finding"]["cause"] == "wait_deaf"  # reported once
    assert rec.resume  # whatever starts it next resumes the session the runner ended


def test_a_decided_end_goes_on_when_the_trigger_cleared(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    sup.login = lambda harness, binary, as_user, agent_path: "needed"
    ended_by_term(sup, backend, clock)
    assert sup.records[PID].watch_end["then"] == "auth"
    sup.update([watched(started_at=watch.stamp(T0 + 60))])  # listening again
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    assert backend.killed[-1] == NAME
    assert states(reports)[-1] == ("failed", "auth", None)


def test_a_restart_counts_only_once_the_session_is_gone(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    ended_by_term(sup, backend, clock)
    assert sup.records[PID].watch_restarts == []  # TERM sent: not counted yet
    backend.attach = True  # someone attaches before the kill: the end is called off
    clock.now += supervisor.KILL_AFTER
    sup.tick()
    assert NAME not in backend.killed
    assert sup.records[PID].watch_restarts == []  # the one allowed restart is still there
    backend.attach = False  # they leave; the quiet spell goes on
    clock.now += supervisor.IDLE_EVERY
    drain(sup)
    assert backend.terminated == [NAME, NAME]  # a restart again, not the cap's hold
    backend.exit(NAME, 143)
    sup.tick()
    assert states(reports)[-1] == ("exited", "hung", "not_listening")
    assert sup.records[PID].watch_restarts == [clock.now]


# --- Gemini delta review A1958 ---------------------------------------------------------------


def test_a_limit_exit_while_logged_out_is_a_needed_login(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    sup.login = lambda harness, binary, as_user, agent_path: "needed"
    running(sup, clock, watched(mode="supervised"))
    clock.now = T0 + JOIN
    backend.exit(NAME, loop.EXIT_RATE_LIMITED)
    drain(sup)
    assert states(reports)[-1] == ("failed", "auth", None)  # not a retry at every reset
    assert last(reports)["finding"]["cause"] == "login_invalid"


@pytest.mark.parametrize(
    ("code", "before", "after"),
    [(loop.EXIT_RATE_LIMITED, 2, 3), (loop.EXIT_RATE_LIMITED_AFTER_CLEAN, 2, 1)],
)
def test_a_limit_exit_is_reported_as_without_the_watch(
    world: Any, code: int, before: int, after: int
) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, watched(mode="supervised"))
    sup.records[PID].limits_unknown = before
    clock.now = T0 + JOIN
    backend.exit(NAME, code)
    drain(sup)
    body = last(reports)
    assert (body["state"], body["reason"], body["detail"]) == ("rate_limited", "quota",
                                                               "reset_unknown")  # fmt: skip
    assert sup.records[PID].limits_unknown == after  # 23 starts the row over first
    backoff = min(supervisor.LIMIT_BACKOFF * 2 ** (after - 1), supervisor.LIMIT_BACKOFF_MAX)
    assert body["retry_at"] == supervisor.stamp(clock.now + backoff)
    assert body["finding"]["cause"] == "usage_limit"


def test_an_interactive_exit_22_is_a_plain_exit(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    clock.now = QUIET_PAST_GRACE
    backend.exit(NAME, loop.EXIT_RATE_LIMITED)  # no loop runs here: just an exit code
    drain(sup)
    assert states(reports)[-1] == ("exited", "hung", "not_listening")
    assert last(reports)["finding"]["cause"] == "harness_exited"


def test_a_completed_watch_restart_ends_a_row_of_limits(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    ended_by_term(sup, backend, clock)
    sup.records[PID].limits_unknown = 3
    backend.exit(NAME, 143)
    sup.tick()
    assert states(reports)[-1] == ("exited", "hung", "not_listening")
    assert sup.records[PID].limits_unknown == 0


class LostReplies(Reports):
    """The hub takes a status report, but its reply is lost `lose` times."""

    def __init__(self) -> None:
        super().__init__()
        self.lose = 0

    def call(self, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
        if self.lose and path.endswith("/status"):
            self.lose -= 1
            self.sent.append((path.split("/")[3], body))  # the hub stored it
            raise hub.HubError("no answer")
        return super().call(method, path, body, **kwargs)


def test_a_finding_whose_reply_was_lost_stays_in_one_seq(world: Any) -> None:
    sup, backend, _, clock, _ = world
    hub_ = LostReplies()
    sup.client = hub_
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    hub_.lose = 1
    sup.tick()  # exited/hung with the finding: stored, the reply lost
    clock.now += 11
    settle(sup)  # the restart: the same report first, then `starting`
    carried = with_findings(hub_)
    assert len(carried) == 2  # sent twice ...
    assert len({body["seq"] for body in carried}) == 1  # ... with one seq: one report
    after = hub_.sent[-1][1]
    assert after["state"] == "starting" and "finding" not in after
    assert after["seq"] == carried[0]["seq"] + 1


# --- Gemini review A2033: a refused report that carries a finding ----------------------------


class Answers(Reports):
    """Every status report tried, in `tried`; the next ones answered with `answers` in turn
    (an exception each), the rest taken. `during` runs while a report is in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.tried: list[dict[str, Any]] = []
        self.answers: list[hub.HubError] = []
        self.during: Any = None

    def call(self, method: str, path: str, body: Any = None, **kwargs: Any) -> Any:
        if path.endswith("/status"):
            self.tried.append(body)
            if self.during is not None:
                self.during()
                self.during = None
            if self.answers:
                raise self.answers.pop(0)
        return super().call(method, path, body, **kwargs)


def invalid(*fields: str) -> hub.HubError:
    exc = hub.HubError("invalid", code="invalid", status=400)
    exc.details = {"fields": {name: "invalid" for name in fields}}
    return exc


def exited_with_finding(
    sup: supervisor.Supervisor, backend: FakeTmux, clock: Clock, *answers: hub.HubError
) -> Answers:
    """A deaf `maity wait` ended and gone: its `exited`/`hung` report carries the finding and
    meets `answers`."""
    hub_ = Answers()
    sup.client = hub_  # type: ignore[assignment]  # a fake that answers only the report call
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    hub_.answers.extend(answers)
    sup.tick()
    assert hub_.tried[-1]["state"] == "exited"
    return hub_


def test_a_finding_report_refused_on_another_field_is_not_resent_in_the_backoff(
    world: Any,
) -> None:
    sup, backend, _, clock, _ = world
    hub_ = exited_with_finding(sup, backend, clock, invalid("restarts"))
    tried = len(hub_.tried)
    clock.now += supervisor.TICK  # still within the restart's first backoff step
    sup.tick()
    assert len(hub_.tried) == tried  # the refused body is never sent again
    clock.now += supervisor.TICK + 1  # past it: the restart
    settle(sup)
    carried = with_findings(hub_)
    assert len(carried) == 1
    assert (carried[0]["state"], carried[0]["finding"]["cause"]) == ("starting", "wait_deaf")


def test_a_terminal_finding_report_refused_on_another_field_is_never_resent(
    world: Any,
) -> None:
    sup, backend, _, clock, _ = world
    sup.login = lambda harness, binary, as_user, agent_path: "needed"
    hub_ = Answers()
    sup.client = hub_
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    hub_.answers.append(invalid("exit_code"))
    sup.tick()
    assert hub_.tried[-1]["state"] == "failed" and "finding" in hub_.tried[-1]
    tried = len(hub_.tried)
    for _ in range(5):
        clock.now += supervisor.TICK
        sup.tick()
    assert len(hub_.tried) == tried


def test_a_finding_refused_alone_is_dropped_and_its_state_still_goes(world: Any) -> None:
    sup, backend, _, clock, _ = world
    hub_ = exited_with_finding(sup, backend, clock, invalid("finding.signals.below"))
    refused, again = hub_.tried[-2], hub_.tried[-1]
    assert "finding" in refused and "finding" not in again
    assert again["seq"] == refused["seq"] and again["state"] == "exited"
    assert hub_.sent[-1][1] is again  # taken at once
    rec = sup.records[PID]
    assert rec.finding is None and rec.pending is None
    clock.now += 11
    settle(sup)
    assert with_findings(hub_) == [] and hub_.sent[-1][1]["state"] == "starting"


def test_a_detail_refused_on_a_finding_report_keeps_the_finding_and_seq(world: Any) -> None:
    sup, backend, _, clock, _ = world
    hub_ = exited_with_finding(sup, backend, clock, invalid("detail"))
    refused, again = hub_.tried[-2], hub_.tried[-1]
    assert refused["detail"] == "not_listening" and again["detail"] is None
    assert again["seq"] == refused["seq"] and again["finding"] == refused["finding"]
    assert len(with_findings(hub_)) == 1  # delivered once
    assert sup.records[PID].finding is None


def test_a_detail_strip_then_another_refusal_is_not_resent(world: Any) -> None:
    sup, backend, _, clock, _ = world
    hub_ = exited_with_finding(sup, backend, clock, invalid("detail"), invalid("restarts"))
    tried = len(hub_.tried)
    for _ in range(3):
        clock.now += supervisor.TICK / 2  # within the backoff: no state change
        sup.tick()
    assert len(hub_.tried) == tried
    assert sum(1 for body in hub_.tried if body.get("detail") == "not_listening") == 1


def test_a_finding_refused_twice_is_dropped(world: Any) -> None:
    sup, backend, _, clock, logs = world
    hub_ = exited_with_finding(sup, backend, clock, invalid("restarts"))
    assert sup.records[PID].finding is not None  # kept for the next state change
    clock.now += 11
    hub_.answers.append(invalid("restarts"))
    settle(sup)  # `starting` carries it and is refused too
    assert hub_.tried[-1]["state"] == "starting" and "finding" in hub_.tried[-1]
    assert sup.records[PID].finding is None  # refused twice: dropped
    clock.now += supervisor.RUNNING_AFTER
    sup.tick()
    third = hub_.tried[-1]
    assert third["state"] == "running" and "finding" not in third  # the rule itself
    assert hub_.sent[-1][1] is third and with_findings(hub_) == []
    # And the log says what happened at each refusal.
    assert any("the next change carries its finding" in line for line in logs)
    assert any("its finding dropped" in line for line in logs)


@pytest.mark.parametrize(("code", "status"), [("stale_generation", 409), ("not_found", 404)])
def test_a_finding_report_the_hub_moved_past_is_settled(world: Any, code: str, status: int) -> None:
    sup, backend, _, clock, _ = world
    exited_with_finding(sup, backend, clock, hub.HubError(code, code=code, status=status))
    rec = sup.records[PID]
    assert rec.pending is None and rec.finding is None


@pytest.mark.parametrize("answer", [None, "invalid"])
def test_a_newer_finding_is_kept_whatever_the_older_reports_answer(
    world: Any, answer: str | None
) -> None:
    sup, backend, _, clock, _ = world
    hub_ = Answers()
    sup.client = hub_
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    newer = {"cause": "unknown"}
    rec = sup.records[PID]
    hub_.during = lambda: sup._found(rec, newer)  # filed while the older one is in flight
    if answer == "invalid":
        hub_.answers.append(invalid("restarts"))
    sup.tick()
    assert "finding" in hub_.tried[-1] and hub_.tried[-1]["finding"] is not newer
    assert rec.finding is newer


@pytest.mark.parametrize(
    ("answer", "status"), [(None, None), ("stale_generation", 409), ("not_found", 404)]
)
def test_a_report_replaced_while_in_flight_is_left_alone(
    world: Any, answer: str | None, status: int | None
) -> None:
    sup, backend, _, clock, _ = world
    hub_ = Answers()
    sup.client = hub_
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    drain(sup)
    backend.exit(NAME, 143)
    rec = sup.records[PID]
    acked = list(rec.acked or [])
    newer_pending: dict[str, Any] = {"key": ["newer"], "body": {"state": "running"}}
    newer_finding = {"cause": "unknown"}

    def swap() -> None:  # a newer report and a newer finding while the POST is in flight
        rec.pending = newer_pending
        sup._found(rec, newer_finding)

    hub_.during = swap
    if answer is not None:
        hub_.answers.append(hub.HubError(answer, code=answer, status=status))
    sup.tick()  # `exited`/`hung` with the older finding: taken, or the hub moved past it
    assert hub_.tried[-1]["state"] == "exited"
    assert rec.pending is newer_pending and list(rec.acked or []) == acked
    assert rec.finding is newer_finding


def test_a_restart_after_a_detail_strip_sends_the_stripped_report(world: Any) -> None:
    sup, backend, _, clock, _ = world
    exited_with_finding(sup, backend, clock, invalid("detail"), hub.HubError("no answer"))
    sup.save()  # the runner stops here
    hub_ = Answers()
    again = supervisor.Supervisor(
        sup.cfg, FakeTmux(), hub_, lambda line: None, {}, now=clock  # type: ignore[arg-type]
    )
    again.load()
    pending = again.records[PID].pending
    assert pending is not None and pending["body"]["detail"] is None
    assert "finding" in pending["body"]
    again.update(sup.desired)
    again._report(again.desired)
    assert hub_.tried == [pending["body"]]  # the stripped one, never the refused one


# --- ops' live check, point 1: facts older than the trigger ---------------------------------


def two_passes(sup: supervisor.Supervisor) -> None:
    """Two ticks with whatever the runner read last: no fresh read in between."""
    sup.tick()
    for worker in list(sup.watching.values()):
        worker.join(5)
    sup.tick()


def test_an_agent_that_joins_after_the_last_read_is_not_restarted(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, watched())  # read at the start: no session yet
    # The agent joins three seconds after the start; nothing wakes the runner.
    clock.now = T0 + JOIN
    two_passes(sup)
    assert backend.terminated == [] and sup.watching == {}
    assert sup.wants_placements()  # it asks for the placements anew instead
    sup.update([watched(started_at=watch.stamp(T0 + 3))])  # serve's read after its poll
    assert not sup.wants_placements()
    clock.now += 30
    drain(sup)
    assert backend.terminated == [] and with_findings(reports) == []
    assert sup.records[PID].watch_joined


def test_a_listen_again_after_the_last_read_is_not_restarted(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    two_passes(sup)  # the last read still says not listening
    assert backend.terminated == [] and sup.wants_placements()
    sup.update([watched(started_at=watch.stamp(T0 + 60))])  # listening again
    clock.now += 30
    drain(sup)
    assert backend.terminated == [] and with_findings(reports) == []


def test_a_trigger_that_holds_after_the_reread_is_acted_on(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    running(sup, clock, watched(mode="supervised"))
    clock.now = T0 + JOIN
    two_passes(sup)
    assert backend.terminated == [] and sup.wants_placements()
    clock.now += 30
    drain(sup)  # the read shows no session still
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    assert states(reports)[-1] == ("exited", "hung", "never_joined")


# --- ops' live check on 067c7e0e: facts older than the watch's own action -------------------


def nudged(sup: supervisor.Supervisor, backend: FakeTmux, clock: Clock) -> None:
    """Not listening with nothing below: a fresh read, then the watch's nudge two seconds after
    that read started."""
    running(sup, clock, joined_then_quiet())
    clock.now = QUIET_PAST_GRACE
    reread(sup)  # started at QUIET_PAST_GRACE + the margin
    clock.now += 2
    two_passes(sup)
    assert backend.typed == [(NAME, supervisor.NUDGE_LINE)]  # the nudge, and nothing ended
    assert backend.terminated == []


def test_a_nudge_answered_by_a_new_wait_is_not_restarted(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    nudged(sup, backend, clock)
    backend.below = tmux.WAITING  # the agent runs `maity wait` again
    clock.now += supervisor.IDLE_EVERY  # the minute-later look of the not_waiting spell
    two_passes(sup)  # no read since the nudge
    assert backend.terminated == [] and sup.watching == {}
    assert sup.wants_placements()  # no decision: it asks for a read
    # The read after the nudge shows the episode over.
    sup.update([watched(started_at=watch.stamp(T0 + 60))], read_at=clock.now)
    clock.now += supervisor.IDLE_EVERY
    drain(sup)
    assert backend.terminated == []
    assert [b["finding"]["cause"] for b in with_findings(reports)] == ["not_waiting"]


def test_a_read_older_than_the_nudge_decides_nothing(world: Any) -> None:
    sup, backend, _, clock, _ = world
    nudged(sup, backend, clock)
    backend.below = tmux.WAITING
    clock.now += supervisor.IDLE_EVERY
    # A read that started before the nudge, though after the trigger's moment.
    sup.update(list(sup.desired), read_at=QUIET_PAST_GRACE + supervisor.FRESH_MARGIN)
    two_passes(sup)
    assert backend.terminated == [] and sup.watching == {} and sup.wants_placements()


def test_after_a_nudge_a_fresh_read_that_still_says_deaf_restarts(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    nudged(sup, backend, clock)
    backend.below = tmux.WAITING
    clock.now += supervisor.IDLE_EVERY
    two_passes(sup)
    assert backend.terminated == []  # it waits for a read first ...
    drain(sup)  # ... which still says not listening, with a `maity wait` below: deaf
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    assert states(reports)[-1] == ("exited", "hung", "not_listening")
    assert last(reports)["finding"]["cause"] == "wait_deaf"


def test_the_watchs_last_action_is_kept_and_forgotten_on_a_new_run(world: Any) -> None:
    sup, backend, _, clock, _ = world
    nudged(sup, backend, clock)
    assert sup.records[PID].watch_acted_at == clock.now  # set by the nudge
    backend.exit(NAME, 1)  # the harness ends; no read since the nudge: a plain exit
    sup.tick()
    clock.now += 11
    settle(sup)  # its restart under the policy
    assert sup.records[PID].state == "starting"
    assert sup.records[PID].watch_acted_at is None


# --- bcr2: the TERM waits for a read after the decision -------------------------------------


def decided(sup: supervisor.Supervisor, backend: FakeTmux, clock: Clock) -> None:
    """A deaf `maity wait`: a fresh read, then a restart decided two seconds after that read
    started; its TERM waits for a read after the decision."""
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    reread(sup)
    clock.now += 2
    two_passes(sup)
    assert sup.records[PID].watch_end is not None  # decided ...
    assert backend.terminated == [] and sup.wants_placements()  # ... no TERM, a read asked


def test_no_term_goes_out_without_a_read_after_the_decision(world: Any) -> None:
    sup, backend, _, clock, _ = world
    decided(sup, backend, clock)
    for _ in range(3):
        clock.now += supervisor.TICK
        sup.tick()
    assert backend.terminated == [] and sup.wants_placements()


def test_a_pause_in_the_read_after_the_decision_calls_the_end_off(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    decided(sup, backend, clock)
    paused = joined_then_quiet(paused=True)
    sup.update([paused], read_at=clock.now + supervisor.FRESH_MARGIN)
    sup.tick()
    assert backend.terminated == [] and backend.killed == []
    rec = sup.records[PID]
    assert rec.watch_end is None and rec.watch_restarts == []
    body = last(reports)
    assert (body["state"], body["finding"]["cause"]) == ("running", "wait_deaf")


def test_a_fresh_read_that_still_shows_the_trigger_sends_the_term(world: Any) -> None:
    sup, backend, reports, clock, _ = world
    decided(sup, backend, clock)
    sup.update(list(sup.desired), read_at=clock.now + supervisor.FRESH_MARGIN)
    sup.tick()
    assert backend.terminated == [NAME]
    backend.exit(NAME, 143)
    sup.tick()
    assert states(reports)[-1] == ("exited", "hung", "not_listening")


def test_a_read_that_started_before_the_trigger_is_not_fresh(world: Any) -> None:
    sup, backend, _, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE + 30  # the answer arrives after the trigger's moment ...
    sup.update(list(sup.desired), read_at=QUIET_PAST_GRACE - 1)  # ... the GET started before
    sup.tick()
    assert sup.watching == {} and sup.wants_placements()  # it asks again
    clock.now += 30
    # A GET started at the moment plus the margin for the hub's whole-second clock.
    sup.update(list(sup.desired), read_at=QUIET_PAST_GRACE + supervisor.FRESH_MARGIN)
    sup.tick()
    assert PID in sup.watching
    for worker in list(sup.watching.values()):
        worker.join(5)


def test_placements_without_a_read_time_are_not_fresh(world: Any) -> None:
    sup, backend, _, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE + 30
    sup.update(list(sup.desired))  # no read time: no known moment
    sup.tick()
    assert sup.watching == {} and sup.wants_placements()


def test_facts_count_as_fresh_from_the_triggers_own_moment(world: Any) -> None:
    sup, backend, _, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE
    sup.facts_read_at = QUIET_PAST_GRACE  # read at that moment: within the margin
    sup.tick()
    assert sup.watching == {} and sup.wants_placements()
    sup.facts_read_at = QUIET_PAST_GRACE + supervisor.FRESH_MARGIN  # read past the margin
    clock.now += supervisor.IDLE_EVERY
    sup.tick()
    assert PID in sup.watching  # a diagnosis starts
    for worker in list(sup.watching.values()):
        worker.join(5)


def test_an_offset_that_moves_between_read_and_check_makes_no_read_fresh(world: Any) -> None:
    sup, backend, _, clock, _ = world
    running(sup, clock, joined_then_quiet())
    backend.below = tmux.WAITING
    clock.now = QUIET_PAST_GRACE + 30
    sup.hub_offset = 1.0  # the hub a second ahead when the read starts ...
    sup.update(list(sup.desired), read_at=QUIET_PAST_GRACE - 0.5)  # ... just before the moment
    sup.hub_offset = 0.0  # a later `server_time` (whole seconds) moves the offset down
    sup.tick()
    assert sup.watching == {} and sup.wants_placements()  # still not fresh: it asks again
