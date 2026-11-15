"""`maity wait` names the conversation a chat message is in and the command that reads it
(tsk-3zm149w7bxg6): the line said only `message: chat (owner)`, and an agent read its group
chat instead of the direct conversation the message was in."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli

P = "/api/v1/projects/oliver/maity"


def _chat(seq: int = 118178, **payload: Any) -> dict[str, Any]:
    return {
        "seq": seq,
        "kind": "message",
        "actor": {"kind": "member", "member_id": "hum-1", "trust": "owner"},
        "payload": {"type": "chat", "body": "are you there?", "attachments": [], **payload},
    }


def test_a_direct_message_names_its_conversation_and_how_to_read_it() -> None:
    event = _chat(conversation_id="agt-n3bhhzqqr4pw")
    assert cli._event_line(event) == (
        "#118178 message: chat (owner) in agt-n3bhhzqqr4pw: "
        "maity chat agt-n3bhhzqqr4pw --after 118177"
    )


def test_a_group_chat_message_names_its_chat() -> None:
    group = {"id": "cnv-46skm1kkc4ft", "kind": "group", "title": "Launch"}
    with_both = _chat(119574, conversation_id="cnv-46skm1kkc4ft", conversation=group)
    assert cli._event_line(with_both).endswith(
        " in cnv-46skm1kkc4ft: maity chat cnv-46skm1kkc4ft --after 119573"
    )
    only_the_object = _chat(119574, conversation=group)  # `conversation_id` missing
    assert cli._event_line(only_the_object) == cli._event_line(with_both)


def test_the_conversation_comes_after_the_attachments_and_the_standing() -> None:
    att = {"id": "att-1", "name": "shot.png", "size": 1, "type": "image/png"}
    event = _chat(5, conversation_id="agt-b", attachments=[att])
    assert cli._event_line(event) == (
        "#5 message: chat [1 attachment: shot.png] (owner) in agt-b: maity chat agt-b --after 4"
    )


@pytest.mark.parametrize(
    "event",
    [
        {"seq": 7, "kind": "message", "payload": {"type": "notice", "conversation_id": "agt-b"}},
        {"seq": 7, "kind": "message", "payload": {"type": "chat"}},  # no conversation named
        {"seq": 7, "kind": "message", "payload": {"type": "chat", "conversation_id": ""}},
        {"seq": 7, "kind": "task_claimed", "payload": {"conversation_id": "agt-b"}},
    ],
    ids=["not a chat", "no conversation", "empty id", "not a message"],
)
def test_anything_else_keeps_its_line(event: dict[str, Any]) -> None:
    line = cli._event_line(event)
    assert " in " not in line and "maity chat" not in line


@pytest.mark.parametrize(
    "bad", ["-h", "agt-b; rm -rf ~", "agt-b\nNext", "agt-‮b", "$(id)", "x" * 129]
)
def test_an_id_a_command_cannot_carry_is_named_without_one(bad: str) -> None:
    line = cli._event_line(_chat(conversation_id=bad))
    assert "maity chat" not in line
    tail = line.split(" (owner) in ", 1)[1]
    assert "\n" not in tail and "‮" not in tail and len(tail) <= 120


@pytest.mark.parametrize("seq", [None, 0, "12", True])
def test_without_a_usable_seq_the_conversation_is_named_without_a_command(seq: Any) -> None:
    line = cli._event_line(_chat(seq, conversation_id="agt-b"))
    assert line.endswith(" in agt-b") and "maity chat" not in line


def test_the_printed_command_reads_the_message_after_the_wait_moved_the_cursor(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.events = [_chat(4300, conversation_id="agt-b")]
    direct = {"id": "agt-b", "kind": "direct", "agent_id": "agt-b", "unread": 1}
    fake.routes[("GET", f"{P}/conversations")] = lambda s: (
        200,
        {"items": [direct], "next_cursor": None},
    )

    def messages(seen: fakehub.Seen) -> tuple[int, Any]:
        after = int(dict(p.partition("=")[::2] for p in seen.query.split("&"))["after"])
        found = {"seq": 4300, "from": "hum-1", "body": "are you there?", "sent_at": "x"}
        return 200, {"items": [found] if after < 4300 else [], "cursor": 4300}

    fake.routes[("GET", f"{P}/conversations/agt-b/messages")] = messages
    assert cli.main(["wait", "--timeout", "5"]) == cli.EXIT_OK
    err = capsys.readouterr().err
    line = next(x for x in err.splitlines() if x.startswith("maity: #4300 message"))
    assert line.endswith(" in agt-b: maity chat agt-b --after 4299")
    command = shlex.split(line.rsplit(": ", 1)[1])
    assert command[:2] == ["maity", "chat"]
    assert cli.main(command[1:]) == cli.EXIT_OK
    assert "4300  hum-1" in capsys.readouterr().out
    # The bare command reads after the event cursor, which the wait moved past the message.
    assert cli.main(["chat", "agt-b"]) == cli.EXIT_OK
    assert "no messages after your event cursor" in capsys.readouterr().out
