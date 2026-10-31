"""A member's bridges: the connections of agents that lend it their hands (docs/api.md §2.3,
"The bridge")."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import StringConstraints
from sqlalchemy import Connection

from maity_hub import bridges, idempotency
from maity_hub.access import Membership, member_row, membership
from maity_hub.cross_owner import owner_of
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import forbidden, humans_only
from maity_hub.events import lock_project
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
    """End a connection: either agent's owner, either agent, a human with `members:admin`
    (§2.3). An open request to change it is withdrawn with it."""

    def action(conn: Connection) -> idempotency.Outcome:
        mine = membership(conn, caller, slug)
        project = lock_project(conn, mine.project.id)
        served = member_row(conn, project.id, member_id)
        row = bridges.get(conn, project.id, served, bridge_id)
        if not bridges.may_end(conn, mine, row):
            raise forbidden("members:admin")
        bridges.end(conn, row, caller.actor(mine.id))
        return idempotency.Outcome(204, None, None, {})

    return idempotency.run(engine_of(request), request, caller, action)
