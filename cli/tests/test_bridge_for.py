"""`maity --for <agent> <command>`: a bridge acting for an agent it serves (§2.3, §13)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, hub, onboarding, sign, state

SERVED = {
    "id": "agt-s",
    "kind": "agent",
    "handle": "designer",
    "aliases": [],
    "owner_id": "hum-1",
    "name": "m/designer",
}


def test_the_for_line_comes_after_the_on_request_line_before_the_body_hash() -> None:
    both = sign.canonical_string("get", "/api/v1/x", "", "17", "n", b"", "req-1", "agt-s")
    lines = both.split("\n")
    assert lines[6:8] == ["req-1", "for:agt-s"] and len(lines) == 9
    alone = sign.canonical_string("get", "/api/v1/x", "", "17", "n", b"", None, "agt-s")
    assert alone.split("\n")[6] == "for:agt-s"
    plain = sign.canonical_string("get", "/api/v1/x", "", "17", "n", b"")
    assert len(plain.split("\n")) == 7


def _members(fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", "/api/v1/projects/oliver/maity/members")] = lambda _seen: (
        200,
        {"items": [*fakehub.MEMBERS, SERVED], "next_cursor": None},
    )


def test_a_handle_resolves_and_every_call_carries_maity_for(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _members(fake)
    fake.routes[("POST", "/api/v1/projects/oliver/maity/events")] = lambda _seen: (
        201,
        {"seq": 9, "id": "evt-9"},
    )
    assert cli.main(["--for", "designer", "say", "all", "done", "--type", "notice"]) == 0
    sent = [s for s in fake.seen if s.method == "POST"]
    assert sent and sent[-1].headers["maity-for"] == "agt-s"  # signed: the fake verified it
    listed = [s for s in fake.seen if s.path.endswith("/members")]
    assert listed and "maity-for" not in listed[0].headers  # resolved as the bridge itself


def test_for_is_a_usage_error_on_commands_that_call_me(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["--for", "agt-s", "resume"]) == cli.EXIT_USAGE
    assert "--for applies to project commands" in capsys.readouterr().err
    assert not [s for s in fake.seen if s.path.startswith("/api/v1/me")]
    assert cli.main(["--for", "agt-s", "join", "https://x/j/t", "--code", "c"]) == cli.EXIT_USAGE


def test_wait_for_reads_with_for_and_keeps_its_own_cursor(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    queries: list[str] = []

    def events(seen: fakehub.Seen) -> tuple[int, Any]:
        queries.append(seen.query)
        assert seen.headers["maity-for"] == "agt-s"
        return 200, {"items": [{"seq": 30, "kind": "message"}], "cursor": 30}

    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = events
    assert cli.main(["--for", "agt-s", "wait", "--timeout", "60"]) == cli.EXIT_OK
    assert [e["seq"] for e in json.loads(capsys.readouterr().out)] == [30]
    assert "after=0&" in queries[0] and "for=agt-s" in queries[0]
    saved = state.load_state(joined)
    assert saved["cursor"] == 17 and saved["for_cursors"] == {"agt-s": 30}


def test_the_resume_names_each_agent_it_carries_for() -> None:
    lines = onboarding._who(
        {
            "me": {"member_id": "agt-b", "handle": "agent-b"},
            "membership": {
                "bridging_for": [
                    {"id": "brg-1", "member_id": "agt-s", "handle": "designer",
                     "purpose": "git for the designer's files", "cross_owner": False},
                ]
            },
        },
        {},
    )  # fmt: skip
    assert "You carry for @designer: git for the designer's files" in lines


@pytest.mark.parametrize(
    "argv",
    [
        ["--for", "designer", "dormant"],  # a handle: not even resolved
        ["--for", "agt-s", "resume", "--full"],  # a stored packet is not printed either
        ["--for", "agt-s", "profile", "avatar", "missing.png"],  # before the file is read
    ],
)
def test_for_on_a_command_of_the_bridges_own_sends_nothing(
    argv: list[str], joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    state.save_state(joined, {"me": {"member_id": "agt-b"}}, name=cli.LAST_PACKET)
    assert cli.main(argv) == cli.EXIT_USAGE
    assert "--for applies to project commands" in capsys.readouterr().err
    assert fake.seen == []


def test_say_human_for_an_agent_writes_in_its_conversation(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _members(fake)
    path = "/api/v1/projects/oliver/maity/conversations/agt-s/messages"
    fake.routes[("POST", path)] = lambda _seen: (201, {"seq": 9, "id": "evt-9"})
    assert cli.main(["--for", "designer", "say", "human", "on it"]) == 0
    posted = [s for s in fake.seen if s.method == "POST"]
    assert [s.path for s in posted] == [path] and posted[0].headers["maity-for"] == "agt-s"
    assert len([s for s in fake.seen if s.path.endswith("/members")]) == 1  # resolved once


def test_the_served_agent_answers_for_its_card_through_the_bridge(joined: Path) -> None:
    cli.Session.for_target = "agt-s"
    try:
        session = cli.Session()
        held = {"from": {"member_id": "agt-s", "instance": None}}
        cli._check_holder(session, "tko-1", held)  # its claim through the bridge
        assert session.me == "agt-s" and session.my_instance is None
        with pytest.raises(cli.LocalRefusal):
            cli._check_holder(session, "tko-1", {"from": {"member_id": "agt-other"}})
    finally:
        cli.Session.for_target = None


def test_a_failed_lookup_of_the_handle_never_lets_a_call_go_out_as_the_bridge(
    joined: Path, fake: fakehub.FakeHub
) -> None:
    cli.Session.for_target = "designer"
    try:
        session = cli.Session()
        fake.routes[("GET", "/api/v1/projects/oliver/maity/members")] = lambda _seen: (
            502,
            {"error": {"code": "unavailable", "message": "down"}},
        )
        with pytest.raises(hub.HubError):
            session.client.call("GET", "/projects/oliver/maity/tasks")
        with pytest.raises(hub.ForRefused):  # the /me refusal does not hang on it
            session.client.call("GET", "/me")
        _members(fake)
        fake.routes[("GET", "/api/v1/projects/oliver/maity/tasks")] = lambda _seen: (
            200,
            {"items": [], "next_cursor": None},
        )
        session.client.call("GET", "/projects/oliver/maity/tasks")  # resolved on the retry
        tasks = [s for s in fake.seen if s.path.endswith("/tasks")]
        assert [s.headers.get("maity-for") for s in tasks] == ["agt-s"]
        assert not [s for s in fake.seen if s.path.startswith("/api/v1/me")]
    finally:
        cli.Session.for_target = None
