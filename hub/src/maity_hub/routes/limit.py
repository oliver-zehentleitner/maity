"""`POST /me/limit`: a member declares that it is out until a time (docs/api.md §6.12)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, select

from maity_hub import availability, clock, idempotency, namespace
from maity_hub import tables as t
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import invalid
from maity_hub.models import Strict
from maity_hub.routes.me import human_body
from maity_hub.routes.members import load_member

router = APIRouter()

# RFC 3339 with its offset: a time without one is never read as some local time.
RFC3339 = re.compile(
    r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d{1,9})?([Zz]|[+-]\d{2}:\d{2})", re.ASCII
)


class LimitIn(Strict):
    until: str | None = Field(max_length=64)
    harness: str | None = Field(default=None, max_length=200)
    reason: str | None = Field(default=None, max_length=availability.REASON_MAX)
    show_reason_in: list[str] | None = Field(default=None, max_length=200)


def parse_until(text: str) -> datetime:
    """`until` as an aware UTC moment, `invalid` with `format`, `past` or `too_far`."""
    if not RFC3339.fullmatch(text):
        raise invalid({"until": "format"}, "until must be RFC 3339 with an offset")
    try:
        moment = datetime.fromisoformat(text.upper().replace("Z", "+00:00"))
    except ValueError:
        raise invalid({"until": "format"}, "until must be RFC 3339 with an offset") from None
    moment = moment.astimezone(UTC)
    now = clock.now()
    if moment <= now:
        raise invalid({"until": "past"})
    if moment > now + availability.LIMIT_AHEAD:
        raise invalid({"until": "too_far"}, "a limit ends within 7 days")
    return moment


@router.post("/me/limit")
def post_limit(body: LimitIn, request: Request, caller: AnyCaller) -> JSONResponse:
    given = body.model_fields_set

    def action(conn: Connection) -> idempotency.Outcome:
        until = parse_until(body.until) if body.until is not None else None
        if caller.kind == "human":
            return _human(conn, caller, until, body, given)
        return _agent(conn, caller, until, body, given)

    return idempotency.run(engine_of(request), request, caller, action)


def _agent(
    conn: Connection, caller: Caller, until: datetime | None, body: LimitIn, given: set[str]
) -> idempotency.Outcome:
    if "show_reason_in" in given:
        # An agent's reason is shown as sent anyway (§6.12).
        raise invalid({"show_reason_in": "humans_only"})
    row = conn.execute(select(t.membership).where(t.membership.c.id == caller.membership_id)).one()
    availability.set_agent_limit(
        conn,
        row,
        until,
        source="self",
        harness=body.harness or caller.harness,
        reason=body.reason,
        placement_id=None,
        actor=caller.actor(row.id),
    )
    return idempotency.Outcome(200, "member", str(row.id), load_member(conn, str(row.id)))


def _human(
    conn: Connection, caller: Caller, until: datetime | None, body: LimitIn, given: set[str]
) -> idempotency.Outcome:
    if "harness" in given:
        raise invalid({"harness": "agents_only"})
    assert caller.human_id is not None
    # Full names (§6.25), each a project the caller is a member of.
    slugs = list(dict.fromkeys(body.show_reason_in or []))
    if slugs:
        mine = set(
            namespace.full_names(
                conn,
                conn.execute(
                    select(t.membership.c.project_id).where(
                        t.membership.c.human_id == caller.human_id,
                        t.membership.c.active.is_(True),
                    )
                ).scalars(),
            ).values()
        )
        if any(slug not in mine for slug in slugs):
            raise invalid({"show_reason_in": "not_a_member"})
    availability.set_human_limit(
        conn,
        caller.human_id,
        until,
        reason=body.reason,
        show_reason_in=slugs,
        actor_of=caller.actor,
    )
    return idempotency.Outcome(200, "me", caller.human_id, human_body(conn, caller.human_id))


idempotency.LOADERS["me"] = idempotency.plain(human_body)
