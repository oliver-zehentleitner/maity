"""Account records (docs/api.md §18.1, §2.6.5): audit records about one human's own
account, readable by that human alone, never events.

A record's number comes from the table's own sequence, taken while the human's row is
locked until commit, so one account never shows a number before every lower one, and
`at` never decreases along one account's records. Kept 90 days.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, func, insert, select

from maity_hub import clock
from maity_hub import tables as t

KEPT = timedelta(days=90)
SECURITY = (
    "session_created",
    "email_address_changed",
    "second_factor_changed",
    "second_factor_failed",
    "forge_access_changed",
)
# The forge access changes that are a `security` item; the others are no notification.
FORGE_ADDED = ("linked", "token_set")
# Records that are `inbox` items, open until their matter is closed (§18.1).
INBOX = ("registration_pending", "mail_disabled", "report_open")
# Records that are `inbox` items read by a read mark, as any notice (§18.1).
NOTICES = ("moderation_applied",)
PERSONAL = (
    "personal_request_created",
    "personal_request_answered",
    "personal_request_withdrawn",
)


def write(conn: Connection, human_id: str, kind: str, data: dict[str, Any]) -> int:
    """Append one record for `human_id` inside the caller's transaction; returns `n`."""
    conn.execute(select(t.human.c.id).where(t.human.c.id == human_id).with_for_update())
    previous = conn.execute(
        select(func.max(t.account_record.c.at)).where(t.account_record.c.human_id == human_id)
    ).scalar()
    now = clock.now()
    at = max(now, previous) if previous is not None else now
    result = conn.execute(
        insert(t.account_record).values(human_id=human_id, type=kind, data=data, at=at)
    )
    key = result.inserted_primary_key
    if key is None:
        raise RuntimeError("the record insert returned no number")
    return int(key[0])


def personal_request(conn: Connection, request: Any) -> None:
    """One record per state change of a personal request, for the human it is addressed
    to: ids and status, nothing of its content (§18.1)."""
    if not request.personal or request.to_human is None:
        return
    kind = {
        "open": "personal_request_created",
        "answered": "personal_request_answered",
        "withdrawn": "personal_request_withdrawn",
    }[request.status]
    write(
        conn,
        request.to_human,
        kind,
        {"request_id": request.id, "project_id": request.project_id, "status": request.status},
    )


def forge_access_changed(
    conn: Connection, human_id: str, source: str, change: str, login: str | None
) -> None:
    """A change of the human's forge access (§11.4): `source` is `app` or `owner_token`.
    The account login names what was added; never a token."""
    write(
        conn,
        human_id,
        "forge_access_changed",
        {"forge": "github", "source": source, "change": change, "login": login},
    )


def session_created(conn: Connection, human_id: str, data: dict[str, Any]) -> int:
    return write(conn, human_id, "session_created", data)


def session_ended(conn: Connection, human_id: str, session_id: str, by: str) -> None:
    write(conn, human_id, "session_ended", {"session_id": session_id, "ended_by": by})


def sign_in_records(conn: Connection, human_id: str) -> dict[str, Any]:
    """The live `session_created` records of a human, by the session's public id."""
    since = clock.now() - KEPT
    rows = conn.execute(
        select(t.account_record).where(
            t.account_record.c.human_id == human_id,
            t.account_record.c.type == "session_created",
            t.account_record.c.at >= since,
        )
    ).all()
    return {row.data.get("session_id"): row for row in rows}
