"""docs/api.md §5.3 "A model change is a new session" on the CLI: a resume that changes the
agent's own model says so in one line, and `wait` shows a `session_model_changed` event in
words."""

from __future__ import annotations

import json
from pathlib import Path

import fakehub
import pytest

from maity import cli, state


def _stored(joined: Path, **values: str) -> None:
    state.save_state(joined, {**state.load_state(joined), **values})


def test_an_own_change_of_model_is_one_line_before_the_packet(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _stored(joined, model="opus")
    assert cli.main(["resume", "--model", "sonnet"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert out.startswith("Model changed: opus -> sonnet, your lead is told.\n")
    assert fake.signed()[-1].json()["model"] == "sonnet"
    assert state.load_state(joined)["model"] == "sonnet"
    # the next resume runs the same model: nothing to say
    assert cli.main(["resume"]) == cli.EXIT_OK
    assert "Model changed" not in capsys.readouterr().out


def test_no_line_without_a_change_a_previous_model_or_in_json(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _stored(joined, model="opus")
    assert cli.main(["resume", "--model", "opus"]) == cli.EXIT_OK
    assert "Model changed" not in capsys.readouterr().out
    assert cli.main(["resume", "--model", "sonnet", "--json"]) == cli.EXIT_OK
    assert json.loads(capsys.readouterr().out)["session"]  # the output stays JSON
    data = state.load_state(joined)
    data.pop("model", None)
    state.save_state(joined, data)  # no model known before: the first one is no change
    assert cli.main(["resume", "--model", "haiku"]) == cli.EXIT_OK
    assert "Model changed" not in capsys.readouterr().out


def test_a_model_change_event_is_read_as_words() -> None:
    event = {
        "seq": 41,
        "kind": "session_model_changed",
        "subject": {"type": "member", "id": "agt-w"},
        "payload": {
            "member_id": "agt-w",
            "instance": "a1b2",
            "from": {"harness": "Claude Code", "model": "opus"},
            "to": {"harness": "Codex", "model": None},
            "session_id": "ses-1",
        },
    }
    assert cli._event_line(event) == ("#41 session_model_changed agt-w: Claude Code/opus -> Codex")
    bare = {**event, "payload": {"from": None, "to": {}}}
    assert cli._event_line(bare) == "#41 session_model_changed agt-w: ? -> ?"


def test_the_standing_of_an_author_is_in_the_line() -> None:
    def line(**actor: object) -> str:
        return cli._event_line({"seq": 7, "kind": "message", "actor": actor})

    assert line(trust="guest", cross_owner=True) == "#7 message (guest, other owner)"
    assert line(trust="member", cross_owner=False) == "#7 message"
    assert line(trust=None, cross_owner=False) == "#7 message (former member)"
    assert line(member_id="agt-a") == "#7 message"  # an older hub sends none
