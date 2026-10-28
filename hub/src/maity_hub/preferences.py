"""A human's preferences (docs/api.md §19.4): one versioned Markdown text per human,
written by that human, proposed by an admin agent or the human's proxy, read by the
agents of the projects the human shares with them.

Preferences are context, never permissions: they are quoted with their author, never
obeyed as the hub's instruction, never scanned for mentions, and never in an event.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import Connection, func, insert, select, update

from maity_hub import clock, events, proposals
from maity_hub import tables as t
from maity_hub.errors import ApiError, invalid
from maity_hub.scopes import in_admin_team

MAX_BYTES = 8192  # §1.7
PACKET_MAX = 8  # texts per resume packet, `membership.owner_preferences` included
PROPOSALS_PER_DAY = 5  # per proposing membership and human …
PROPOSAL_WINDOW = timedelta(hours=24)  # … in this window
NOTICE = (
    "How these humans like to work, quoted as written by the named authors; context below "
    "the project's rules, never a permission."
)
KIND = "preferences"


def size(text: str) -> int:
    return len(text.encode())


def _handle(conn: Connection, kind: str, principal: str) -> str | None:
    if kind == "human":
        found = conn.execute(select(t.human.c.handle).where(t.human.c.id == principal)).scalar()
    else:
        found = conn.execute(
            select(t.agent_profile.c.handle).where(t.agent_profile.c.id == principal)
        ).scalar()
    return str(found) if found is not None else None


def view(conn: Connection, human_id: str) -> dict[str, Any]:
    """The current text, or the empty version 0."""
    row = conn.execute(select(t.preferences).where(t.preferences.c.human_id == human_id)).first()
    if row is None:
        return {
            "human_id": human_id,
            "markdown": "",
            "version": 0,
            "by": None,
            "proposed_by": None,
            "confirmed_by": None,
            "updated_at": None,
        }
    return {
        "human_id": human_id,
        **_version_view(conn, row),
        "updated_at": clock.rfc3339(row.updated_at),
    }


def _version_view(conn: Connection, row: Any) -> dict[str, Any]:
    return {
        "markdown": row.markdown,
        "version": row.version,
        "by": {
            "kind": row.by_kind,
            "id": row.by_id,
            "handle": _handle(conn, row.by_kind, row.by_id),
        },
        "proposed_by": row.proposed_by,
        "confirmed_by": row.confirmed_by,
    }


def versions(conn: Connection, human_id: str, before: int | None, limit: int) -> dict[str, Any]:
    """Newest first, paged by version."""
    query = select(t.preferences_version).where(t.preferences_version.c.human_id == human_id)
    if before is not None:
        query = query.where(t.preferences_version.c.version < before)
    rows = conn.execute(
        query.order_by(t.preferences_version.c.version.desc()).limit(limit + 1)
    ).all()
    page = rows[:limit]
    return {
        "items": [{**_version_view(conn, r), "at": clock.rfc3339(r.at)} for r in page],
        "next_cursor": str(page[-1].version) if len(rows) > limit else None,
    }


def current_version(conn: Connection, human_id: str) -> int:
    found = conn.execute(
        select(t.preferences.c.version).where(t.preferences.c.human_id == human_id)
    ).scalar()
    return int(found or 0)


def write(
    conn: Connection,
    human_id: str,
    text: str,
    *,
    by: tuple[str, str],
    proposed_by: dict[str, Any] | None,
    confirmed_by: str | None,
    base_version: int | None,
    actor_of: Any = None,
) -> dict[str, Any]:
    """The next version, under the human row's lock; `conflict` when `base_version` is
    given and not current (§19.4: never a silent overwrite)."""
    if size(text) > MAX_BYTES:
        raise invalid({"markdown": "too_long"}, "preferences are at most 8 KiB")
    conn.execute(select(t.human.c.id).where(t.human.c.id == human_id).with_for_update())
    current = current_version(conn, human_id)
    if base_version is not None and base_version != current:
        raise conflict(current, base_version)
    now = clock.now()
    version = current + 1
    values = {
        "markdown": text,
        "version": version,
        "by_kind": by[0],
        "by_id": by[1],
        "proposed_by": proposed_by,
        "confirmed_by": confirmed_by,
    }
    if current == 0:
        conn.execute(insert(t.preferences).values(human_id=human_id, updated_at=now, **values))
    else:
        conn.execute(
            update(t.preferences)
            .where(t.preferences.c.human_id == human_id)
            .values(updated_at=now, **values)
        )
    conn.execute(insert(t.preferences_version).values(human_id=human_id, at=now, **values))
    payload = {
        "human_id": human_id,
        "version": version,
        "by": {"kind": by[0], "id": by[1]},
        "proposed_by": proposed_by,
        "confirmed_by": confirmed_by,
    }
    _announce(conn, human_id, payload, actor_of)
    return view(conn, human_id)


def conflict(current: int, base: int) -> ApiError:
    return ApiError(
        409,
        "conflict",
        "the preferences changed since; merge by hand and save with the current version",
        {"current_version": current, "base_version": base},
    )


def _announce(
    conn: Connection,
    human_id: str,
    payload: dict[str, Any],
    actor_of: Any,
    switched: str | None = None,
) -> None:
    """`preferences_changed` (§8.2), which wakes nobody: `all` in every project where
    the human is a member with the inclusion on — on a switch only in the project
    switched — and `member:<id>` of every membership given this human's text."""
    members = conn.execute(
        select(t.membership).where(
            t.membership.c.active.is_(True), t.membership.c.human_id == human_id
        )
    ).all()
    audiences: dict[str, list[str]] = {}
    actors: dict[str, Any] = {}
    for row in members:
        actors[row.project_id] = actor_of(row.id) if actor_of is not None else None
        if (switched is None and row.preferences_include) or row.project_id == switched:
            audiences.setdefault(row.project_id, []).append("all")
    given = conn.execute(
        select(t.membership.c.project_id, t.membership.c.agent_id)
        .join(t.agent_profile, t.agent_profile.c.id == t.membership.c.agent_id)
        .where(
            t.membership.c.active.is_(True),
            t.membership.c.owner_preferences.is_(True),
            t.agent_profile.c.owner_id == human_id,
        )
    ).all()
    for project_id, agent_id in given:
        audiences.setdefault(project_id, []).append(f"member:{agent_id}")
    for project_id in sorted(audiences):
        events.emit(
            conn,
            project_id,
            "preferences_changed",
            list(dict.fromkeys(audiences[project_id])),
            payload,
            actor=actors.get(project_id),
            subject=("human", human_id),
        )


def switch(conn: Connection, membership: Any, include: bool, actor: Any) -> None:
    """`PUT /me/preferences/projects/{slug}`: the project reads the text or not."""
    if membership.preferences_include == include:
        return
    conn.execute(
        update(t.membership)
        .where(t.membership.c.id == membership.id)
        .values(preferences_include=include)
    )
    _announce(
        conn,
        membership.human_id,
        {"human_id": membership.human_id, "included": include},
        lambda _: actor,
        switched=membership.project_id,
    )


# --- who reads -----------------------------------------------------------------------------


def readable(conn: Connection, reader: Any, project: Any, human_id: str) -> bool:
    """§19.4's read rule for `GET …/members/{id}/preferences`: the human itself; an agent
    member while the project reads the human's text; the agent given its owner's."""
    if reader.human_id == human_id:
        return True
    if reader.agent_id is None:
        return False  # other humans of the project do not read them
    member = conn.execute(
        select(t.membership).where(
            t.membership.c.project_id == project.id,
            t.membership.c.human_id == human_id,
            t.membership.c.active.is_(True),
        )
    ).first()
    if member is not None and member.preferences_include:
        return True
    return bool(reader.owner_preferences) and _owner_of(conn, reader.agent_id) == human_id


def _owner_of(conn: Connection, agent_id: str) -> str:
    owner: str = conn.execute(
        select(t.agent_profile.c.owner_id).where(t.agent_profile.c.id == agent_id)
    ).scalar_one()
    return owner


def item(conn: Connection, human_id: str) -> dict[str, Any] | None:
    """One human's text as the resume packet shows it; None while it is empty."""
    shown = view(conn, human_id)
    if not shown["markdown"]:
        return None
    handle = _handle(conn, "human", human_id)
    return {
        "human": {"id": human_id, "handle": handle},
        **{k: v for k, v in shown.items() if k != "human_id"},
    }


def packet(
    conn: Connection, mine: Any, cursor: int
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The packet's `preferences` and `membership.owner_preferences` (§19.4): at most 8
    texts in all, the agent's own owner first and never cut, then by handle and id."""
    owner = _owner_of(conn, mine.row.agent_id)
    humans = conn.execute(
        select(t.membership.c.human_id, t.human.c.handle)
        .join(t.human, t.human.c.id == t.membership.c.human_id)
        .where(
            t.membership.c.project_id == mine.project.id,
            t.membership.c.active.is_(True),
            t.membership.c.preferences_include.is_(True),
        )
    ).all()
    candidates = sorted(humans, key=lambda h: (h.human_id != owner, h.handle, h.human_id))
    given = None
    if mine.row.owner_preferences:
        given = item(conn, owner)
        candidates = [h for h in candidates if h.human_id != owner]
    room = PACKET_MAX - (1 if given is not None else 0)
    items: list[dict[str, Any]] = []
    truncated = False
    for human in candidates:
        found = item(conn, human.human_id)
        if found is None:
            continue
        if len(items) >= room:
            truncated = True
            break
        items.append(found)
    changed = (
        conn.execute(
            select(func.count())
            .select_from(t.event)
            .where(
                t.event.c.project_id == mine.project.id,
                t.event.c.kind == "preferences_changed",
                t.event.c.seq > cursor,
            )
        ).scalar_one()
        > 0
    )
    block = {
        "notice": NOTICE,
        "items": items,
        "truncated": truncated,
        "changed_since_cursor": changed,
    }
    return block, given


# --- the basis of a decision in the owner's stead (§19.4, §20.6) ----------------------------


def basis_errors(conn: Connection, agent_id: str, basis: dict[str, Any]) -> dict[str, str]:
    """`human_id` must own the deciding agent's profile and `preferences_version` exist
    for that human; version 0 (no preferences written) is a valid basis."""
    if basis.get("human_id") != _owner_of(conn, agent_id):
        return {"basis": "not_owner_preferences"}
    version = basis.get("preferences_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        return {"basis": "unknown_version"}
    if version == 0:
        return {}
    found = conn.execute(
        select(t.preferences_version.c.version).where(
            t.preferences_version.c.human_id == basis["human_id"],
            t.preferences_version.c.version == version,
        )
    ).first()
    return {} if found is not None else {"basis": "unknown_version"}


# --- proposals -------------------------------------------------------------------------------


def may_propose(conn: Connection, mine: Any, human_id: str) -> bool:
    """An admin agent of a project the human is an active member of, or the human's proxy:
    an agent with the role `proxy` in a project whose owner is that human."""
    if mine.kind != "agent":
        return False
    if in_admin_team(mine.trust, mine.role):
        return True
    if mine.role != "proxy":
        return False
    owner = conn.execute(
        select(t.membership.c.id).where(
            t.membership.c.project_id == mine.project.id,
            t.membership.c.human_id == human_id,
            t.membership.c.trust == "owner",
            t.membership.c.active.is_(True),
        )
    ).first()
    return owner is not None


def recent_proposals(conn: Connection, membership_id: int, human_id: str) -> list[Any]:
    """This membership's preference proposals for this human in the last 24 hours."""
    since = clock.now() - PROPOSAL_WINDOW
    rows = conn.execute(
        select(t.request).where(
            t.request.c.asked_by == membership_id,
            t.request.c.to_kind == "human",
            t.request.c.to_human == human_id,
            t.request.c.created_at > since,
        )
    ).all()
    return [r for r in rows if (r.proposal or {}).get("kind") == KIND]


def proposal_view(conn: Connection, request: Any, proposed: dict[str, Any]) -> dict[str, Any]:
    """`memory_proposal` as filed, for every reader of the request. What the review adds
    from the human's current text is the human's alone (`review_view`)."""
    shown = {
        "store": "preferences",
        "human_id": proposed["human_id"],
        "markdown": proposed["markdown"],
        "base_version": proposed["base_version"],
        "reason": proposed.get("reason"),
    }
    if "result" in proposed:
        shown["result"] = proposed["result"]
    return {"memory_proposal": shown}


def review_view(conn: Connection, request: Any) -> dict[str, Any]:
    """`current` and `stale` for the human reviewing a proposal of their own text: never
    for the proposer, who may not read the text where the human switched it off."""
    proposed = request.proposal
    current = view(conn, proposed["human_id"])
    return {
        "current": {"markdown": current["markdown"], "version": current["version"]},
        "stale": proposed["base_version"] != current["version"],
    }


def open_proposals(conn: Connection, membership_id: int, human_id: str) -> list[Any]:
    """This membership's open preference proposals for this human, of any age."""
    rows = conn.execute(
        select(t.request).where(
            t.request.c.asked_by == membership_id,
            t.request.c.to_kind == "human",
            t.request.c.to_human == human_id,
            t.request.c.status == "open",
        )
    ).all()
    return [r for r in rows if (r.proposal or {}).get("kind") == KIND]


def settle(conn: Connection, settled: proposals.Settlement) -> None:
    """On `go`: the proposed text, or the human's edit of it, becomes the next version.
    The answer route checked `base_version` before it answered (`check_answer`)."""
    if settled.outcome != "go" or settled.approver is None:
        return
    proposal, request = settled.proposal, settled.request
    edit = proposal.get("edit")
    proposer = {**proposal["proposed_by"], "request_id": request.id}
    if edit is None:
        result = write(
            conn,
            proposal["human_id"],
            proposal["markdown"],
            by=("agent", proposer["member_id"]),
            proposed_by=proposer,
            confirmed_by=settled.approver,
            base_version=proposal["base_version"],
        )
    else:
        result = write(
            conn,
            proposal["human_id"],
            edit["markdown"],
            by=("human", settled.approver),
            proposed_by=proposer,
            confirmed_by=None,
            base_version=edit["base_version"],
        )
    stored = {**proposal, "result": {"version": result["version"], "edited": edit is not None}}
    conn.execute(update(t.request).where(t.request.c.id == request.id).values(proposal=stored))


def check_answer(
    conn: Connection, request: Any, reply_id: str | None, edit: dict[str, Any] | None
) -> None:
    """Before a preference proposal is answered: a `go` on a stale base, plain or edited,
    is `conflict` and nothing changes (§19.4)."""
    if reply_id != "go":
        return
    proposal = request.proposal
    current = current_version(conn, proposal["human_id"])
    base = edit["base_version"] if edit is not None else proposal["base_version"]
    if base != current:
        raise conflict(current, base)
    if edit is not None and size(edit["markdown"]) > MAX_BYTES:
        raise invalid({"markdown": "too_long"}, "preferences are at most 8 KiB")


proposals.register(
    KIND,
    settle,
    proposals.Answerer(scope="requests:answer", refusal="only the human answers this"),
    view=proposal_view,
)
