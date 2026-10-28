"""`/projects/{owner}/{slug}/attachments` (docs/api.md §8.7): upload, read, list and delete.

An upload is raw bytes with the name in the query. An image is decoded and encoded again
outside the transaction, in the avatar decoder's process; the blob is written before the
row is committed, and removed again when the transaction does not commit. Reading asks
the one question the message does: may this caller read it.
"""

from __future__ import annotations

import hashlib
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import attachment_store as blobs
from maity_hub import attachments, avatars, clock, group_chats, idempotency, paging
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.events import emit, lock_project, on_commit, on_rollback
from maity_hub.ids import new_id
from maity_hub.namespace import ProjectRoute
from maity_hub.routes.conversations import Outsider, _reader
from maity_hub.routes.events import chat_parties
from maity_hub.routes.project_images import _matches
from maity_hub.scopes import in_admin_team

router = APIRouter(route_class=ProjectRoute)

CLOSED = ("accepted", "archived")
HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "private, no-cache",
}


def _row(conn: Connection, mine: Membership, attachment_id: str) -> Any:
    found = conn.execute(
        select(t.attachment).where(
            t.attachment.c.id == attachment_id, t.attachment.c.project_id == mine.project.id
        )
    ).first()
    if found is None:
        raise not_found()
    return found


def load(conn: Connection, attachment_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.attachment).where(t.attachment.c.id == attachment_id)).one()
    return attachments.view(conn, [row])[0]


idempotency.LOADERS["attachment"] = idempotency.plain(load)


def _admin_human(mine: Membership) -> bool:
    return mine.kind == "human" and mine.may("members:admin")


# --- upload --------------------------------------------------------------------------------


def _require_post(mine: Any) -> None:
    """`events:post`, or a guest's: it sends attachments with its chat (§2.3, §8.7)."""
    if mine.trust != "guest":
        mine.require("events:post")


@router.post("/projects/{owner}/{slug}/attachments")
def upload(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    engine = engine_of(request)
    settings = settings_of(request)
    with engine.begin() as conn:
        mine = membership(conn, caller, slug)
        _require_post(mine)
        blobs.store_of(settings)  # unconfigured: refused before the body is looked at
    replayed = idempotency.replay_first(engine, request, caller)
    if replayed is not None:  # a repeat is the stored answer: no decode, no count
        return replayed
    raw_name = request.query_params.get("name")
    if raw_name is None or not raw_name.strip():
        raise invalid({"name": "required"})
    data: bytes = request.scope["state"].get("body", b"")
    declared = attachments.declared_type(request.headers.get("content-type"))
    sniffed = attachments.sniff(data)
    if sniffed is not None and declared != sniffed:
        raise invalid({"body": "unsupported_type"}, "the declared type does not name the image")
    if mine.project.state in CLOSED:
        raise ApiError(409, "project_closed", f"the project is {mine.project.state}")
    rate_key = str(mine.id)
    received = len(data)  # what the rate was charged: the refund is this, whatever follows
    attachments.check_rate(rate_key, received)
    kind, width, height = "file", None, None
    kept_type = attachments.file_type(declared)
    try:
        if sniffed is not None:
            image = avatars.decode_attachment(settings, data, sniffed)
            data, kept_type, width, height, kind = (
                image.data,
                image.type,
                image.width,
                image.height,
                "image",
            )
    except ApiError:
        attachments.give_back(rate_key, received)  # nothing was stored: not counted
        raise
    name = attachments.clean_name(raw_name, image_type=sniffed)
    store = blobs.store_of(settings)
    attachment_id = new_id("attachment")

    def action(conn: Connection) -> idempotency.Outcome:
        project = lock_project(conn, membership(conn, caller, slug).project.id)
        # The decode took time: the right to post and the project's state are read again,
        # under the lock, right before the insert.
        locked = membership(conn, caller, slug)
        _require_post(locked)
        if project.state in CLOSED:
            raise ApiError(409, "project_closed", f"the project is {project.state}")
        used = attachments.used(conn, locked.project.id)
        if used + len(data) > settings.attachment_quota:
            raise attachments.quota_error("project", used=used, quota=settings.attachment_quota)
        count, held = attachments.pending_of(conn, locked.id)
        if count + 1 > attachments.PENDING_COUNT or held + len(data) > attachments.PENDING_BYTES:
            raise attachments.quota_error(
                "pending",
                used=held,
                quota=attachments.PENDING_BYTES,
                count=count,
                max=attachments.PENDING_COUNT,
            )
        key = blobs.key_of(locked.project.id, attachment_id)
        store.put(key, data)  # the blob first, the row after
        on_rollback(conn, lambda: store.delete(key))
        conn.execute(
            insert(t.attachment).values(
                id=attachment_id,
                project_id=locked.project.id,
                uploaded_by=locked.id,
                name=name,
                size=len(data),
                type=kept_type,
                kind=kind,
                sha256=attachments.digest(data),
                width=width,
                height=height,
                uploaded_at=clock.now(),
            )
        )
        return idempotency.Outcome(201, "attachment", attachment_id, load(conn, attachment_id))

    try:
        return idempotency.run(engine, request, caller, action)
    except BaseException:
        attachments.give_back(rate_key, received)
        raise


# --- reading -------------------------------------------------------------------------------


@router.get("/projects/{owner}/{slug}/attachments/{attachment_id}")
def get_attachment(
    slug: str, attachment_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    blobs.store_of(settings_of(request))  # every attachment call: configured, or 409
    with engine_of(request).begin() as conn:
        mine = _reader(conn, caller, slug)
        if isinstance(mine, Membership):
            mine.require("project:read")
        row = _row(conn, mine, attachment_id)
        if not attachments.readable(conn, mine, row):
            raise not_found()
        return JSONResponse(attachments.view(conn, [row])[0])


@router.get("/projects/{owner}/{slug}/attachments/{attachment_id}/content")
def get_content(slug: str, attachment_id: str, request: Request, caller: AnyCaller) -> Response:
    settings = settings_of(request)
    store = blobs.store_of(settings)  # also before a 304: configured, or 409
    with engine_of(request).begin() as conn:
        mine = _reader(conn, caller, slug)
        if isinstance(mine, Membership):
            mine.require("project:read")
        row = _row(conn, mine, attachment_id)
        # Authorized first, and only then compared: no `304` for a caller who may not read.
        if row.deleted_at is not None or not attachments.readable(conn, mine, row):
            raise not_found()
    tag = f'"{row.sha256}"'
    headers = {**HEADERS, "ETag": tag}
    if _matches(request.headers.get("if-none-match"), tag):
        return Response(status_code=304, headers=headers)
    data = store.get(blobs.key_of(row.project_id, row.id))
    if data is None:
        # The bytes may have gone since the row was read: a redaction or a deletion commits
        # and removes them. Read the row again; gone or unreadable now is `not_found`.
        with engine_of(request).begin() as conn:
            mine = _reader(conn, caller, slug)
            again = _row(conn, mine, attachment_id)
            if again.deleted_at is not None or not attachments.readable(conn, mine, again):
                raise not_found()
    if data is None or hashlib.sha256(data).hexdigest() != row.sha256:
        raise ApiError(500, "internal", "the stored bytes do not match their digest")
    if row.kind == "image":
        inline = request.query_params.get("download") != "1"
        headers["Content-Disposition"] = attachments.disposition(row.name, inline=inline)
        return Response(content=data, media_type=row.type, headers=headers)
    headers["Content-Disposition"] = attachments.disposition(row.name, inline=False)
    return Response(content=data, media_type="application/octet-stream", headers=headers)


@router.get("/projects/{owner}/{slug}/attachments")
def list_pending(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    blobs.store_of(settings_of(request))  # every attachment call: configured, or 409
    if request.query_params.get("status") != "pending":
        raise invalid({"status": "unknown"}, "only status=pending is listed")
    narrowed = request.query_params.get("uploaded_by")
    limit_raw = request.query_params.get("limit", "50")
    if not limit_raw.isdigit() or not 1 <= int(limit_raw) <= 200:
        raise invalid({"limit": "out_of_range"})
    limit = int(limit_raw)
    bound = paging.scope(uploaded_by=narrowed)
    cursor = request.query_params.get("cursor")
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        everyone = _admin_human(mine)
        if narrowed not in (None, mine.principal_id) and not everyone:
            if mine.kind == "agent" and in_admin_team(mine.trust, mine.role):
                raise humans_only("an agent never reads another member's pending uploads")
            raise forbidden("members:admin")
        query = select(t.attachment).where(
            t.attachment.c.project_id == mine.project.id,
            t.attachment.c.message_seq.is_(None),
            t.attachment.c.deleted_at.is_(None),
        )
        if not everyone or narrowed == mine.principal_id:
            query = query.where(t.attachment.c.uploaded_by == mine.id)
        elif narrowed is not None:
            query = query.where(
                t.attachment.c.uploaded_by.in_(
                    select(t.membership.c.id).where(
                        t.membership.c.project_id == mine.project.id,
                        (t.membership.c.agent_id == narrowed)
                        | (t.membership.c.human_id == narrowed),
                    )
                )
            )
        if cursor is not None:
            after_at, after_id = paging.uncursor(cursor, bound)
            query = query.where(
                (t.attachment.c.uploaded_at > after_at)
                | ((t.attachment.c.uploaded_at == after_at) & (t.attachment.c.id > after_id))
            )
        rows = conn.execute(
            query.order_by(t.attachment.c.uploaded_at, t.attachment.c.id).limit(limit + 1)
        ).all()
        page = rows[:limit]
        next_cursor = (
            paging.cursor(page[-1].uploaded_at, page[-1].id, bound) if len(rows) > limit else None
        )
        items = [attachments.view(conn, [row], whole=row.uploaded_by == mine.id)[0] for row in page]
        return JSONResponse({"items": items, "next_cursor": next_cursor})


# --- deleting ------------------------------------------------------------------------------


@router.delete("/projects/{owner}/{slug}/attachments/{attachment_id}")
def delete_attachment(
    slug: str, attachment_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    store = blobs.store_of(settings_of(request))

    def action(conn: Connection) -> idempotency.Outcome:
        mine = _reader(conn, caller, slug)
        project = lock_project(conn, mine.project.id)
        del project
        row = _row(conn, mine, attachment_id)
        if row.message_seq is not None:
            return _delete_sent(conn, mine, caller, row, store)
        if isinstance(mine, Outsider):
            raise not_found()
        _require_post(mine)
        own = row.uploaded_by == mine.id
        if not own and not _admin_human(mine):
            if mine.kind == "agent" and in_admin_team(mine.trust, mine.role):
                raise humans_only("an agent deletes only what it sent")
            raise not_found()  # another member's pending upload does not exist for it
        # A pending upload leaves no tombstone and no event; the bytes go once the row is.
        conn.execute(delete(t.attachment).where(t.attachment.c.id == row.id))
        on_commit(conn, lambda: store.delete(blobs.key_of(row.project_id, row.id)))
        shown = attachments.view(conn, [row], whole=own)[0]
        return idempotency.Outcome(200, None, None, shown)

    return idempotency.run(engine_of(request), request, caller, action)


def _not_a_participant() -> ApiError:
    return ApiError(
        403, "forbidden", "only a human in the chat deletes here", {"reason": "not_a_participant"}
    )


def _delete_sent(
    conn: Connection, mine: Any, caller: Any, row: Any, store: blobs.LocalStore
) -> idempotency.Outcome:
    """An attachment a message carries (§8.7): readable as the message is, deleted by its
    uploader, by a human in the chat now (a chat message), or by a human with
    `members:admin` (a project message). The row stays as a tombstone, the bytes go after
    the commit, and `attachment_deleted` reaches whoever reads the message."""
    if not attachments.readable(conn, mine, row):
        raise not_found()  # what the caller cannot read does not exist for it
    event = conn.execute(select(t.event).where(t.event.c.seq == row.message_seq)).one()
    if isinstance(mine, Outsider):
        raise ApiError(
            403, "forbidden", "an owner reads along and does not act", {"reason": "observer"}
        )
    if row.deleted_at is not None:  # a deleted one answers with its tombstone (§1.5)
        return idempotency.Outcome(200, None, None, attachments.view(conn, [row])[0])
    if row.uploaded_by != mine.id:
        if mine.kind == "agent":
            raise humans_only("an agent deletes only what it sent")
        if event.conversation_id is None:
            if not mine.may("members:admin"):
                raise forbidden("members:admin")
        elif group_chats.is_group(event.conversation_id):
            if group_chats.access(conn, event.conversation_id, mine) != "participant":
                raise _not_a_participant()
        else:  # a direct chat: its human party
            _, human = chat_parties(conn, mine, event.conversation_id)
            if mine.id != human.id:
                raise _not_a_participant()
    conn.execute(
        update(t.attachment)
        .where(t.attachment.c.id == row.id, t.attachment.c.deleted_at.is_(None))
        .values(deleted_at=clock.now(), deleted_by=mine.principal_id, deleted_reason="deleted")
    )
    on_commit(conn, lambda: store.delete(blobs.key_of(row.project_id, row.id)))
    emit(
        conn,
        mine.project.id,
        "attachment_deleted",
        _audience(conn, event),
        {
            "attachment_id": row.id,
            "message_seq": row.message_seq,
            "reason": "deleted",
            "by": mine.principal_id,
        },
        actor=caller.actor(mine.id),
        subject=("event", str(event.seq)),
        # A chat's notice is the chat's, as the message was: no see-all reaches it.
        conversation_id=event.conversation_id,
    )
    fresh = conn.execute(select(t.attachment).where(t.attachment.c.id == row.id)).one()
    return idempotency.Outcome(200, None, None, attachments.view(conn, [fresh])[0])


def _audience(conn: Connection, event: Any) -> list[str]:
    """Whoever reads the message, as `event_redacted` reaches it (§8.5): a project message's
    own audience; a direct chat's two parties; a group chat's current participants (their
    observers read along by the owner rule)."""
    if event.conversation_id is None:
        return list(event.audience or [])
    if group_chats.is_group(event.conversation_id):
        return group_chats.audience(group_chats.stays(conn, event.conversation_id))
    return list(event.audience or [])
