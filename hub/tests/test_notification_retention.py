"""What the account records and the mail's bookkeeping keep, and the hourly sweep that deletes
the rest (docs/api.md §18.1, §18.2, §16.2; `notifications.retention`)."""

from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, func, insert, select

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from maity_hub.notifications import records, retention
from tests import factory
from tests import test_notification_mail as mail_tests
from tests.conftest import ClientFactory
from tests.test_notification_address import mail_env, outbox_rows

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def now() -> datetime:
    clock.set_source(lambda: NOW)
    return NOW


def _at(moment: datetime) -> None:
    clock.set_source(lambda: moment)


def _record(engine: Engine, human_id: str, kind: str, days: float, **data: Any) -> int:
    """A record written `days` before `NOW`; the clock goes back to `NOW`."""
    _at(NOW - timedelta(days=days))
    try:
        with engine.begin() as conn:
            return records.write(conn, human_id, kind, data)
    finally:
        _at(NOW)


def _numbers(engine: Engine) -> set[int]:
    with engine.begin() as conn:
        return set(conn.execute(select(t.account_record.c.n)).scalars())


def _settings(engine: Engine, human_id: str, status: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(t.notification_settings).values(
                human_id=human_id,
                preferences={},
                address=f"{human_id}@example.org",
                address_status=status,
                epoch=0,
                hard_failures=0,
                updated_at=clock.now(),
            )
        )


def _registration(engine: Engine, human_id: str, status: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(t.account_registration).values(
                human_id=human_id,
                created_at=clock.now(),
                expires_at=clock.now() + timedelta(days=30),
                status=status,
            )
        )


# --- account records -------------------------------------------------------------------


def test_records_past_ninety_days_and_a_day_go_the_newer_stay(migrated: Engine, now: Any) -> None:
    me = factory.human(migrated)
    old = _record(migrated, me, records.SIGN_IN, 92, session_id="s1", ip="203.0.113.9")
    edge = _record(migrated, me, records.SIGN_IN, 90.5, session_id="s2")  # within the margin
    recent = _record(migrated, me, "session_ended", 10, session_id="s1", ended_by="self")
    done = retention.prune(migrated)
    assert done["account_record"] == 1
    assert _numbers(migrated) == {edge, recent}
    assert old not in _numbers(migrated)


def test_an_open_inbox_record_stays_until_its_matter_closes(migrated: Engine, now: Any) -> None:
    admin, waiting, decided = (factory.human(migrated) for _ in range(3))
    _registration(migrated, waiting, "pending")
    _registration(migrated, decided, "active")
    still_waits = _record(migrated, admin, "registration_pending", 100, human=waiting, handle="w")
    was_decided = _record(migrated, admin, "registration_pending", 100, human=decided, handle="d")

    disabled, enabled_again = factory.human(migrated), factory.human(migrated)
    _settings(migrated, disabled, "disabled")
    _settings(migrated, enabled_again, "verified")
    stays_disabled = _record(migrated, disabled, "mail_disabled", 100, address="a@example.org")
    set_again = _record(migrated, enabled_again, "mail_disabled", 100, address="b@example.org")

    owner, closed = factory.human(migrated), factory.human(migrated)
    ended_episode = _record(migrated, owner, "agents_not_listening", 120, instances=2, holding=0)
    away_now = _record(migrated, owner, "agents_not_listening", 100, instances=1, holding=1)
    _record(migrated, closed, "agents_not_listening", 110, instances=1, holding=0)
    closing = _record(migrated, closed, "agents_not_listening", 100, instances=0, holding=0)

    retention.prune(migrated)

    left = _numbers(migrated)
    assert {still_waits, stays_disabled, away_now} <= left
    assert not {was_decided, set_again, ended_episode, closing} & left
    assert left == {still_waits, stays_disabled, away_now}


def test_a_matter_that_closes_lets_its_record_go_on_the_next_sweep(
    migrated: Engine, now: Any
) -> None:
    me = factory.human(migrated)
    _settings(migrated, me, "disabled")
    kept = _record(migrated, me, "mail_disabled", 100, address="a@example.org")
    retention.prune(migrated)
    assert kept in _numbers(migrated)
    with migrated.begin() as conn:
        conn.execute(
            t.notification_settings.update()
            .where(t.notification_settings.c.human_id == me)
            .values(address_status="verified")
        )
    retention.prune(migrated)
    assert kept not in _numbers(migrated)


def test_open_records_do_not_stop_the_batches(
    migrated: Engine, now: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The batches walk the records by number: a batch of open records only is passed, and
    the old records behind it still go."""
    monkeypatch.setattr(retention, "BATCH", 2)
    me = factory.human(migrated)
    _settings(migrated, me, "disabled")
    kept = {
        _record(migrated, me, "mail_disabled", 120 - i, address="a@example.org") for i in (0, 1)
    }
    gone = {_record(migrated, me, records.SIGN_IN, 110 - i, session_id=str(i)) for i in range(5)}
    assert retention.prune(migrated)["account_record"] == 5
    assert _numbers(migrated) == kept
    assert not gone & _numbers(migrated)


# --- the mail's bookkeeping ------------------------------------------------------------


def test_items_mailed_before_the_oldest_derivable_item_go(migrated: Engine, now: Any) -> None:
    me = factory.human(migrated)
    with migrated.begin() as conn:
        for item, days in (("e:1", 92), ("r:1", 92), ("e:2", 89), ("r:2", 89), ("e:3", 1)):
            conn.execute(
                insert(t.mail_item_sent).values(
                    human_id=me, item=item, mailed_at=NOW - timedelta(days=days)
                )
            )
    assert retention.prune(migrated)["mail_item_sent"] == 2
    with migrated.begin() as conn:
        left = set(conn.execute(select(t.mail_item_sent.c.item)).scalars())
    assert left == {"e:2", "r:2", "e:3"}


def test_deliveries_older_than_a_day_go_and_the_counters_stay(migrated: Engine, now: Any) -> None:
    with migrated.begin() as conn:
        for hours in (49, 25, 2, 0.5):
            conn.execute(
                insert(t.mail_delivery).values(
                    kind="notification", outcome="sent", at=NOW - timedelta(hours=hours)
                )
            )
        before = mail_settings.counters(conn)
    assert retention.prune(migrated)["mail_delivery"] == 2
    with migrated.begin() as conn:
        assert mail_settings.counters(conn) == before
        assert conn.execute(select(func.count()).select_from(t.mail_delivery)).scalar_one() == 2


def test_stored_positions_unused_for_thirty_days_go(migrated: Engine, now: Any) -> None:
    me = factory.human(migrated)
    with migrated.begin() as conn:
        for handle, created, used in (
            ("npos-old", 40, 31),
            ("npos-used", 40, 1),
            ("npos-new", 29, 29),
        ):
            conn.execute(
                insert(t.notification_position).values(
                    id=handle,
                    human_id=me,
                    vector={"p": {}, "a": 0},
                    created_at=NOW - timedelta(days=created),
                    last_used_at=NOW - timedelta(days=used),
                )
            )
    assert retention.prune(migrated)["notification_position"] == 1
    with migrated.begin() as conn:
        left = set(conn.execute(select(t.notification_position.c.id)).scalars())
    assert left == {"npos-used", "npos-new"}


def test_the_sweep_goes_in_batches_and_stops_when_asked(
    migrated: Engine, now: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(retention, "BATCH", 2)
    with migrated.begin() as conn:
        for _ in range(5):
            conn.execute(
                insert(t.mail_delivery).values(
                    kind="security", outcome="sent", at=NOW - timedelta(days=3)
                )
            )
    stopped = threading.Event()
    stopped.set()
    assert retention.prune(migrated, stopped) == dict.fromkeys(
        ("account_record", "mail_item_sent", "mail_delivery", "notification_position"), 0
    )
    assert retention.prune(migrated, budget=0)["mail_delivery"] == 0
    assert retention.prune(migrated)["mail_delivery"] == 5


def test_the_mail_worker_runs_the_sweep(migrated: Engine) -> None:
    with migrated.begin() as conn:
        conn.execute(
            insert(t.mail_delivery).values(
                kind="security", outcome="sent", at=clock.now() - timedelta(days=3)
            )
        )
    worker = outbox.Worker(migrated, mail_env().mail, None, interval=0.01, prune_every=0.05)
    # `start` is off in tests (`_no_background_mail`); the thread it would start:
    worker._thread = threading.Thread(target=worker._run, daemon=True)
    worker._thread.start()
    try:
        deadline = time.monotonic() + 10
        left = 1
        while left and time.monotonic() < deadline:
            time.sleep(0.05)
            with migrated.begin() as conn:
                left = conn.execute(select(func.count()).select_from(t.mail_delivery)).scalar_one()
    finally:
        worker.stop()
    assert left == 0


# --- the mailer's read of what it sent -------------------------------------------------


def test_a_record_item_mailed_two_months_ago_is_not_mailed_again(
    make_client: ClientFactory, migrated: Engine
) -> None:
    """An item from an account record can be derived for 90 days (a sign-in's alert, a
    security item): what was mailed stays that long, past the 30 days of the events."""
    start = clock.now().replace(hour=12, minute=10, second=0, microsecond=0)
    _at(start)
    mail_tests.setup(make_client, migrated)
    factory.login_handle(make_client(), "maintainer")
    mail_tests.run(migrated)

    def alerts() -> int:
        return len([r for r in outbox_rows(migrated) if r.kind == "security"])

    first = alerts()
    assert first >= 1
    _at(start + timedelta(days=60))
    retention.prune(migrated)
    factory.login_handle(make_client(), "maintainer")  # a new sign-in moves the stamp
    mail_tests.run(migrated)
    assert alerts() == first + 1  # the new sign-in only, not the old one again
