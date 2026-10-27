"""The mail outbox and its worker (docs/api.md §16.2, §18.5, §18.7)."""

from __future__ import annotations

import base64
from datetime import timedelta

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
        conn.execute(
            t.mail_delivery.insert().values(kind="security", outcome="sent", at=clock.now())
        )
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
        conn.execute(
            t.mail_delivery.insert().values(kind="sign_in", outcome="sent", at=clock.now())
        )
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
