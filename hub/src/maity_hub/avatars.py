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

import logging
import math
import subprocess
import sys
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update

from maity_hub import avatar_decode, clock, images
from maity_hub import tables as t
from maity_hub.avatar_decode import REFUSED
from maity_hub.config import Settings
from maity_hub.errors import invalid, rate_limited
from maity_hub.ratelimit import Limiter
from maity_hub.scopes import has_scope

log = logging.getLogger(__name__)

SOURCES = ("uploaded", "forge")  # the first with an image wins
HEADERS = {**images.HEADERS, "Cache-Control": "private, no-cache"}
# At most 10 changes an hour for one avatar, whichever credential (or owner) makes them.
CHANGES = Limiter(10, 3600, name="avatars.CHANGES")

_slots_lock = threading.Lock()
_slots: dict[int, threading.BoundedSemaphore] = {}


def _slots_for(count: int) -> threading.BoundedSemaphore:
    with _slots_lock:
        if count not in _slots:
            _slots[count] = threading.BoundedSemaphore(count)
        return _slots[count]


DECODER = Path(avatar_decode.__file__)
REASONS = ("dimensions", "undecodable")  # what the decoder may answer (§6.10)


def decode(settings: Settings, data: bytes, content_type: str, mode: str = "avatar") -> bytes:
    """The PNG to store (with `mode` `attachment`: the re-encoded image file), or `invalid`
    (`details.fields.body`) for an image that is not accepted, or `rate_limited` when
    every decode slot is taken (§6.10).

    The child runs the decoder file by path under `python -I` with an empty
    environment: neither the hub's settings (the database URL, the forge token) nor its
    `sys.path` reach the process that parses untrusted bytes. It keeps the hub's user,
    so this narrows what an exploited decoder holds; it is not a sandbox."""
    slots = _slots_for(settings.avatar_decodes)
    if not slots.acquire(blocking=False):
        raise rate_limited(max(1, math.ceil(settings.avatar_decode_seconds)))
    seconds = max(1, math.ceil(settings.avatar_decode_seconds))
    command = [
        sys.executable,
        "-I",
        str(DECODER),
        content_type,
        str(settings.avatar_decode_memory_mb * 1024 * 1024),
        str(seconds),
        *([mode] if mode != "avatar" else []),
    ]
    try:
        done = subprocess.run(
            command,
            input=data,
            capture_output=True,
            timeout=settings.avatar_decode_seconds,
            check=False,
            env={},
        )
    except subprocess.TimeoutExpired:  # run() has killed it
        log.warning("%s decode killed after %ss", mode, settings.avatar_decode_seconds)
        raise invalid({"body": "undecodable"}, "the image did not decode in time") from None
    finally:
        slots.release()
    if done.returncode == 0 and done.stdout:
        return done.stdout
    detail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [""]
    if done.returncode == REFUSED:
        reason = done.stdout.decode("ascii", "replace")
        log.info("%s refused: %s (%s)", mode, reason, detail[0][:200])
        reason = reason if reason in REASONS else "undecodable"
        raise invalid({"body": reason}, "the image was not accepted")
    # Killed by a signal (past its memory or CPU limit, or a crash) or failed otherwise:
    # refused, nothing stored, and the operator can tell it from a plain refusal.
    signal = -done.returncode if done.returncode < 0 else None
    log.warning(
        "%s decoder exited %s%s: %s",
        mode,
        done.returncode,
        f" (signal {signal})" if signal else "",
        detail[0][:200],
    )
    raise invalid({"body": "undecodable"}, "the image could not be decoded")


def check_rate(owner_id: str) -> None:
    """Refuse before any decoding when this avatar has had its changes for the hour."""
    wait = CHANGES.blocked(owner_id)
    if wait:
        raise rate_limited(wait)


def count_change(conn: Connection | None, owner_id: str) -> None:
    """Count one `PUT` or `DELETE` of this avatar, or refuse it. Inside a transaction
    (`conn`), a rollback or a retry of it gives the count back."""
    wait = CHANGES.hit(owner_id)
    if wait:
        raise rate_limited(wait)
    if conn is not None:
        from maity_hub.events import on_rollback

        on_rollback(conn, lambda: CHANGES.give_back(owner_id, 1))


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


def states(conn: Connection, owner_ids: Iterable[str]) -> dict[str, dict[str, str | None]]:
    """`state` of several owners in one query."""
    ids = list(owner_ids)
    rows = _rows(conn, ids)
    return {
        i: (
            {"avatar_url": url_of(i, rows[i].etag), "avatar_source": rows[i].source}
            if i in rows
            else {"avatar_url": None, "avatar_source": None}
        )
        for i in ids
    }


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


def lock_owner(conn: Connection, owner_id: str) -> None:
    """Serialise changes of one picture: two uploads must not both find no row and
    both insert one."""
    table = t.agent_profile if owner_id.startswith("agt-") else t.human
    conn.execute(select(table.c.id).where(table.c.id == owner_id).with_for_update()).first()


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


def announce(conn: Connection, owner_id: str, before: dict[str, str | None], caller: Any) -> None:
    """`avatar_changed` in every project the member is in, when the effective picture's
    source or content changed (§6.10, §8.2). The member is the actor where it made the
    change itself; an owner's change has none, so the event does not name the owner."""
    from maity_hub.events import emit

    after = state(conn, owner_id)
    if after == before:  # the same bytes give the same URL: nothing changed
        return
    column = t.membership.c.agent_id if owner_id.startswith("agt-") else t.membership.c.human_id
    memberships = conn.execute(
        select(t.membership.c.id, t.membership.c.project_id).where(
            column == owner_id, t.membership.c.active.is_(True)
        )
    ).all()
    own = caller.principal_id == owner_id
    for membership in sorted(memberships, key=lambda m: m.project_id):
        emit(
            conn,
            membership.project_id,
            "avatar_changed",
            ["all"],
            {"member_id": owner_id, "avatar_url": after["avatar_url"]},
            actor=caller.actor(membership.id) if own else None,
            subject=("member", owner_id),
        )


def may_read(conn: Connection, caller: Any, owner_id: str) -> bool:
    """§6.10, who may read an image: the member itself, the agent's owner, a caller
    sharing a project with it, a `members:admin` of a project where an agent the human
    owns is a member, and the instance admin for a human's picture; an organisation's
    picture its members and the members of its projects, nobody else."""
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
    if owner_id.startswith("org-"):
        return _reads_org(conn, me, owner_id)
    if owner_id.startswith("agt-"):
        owner = conn.execute(
            select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == owner_id)
        ).scalar()
        if owner == me:
            return True
    elif is_instance_admin(conn, me):
        return True
    my_projects = {
        row.project_id: (row.trust, row.role_base)
        for row in conn.execute(
            select(t.membership.c.project_id, t.membership.c.trust, t.membership.c.role_base).where(
                t.membership.c.human_id == me, t.membership.c.active.is_(True)
            )
        )
    }
    if set(my_projects) & _projects_of(conn, owner_id):
        return True
    if owner_id.startswith("hum-"):
        # The owner of an agent is shown to admins only (§6.2), and so is their picture.
        admin_of = {
            p
            for p, (trust, role) in my_projects.items()
            if has_scope(trust, role, "human", "members:admin")
        }
        agents_in = set(
            conn.execute(
                select(t.membership.c.project_id)
                .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
                .where(t.agent_profile.c.owner_id == owner_id, t.membership.c.active.is_(True))
            ).scalars()
        )
        return bool(admin_of & agents_in)
    return False


def _reads_org(conn: Connection, human_id: str, org_id: str) -> bool:
    """A member of the organisation, or of a project it owns (§6.10)."""
    if (
        conn.execute(
            select(t.org_member.c.human_id).where(
                t.org_member.c.org_id == org_id, t.org_member.c.human_id == human_id
            )
        ).first()
        is not None
    ):
        return True
    m = t.membership.c
    return (
        conn.execute(
            select(m.id)
            .join(t.project, t.project.c.id == m.project_id)
            .where(
                t.project.c.owner_org_id == org_id,
                m.human_id == human_id,
                m.active.is_(True),
            )
            .limit(1)
        ).first()
        is not None
    )


def _projects_of(conn: Connection, member_id: str) -> set[str]:
    column = t.membership.c.agent_id if member_id.startswith("agt-") else t.membership.c.human_id
    return set(
        conn.execute(
            select(t.membership.c.project_id).where(
                column == member_id, t.membership.c.active.is_(True)
            )
        ).scalars()
    )


class Reencoded:
    """An attachment's image as the hub stores it (docs/api.md §8.7): the bytes, their
    type, and the size the stored file's own header states."""

    __slots__ = ("data", "height", "type", "width")

    def __init__(self, data: bytes, type_: str, width: int, height: int) -> None:
        self.data = data
        self.type = type_
        self.width = width
        self.height = height


STORED_TYPE = {
    "image/png": "image/png",
    "image/gif": "image/png",  # a GIF keeps its first frame, as a PNG
    "image/jpeg": "image/jpeg",
    "image/webp": "image/webp",
}


def decode_attachment(settings: Settings, data: bytes, content_type: str) -> Reencoded:
    """An attachment's image decoded and encoded again, in the avatar decoder's process,
    under its budgets and its decode slots (§8.7); `invalid` (`details.fields.body`) for
    an image that is not accepted, `rate_limited` when every slot is taken."""
    stored = decode(settings, data, content_type, "attachment")
    kind = STORED_TYPE[content_type]
    try:
        width, height = avatar_decode.dimensions(stored, kind)
    except avatar_decode.Refused:
        raise invalid({"body": "undecodable"}, "the image could not be decoded") from None
    return Reencoded(stored, kind, width, height)
