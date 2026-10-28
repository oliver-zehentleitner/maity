"""Mail waiting to be sent, and the worker that sends it (docs/api.md §16.2, §18.5, §18.7).

A mail is written to `mail_outbox` in the transaction that decides it, so it goes out
only if that commits. The worker sends what is due with the settings in effect at that
moment and counts each outcome in `mail_delivery` by its budget kind. Security mail over
`security_max_per_hour` waits for the next hour, in order, never dropped; `enabled:
false` holds every mail. A failure of the instance's own setting (connection, TLS,
`AUTH`) is retried with backoff for up to 24 hours, whoever the mail was for.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.mail import headers, settings, smtp
from maity_hub.mail.environment import MailEnvironment
from maity_hub.notifications import records

log = logging.getLogger(__name__)

INTERVAL = 5.0  # seconds between looks at the outbox
RETRY_FOR = timedelta(hours=24)
BUDGETS = {
    "notification": "max_per_hour",
    "security": "security_max_per_hour",
    "sign_in": "sign_in_max_per_hour",
}
# Answers to an anonymous request: over their budget they are dropped, never held; a late
# link is useless (§16.2).
DROPPED_OVER_BUDGET = ("sign_in",)
# A failure here is the instance's setting, not the recipient's address (§18.7).
SETTING_STAGES = ("resolve", "connect", "tls", "auth", "timeout")


def enqueue(
    conn: Connection,
    *,
    kind: str,
    to: str,
    subject: str,
    body: str,
    human_id: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> int:
    """Put one mail in the outbox; `to` is a checked address (§18.4)."""
    now = clock.now()
    result = conn.execute(
        insert(t.mail_outbox).values(
            kind=kind,
            human_id=human_id,
            recipient=to,
            subject=headers.clean(subject)[:255],
            body=body,
            headers=extra_headers or {},
            created_at=now,
            not_before=now,
            attempts=0,
            status="waiting",
        )
    )
    key = result.inserted_primary_key
    assert key is not None
    return int(key[0])


def _count(conn: Connection, kind: str, outcome: str) -> None:
    conn.execute(insert(t.mail_delivery).values(kind=kind, outcome=outcome, at=clock.now()))


def send_due(engine: Engine, env: MailEnvironment, secret_key: bytes | None) -> int:
    """Send what is due now; returns how many left the hub.

    The settings in effect are read again before every delivery, so `enabled: false` and
    any other change reach the rest of a pass: a delivery under way ends, the rest stays
    in the queue (§16.2). A row is claimed and admitted in one transaction: the claim, so
    of two processes passing over the outbox only one takes it, and the admission, which
    counts it against the hour's budget of its kind under a lock on that kind's row. No
    clock and no commit of another worker decides who gets the last place."""
    if _resolved(engine, env, secret_key) is None:
        return 0
    with engine.begin() as conn:
        due = conn.execute(
            select(t.mail_outbox)
            .where(_claimable(clock.now()))
            .order_by(t.mail_outbox.c.id)
            .limit(50)
        ).all()
    sent = 0
    for row in due:
        resolved = _resolved(engine, env, secret_key)
        if resolved is None:
            break
        with engine.begin() as conn:
            if not _claim(conn, row.id):
                continue  # another process took it
            if _disabled_address(conn, row):
                _finish(conn, row.id, "dropped")  # no further mail to it (§18.7)
                continue
            # A retry was admitted when it first went out; a claim that lapsed is
            # admitted again, which errs on the side of the budget.
            attempts = conn.execute(
                select(t.mail_outbox.c.attempts).where(t.mail_outbox.c.id == row.id)
            ).scalar_one()
            if attempts == 0 and not _admit(conn, row.kind, int(resolved.value(BUDGETS[row.kind]))):
                if row.kind in DROPPED_OVER_BUDGET:
                    _finish(conn, row.id, "dropped")
                    _count(conn, row.kind, "dropped")
                else:
                    # Over the budget: security mail waits for the next hour (§16.2).
                    _release(conn, row.id, clock.now() + timedelta(minutes=5))
                continue
        outcome = smtp.send(resolved, _message(resolved, row))
        with engine.begin() as conn:
            sent += _settle(conn, row, outcome)
    return sent


def _resolved(engine: Engine, env: MailEnvironment, secret_key: bytes | None) -> Any:
    """The settings in effect now, or None while mail cannot or must not be sent."""
    with engine.begin() as conn:
        resolved = settings.resolve(conn, env, secret_key)
    return resolved if resolved.complete and resolved.enabled else None


def _admit(conn: Connection, kind: str, budget: int) -> bool:
    """Count one mail of `kind` against the hour's budget, if there is room: the kind's row
    is locked (`FOR UPDATE`; on SQLite the transaction already is), the hour rolls when it
    has passed, and `admitted` grows by one only below `budget`. Counted when a mail is
    admitted, not when it is sent: one that then fails for good keeps its place, which is
    the strict side of a budget against abuse."""
    now = clock.now()
    row = conn.execute(
        select(t.mail_budget).where(t.mail_budget.c.kind == kind).with_for_update()
    ).first()
    if row is None:
        try:
            with conn.begin_nested():
                conn.execute(insert(t.mail_budget).values(kind=kind, window_start=now, admitted=0))
        except IntegrityError:
            pass  # another worker made it at the same moment
        row = conn.execute(
            select(t.mail_budget).where(t.mail_budget.c.kind == kind).with_for_update()
        ).one()
    admitted = row.admitted
    window = row.window_start
    if now - window >= timedelta(hours=1):
        window, admitted = now, 0
    if admitted >= budget:
        return False
    conn.execute(
        update(t.mail_budget)
        .where(t.mail_budget.c.kind == kind)
        .values(window_start=window, admitted=admitted + 1)
    )
    return True


def _disabled_address(conn: Connection, row: Any) -> bool:
    """Whether the mail goes to a human's address that three hard failures disabled, as
    it stands now (§18.7): decided before each delivery, so what was queued earlier and
    the rest of a batch after the third failure stop too. Only the confirmation link of
    the address being set again passes (it is marked `_purpose: verify` and goes to the
    pending address): it is the way back, and nothing else follows it while the address
    stays disabled, the link used or not."""
    if row.human_id is None:
        return False
    found = conn.execute(
        select(t.notification_settings).where(t.notification_settings.c.human_id == row.human_id)
    ).first()
    return (
        found is not None
        and found.address_status == "disabled"
        and found.address == row.recipient
        and not (
            (row.headers or {}).get("_purpose") == "verify"
            and found.pending_address == row.recipient
        )
    )


def _release(conn: Connection, row_id: int, not_before: datetime) -> None:
    """Give a claimed row back to the queue, due again at `not_before`."""
    conn.execute(
        update(t.mail_outbox)
        .where(t.mail_outbox.c.id == row_id, t.mail_outbox.c.status == "sending")
        .values(status="waiting", not_before=not_before)
    )


# A claim holds a row while it is sent; one that outlives this (the process died
# mid-send) is taken again, so a mail is sent at least once, and by one process at a time.
CLAIM_FOR = timedelta(minutes=2)


def _claimable(now: datetime) -> Any:
    """Waiting and due, or claimed by a process that did not finish in time."""
    return t.mail_outbox.c.status.in_(("waiting", "sending")) & (t.mail_outbox.c.not_before <= now)


def _claim(conn: Connection, row_id: int) -> bool:
    """Take the row with one conditional UPDATE: True for the one process that did."""
    now = clock.now()
    taken = conn.execute(
        update(t.mail_outbox)
        .where(t.mail_outbox.c.id == row_id, _claimable(now))
        .values(status="sending", not_before=now + CLAIM_FOR)
    ).rowcount
    return bool(taken == 1)


def _finish(conn: Connection, row_id: int, status: str) -> None:
    """The row leaves the queue: it keeps its recipient and subject for the week, but not
    the text, which carries the mail's links (a leaked table gives no link of a mail
    that is out)."""
    conn.execute(
        update(t.mail_outbox).where(t.mail_outbox.c.id == row_id).values(status=status, body="")
    )


def _message(resolved: settings.Resolved, row: Any) -> Any:
    sender = resolved.sender
    assert sender is not None
    mail = headers.message(
        sender=sender.address,
        sender_name=sender.name,
        to=row.recipient,
        subject=row.subject,
        body=row.body,
        reply_to=resolved.value("reply_to"),
    )
    for name, value in (row.headers or {}).items():
        if not name.startswith("_"):  # a mark for the hub's own use, never a header
            mail[name] = headers.clean(str(value))
    return mail


def _settle(conn: Connection, row: Any, outcome: smtp.Outcome) -> int:
    if outcome.ok:
        _finish(conn, row.id, "sent")
        _count(conn, row.kind, "sent")
        _delivered(conn, row)
        return 1
    _count(conn, row.kind, "failed")
    permanent = outcome.smtp_code is not None and outcome.smtp_code >= 500
    if permanent and outcome.stage in ("rcpt_to", "data"):
        _finish(conn, row.id, "failed")
        _hard_failure(conn, row)
        return 0
    attempts = row.attempts + 1
    if clock.now() - row.created_at >= RETRY_FOR:
        _finish(conn, row.id, "dropped")
        return 0
    backoff = timedelta(minutes=min(60, 2**attempts))
    conn.execute(
        update(t.mail_outbox)
        .where(t.mail_outbox.c.id == row.id)
        .values(status="waiting", attempts=attempts, not_before=clock.now() + backoff)
    )
    if outcome.stage in SETTING_STAGES:
        log.warning("mail: sending failed at stage %s; retrying", outcome.stage)
    return 0


HARD_FAILURES = 3
KEPT = timedelta(days=7)  # what was sent, failed or dropped, then the row goes


def _address_row(conn: Connection, row: Any) -> Any:
    """The human's settings when the mail went to their address in use, else None: a
    verification link to a pending address counts against no address."""
    if row.human_id is None:
        return None
    found = conn.execute(
        select(t.notification_settings)
        .where(t.notification_settings.c.human_id == row.human_id)
        .with_for_update()
    ).first()
    return found if found is not None and found.address == row.recipient else None


def _delivered(conn: Connection, row: Any) -> None:
    """A delivered mail resets the address's count of hard failures (§18.7)."""
    found = _address_row(conn, row)
    if found is not None and found.hard_failures:
        conn.execute(
            update(t.notification_settings)
            .where(t.notification_settings.c.human_id == row.human_id)
            .values(hard_failures=0)
        )


def _hard_failure(conn: Connection, row: Any) -> None:
    """A permanent failure at `RCPT TO` or `DATA` counts against the address; the third
    in a row disables it and tells the human in the dashboard (§18.7)."""
    found = _address_row(conn, row)
    if found is None or found.address_status != "verified":
        return
    failures = found.hard_failures + 1
    values: dict[str, Any] = {"hard_failures": failures, "updated_at": clock.now()}
    if failures >= HARD_FAILURES:
        values.update(address_status="disabled", disabled_at=clock.now())
    conn.execute(
        update(t.notification_settings)
        .where(t.notification_settings.c.human_id == row.human_id)
        .values(**values)
    )
    if failures >= HARD_FAILURES:
        records.write(conn, row.human_id, "mail_disabled", {"address": found.address})


def forget_old(conn: Connection) -> None:
    """Rows that left the queue keep their recipient and subject a week, no longer."""
    conn.execute(
        delete(t.mail_outbox).where(
            t.mail_outbox.c.status.in_(("sent", "failed", "dropped")),
            t.mail_outbox.c.created_at < clock.now() - KEPT,
        )
    )


class Worker:
    """Sends the outbox in the background, one mail at a time."""

    def __init__(
        self,
        engine: Engine,
        env: MailEnvironment,
        secret_key: bytes | None,
        interval: float = INTERVAL,
    ) -> None:
        self.engine, self.env, self.secret_key, self.interval = engine, env, secret_key, interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-mail", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=25)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                send_due(self.engine, self.env, self.secret_key)
                with self.engine.begin() as conn:
                    forget_old(conn)
            except Exception:  # one bad pass must not stop the sender
                log.exception("mail: a pass over the outbox failed")
