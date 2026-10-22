"""The CLI side of availability (§6.11, §13, §15.7): `maity limit`, the Availability block,
and the runner's `rate_limited`."""

# ruff: noqa: F811 - `world` is test_supervisor's fixture: pytest binds it by its name
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest
from test_onboarding import packet
from test_supervisor import placement, recorded, settle, world  # noqa: F401

from maity import cli, onboarding
from maity.runner import adapters, loop, supervisor

# --- maity limit -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "until"),
    [
        ("90m", "1970-01-01T01:30:00Z"),
        ("1h30m", "1970-01-01T01:30:00Z"),
        ("2d12h", "1970-01-03T12:00:00Z"),
        ("7d", "1970-01-08T00:00:00Z"),
        ("45s", "1970-01-01T00:00:45Z"),
        ("2026-10-22T17:00:00+02:00", "2026-10-22T15:00:00Z"),  # converted, not sent as given
        ("2026-10-22T17:00:00Z", "2026-10-22T17:00:00Z"),
    ],
)
def test_until_is_sent_in_utc(value: str, until: str) -> None:
    assert cli.limit_until(value, now=0) == until


@pytest.mark.parametrize(
    "value",
    ["2026-10-22T17:00", "2026-10-22", "8d", "7d1s", "1.5h", "-3h", "0h", "30m1h", "1h1h",
     "h", "", "90 m", "soon"],
)  # fmt: skip
def test_anything_else_is_refused_before_any_call(
    value: str, joined: Path, fake: fakehub.FakeHub
) -> None:
    before = len(fake.seen)
    assert cli.main(["limit", f"--until={value}"]) == cli.EXIT_USAGE
    assert len(fake.seen) == before


def test_limit_posts_and_prints_the_stored_until(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer = {"availability": {"state": "limited", "until": "2026-10-22T17:00:00Z"}}
    fake.routes[("POST", "/api/v1/me/limit")] = lambda s: (200, answer)
    args = ["limit", "--until", "2026-10-22T19:00:00+02:00", "--reason", "quota"]
    assert cli.main(args) == cli.EXIT_OK
    assert fake.signed()[-1].json() == {"until": "2026-10-22T17:00:00Z", "reason": "quota"}
    assert capsys.readouterr().out.strip() == "limited until 2026-10-22T17:00:00Z"


# --- the Availability block --------------------------------------------------------------------


def test_the_availability_block_follows_the_contracts_shape() -> None:
    covered_card = {
        "id": "tsk-0004",
        "status": "in_progress",
        "title": "Leases",
        "cover": {"for": "agt-c", "by": "agt-b", "since": "2026-10-22T14:05:00Z"},
    }
    covered_req = {
        "id": "req-0012",
        "class": "decision",
        "title": "Which lease?",
        "cover": {"for": "agt-c", "by": "agt-b", "since": "2026-10-22T14:05:00Z"},
    }
    peers = [
        {"member_id": "agt-a", "handle": "agent-a", "role": "admin", "presence": "online",
         "availability": {"state": "available"}},
        {"member_id": "agt-c", "handle": "agent-c", "role": "member", "presence": "offline",
         "availability": {"state": "limited", "until": "2026-10-22T17:00:00Z"},
         "covered_by": {"member_id": "agt-b", "since": "2026-10-22T14:05:00Z"}},
        {"member_id": "agt-r", "handle": "oz-agent-review", "role": "reviewer",
         "presence": "offline", "availability": {"state": "offline"}},
    ]  # fmt: skip
    membership = {**packet()["membership"], "covering": [
        {"member_id": "agt-c", "since": "2026-10-22T14:05:00Z"}]}  # fmt: skip
    text = onboarding.render(packet(
        membership=membership, peers=peers, claims=[covered_card],
        requests={"mine_open": [], "answered_since_cursor": [], "to_answer": [covered_req]},
    ))  # fmt: skip
    block = text[text.index("Availability\n") :].split("\n\n")[0].splitlines()
    assert block == [
        "Availability",
        "  covering @agent-c since 2026-10-22T14:05:00Z: tsk-0004, req-0012",
        "  @agent-c limited until 2026-10-22T17:00:00Z, covered by @agent-b",
        "  @oz-agent-review offline",
    ]
    assert text.index("Availability") < text.index("Your briefing")
    assert "tsk-0004 [in_progress] Leases (cover for @agent-c)" in text
    assert "req-0012 (decision): Which lease? (cover for @agent-c)" in text


def test_no_availability_block_when_everyone_is_available() -> None:
    assert "Availability" not in onboarding.render(packet())


# --- the runner's rate_limited ----------------------------------------------------------------


def test_the_loop_reports_a_verified_limit_exit(tmp_path: Path) -> None:
    limit = tmp_path / "limit.json"
    spec = {"first": ["h"], "again": ["h"], "env": {},
            "restart": {"initial": 10, "factor": 2.0, "max": 300, "crash_window": 1800,
                        "crash_cap": 5, "quick_exit": 60},
            "limit": {"exit_codes": [75], "file": str(limit)}}  # fmt: skip
    run = loop.Loop(spec, run=lambda argv, env: 75, wait=lambda: (3, "", ""),
                    sleep=lambda s: None, log=lambda line: None)  # fmt: skip
    assert run.main() == loop.EXIT_RATE_LIMITED
    assert json.loads(limit.read_text()) == {"exit_code": 75, "reset_at": None}


def test_without_a_verified_signal_a_limit_is_an_ordinary_exit() -> None:
    assert adapters.LIMIT_EXITS == {}  # nothing verified on a real run yet (§15.7)


def limited(sup: Any, backend: Any, reset_at: str | None = None, code: int = 75) -> None:
    agent_dir = sup.cfg.state_dir / "agents" / "plc-0003"
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / adapters.LIMIT_FILE).write_text(
        json.dumps({"exit_code": code, "reset_at": reset_at})
    )
    backend.exit("maity_maity_agent-3", loop.EXIT_RATE_LIMITED)
    sup.tick()


def test_a_limit_without_a_reset_time_backs_off_15_minutes_doubling_to_2_hours(
    world: Any,
) -> None:
    sup, backend, reports, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    gaps = []
    for _ in range(5):
        settle(sup)
        limited(sup, backend)
        rec = sup.records["plc-0003"]
        assert (rec.state, rec.reason, rec.detail) == ("rate_limited", "quota", "reset_unknown")
        gaps.append(round(rec.retry_at - clock.now))
        clock.now = rec.retry_at
    assert gaps == [900, 1800, 3600, 7200, 7200]
    body = next(b for _, b in reports.sent if b["state"] == "rate_limited")
    assert body["exit_code"] == 75 and body["retry_at"] is not None
    assert body["crash_count"] is None  # not a crash
    assert sup.records["plc-0003"].crashes == []


def test_a_named_reset_is_used_and_capped_at_7_days(world: Any) -> None:
    sup, backend, _, clock, _ = world
    recorded(sup.cfg)
    sup.update([placement()])
    settle(sup)
    limited(sup, backend, supervisor.stamp(clock.now + 3600))
    rec = sup.records["plc-0003"]
    assert rec.detail is None and round(rec.retry_at - clock.now) == 3600
    clock.now = rec.retry_at
    settle(sup)
    limited(sup, backend, supervisor.stamp(clock.now + 30 * 86400))
    assert round(sup.records["plc-0003"].retry_at - clock.now) == 7 * 86400


def test_a_rate_limited_placement_keeps_its_slot_and_a_stop_ends_it(world: Any) -> None:
    sup, backend, reports, clock, _ = world  # max_agents = 2
    for n in (3, 4, 5):
        recorded(sup.cfg, n)
    sup.update([placement(3), placement(4)])
    settle(sup)
    limited(sup, backend)
    sup.update([placement(3), placement(4), placement(5)])
    settle(sup)
    assert sup.records["plc-0005"].reason == "capacity"  # agent-3's slot is still taken
    sup.update([placement(3, desired="stopped"), placement(4), placement(5)])
    settle(sup)
    assert (sup.records["plc-0003"].state, sup.records["plc-0003"].retry_at) == ("stopped", None)
    clock.now += 2 * 3600
    settle(sup)
    assert "maity_maity_agent-3" not in [n for n, _, _ in backend.started[2:]]
