"""The mail registration sends (docs/api.md §2.7.1): the link to confirm an address, and
the note to an address that has an account already.

Until the mail outbox exists (#280) nothing is sent and nothing is kept: `send` is a
no-op, so no address outlives its pending registration in memory. With the outbox it
becomes `outbox.enqueue(conn, kind="registration", …)`, on the registration budget
(§16.2), and this module is the one place that changes. Tests replace `send` to see what
would go out.
"""

from __future__ import annotations

from sqlalchemy import Connection

KINDS = ("register_link", "already_registered")


def send(conn: Connection, *, kind: str, to: str, pending_id: str | None = None) -> None:
    """Send one registration mail in the caller's transaction (it goes out only if that
    commits). A no-op until the outbox lands: it checks the kind and keeps nothing."""
    del conn, to, pending_id
    if kind not in KINDS:
        raise ValueError(f"unknown registration mail {kind}")
