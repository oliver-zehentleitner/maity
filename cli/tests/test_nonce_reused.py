"""A long-poll a proxy re-sent reaches the hub twice; the hub refuses the copy as
`nonce_reused` (hub/tests/test_two_processes.py, the identical signed GET at a second process).
The client made that nonce for its one attempt, so this is usually such a copy; a `GET` is
signed again and sent once more, a write is never sent again on it (tsk-d9b3t5wprwgc)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, hub, state

EVENTS = ("GET", "/api/v1/projects/oliver/maity/events")
NONCE_REUSED = (
    401,
    {
        "error": {
            "code": "nonce_reused",
            "message": "this nonce was used within the window",
            "details": {},
        }
    },
)


def test_wait_reads_on_after_a_redelivered_long_poll(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    nonces: list[str] = []

    def response(seen: fakehub.Seen) -> tuple[int, Any]:
        nonces.append(seen.headers["maity-nonce"])
        if len(nonces) == 1:
            return NONCE_REUSED
        return 200, {"items": [{"seq": 18, "kind": "message"}], "cursor": 18}

    fake.routes[EVENTS] = response
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    assert [e["seq"] for e in json.loads(capsys.readouterr().out)] == [18]
    assert len(nonces) == 2 and nonces[0] != nonces[1]  # signed again, with a new nonce


def test_a_get_is_sent_again_only_once(joined: Path, fake: fakehub.FakeHub) -> None:
    fake.routes[EVENTS] = lambda seen: NONCE_REUSED
    session = cli.Session()
    with pytest.raises(hub.HubError) as raised:
        session.client.call("GET", session.project_path("events"), timeout=5)
    assert raised.value.code == "nonce_reused"
    assert len([s for s in fake.signed() if s.path.endswith("/events")]) == 2


def test_a_write_is_not_sent_again(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", "/api/v1/projects/oliver/maity/requests")] = lambda seen: NONCE_REUSED
    args = ["ask", "Merge #12?", "--to", "human", "--class", "decision"]
    args += ["--option", "yes", "--option", "no"]
    assert cli.main(args) != cli.EXIT_OK
    assert "nonce_reused" in capsys.readouterr().err
    assert len([s for s in fake.signed() if s.path.endswith("/requests")]) == 1


def test_the_repeat_gets_only_what_is_left_of_the_timeout(
    joined: Path, fake: fakehub.FakeHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.routes[EVENTS] = lambda seen: NONCE_REUSED
    session = cli.Session()
    real = time.monotonic

    def clock() -> float:  # once the first attempt reached the hub, its 5 seconds are gone
        return real() + (6.0 if fake.seen else 0.0)

    monkeypatch.setattr(time, "monotonic", clock)
    with pytest.raises(hub.HubError) as raised:
        session.client.call("GET", session.project_path("events"), timeout=5)
    assert raised.value.code == "nonce_reused"
    assert len(fake.signed()) == 1
