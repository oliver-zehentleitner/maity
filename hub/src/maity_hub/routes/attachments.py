"""`/projects/{owner}/{slug}/attachments` (docs/api.md §8.7): upload, read, list and delete.

An upload is raw bytes with the name in the query. An image is decoded and encoded again
outside the transaction, in the avatar decoder's process; the blob is written before the
transaction that inserts the row begins, outside the project's lock, and removed again when
that transaction does not commit. Reading asks the one question the message does: may this
caller read it.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import Connection, Engine, delete, insert, select, update

from maity_hub import attachment_store as blobs
from maity_hub import attachments, avatars, clock, group_chats, idempotency, paging
from maity_hub import tables as t
from maity_hub.access import Membership, membership
from maity_hub.deps import AnyCaller, engine_of, settings_of
from maity_hub.errors import ApiError, forbidden, humans_only, invalid, not_found
from maity_hub.events import emit, lock_project, on_commit
from maity_hub.ids import new_id
from maity_hub.namespace import ProjectRoute
from maity_hub.policy import CLOSED_STATES
from maity_hub.routes.conversations import Outsider, _reader
from maity_hub.routes.events import chat_parties
from maity_hub.routes.project_images import _matches
from maity_hub.scopes import in_admin_team

router = APIRouter(route_class=ProjectRoute)
log = logging.getLogger(__name__)

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
    if mine.project.state in CLOSED_STATES:
        raise ApiError(409, "project_closed", f"the project is {mine.project.state}")
    rate_key = str(mine.id)
    charged = attachments.check_rate(rate_key, len(data))  # the refund is this, whatever follows
    kind, width, height = "file", None, None
    kept_type = attachments.file_type(declared)
    try:
        if sniffed is not None:
            # The count bound before a decode that can take seconds; the bytes it keeps are
            # known only after it, so the quota and the byte bound wait for the check below.
            with engine.begin() as conn:
                _check_room(conn, mine, settings, None)
            image = avatars.decode_attachment(settings, data, sniffed)
            data, kept_type, width, height, kind = (
                image.data,
                image.type,
                image.width,
                image.height,
                "image",
            )
    except ApiError:
        attachments.give_back(rate_key, charged)  # nothing was stored: not counted
        raise
    name = attachments.clean_name(raw_name, image_type=sniffed)
    store = blobs.store_of(settings)
    attachment_id = new_id("attachment")
    try:
        # The quota and the pending bounds before the store is written, without the lock: a
        # refusal costs no write. They are read again under the lock, right before the insert.
        with engine.begin() as conn:
            _check_room(conn, membership(conn, caller, slug), settings, len(data))
    except BaseException:
        attachments.give_back(rate_key, charged)  # nothing was stored: not counted
        raise
    # The blob first, the row after (§8.7), and the blob outside every transaction: for `s3`
    # the write is a network call, and none may wait under the project's lock or hold a
    # database connection. The sweep leaves a blob without a row alone for `BLOB_GRACE`; the
    # row is inserted only while less than `UPLOAD_FRESH` has passed since the write began.
    # From the write on, the rate stays charged, whatever follows: even a write that failed
    # may have stored the bytes (a lost answer), so it is not given back.
    key = blobs.key_of(mine.project.id, attachment_id)
    started = attachments.upload_clock()
    try:
        store.put(key, data)
        if attachments.upload_clock() - started > attachments.UPLOAD_FRESH:
            raise ApiError(503, "upload_expired", "the upload took too long; send it again")
    except BaseException:
        _discard(store, key)
        raise

    def action(conn: Connection) -> idempotency.Outcome:
        project = lock_project(conn, membership(conn, caller, slug).project.id)
        # The decode took time: the right to post and the project's state are read again,
        # under the lock, right before the insert.
        locked = membership(conn, caller, slug)
        _require_post(locked)
        if locked.project.id != mine.project.id:  # the blob's key names the project it was for
            raise not_found()
        if project.state in CLOSED_STATES:
            raise ApiError(409, "project_closed", f"the project is {project.state}")
        _check_room(conn, locked, settings, len(data))
        if attachments.upload_clock() - started > attachments.UPLOAD_FRESH:
            # The database did not take the row in time (a lock wait, retries); the sweep may
            # already count the blob as a stray, so no row may name it now (§8.7).
            log.warning("an upload waited too long for its row; refused, its blob removed")
            raise ApiError(503, "upload_expired", "the upload took too long; send it again")
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
        answer = idempotency.run(engine, request, caller, action)
    except BaseException:
        # An error does not prove the row is absent: a COMMIT whose answer was lost, or a
        # retry refused after an attempt that did commit, leaves a row that names this blob.
        _discard_unless_committed(engine, store, key, attachment_id)
        raise
    if json.loads(bytes(answer.body)).get("id") != attachment_id:
        # A concurrent call with the same key won: its answer, not this blob.
        _discard_unless_committed(engine, store, key, attachment_id)
    return answer


def _check_room(conn: Connection, mine: Any, settings: Any, size: int | None) -> None:
    """The project's quota and the membership's pending bounds (§8.7) for `size` more bytes;
    with `size` None only the count of pending uploads."""
    if size is not None:
        used = attachments.used(conn, mine.project.id)
        if used + size > settings.attachment_quota:
            raise attachments.quota_error("project", used=used, quota=settings.attachment_quota)
    count, held = attachments.pending_of(conn, mine.id)
    if count + 1 > attachments.PENDING_COUNT or held + (size or 0) > attachments.PENDING_BYTES:
        raise attachments.quota_error(
            "pending",
            used=held,
            quota=attachments.PENDING_BYTES,
            count=count,
            max=attachments.PENDING_COUNT,
        )


def _discard_unless_committed(
    engine: Engine, store: blobs.BlobStore, key: str, attachment_id: str
) -> None:
    """Remove the upload's blob only when a fresh read finds no row with its id. When the row
    is there, the blob is its bytes and stays; when the read fails, the blob stays too, and
    the sweep removes it after `BLOB_GRACE` if no row names it by then."""
    try:
        with engine.connect() as conn:
            found = conn.execute(
                select(t.attachment.c.id).where(t.attachment.c.id == attachment_id)
            ).first()
    except Exception:
        log.warning("an upload failed and its row could not be read; the sweep decides")
        return
    if found is not None:
        log.warning("an upload failed after its row was committed; its blob kept")
        return
    _discard(store, key)


def _discard(store: blobs.BlobStore, key: str) -> None:
    """Remove the blob of an upload whose row was never committed, after the transaction and
    outside its lock. When that fails too, the blob is one without a row, and the sweep
    removes it once it is older than `BLOB_GRACE`."""
    try:
        store.delete(key)
    except Exception:
        log.warning("an upload's blob could not be removed; the sweep removes it later")


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
    blob = store.open(blobs.key_of(row.project_id, row.id))
    if blob is None:
        # The bytes may have gone since the row was read: a redaction or a deletion commits
        # and removes them. Read the row again; gone or unreadable now is `not_found`.
        with engine_of(request).begin() as conn:
            mine = _reader(conn, caller, slug)
            again = _row(conn, mine, attachment_id)
            if again.deleted_at is not None or not attachments.readable(conn, mine, again):
                raise not_found()
        raise _not_matching()
    if row.kind == "image":
        inline = request.query_params.get("download") != "1"
        headers["Content-Disposition"] = attachments.disposition(row.name, inline=inline)
        media_type = row.type
    else:
        headers["Content-Disposition"] = attachments.disposition(row.name, inline=False)
        media_type = "application/octet-stream"
    if blob.size != row.size:
        blob.close()
        raise _not_matching()
    if row.size <= WHOLE:
        # Small enough to check before the first byte goes out: a mismatch is a plain 500.
        try:
            data = b"".join(blob)
        finally:
            blob.close()
        if hashlib.sha256(data).hexdigest() != row.sha256:
            raise _not_matching()
        return Response(content=data, media_type=media_type, headers=headers)
    headers["Content-Length"] = str(row.size)
    return StreamingResponse(_checked(blob, row.sha256), media_type=media_type, headers=headers)


# Up to this size the bytes are read whole and checked before the answer starts; above it
# they stream, and the check holds the last piece back (`_checked`).
WHOLE = 1024 * 1024


def _not_matching() -> ApiError:
    return ApiError(500, "internal", "the stored bytes do not match their digest")


def _checked(blob: blobs.Blob, sha256: str) -> Iterator[bytes]:
    """The blob's pieces, hashed as they pass. The last piece is held back until the whole
    digest is known: bytes that do not match their digest end the answer short of its
    `Content-Length`, so no client takes them for the attachment."""
    digest = hashlib.sha256()
    held: bytes | None = None
    try:
        for piece in blob:
            digest.update(piece)
            if held is not None:
                yield held
            held = piece
        if digest.hexdigest() != sha256:
            log.error("an attachment's stored bytes do not match their digest; answer cut short")
            raise blobs.StoreError("the stored bytes do not match their digest")
        if held is not None:
            yield held
    finally:
        blob.close()


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
    conn: Connection, mine: Any, caller: Any, row: Any, store: blobs.BlobStore
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
