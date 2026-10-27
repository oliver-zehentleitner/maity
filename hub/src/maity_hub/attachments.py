"""Attachments (docs/api.md §8.7): the metadata, the name, the sniffed type, the caps and
the read rule. The bytes are the blob store's (`attachment_store`); the routes are
`routes/attachments`."""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from datetime import timedelta
from typing import Any
from urllib.parse import quote

from sqlalchemy import Connection, func, select

from maity_hub import events
from maity_hub import tables as t
from maity_hub.access import Membership
from maity_hub.errors import ApiError, rate_limited
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
EXTENSION = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
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


def message_readable(conn: Connection, mine: Membership, seq: int) -> bool:
    """Exactly who reads the message reads its attachments (§8.7): the event is read
    through the one read rule of `GET /events`, and a redacted message has none."""
    row = conn.execute(
        select(t.event).where(t.event.c.seq == seq, t.event.c.project_id == mine.project.id)
    ).first()
    if row is None or row.redacted:
        return False
    hidden = events.hidden_redactions(conn, [row], mine.row)
    return events.readable_by(row, mine.row, mine.principal_id, hidden)


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
