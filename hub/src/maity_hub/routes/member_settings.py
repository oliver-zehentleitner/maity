"""A human member's own settings in a project (docs/api.md §6.2).

Each setting is `null` (use the human's personal default from their notification
settings, §18.4) or a value for this project only. The first is `not_listening.minutes`,
how long an episode of one of the human's agent instances here lasts before it counts as
away (§5.3).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, select, update

from maity_hub import tables as t
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, engine_of
from maity_hub.errors import humans_only, invalid
from maity_hub.namespace import ProjectRoute
from maity_hub.notifications import preferences

router = APIRouter(route_class=ProjectRoute)

SETTINGS = ("not_listening",)


def own(row: Any) -> dict[str, Any]:
    """The member's overrides as stored, every setting present, `null` where none is set."""
    stored = row.own_settings or {}
    return {"not_listening": {"minutes": (stored.get("not_listening") or {}).get("minutes")}}


def not_listening_minutes(conn: Connection, row: Any, human_id: str) -> int:
    """The threshold the hub uses for this member's agents here: the override, or else the
    human's personal `not_listening.minutes` (§5.3, §6.2)."""
    override = own(row)["not_listening"]["minutes"]
    if override is not None:
        return int(override)
    return int(preferences.preferences(conn, human_id)["not_listening"]["minutes"])


def _view(conn: Connection, row: Any, human_id: str) -> dict[str, Any]:
    return {
        **own(row),
        "effective": {"not_listening": {"minutes": not_listening_minutes(conn, row, human_id)}},
    }


def _mine(conn: Connection, caller: Any, slug: str) -> tuple[Any, str]:
    if caller.kind != "human" or caller.human_id is None:
        raise humans_only("a member's own settings are a human's")
    return membership(conn, caller, slug), caller.human_id  # `not_found` without one


@router.get("/projects/{owner}/{slug}/me/settings")
def get_own_settings(slug: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine, human_id = _mine(conn, caller, slug)
        return JSONResponse(_view(conn, mine.row, human_id))


@router.patch("/projects/{owner}/{slug}/me/settings")
def patch_own_settings(
    slug: str, request: Request, caller: AnyCaller, body: Annotated[dict[str, Any], Body()]
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        # Who may call and on which membership first, as `GET` does: a stranger's body is
        # never judged, it learns nothing but `not_found`.
        mine, human_id = _mine(conn, caller, slug)
        errors: dict[str, str] = {}
        for key in body:
            if key not in SETTINGS:
                errors[key] = "extra_forbidden"
        given = body.get("not_listening")
        if "not_listening" in body:
            if not isinstance(given, dict) or not set(given) <= {"minutes"}:
                errors["not_listening"] = "invalid"
            elif given.get("minutes") is not None and not preferences.minutes_valid(
                given["minutes"]
            ):
                errors["not_listening.minutes"] = "invalid"
        if errors:
            raise invalid(errors)
        stored = dict(mine.row.own_settings or {})
        if isinstance(given, dict) and "minutes" in given:
            stored["not_listening"] = {"minutes": given["minutes"]}  # `null`: the default
        conn.execute(
            update(t.membership).where(t.membership.c.id == mine.id).values(own_settings=stored)
        )
        row = conn.execute(select(t.membership).where(t.membership.c.id == mine.id)).one()
        return JSONResponse(_view(conn, row, human_id))
