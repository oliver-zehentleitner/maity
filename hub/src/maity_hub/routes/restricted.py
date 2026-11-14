"""A card's restricted text: `GET`, `PUT`, `DELETE …/tasks/{id}/restricted` (docs/api.md
§6.4 "Restricted text", §6.1 "Restricted access").

The order of the checks is the contract's: the card, the bridge, the set, good standing,
then the body, a write that changes nothing, the caps, `base_version` and the quota. The
body is read only after the access checks, never by a model in the signature, so that no
outsider reaches a validation answer. Nothing here puts the text in an error, an event, a
log line or a stored idempotent answer; a write that changes the text writes one
`restricted_changed` with ids, version and action only (`restricted.card_changed`)."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, func, insert, select, update

from maity_hub import clock, idempotency, restricted
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.auth import sessions
from maity_hub.auth.caller import Caller
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.namespace import ProjectRoute
from maity_hub.policy import CLOSED_STATES
from maity_hub.routes.tasks import _locked, _project_card
from maity_hub.views import deleted, ts

router = APIRouter(route_class=ProjectRoute)

TEXT_MAX = 1000
HISTORY_SHOWN = 50
QUOTA = 200  # cards with a text per project
MEMBERSHIP_CAP = 20  # changing PUT or DELETE per membership per hour
CARD_CAP = 10  # changing PUT per card per hour; a DELETE never counts here
WINDOW = timedelta(hours=1)
# Line feed and tab stay; every other control, format, private-use or surrogate code point,
# and the line and paragraph separators, are refused (§6.4 "The text").
REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Co", "Cs", "Zl", "Zp"})
RESOURCE = "restricted_text"
PATH = "/projects/{owner}/{slug}/tasks/{card_id}/restricted"


# --- access ----------------------------------------------------------------------------------


def _refused(reason: str, message: str) -> ApiError:
    return ApiError(403, "forbidden", message, {"reason": reason})


def _admit(conn: Connection, caller: Caller, slug: str, card_id: str) -> tuple[Membership, Any]:
    """The access check, before anything reads the body (§6.4 "Access"): the card is found,
    a `Maity-For` call is refused, the caller is in the set, a human's session is in good
    standing. The answer outside the set is the same whether or not the card has a text."""
    mine = membership(conn, caller, slug)
    mine.require("project:read")
    card = _project_card(conn, mine, card_id)
    if mine.bridged or caller.bridge is not None:
        raise _refused("bridge_no_restricted", "a bridged call reaches no restricted text")
    if not restricted.in_set(conn, mine.project, mine.id):
        raise _refused("restricted", "you are not in this project's restricted-access set")
    if caller.kind == "human":
        session = None
        if caller.human_session is not None:
            session = conn.execute(
                select(t.human_session).where(t.human_session.c.id_hash == caller.human_session)
            ).first()
        if session is None or not sessions.good_standing(session):
            raise _refused(
                "not_in_good_standing", "confirm this session's sign-in to read restricted text"
            )
    return mine, card


# --- the body --------------------------------------------------------------------------------


def _raw(request: Request) -> bytes:
    body = request.scope.get("state", {}).get("body", b"")
    return body if isinstance(body, bytes) else b""


def _text(value: Any) -> str:
    """The text as stored, or `invalid` naming why (§6.4 "The text"): never trimmed."""
    if not isinstance(value, str):
        raise invalid({"text": "string_type" if value is not None else "required"})
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise invalid({"text": "empty"}, "a restricted text is 1 to 1000 characters")
    if any(unicodedata.category(c) in REFUSED_CATEGORIES and c not in "\n\t" for c in text):
        raise invalid({"text": "control_character"}, "the text holds a refused character")
    if len(text) > TEXT_MAX:
        raise invalid({"text": "too_long"}, "a restricted text is 1 to 1000 characters")
    return text


def _version(value: Any, field: str = "base_version") -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise invalid({field: "int_type" if not isinstance(value, int) else "greater_than_equal"})
    return value


def _put_body(raw: bytes) -> tuple[str, int]:
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        raise invalid({"body": "not_json"}) from None
    if not isinstance(data, dict):
        raise invalid({"body": "not_an_object"})
    extra = sorted(set(data) - {"text", "base_version"})
    if extra:
        raise invalid({name: "extra_forbidden" for name in extra})
    if "text" not in data:
        raise invalid({"text": "required"})
    text = _text(data["text"])
    if data.get("base_version") is None:
        raise invalid({"base_version": "required"}, "name the text's version you read")
    return text, _version(data["base_version"])


def _query_version(request: Request) -> int | None:
    extra = sorted(set(request.query_params) - {"base_version"})
    if extra:
        raise invalid({name: "extra_forbidden" for name in extra})
    given = request.query_params.get("base_version")
    if given is None:
        return None
    # ASCII digits only: `str.isdigit` also passes "²" and other Unicode digits that `int`
    # refuses, and `int` refuses an overlong number too; each is `invalid`, never a 500.
    if re.fullmatch(r"[0-9]+", given) is None:
        raise invalid({"base_version": "int_parsing"})
    try:
        return int(given)
    except ValueError:
        raise invalid({"base_version": "int_parsing"}) from None


# --- views -----------------------------------------------------------------------------------


def _people(conn: Connection, membership_ids: set[int]) -> dict[int, dict[str, Any]]:
    """`{kind, id, handle}` per membership; a deleted account without its handle (§2.9)."""
    if not membership_ids:
        return {}
    rows = conn.execute(
        select(
            t.membership.c.id,
            t.membership.c.human_id,
            t.membership.c.agent_id,
            t.human.c.handle.label("human_handle"),
            t.human.c.deleted_at,
            t.agent_profile.c.handle.label("agent_handle"),
        )
        .select_from(t.membership)
        .outerjoin(t.human, t.human.c.id == t.membership.c.human_id)
        .outerjoin(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(t.membership.c.id.in_(membership_ids))
    ).all()
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        if row.agent_id:
            out[row.id] = {"kind": "agent", "id": row.agent_id, "handle": row.agent_handle}
        else:
            handle = None if deleted(row) else row.human_handle
            out[row.id] = {"kind": "human", "id": row.human_id, "handle": handle}
    return out


def _row(conn: Connection, card_id: str) -> Any:
    return conn.execute(
        select(t.task_restricted).where(t.task_restricted.c.task_id == card_id)
    ).first()


def _state(conn: Connection, card_id: str, row: Any) -> dict[str, Any]:
    """The answer of a write: the read's shape without `text` and `history`."""
    if row is None:
        return {"task_id": card_id, "version": 0, "updated_by": None, "updated_at": None}
    by = _people(conn, {row.updated_by})
    return {
        "task_id": card_id,
        "version": row.version,
        "updated_by": by.get(row.updated_by),
        "updated_at": ts(row.updated_at),
    }


def _read(conn: Connection, card_id: str) -> dict[str, Any]:
    row = _row(conn, card_id)
    entries = conn.execute(
        select(t.task_restricted_history)
        .where(t.task_restricted_history.c.task_id == card_id)
        .order_by(t.task_restricted_history.c.version.desc())
        .limit(HISTORY_SHOWN)
    ).all()
    people = _people(conn, {e.author for e in entries} | ({row.updated_by} if row else set()))
    return {
        "task_id": card_id,
        "text": row.text if row is not None else None,
        **{k: v for k, v in _state(conn, card_id, row).items() if k != "task_id"},
        "history": [
            {"version": e.version, "action": e.action, "by": people.get(e.author), "at": ts(e.at)}
            for e in entries
        ],
    }


def _load(conn: Connection, card_id: str, _request: Request) -> dict[str, Any]:
    # A replay answers only after `_admit` passed again (below): the current state, never
    # the text.
    return _state(conn, card_id, _row(conn, card_id))


idempotency.register(RESOURCE, _load, idempotency.in_project(idempotency.column_of(t.card)))


# --- caps ------------------------------------------------------------------------------------


def _retry_after(oldest: datetime, now: datetime) -> int:
    return max(1, math.ceil((oldest + WINDOW - now).total_seconds()))


def _caps(conn: Connection, mine: Membership, card_id: str, *, put: bool, now: datetime) -> None:
    """`rate_limited` while the changing writes of the last hour reach a cap (§6.4, §1.7).
    Counted from the history under the project lock: exact, and only what changed counts."""
    since = now - WINDOW
    h = t.task_restricted_history
    mine_count, mine_oldest = conn.execute(
        select(func.count(), func.min(h.c.at)).where(h.c.author == mine.id, h.c.at > since)
    ).one()
    if mine_count >= MEMBERSHIP_CAP:
        raise rate_limited(_retry_after(mine_oldest, now))
    if not put:
        return
    card_count, card_oldest = conn.execute(
        select(func.count(), func.min(h.c.at)).where(
            h.c.task_id == card_id, h.c.action == "set", h.c.at > since
        )
    ).one()
    if card_count >= CARD_CAP:
        raise rate_limited(_retry_after(card_oldest, now))


def _conflict(row: Any, base_version: int) -> ApiError:
    return ApiError(
        409,
        "conflict",
        "the restricted text changed since you read it; read it and decide again",
        {"current_version": row.version if row is not None else 0, "base_version": base_version},
    )


def _write(
    conn: Connection, mine: Membership, card: Any, row: Any, text: str | None, now: datetime
) -> Any:
    version = (row.version if row is not None else 0) + 1
    values = {"text": text, "version": version, "updated_by": mine.id, "updated_at": now}
    if row is None:
        conn.execute(
            insert(t.task_restricted).values(task_id=card.id, project_id=card.project_id, **values)
        )
    else:
        conn.execute(
            update(t.task_restricted).where(t.task_restricted.c.task_id == card.id).values(**values)
        )
    conn.execute(
        insert(t.task_restricted_history).values(
            task_id=card.id,
            version=version,
            action="set" if text is not None else "cleared",
            author=mine.id,
            at=now,
        )
    )
    return _row(conn, card.id)


# --- routes ----------------------------------------------------------------------------------


@router.get(PATH)
def get_restricted(slug: str, card_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    """Allowed on closed cards and in every project state (§6.4)."""
    with engine_of(request).begin() as conn:
        _mine, card = _admit(conn, caller, slug, card_id)
        return JSONResponse(_read(conn, card.id))


def _admit_locked(
    conn: Connection, caller: Caller, slug: str, card_id: str
) -> tuple[Membership, Any]:
    """The project lock first, then the access check inside it (§6.4 "Access"): a set or
    membership change committed before the lock is seen, so a caller it removed writes
    nothing. The project the write decides on is the one read under the lock."""
    locked = _locked(conn, membership(conn, caller, slug))
    mine, card = _admit(conn, caller, slug, card_id)
    return replace(mine, project=locked.project), card


def _guarded(request: Request, caller: Caller, slug: str, card_id: str) -> None:
    """The access check ahead of the idempotent run: a repeat of a stored call answers only
    after it passed again, so a caller no longer in the set gets `forbidden`, never the
    stored answer (§6.4 "Idempotency")."""
    with engine_of(request).begin() as conn:
        _admit(conn, caller, slug, card_id)


@router.put(PATH)
def put_restricted(slug: str, card_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    _guarded(request, caller, slug, card_id)

    def action(conn: Connection) -> idempotency.Outcome:
        mine, card = _admit_locked(conn, caller, slug, card_id)
        text, base_version = _put_body(_raw(request))
        row = _row(conn, card.id)
        if row is not None and row.text == text:
            return idempotency.Outcome(200, RESOURCE, card.id, _state(conn, card.id, row))
        if mine.project.state in CLOSED_STATES:
            raise ApiError(409, "project_closed", f"the project is {mine.project.state}")
        now = clock.now()
        _caps(conn, mine, card.id, put=True, now=now)
        if base_version != (row.version if row is not None else 0):
            raise _conflict(row, base_version)
        if (row is None or row.text is None) and restricted.cards_with_text(
            conn, card.project_id
        ) >= QUOTA:
            raise ApiError(
                409,
                "restricted_quota",
                f"at most {QUOTA} cards of a project have a restricted text",
                {"max": QUOTA},
            )
        row = _write(conn, mine, card, row, text, now)
        restricted.card_changed(
            conn, mine.project, card.id, row.version, "set", mine.id, caller.actor(mine.id), now
        )
        return idempotency.Outcome(200, RESOURCE, card.id, _state(conn, card.id, row))

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete(PATH)
def delete_restricted(slug: str, card_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    """Clears the text; allowed in every project state (§6.4)."""
    _guarded(request, caller, slug, card_id)

    def action(conn: Connection) -> idempotency.Outcome:
        mine, card = _admit_locked(conn, caller, slug, card_id)
        base_version = _query_version(request)
        row = _row(conn, card.id)
        if row is None or row.text is None:
            return idempotency.Outcome(200, RESOURCE, card.id, _state(conn, card.id, row))
        now = clock.now()
        _caps(conn, mine, card.id, put=False, now=now)
        if base_version is not None and base_version != row.version:
            raise _conflict(row, base_version)
        row = _write(conn, mine, card, row, None, now)
        restricted.card_changed(
            conn, mine.project, card.id, row.version, "cleared", mine.id, caller.actor(mine.id), now
        )
        return idempotency.Outcome(200, RESOURCE, card.id, _state(conn, card.id, row))

    return idempotency.run(engine_of(request), request, caller, action)
