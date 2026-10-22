"""`GET /projects/{slug}/probe` (docs/api.md §11)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from maity_hub import clock, forge, probe
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, engine_of, reader_of
from maity_hub.errors import ApiError, invalid

router = APIRouter()

REF = r"^[^\s~^:?*\[\\]{1,255}$"  # what git accepts in a ref name, roughly


@router.get("/projects/{slug}/probe")
def read_probe(
    slug: str,
    request: Request,
    caller: AnyCaller,
    pr: int | None = Query(default=None, ge=1, le=2**31),
    branch: str | None = Query(default=None, pattern=REF),
    tag: str | None = Query(default=None, pattern=REF),
    max_age: int = Query(default=probe.MAX_AGE, ge=0, le=86400),
) -> JSONResponse:
    engine = engine_of(request)
    with engine.begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
    project = mine.project
    if pr is None and branch is None and tag is None:
        raise invalid({"pr": "one_of_pr_branch_tag"})
    fg = reader_of(request)
    if not fg.configured_for(project.repository_url):
        raise ApiError(
            409, "probe_not_configured", "the hub holds no forge token for this repository"
        )
    wanted = [("pr", str(pr) if pr else None), ("branch", branch), ("tag", tag)]
    shown: dict[str, Any] = {"pr": None, "branch": None, "tag": None}
    observations = []
    for kind, ref in wanted:
        if ref is None:
            continue
        try:
            observation = probe.observe(engine, fg, project, kind, ref, max_age)
        except forge.ForgeUnavailableError:
            stored = probe.last(engine, project.id, kind, ref)
            details = {"last": stored.stamped()} if stored is not None else None
            raise ApiError(503, "probe_unavailable", "the forge did not answer", details) from None
        observations.append(observation)
        shown[kind] = observation.shown()
    return JSONResponse(
        {
            "forge": forge.kind_of(project.repository_url),
            "repository": forge.repository_of(project.repository_url),
            "observed_at": clock.rfc3339(min(o.observed_at for o in observations)),
            "fresh": all(o.fresh for o in observations),
            **shown,
        }
    )
