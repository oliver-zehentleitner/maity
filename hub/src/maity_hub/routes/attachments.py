"""`/projects/{slug}/attachments` (docs/api.md §8.7): upload, read, list and delete.

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
from sqlalchemy import Connection, delete, insert, select

from maity_hub import attachment_store as blobs
from maity_hub import attachments, avatars, clock, idempotency, paging
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.events import lock_project, on_commit, on_rollback
from maity_hub.ids import new_id
from maity_hub.routes.project_images import _matches

router = APIRouter()

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


@router.post("/projects/{slug}/attachments")
def upload(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    engine = engine_of(request)
    settings = settings_of(request)
    with engine.begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("events:post")
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
    attachments.check_rate(rate_key, len(data))
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
        attachments.give_back(rate_key, len(data))  # nothing was stored: not counted
        raise
    name = attachments.clean_name(raw_name, image_type=sniffed)
    store = blobs.store_of(settings)
    attachment_id = new_id("attachment")

    def action(conn: Connection) -> idempotency.Outcome:
        locked = membership(conn, caller, slug)
        lock_project(conn, locked.project.id)
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
        attachments.give_back(rate_key, len(data))
        raise


# --- reading -------------------------------------------------------------------------------


@router.get("/projects/{slug}/attachments/{attachment_id}")
def get_attachment(
    slug: str, attachment_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        row = _row(conn, mine, attachment_id)
        if not attachments.readable(conn, mine, row):
            raise not_found()
        return JSONResponse(attachments.view(conn, [row])[0])


@router.get("/projects/{slug}/attachments/{attachment_id}/content")
def get_content(slug: str, attachment_id: str, request: Request, caller: AnyCaller) -> Response:
    settings = settings_of(request)
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        row = _row(conn, mine, attachment_id)
        # Authorized first, and only then compared: no `304` for a caller who may not read.
        if row.deleted_at is not None or not attachments.readable(conn, mine, row):
            raise not_found()
    tag = f'"{row.sha256}"'
    headers = {**HEADERS, "ETag": tag}
    if _matches(request.headers.get("if-none-match"), tag):
        return Response(status_code=304, headers=headers)
    data = blobs.store_of(settings).get(blobs.key_of(row.project_id, row.id))
    if data is None or hashlib.sha256(data).hexdigest() != row.sha256:
        raise ApiError(500, "internal", "the stored bytes do not match their digest")
    if row.kind == "image":
        inline = request.query_params.get("download") != "1"
        headers["Content-Disposition"] = attachments.disposition(row.name, inline=inline)
        return Response(content=data, media_type=row.type, headers=headers)
    headers["Content-Disposition"] = attachments.disposition(row.name, inline=False)
    return Response(content=data, media_type="application/octet-stream", headers=headers)


@router.get("/projects/{slug}/attachments")
def list_pending(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
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
            if mine.kind == "agent" and mine.role in ("owner", "admin"):
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


@router.delete("/projects/{slug}/attachments/{attachment_id}")
def delete_attachment(
    slug: str, attachment_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    store = blobs.store_of(settings_of(request))

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        mine.require("events:post")
        lock_project(conn, mine.project.id)
        row = _row(conn, mine, attachment_id)
        if row.message_seq is not None:
            # A sent message's attachment is part of the message: read and taken out by
            # the message's rules, which arrive with the binding.
            raise not_found()
        own = row.uploaded_by == mine.id
        if not own and not _admin_human(mine):
            if mine.kind == "agent" and mine.role in ("owner", "admin"):
                raise humans_only("an agent deletes only what it sent")
            raise not_found()  # another member's pending upload does not exist for it
        # A pending upload leaves no tombstone and no event; the bytes go once the row is.
        conn.execute(delete(t.attachment).where(t.attachment.c.id == row.id))
        on_commit(conn, lambda: store.delete(blobs.key_of(row.project_id, row.id)))
        shown = attachments.view(conn, [row], whole=own)[0]
        return idempotency.Outcome(200, None, None, shown)

    return idempotency.run(engine_of(request), request, caller, action)
