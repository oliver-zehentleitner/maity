"""docs/api.md §5.3: one presence table (`seen.presence_by_age`) for members, instances and
runners, and the one nullable RFC 3339 time (`clock.rfc3339_or_none`) every view writes."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from maity_hub import clock, instances, runners, views
from maity_hub.seen import AWAY, ONLINE, SEEN_EVERY, presence_by_age

NOW = datetime(2026, 11, 18, 12, 0, 0, tzinfo=UTC)
TICK = timedelta(microseconds=1)


@pytest.mark.parametrize(
    ("age", "shown"),
    [
        (-timedelta(seconds=5), "online"),
        (timedelta(0), "online"),
        (ONLINE, "online"),
        (ONLINE + TICK, "away"),
        (AWAY, "away"),
        (AWAY + TICK, "offline"),
        (timedelta(days=3), "offline"),
    ],
)
def test_the_table_reads_both_windows_inclusive(age: timedelta, shown: str) -> None:
    assert (timedelta(seconds=120), timedelta(hours=2)) == (ONLINE, AWAY)
    assert presence_by_age(age) == shown


def test_a_member_reads_from_its_latest_call_an_instance_or_runner_from_the_stored_one() -> None:
    """A member's `last_seen_at` is throttled, so it reads a minute later (§2.4); a credential's
    `last_used_at` and a runner's `last_seen_at` are written on every call and read as stored."""
    clock.set_source(lambda: NOW)
    stored = NOW - ONLINE - SEEN_EVERY + timedelta(seconds=10)  # 170 s ago
    member = SimpleNamespace(paused_since=None, agent_id=None, last_seen_at=stored)
    assert views.presence(member, None, False) == "online"
    assert instances.presence(stored, True, False) == "away"
    assert runners.presence(SimpleNamespace(last_seen_at=stored), False) == "away"
    gone = NOW - AWAY - TICK
    member.last_seen_at = gone
    assert views.presence(member, None, False) == "away"
    assert instances.presence(gone, True, False) == "offline"
    assert runners.presence(SimpleNamespace(last_seen_at=gone), False) == "offline"
    assert instances.presence(None, True, True) == "online"  # listening wins
    assert instances.presence(stored, False, False) == "offline"  # no live session


def test_a_nullable_time_is_rfc3339_in_utc_or_none() -> None:
    assert clock.rfc3339_or_none(None) is None
    assert clock.rfc3339_or_none(NOW + timedelta(microseconds=999_999)) == "2026-11-18T12:00:00Z"
    vienna = timezone(timedelta(hours=1))
    assert clock.rfc3339_or_none(datetime(2026, 11, 18, 13, 0, tzinfo=vienna)) == (
        "2026-11-18T12:00:00Z"
    )
    assert views.ts is clock.rfc3339_or_none
    for moment in (NOW, datetime(1970, 1, 1, tzinfo=UTC), None):
        expected = clock.rfc3339(moment) if moment is not None else None
        assert clock.rfc3339_or_none(moment) == expected
