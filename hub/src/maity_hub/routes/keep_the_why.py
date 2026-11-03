"""`GET /projects/{owner}/{slug}/keep-the-why` (docs/api.md §11.3) and the Keep the Why views'
reads, `…/keep-the-why/export` and `…/keep-the-why/bodies` (§11.5)."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from maity_hub import clock, forge, ktw, ktw_reads
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, engine_of, reader_of
from maity_hub.errors import ApiError, not_found, probe_not_configured
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


# --- §11.5: the Keep the Why views' reads -------------------------------------------------------


def _matches(header: str | None, etag: str) -> bool:
    """Whether `If-None-Match` names `etag`, weak or strong, or is `*`."""
    if not header:
        return False
    tags = [tag.strip() for tag in header.split(",")]
    return "*" in tags or any(tag.removeprefix("W/") == etag for tag in tags)


def _views_read(
    which: str,
    slug: str,
    request: Request,
    caller: AnyCaller,
    canonical: str | None,
    root: str | None,
    max_age: int,
) -> Response:
    """One of §11.5's reads. The caller is authorized before `If-None-Match` is compared, so
    one without `project:read` gets `not_found`, never `304`."""
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
    project = mine.project
    if not project.repository_url:
        raise ApiError(
            409,
            "ktw_not_configured",
            "the repository names no Keep the Why export (.keep-the-why, dashboard-state)",
        )
    fg = reader_of(request).for_project(project.id)
    if fg.refused is not None:
        raise probe_not_configured(fg.refused if mine.may("project:admin") else None)
    held = fg.retry_at()
    if held is not None:
        raise ApiError(
            503, "probe_unavailable", "the forge budget is spent", {"retry_at": clock.rfc3339(held)}
        )
    read = ktw_reads.export if which == "state" else ktw_reads.bodies
    try:
        served = read(
            fg, project.id, project.repository_url, canonical or None, root or "", max_age
        )
    except forge.ForgeUnavailableError as error:  # the budget ran out during the read
        details = {"retry_at": clock.rfc3339(error.retry_at)} if error.retry_at else None
        raise ApiError(503, "probe_unavailable", "the forge did not answer", details) from None
    except ktw_reads.Refused as refused:
        raise ApiError(
            refused.status, refused.code, refused.message, refused.details or None
        ) from None
    headers = {"ETag": served.etag, "Cache-Control": "private, no-cache"}
    if _matches(request.headers.get("If-None-Match"), served.etag):
        return Response(status_code=304, headers=headers)
    return Response(served.document(which), media_type="application/json", headers=headers)


@router.get("/projects/{owner}/{slug}/keep-the-why/export")
def read_keep_the_why_export(
    slug: str,
    request: Request,
    caller: AnyCaller,
    canonical: str | None = Query(default=None, max_length=2048),
    root: str | None = Query(default=None, max_length=2048),
    max_age: int = Query(default=ktw.DEFAULT_MAX_AGE, ge=0, le=86400),
) -> Response:
    return _views_read("state", slug, request, caller, canonical, root, max_age)


@router.get("/projects/{owner}/{slug}/keep-the-why/bodies")
def read_keep_the_why_bodies(
    slug: str,
    request: Request,
    caller: AnyCaller,
    canonical: str | None = Query(default=None, max_length=2048),
    root: str | None = Query(default=None, max_length=2048),
    max_age: int = Query(default=ktw.DEFAULT_MAX_AGE, ge=0, le=86400),
) -> Response:
    return _views_read("bodies", slug, request, caller, canonical, root, max_age)
