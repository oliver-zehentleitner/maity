"""Shared UTC stamp formatter and parser (tsk-d2zhcxhg10b5)."""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from maity import cli, hub, stamp
from maity.runner import keeper, scratch, serve, supervisor, watch

T0 = int(datetime(2026, 11, 20, 20, 26, tzinfo=UTC).timestamp())
WIRE = "2026-11-20T20:26:00Z"


def test_stamp_formats_a_float_a_datetime_and_none_as_now() -> None:
    assert stamp.stamp(0) == "1970-01-01T00:00:00Z"
    assert stamp.stamp(59.9) == "1970-01-01T00:00:59Z"
    assert stamp.stamp(T0) == WIRE
    at = datetime(2026, 11, 20, 22, 26, 0, tzinfo=timezone(timedelta(hours=2)))
    assert stamp.stamp(at) == WIRE
    naive = datetime(2026, 11, 20, 20, 26, 0, 123456)
    assert stamp.stamp(naive) == naive.astimezone(UTC).strftime(stamp.FORMAT)
    before, got, after = int(time.time()), stamp.stamp(), int(time.time())
    assert got in {stamp.stamp(float(t)) for t in range(before, after + 1)}


def test_parse_stamp_accepts_z_without_rewriting_it() -> None:
    at = stamp.parse_stamp(WIRE)
    assert at == datetime(2026, 11, 20, 20, 26, tzinfo=UTC)
    assert stamp.parse_stamp("2026-11-20T20:26:00+00:00") == at
    assert stamp.parse_stamp("2026-11-20T22:26:00+02:00") == at
    assert stamp.parse_stamp("2026-11-20T20:26:00.5Z") == datetime(
        2026, 11, 20, 20, 26, 0, 500000, tzinfo=UTC
    )
    assert stamp.parse_stamp("2026-11-20t20:26:00Z") == at
    assert stamp.parse_stamp("2026-11-20 20:26:00Z") == at


def test_low_year_stamp_round_trips_through_strict_parser_and_cli() -> None:
    at = datetime(1, 1, 2, 3, 4, 5, tzinfo=UTC)
    expected = "0001-01-02T03:04:05Z"
    written = stamp.stamp(at)
    assert written == expected
    assert stamp.parse_stamp(written, strict=True) == at
    assert cli.limit_until(expected, now=0) == expected


def test_parse_stamp_rejects_a_non_string_a_naive_value_and_junk() -> None:
    for value in (
        None,
        T0,
        "",
        "soon",
        "2026-11-20T20:26:00",
        "2026-11-20T20:26:00z",
        "2026-13-01T00:00:00Z",
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
    ):
        assert stamp.parse_stamp(value) is None


def test_parse_stamp_strict_is_the_wire_form_only() -> None:
    assert stamp.parse_stamp(WIRE, strict=True) == datetime(2026, 11, 20, 20, 26, tzinfo=UTC)
    for value in (
        "2026-11-20T20:26:00+00:00",
        "2026-11-20T20:26:00.5Z",
        "2026-11-20 20:26:00Z",
        "2026-11-20t20:26:00Z",
        "2026-11-20T20:26:00z",
        "2026-13-01T00:00:00Z",
        T0,
        None,
    ):
        assert stamp.parse_stamp(value, strict=True) is None


def test_cli_aliases_use_the_shared_helpers() -> None:
    at = datetime(2026, 11, 20, 20, 26, tzinfo=UTC)
    assert cli._utc(at) == WIRE
    assert cli._parse_utc(WIRE) == at
    assert cli._parse_utc("2026-11-20T20:26:00") is None


def test_cli_time_still_accepts_lowercase_and_drops_fractions() -> None:
    assert cli.limit_until("2026-10-22t17:00:00z", now=0) == "2026-10-22T17:00:00Z"
    assert cli.limit_until("2026-10-22T17:00:00.9Z", now=0) == "2026-10-22T17:00:00Z"
    assert cli.limit_until("90m", now=0) == "1970-01-01T01:30:00Z"


def test_hub_server_time_rejects_a_naive_stamp() -> None:
    # Behaviour change: the old copy called .timestamp() on a naive fromisoformat
    # result, which is local time. parse_stamp rejects a value with no offset.
    assert hub._parse_server_time("2026-11-20T20:26:00") is None
    assert hub._parse_server_time(WIRE) == float(T0)
    assert hub._parse_server_time("2026-11-20T20:26:00+00:00") == float(T0)
    assert hub._parse_server_time(None) is None
    assert hub._parse_server_time(T0) is None


def test_supervisor_stamp_none_is_missing_not_now() -> None:
    assert supervisor.stamp(None) is None
    assert supervisor.stamp(T0) == WIRE
    assert serve.utc(T0) == WIRE
    assert serve.utc(0) == "1970-01-01T00:00:00Z"
    before, written, after = int(time.time()), serve.utc(), int(time.time())
    assert written in {stamp.stamp(float(t)) for t in range(before, after + 1)}


def test_keeper_age_requires_canonical_persisted_stamps() -> None:
    assert keeper._age("1970-01-01T00:00:00Z", 10.0) == 10.0
    assert keeper._age(WIRE, T0 + 30) == 30.0
    assert keeper.stamp(T0) == WIRE
    for text in (
        None,
        "",
        "2026-11-20T20:26:00+00:00",
        "2026-11-20T20:26:00.5Z",
        "2026-11-20t20:26:00z",
        "2026-1-2T3:4:5Z",
        "soon",
    ):
        assert keeper._age(text, T0) is None


def test_watch_parse_stamp_stays_strict_and_returns_a_float() -> None:
    assert watch.parse_stamp(WIRE) == float(T0)
    assert watch.stamp(T0) == WIRE
    assert watch.parse_stamp("2026-11-20T20:26:00+00:00") is None
    assert watch.parse_stamp("2026-11-20T20:26:00.5Z") is None


def test_scratch_log_removal_uses_the_shared_stamp(tmp_path: Path) -> None:
    entry = scratch.log_removal(
        tmp_path,
        "plc-0001",
        Path("/w/.scratch/plc-0001"),
        8,
        "closed",
        at=T0,
    )
    assert entry["at"] == WIRE
