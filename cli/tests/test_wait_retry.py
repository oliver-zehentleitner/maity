from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, state


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(cli, "time", clock)
    return clock


@pytest.mark.parametrize("status", [500, 502, 503, 504, 599])
def test_wait_recovers_with_same_cursor(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
    status: int,
) -> None:
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    calls: list[str] = []

    def response(seen: fakehub.Seen) -> tuple[int, Any]:
        calls.append(seen.query)
        if len(calls) <= 2:
            return status, {"error": {"code": "internal", "message": "unavailable"}}
        return 200, {"items": [{"seq": 18, "kind": "message"}], "cursor": 18}

    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = response
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert [e["seq"] for e in json.loads(captured.out)] == [18]
    assert captured.err.count(f"hub answered {status}, retrying until the timeout") == 1
    assert len(calls) == 3 and all("after=17&" in query for query in calls)
    assert clock.sleeps == [2, 4]
    assert state.load_state(joined)["cursor"] == 18


def test_wait_outage_stops_at_deadline(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda seen: (503, "unavailable")
    assert cli.main(["wait", "--timeout", "75"]) == cli.EXIT_TIMEOUT
    # the last 5 seconds stay for the unread-chats note (`NOTE_RESERVE`)
    assert clock.sleeps == [2, 4, 8, 16, 30, 10]
    assert clock.now == 70
    assert state.load_state(joined)["cursor"] == 17
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.count("retrying until the timeout") == 1


@pytest.mark.parametrize("status", [400, 401, 403, 429])
def test_wait_does_not_retry_client_errors(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    status: int,
) -> None:
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda seen: (
        status,
        {"error": {"code": "denied", "message": "denied"}},
    )
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_ERROR
    assert clock.sleeps == []


def test_success_resets_backoff_and_retries_latest_cursor(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
) -> None:
    replies = iter(
        [
            (503, "unavailable"),
            (200, {"items": [], "cursor": 17}),
            (503, "unavailable"),
            (200, {"items": [{"seq": 18, "kind": "message"}], "cursor": 18}),
        ]
    )
    calls: list[str] = []

    def response(seen: fakehub.Seen) -> tuple[int, Any]:
        calls.append(seen.query)
        return next(replies)

    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = response
    assert cli.main(["wait", "--timeout", "60", "--keep-cursor"]) == cli.EXIT_OK
    assert clock.sleeps == [2, 1, 2]
    assert all("after=0&" in query for query in calls[:2])
    assert all("after=17&" in query for query in calls[2:])
    assert "cursor" not in state.load_state(joined)
