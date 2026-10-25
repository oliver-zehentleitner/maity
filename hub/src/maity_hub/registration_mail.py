"""The mail registration sends (docs/api.md §2.7.1): the link to confirm an address, and
the note to an address that has an account already.

Until the mail outbox exists (#280) nothing is sent: `send` only records what it would
send, so tests can see it. With the outbox it becomes `outbox.enqueue(conn,
kind="registration", …)`, on the registration budget (§16.2), and this module is the one
place that changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Connection

KINDS = ("register_link", "already_registered")


@dataclass(frozen=True)
class Sent:
    kind: str
    to: str
    pending_id: str | None


# What `send` was asked to send, newest last; the tests read and clear it.
SENT: list[Sent] = []


def send(conn: Connection, *, kind: str, to: str, pending_id: str | None = None) -> None:
    """Send one registration mail in the caller's transaction (it goes out only if that
    commits). A no-op until the outbox lands."""
    del conn
    if kind not in KINDS:
        raise ValueError(f"unknown registration mail {kind}")
    SENT.append(Sent(kind, to, pending_id))
