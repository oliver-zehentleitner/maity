"""Rows as the API shows them (docs/api.md §5, §6, §10)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import clock, forge, policy
from maity_hub import tables as t
from maity_hub.config import Settings

ONLINE = timedelta(seconds=120)
AWAY = timedelta(hours=2)


def ts(moment: datetime | None) -> str | None:
    return clock.rfc3339(moment) if moment is not None else None


def human_member(row: Any) -> dict[str, Any]:
    return {"id": row.id, "kind": "human", "handle": row.handle, "display_name": row.display_name}


def agent_member(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "agent",
        "handle": row.handle,
        "display_name": row.display_name,
        "owner_id": row.owner_id,
    }


def git_identity(row: Any) -> dict[str, str] | None:
    if row.git_name is None and row.git_email is None:
        return None
    return {"name": row.git_name, "email": row.git_email}


def repository(project: Any, settings: Settings) -> dict[str, Any] | None:
    if project.repository_url is None:
        return None
    return {
        "url": project.repository_url,
        "default_branch": project.repository_default_branch,
        "forge": forge_of(project.repository_url),
        "probe_configured": forge.configured_for(project.repository_url),
    }


def forge_of(url: str) -> str | None:
    return forge.kind_of(url)


def absence(project: Any) -> dict[str, Any] | None:
    if project.absence_until is None:
        return None
    return {"until": ts(project.absence_until), "scope": project.absence_scope}


def project_view(project: Any, settings: Settings) -> dict[str, Any]:
    return {
        "slug": project.slug,
        "name": project.name,
        "state": project.state,
        "state_note": project.state_note,
        "state_changed_at": ts(project.state_changed_at),
        "repository": repository(project, settings),
        "keep_the_why": project.keep_the_why,
        "policy": policy.of(project),
        "absence": absence(project),
        "settings": project.settings,
        "rules_version": project.rules_version,
        "created_at": ts(project.created_at),
    }


def principal_id(conn: Connection, membership_id: int | None) -> str | None:
    """The member id (`hum-…`/`agt-…`) of a membership row id."""
    if membership_id is None:
        return None
    return principal_ids(conn, [membership_id])[membership_id]


def principal_ids(conn: Connection, membership_ids: Iterable[int | None]) -> dict[int, str]:
    """The member ids of several membership row ids, in one query. Lists build
    their views through this and the other `*_views`, so a page costs a fixed
    number of statements instead of a few per row."""
    wanted = {i for i in membership_ids if i is not None}
    if not wanted:
        return {}
    rows = conn.execute(
        select(t.membership.c.id, t.membership.c.agent_id, t.membership.c.human_id).where(
            t.membership.c.id.in_(wanted)
        )
    ).all()
    found = {row.id: row.agent_id or row.human_id for row in rows}
    missing = wanted - found.keys()
    if missing:
        raise LookupError(f"membership rows {sorted(missing)} do not exist")
    return found


def paused(row: Any) -> dict[str, Any] | None:
    if row.paused_since is None:
        return None
    return {"reason": row.paused_reason, "since": ts(row.paused_since), "by": row.paused_by}


def presence(row: Any, session: Any, listening: bool) -> str:
    """Computed, never stored (§5.3)."""
    if row.paused_since is not None:
        return "paused"
    if listening:
        return "online"
    if row.agent_id is not None and session is None:
        return "offline"
    seen: datetime | None = row.last_seen_at
    if seen is None:
        return "offline"
    age = clock.now() - seen
    if age <= ONLINE:
        return "online"
    if age <= AWAY:
        return "away"
    return "offline"


def _sessions(conn: Connection, membership_ids: set[int]) -> tuple[dict[int, Any], dict[int, Any]]:
    """Per membership: the newest live session, and the newest session of any kind."""
    if not membership_ids:
        return {}, {}
    live: dict[int, Any] = {}
    for row in conn.execute(
        select(t.agent_session)
        .where(
            t.agent_session.c.membership_id.in_(membership_ids),
            t.agent_session.c.live.is_(True),
        )
        .order_by(t.agent_session.c.started_at.desc(), t.agent_session.c.id.desc())
    ):
        live.setdefault(row.membership_id, row)
    newest = (
        select(
            t.agent_session.c.membership_id,
            func.max(t.agent_session.c.started_at).label("started_at"),
        )
        .where(t.agent_session.c.membership_id.in_(membership_ids - live.keys()))
        .group_by(t.agent_session.c.membership_id)
        .subquery()
    )
    latest: dict[int, Any] = dict(live)
    if membership_ids - live.keys():
        for row in conn.execute(
            select(t.agent_session)
            .join(
                newest,
                (newest.c.membership_id == t.agent_session.c.membership_id)
                & (newest.c.started_at == t.agent_session.c.started_at),
            )
            .order_by(t.agent_session.c.id.desc())
        ):
            latest.setdefault(row.membership_id, row)
    return live, latest


def member_view(conn: Connection, row: Any, *, briefing: bool = False) -> dict[str, Any]:
    """The member view of §6.2: the principal, the membership, the live session.

    `briefing` only for the member itself and for `members:admin` (§6.2), never in
    an event that goes to everyone; the caller decides."""
    return member_views(conn, [row], briefing=briefing)[0]


def member_views(
    conn: Connection, rows: Sequence[Any], *, briefing: bool | Callable[[Any], bool] = False
) -> list[dict[str, Any]]:
    """`member_view` for several membership rows, with a fixed number of queries;
    `briefing` for every row, or per row through a predicate."""
    from maity_hub import listening  # the in-process registry of open long-polls

    agent_ids = {r.agent_id for r in rows if r.agent_id is not None}
    human_ids = {r.human_id for r in rows if r.agent_id is None}
    agents = (
        {
            a.id: a
            for a in conn.execute(
                select(t.agent_profile).where(t.agent_profile.c.id.in_(agent_ids))
            )
        }
        if agent_ids
        else {}
    )
    humans = (
        {h.id: h for h in conn.execute(select(t.human).where(t.human.c.id.in_(human_ids)))}
        if human_ids
        else {}
    )
    principals = principal_ids(conn, (r.reports_to for r in rows))
    live, latest_of = _sessions(conn, {r.id for r in rows if r.agent_id is not None})
    views = []
    for row in rows:
        head = (
            agent_member(agents[row.agent_id])
            if row.agent_id
            else human_member(humans[row.human_id])
        )
        view: dict[str, Any] = {
            **head,
            "role": row.role,
            "reports_to": principals.get(row.reports_to) if row.reports_to is not None else None,
            "areas": row.areas,
            "capabilities": row.capabilities,
        }
        session = None
        if row.agent_id is not None:
            session = live.get(row.id)
            latest = latest_of.get(row.id)
            is_listening = session is not None and listening.is_listening(session.id)
            view["harness"] = latest.harness if latest else None
            view["model"] = latest.model if latest else None
            view["session"] = (
                {
                    "id": session.id,
                    "harness": session.harness,
                    "model": session.model,
                    "client": session.client,
                    "started_at": ts(session.started_at),
                    "listening": is_listening,
                }
                if session
                else None
            )
        else:
            is_listening = False
        view.update(
            {
                "last_seen_at": ts(row.last_seen_at),
                "presence": presence(row, session, is_listening),
                "paused": paused(row),
                "joined_at": ts(row.joined_at),
            }
        )
        if row.removed_at is not None:
            view["removed_at"] = ts(row.removed_at)
        if briefing(row) if callable(briefing) else briefing:
            view["briefing"] = row.briefing
        views.append(view)
    return views


def human_paused(row: Any) -> bool:
    """Paused by someone other than the member itself: the soft stop of §5.3."""
    return row.paused_since is not None and row.paused_by != (row.agent_id or row.human_id)


def agent_view(conn: Connection, row: Any) -> dict[str, Any]:
    memberships = conn.execute(
        select(t.project.c.slug, t.membership.c.role)
        .join(t.project, t.project.c.id == t.membership.c.project_id)
        .where(t.membership.c.agent_id == row.id, t.membership.c.active.is_(True))
        .order_by(t.project.c.slug)
    ).all()
    return {
        "id": row.id,
        "handle": row.handle,
        "display_name": row.display_name,
        "owner_id": row.owner_id,
        "git_identity": git_identity(row),
        "memberships": [{"project": m.slug, "role": m.role} for m in memberships],
        "created_at": ts(row.created_at),
    }


def credential_view(conn: Connection, row: Any) -> dict[str, Any]:
    session = conn.execute(
        select(t.agent_session.c.id).where(
            t.agent_session.c.credential_id == row.id, t.agent_session.c.live.is_(True)
        )
    ).scalar()
    return {
        "id": row.id,
        "member_id": principal_id(conn, row.membership_id),
        "client": row.client,
        "created_at": ts(row.created_at),
        "resumed_at": ts(row.resumed_at),
        "last_used_at": ts(row.last_used_at),
        "session_id": session,
        "revoked_at": ts(row.revoked_at),
        "revoked_by": row.revoked_by,
        "revoked_reason": row.revoked_reason,
    }


def join_view(conn: Connection, row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "agent_id": row.agent_id,
        "role": row.role,
        "created_by": row.created_by,
        "created_at": ts(row.created_at),
        "expires_at": ts(row.expires_at),
        "used_at": ts(row.used_at),
        "burned": row.burned_at is not None,
        "revoked_at": ts(row.revoked_at),
    }


def _release(conn: Connection, row: Any, tags: dict[str, Any]) -> dict[str, Any] | None:
    if row.kind != "release":
        return None
    from maity_hub.releases import release_view

    return release_view(conn, row, tags.get(row.id))


def task_view(conn: Connection, row: Any) -> dict[str, Any]:
    """The card as §6.4 shows it (the tasks slice adds its endpoints)."""
    return task_views(conn, [row])[0]


def task_views(conn: Connection, rows: Sequence[Any]) -> list[dict[str, Any]]:
    """`task_view` for several cards: one query for the edges, one for the members."""
    if not rows:
        return []
    edges: dict[str, dict[str, list[str]]] = {
        r.id: {"depends_on": [], "ships_with": []} for r in rows
    }
    for edge in conn.execute(
        select(t.card_edge.c.from_card, t.card_edge.c.to_card, t.card_edge.c.kind).where(
            t.card_edge.c.from_card.in_(edges.keys())
        )
    ):
        edges[edge.from_card].setdefault(edge.kind, []).append(edge.to_card)
    members = principal_ids(
        conn, (m for r in rows for m in (r.claim_holder, r.created_by, r.assigned_to))
    )
    from maity_hub.releases import tags  # releases reads views; imported here, not at the top

    release_tags = tags(conn, [r for r in rows if r.kind == "release"])
    now = clock.now()
    views = []
    for row in rows:
        claim = None
        if row.claim_holder is not None:
            claim = {
                "holder": members[row.claim_holder],
                "session_id": row.claim_session_id,
                "since": ts(row.claim_since),
                "lease_until": ts(row.lease_until),
                "expired": row.lease_until is not None and row.lease_until <= now,
            }
        views.append(
            {
                "id": row.id,
                "kind": row.kind,
                "title": row.title,
                "body": row.body,
                "label": row.label,
                "status": row.status,
                "area": row.area,
                "created_by": members.get(row.created_by),
                "assigned_to": members.get(row.assigned_to),
                "claim": claim,
                "checkpoint": row.checkpoint,
                "depends_on": sorted(edges[row.id]["depends_on"]),
                "ships_with": sorted(edges[row.id]["ships_with"]),
                "blocked_by_request": row.blocked_by_request,
                "ktw_ref": row.ktw_ref,
                "report": row.report,
                "release": _release(conn, row, release_tags),
                "contract": row.contract,
                "created_at": ts(row.created_at),
                "updated_at": ts(row.updated_at),
                "closed_at": ts(row.closed_at),
            }
        )
    return views


def event_view(conn: Connection, row: Any) -> dict[str, Any]:
    """An event as §8.1 shows it."""
    return event_views(conn, [row])[0]


def event_views(conn: Connection, rows: Sequence[Any]) -> list[dict[str, Any]]:
    """`event_view` for several events, with one query for the actors."""
    actors = principal_ids(conn, (r.actor_membership for r in rows))
    views = []
    for row in rows:
        actor = None
        if row.actor_membership is not None:
            actor = {
                "member_id": actors[row.actor_membership],
                "session_id": row.actor_session_id,
                "harness": row.actor_harness,
                "model": row.actor_model,
            }
        views.append(
            {
                "seq": row.seq,
                "kind": row.kind,
                "at": ts(row.at),
                "actor": actor,
                "subject": (
                    {"type": row.subject_type, "id": row.subject_id} if row.subject_type else None
                ),
                "audience": row.audience,
                "payload": row.payload,
                "redacted": row.redacted,
            }
        )
    return views
