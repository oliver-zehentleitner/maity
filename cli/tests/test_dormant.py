"""`maity dormant` and the resume line of a dormant instance (docs/api.md §6.17, §13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fakehub
import pytest
from test_onboarding import packet

from maity import cli, onboarding, state

ME = "/api/v1/me"


def _instance(joined: Path, instance: str = "wqe2") -> None:
    data = state.load_state(joined)
    data["instance"] = instance
    state.save_state(joined, data)


def _member(dormant: Any) -> dict[str, Any]:
    """The member view `PATCH /me` answers with (§6.2), this instance among its siblings."""
    return {
        "id": "agt-b",
        "handle": "agent-b",
        "instances": [
            {"id": "k7mq", "label": "agent-b#k7mq", "dormant": None},
            {"id": "wqe2", "label": "agent-b#wqe2", "dormant": dormant},
        ],
    }


ASLEEP = {"since": "2026-10-31T06:00:00Z", "by": {"kind": "agent", "id": "agt-b"}}


@pytest.mark.parametrize(
    ("flags", "sent", "dormant", "line"),
    [
        ([], True, ASLEEP, "dormant: only @agent-b#wqe2 wakes this instance\n"),
        (["--off"], False, None, "awake\n"),
    ],
)
def test_the_command_patches_me_and_says_what_the_hub_stored(
    flags: list[str],
    sent: bool,
    dormant: Any,
    line: str,
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _instance(joined)
    fake.routes[("PATCH", ME)] = lambda seen: (200, _member(dormant))
    assert cli.main(["dormant", *flags]) == cli.EXIT_OK
    assert [r.json() for r in fake.signed() if r.path == ME] == [{"dormant": sent}]
    assert capsys.readouterr().out == line


def test_the_line_follows_the_answer_not_the_request(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    """A sibling's state is not this instance's: only the entry for this instance counts."""
    _instance(joined, "k7mq")
    fake.routes[("PATCH", ME)] = lambda seen: (200, _member(ASLEEP))
    assert cli.main(["dormant"]) == cli.EXIT_OK
    assert capsys.readouterr().out == "awake\n"


@pytest.mark.parametrize(
    ("stored", "answer"),
    [
        ("wqe2", {"handle": "agent-b"}),  # an answer without this instance's entry
        (None, _member(ASLEEP)),  # no instance id stored: no entry is this instance's
    ],
)
def test_without_its_own_entry_no_state_and_no_address_is_printed(
    stored: str | None,
    answer: dict[str, Any],
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The member address does not wake a dormant instance, so it is never printed as if."""
    if stored:
        _instance(joined, stored)
    fake.routes[("PATCH", ME)] = lambda seen: (200, answer)
    assert cli.main(["dormant"]) == cli.EXIT_OK  # the hub stored it; the call did not fail
    out, err = capsys.readouterr()
    assert out == ""
    assert "the hub's answer does not show this instance; run `maity resume`" in err


def test_json_prints_the_answer(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    _instance(joined)
    fake.routes[("PATCH", ME)] = lambda seen: (200, _member(None))
    assert cli.main(["dormant", "--off", "--json"]) == cli.EXIT_OK
    assert '"label": "agent-b#wqe2"' in capsys.readouterr().out


def test_json_without_its_own_entry_prints_the_answer_and_the_hint(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    """The answer still goes to stdout for a script; the hint goes to stderr."""
    _instance(joined, "zz99")
    fake.routes[("PATCH", ME)] = lambda seen: (200, _member(None))
    assert cli.main(["dormant", "--json"]) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert '"label": "agent-b#wqe2"' in out
    assert "the hub's answer does not show this instance; run `maity resume`" in err


def _me(**fields: Any) -> dict[str, Any]:
    base = packet()
    return {**base, "me": {**base["me"], "instance": "wqe2", **fields}}


def test_resume_of_a_dormant_instance_names_the_address_that_wakes_it() -> None:
    text = onboarding.render(_me(dormant=ASLEEP))
    line = "Dormant: only @agent-b#wqe2 wakes this instance. End it with: maity dormant --off"
    assert line in text
    assert text.index("You are agent-b#wqe2") < text.index(line) < text.index("Trust:")


def test_an_awake_instance_has_no_dormant_line() -> None:
    assert "Dormant:" not in onboarding.render(_me(dormant=None))


def test_a_dormant_sibling_is_marked() -> None:
    sibling = {"id": "k7mq", "presence": "online", "dormant": ASLEEP}
    text = onboarding.render({**_me(), "team": [sibling]})
    assert "Other instances of you: agent-b#k7mq (online, dormant)" in text
