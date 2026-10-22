"""A member's picture (docs/api.md §6.10).

The picture belongs to the account (`hum-…`) or the agent profile (`agt-…`), never to a
membership, so it is the same in every project. Sources, the first with an image wins:
`uploaded` (the member, or an agent's owner, set it), then `forge` (humans, once the
accounts design links a forge account; nothing writes it yet). No row: `avatar_url` is
null and the client draws the generated avatar.

An upload is decoded and encoded again in a process of its own (`avatar_decode`), under
the operator's time and memory budgets, at most `avatar_decodes` at once; the hub stores
and serves only the PNG that comes out. Changes are limited per avatar, whichever
credential makes them.
"""

from __future__ import annotations

import math
import subprocess
import sys
import threading
from collections.abc import Iterable
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import clock, images
from maity_hub import tables as t
from maity_hub.avatar_decode import REFUSED
from maity_hub.config import Settings
from maity_hub.errors import invalid, rate_limited
from maity_hub.ratelimit import Limiter

SOURCES = ("uploaded", "forge")  # the first with an image wins
HEADERS = {**images.HEADERS, "Cache-Control": "private, no-cache"}
# At most 10 changes an hour for one avatar, whichever credential (or owner) makes them.
CHANGES = Limiter(10, 3600)

_slots_lock = threading.Lock()
_slots: dict[int, threading.BoundedSemaphore] = {}


def _slots_for(count: int) -> threading.BoundedSemaphore:
    with _slots_lock:
        if count not in _slots:
            _slots[count] = threading.BoundedSemaphore(count)
        return _slots[count]


def decode(settings: Settings, data: bytes, content_type: str) -> bytes:
    """The PNG to store, or `invalid` (`details.fields.body`) for an image that is not
    accepted, or `rate_limited` when every decode slot is taken (§6.10)."""
    slots = _slots_for(settings.avatar_decodes)
    if not slots.acquire(blocking=False):
        raise rate_limited(max(1, math.ceil(settings.avatar_decode_seconds)))
    try:
        command = [
            sys.executable,
            "-m",
            "maity_hub.avatar_decode",
            content_type,
            str(settings.avatar_decode_memory_mb * 1024 * 1024),
        ]
        try:
            done = subprocess.run(
                command,
                input=data,
                capture_output=True,
                timeout=settings.avatar_decode_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:  # run() has killed it
            raise invalid({"body": "over_budget"}, "the image took too long to decode") from None
    finally:
        slots.release()
    if done.returncode == 0 and done.stdout:
        return done.stdout
    if done.returncode == REFUSED:
        reason = done.stdout.decode("ascii", "replace")[:32] or "undecodable"
        raise invalid({"body": reason}, "the image was not accepted")
    # Killed past its memory limit, or crashed: refused, and nothing stored.
    raise invalid({"body": "over_budget"}, "the image could not be decoded within its budget")


def check_rate(owner_id: str) -> None:
    """Refuse before any decoding when this avatar has had its changes for the hour."""
    wait = CHANGES.blocked(owner_id)
    if wait:
        raise rate_limited(wait)


def count_change(owner_id: str) -> None:
    """Count one `PUT` or `DELETE` of this avatar, or refuse it."""
    wait = CHANGES.hit(owner_id)
    if wait:
        raise rate_limited(wait)


def _rows(conn: Connection, owner_ids: Iterable[str]) -> dict[str, Any]:
    """The row that applies per owner: an upload over the forge's image."""
    wanted = {i for i in owner_ids if i}
    if not wanted:
        return {}
    found: dict[str, Any] = {}
    rows = conn.execute(
        select(t.avatar_image.c.owner_id, t.avatar_image.c.source, t.avatar_image.c.etag).where(
            t.avatar_image.c.owner_id.in_(wanted)
        )
    ).all()
    for row in sorted(rows, key=lambda r: SOURCES.index(r.source)):
        found.setdefault(row.owner_id, row)
    return found


def url_of(owner_id: str, etag: str) -> str:
    return f"/api/v1/avatars/{owner_id}?v={etag.strip(chr(34))}"


def urls(conn: Connection, owner_ids: Iterable[str]) -> dict[str, str | None]:
    """`avatar_url` per member id; null where no source has an image."""
    ids = [i for i in owner_ids if i]
    rows = _rows(conn, ids)
    return {i: (url_of(i, rows[i].etag) if i in rows else None) for i in ids}


def state(conn: Connection, owner_id: str) -> dict[str, str | None]:
    """`{avatar_url, avatar_source}`: the answer of a change, and the settings view."""
    row = _rows(conn, [owner_id]).get(owner_id)
    if row is None:
        return {"avatar_url": None, "avatar_source": None}
    return {"avatar_url": url_of(owner_id, row.etag), "avatar_source": row.source}


def current(conn: Connection, owner_id: str) -> tuple[bytes, str] | None:
    """The stored image that applies, and its `ETag`."""
    row = _rows(conn, [owner_id]).get(owner_id)
    if row is None:
        return None
    data = conn.execute(
        select(t.avatar_image.c.data).where(
            t.avatar_image.c.owner_id == owner_id, t.avatar_image.c.source == row.source
        )
    ).scalar_one()
    return bytes(data), row.etag


def store_upload(conn: Connection, owner_id: str, png: bytes) -> None:
    values = {"data": png, "etag": images.etag(png), "updated_at": clock.now()}
    key = (t.avatar_image.c.owner_id == owner_id) & (t.avatar_image.c.source == "uploaded")
    if conn.execute(update(t.avatar_image).where(key).values(**values)).rowcount == 0:
        conn.execute(insert(t.avatar_image).values(owner_id=owner_id, source="uploaded", **values))


def remove_upload(conn: Connection, owner_id: str) -> None:
    conn.execute(
        delete(t.avatar_image).where(
            t.avatar_image.c.owner_id == owner_id, t.avatar_image.c.source == "uploaded"
        )
    )


def may_read(conn: Connection, caller: Any, owner_id: str) -> bool:
    """§6.10, who may read an image: the member itself, the agent's owner, a caller
    sharing a project with it, a `members:admin` of a project where an agent the human
    owns is a member, and the instance admin for a human's picture."""
    from maity_hub.admin import is_instance_admin

    if caller.kind == "agent":
        if caller.agent_id == owner_id:
            return True
        mine = conn.execute(
            select(t.membership.c.project_id).where(t.membership.c.id == caller.membership_id)
        ).scalar()
        return mine is not None and mine in _projects_of(conn, owner_id)
    if caller.kind != "human":
        return False
    me = caller.human_id
    if me == owner_id:
        return True
    if owner_id.startswith("agt-"):
        owner = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == owner_id)
        ).scalar()
        if owner == me:
            return True
    elif is_instance_admin(conn, me):
        return True
    my_projects = {
        row.project_id: row.role
        for row in conn.execute(
            select(t.membership.c.project_id, t.membership.c.role).where(
                t.membership.c.human_id == me, t.membership.c.active.is_(True)
            )
        )
    }
    if set(my_projects) & _projects_of(conn, owner_id):
        return True
    if owner_id.startswith("hum-"):
        # The owner of an agent is shown to admins only (§6.2), and so is their picture.
        admin_of = {p for p, role in my_projects.items() if role in ("owner", "admin")}
        agents_in = set(
            conn.execute(
                select(t.membership.c.project_id)
                .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
                .where(t.agent_profile.c.owner_id == owner_id, t.membership.c.active.is_(True))
            ).scalars()
        )
        return bool(admin_of & agents_in)
    return False


def _projects_of(conn: Connection, member_id: str) -> set[str]:
    column = t.membership.c.agent_id if member_id.startswith("agt-") else t.membership.c.human_id
    return set(
        conn.execute(
            select(t.membership.c.project_id).where(
                column == member_id, t.membership.c.active.is_(True)
            )
        ).scalars()
    )
