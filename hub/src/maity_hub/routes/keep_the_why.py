"""`GET /projects/{owner}/{slug}/keep-the-why` (docs/api.md §11.3) and the Keep the Why views'
reads, `…/keep-the-why/export` and `…/keep-the-why/bodies` (§11.5). An outsider of a public
project in the operator's own namespaces reads all three while the hub last found its repository
public and the forge says it is public now, read with the instance's token and no grant into a
cache of their own (§2.3)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from maity_hub import access, clock, forge, ktw, ktw_reads
from maity_hub.deps import AnyCaller, engine_of, reader_of, settings_of
from maity_hub.errors import (
    ApiError,
    ktw_not_configured,
    ktw_unavailable,
    not_found,
    probe_not_configured,
)
from maity_hub.namespace import ProjectRoute

router = APIRouter(route_class=ProjectRoute)


def _require_why(mine: access.Membership | access.OutsideReader) -> None:
    """`project:read`, and for an outsider the public view's condition (§2.3, §16.9 **Why**,
    `public_project_views.why_data`): only while the hub last found the project's repository
    public, otherwise `not_found` as on every route closed to it. The cheap first check:
    `_outside_reader` asks the forge itself after it (the stored flag lags the forge)."""
    mine.require("project:read")
    if isinstance(mine, access.OutsideReader) and mine.project.repository_public is not True:
        raise not_found()


def _spent(retry_at: datetime) -> ApiError:
    """`probe_unavailable` while the reader's budget is spent (§11.4), as for a member."""
    return ApiError(
        503,
        "probe_unavailable",
        "the forge's rate limit is spent",
        {"retry_at": clock.rfc3339(retry_at)},
    )


def _outside_token(request: Request, project: Any) -> str:
    """The token an outsider's reads use: the instance's, and only for a project in the
    operator's own namespaces, which that token serves, exactly where the public view shows
    its **Why** (§2.3, §16.9: `public_project_views.render_views`' `by_instance`); `not_found`
    everywhere else, as `access.gate` answers before the query (the lead, seq 186180: no
    anonymous read, whose hub-wide budget a loop over projects could drain). Never
    `Forge.for_project`, which may write the project's source and the grants' state: an
    outsider's read leaves no trace."""
    hub = settings_of(request)
    token = hub.forge_github_token
    instance = hub.forge_instance_namespaces if token is not None else None
    with engine_of(request).connect() as conn:
        served = access.instance_serves_project(conn, project, instance)
    if token is None or not served:
        raise not_found()
    return token


def _outside_reader(request: Request, project: Any, max_age: int) -> forge.Forge:
    """An outsider's reader (`ktw_reads.outside_reader`): no grant, bound to no project, and
    only while the forge says now that the repository is public; `not_found` otherwise, as a
    closed route answers (§2.3), and `probe_unavailable` while the reader's budget is spent,
    as for a member. The project's own source is never asked (`_outside_token`)."""
    token = _outside_token(request, project)
    try:
        reader = ktw_reads.outside_reader(token, project.id, project.repository_url, max_age)
    except forge.ForgeUnavailableError as error:  # only a spent budget is raised
        if error.retry_at is None:
            raise not_found() from None
        raise _spent(error.retry_at) from None
    if reader is None:
        raise not_found()
    return reader


@router.get("/projects/{owner}/{slug}/keep-the-why")
@access.outside_read
def read_keep_the_why(
    slug: str,
    request: Request,
    caller: AnyCaller,
    max_age: int = Query(default=ktw.DEFAULT_MAX_AGE, ge=0, le=86400),
    member: str | None = Query(default=None, max_length=2048),
) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = access.reader(conn, caller, slug)
    _require_why(mine)
    project = mine.project
    outside = isinstance(mine, access.OutsideReader)
    reader, cache = reader_of(request), ktw.CACHE
    if outside:  # never the members' cache, which a grant may fill
        reader, cache = _outside_reader(request, project, max_age), ktw_reads.OUTSIDE_CACHE
    try:
        entry, fresh = cache.get(reader, project.id, project.repository_url, max_age)
    except ktw.Busy:
        raise ktw_unavailable(
            "forge_unavailable", "the Keep the Why family is being read; try again shortly"
        ) from None
    snapshot = entry.snapshot
    if snapshot is None:
        raise ktw_not_configured()
    if outside and snapshot.not_covered is not None:
        raise not_found()  # the reader without a grant was refused: not public to it
    if snapshot.error is not None:
        last = {"last": snapshot.answer(fresh=False)} if snapshot.members else {}
        raise ktw_unavailable(
            snapshot.error["reason"], "the root .keep-the-why could not be read", **last
        )
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
    mine: access.Membership | access.OutsideReader,
    request: Request,
    canonical: str | None,
    root: str | None,
    max_age: int,
) -> Response:
    """One of §11.5's reads, for the reader its endpoint read (`access.reader`). The caller is
    authorized before `If-None-Match` is compared, so one without `project:read`, or an
    outsider while the repository is not public, gets `not_found`, never `304`. An outsider's
    family is read without a grant into `ktw_reads.OUTSIDE_CACHE` (`_outside_reader`)."""
    _require_why(mine)
    project = mine.project
    if not project.repository_url:
        raise ktw_not_configured()
    outside = isinstance(mine, access.OutsideReader)
    read = ktw_reads.export if which == "state" else ktw_reads.bodies
    if outside:
        reader = _outside_reader(request, project, max_age)
        spent = reader.retry_at()
        if spent is not None:
            raise _spent(spent)
        try:
            served = read(
                reader,
                reader,
                project.id,
                project.repository_url,
                canonical or None,
                root or "",
                max_age,
                ktw_reads.OUTSIDE_CACHE,
            )
        except forge.NotCoveredError:
            raise not_found() from None  # refused to the reader without a grant: not public
        except forge.ForgeUnavailableError as error:
            if error.retry_at is None:
                raise ktw_unavailable("forge_unavailable") from None
            raise _spent(error.retry_at) from None
        return _answer(which, served, request)
    base = reader_of(request)
    fg = base.for_project(project.id)
    admin = mine.may("project:admin")
    try:
        if not fg.configured_for(project.repository_url):
            raise forge.NotCoveredError(forge.unread_reason(fg, project.repository_url))
        spent = fg.retry_at()  # read once: on PostgreSQL each read is a query
        if spent is not None:
            raise forge.ForgeUnavailableError(
                "the forge's rate limit is spent", rate_limited=True, retry_at=spent
            )
        # Every call, not only when the cache is refreshed: no export held in memory outlives
        # the grant or the visibility (§11.5). With the instance token this is §11.4's
        # visibility check (kept for 10 minutes); an owner's grant is re-chosen by
        # `for_project` itself.
        fg.require_covered(forge.repository_of(project.repository_url))
        served = read(
            fg,
            ktw_reads.named_reader(base, fg),
            project.id,
            project.repository_url,
            canonical or None,
            root or "",
            max_age,
        )
    except forge.NotCoveredError as error:
        raise probe_not_configured(error.reason if admin else None) from None
    except forge.ForgeUnavailableError as error:
        if error.retry_at is None:
            raise ktw_unavailable("forge_unavailable") from None
        raise _spent(error.retry_at) from None
    return _answer(which, served, request)


def _answer(which: str, served: ktw_reads.Served, request: Request) -> Response:
    headers = {"ETag": served.etag, "Cache-Control": "private, no-cache"}
    if _matches(request.headers.get("If-None-Match"), served.etag):
        return Response(status_code=304, headers=headers)
    return Response(served.document(which), media_type="application/json", headers=headers)


@router.get("/projects/{owner}/{slug}/keep-the-why/export")
@access.outside_read
def read_keep_the_why_export(
    slug: str,
    request: Request,
    caller: AnyCaller,
    canonical: str | None = Query(default=None, max_length=2048),
    root: str | None = Query(default=None, max_length=2048),
    max_age: int = Query(default=ktw.DEFAULT_MAX_AGE, ge=0, le=86400),
) -> Response:
    with engine_of(request).begin() as conn:
        mine = access.reader(conn, caller, slug)
    return _views_read("state", mine, request, canonical, root, max_age)


@router.get("/projects/{owner}/{slug}/keep-the-why/bodies")
@access.outside_read
def read_keep_the_why_bodies(
    slug: str,
    request: Request,
    caller: AnyCaller,
    canonical: str | None = Query(default=None, max_length=2048),
    root: str | None = Query(default=None, max_length=2048),
    max_age: int = Query(default=ktw.DEFAULT_MAX_AGE, ge=0, le=86400),
) -> Response:
    with engine_of(request).begin() as conn:
        mine = access.reader(conn, caller, slug)
    return _views_read("bodies", mine, request, canonical, root, max_age)
