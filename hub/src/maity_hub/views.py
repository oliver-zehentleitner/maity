"""Rows as the API shows them (docs/api.md §5, §6, §10)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, func, select

from maity_hub import avatars, clock, forge, onboarding, policy, ticker_read
from maity_hub import tables as t
from maity_hub.config import Settings

ONLINE = timedelta(seconds=120)
AWAY = timedelta(hours=2)


def ts(moment: datetime | None) -> str | None:
    return clock.rfc3339(moment) if moment is not None else None


def human_member(row: Any, *, avatar_url: str | None) -> dict[str, Any]:
    """`avatar_url` is the caller's to look up (`avatars.urls`), so a list costs one query."""
    return {
        "id": row.id,
        "kind": "human",
        "handle": row.handle,
        "display_name": row.display_name,
        "avatar_url": avatar_url,
    }


def agent_member(row: Any, *, avatar_url: str | None) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": "agent",
        "handle": row.handle,
        "display_name": row.display_name,
        "avatar_url": avatar_url,
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
        "probe_configured": forge.Forge(settings.forge_github_token).configured_for(
            project.repository_url
        ),
    }


def forge_of(url: str) -> str | None:
    return forge.kind_of(url)


def absence(project: Any) -> dict[str, Any] | None:
    if project.absence_until is None:
        return None
    return {"until": ts(project.absence_until), "scope": project.absence_scope}


NO_IMAGE = {"available": False, "source": None}


def project_language(project: Any) -> str:
    """The working language of a new or existing project (§6.1)."""
    return "de" if (project.settings or {}).get("language") == "de" else "en"


def project_view(
    project: Any,
    settings: Settings,
    shown: dict[str, Any] | None = None,
    export: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`shown` is what `images.views` says the project shows as logo and banner, `export`
    the Keep the Why export as `ktw.export_for_view` holds it."""
    shown = shown or {}
    return {
        "slug": project.slug,
        "name": project.name,
        "state": project.state,
        "state_note": project.state_note,
        "state_changed_at": ts(project.state_changed_at),
        "repository": repository(project, settings),
        "logo": shown.get("logo", NO_IMAGE),
        "banner": shown.get("banner", NO_IMAGE),
        "keep_the_why": project.keep_the_why,
        "keep_the_why_export": export,
        "policy": policy.of(project),
        "absence": absence(project),
        "settings": {
            **(project.settings or {}),
            "language": project_language(project),
            "onboarding": onboarding.settings(project),
        },
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


def _placements(conn: Connection, membership_ids: set[int]) -> dict[int, dict[str, Any]]:
    """Per agent membership its active placement, as the Agents list needs it (§15.11)."""
    if not membership_ids:
        return {}
    rows = conn.execute(
        select(
            t.placement.c.membership_id,
            t.placement.c.id,
            t.placement.c.desired,
            t.placement.c.reported,
            t.runner.c.name,
        )
        .join(t.runner, t.runner.c.id == t.placement.c.runner_id)
        .where(t.placement.c.membership_id.in_(membership_ids), t.placement.c.active.is_(True))
    ).all()
    return {
        r.membership_id: {
            "id": r.id,
            "state": (r.reported or {}).get("state"),
            "desired": r.desired,
            "runner_name": r.name,
        }
        for r in rows
    }


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


def member_view(
    conn: Connection, row: Any, *, briefing: bool = False, details: bool = False
) -> dict[str, Any]:
    """The member view of §6.2: the principal, the membership, the live session.

    `briefing` only for the member itself and for `members:admin` (§6.2), never in
    an event that goes to everyone; the caller decides. `details` adds `owner` and
    `credentials`, for `members:admin` and an agent's owner, never in an event."""
    return member_views(conn, [row], briefing=briefing, details=details)[0]


def _sharing(conn: Connection, rows: Sequence[Any]) -> dict[int, list[dict[str, str]]]:
    """`shared_environment` of the agent rows given, per project (§5.3)."""
    from maity_hub import environment

    by_project: dict[str, set[int]] = {}
    for row in rows:
        by_project.setdefault(row.project_id, set()).add(row.id)
    found: dict[int, list[dict[str, str]]] = {}
    for project_id, ids in by_project.items():
        found.update(environment.views(conn, project_id, ids))
    return found


def member_views(
    conn: Connection,
    rows: Sequence[Any],
    *,
    briefing: bool | Callable[[Any], bool] = False,
    details: bool | Callable[[Any], bool] = False,
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
    pictures = avatars.urls(conn, [*agent_ids, *human_ids])
    live, latest_of = _sessions(conn, {r.id for r in rows if r.agent_id is not None})
    placed = _placements(conn, {r.id for r in rows if r.agent_id is not None})
    detailed = [
        r for r in rows if r.agent_id is not None and (details(r) if callable(details) else details)
    ]
    owners = _owners(conn, {r.agent_id: agents[r.agent_id] for r in detailed})
    from maity_hub import instances  # instances reads the tables views also reads

    handles = {a.id: a.handle for a in agents.values()}
    team_of = instances.views(conn, [r for r in rows if r not in detailed], handles)
    team_of.update(instances.views(conn, detailed, handles, details=True))
    counted = _credential_counts(conn, {r.id for r in detailed})
    sharing = _sharing(conn, detailed)
    views = []
    for row in rows:
        head = (
            agent_member(agents[row.agent_id], avatar_url=pictures[row.agent_id])
            if row.agent_id
            else human_member(humans[row.human_id], avatar_url=pictures[row.human_id])
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
                "placement": placed.get(row.id),  # always null for a human
            }
        )
        if row.agent_id is not None:
            view["team"] = instances.team(conn, row)
            view["instances"] = team_of.get(row.id, [])
        if row.removed_at is not None:
            view["removed_at"] = ts(row.removed_at)
        if briefing(row) if callable(briefing) else briefing:
            view["briefing"] = row.briefing
        if details(row) if callable(details) else details:
            view["owner"] = owners.get(row.agent_id) if row.agent_id else None
            view["credentials"] = counted.get(row.id, NO_CREDENTIALS) if row.agent_id else None
            # Never in an event: views built for events pass no `details` (§5.3).
            view["shared_environment"] = sharing.get(row.id, [])
        views.append(view)
    return views


NO_CREDENTIALS = {
    "active": 0,
    "never_resumed": 0,
    "revoked_recent": 0,
    "last_used_at": None,
    "last_used_via": None,
}
REVOKED_LISTED = timedelta(days=30)  # how long §10 keeps listing a revoked credential


def _owners(conn: Connection, agents: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per agent profile its human as `{id, handle, display_name}` (§6.2)."""
    owner_ids = {a.owner_id for a in agents.values()}
    if not owner_ids:
        return {}
    pictures = avatars.urls(conn, owner_ids)
    humans = {
        h.id: {
            "id": h.id,
            "handle": h.handle,
            "display_name": h.display_name,
            "avatar_url": pictures[h.id],
        }
        for h in conn.execute(select(t.human).where(t.human.c.id.in_(owner_ids)))
    }
    return {agent_id: humans[a.owner_id] for agent_id, a in agents.items()}


def _credential_counts(conn: Connection, membership_ids: set[int]) -> dict[int, dict[str, Any]]:
    """Counts and times of a membership's agent credentials, never an id or a secret."""
    if not membership_ids:
        return {}
    recent = clock.now() - REVOKED_LISTED
    counted: dict[int, dict[str, Any]] = {}
    for c in conn.execute(
        select(t.credential).where(t.credential.c.membership_id.in_(membership_ids))
    ):
        found = counted.setdefault(c.membership_id, dict(NO_CREDENTIALS))
        if c.revoked_at is not None:
            if c.revoked_at >= recent:
                found["revoked_recent"] += 1
            continue
        found["active"] += 1
        if c.resumed_at is None:
            found["never_resumed"] += 1
        if c.last_used_at is not None and (
            found["last_used_at"] is None or c.last_used_at > found["_latest"]
        ):
            found["_latest"] = c.last_used_at
            found["last_used_at"] = ts(c.last_used_at)
            found["last_used_via"] = c.last_used_via
    for found in counted.values():
        found.pop("_latest", None)
    return counted


def human_paused(row: Any) -> bool:
    """Paused by someone other than the member itself: the soft stop of §5.3."""
    return row.paused_since is not None and row.paused_by != (row.agent_id or row.human_id)


def agent_view(
    conn: Connection, row: Any, picture: dict[str, str | None] | None = None
) -> dict[str, Any]:
    """The agent profile (§6.3), for its owner; `picture` from `avatars.states` when a
    list has looked them up together."""
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
        # avatar_url and avatar_source: only its owner reads this
        **(picture if picture is not None else avatars.state(conn, row.id)),
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
        "last_used_via": row.last_used_via,
        "session_id": session,
        "instance": row.instance,
        "replaces": row.replaces,
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
        "via": row.via,
        "new_instance": bool(row.new_instance),
        "replaces": row.replaces,
        "instance": row.instance,
    }


def _release(
    conn: Connection, row: Any, fg: forge.Forge, tags: dict[str, Any]
) -> dict[str, Any] | None:
    if row.kind != "release":
        return None
    from maity_hub.releases import release_view

    return release_view(conn, row, fg, tags.get(row.id))


def task_view(conn: Connection, row: Any, fg: forge.Forge) -> dict[str, Any]:
    """The card as §6.4 shows it (the tasks slice adds its endpoints)."""
    return task_views(conn, [row], fg)[0]


def task_views(conn: Connection, rows: Sequence[Any], fg: forge.Forge) -> list[dict[str, Any]]:
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
    from maity_hub.instances import address
    from maity_hub.releases import tags  # releases reads views; imported here, not at the top

    release_tags = tags(conn, [r for r in rows if r.kind == "release"])
    now = clock.now()
    views = []
    for row in rows:
        claim = None
        if row.claim_holder is not None:
            holder = members[row.claim_holder]
            claim = {
                "holder": holder,
                "instance": row.claim_instance,
                "address": address(holder, row.claim_instance) if row.claim_instance else None,
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
                "mentions": row.mentions or [],
                "label": row.label,
                "status": row.status,
                "rank": row.rank,
                "area": row.area,
                "created_by": members.get(row.created_by),
                "assigned_to": members.get(row.assigned_to),
                "assigned_instance": row.assigned_instance,
                "claim": claim,
                "checkpoint": row.checkpoint,
                "depends_on": sorted(edges[row.id]["depends_on"]),
                "ships_with": sorted(edges[row.id]["ships_with"]),
                "blocked_by_request": row.blocked_by_request,
                "ktw_ref": row.ktw_ref,
                "report": row.report,
                "release": _release(conn, row, fg, release_tags),
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


def sees_reasons(reader: Any) -> bool:
    """A redaction's reason reaches the human owners and admins (§8.5); the redactor
    reads its own reason in any case."""
    return reader is not None and reader.kind == "human" and reader.role in ("owner", "admin")


def sees_chat_reasons(reader: Any, group_readers: set[str] | None = None) -> bool:
    """A chat message's redaction reason (§8.5): a direct chat's human party sees it, an
    agent never does. In a group chat, `group_readers` names the humans it reaches
    (`group_chats.reason_readers`): an owner reading along is a human but not one."""
    if reader is None or reader.kind != "human":
        return False
    return group_readers is None or reader.principal_id in group_readers


def _without_reason(row: Any, reader: Any, group_readers: set[str] | None = None) -> Any:
    """`row.payload` as `reader` sees it: the reason of a redaction (the `event_redacted`
    notice and the tombstone it leaves) is null for everyone it is not for (§8.5).
    Every other event's `reason` is untouched."""
    payload = row.payload
    redaction = row.kind == "event_redacted" or row.redacted
    if not redaction or not isinstance(payload, dict):
        return payload
    chat = row.conversation_id is not None
    if sees_chat_reasons(reader, group_readers) if chat else sees_reasons(reader):
        return payload
    if reader is not None and row.kind == "event_redacted" and row.actor_membership == reader.id:
        return payload  # the redactor's own notice
    if reader is not None and row.redacted and payload.get("by") == reader.principal_id:
        return payload  # the redactor's own tombstone
    return {**payload, "reason": None}  # no reader known: hidden, never shown by default


def event_views(conn: Connection, rows: Sequence[Any], reader: Any = None) -> list[dict[str, Any]]:
    """`event_view` for several events, with one query for the actors. `reader` (a
    `Membership`) is the member the views are for; without one a redaction's reason is
    hidden, so a caller that forgets to pass it shows less, never more."""
    actors = principal_ids(conn, (r.actor_membership for r in rows))
    from maity_hub.instances import instances_of

    instance_of = instances_of(
        conn, (r.actor_credential_id for r in rows if r.actor_membership is not None)
    )
    runner_ids = {r.actor_runner_id for r in rows if r.actor_runner_id is not None}
    runner_names = (
        dict(
            conn.execute(
                select(t.runner.c.id, t.runner.c.name).where(t.runner.c.id.in_(runner_ids))
            ).all()
        )
        if runner_ids
        else {}
    )
    from maity_hub.group_chats import reason_readers as group_reason_readers

    reason_readers = group_reason_readers(
        conn,
        {
            r.conversation_id
            for r in rows
            if r.conversation_id and (r.redacted or r.kind == "event_redacted")
        },
    )
    decided = ticker_read.details(conn, rows)
    notices = ticker_read.ticker_subjects(conn, rows)
    views = []
    for row in rows:
        actor: dict[str, Any] | None = None
        if row.actor_membership is not None:
            actor = {
                "kind": "member",
                "member_id": actors[row.actor_membership],
                "instance": instance_of.get(row.actor_credential_id or ""),
                "session_id": row.actor_session_id,
                "harness": row.actor_harness,
                "model": row.actor_model,
            }
        elif row.actor_runner_id is not None:  # §15.10
            actor = {
                "kind": "runner",
                "id": row.actor_runner_id,
                "name": runner_names.get(row.actor_runner_id),
                "credential_id": row.actor_credential_id,
                "session_id": row.actor_session_id,
                "via": row.actor_via,
            }
        payload = _without_reason(row, reader, reason_readers.get(row.conversation_id or ""))
        audience = row.audience
        if row.kind == "event_redacted" and row.subject_id in notices:
            audience = ticker_read.shaped_audience(audience, reader)  # like the item it removed
        if row.kind == "ticker":
            # Shaped per reader on every path that returns it (§17.5), its tombstone too.
            if row.redacted:
                audience = ticker_read.shaped_audience(audience, reader)
            else:
                payload, audience = ticker_read.shaped(
                    payload, audience, reader, decided.get(row.seq)
                )
        views.append(
            {
                "seq": row.seq,
                "kind": row.kind,
                "at": ts(row.at),
                "actor": actor,
                "subject": (
                    {"type": row.subject_type, "id": row.subject_id} if row.subject_type else None
                ),
                "audience": audience,
                "payload": payload,
                "redacted": row.redacted,
            }
        )
    return views
