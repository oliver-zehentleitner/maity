"""A member's bridges: the connections of agents that lend it their hands (docs/api.md §2.3,
"The bridge")."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import StringConstraints
from sqlalchemy import Connection, select

from maity_hub import bridges, idempotency, namespace
from maity_hub import tables as t
from maity_hub.access import Membership, member_row, membership
from maity_hub.cross_owner import owner_of
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import ApiError, forbidden, humans_only, not_found
from maity_hub.events import Actor, lock_project
from maity_hub.models import Strict
from maity_hub.namespace import ProjectRoute
from maity_hub.tables import BRIDGE_PURPOSE
from maity_hub.views import principal_id

router = APIRouter(route_class=ProjectRoute)

Purpose = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=BRIDGE_PURPOSE)
]


class BridgeIn(Strict):
    bridge: str
    purpose: Purpose


class BridgePatch(Strict):
    purpose: Purpose


def _served(conn: Connection, mine: Membership, member_id: str) -> Any:
    """The served agent, asked about by its owner alone, a human (§2.3): an admin who owns
    neither agent does not connect another human's agents."""
    if mine.kind != "human":
        raise humans_only("only the served agent's owner, a human, connects a bridge")
    served = member_row(conn, mine.project.id, member_id)
    if served.agent_id is not None and owner_of(conn, served) != mine.principal_id:
        raise bridges.agent_owner()
    return served


def _request(conn: Connection, request_id: str) -> dict[str, Any]:
    from maity_hub.routes.requests import load_request

    return load_request(conn, request_id)


@router.post("/projects/{owner}/{slug}/members/{member_id}/bridges")
def connect(
    slug: str, member_id: str, body: BridgeIn, request: Request, caller: AnyCaller
) -> JSONResponse:
    """Connect a bridge to the served agent: at once with one owner behind both, else a
    consent of the bridge's owner and of the project (§2.3)."""

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = lock_project(conn, mine.project.id)  # the limit of 5 counts consistently
        served = _served(conn, mine, member_id)
        bridge = bridges.bridge_member(conn, project.id, body.bridge)
        cross = bridges.check(conn, project, served, bridge, besides_pair=True)
        actor = caller.actor(mine.id)
        # A further POST for the pair replaces its open request, with the new purpose.
        bridges.withdraw(
            conn,
            bridges.open_requests(conn, served.id, bridge=bridge.id, pending_new=True),
            actor,
            "superseded",
        )
        if not cross:
            row = bridges.create(
                conn, project.id, served, bridge, body.purpose, False, mine.principal_id, actor
            )
            return idempotency.Outcome(201, "bridge", row.id, bridges.view(conn, row))
        asked = bridges.file(conn, project, mine, caller, served, bridge, body.purpose)
        return idempotency.Outcome(202, "request", asked[0], _request(conn, asked[0]))

    return idempotency.run(engine_of(request), request, caller, action)


@router.patch("/projects/{owner}/{slug}/members/{member_id}/bridges/{bridge_id}")
def change_purpose(
    slug: str,
    member_id: str,
    bridge_id: str,
    body: BridgePatch,
    request: Request,
    caller: AnyCaller,
) -> JSONResponse:
    """Change what a connection is for: at once with one owner, else a new consent while
    the old purpose holds until `go` (§2.3)."""

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = lock_project(conn, mine.project.id)
        served = _served(conn, mine, member_id)
        row = bridges.get(conn, project.id, served, bridge_id)
        actor = caller.actor(mine.id)
        bridges.withdraw(
            conn, bridges.open_requests(conn, served.id, connection=row.id), actor, "superseded"
        )
        if not row.cross_owner:
            changed = bridges.set_purpose(conn, row, body.purpose, actor)
            return idempotency.Outcome(200, "bridge", row.id, bridges.view(conn, changed))
        bridge = bridges.bridge_member(conn, project.id, str(principal_id(conn, row.bridge)))
        bridges.limits(conn, project, served, owner_of(conn, bridge))
        asked = bridges.file(
            conn, project, mine, caller, served, bridge, body.purpose, connection=row
        )
        return idempotency.Outcome(202, "request", asked[0], _request(conn, asked[0]))

    return idempotency.run(engine_of(request), request, caller, action)


@router.delete("/projects/{owner}/{slug}/members/{member_id}/bridges/{bridge_id}")
def disconnect(
    slug: str, member_id: str, bridge_id: str, request: Request, caller: AnyCaller
) -> JSONResponse:
    """End a connection: either agent's owner (the bridge's also from outside the project),
    either agent, a human with `members:admin` (§2.3). An open request to change it is
    withdrawn with it; the answer is the connection in its final state (§12)."""

    def action(conn: Connection) -> idempotency.Outcome:
        try:
            mine = membership(conn, caller, slug)
        except ApiError:
            # The bridge's owner may be no member and still ends its agent's connection,
            # seeing that one connection and nothing else of the project (§2.3, §1.3).
            row = _for_outside_owner(conn, caller, slug, member_id, bridge_id)
            ended = bridges.end(conn, row, _outside_actor(caller), by=caller.principal_id)
            return idempotency.Outcome(200, "bridge", row.id, bridges.view(conn, ended))
        project = lock_project(conn, mine.project.id)
        served = member_row(conn, project.id, member_id)
        row = bridges.get(conn, project.id, served, bridge_id)
        if not bridges.may_end(conn, mine, row):
            raise forbidden("members:admin")
        ended = bridges.end(conn, row, caller.actor(mine.id), by=mine.principal_id)
        return idempotency.Outcome(200, "bridge", row.id, bridges.view(conn, ended))

    return idempotency.run(engine_of(request), request, caller, action)


def _for_outside_owner(
    conn: Connection, caller: Any, slug: str, member_id: str, bridge_id: str
) -> Any:
    """The live connection whose bridge the calling human owns without being a member;
    anything else stays `not_found`, as the project does for a non-member."""
    project = namespace.resolve(conn, slug) if caller.kind == "human" else None
    if project is None:
        raise not_found()
    lock_project(conn, project.id)
    m, b = t.membership.c, t.bridge.c
    row = conn.execute(
        select(t.bridge)
        .select_from(t.bridge.join(t.membership, m.id == b.served))
        .where(
            b.id == bridge_id,
            b.project_id == project.id,
            b.live.is_(True),
            m.agent_id == member_id,
        )
    ).first()
    if row is None:
        raise not_found()
    bridge = conn.execute(select(t.membership).where(m.id == row.bridge)).one()
    if owner_of(conn, bridge) != caller.human_id:
        raise not_found()
    return row


def _outside_actor(caller: Any) -> Actor:
    """A human who is no member as the actor (§8.1)."""
    return Actor(membership_id=None, human_id=caller.human_id, via=caller.via)


def _load(conn: Connection, bridge_id: str) -> dict[str, Any]:
    row = conn.execute(select(t.bridge).where(t.bridge.c.id == bridge_id)).first()
    if row is None:
        raise not_found()
    return bridges.view(conn, row)


idempotency.LOADERS["bridge"] = idempotency.plain(_load)
