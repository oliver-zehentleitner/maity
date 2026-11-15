"""What the account records and the mail's bookkeeping keep, and the sweep that deletes the
rest (docs/api.md §2.6.5, §16.2, §18.1, §18.2; context/notifications.md
c28a0dba-829b-4476-a422-9eadcca9337a).

Once an hour the mail worker (`outbox.Worker`) deletes:

- account records past `records.KEPT` (90 days) and `MARGIN`, except an inbox record whose
  matter is still open (`still_open`): it goes on the first sweep after its matter closed;
- `mail_item_sent` rows mailed more than `SENT_KEPT` ago: no item the mailer can still derive
  is that old, so the row can no longer stop a second mail;
- `mail_delivery` rows past `DELIVERIES_KEPT`: the counters and the budget read the last hour;
- stored positions (`notification_position`) unused for `POSITIONS_KEPT`.

Each table goes in batches of `BATCH` rows, a short transaction each, chosen by key and deleted
by key with the same condition again, so no statement holds many rows' locks and the same
statement runs on SQLite, PostgreSQL and MariaDB. A pass stops at `PASS_BUDGET` or when the
worker stops; what is left goes on the next pass.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Column, Connection, Engine, Table, delete, func, select, tuple_

from maity_hub import clock, worker_runs
from maity_hub import tables as t
from maity_hub.notifications import records

EVERY = 3600.0  # seconds between two sweeps
PASS_BUDGET = 30.0  # seconds one sweep may take before it leaves the rest to the next
BATCH = 500
# Past the age a reader still asks for: a reader that filters by `>= now - KEPT` and the sweep
# never race for a row at the edge.
MARGIN = timedelta(days=1)
# The oldest item the mailer derives is a record within `records.KEPT` (events: 30 days), and a
# row is written when its item is mailed, never before the item's `at`.
SENT_KEPT = records.KEPT + MARGIN
DELIVERIES_KEPT = timedelta(days=1)
POSITIONS_KEPT = timedelta(days=30)  # "kept at least 30 days after its last use" (§18.2)

Stopping = worker_runs.Stopping | None


class _Deadline:
    """Stops at `PASS_BUDGET` or when the worker does."""

    def __init__(self, stop: Stopping, budget: float) -> None:
        self.stop, self.until = stop, time.monotonic() + budget

    def is_set(self) -> bool:
        return (self.stop is not None and self.stop.is_set()) or time.monotonic() >= self.until


def prune(engine: Engine, stop: Stopping = None, budget: float = PASS_BUDGET) -> dict[str, int]:
    """One sweep; returns how many rows of each table went."""
    now = clock.now()
    deadline = _Deadline(stop, budget)
    sent, delivery, position = t.mail_item_sent.c, t.mail_delivery.c, t.notification_position.c
    return {
        "account_record": _records(engine, now - records.KEPT - MARGIN, deadline),
        "mail_item_sent": _batched(
            engine,
            t.mail_item_sent,
            (sent.human_id, sent.item),
            sent.mailed_at < now - SENT_KEPT,
            deadline,
        ),
        "mail_delivery": _batched(
            engine, t.mail_delivery, (delivery.id,), delivery.at < now - DELIVERIES_KEPT, deadline
        ),
        "notification_position": _batched(
            engine,
            t.notification_position,
            (position.id,),
            position.last_used_at < now - POSITIONS_KEPT,
            deadline,
        ),
    }


def _batched(
    engine: Engine, table: Table, keys: Sequence[Column[Any]], condition: Any, stop: _Deadline
) -> int:
    """Delete the rows that meet `condition`, `BATCH` at a time. The DELETE names the keys it
    chose and checks the condition again: a row that changed in between (a position used) stays."""
    done = 0
    while not stop.is_set():
        with engine.begin() as conn:
            rows = conn.execute(select(*keys).where(condition).order_by(*keys).limit(BATCH)).all()
            if not rows:
                break
            chosen = (
                keys[0].in_([row[0] for row in rows])
                if len(keys) == 1
                else tuple_(*keys).in_([tuple(row) for row in rows])
            )
            conn.execute(delete(table).where(chosen, condition))
        done += len(rows)
        if len(rows) < BATCH:
            break
    return done


def _records(engine: Engine, before: datetime, stop: _Deadline) -> int:
    """Delete the account records written before `before`, but not one whose matter is still
    open. The batches walk the records by number, so the open ones they pass are not chosen
    again; old records have the low numbers, so a batch reads the start of the key."""
    c = t.account_record.c
    done, after = 0, 0
    while not stop.is_set():
        with engine.begin() as conn:
            rows = conn.execute(
                select(c.n, c.human_id, c.type, c.data)
                .where(c.at < before, c.n > after)
                .order_by(c.n)
                .limit(BATCH)
            ).all()
            if not rows:
                break
            after = rows[-1].n
            kept = still_open(conn, rows)
            gone = [row.n for row in rows if row.n not in kept]
            if gone:
                conn.execute(delete(t.account_record).where(c.n.in_(gone)))
        done += len(gone)
        if len(rows) < BATCH:
            break
    return done


def still_open(conn: Connection, rows: Sequence[Any]) -> set[int]:
    """The numbers of the inbox records among `rows` whose matter is still open (§18.1), read
    as the bell reads them:

    - `registration_pending`: while the registration it names waits for a decision;
    - `mail_disabled`: while the human's address stays disabled;
    - `agents_not_listening`: the human's newest record of the type, while its count is not 0.
    """
    by_type: dict[str, list[Any]] = {}
    for row in rows:
        if row.type in records.INBOX:
            by_type.setdefault(row.type, []).append(row)
    kept: set[int] = set()
    pending = by_type.get("registration_pending", [])
    if pending:
        waiting = set(
            conn.execute(
                select(t.account_registration.c.human_id).where(
                    t.account_registration.c.human_id.in_(
                        {str((row.data or {}).get("human")) for row in pending}
                    ),
                    t.account_registration.c.status == "pending",
                )
            ).scalars()
        )
        kept |= {row.n for row in pending if str((row.data or {}).get("human")) in waiting}
    disabled_rows = by_type.get("mail_disabled", [])
    if disabled_rows:
        disabled = set(
            conn.execute(
                select(t.notification_settings.c.human_id).where(
                    t.notification_settings.c.human_id.in_({row.human_id for row in disabled_rows}),
                    t.notification_settings.c.address_status == "disabled",
                )
            ).scalars()
        )
        kept |= {row.n for row in disabled_rows if row.human_id in disabled}
    away = by_type.get("agents_not_listening", [])
    if away:
        c = t.account_record.c
        newest = dict(
            conn.execute(
                select(c.human_id, func.max(c.n))
                .where(
                    c.human_id.in_({row.human_id for row in away}),
                    c.type == "agents_not_listening",
                )
                .group_by(c.human_id)
            ).all()
        )
        kept |= {
            row.n
            for row in away
            if newest.get(row.human_id) == row.n and int((row.data or {}).get("instances", 0)) > 0
        }
    return kept
