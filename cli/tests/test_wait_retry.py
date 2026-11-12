from __future__ import annotations

import json
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


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    clock = Clock()
    monkeypatch.setattr(cli, "time", clock)
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
    assert captured.err.count("hub answered 429, retrying until the timeout") == 1


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
    assert capsys.readouterr().err.count("hub answered 503, retrying until the timeout") == 1


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


def test_a_disconnect_before_the_deadline_still_warns(
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
    assert capsys.readouterr().err.count("hub connection lost, retrying until the timeout") == 1


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
