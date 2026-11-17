from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import fakehub
import pytest

from maity import cli, hub, state


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


EPOCH = datetime(2026, 11, 17, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(cli, "time", clock)
    # The outage clock reads the wall time; here it moves with the fake monotonic one.
    monkeypatch.setattr(
        cli, "_utc_now", lambda: EPOCH + timedelta(seconds=clock.now), raising=False
    )
    return clock


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504, 599])
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
    assert "hub answered" not in captured.err  # a short drop that recovers is silent
    assert len(calls) == 3 and all("after=17&" in query for query in calls)
    assert clock.sleeps == [2, 4]
    assert state.load_state(joined)["cursor"] == 18
    assert not (joined / cli.OUTAGE_FILE).exists()


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
    # failed reads at 0, 2, 6, 14 and 30 s; the minute passes during the last backoff, and
    # the line comes before the window is rested out, not only at a next failed read
    assert captured.err.count("retrying until the timeout") == 1
    assert (
        "hub answered 503 since 2026-11-17T10:00:00Z, still at 2026-11-17T10:01:00Z; "
        "retrying until the timeout" in captured.err
    )
    saved = state.load_state(joined, cli.OUTAGE_FILE)
    assert saved["since"] == "2026-11-17T10:00:00Z" and saved["reported"] is True


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
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


def test_wait_on_429_waits_at_least_retry_after_within_the_deadline(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    replies = iter(
        [
            (429, "Too Many Requests", {"Retry-After": "7"}),  # longer than the back-off
            (429, "Too Many Requests", {"Retry-After": "1"}),  # shorter: the back-off wins
            (429, "Too Many Requests", {}),  # none at all, as from a limit on open requests
            (429, "Too Many Requests", {"Retry-After": "3600"}),  # beyond the deadline
        ]
    )
    calls: list[str] = []

    def response(seen: fakehub.Seen) -> Any:
        calls.append(seen.query)
        return next(replies)

    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = response
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_TIMEOUT
    # 7 (Retry-After), 4 (back-off), 8 (back-off), then the rest up to the deadline:
    # 60 less the 5 seconds kept for the unread-chats note
    assert clock.sleeps == [7, 4, 8, 36]
    assert all("after=17&" in query for query in calls)
    assert state.load_state(joined)["cursor"] == 17
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "hub answered" not in captured.err  # failures over 19 s: no outage yet


def test_wait_on_database_unavailable_waits_at_least_retry_after(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 503 `database_unavailable` (§1.3: unreachable or a used-up pool) carries Retry-After;
    the wait keeps it like a 429's, never past the deadline, and reads on with the same cursor."""
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    busy = {"error": {"code": "database_unavailable", "message": "the database is unreachable"}}
    replies = iter(
        [
            (503, busy, {"Retry-After": "5"}),  # longer than the first back-off
            (503, busy, {"Retry-After": "1"}),  # shorter: the back-off wins
            (503, busy, {"Retry-After": "3600"}),  # beyond the deadline
        ]
    )
    calls: list[str] = []

    def response(seen: fakehub.Seen) -> Any:
        calls.append(seen.query)
        return next(replies)

    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = response
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_TIMEOUT
    # 5 (Retry-After), 4 (back-off), then the rest up to the deadline less the note's 5 seconds
    assert clock.sleeps == [5, 4, 46]
    assert all("after=17&" in query for query in calls)
    assert state.load_state(joined)["cursor"] == 17
    assert "hub answered" not in capsys.readouterr().err  # failures over 9 s: no outage yet


def test_wait_on_another_5xx_keeps_its_back_off_whatever_retry_after(
    joined: Path, fake: fakehub.FakeHub, clock: Clock
) -> None:
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    replies = iter(
        [(502, "Bad Gateway", {"Retry-After": "40"}), (200, {"items": [], "cursor": 17})]
    )
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda seen: next(replies)
    cli.main(["wait", "--timeout", "60"])
    assert clock.sleeps[0] == 2


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


def _events_calls(monkeypatch: pytest.MonkeyPatch, answer: Any) -> list[tuple[int, float | None]]:
    """Route the events long-polls through `answer(wait)`; the (wait, read timeout) of each."""
    calls: list[tuple[int, float | None]] = []
    real = hub.Client.call

    def call(
        self: hub.Client,
        method: str,
        path: str,
        query: Any = (),
        body: Any = None,
        timeout: float | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not path.endswith("/events"):
            return real(self, method, path, query, body, timeout, *args, **kwargs)
        wait = int(dict(query)["wait"])
        calls.append((wait, timeout))
        return answer(wait)

    monkeypatch.setattr(hub.Client, "call", call)
    return calls


def test_every_poll_leaves_the_hub_time_to_answer(
    joined: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def answer(wait: int) -> dict[str, Any]:
        clock.now += wait  # the hub holds the full poll, then answers empty
        return {"items": [], "cursor": 0}

    calls = _events_calls(monkeypatch, answer)
    assert cli.main(["wait", "--timeout", "120"]) == cli.EXIT_TIMEOUT
    # 115 s until the note's reserve, 10 s of slack each: the last 10 s are rested out
    # rather than spent on short polls the hub could not answer in time
    assert calls == [(55, 70), (50, 60)]
    assert clock.sleeps == [10]


def test_a_short_window_still_polls_once(
    joined: Path, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    def answer(wait: int) -> dict[str, Any]:
        clock.now += wait
        return {"items": [], "cursor": 0}

    calls = _events_calls(monkeypatch, answer)
    assert cli.main(["wait", "--timeout", "1"]) == cli.EXIT_TIMEOUT
    assert calls == [(1, 0.75)]


def test_the_last_read_running_out_is_a_quiet_timeout(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def answer(wait: int) -> dict[str, Any]:
        clock.now = 55  # the hub is slow: the read runs out at the deadline
        raise hub.HubError("timed out", status=None)

    _events_calls(monkeypatch, answer)
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_TIMEOUT
    assert "connection lost" not in capsys.readouterr().err
    assert clock.sleeps == []


def test_a_disconnect_shorter_than_the_outage_threshold_is_silent(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def answer(wait: int) -> dict[str, Any]:
        clock.now += 1
        raise hub.HubError("reset", status=None)

    _events_calls(monkeypatch, answer)
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_TIMEOUT
    # failed reads at 1, 4, 9, 18 and 35 s: 34 s without an answer, under OUTAGE_AFTER
    assert "connection lost" not in capsys.readouterr().err


def test_a_disconnect_of_a_minute_is_reported_with_utc_times(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def answer(wait: int) -> dict[str, Any]:
        clock.now += 1
        raise hub.HubError("reset", status=None)

    _events_calls(monkeypatch, answer)
    assert cli.main(["wait", "--timeout", "120"]) == cli.EXIT_TIMEOUT
    err = capsys.readouterr().err
    # failed reads at 1, 4, 9, 18 and 35 s, then a backoff to 65 s: 64 s after the first
    assert err.count("hub connection lost since") == 1
    assert (
        "hub connection lost since 2026-11-17T10:00:01Z, still at 2026-11-17T10:01:05Z; "
        "retrying until the timeout" in err
    )


def _down_then(
    clock: Clock, monkeypatch: pytest.MonkeyPatch, down: float, page: dict[str, Any]
) -> list[int]:
    """Events polls that drop until `down` seconds on the clock, then answer `page`; the
    `after` of each poll."""
    afters: list[int] = []
    real = hub.Client.call

    def call(
        self: hub.Client,
        method: str,
        path: str,
        query: Any = (),
        body: Any = None,
        timeout: float | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if not path.endswith("/events"):
            return real(self, method, path, query, body, timeout, *args, **kwargs)
        afters.append(int(dict(query)["after"]))
        clock.now += 1
        if clock.now < down:
            raise hub.HubError("reset", status=None)
        return page

    monkeypatch.setattr(hub.Client, "call", call)
    return afters


def test_an_outage_is_counted_across_waits_and_its_end_is_reported(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Three short waits during one outage: the third reaches a minute without an answer and
    says so, the wait after it reads on from the same cursor and says the hub is back."""
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    event = {"seq": 18, "kind": "message", "payload": {"type": "notice", "body": "hi"}}
    _down_then(clock, monkeypatch, 1000, {"items": [event], "cursor": 18})
    # waits of 30 s, each ending 25 s in: the first two stay under a minute since 10:00:01
    for _ in range(2):
        assert cli.main(["wait", "--timeout", "30"]) == cli.EXIT_TIMEOUT
        assert "connection lost" not in capsys.readouterr().err
    saved = state.load_state(joined, cli.OUTAGE_FILE)
    assert saved["since"] == "2026-11-17T10:00:01Z" and saved["reported"] is False
    # the third fails at 51, 54 and 59 s; the minute passes in the backoff after that
    assert cli.main(["wait", "--timeout", "30"]) == cli.EXIT_TIMEOUT
    err = capsys.readouterr().err
    assert err.count("hub connection lost since") == 1
    assert "hub connection lost since 2026-11-17T10:00:01Z, still at 2026-11-17T10:01:07Z" in err
    afters = _down_then(clock, monkeypatch, 0, {"items": [event], "cursor": 18})  # back
    clock.now = 100
    assert cli.main(["wait", "--timeout", "30"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert (
        "hub answering again at 2026-11-17T10:01:41Z, unreachable since 2026-11-17T10:00:01Z"
        in captured.err
    )
    assert [e["seq"] for e in json.loads(captured.out)] == [18]
    assert afters == [17]  # the cursor it had before the outage: nothing lost, nothing twice
    assert state.load_state(joined)["cursor"] == 18
    assert not (joined / cli.OUTAGE_FILE).exists()


def test_a_stale_outage_clock_starts_afresh(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A clock whose last failure is more than OUTAGE_AFTER old (a wait killed in an outage)
    does not make the next short drop an outage, and its end is not announced."""
    state.save_state(
        joined,
        {"since": "2026-11-17T08:00:00Z", "last": "2026-11-17T09:58:59Z", "reported": True},
        cli.OUTAGE_FILE,
    )
    _down_then(clock, monkeypatch, 3, {"items": [{"seq": 5, "kind": "message"}], "cursor": 5})
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    err = capsys.readouterr().err
    assert "connection lost" not in err and "answering again" not in err
    assert not (joined / cli.OUTAGE_FILE).exists()


def test_a_fresh_outage_clock_reports_on_the_first_failure_of_the_next_wait(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    state.save_state(
        joined,
        {"since": "2026-11-17T09:58:00Z", "last": "2026-11-17T09:59:50Z", "reported": True},
        cli.OUTAGE_FILE,
    )
    _down_then(clock, monkeypatch, 1000, {"items": [], "cursor": 0})
    assert cli.main(["wait", "--timeout", "10"]) == cli.EXIT_TIMEOUT
    err = capsys.readouterr().err
    line = "hub connection lost since 2026-11-17T09:58:00Z, still at 2026-11-17T10:00:01Z"
    assert err.count(line) == 1


@pytest.mark.parametrize("content", [b"not json", b"\xff"], ids=["not json", "not UTF-8"])
def test_a_broken_outage_file_costs_the_wait_nothing(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    content: bytes,
) -> None:
    path = joined / cli.OUTAGE_FILE
    path.write_bytes(content)
    path.chmod(0o600)  # private, so the read gets as far as the content
    _down_then(clock, monkeypatch, 3, {"items": [{"seq": 5, "kind": "message"}], "cursor": 5})
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert [e["seq"] for e in json.loads(captured.out)] == [5]
    assert "connection lost" not in captured.err


def _wall_jumps(clock: Clock, monkeypatch: pytest.MonkeyPatch, at: float, jump: float) -> None:
    """The wall clock moves with the monotonic one, and jumps by `jump` seconds once the
    monotonic clock reaches `at`."""
    monkeypatch.setattr(
        cli,
        "_utc_now",
        lambda: EPOCH + timedelta(seconds=clock.now + (jump if clock.now >= at else 0)),
    )


def test_a_forward_wall_clock_jump_makes_no_outage_of_a_short_drop(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _wall_jumps(clock, monkeypatch, 2, 3600)  # 10:00 -> 11:00 before the second failed read
    _down_then(clock, monkeypatch, 1000, {"items": [], "cursor": 0})
    assert cli.main(["wait", "--timeout", "30"]) == cli.EXIT_TIMEOUT
    # failed reads at 1, 4, 9 and 18 s of the monotonic clock: 17 s, no outage
    assert "connection lost" not in capsys.readouterr().err


def test_a_backward_wall_clock_jump_does_not_start_the_clock_afresh(
    joined: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _wall_jumps(clock, monkeypatch, 30, -3600)  # back an hour before the read at 35 s
    _down_then(clock, monkeypatch, 1000, {"items": [], "cursor": 0})
    assert cli.main(["wait", "--timeout", "120"]) == cli.EXIT_TIMEOUT
    err = capsys.readouterr().err
    # failed reads at 1, 4, 9, 18 and 35 s, then a backoff to 65 s: reported there, 64 s after
    # the first, its time named on the wall clock as it reads now
    assert err.count("hub connection lost since") == 1
    assert "hub connection lost since 2026-11-17T09:00:01Z, still at 2026-11-17T09:01:05Z" in err


@pytest.mark.parametrize(("named", "warned"), [("99.0.0", True), ("0.0.1", False), (None, False)])
def test_wait_warns_once_when_the_hub_names_a_newer_cli(
    joined: Path,
    fake: fakehub.FakeHub,
    capsys: pytest.CaptureFixture[str],
    named: str | None,
    warned: bool,
) -> None:
    page = {
        "items": [{"seq": 5, "kind": "ticker", "payload": {}}],
        "cursor": 5,
        "cli_version": named,
    }
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda seen: (200, page)
    assert cli.main(["wait"]) == cli.EXIT_OK
    err = capsys.readouterr().err
    assert ("pipx upgrade maity" in err) is warned
    assert err.count("pipx upgrade maity") == int(warned)


def test_wait_escapes_what_can_hide_text_and_keeps_other_languages(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    body = "für 日本語 a\u202eb\u2028c\u0085d\U000e0041e"
    event = {"seq": 18, "kind": "message", "payload": {"body": body}}
    answer = {"items": [event], "cursor": 18}
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda s: (200, answer)
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert json.loads(captured.out)[0]["payload"]["body"] == body
    assert "für 日本語" in captured.out
    assert not any(c in captured.out for c in "\u202e\u2028\u0085\U000e0041")
    assert cli.DATA_NOTE in captured.err


def test_wait_says_nothing_about_data_without_a_message(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    answer = {"items": [{"seq": 18, "kind": "task_updated"}], "cursor": 18}
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda s: (200, answer)
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    assert cli.DATA_NOTE not in capsys.readouterr().err


WINDOW = {
    "error": {
        "code": "maintenance",
        "message": "the hub is in a maintenance window",
        "details": {"from": "2026-11-02T13:00:00Z", "until": "2026-11-02T13:30:00Z", "text": "DB"},
    }
}


def test_wait_sleeps_a_maintenance_window_out_and_reads_on(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("random.random", lambda: 0.25)
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    calls: list[str] = []

    def response(seen: fakehub.Seen) -> tuple[Any, ...]:
        calls.append(seen.query)
        if len(calls) <= 2:
            return 503, WINDOW, {"Retry-After": "120"}
        return 200, {"items": [{"seq": 18, "kind": "message"}], "cursor": 18}

    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = response
    assert cli.main(["wait", "--timeout", "600"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert [e["seq"] for e in json.loads(captured.out)] == [18]
    assert captured.err.count("Maintenance until 2026-11-02 13:30 UTC: DB") == 1  # once
    assert clock.sleeps == [120 + 15, 120 + 15]  # Retry-After plus 0.25 × 60
    assert all("after=17&" in query for query in calls)


def test_wait_never_sleeps_a_window_past_its_timeout(
    joined: Path, fake: fakehub.FakeHub, clock: Clock, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda seen: (
        503,
        WINDOW,
        {"Retry-After": "1800"},
    )
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_TIMEOUT  # never 7
    assert clock.now <= 60
    assert "Maintenance until 2026-11-02 13:30 UTC" in capsys.readouterr().err


def test_other_commands_exit_7_in_a_window(
    joined: Path, fake: fakehub.FakeHub, capsys: pytest.CaptureFixture[str]
) -> None:
    fake.routes[("POST", "/api/v1/me/resume")] = lambda seen: (
        503,
        WINDOW,
        {"Retry-After": "1800"},
    )
    assert cli.main(["resume"]) == cli.EXIT_MAINTENANCE == 7
    err = capsys.readouterr().err
    assert "Maintenance until 2026-11-02 13:30 UTC, try again then" in err


def test_an_end_that_is_no_timestamp_is_not_echoed() -> None:
    error = hub.HubError("x", code="maintenance", status=503)
    error.details = {"until": "\x1b[2Jsoon"}
    assert hub.maintenance_until(error) == "its end"
    assert hub.maintenance_until(hub.HubError("x", code="internal", status=503)) is None


def test_wait_for_a_handle_sleeps_a_window_out_while_resolving_it(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--for <handle>` looks the handle up with a call of its own; a window answering that
    call is slept out like one answering the poll, never exit 7 (§13)."""
    from test_bridge_for import SERVED

    monkeypatch.setattr("random.random", lambda: 0.0)
    lookups: list[str] = []

    def members(seen: fakehub.Seen) -> tuple[Any, ...]:
        lookups.append(seen.path)
        if len(lookups) == 1:
            return 503, WINDOW, {"Retry-After": "120"}
        return 200, {"items": [*fakehub.MEMBERS, SERVED], "next_cursor": None}

    fake.routes[("GET", "/api/v1/projects/oliver/maity/members")] = members
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda seen: (
        200,
        {"items": [{"seq": 4, "kind": "message"}], "cursor": 4},
    )
    assert cli.main(["--for", "designer", "wait", "--timeout", "600"]) == cli.EXIT_OK
    assert len(lookups) == 2 and clock.sleeps == [120]
    assert "Maintenance until 2026-11-02 13:30 UTC" in capsys.readouterr().err


def test_a_window_text_with_terminal_escapes_reaches_the_terminal_disarmed(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The window's `text` is the hub's (§16.12): it goes through `onboarding.inline`, so a
    control character or an escape sequence in it never reaches the terminal as one."""
    monkeypatch.setattr("random.random", lambda: 0.0)
    window = json.loads(json.dumps(WINDOW))
    window["error"]["details"]["text"] = "DB\x1b[2J\x07\nnext line\x9b31m"
    calls: list[str] = []

    def response(seen: fakehub.Seen) -> tuple[Any, ...]:
        calls.append(seen.query)
        if len(calls) == 1:
            return 503, window, {"Retry-After": "1"}
        return 200, {"items": [{"seq": 18, "kind": "message"}], "cursor": 18}

    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = response
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    line = next(ln for ln in capsys.readouterr().err.splitlines() if "Maintenance until" in ln)
    assert "DB" in line and "next line" in line
    assert not any(c in line for c in ("\x1b", "\x07", "\x9b", "\r"))


def test_a_window_without_retry_after_sleeps_60_seconds_plus_jitter(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `503 maintenance` without `Retry-After` (hub.py `maintenance_sleep`): 60 s, plus a
    random 0–60 s."""
    monkeypatch.setattr("random.random", lambda: 0.25)
    calls: list[str] = []

    def response(seen: fakehub.Seen) -> tuple[Any, ...]:
        calls.append(seen.query)
        if len(calls) == 1:
            return 503, WINDOW
        return 200, {"items": [{"seq": 18, "kind": "message"}], "cursor": 18}

    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = response
    assert cli.main(["wait", "--timeout", "600"]) == cli.EXIT_OK
    assert clock.sleeps == [60 + 15]
    assert (
        hub.maintenance_sleep(hub.HubError("x", code="maintenance", status=503), lambda: 0.5) == 90
    )


# --- where N comes from (§13) ----------------------------------------------------------------


def _outage(fake: fakehub.FakeHub) -> None:
    fake.routes[("GET", "/api/v1/projects/oliver/maity/events")] = lambda seen: (503, "unavailable")


@pytest.mark.parametrize(
    ("flag", "env", "hint", "ends_at"),
    [
        (["--timeout", "40"], "300", 200, 35),  # the flag wins
        ([], "300", 200, 295),  # then the variable
        ([], " 300 ", 200, 295),  # spaces around it are no error
        ([], "", 200, 195),  # set but empty: unset
        ([], None, 200, 195),  # then the hub's hint
        ([], None, None, 595),  # then 600
        ([], None, 9000, 7195),  # a hint beyond the cap is taken at the cap
        ([], None, 7201, 7195),
        # A hint that is not a positive whole number is the hub's mistake: ignored, never
        # refused (§13); `true` counts as no number, though Python takes it for 1.
        ([], None, 0, 595),
        ([], None, -1, 595),
        ([], None, "200", 595),
        ([], None, 1.5, 595),
        ([], None, False, 595),
        ([], None, True, 595),
    ],
)
def test_wait_takes_n_from_the_flag_the_variable_the_hint_or_600(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    flag: list[str],
    env: str | None,
    hint: object,
    ends_at: int,
) -> None:
    data = {k: v for k, v in state.load_state(joined).items() if k != "wait_timeout"}
    state.save_state(joined, data if hint is None else {**data, "wait_timeout": hint})
    if env is None:
        monkeypatch.delenv(cli.WAIT_ENV, raising=False)
    else:
        monkeypatch.setenv(cli.WAIT_ENV, env)
    _outage(fake)
    assert cli.main(["wait", *flag]) == cli.EXIT_TIMEOUT
    assert clock.now == ends_at  # N less the reserve for the unread-chats note


@pytest.mark.parametrize(
    ("flag", "env", "message"),
    [
        (["--timeout", "0"], None, "--timeout must be 1 to 7200 seconds, not 0"),
        (["--timeout", "7201"], None, "--timeout must be 1 to 7200 seconds, not 7201"),
        ([], "1800000", "MAITY_WAIT_TIMEOUT must be 1 to 7200 seconds, not 1800000"),
        ([], "-5", "MAITY_WAIT_TIMEOUT must be 1 to 7200 seconds, not -5"),
        ([], "30s", "MAITY_WAIT_TIMEOUT must be a whole number of seconds, not '30s'"),
        ([], "1.5", "MAITY_WAIT_TIMEOUT must be a whole number of seconds, not '1.5'"),
    ],
)
def test_wait_refuses_n_outside_its_range_naming_the_source(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    flag: list[str],
    env: str | None,
    message: str,
) -> None:
    if env is None:
        monkeypatch.delenv(cli.WAIT_ENV, raising=False)
    else:
        monkeypatch.setenv(cli.WAIT_ENV, env)
    _outage(fake)
    assert cli.main(["wait", *flag]) == cli.EXIT_USAGE
    assert message in capsys.readouterr().err
    assert clock.now == 0 and fake.seen == []  # refused before any call


def test_wait_bounds_hold_at_both_ends(
    joined: Path, fake: fakehub.FakeHub, clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(cli.WAIT_ENV, "7200")
    _outage(fake)
    assert cli.main(["wait"]) == cli.EXIT_TIMEOUT
    assert clock.now == 7195
    assert cli.main(["wait", "--timeout", "1"]) == cli.EXIT_TIMEOUT


@pytest.mark.parametrize(
    ("hint", "ends_at"),
    [(300, 295), (True, 595), (False, 595), (0, 595), (-1, 595), ("200", 595), (1.5, 595)]
    + [(None, 595), ("missing", 595), ("no hints", 595)],
)
def test_each_resume_replaces_the_hint_an_invalid_one_falls_back_to_600(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    hint: object,
    ends_at: int,
) -> None:
    """Review of #1491: an earlier valid hint (120) must not survive a resume whose packet
    brings an invalid one or none; through the real resume, then wait (§13)."""
    monkeypatch.delenv(cli.WAIT_ENV, raising=False)
    state.save_state(joined, {**state.load_state(joined), "wait_timeout": 120})
    packet: dict[str, Any] = {"session": {"id": "ses-b-0005"}, "hints": {}}
    if hint == "no hints":  # an older hub's packet, without the object at all
        del packet["hints"]
    elif hint != "missing":  # a key left out, as a supervised session's packet does (§15.11)
        packet["hints"]["wait_timeout"] = hint
    fake.routes[("POST", "/api/v1/me/resume")] = lambda seen: (200, packet)
    assert cli.main(["resume"]) == cli.EXIT_OK
    _outage(fake)
    assert cli.main(["wait"]) == cli.EXIT_TIMEOUT
    assert clock.now == ends_at


@pytest.mark.parametrize("answer", [(503, "unavailable"), (200, ["not", "an", "object"])])
def test_a_failed_resume_keeps_the_last_successful_hint(
    joined: Path,
    fake: fakehub.FakeHub,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    answer: tuple[int, Any],
) -> None:
    """A resume that fails stores nothing: the hint stays the last successful resume's, as
    cli/context/commands.md cff2a54d says."""
    monkeypatch.delenv(cli.WAIT_ENV, raising=False)
    state.save_state(joined, {**state.load_state(joined), "wait_timeout": 120})
    fake.routes[("POST", "/api/v1/me/resume")] = lambda seen: answer
    assert cli.main(["resume"]) != cli.EXIT_OK
    assert state.load_state(joined)["wait_timeout"] == 120


class RawHub:
    """A hub on a loopback socket, inside the test, that answers each connection with the
    next scripted reply as raw bytes and closes it, so an answer can break off where
    urllib and http.client really see it: a status line, headers or a body cut short.
    After the script, `last` is sent to every further request."""

    def __init__(self, replies: list[bytes], last: bytes) -> None:
        self.replies = list(replies)
        self.last = last
        self.requests: list[str] = []
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                self.requests.append(data.split(b"\r\n", 1)[0].decode("latin-1"))
                conn.sendall(self.replies.pop(0) if self.replies else self.last)
                conn.shutdown(socket.SHUT_WR)

    def close(self) -> None:
        # A close alone does not wake a thread blocked in accept() on Linux, and a later test's
        # socket can reuse the descriptor: shut it down first, then wait for the thread.
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()


def _ok(body: Any) -> bytes:
    data = json.dumps(body).encode()
    head = f"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n"
    return head.encode() + b"\r\n" + data


@pytest.fixture
def raw(joined: Path) -> Iterator[Any]:
    """`raw(replies, last)` starts a RawHub and points the joined clone at it."""
    hubs: list[RawHub] = []

    def start(replies: list[bytes], last: bytes) -> RawHub:
        made = RawHub(replies, last)
        hubs.append(made)
        state.save_state(joined, {**state.load_state(joined), "hub": made.url})
        return made

    yield start
    for made in hubs:
        made.close()


BROKEN = {
    "body cut, Content-Length": b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
    b'Content-Length: 100\r\n\r\n{"items": [',
    "body cut, chunked": b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
    b'Transfer-Encoding: chunked\r\n\r\n40\r\n{"items": [',
    "status line cut": b"HTTP/1.1 20",
    "a 503's body cut, chunked": b"HTTP/1.1 503 Service Unavailable\r\n"
    b'Transfer-Encoding: chunked\r\n\r\n40\r\n{"error": ',
    "headers cut": b"HTTP/1.1 200 OK\r\nContent-Ty",
    "an empty 200": b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n",
    "a 200 that is no object": _ok([]),
}


@pytest.mark.parametrize("broken", BROKEN.values(), ids=BROKEN.keys())
def test_an_answer_that_breaks_off_is_retried_from_the_same_cursor(
    joined: Path, clock: Clock, raw: Any, capsys: pytest.CaptureFixture[str], broken: bytes
) -> None:
    state.save_state(joined, {**state.load_state(joined), "cursor": 17})
    page = {"items": [{"seq": 18, "kind": "message"}], "cursor": 18}
    served = raw([broken], _ok(page))
    assert cli.main(["wait", "--timeout", "60"]) == cli.EXIT_OK
    captured = capsys.readouterr()
    assert [e["seq"] for e in json.loads(captured.out)] == [18]
    events = [r for r in served.requests if "/events?" in r]
    assert len(events) == 2 and all("after=17&" in r for r in events)
    assert "connection lost" not in captured.err and "hub answered" not in captured.err
    assert state.load_state(joined)["cursor"] == 18


def test_a_page_that_is_no_object_keeps_the_outage_clock(
    joined: Path, clock: Clock, raw: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 200 that is no page is no answer: it neither ends a running outage (no recovery line,
    the clock kept) nor is taken as events."""
    clock_file = {"since": "2026-11-17T09:59:30Z", "last": "2026-11-17T09:59:59Z"}
    state.save_state(joined, {**clock_file, "reported": True}, cli.OUTAGE_FILE)
    raw([], _ok([]))
    assert cli.main(["wait", "--timeout", "10"]) == cli.EXIT_TIMEOUT
    captured = capsys.readouterr()
    assert captured.out == "" and "answering again" not in captured.err
    assert state.load_state(joined, cli.OUTAGE_FILE)["since"] == "2026-11-17T09:59:30Z"


def test_another_command_fails_once_on_an_answer_that_breaks_off(
    joined: Path, raw: Any, capsys: pytest.CaptureFixture[str]
) -> None:
    served = raw([], BROKEN["body cut, Content-Length"])
    assert cli.main(["messages"]) == cli.EXIT_ERROR
    assert "broke off its answer (IncompleteRead)" in capsys.readouterr().err
    assert len(served.requests) == 1
