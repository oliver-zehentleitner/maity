"""`GET /projects/{owner}/{slug}/keep-the-why` (docs/api.md §11.3)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from maity_hub import ktw
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, engine_of, reader_of
from maity_hub.errors import ApiError, not_found
from maity_hub.namespace import ProjectRoute

router = APIRouter(route_class=ProjectRoute)


@router.get("/projects/{owner}/{slug}/keep-the-why")
def read_keep_the_why(
    slug: str,
    request: Request,
    caller: AnyCaller,
    max_age: int = Query(default=ktw.DEFAULT_MAX_AGE, ge=0, le=86400),
    member: str | None = Query(default=None, max_length=2048),
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
    project = mine.project
    try:
        entry, fresh = ktw.CACHE.get(
            reader_of(request), project.id, project.repository_url, max_age
        )
    except ktw.Busy:
        raise ApiError(
            503,
            "ktw_unavailable",
            "the Keep the Why family is being read; try again shortly",
            {"reason": "forge_unavailable"},
        ) from None
    snapshot = entry.snapshot
    if snapshot is None:
        raise ApiError(
            409,
            "ktw_not_configured",
            "the repository names no Keep the Why export (.keep-the-why, dashboard-state)",
        )
    if snapshot.error is not None:
        details: dict[str, object] = {"reason": snapshot.error["reason"]}
        if snapshot.members:
            details["last"] = snapshot.answer(fresh=False)
        raise ApiError(503, "ktw_unavailable", "the root .keep-the-why could not be read", details)
    if member is not None and all(m.path != member for m in snapshot.members):
        raise not_found()
    return JSONResponse(snapshot.answer(member, fresh))
