"""Handle arguments resolve aliases (§6.24): `say`, `ask --to`, `takeover --to`, `answer
--on-behalf-of` and placements name a member by id, current handle, former handle or global
name, ambiguity refused as the hub refuses a mention (§8.6)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, onboarding

P = "/api/v1/projects/maity"
MEMBERS: list[dict[str, Any]] = [
    {"id": "hum-1", "kind": "human", "handle": "oliver", "aliases": ["oz"]},
    {"id": "hum-2", "kind": "human", "handle": "anna", "aliases": []},
    {"id": "agt-a", "kind": "agent", "handle": "lead", "aliases": ["agent-a"],
     "owner_id": "hum-1", "name": "oliver/lead"},
    {"id": "agt-b", "kind": "agent", "handle": "agent-b", "aliases": [], "owner_id": "hum-1",
     "name": "oliver/agent-b"},
    {"id": "agt-x", "kind": "agent", "handle": "agent-b", "aliases": ["builder"],
     "owner_id": "hum-2", "name": "anna/agent-b"},
    {"id": "agt-y", "kind": "agent", "handle": "anna-bot", "aliases": ["oliver"],
     "owner_id": "hum-2", "name": "anna/anna-bot"},
    {"id": "agt-z", "kind": "agent", "handle": "zed", "aliases": ["builder"],
     "owner_id": "hum-1", "name": "oliver/zed"},
]  # fmt: skip


@pytest.mark.parametrize(
    ("which", "member"),
    [
        ("agt-a", "agt-a"),  # an id
        ("lead", "agt-a"),  # the current handle
        ("agent-a", "agt-a"),  # a former handle
        ("Agent-A", "agt-a"),
        ("oliver/agent-b", "agt-b"),  # a global name
        ("oz/agent-b", "agt-b"),  # the owner's former handle
        ("oliver/agent-a", "agt-a"),  # the profile's former handle
        ("anna/builder", "agt-x"),
        ("oliver", "hum-1"),  # a human's current handle beats an agent's alias
        ("oz", "hum-1"),
    ],
)
def test_resolve_member(which: str, member: str) -> None:
    assert cli.resolve_member(MEMBERS, which) == member


@pytest.mark.parametrize("which", ["agent-b", "builder"])
def test_several_candidates_are_refused_with_their_names(which: str) -> None:
    with pytest.raises(cli.CommandError) as exc:
        cli.resolve_member(MEMBERS, which)
    assert "could mean anna/" in str(exc.value)


def test_an_unknown_name_is_refused_or_passed_on() -> None:
    with pytest.raises(cli.CommandError):
        cli.resolve_member(MEMBERS, "nobody")
    assert cli.resolve_member(MEMBERS, "nobody", strict=False) == "nobody"


@pytest.fixture
def members(fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", f"{P}/members")] = lambda s: (200, {"items": MEMBERS})


def test_say_to_a_former_handle_and_an_instance(
    joined: Path, fake: fakehub.FakeHub, members: None, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", f"{P}/events")] = lambda s: (201, {"seq": 7})
    assert cli.main(["say", "agent-a", "hi", "--type", "notice"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["to"] == "agt-a"
    assert cli.main(["say", "lead#wqe2", "hi", "--type", "notice"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["to"] == "agt-a#wqe2"
    assert "sent notice to agt-a#wqe2" in capsys.readouterr().out


def test_say_to_your_humans_handle_is_the_chat(
    joined: Path, fake: fakehub.FakeHub, members: None
) -> None:
    fake.routes[("POST", f"{P}/conversations/agt-b/messages")] = lambda s: (201, {"seq": 9})
    assert cli.main(["resume"]) == cli.EXIT_OK  # the owner is hum-1
    assert cli.main(["say", "oz", "done"]) == cli.EXIT_OK
    assert fake.signed()[-1].path == f"{P}/conversations/agt-b/messages"


def test_say_to_an_ambiguous_handle_sends_nothing(
    joined: Path, fake: fakehub.FakeHub, members: None, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["say", "agent-b", "hi", "--type", "notice"]) == cli.EXIT_ERROR
    assert "agent-b could mean anna/agent-b, oliver/agent-b" in capsys.readouterr().err
    assert [s.method for s in fake.signed()] == ["GET"]


def test_tokens_are_not_looked_up(joined: Path, fake: fakehub.FakeHub, members: None) -> None:
    fake.routes[("POST", f"{P}/events")] = lambda s: (201, {"seq": 7})
    for to in ("all", "role:reviewer", "trust:admin"):
        assert cli.main(["say", to, "hi", "--type", "notice"]) == cli.EXIT_OK
    assert [s.method for s in fake.signed()] == ["POST"] * 3


def test_ask_to_a_handle(joined: Path, fake: fakehub.FakeHub, members: None) -> None:
    fake.routes[("POST", f"{P}/requests")] = lambda s: (201, {"id": "req-1"})
    assert cli.main(["ask", "Go?", "--to", "anna", "--class", "info"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["to"] == "hum-2"
    assert cli.main(["ask", "Go?", "--to", "owner", "--class", "info"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["to"] == "owner"


def test_takeover_to_a_former_handle(joined: Path, fake: fakehub.FakeHub, members: None) -> None:
    fake.routes[("GET", f"{P}/tasks/tsk-4")] = lambda s: (200, {"id": "tsk-4"})
    fake.routes[("POST", f"{P}/tasks/tsk-4/takeover")] = lambda s: (201, {"id": "tko-1"})
    argv = ["takeover", "tsk-4", "--reason", "silent", "--to", "agent-a#k7mq", "--json"]
    assert cli.main(argv) == cli.EXIT_OK
    assert fake.signed()[-1].json()["to"] == "agt-a#k7mq"


def test_answer_on_behalf_of_a_former_handle(
    joined: Path, fake: fakehub.FakeHub, members: None
) -> None:
    fake.routes[("POST", f"{P}/requests/req-1/answer")] = lambda s: (200, {"status": "answered"})
    assert cli.main(["answer", "req-1", "--text", "yes", "--on-behalf-of", "oz"]) == cli.EXIT_OK
    assert fake.signed()[-1].json()["on_behalf_of"] == "hum-1"


def test_placement_by_a_former_handle(joined: Path, fake: fakehub.FakeHub, members: None) -> None:
    placement = {"id": "plc-3", "agent": {"id": "agt-a", "handle": "lead"}}
    fake.routes[("GET", f"{P}/placements")] = lambda s: (200, {"items": [placement]})
    fake.routes[("POST", f"{P}/placements/plc-3/restart")] = lambda s: (200, placement)
    assert cli.main(["placement", "restart", "agent-a"]) == cli.EXIT_OK
    assert fake.signed()[-1].path == f"{P}/placements/plc-3/restart"


def test_resume_shows_former_handles() -> None:
    peers = [{"member_id": "agt-a", "handle": "lead", "aliases": ["agent-a", "a\x1b[2J"],
              "trust": "admin", "role": "coder", "presence": "online"}]  # fmt: skip
    text = onboarding.render({"peers": peers})
    assert "lead [agt-a] (admin coder, online; formerly agent-a, a" in text
    assert "\x1b" not in text


# --- `say <to> --type T "…"`: the message after the options --------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["say", "agt-a", "--type", "notice", "hi there"],
        ["say", "agt-a", "--task", "tsk-4", "--type", "notice", "hi there"],
        ["say", "--type", "notice", "agt-a", "hi there"],
        ["say", "agt-a", "hi there", "--type", "notice"],
    ],
)
def test_say_takes_the_message_before_or_after_the_options(
    joined: Path, fake: fakehub.FakeHub, argv: list[str]
) -> None:
    fake.routes[("POST", f"{P}/events")] = lambda s: (201, {"seq": 7})
    assert cli.main(argv) == cli.EXIT_OK
    sent = fake.signed()[-1].json()
    assert (sent["to"], sent["body"]) == ("agt-a", "hi there")


@pytest.mark.parametrize(
    "argv",
    [
        ["say", "agt-a", "--type", "notice", "one", "two"],
        ["say", "agt-a", "hi", "--type", "notice", "more"],
        ["say", "agt-a", "--type", "notice", "--bogus"],
        ["task", "show", "tsk-1", "extra"],
    ],
)
def test_anything_else_left_over_is_still_an_error(joined: Path, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == cli.EXIT_USAGE
