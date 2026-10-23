"""Card links, the edit history and notes (docs/api.md §6.13, §6.15, §6.16).

A link added or removed is a change to the card (`task_updated`, a history entry); a
note never is. Both are refused in a closed project when they add, never when they
remove.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Connection, and_, insert, or_, select, update

from maity_hub import clock, forge, idempotency, mentions, namespace, paging
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.auth import credentials
from maity_hub.auth.caller import Caller
from maity_hub.auth.leaks import revoke_leaked
from maity_hub.board import history, importing, links, notes
from maity_hub.deps import AnyCaller, engine_of, reader_of
from maity_hub.errors import ApiError, humans_only, invalid, not_found, rate_limited
from maity_hub.events import emit, on_rollback, transaction
from maity_hub.ids import new_id
from maity_hub.models import Strict, Written, markdown
from maity_hub.namespace import ProjectRoute
from maity_hub.policy import CLOSED_STATES
from maity_hub.routes.tasks import TaskCreate, _locked, _project_card, audience, create_card
from maity_hub.views import shape_deleted

router = APIRouter(route_class=ProjectRoute)

PAGE_DEFAULT, PAGE_MAX = 50, 200
REDACTION_AUDIENCE = ["trust:owner", "trust:admin"]  # every redaction's notice (§8.5)


class NoteIn(Written):
    body: str = markdown(min_length=1)


class ResolveIn(Strict):
    state: str
    reason: str | None = markdown(default=None)


class RedactIn(Strict):
    reason: str = markdown(min_length=1)


# --- shared --------------------------------------------------------------------------------


def _card(conn: Connection, mine: Membership, card_id: str) -> Any:
    return _project_card(conn, mine, card_id)


def _refuse_closed(mine: Membership) -> None:
    """A closed project refuses what adds to it, never what removes (§6.13, §6.16)."""
    if mine.project.state in CLOSED_STATES:
        raise ApiError(409, "project_closed", f"the project is {mine.project.state}")


def changed(
    conn: Connection,
    mine: Membership,
    caller: Caller,
    card: Any,
    values: dict[str, Any],
    entry_ids: list[str],
) -> int:
    """A member's change to a card that is not a PATCH: `updated_at`, `task_updated`
    with `fields`, the new values and the history entries, the entries tied to it."""
    conn.execute(
        update(t.card)
        .where(t.card.c.id == card.id)
        .values(
            updated_at=clock.now(),
            changed_by_credential=caller.credential_id,
            changed_via=caller.via,
        )
    )
    seq = emit(
        conn,
        mine.project.id,
        "task_updated",
        audience(conn, card),
        {
            "id": card.id,
            "fields": sorted(values),
            **values,
            "history": entry_ids,
            "project_state": mine.project.state,
        },
        actor=caller.actor(mine.id),
        subject=("task", card.id),
    )
    history.stamp(conn, entry_ids, seq)
    return seq


# --- links (§6.13) -------------------------------------------------------------------------


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/links")
def post_link(
    slug: str, card_id: str, body: links.LinkIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("tasks:write")
        mine = _locked(conn, mine)
        card = _card(conn, mine, card_id)
        _refuse_closed(mine)
        shown = links.add(conn, card, body, mine.project.repository_url, mine.id)
        entry = history.record(
            conn, card, {}, caller.actor(mine.id), extra=[("links", None, shown)]
        )
        changed(conn, mine, caller, card, {"links": {"added": shown}}, entry)
        return idempotency.Outcome(201, "link", shown["id"], shown)

    response = idempotency.run(engine_of(request), request, caller, action)
    observe_soon(request, slug, response)
    return response


def observe_soon(request: Request, slug: str, response: JSONResponse) -> None:
    """A new forge link is read after the commit, by the probe's worker, never here:
    a job for the project's links (§6.13)."""
    worker = request.app.state.probe
    if worker is None or response.status_code != 201:
        return
    with engine_of(request).connect() as conn:
        project = namespace.resolve(conn, slug)
    if project is not None:
        worker.links_added(project.id)


def load_link(conn: Connection, link_id: str) -> dict[str, Any]:
    """A replayed add: the link as it is, or once removed as its add entry holds it."""
    row = conn.execute(select(t.card_link).where(t.card_link.c.id == link_id)).first()
    if row is not None:
        return links.link_view(conn, row)
    entry = conn.execute(
        select(t.card_history).where(
            t.card_history.c.link_id == link_id, t.card_history.c.link_change == "added"
        )
    ).first()
    if entry is None:
        raise not_found()
    return history.link_shown(entry)


def load_removed_link(conn: Connection, entry_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.card_history).where(t.card_history.c.id == entry_id)).one()
    return history.link_shown(row)


idempotency.LOADERS["link"] = idempotency.plain(load_link)
idempotency.LOADERS["removed_link"] = idempotency.plain(load_removed_link)


@router.delete("/projects/{owner}/{slug}/tasks/{card_id}/links/{link_id}")
def delete_link(
    slug: str, card_id: str, link_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _card(conn, mine, card_id)
        row = conn.execute(
            select(t.card_link).where(t.card_link.c.id == link_id, t.card_link.c.card_id == card.id)
        ).first()
        if row is None:
            # Removed already: a DELETE is idempotent (§1.5) and answers with what it
            # removed, from the removal's entry; a link that never was is not_found.
            removal = history.link_entry(conn, card.id, link_id, removed=True)
            if removal is None:
                raise not_found()
            return idempotency.Outcome(200, "removed_link", removal.id, history.link_shown(removal))
        holder = card.claim_holder == mine.id
        if not (row.added_by == mine.id or holder or card.created_by == mine.id):
            mine.require("tasks:admin")
        shown = links.link_view(conn, row)
        conn.execute(t.card_link.delete().where(t.card_link.c.id == row.id))
        entry = history.record(
            conn, card, {}, caller.actor(mine.id), extra=[("links", shown, None)]
        )
        changed(conn, mine, caller, card, {"links": {"removed": shown}}, entry)
        # A replay answers with what was removed, from its history entry: the row is gone.
        return idempotency.Outcome(200, "removed_link", entry[0], shown)

    return idempotency.run(engine_of(request), request, caller, action)


# --- history (§6.15) -----------------------------------------------------------------------


@router.get("/projects/{owner}/{slug}/tasks/{card_id}/history")
def get_history(
    slug: str,
    card_id: str,
    request: Request,
    caller: AnyCaller,
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        card = _card(conn, mine, card_id)
        c = t.card_history.c
        query = select(t.card_history).where(c.card_id == card.id)
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor)
            query = query.where(or_(c.at < after_at, and_(c.at == after_at, c.id < after_id)))
        rows = conn.execute(query.order_by(c.at.desc(), c.id.desc()).limit(limit + 1)).all()
        page = rows[:limit]
        actors = history.members(conn, (r.actor_membership for r in page))
        next_cursor = paging.cursor(page[-1].at, page[-1].id) if len(rows) > limit else None
        return JSONResponse(
            {
                "items": shape_deleted(conn, [history.view(r, actors) for r in page]),
                "next_cursor": next_cursor,
            }
        )


def load_history(conn: Connection, entry_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.card_history).where(t.card_history.c.id == entry_id)).one()
    entry = history.view(row, history.members(conn, [row.actor_membership]))
    return dict(shape_deleted(conn, [entry])[0])


idempotency.LOADERS["history"] = idempotency.plain(load_history)


def _redactor(mine: Membership, caller: Caller) -> None:
    """`events:admin`, human memberships only (§6.15, §6.16)."""
    if caller.kind != "human":
        raise humans_only("only a human redacts")
    mine.require("events:admin")


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/history/{history_id}/redact")
def redact_history(
    slug: str, card_id: str, history_id: str, body: RedactIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        _redactor(mine, caller)
        mine = _locked(conn, mine)
        card = _card(conn, mine, card_id)
        row = conn.execute(
            select(t.card_history).where(
                t.card_history.c.id == history_id, t.card_history.c.card_id == card.id
            )
        ).first()
        if row is None:
            raise not_found()
        if history.redact(conn, row, history.tombstone(body.reason, mine.principal_id)):
            emit(
                conn,
                mine.project.id,
                "event_redacted",
                REDACTION_AUDIENCE,
                {"history_id": row.id, "task_id": card.id, "reason": body.reason},
                actor=caller.actor(mine.id),
                subject=("task", card.id),
            )
        return idempotency.Outcome(200, "history", row.id, load_history(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


# --- notes (§6.16) -------------------------------------------------------------------------


def _note_view(conn: Connection, row: Any) -> dict[str, Any]:
    note = notes.view(row, history.members(conn, [row.author]))
    return dict(shape_deleted(conn, [note])[0])


def load_note(conn: Connection, note_id: str) -> dict[str, Any]:
    return _note_view(
        conn, conn.execute(select(t.card_note).where(t.card_note.c.id == note_id)).one()
    )


idempotency.LOADERS["note"] = idempotency.plain(load_note)


def _note(conn: Connection, card: Any, note_id: str) -> Any:
    row = conn.execute(
        select(t.card_note).where(t.card_note.c.id == note_id, t.card_note.c.card_id == card.id)
    ).first()
    if row is None:
        raise not_found()
    return row


def _task_ref(card: Any) -> dict[str, Any]:
    return {"id": card.id, "title": card.title, "status": card.status}


def _members(conn: Connection, *membership_ids: int | None) -> list[str]:
    from maity_hub.views import principal_ids

    found = principal_ids(conn, membership_ids)
    return [f"member:{found[i]}" for i in membership_ids if i is not None]


@router.get("/projects/{owner}/{slug}/tasks/{card_id}/notes")
def list_notes(
    slug: str,
    card_id: str,
    request: Request,
    caller: AnyCaller,
    state: str = "open",
    limit: int = Query(default=PAGE_DEFAULT, ge=1, le=PAGE_MAX),
    cursor: str | None = None,
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        card = _card(conn, mine, card_id)
        c = t.card_note.c
        query = select(t.card_note).where(c.card_id == card.id)
        if state != "all":
            wanted = [s for s in state.split(",") if s]
            if not wanted or any(s not in notes.STATES for s in wanted):
                raise invalid({"state": "unknown"})
            query = query.where(c.state.in_(wanted))
        bound = paging.scope(state=state)
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor, bound)
            query = query.where(
                or_(c.created_at > after_at, and_(c.created_at == after_at, c.id > after_id))
            )
        rows = conn.execute(query.order_by(c.created_at, c.id).limit(limit + 1)).all()
        page = rows[:limit]
        authors = history.members(conn, (r.author for r in page))
        next_cursor = (
            paging.cursor(page[-1].created_at, page[-1].id, bound) if len(rows) > limit else None
        )
        return JSONResponse(
            {
                "items": shape_deleted(conn, [notes.view(r, authors) for r in page]),
                "next_cursor": next_cursor,
            }
        )


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/notes")
def post_note(
    slug: str, card_id: str, body: NoteIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    if len(body.body.encode()) > notes.BODY_MAX:
        raise invalid({"body": "too_long"}, "a note is at most 4 KiB")

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        if mine.trust != "guest":  # a guest comments with notes, whatever its role (§2.3)
            mine.require("tasks:write")
        mine = _locked(conn, mine)
        card = _card(conn, mine, card_id)
        _refuse_closed(mine)
        open_count, total, by_agents = notes.counts(conn, card.id)
        if notes.over_cap(
            open_count=open_count,
            total=total,
            by_agents=by_agents,
            author_is_agent=mine.kind == "agent",
        ):
            raise invalid({"body": "note_cap"}, "the card holds no more notes")
        key = str(mine.id)
        wait = notes.POSTED.hit(key)
        if wait:
            raise rate_limited(wait)
        on_rollback(conn, lambda: notes.POSTED.give_back(key, 1))
        found = mentions.resolve(conn, mine.project.id, body.body, "body")
        note_id = new_id("note")
        conn.execute(
            insert(t.card_note).values(
                id=note_id,
                card_id=card.id,
                author=mine.id,
                author_kind=mine.kind,
                body=body.body,
                mentions=found,
                state="open",
                resolution=None,
                created_at=clock.now(),
                redacted=False,
            )
        )
        shown = load_note(conn, note_id)
        audience = _members(conn, card.claim_holder, card.created_by)
        audience += mentions.tokens(found, mentions.members(found))
        seq = emit(
            conn,
            mine.project.id,
            "note_added",
            list(dict.fromkeys(audience)),
            {"note": shown, "task": _task_ref(card)},
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        conn.execute(update(t.card_note).where(t.card_note.c.id == note_id).values(event_seq=seq))
        return idempotency.Outcome(201, "note", note_id, shown)

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/notes/{note_id}/resolve")
def resolve_note(
    slug: str, card_id: str, note_id: str, body: ResolveIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    if body.state not in notes.RESOLVED:
        raise invalid({"state": "unknown"})

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine = _locked(conn, mine)
        card = _card(conn, mine, card_id)
        # The card's creator or tasks:admin; never its holder for being the holder.
        if card.created_by != mine.id:
            mine.require("tasks:admin")
        row = _note(conn, card, note_id)
        resolution = {
            "by": mine.principal_id,
            "at": clock.rfc3339(clock.now()),
            "reason": body.reason,
        }
        won = conn.execute(
            update(t.card_note)
            .where(t.card_note.c.id == row.id, t.card_note.c.state == "open")
            .values(state=body.state, resolution=resolution)
        ).rowcount
        if won != 1:
            raise ApiError(
                409,
                "invalid_transition",
                "only an open note is resolved",
                {"from": _note(conn, card, note_id).state, "to": body.state},
            )
        emit(
            conn,
            mine.project.id,
            "note_resolved",
            list(dict.fromkeys(_members(conn, row.author, card.claim_holder, card.created_by))),
            {"note_id": row.id, "task_id": card.id, "state": body.state, "resolution": resolution},
            actor=caller.actor(mine.id),
            subject=("task", card.id),
        )
        return idempotency.Outcome(200, "note", row.id, load_note(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


@router.post("/projects/{owner}/{slug}/tasks/{card_id}/notes/{note_id}/redact")
def redact_note(
    slug: str, card_id: str, note_id: str, body: RedactIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        _redactor(mine, caller)
        mine = _locked(conn, mine)
        card = _card(conn, mine, card_id)
        row = _note(conn, card, note_id)
        if notes.redact(conn, row, history.tombstone(body.reason, mine.principal_id)):
            emit(
                conn,
                mine.project.id,
                "event_redacted",
                REDACTION_AUDIENCE,
                {"seq": row.event_seq, "note_id": row.id, "reason": body.reason},
                actor=caller.actor(mine.id),
                subject=("task", card.id),
            )
        return idempotency.Outcome(200, "note", row.id, load_note(conn, row.id))

    return idempotency.run(engine_of(request), request, caller, action)


# --- the import (§6.14) --------------------------------------------------------------------


class ImportIn(Strict):
    issue_url: str = Field(max_length=links.URL_MAX)
    area: str | None = None
    label: str | None = None
    status: str = "open"
    assigned_to: str | None = None
    reason: str | None = markdown(default=None)


def _refuse_credentials(request: Request, issue: dict[str, Any]) -> None:
    """What the forge says passes the check every request body passes (§1.3): a string
    in the hub's credential format in the title, the body or the login is refused as
    `credential_in_payload` before anything is stored, and revoked as a leak."""
    text = "\n".join(str(issue.get(k) or "") for k in ("title", "body", "author_login"))
    found = credentials.find_all(text.encode())
    if not found:
        return
    with transaction(engine_of(request)) as conn:
        revoke_leaked(conn, found)
    raise ApiError(
        400,
        "credential_in_payload",
        "the issue contains a string in the hub's credential format",
    )


@router.post("/projects/{slug}/tasks/import")
def import_issue(slug: str, body: ImportIn, request: Request, caller: AnyCaller) -> JSONResponse:
    """The one write that reads the forge before it answers: the card cannot exist
    without its title. The read runs before the transaction; nothing is stored when
    it fails."""
    fg = reader_of(request)
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("tasks:write")
    # Only then a repeat answers from the first call's result, without reading the forge
    # again (§1.5): a replay is never a way around membership or scope.
    replayed = idempotency.replay_first(engine_of(request), request, caller)
    if replayed is not None:
        return replayed
    project = mine.project
    try:
        ref = links.parse_forge(body.issue_url, "issue", project.repository_url)
    except links.LinkError as error:
        raise invalid({"issue_url": error.code}) from None
    if not links.is_own_repository(ref, project.repository_url):
        raise invalid({"issue_url": "foreign_repository"})  # the hub reads only its own
    if not fg.configured_for(project.repository_url):
        raise ApiError(
            409, "probe_not_configured", "the hub holds no forge token for this repository"
        )
    at = clock.rfc3339(clock.now())
    try:
        issue = fg.issue(ref.repository, ref.number)
    except forge.ForgeUnavailableError:
        raise ApiError(503, "probe_unavailable", "the forge did not answer") from None
    if issue is None:
        raise invalid({"issue_url": "not_found_on_forge"})
    if issue["is_pull_request"]:
        raise invalid({"issue_url": "not_an_issue"})
    _refuse_credentials(request, issue)
    create = TaskCreate(
        title=importing.title(issue),
        body=importing.body(ref.url, issue),
        area=body.area,
        label=body.label,
        status=body.status,
        assigned_to=body.assigned_to,
        reason=body.reason,
        links=[links.LinkIn(kind="issue", forge_url=ref.url)],
    )
    imported_from = {
        "forge_url": ref.url,
        "number": ref.number,
        "author_login": issue["author_login"],
        "imported_at": at,
    }
    observed = links.observed("issue", {**issue, "type": "Issue", "merged": False}, at)

    def action(conn: Connection) -> idempotency.Outcome:
        return create_card(
            conn, caller, slug, create, fg, imported_from=imported_from, observed=observed
        )

    return idempotency.run(engine_of(request), request, caller, action)
