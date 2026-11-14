"""A member's picture (docs/api.md §6.10).

The picture belongs to the account (`hum-…`) or the agent profile (`agt-…`), never to a
membership, so it is the same in every project. Sources, the first with an image wins:
`uploaded` (the member, or an agent's owner, set it), then `forge` (humans, once the
accounts design links a forge account; nothing writes it yet). A human without either has
`avatar_url` null and the client draws the generated avatar. An agent always has a picture:
after an upload its motif (`motifs`, while the set holds the name it chose), then its
`generated` picture, drawn at the profile's creation (`avatar_generated`).

A picture a public page shows is anyone's to read at an address naming no account (`public`).
Every picture is served in four sizes; the smaller ones are scaled once by the decoder and
kept in `avatar_size` until the picture they were made from changes.

An upload is decoded and encoded again in a process of its own (`avatar_decode`), under
the operator's time and memory budgets, at most `avatar_decodes` at once, of which one
human's calls take at most all but one; the hub stores and serves only the PNG that comes
out. Changes are limited per avatar, whichever credential makes them.
"""

from __future__ import annotations

import logging
import math
import re
import subprocess
import sys
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

from sqlalchemy import Connection, Engine, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import avatar_decode, avatar_generated, clock, images, motifs
from maity_hub import tables as t
from maity_hub.avatar_decode import REFUSED
from maity_hub.config import Settings
from maity_hub.errors import invalid, rate_limited
from maity_hub.ratelimit import Limiter
from maity_hub.scopes import has_scope

log = logging.getLogger(__name__)

# The first with an image wins: `forge` for a human, `motif` and `generated` for an agent.
SOURCES = ("uploaded", "forge", "motif", "generated")
HEADERS = {**images.HEADERS, "Cache-Control": "private, no-cache"}
# A picture a public page shows (§6.10): the URL is versioned, so a browser keeps it a day; a
# shared cache keeps it no longer than a public page (§16.9), so it leaves a proxy within a
# minute once it stops being public.
PUBLIC_HEADERS = {**images.HEADERS, "Cache-Control": "public, max-age=86400, s-maxage=60"}
STORED_SIDE = 256  # the stored image's side at most (§6.10, Upload)
SIZES = (*avatar_decode.SIZES, STORED_SIDE)  # what `?s=` may ask for
# At most 10 changes an hour for one avatar, whichever credential (or owner) makes them.
CHANGES = Limiter(10, 3600, name="avatars.CHANGES")


class DecodeSlots:
    """The decodes one process runs at once, `count` in all, of which one holder (the human
    behind a call) takes at most all but one, so a single account cannot take every slot
    while others wait. A take that does not fit is refused at once, never queued."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.share = max(1, count - 1)
        self._lock = threading.Lock()
        self._taken = 0
        self._held: dict[str, int] = {}

    def acquire(self, blocking: bool = False, holder: str | None = None) -> bool:
        if blocking:
            raise ValueError("decode slots are never waited for")
        with self._lock:
            if self._taken >= self.count:
                return False
            if holder is not None and self._held.get(holder, 0) >= self.share:
                return False
            self._taken += 1
            if holder is not None:
                self._held[holder] = self._held.get(holder, 0) + 1
            return True

    def release(self, holder: str | None = None) -> None:
        with self._lock:
            if self._taken <= 0:
                raise ValueError("a decode slot released more often than taken")
            self._taken -= 1
            if holder is not None:
                left = self._held[holder] - 1
                if left:
                    self._held[holder] = left
                else:
                    del self._held[holder]


_slots_lock = threading.Lock()
_slots: dict[int, DecodeSlots] = {}


def _slots_for(count: int) -> DecodeSlots:
    with _slots_lock:
        if count not in _slots:
            _slots[count] = DecodeSlots(count)
        return _slots[count]


def holder_of(caller: Any) -> str | None:
    """Whose share of the decode slots a call takes: the human behind it, an agent's owner
    for an agent, so that one person's agents and sessions share one share."""
    found: str | None = None
    if caller.kind == "agent":
        found = caller.owner_id or caller.agent_id
    elif caller.kind == "human":
        found = caller.human_id
    return found


DECODER = Path(avatar_decode.__file__)
REASONS = ("dimensions", "undecodable")  # what the decoder may answer (§6.10)


def decode(
    settings: Settings,
    data: bytes,
    content_type: str,
    mode: str = "avatar",
    *,
    holder: str | None = None,
) -> bytes:
    """The PNG to store (with `mode` `attachment`: the re-encoded image file), or `invalid`
    (`details.fields.body`) for an image that is not accepted, or `rate_limited` when
    every decode slot is taken, or `holder` already holds its share of them (§6.10).

    The child runs the decoder file by path under `python -I` with an empty
    environment: neither the hub's settings (the database URL, the forge token) nor its
    `sys.path` reach the process that parses untrusted bytes. It keeps the hub's user,
    so this narrows what an exploited decoder holds; it is not a sandbox."""
    slots = _slots_for(settings.avatar_decodes)
    if not slots.acquire(blocking=False, holder=holder):
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
        slots.release(holder)
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
    wait, mark = CHANGES.place(owner_id)
    if wait:
        raise rate_limited(wait)
    if conn is not None:
        from maity_hub.events import on_rollback

        on_rollback(conn, lambda: CHANGES.release(owner_id, mark))


class Picture(NamedTuple):
    """The picture that applies to one owner: its source and its stored image's `ETag`."""

    owner_id: str
    source: str
    etag: str


def chosen_motifs(conn: Connection, agent_ids: Iterable[str]) -> dict[str, str | None]:
    """`avatar_motif` per agent profile id: the name it chose, or None."""
    ids = {i for i in agent_ids if i and i.startswith("agt-")}
    if not ids:
        return {}
    rows = conn.execute(
        select(t.agent_profile.c.id, t.agent_profile.c.avatar_motif).where(
            t.agent_profile.c.id.in_(ids)
        )
    ).all()
    return {row.id: row.avatar_motif for row in rows}


def _rows(conn: Connection, owner_ids: Iterable[str]) -> dict[str, Picture]:
    """The picture that applies per owner (§6.10, Sources): an upload, then the forge's
    image (a human) or the motif the set still holds (an agent), then the generated one."""
    wanted = {i for i in owner_ids if i}
    if not wanted:
        return {}
    stored: dict[str, dict[str, str]] = {}
    for row in conn.execute(
        select(t.avatar_image.c.owner_id, t.avatar_image.c.source, t.avatar_image.c.etag).where(
            t.avatar_image.c.owner_id.in_(wanted)
        )
    ).all():
        stored.setdefault(row.owner_id, {})[row.source] = row.etag
    chosen = chosen_motifs(conn, wanted)
    serving = motifs.current() if any(chosen.values()) else motifs.EMPTY
    found: dict[str, Picture] = {}
    for owner_id in wanted:
        tags = stored.get(owner_id, {})
        motif = serving.named(chosen.get(owner_id))
        if motif is not None:
            tags = {**tags, "motif": motif.etag}
        source = next((s for s in SOURCES if s in tags), None)
        if source is not None:
            found[owner_id] = Picture(owner_id, source, tags[source])
    return found


def url_of(owner_id: str, etag: str) -> str:
    return f"/api/v1/avatars/{owner_id}?v={etag.strip(chr(34))}"


def public_url(etag: str) -> str:
    """The public address of a picture (§6.10): by its digest, naming no account."""
    return f"/api/v1/avatars/public/{etag.strip(chr(34))}"


def urls(conn: Connection, owner_ids: Iterable[str]) -> dict[str, str | None]:
    """`avatar_url` per member id; null where no source has an image."""
    ids = [i for i in owner_ids if i]
    rows = _rows(conn, ids)
    return {i: (url_of(i, rows[i].etag) if i in rows else None) for i in ids}


def public_urls(conn: Connection, owner_ids: Iterable[str]) -> dict[str, str | None]:
    """The public address of each owner's picture, null where none applies. The caller
    decides that the picture is public (`is_public`); this names only the address."""
    ids = [i for i in owner_ids if i]
    rows = _rows(conn, ids)
    return {i: (public_url(rows[i].etag) if i in rows else None) for i in ids}


def _state(owner_id: str, row: Picture | None) -> dict[str, str | None]:
    if row is None:
        return {"avatar_url": None, "avatar_source": None}
    return {"avatar_url": url_of(owner_id, row.etag), "avatar_source": row.source}


def states(conn: Connection, owner_ids: Iterable[str]) -> dict[str, dict[str, str | None]]:
    """`state` of several owners in one query."""
    ids = list(owner_ids)
    rows = _rows(conn, ids)
    return {i: _state(i, rows.get(i)) for i in ids}


def state(conn: Connection, owner_id: str) -> dict[str, str | None]:
    """`{avatar_url, avatar_source}`: the answer of a change, and the settings view."""
    return _state(owner_id, _rows(conn, [owner_id]).get(owner_id))


def current(conn: Connection, owner_id: str) -> tuple[bytes, str] | None:
    """The stored image that applies, and its `ETag`."""
    found = stored(conn, owner_id)
    return None if found is None else (found[0], found[1])


def stored(conn: Connection, owner_id: str) -> tuple[bytes, str, str] | None:
    """The stored image that applies, its `ETag` and its source."""
    row = _rows(conn, [owner_id]).get(owner_id)
    if row is None:
        return None
    if row.source == "motif":
        motif = motifs.current().with_digest(row.etag.strip('"'))
        if motif is None:  # the set changed under a running process: never
            return None
        return motif.data, motif.etag, "motif"
    data = conn.execute(
        select(t.avatar_image.c.data).where(
            t.avatar_image.c.owner_id == owner_id, t.avatar_image.c.source == row.source
        )
    ).scalar_one()
    return bytes(data), row.etag, row.source


def store_generated(conn: Connection, agent_id: str) -> None:
    """Draw the agent's generated picture and store it (§6.10): at the profile's creation;
    the upgrade that brought it drew it for every profile before."""
    png = avatar_generated.draw(agent_id)
    conn.execute(
        insert(t.avatar_image).values(
            owner_id=agent_id,
            source="generated",
            data=png,
            etag=images.etag(png),
            updated_at=clock.now(),
        )
    )


def kept_size(
    conn: Connection, owner_id: str, source: str, base_etag: str, side: int
) -> tuple[bytes, str] | None:
    """The kept `side` of the stored image whose `ETag` is `base_etag`, if one was made."""
    row = conn.execute(
        select(t.avatar_size.c.data, t.avatar_size.c.etag).where(
            t.avatar_size.c.owner_id == owner_id,
            t.avatar_size.c.source == source,
            t.avatar_size.c.size == side,
            t.avatar_size.c.base_etag == base_etag,
        )
    ).first()
    return None if row is None else (bytes(row.data), row.etag)


def keep_size(
    conn: Connection, owner_id: str, source: str, base_etag: str, side: int, png: bytes
) -> str:
    """Keep a size made from the image whose `ETag` is `base_etag`, while that image is still
    the stored one: a size of a replaced picture is never kept. Two requests that made the
    same size keep one of them. Its `ETag`."""
    tag = images.etag(png)
    still = conn.execute(
        select(t.avatar_image.c.etag).where(
            t.avatar_image.c.owner_id == owner_id, t.avatar_image.c.source == source
        )
    ).scalar()
    if still != base_etag:
        return tag
    key = (
        (t.avatar_size.c.owner_id == owner_id)
        & (t.avatar_size.c.source == source)
        & (t.avatar_size.c.size == side)
    )
    conn.execute(delete(t.avatar_size).where(key & (t.avatar_size.c.base_etag != base_etag)))
    try:
        with conn.begin_nested():
            conn.execute(
                insert(t.avatar_size).values(
                    owner_id=owner_id,
                    source=source,
                    size=side,
                    base_etag=base_etag,
                    data=png,
                    etag=tag,
                )
            )
    except IntegrityError:  # the other request kept it first: the same bytes
        pass
    return tag


def side_of(png: bytes) -> int:
    """The stored image's side, from its PNG header (it is square)."""
    return avatar_decode.dimensions(png, "image/png")[0]


def is_public(conn: Connection, hub: Settings, owner_id: str) -> bool:
    """§6.10, A public picture: a human's while the hub serves their page and their
    `public_profile` is on; an agent's while its owner's served agents page lists it, which
    every agent with a page of its own is (§16.9). An organisation's never."""
    from maity_hub import public_people

    if not hub.public_pages:
        return False
    if owner_id.startswith("hum-"):
        human = conn.execute(select(t.human).where(t.human.c.id == owner_id)).first()
        return (
            human is not None and bool(human.public_profile) and public_people.served(conn, human)
        )
    if owner_id.startswith("agt-"):
        agent = conn.execute(
            select(t.agent_profile.c.owner_id).where(
                t.agent_profile.c.id == owner_id, t.agent_profile.c.deleted_at.is_(None)
            )
        ).first()
        if agent is None:
            return False
        owner = conn.execute(select(t.human).where(t.human.c.id == agent.owner_id)).first()
        return owner is not None and any(
            listed.agent.id == owner_id for listed in public_people.listed_agents(conn, owner)
        )
    return False


DIGEST = re.compile(r"[0-9a-f]{16,64}")


def public(conn: Connection, hub: Settings, digest: str) -> tuple[bytes, str, str, str] | None:
    """`GET /avatars/public/{digest}` (§6.10): the stored image whose digest this is, while a
    picture with it is public, with its `ETag`, owner (`""` for a motif) and source. A
    motif's digest answers at every time; two owners with the same bytes share the digest,
    and it answers while either is public."""
    if not DIGEST.fullmatch(digest):
        return None
    motif = motifs.current().with_digest(digest)
    if motif is not None:
        return motif.data, motif.etag, "", "motif"
    tag = f'"{digest}"'
    owners = conn.execute(
        select(t.avatar_image.c.owner_id).where(t.avatar_image.c.etag == tag).distinct()
    ).scalars()
    for owner_id in sorted(owners):
        row = _rows(conn, [owner_id]).get(owner_id)
        if row is not None and row.etag == tag and is_public(conn, hub, owner_id):
            found = stored(conn, owner_id)
            if found is not None:
                return found[0], found[1], owner_id, found[2]
    return None


def at_size(
    engine: Engine,
    settings: Settings,
    owner_id: str,
    found: tuple[bytes, str, str],
    side: int,
) -> tuple[bytes, str]:
    """The picture `found` (bytes, `ETag`, source) at `side` pixels (§6.10, Sizes): the
    stored image at 256 and for a picture no larger than `side`; a motif's sizes from the set;
    any other size scaled once by the decoder, outside a transaction, and kept, then served
    from what was kept."""
    data, etag, source = found
    if side >= STORED_SIDE or side_of(data) <= side:
        return data, etag
    if source == "motif":
        motif = motifs.current().with_digest(etag.strip('"'))
        return motif.at(side) if motif is not None else (data, etag)
    with engine.begin() as conn:
        kept = kept_size(conn, owner_id, source, etag, side)
    if kept is not None:
        return kept
    png = decode(settings, data, "image/png", mode=f"size{side}")
    with engine.begin() as conn:
        return png, keep_size(conn, owner_id, source, etag, side, png)


def lock_owner(conn: Connection, owner_id: str) -> None:
    """Serialise changes of one picture: two uploads must not both find no row and
    both insert one. An organisation's is the row its deletion locks too (§6.26), so a picture
    is not stored after the deletion removed the old one."""
    table = (
        t.org
        if owner_id.startswith("org-")
        else t.agent_profile if owner_id.startswith("agt-") else t.human
    )
    conn.execute(select(table.c.id).where(table.c.id == owner_id).with_for_update()).first()


def drop_sizes(conn: Connection, owner_id: str, source: str | None = None) -> None:
    """The kept sizes go with the image they were made from (§6.10, Sizes)."""
    where = t.avatar_size.c.owner_id == owner_id
    if source is not None:
        where = where & (t.avatar_size.c.source == source)
    conn.execute(delete(t.avatar_size).where(where))


def store_upload(conn: Connection, owner_id: str, png: bytes) -> None:
    drop_sizes(conn, owner_id, "uploaded")
    values = {"data": png, "etag": images.etag(png), "updated_at": clock.now()}
    key = (t.avatar_image.c.owner_id == owner_id) & (t.avatar_image.c.source == "uploaded")
    if conn.execute(update(t.avatar_image).where(key).values(**values)).rowcount == 0:
        conn.execute(insert(t.avatar_image).values(owner_id=owner_id, source="uploaded", **values))


def remove_upload(conn: Connection, owner_id: str) -> None:
    drop_sizes(conn, owner_id, "uploaded")
    conn.execute(
        delete(t.avatar_image).where(
            t.avatar_image.c.owner_id == owner_id, t.avatar_image.c.source == "uploaded"
        )
    )


def choose_motif(conn: Connection, agent_id: str, name: Any, caller: Any) -> None:
    """`avatar_motif` in `PATCH /me` (the agent) or `PATCH /agents/{id}` (its owner): a name
    of the set, or None to clear it (§6.10). A name the set does not hold is `invalid`; a
    choice counts as a change under the per-avatar limit, a repeat of the current one too.
    It shows while no upload does, and `avatar_changed` follows only when it shows."""
    from maity_hub import moderation

    if name is not None and (not isinstance(name, str) or motifs.current().named(name) is None):
        raise invalid({"avatar_motif": "unknown"}, "the hub ships no motif of that name")
    # The lock first: a reset holds it until its hold is written, so the check reads that hold.
    lock_owner(conn, agent_id)
    if name is not None:  # a motif restores a reset picture: not while its hold stands (§16.8)
        moderation.refuse_held(conn, "profile", agent_id, "remove")
    count_change(conn, agent_id)  # given back if this transaction rolls back
    before = state(conn, agent_id)
    conn.execute(
        update(t.agent_profile).where(t.agent_profile.c.id == agent_id).values(avatar_motif=name)
    )
    announce(conn, agent_id, before, caller)


def clear_motif(conn: Connection, agent_id: str) -> None:
    """The agent's chosen motif dropped by a moderation reset (§16.8). A deleted profile
    clears it in its own update (routes/agents.py), not here."""
    conn.execute(
        update(t.agent_profile).where(t.agent_profile.c.id == agent_id).values(avatar_motif=None)
    )


def announce(conn: Connection, owner_id: str, before: dict[str, str | None], caller: Any) -> None:
    """`avatar_changed` in every project the member is in, when the effective picture's
    source or content changed (§6.10, §8.2). The member is the actor where it made the
    change itself; an owner's change has none, so the event does not name the owner."""
    from maity_hub.events import Actor, emit

    after = state(conn, owner_id)
    if after == before:  # the same bytes give the same URL: nothing changed
        return
    _touch_page(conn, owner_id)
    column = t.membership.c.agent_id if owner_id.startswith("agt-") else t.membership.c.human_id
    memberships = conn.execute(
        select(t.membership.c.id, t.membership.c.project_id).where(
            column == owner_id, t.membership.c.active.is_(True)
        )
    ).all()
    # A moderation reset passes its actor (`{kind: moderation, report_id}`, §8.2) as is.
    from_moderation = isinstance(caller, Actor)
    own = not from_moderation and caller.principal_id == owner_id
    for membership in sorted(memberships, key=lambda m: m.project_id):
        emit(
            conn,
            membership.project_id,
            "avatar_changed",
            ["all"],
            {"member_id": owner_id, "avatar_url": after["avatar_url"]},
            actor=caller if from_moderation else (caller.actor(membership.id) if own else None),
            subject=("member", owner_id),
        )


def _touch_page(conn: Connection, owner_id: str) -> None:
    """The picture is an input of the pages that show it (§16.9): the person's page, or the
    agent's page and its owner's agents page, rendered again at once, so a stored page names
    the current public address and never the old one, which answers `not_found` from now on."""
    from maity_hub import public_agents, public_pages, public_people

    if owner_id.startswith("hum-"):
        public_pages.touch(conn, public_people.KIND, owner_id, dependents=False)
    elif owner_id.startswith("agt-"):
        public_pages.touch(conn, public_agents.KIND, owner_id, dependents=False)
        public_people.touch_owner_of(conn, owner_id)


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


def decode_attachment(
    settings: Settings, data: bytes, content_type: str, *, holder: str | None = None
) -> Reencoded:
    """An attachment's image decoded and encoded again, in the avatar decoder's process,
    under its budgets and its decode slots (§8.7); `invalid` (`details.fields.body`) for
    an image that is not accepted, `rate_limited` when every slot is taken or `holder`
    holds its share."""
    stored = decode(settings, data, content_type, "attachment", holder=holder)
    kind = STORED_TYPE[content_type]
    try:
        width, height = avatar_decode.dimensions(stored, kind)
    except avatar_decode.Refused:
        raise invalid({"body": "undecodable"}, "the image could not be decoded") from None
    return Reencoded(stored, kind, width, height)
