"""`maity wait --related`: only events related to the reader, the rest read past
(tsk-3kbpak51yqyn; the definition is `cli._related`)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, state

ME, INSTANCE = "agt-b", "k7mq"


def _event(kind: str, audience: list[str], seq: int = 1, **extra: Any) -> dict[str, Any]:
    return {"seq": seq, "kind": kind, "audience": audience, **extra}


def _about(member: str) -> dict[str, Any]:
    return {"subject": {"type": "member", "id": member}, "payload": {"member_id": member}}


KEPT = {
    "a message to all": _event("message", ["all"], payload={"type": "notice"}),
    "a request to a role": _event("request_created", ["role:reviewer"]),
    "a request answered": _event("request_answered", ["instance:agt-a#x1"]),
    "the project's state": _event("state_changed", ["all"]),
    "the project's rules": _event("rules_changed", ["all"]),
    "a mention by a role-wide note": _event(
        "note_added", ["role:coder"], payload={"mentions": [{"member_id": ME, "instance": None}]}
    ),
    "my own availability, to the admins": _event(
        "member_availability_changed", ["trust:admin"], **_about(ME)
    ),
    "my card, to this instance": _event(
        "task_claimed", ["member:agt-a", f"instance:{ME}#{INSTANCE}"]
    ),
    "my card's pull request merged": _event("link_observed", ["all", f"member:{ME}"]),
    "a card I watch": _event("task_updated", ["watchers:tsk-1"]),
    "a card's restricted list": _event(
        "restricted_changed", ["restricted:tsk-1"], payload={"task_id": "tsk-1"}
    ),
    "a report of mine stalled, to me as its boss": _event(
        "holder_stalled", [f"member:{ME}", "trust:admin"], **_about("agt-x")
    ),
}

SKIPPED = {
    "another member's availability, to me as coordinator": _event(
        "member_availability_changed", [f"member:{ME}", "trust:admin"], **_about("agt-x")
    ),
    "another member's update": _event(
        "member_updated", ["all", "member:agt-x", f"member:{ME}"], **_about("agt-x")
    ),
    "another member joined": _event("member_joined", ["all"], **_about("agt-x")),
    "a link observed by all": _event("link_observed", ["all"]),
    "a report to the reviewers": _event("task_reported", ["role:reviewer", "trust:admin"]),
    "a sibling instance's card": _event("task_claimed", [f"instance:{ME}#other"]),
    "a project update": _event("project_updated", ["all"]),
    "a change of the restricted-access set": _event(
        "restricted_changed", ["restricted:set"], payload={"task_id": None}
    ),
}


@pytest.mark.parametrize("event", KEPT.values(), ids=KEPT.keys())
def test_related_keeps(event: dict[str, Any]) -> None:
    assert cli._related(event, ME, INSTANCE)


@pytest.mark.parametrize("event", SKIPPED.values(), ids=SKIPPED.keys())
def test_related_skips(event: dict[str, Any]) -> None:
    assert not cli._related(event, ME, INSTANCE)


def test_any_own_instance_counts_without_an_instance_but_not_for_a_bridge() -> None:
    event = _event("task_claimed", [f"instance:{ME}#other"])
    assert cli._related(event, ME, None)
    assert not cli._related(event, ME, None, carried=True)


def test_without_a_member_id_nothing_is_skipped() -> None:
    assert cli._related(_event("project_updated", ["all"]), None, None)


def _events(fake: fakehub.FakeHub) -> None:
    fake.events += [
        _event("member_availability_changed", ["trust:admin"], 11, **_about("agt-x")),
        _event("message", ["all"], 12, payload={"type": "notice", "body": "hi"}),
        _event("link_observed", ["all"], 13),
        _event("task_claimed", [f"member:{ME}"], 14),
        _event("member_updated", ["all"], 15, **_about("agt-x")),
    ]


def test_wait_related_reads_past_the_rest(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _events(fake)
    assert cli.main(["wait", "--timeout", "5", "--related"]) == cli.EXIT_OK
    assert [e["seq"] for e in json.loads(capsys.readouterr().out)] == [12, 14]
    assert state.load_state(joined)["cursor"] == 14


def test_wait_related_acknowledges_what_it_reads_past_and_waits_on(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.events += [_event("link_observed", ["all"], 11)]
    assert cli.main(["wait", "--timeout", "2", "--related"]) == cli.EXIT_TIMEOUT
    assert capsys.readouterr().out == ""
    assert state.load_state(joined)["cursor"] == 11


def test_wait_related_returns_an_event_of_a_cards_restricted_list(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    """A card's `restricted_changed`, delivered by `restricted:<task id>` alone, is printed,
    not acknowledged unseen."""
    fake.events += [
        _event("link_observed", ["all"], 17),
        _event("restricted_changed", ["restricted:tsk-1"], 18, payload={"task_id": "tsk-1"}),
    ]
    assert cli.main(["wait", "--timeout", "5", "--related"]) == cli.EXIT_OK
    assert [e["seq"] for e in json.loads(capsys.readouterr().out)] == [18]
    assert state.load_state(joined)["cursor"] == 18


def test_wait_related_and_kind_must_both_match(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _events(fake)
    assert cli.main(["wait", "--timeout", "5", "--related", "--kind", "task_claimed"]) == 0
    assert [e["seq"] for e in json.loads(capsys.readouterr().out)] == [14]


def test_wait_related_with_this_instance(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    state.save_state(joined, {**state.load_state(joined), "instance": INSTANCE})
    fake.events += [
        _event("task_claimed", [f"instance:{ME}#other"], 11),
        _event("task_claimed", [f"instance:{ME}#{INSTANCE}"], 12),
    ]
    assert cli.main(["wait", "--timeout", "5", "--related"]) == cli.EXIT_OK
    assert [e["seq"] for e in json.loads(capsys.readouterr().out)] == [12]


def test_wait_related_does_not_go_with_keep_cursor(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["wait", "--timeout", "2", "--related", "--keep-cursor"])
    assert code == cli.EXIT_USAGE
    assert "--related reads past other events" in capsys.readouterr().err
    assert not [s for s in fake.seen if s.path.endswith("/events")]


def test_wait_without_related_still_returns_everything(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _events(fake)
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    assert [e["seq"] for e in json.loads(capsys.readouterr().out)] == [11, 12, 13, 14, 15]


def test_wait_for_relates_events_to_the_served_agent(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    served = {"id": "agt-s", "kind": "agent", "handle": "designer", "aliases": []}
    fake.routes[("GET", "/api/v1/projects/oliver/maity/members")] = lambda _seen: (
        200,
        {"items": [*fakehub.MEMBERS, served], "next_cursor": None},
    )
    items = [
        _event("task_claimed", [f"member:{ME}"], 30),  # the bridge's own, not agt-s's
        _event("task_claimed", ["member:agt-s"], 31),
    ]
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda _seen: (
        200,
        {"items": items, "cursor": 31},
    )
    assert cli.main(["--for", "agt-s", "wait", "--timeout", "60", "--related"]) == cli.EXIT_OK
    assert [e["seq"] for e in json.loads(capsys.readouterr().out)] == [31]
