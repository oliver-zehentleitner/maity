"""The mail outbox and its worker (docs/api.md §16.2, §18.5, §18.7)."""

from __future__ import annotations

import base64
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import instance_settings as store
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from tests.smtpfake import FakeSmtp, Script

SIGNING = base64.b64encode(b"s" * 32).decode()


def mail_env(port: int = 25) -> Settings:
    return Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_SMTP_HOST": "127.0.0.1",
            "MAITY_SMTP_PORT": str(port),
            "MAITY_SMTP_TLS": "none",
            "MAITY_SMTP_FROM": "Maity <maity@example.org>",
            "MAITY_MAIL_SIGNING_KEY": SIGNING,
        }
    )


def spent(conn: Any, kind: str, admitted: int = 1) -> None:
    """The hour's budget of `kind` already used."""
    conn.execute(
        t.mail_budget.insert().values(kind=kind, window_start=clock.now(), admitted=admitted)
    )


def queue(conn: object, kind: str = "security") -> int:
    return outbox.enqueue(conn, kind=kind, to="me@example.org", subject="s", body="b\n")  # type: ignore[arg-type]


def test_the_outbox_sends_and_counts(migrated: Engine) -> None:
    server = FakeSmtp(Script())
    try:
        hub = mail_env(server.port)
        with migrated.begin() as conn:
            queue(conn)
        assert outbox.send_due(migrated, hub.mail, None) == 1
        assert server.record.commands[-2] == "DATA"
        with migrated.begin() as conn:
            assert conn.execute(select(t.mail_outbox.c.status)).scalar() == "sent"
            delivery = conn.execute(select(t.mail_delivery)).one()
        assert (delivery.kind, delivery.outcome) == ("security", "sent")
    finally:
        server.close()


def test_a_mail_that_is_not_committed_is_not_sent(migrated: Engine) -> None:
    class Rolled(Exception):
        pass

    try:
        with migrated.begin() as conn:
            queue(conn)
            raise Rolled
    except Rolled:
        pass
    with migrated.begin() as conn:
        assert conn.execute(select(t.mail_outbox)).first() is None


def test_security_mail_over_its_budget_waits(migrated: Engine) -> None:
    hub = mail_env(1)  # nothing listens: nothing may be tried either
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 1, None)
        spent(conn, "security")
        queue(conn)
    assert outbox.send_due(migrated, hub.mail, None) == 0
    with migrated.begin() as conn:
        row = conn.execute(select(t.mail_outbox)).one()
        assert mail_settings.counters(conn)["security_queued"] == 1
    assert row.status == "waiting" and row.attempts == 0


def test_disabled_mail_holds_the_outbox(migrated: Engine) -> None:
    server = FakeSmtp(Script())
    try:
        hub = mail_env(server.port)
        with migrated.begin() as conn:
            store.put(conn, "mail.enabled", False, None)
            queue(conn)
        assert outbox.send_due(migrated, hub.mail, None) == 0
        assert server.record.commands == []  # nothing even connected
    finally:
        server.close()


def test_a_sign_in_mail_over_its_budget_is_dropped(migrated: Engine) -> None:
    hub = mail_env(1)
    with migrated.begin() as conn:
        store.put(conn, "mail.sign_in_max_per_hour", 1, None)
        spent(conn, "sign_in")
        queue(conn, "sign_in")
    assert outbox.send_due(migrated, hub.mail, None) == 0
    with migrated.begin() as conn:
        assert conn.execute(select(t.mail_outbox.c.status)).scalar() == "dropped"
        assert mail_settings.counters(conn)["sign_in_dropped_last_hour"] == 1


def test_a_failure_of_the_instance_is_retried_with_backoff(migrated: Engine) -> None:
    hub = mail_env(1)  # nothing listens: the connection fails
    with migrated.begin() as conn:
        queue(conn)
    assert outbox.send_due(migrated, hub.mail, None) == 0
    with migrated.begin() as conn:
        row = conn.execute(select(t.mail_outbox)).one()
    assert (row.status, row.attempts) == ("waiting", 1) and row.not_before > clock.now()


def test_a_mail_the_instance_could_not_send_for_a_day_is_dropped(migrated: Engine) -> None:
    hub = mail_env(1)
    with migrated.begin() as conn:
        row = queue(conn)
        conn.execute(
            update(t.mail_outbox)
            .where(t.mail_outbox.c.id == row)
            .values(created_at=clock.now() - timedelta(hours=25))
        )
    outbox.send_due(migrated, hub.mail, None)
    with migrated.begin() as conn:
        assert conn.execute(select(t.mail_outbox.c.status)).scalar() == "dropped"


def test_a_permanent_refusal_fails_the_row(migrated: Engine) -> None:
    server = FakeSmtp(Script(rcpt_reply="550 5.1.1 no such user"))
    try:
        with migrated.begin() as conn:
            queue(conn)
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 0
    finally:
        server.close()
    with migrated.begin() as conn:
        assert conn.execute(select(t.mail_outbox.c.status)).scalar() == "failed"
        assert conn.execute(select(t.mail_delivery.c.outcome)).scalar() == "failed"


def test_forgetting_old_rows_never_touches_waiting_or_claimed_mail(migrated: Engine) -> None:
    old = clock.now() - timedelta(days=8)
    with migrated.begin() as conn:
        for status in ("waiting", "sending", "sent", "failed", "dropped"):
            row = queue(conn)
            conn.execute(
                update(t.mail_outbox)
                .where(t.mail_outbox.c.id == row)
                .values(status=status, created_at=old)
            )
        fresh = queue(conn)
        conn.execute(update(t.mail_outbox).where(t.mail_outbox.c.id == fresh).values(status="sent"))
        outbox.forget_old(conn)
        left = conn.execute(select(t.mail_outbox.c.status, t.mail_outbox.c.id)).all()
    assert sorted(status for status, _ in left) == ["sending", "sent", "waiting"]
    assert fresh in {row_id for _, row_id in left}


# --- two processes (one sender per row) ------------------------------------------------


def test_of_two_passes_that_both_see_a_row_only_one_claims_it(migrated: Engine) -> None:
    with migrated.begin() as conn:
        row = queue(conn)
    with migrated.begin() as conn:  # both passes selected the row; the first claims it
        seen = conn.execute(select(t.mail_outbox).where(t.mail_outbox.c.id == row)).one()
        assert seen.status == "waiting"
        assert outbox._claim(conn, row) is True
    with migrated.begin() as conn:  # the second, with the same stale view, does not
        assert outbox._claim(conn, row) is False
        assert conn.execute(select(t.mail_outbox.c.status)).scalar() == "sending"


def test_a_claim_that_outlived_its_process_is_taken_again(migrated: Engine) -> None:
    server = FakeSmtp(Script())
    try:
        with migrated.begin() as conn:
            row = queue(conn)
            conn.execute(  # a process claimed it and died
                update(t.mail_outbox)
                .where(t.mail_outbox.c.id == row)
                .values(status="sending", not_before=clock.now() + timedelta(minutes=2))
            )
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 0
        later = clock.now() + timedelta(minutes=3)
        clock.set_source(lambda: later)
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 1
    finally:
        server.close()


# --- what H found in the first version (#478) -----------------------------------------


def _ok() -> Any:
    from maity_hub.mail import smtp

    return smtp.Outcome(ok=True, stage=None, smtp_code=None, detail=None, at=clock.now())


def test_two_workers_never_both_take_the_last_place_of_a_budget(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A claims the first mail and is still in the SMTP conversation when B passes over
    the second: with a budget of one, B must not send."""
    from maity_hub.mail import smtp

    hub = mail_env(1)
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 1, None)
        queue(conn)
        queue(conn)
    sends: list[str] = []

    def slow(resolved: Any, message: Any) -> Any:
        sends.append(message["Subject"])
        if len(sends) == 1:  # worker B passes while A is in the conversation
            assert outbox.send_due(migrated, hub.mail, None) == 0
        return _ok()

    monkeypatch.setattr(smtp, "send", slow)
    assert outbox.send_due(migrated, hub.mail, None) == 1
    assert len(sends) == 1
    with migrated.begin() as conn:
        rows = conn.execute(select(t.mail_outbox).order_by(t.mail_outbox.c.id)).all()
    assert [r.status for r in rows] == ["sent", "waiting"]
    assert rows[1].not_before > clock.now()  # the second waits for the next hour


def test_an_anonymous_answer_in_flight_counts_too(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub.mail import smtp

    hub = mail_env(1)
    with migrated.begin() as conn:
        store.put(conn, "mail.sign_in_max_per_hour", 1, None)
        queue(conn, "sign_in")
        queue(conn, "sign_in")
    sends: list[int] = []

    def slow(resolved: Any, message: Any) -> Any:
        sends.append(1)
        if len(sends) == 1:
            outbox.send_due(migrated, hub.mail, None)
        return _ok()

    monkeypatch.setattr(smtp, "send", slow)
    assert outbox.send_due(migrated, hub.mail, None) == 1
    with migrated.begin() as conn:
        statuses = [r.status for r in conn.execute(select(t.mail_outbox).order_by("id"))]
    assert statuses == ["sent", "dropped"]  # over its budget, it is dropped, never sent late


def test_a_lapsed_claim_does_not_hold_a_place_of_the_budget(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub.mail import smtp

    hub = mail_env(1)
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 1, None)
        first = queue(conn)
        queue(conn)
        conn.execute(  # a process claimed the first one and died, long ago
            update(t.mail_outbox)
            .where(t.mail_outbox.c.id == first)
            .values(status="sending", not_before=clock.now() - timedelta(minutes=1))
        )
    monkeypatch.setattr(smtp, "send", lambda resolved, message: _ok())
    assert outbox.send_due(migrated, hub.mail, None) == 1  # the lapsed one, then no room
    with migrated.begin() as conn:
        statuses = [r.status for r in conn.execute(select(t.mail_outbox).order_by("id"))]
    assert statuses == ["sent", "waiting"]


def test_mail_switched_off_during_a_delivery_stops_the_rest_of_the_pass(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub.mail import smtp

    hub = mail_env(1)
    with migrated.begin() as conn:
        for _ in range(3):
            queue(conn)
    sends: list[int] = []

    def switch_off(resolved: Any, message: Any) -> Any:
        sends.append(1)
        with migrated.begin() as conn:
            store.put(conn, "mail.enabled", False, None)  # the operator, mid-pass
        return _ok()

    monkeypatch.setattr(smtp, "send", switch_off)
    assert outbox.send_due(migrated, hub.mail, None) == 1
    assert len(sends) == 1  # the delivery under way ended, nothing else left
    with migrated.begin() as conn:
        statuses = [r.status for r in conn.execute(select(t.mail_outbox).order_by("id"))]
    assert statuses == ["sent", "waiting", "waiting"]


def test_an_older_retry_that_falls_due_while_a_newer_mail_is_in_flight_waits(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The id of a row says nothing about when it was claimed: the older mail was put
    back by a retry and falls due while the newer one is being sent."""
    from maity_hub.mail import smtp

    hub = mail_env(1)
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 1, None)
        older = queue(conn)
        newer = queue(conn)
        conn.execute(  # a retry: due only after the newer one has been claimed
            update(t.mail_outbox)
            .where(t.mail_outbox.c.id == older)
            .values(not_before=clock.now() + timedelta(seconds=1))
        )
    sends: list[int] = []

    def slow(resolved: Any, message: Any) -> Any:
        sends.append(1)
        if len(sends) == 1:  # two seconds later worker B takes the older mail, now due
            later = clock.now() + timedelta(seconds=2)
            clock.set_source(lambda: later)
            assert outbox.send_due(migrated, hub.mail, None) == 0
        return _ok()

    monkeypatch.setattr(smtp, "send", slow)
    assert outbox.send_due(migrated, hub.mail, None) == 1
    assert len(sends) == 1
    with migrated.begin() as conn:
        rows = {r.id: r.status for r in conn.execute(select(t.mail_outbox))}
    assert rows == {older: "waiting", newer: "sent"}


# --- the admission (H's third round on #478) --------------------------------------------


def test_the_clock_jumping_when_a_worker_claims_does_not_admit_a_second_mail(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No clock decides who has the last place: worker A claims id2, the clock jumps by two
    seconds, and worker B, a second later by its own reading, takes the older id1."""
    from maity_hub.mail import smtp

    hub = mail_env(1)
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 1, None)
        older = queue(conn)
        newer = queue(conn)
        conn.execute(
            update(t.mail_outbox)
            .where(t.mail_outbox.c.id == older)
            .values(not_before=clock.now() + timedelta(seconds=1))
        )
    start = clock.now()
    sends: list[int] = []

    def jumpy(resolved: Any, message: Any) -> Any:
        sends.append(1)
        if len(sends) == 1:
            clock.set_source(lambda: start + timedelta(seconds=1, milliseconds=500))
            assert outbox.send_due(migrated, hub.mail, None) == 0
        return _ok()

    monkeypatch.setattr(smtp, "send", jumpy)
    assert outbox.send_due(migrated, hub.mail, None) == 1
    with migrated.begin() as conn:
        rows = {r.id: r.status for r in conn.execute(select(t.mail_outbox))}
    assert rows == {older: "waiting", newer: "sent"}


def test_two_admissions_racing_for_the_last_place_admit_one(migrated: Engine) -> None:
    import threading

    barrier = threading.Barrier(2)
    answers: list[bool] = []

    def admit() -> None:
        barrier.wait(timeout=10)  # both go for the row at once
        with migrated.begin() as conn:
            answers.append(outbox._admit(conn, "security", 1))

    threads = [threading.Thread(target=admit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(answers) == [False, True]
    with migrated.begin() as conn:
        assert conn.execute(select(t.mail_budget.c.admitted)).scalar_one() == 1


def test_the_hour_rolls_and_the_budget_is_open_again(migrated: Engine) -> None:
    with migrated.begin() as conn:
        assert outbox._admit(conn, "security", 1) is True
        assert outbox._admit(conn, "security", 1) is False
    later = clock.now() + timedelta(hours=1, seconds=1)
    clock.set_source(lambda: later)
    with migrated.begin() as conn:
        assert outbox._admit(conn, "security", 1) is True
        row = conn.execute(select(t.mail_budget)).one()
    assert row.admitted == 1 and row.window_start == later


def test_each_kind_has_a_budget_of_its_own(migrated: Engine) -> None:
    with migrated.begin() as conn:
        assert outbox._admit(conn, "security", 1) is True
        assert outbox._admit(conn, "sign_in", 1) is True
        assert outbox._admit(conn, "security", 1) is False


def test_a_retry_is_not_admitted_twice(migrated: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    from maity_hub.mail import smtp

    hub = mail_env(1)
    with migrated.begin() as conn:
        store.put(conn, "mail.security_max_per_hour", 1, None)
        spent(conn, "security")  # the one place is used: by this mail's first attempt
        row = queue(conn)
        conn.execute(update(t.mail_outbox).where(t.mail_outbox.c.id == row).values(attempts=1))
    monkeypatch.setattr(smtp, "send", lambda resolved, message: _ok())
    assert outbox.send_due(migrated, hub.mail, None) == 1  # it is not asked for a second place
    with migrated.begin() as conn:
        assert conn.execute(select(t.mail_budget.c.admitted)).scalar_one() == 1


def test_a_mail_that_fails_for_good_keeps_its_place(migrated: Engine) -> None:
    server = FakeSmtp(Script(rcpt_reply="550 5.1.1 no such user"))
    try:
        with migrated.begin() as conn:
            store.put(conn, "mail.security_max_per_hour", 1, None)
            queue(conn)
            queue(conn)
        assert outbox.send_due(migrated, mail_env(server.port).mail, None) == 0
    finally:
        server.close()
    with migrated.begin() as conn:
        statuses = [r.status for r in conn.execute(select(t.mail_outbox).order_by("id"))]
    assert statuses == ["failed", "waiting"]  # the second finds the place used
