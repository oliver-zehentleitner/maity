"""Attachments (docs/api.md §8.7): the metadata, the name, the sniffed type, the caps and
the read rule. The bytes are the blob store's (`attachment_store`); the routes are
`routes/attachments`."""

from __future__ import annotations

import hashlib
import logging
import math
import re
import threading
import time
import unicodedata
from collections.abc import Sequence
from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote

from sqlalchemy import Connection, Engine, delete, func, select, update

from maity_hub import attachment_store, clock, events
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.config import Settings
from maity_hub.errors import ApiError, invalid, rate_limited
from maity_hub.policy import CLOSED_STATES
from maity_hub.ratelimit import Limiter
from maity_hub.views import principal_ids, ts

FILE_CAP = 10 * 1024 * 1024  # per file, before re-encoding
PENDING_COUNT = 20  # pending uploads per membership ...
PENDING_BYTES = 100 * 1024 * 1024  # ... and their bytes
PENDING_FOR = timedelta(hours=24)  # a pending upload expires after this
NAME_CODE_POINTS, NAME_BYTES = 200, 255
RATE_WINDOW = 600  # 30 uploads and 100 MiB per membership in 10 minutes
RATE_UPLOADS = 30
RATE_UNIT = 64 * 1024  # the byte limiter counts in units of 64 KiB: 100 MiB is 1600
UPLOADS = Limiter(RATE_UPLOADS, RATE_WINDOW)
VOLUME = Limiter(1600, RATE_WINDOW)

IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
_TYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$")
# What a stored image is named by when it has no name: a GIF is stored as PNG.
EXTENSION = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".png"}
# Pending uploads show another member's admin these fields only (§8.7).
HIDDEN = ("name", "type", "kind", "sha256", "width", "height")


def sniff(data: bytes) -> str | None:
    """An image's type by its magic bytes, never by its name or declared type."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return None


def declared_type(header: str | None) -> str:
    """The `Content-Type` as a bare lower-case `type/subtype`, `image/jpg` as JPEG."""
    value = (header or "").split(";", 1)[0].strip().lower()
    return "image/jpeg" if value == "image/jpg" else value


def file_type(declared: str) -> str:
    """The type kept for a file that is not an image: the declared one when it is a
    valid `type/subtype`, else `application/octet-stream`. Information, never how the
    hub serves the bytes."""
    return declared if _TYPE.match(declared) else "application/octet-stream"


def _fits(name: str) -> bool:
    return len(name) <= NAME_CODE_POINTS and len(name.encode()) <= NAME_BYTES


def clean_name(raw: str, *, image_type: str | None = None) -> str:
    """The name as stored (§8.7), once, at upload: NFC; `/` and `\\` become `_`; control
    and format characters and `:` removed; whitespace and leading dots trimmed; at most
    200 code points and 255 bytes, cut before the last `.` so the extension survives. An
    empty name, `.` or `..` is `attachment` plus an image's extension; a GIF, stored as
    PNG, gets `.png`."""
    name = unicodedata.normalize("NFC", raw).replace("/", "_").replace("\\", "_")
    name = "".join(c for c in name if unicodedata.category(c) not in ("Cc", "Cf") and c != ":")
    name = name.strip().lstrip(".").strip()
    if image_type == "image/gif" and name:
        stem, dot, ext = name.rpartition(".")
        name = (stem if dot and stem and ext.lower() == "gif" else name) + ".png"
    if name in ("", ".", ".."):
        return "attachment" + EXTENSION.get(image_type or "", "")
    if _fits(name):
        return name
    stem, dot, ext = name.rpartition(".")
    suffix = f"{dot}{ext}" if dot and stem and len(ext) < 100 else ""
    stem = stem if suffix else name
    while stem and not _fits(stem + suffix):
        stem = stem[:-1]
    return (stem + suffix) or "attachment"


def disposition(name: str, *, inline: bool) -> str:
    """`Content-Disposition` with the name in `filename*` (UTF-8) and, for a download, an
    ASCII fallback."""
    mode = "inline" if inline else "attachment"
    encoded = quote(name, safe="")
    if inline:
        return f"{mode}; filename*=UTF-8''{encoded}"
    fallback = re.sub(r'[^\x20-\x7e]|["\;]', "_", name)
    return f"{mode}; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def charge(uploads_key: str, size: int) -> int:
    """Count one upload of `size` bytes against the membership's rate, or the seconds to
    wait; nothing is counted then."""
    units = max(1, math.ceil(size / RATE_UNIT))
    wait = UPLOADS.hit(uploads_key)
    if wait:
        return wait
    wait = VOLUME.take(uploads_key, min(units, VOLUME.limit))
    if wait or units > VOLUME.limit:
        UPLOADS.give_back(uploads_key, 1)
        return wait or RATE_WINDOW
    return 0


def give_back(uploads_key: str, size: int) -> None:
    UPLOADS.give_back(uploads_key, 1)
    VOLUME.give_back(uploads_key, min(max(1, math.ceil(size / RATE_UNIT)), VOLUME.limit))


def check_rate(uploads_key: str, size: int) -> None:
    wait = charge(uploads_key, size)
    if wait:
        raise rate_limited(wait)


def used(conn: Connection, project_id: str) -> int:
    """Bytes stored by a project: every attachment not deleted, pending ones included."""
    total = conn.execute(
        select(func.coalesce(func.sum(t.attachment.c.size), 0)).where(
            t.attachment.c.project_id == project_id, t.attachment.c.deleted_at.is_(None)
        )
    ).scalar()
    return int(total or 0)


def pending_of(conn: Connection, membership_id: int) -> tuple[int, int]:
    """(count, bytes) of a membership's pending uploads."""
    count, size = conn.execute(
        select(func.count(), func.coalesce(func.sum(t.attachment.c.size), 0)).where(
            t.attachment.c.uploaded_by == membership_id,
            t.attachment.c.message_seq.is_(None),
            t.attachment.c.deleted_at.is_(None),
        )
    ).one()
    return int(count), int(size)


def quota_error(scope: str, **details: Any) -> ApiError:
    return ApiError(
        409,
        "attachment_quota",
        "the upload would take the "
        + ("project" if scope == "project" else "membership")
        + " over its quota",
        {"scope": scope, **details},
    )


def reader_row(mine: Any) -> Any:
    """The membership row the read rule takes: a member's own, or for an owner outside the
    project, who has none, a stand-in that holds no role and no agent."""
    row = getattr(mine, "row", None)
    if row is not None:
        return row
    return SimpleNamespace(
        id=-1, trust=None, role="outsider", agent_id=None, human_id=mine.principal_id
    )


def message_readable(conn: Connection, mine: Any, seq: int) -> bool:
    """Exactly who reads the message reads its attachments (§8.7): the event is read
    through the one read rule of `GET /events`, and a redacted message has none. An owner
    outside the project reads only a group chat's message it reads along in (§9.2); the
    stand-in row must never reach a project message that is addressed to `all`."""
    row = conn.execute(
        select(t.event).where(t.event.c.seq == seq, t.event.c.project_id == mine.project.id)
    ).first()
    if row is None or row.redacted:
        return False
    outside = getattr(mine, "row", None) is None
    if outside:
        from maity_hub import group_chats

        if not group_chats.is_group(row.conversation_id):
            return False
        if group_chats.access(conn, row.conversation_id, mine) != "observer":
            return False
    seen = reader_row(mine)
    hidden = events.hidden_redactions(conn, [row], seen)
    return events.readable_by(row, seen, mine.principal_id, hidden)


def readable(conn: Connection, mine: Membership, row: Any) -> bool:
    if row.deleted_at is not None and row.message_seq is None:
        return False  # a pending upload that was deleted leaves nothing
    if row.message_seq is None:  # pending: its uploader's alone
        return bool(row.uploaded_by == mine.id)
    return message_readable(conn, mine, row.message_seq)


def expires_at(row: Any) -> str | None:
    pending = row.message_seq is None and row.deleted_at is None
    return ts(row.uploaded_at + PENDING_FOR) if pending else None


def view(conn: Connection, rows: list[Any], *, whole: bool = True) -> list[dict[str, Any]]:
    """The attachment as §8.7 shows it; with `whole` false, a pending upload of another
    member as the listing shows it: size, uploader and times only."""
    members = principal_ids(conn, (r.uploaded_by for r in rows))
    shown = []
    for row in rows:
        item: dict[str, Any] = {
            "id": row.id,
            "name": row.name,
            "size": row.size,
            "type": row.type,
            "kind": row.kind,
            "sha256": row.sha256,
            "width": row.width,
            "height": row.height,
            "uploaded_by": members.get(row.uploaded_by),
            "uploaded_at": ts(row.uploaded_at),
            "message_seq": row.message_seq,
            "deleted_at": ts(row.deleted_at),
            "deleted_by": row.deleted_by,
            "deleted_reason": row.deleted_reason,
        }
        if row.message_seq is None and row.deleted_at is None:
            item["expires_at"] = expires_at(row)
        if not whole:
            item |= dict.fromkeys(HIDDEN)
        shown.append(item)
    return shown


MESSAGE_MAX = 10  # attachments one message may name (§1.7)


def meta(row: Any) -> dict[str, Any]:
    """What a message carries of an attachment: metadata only, never content or a URL."""
    return {
        "id": row.id,
        "name": row.name,
        "size": row.size,
        "type": row.type,
        "kind": row.kind,
        "width": row.width,
        "height": row.height,
    }


def bind(
    conn: Connection, mine: Membership, ids: list[str], settings: Settings | None
) -> list[Any]:
    """The pending uploads of the posting membership a message names, in the order named
    (§8.7), or the refusal: `attachments_not_configured` with no store, `project_closed`,
    `too_many`, and per id `unknown` (not a pending upload of the poster in this project,
    deleted ones and other members' alike) or `already_attached`."""
    if not ids:
        return []
    if settings is None or settings.attachment_dir is None:
        raise ApiError(
            409,
            "attachments_not_configured",
            "this hub has no attachment store: the operator sets MAITY_ATTACHMENT_DIR",
        )
    if mine.project.state in CLOSED_STATES:
        raise ApiError(409, "project_closed", f"the project is {mine.project.state}")
    if len(ids) > MESSAGE_MAX:
        raise invalid({"attachments": "too_many"})
    rows = {
        r.id: r
        for r in conn.execute(
            select(t.attachment).where(
                t.attachment.c.id.in_(ids), t.attachment.c.project_id == mine.project.id
            )
        )
    }
    problems: dict[str, str] = {}
    seen: set[str] = set()
    for attachment_id in ids:
        row = rows.get(attachment_id)
        if attachment_id in seen:
            problems[attachment_id] = "already_attached"
        elif (
            row is None
            or row.uploaded_by != mine.id
            or row.deleted_at is not None
            or (row.message_seq is None and clock.now() - row.uploaded_at >= PENDING_FOR)
        ):  # an upload past its 24 hours is as good as gone: the sweep may take it any moment
            problems[attachment_id] = "unknown"
        elif row.message_seq is not None:
            problems[attachment_id] = "already_attached"
        seen.add(attachment_id)
    if problems:
        raise invalid({"attachments": problems}, "some attachments cannot be named")
    return [rows[i] for i in ids]


def attach(conn: Connection, rows: list[Any], seq: int) -> None:
    """Bind the uploads to the message just written, in its transaction; one that was
    taken or deleted meanwhile refuses the whole post."""
    if not rows:
        return
    done = conn.execute(
        update(t.attachment)
        .where(
            t.attachment.c.id.in_([r.id for r in rows]),
            t.attachment.c.message_seq.is_(None),
            t.attachment.c.deleted_at.is_(None),
        )
        .values(message_seq=seq)
    ).rowcount
    if done != len(rows):
        raise invalid({"attachments": dict.fromkeys((r.id for r in rows), "unknown")})


def redact_message(
    conn: Connection, seq: int, by: str | None, store: attachment_store.LocalStore | None
) -> None:
    """A redacted message has no attachments (§8.7, §8.5): the rows become tombstones in the
    redaction's transaction, `deleted_reason` `redacted`, and the bytes go once it commits.
    The `event_redacted` event covers them: no `attachment_deleted` is emitted."""
    rows = conn.execute(
        select(t.attachment).where(
            t.attachment.c.message_seq == seq, t.attachment.c.deleted_at.is_(None)
        )
    ).all()
    if not rows:
        return
    conn.execute(
        update(t.attachment)
        .where(t.attachment.c.id.in_([r.id for r in rows]))
        .values(deleted_at=clock.now(), deleted_by=by, deleted_reason="redacted")
    )
    if store is not None:
        keys = [attachment_store.key_of(r.project_id, r.id) for r in rows]

        def remove() -> None:
            for key in keys:
                store.delete(key)

        events.on_commit(conn, remove)


def drop_pending(conn: Connection, membership_id: int) -> None:
    """A removed member's pending uploads go (§6.2): the rows at once, the bytes with the
    next sweep, which removes any blob no row names. What the member sent stays."""
    conn.execute(
        delete(t.attachment).where(
            t.attachment.c.uploaded_by == membership_id,
            t.attachment.c.message_seq.is_(None),
        )
    )


# --- the sweep (§8.7) ------------------------------------------------------------------------

log = logging.getLogger(__name__)
SWEEP_EVERY = 300  # seconds between sweeps
BLOB_GRACE = 600  # a blob younger than this may belong to a transaction still open


def expire(
    engine: Engine, store: attachment_store.LocalStore, candidates: Sequence[Any], cutoff: Any
) -> int:
    """Delete the candidates that are still pending and still past the cutoff, each under
    its project's lock, and remove the bytes of the rows that were deleted, and of no other.
    A message that named a candidate since it was chosen has bound it: the conditional
    delete finds nothing and the file stays."""
    removed = 0
    for row in candidates:
        with engine.begin() as conn:
            events.lock_project(conn, row.project_id)
            gone = conn.execute(
                delete(t.attachment).where(
                    t.attachment.c.id == row.id,
                    t.attachment.c.message_seq.is_(None),
                    t.attachment.c.deleted_at.is_(None),
                    t.attachment.c.uploaded_at < cutoff,
                )
            ).rowcount
        if gone == 1:
            store.delete(attachment_store.key_of(row.project_id, row.id))
            removed += 1
    return removed


def remove_stray(engine: Engine, store: attachment_store.LocalStore, key: str) -> bool:
    """Remove a blob no row names, if it is older than a transaction can be. The project's lock is
    held from the look at the row to the removal, as an upload holds it from writing the blob to
    inserting the row: an upload that commits meanwhile cannot lose its file."""
    project_id, _, attachment_id = key.partition("/")
    with engine.begin() as conn:
        events.lock_project(conn, project_id)
        named = conn.execute(
            select(t.attachment.c.id).where(t.attachment.c.id == attachment_id)
        ).first()
        if named is not None:
            return False
        age = store.age(key, time.time())
        if age is None or age <= BLOB_GRACE:
            return False
        store.delete(key)
    return True


def sweep(engine: Engine, store: attachment_store.LocalStore) -> dict[str, int]:
    """One pass: pending uploads past 24 hours go with their bytes, the bytes of a
    tombstoned row go if they are still there, and a blob no row names goes once it is
    older than a transaction can be. Returns what it removed, by kind."""
    done = {"expired": 0, "tombstoned": 0, "orphans": 0}
    cutoff = clock.now() - PENDING_FOR
    with engine.connect() as conn:
        candidates = conn.execute(
            select(t.attachment.c.id, t.attachment.c.project_id).where(
                t.attachment.c.message_seq.is_(None),
                t.attachment.c.deleted_at.is_(None),
                t.attachment.c.uploaded_at < cutoff,
            )
        ).all()
        tombstoned = conn.execute(
            select(t.attachment.c.id, t.attachment.c.project_id).where(
                t.attachment.c.deleted_at.is_not(None)
            )
        ).all()
    done["expired"] = expire(engine, store, candidates, cutoff)
    for row in tombstoned:  # a tombstone never comes back: its bytes can go without a lock
        key = attachment_store.key_of(row.project_id, row.id)
        if store.age(key, time.time()) is not None:
            store.delete(key)
            done["tombstoned"] += 1
    for project in store.projects():
        for key in store.keys(project):
            if remove_stray(engine, store, key):
                done["orphans"] += 1
    return done


class Worker:
    """Runs the sweep in the background, one thread per process, when a store is set."""

    def __init__(self, engine: Engine, store: attachment_store.LocalStore) -> None:
        self.engine = engine
        self.store = store
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-attachments", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop.wait(SWEEP_EVERY):
            try:
                sweep(self.engine, self.store)
            except Exception:
                log.exception("the attachment sweep failed")
