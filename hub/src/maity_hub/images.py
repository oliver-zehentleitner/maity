"""A project's logo and banner (docs/api.md §11.2).

Two sources, the first with an image wins: what a project admin uploaded, then the
repository's image as the hub last read it from the forge. Both are rows of
`project_image`; a forge row without data records that the forge had none.

The hub accepts PNG, JPEG and WebP by their magic bytes, at most 1 MiB, from an upload
and from the forge alike, and never decodes or re-encodes them. Forge images come from
the forge's image hosts only, read under the transport rule of §11.1 without a token.
Nothing here runs while a project view is built: the view reads the rows (`views`), a
read-through happens only on `GET …/logo` when nothing is stored, and `Worker` refreshes
what is older than `FRESH` in the background.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, Engine, delete, insert, select, update

from maity_hub import clock, events, forge, outbound
from maity_hub import tables as t

log = logging.getLogger(__name__)

KINDS = ("logo", "banner")
CAP = 1024 * 1024
FRESH = timedelta(hours=6)
# The forge's image hosts (§11.2): an image URL on any other host is no image.
IMAGE_HOSTS = {
    "logo": "avatars.githubusercontent.com",
    "banner": "repository-images.githubusercontent.com",
}
HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "private, max-age=21600",
}


def sniff(data: bytes) -> str | None:
    """The image type by its magic bytes; None for anything but PNG, JPEG and WebP."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def etag(data: bytes) -> str:
    return '"' + hashlib.sha256(data).hexdigest()[:32] + '"'


@dataclass(frozen=True)
class Image:
    data: bytes
    content_type: str
    etag: str
    source: str  # uploaded, forge


def _rows(conn: Connection, project_ids: Iterable[str], with_data: bool = False) -> list[Any]:
    wanted = list(project_ids)
    if not wanted:
        return []
    columns: list[Any] = [c for c in t.project_image.c if with_data or c.name != "data"]
    if not with_data:
        columns.append((t.project_image.c.data.isnot(None)).label("has_data"))
    return list(
        conn.execute(select(*columns).where(t.project_image.c.project_id.in_(wanted))).all()
    )


def _shown(rows: list[Any], kind: str) -> Any | None:
    """The row that is shown for `kind`: an upload, else a forge row with an image."""
    for source in ("uploaded", "forge"):
        for row in rows:
            if row.kind == kind and row.source == source:
                has = row.has_data if hasattr(row, "has_data") else row.data is not None
                if has:
                    return row
    return None


def _state(row: Any | None) -> dict[str, Any]:
    if row is None:
        return {"available": False, "source": None}
    return {"available": True, "source": row.source, "etag": row.etag}


def views(conn: Connection, project_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """`{project_id: {"logo": …, "banner": …}}` for the project view (§6.1), in one query."""
    wanted = list(project_ids)
    by_project: dict[str, list[Any]] = {p: [] for p in wanted}
    for row in _rows(conn, wanted):
        by_project[row.project_id].append(row)
    return {p: {k: _state(_shown(rows, k)) for k in KINDS} for p, rows in by_project.items()}


def current(conn: Connection, project_id: str, kind: str) -> Image | None:
    row = _shown(_rows(conn, [project_id], with_data=True), kind)
    if row is None:
        return None
    return Image(bytes(row.data), row.content_type, row.etag, row.source)


def forge_row(conn: Connection, project_id: str, kind: str) -> Any | None:
    return conn.execute(
        select(t.project_image.c.checked_at, t.project_image.c.etag).where(
            t.project_image.c.project_id == project_id,
            t.project_image.c.kind == kind,
            t.project_image.c.source == "forge",
        )
    ).first()


def _announce(conn: Connection, project_id: str, kind: str, actor: events.Actor | None) -> None:
    """`project_updated` with what the project now shows for `kind`, never the bytes."""
    shown = _shown(_rows(conn, [project_id]), kind)
    events.emit(
        conn,
        project_id,
        "project_updated",
        ["all"],
        {"fields": {kind: _state(shown)}},
        actor=actor,
        subject=("project", project_id),
    )


def _write(
    conn: Connection, project_id: str, kind: str, source: str, values: dict[str, Any]
) -> None:
    key = (
        t.project_image.c.project_id == project_id,
        t.project_image.c.kind == kind,
        t.project_image.c.source == source,
    )
    if conn.execute(select(t.project_image.c.kind).where(*key)).first() is None:
        conn.execute(
            insert(t.project_image).values(
                project_id=project_id, kind=kind, source=source, **values
            )
        )
    else:
        conn.execute(update(t.project_image).where(*key).values(**values))


# --- uploads ---------------------------------------------------------------------------------


def upload(
    conn: Connection,
    project_id: str,
    kind: str,
    data: bytes,
    content_type: str,
    membership_id: int,
    actor: events.Actor,
) -> dict[str, Any]:
    """Store an upload, already checked by the caller; announce it when the shown image
    changes. Returns the kind's state."""
    before = _state(_shown(_rows(conn, [project_id]), kind))
    _write(
        conn,
        project_id,
        kind,
        "uploaded",
        {
            "data": data,
            "content_type": content_type,
            "etag": etag(data),
            "checked_at": clock.now(),
            "uploaded_by": membership_id,
        },
    )
    after = _state(_shown(_rows(conn, [project_id]), kind))
    if after != before:
        _announce(conn, project_id, kind, actor)
    return after


def remove_upload(
    conn: Connection, project_id: str, kind: str, actor: events.Actor
) -> dict[str, Any]:
    before = _state(_shown(_rows(conn, [project_id]), kind))
    conn.execute(
        delete(t.project_image).where(
            t.project_image.c.project_id == project_id,
            t.project_image.c.kind == kind,
            t.project_image.c.source == "uploaded",
        )
    )
    after = _state(_shown(_rows(conn, [project_id]), kind))
    if after != before:
        _announce(conn, project_id, kind, actor)
    return after


def forget_forge(conn: Connection, project_id: str) -> None:
    """The repository changed: the forge images were of the old one."""
    shown_before = {k: _state(_shown(_rows(conn, [project_id]), k)) for k in KINDS}
    conn.execute(
        delete(t.project_image).where(
            t.project_image.c.project_id == project_id, t.project_image.c.source == "forge"
        )
    )
    for kind in KINDS:
        if _state(_shown(_rows(conn, [project_id]), kind)) != shown_before[kind]:
            _announce(conn, project_id, kind, None)


# --- the forge -------------------------------------------------------------------------------


class Unavailable(Exception):
    """The forge or its image host did not answer; the last image, if any, stays."""


def _image_url(reader: forge.Forge, repository: str, kind: str) -> str | None:
    try:
        if kind == "logo":
            return reader.owner_avatar(repository)
        return reader.social_preview(repository)
    except forge.ForgeUnavailableError:
        raise Unavailable from None


def _download(url: str, kind: str) -> tuple[bytes, str] | None:
    """The image at `url` if it is on the kind's image host and is an image the hub
    accepts; None for anything else (another host, a 404, SVG, too large)."""
    host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
    if not url.startswith("https://") or host != IMAGE_HOSTS[kind]:
        return None
    try:
        answer = outbound.read(url, cap=CAP)
    except outbound.Refused as refused:
        if refused.reason == "too_large" or refused.reason == "url_invalid":
            return None
        raise Unavailable from None
    if answer.status in (404, 410):
        return None
    if answer.status != 200:
        raise Unavailable
    content_type = sniff(answer.body)
    return None if content_type is None else (answer.body, content_type)


def read_forge(reader: forge.Forge, repository: str, kind: str) -> tuple[bytes, str] | None:
    """The forge's image for `kind`: (bytes, type), None when it has none the hub accepts;
    `Unavailable` when it did not answer."""
    url = _image_url(reader, repository, kind)
    return None if url is None else _download(url, kind)


def refresh(engine: Engine, reader: forge.Forge, project_id: str, kind: str) -> bool:
    """Read the forge's image and store the answer. A failure keeps what is stored and
    returns False; an answer, image or none, replaces it and returns True."""
    with engine.begin() as conn:
        repository_url = conn.execute(
            select(t.project.c.repository_url).where(t.project.c.id == project_id)
        ).scalar()
    if repository_url is None or forge.kind_of(repository_url) != "github":
        return True
    repository = forge.repository_of(repository_url)
    try:
        found = read_forge(reader, repository, kind)
    except Unavailable:
        return False
    with events.transaction(engine) as conn:
        events.lock_project(conn, project_id)
        still = conn.execute(
            select(t.project.c.repository_url).where(t.project.c.id == project_id)
        ).scalar()
        if still != repository_url:
            return True  # the repository changed while the read ran; its answer is stale
        before = _state(_shown(_rows(conn, [project_id]), kind))
        values: dict[str, Any] = {"checked_at": clock.now(), "uploaded_by": None}
        if found is None:
            values.update(data=None, content_type=None, etag=None)
        else:
            data, content_type = found
            values.update(data=data, content_type=content_type, etag=etag(data))
        _write(conn, project_id, kind, "forge", values)
        if _state(_shown(_rows(conn, [project_id]), kind)) != before:
            _announce(conn, project_id, kind, None)
    return True


def stale(conn: Connection) -> list[tuple[str, str]]:
    """(project, kind) pairs on GitHub whose forge image was never read or is older than
    FRESH, for the worker."""
    projects = conn.execute(
        select(t.project.c.id, t.project.c.repository_url).where(
            t.project.c.repository_url.isnot(None)
        )
    ).all()
    checked = {
        (r.project_id, r.kind): r.checked_at
        for r in conn.execute(
            select(
                t.project_image.c.project_id, t.project_image.c.kind, t.project_image.c.checked_at
            ).where(t.project_image.c.source == "forge")
        ).all()
    }
    due = clock.now() - FRESH
    found = []
    for project in projects:
        if forge.kind_of(project.repository_url) != "github":
            continue
        for kind in KINDS:
            at = checked.get((project.id, kind))
            if at is None or at < due:
                found.append((project.id, kind))
    return found


INTERVAL = 600.0  # seconds between sweeps


class Worker:
    """Refreshes stale forge images in the background, one at a time."""

    def __init__(self, engine: Engine, reader: forge.Forge, interval: float = INTERVAL) -> None:
        self.engine = engine
        self.reader = reader
        self.interval = interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-images", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def sweep(self) -> None:
        with self.engine.begin() as conn:
            due = stale(conn)
        for project_id, kind in due:
            if self._stop.is_set():
                return
            try:
                refresh(self.engine, self.reader, project_id, kind)
            except Exception:  # one project's failure must not stop the others
                log.exception("refreshing the %s of %s failed", kind, project_id)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self.sweep()
