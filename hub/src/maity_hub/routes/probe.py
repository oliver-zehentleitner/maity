"""`GET /projects/{owner}/{slug}/probe` (docs/api.md §11)."""

from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from maity_hub import clock, forge, probe
from maity_hub.access import membership
from maity_hub.db import read_transaction
from maity_hub.deps import AnyCaller, engine_of, reader_of
from maity_hub.errors import ApiError, invalid, probe_not_configured
from maity_hub.namespace import ProjectRoute

router = APIRouter(route_class=ProjectRoute)

REF = r"^[^\s~^:?*\[\\]{1,255}$"  # what git accepts in a ref name, roughly
SHA = re.compile(r"[0-9a-fA-F]{40}")  # a commit by its full sha, never a prefix (§6.6)


@router.get("/projects/{owner}/{slug}/probe")
def read_probe(
    slug: str,
    request: Request,
    caller: AnyCaller,
    pr: int | None = Query(default=None, ge=1, le=2**31),
    branch: str | None = Query(default=None, pattern=REF),
    tag: str | None = Query(default=None, pattern=REF),
    commit: str | None = Query(default=None),
    max_age: int = Query(default=probe.MAX_AGE, ge=0, le=86400),
) -> JSONResponse:
    engine = engine_of(request)
    with read_transaction(engine) as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
    project = mine.project
    if pr is None and branch is None and tag is None and commit is None:
        raise invalid({"pr": "one_of_pr_branch_tag_commit"})
    if commit is not None:
        if not SHA.fullmatch(commit):
            raise invalid({"commit": "not_a_sha"}, "a commit is named by its full 40 hex sha")
        commit = commit.lower()
    fg = reader_of(request).for_project(project.id)
    if not fg.configured_for(project.repository_url):
        reason = fg.refused or "no_grant"
        raise probe_not_configured(reason if mine.may("project:admin") else None)
    wanted = [("pr", str(pr) if pr else None), ("branch", branch), ("tag", tag)]
    wanted.append(("commit", commit))
    shown: dict[str, Any] = {"pr": None, "branch": None, "tag": None, "commit": None}
    observations: list[probe.Observation | probe.CommitObservation] = []
    for kind, ref in wanted:
        if ref is None:
            continue
        try:
            observation: probe.Observation | probe.CommitObservation
            if kind == "commit":
                observation = probe.observe_commit(
                    engine, fg, project, ref, max_age, floor=probe.FORCED_FLOOR
                )
            else:
                observation = probe.observe(
                    engine, fg, project, kind, ref, max_age, floor=probe.FORCED_FLOOR
                )
        except forge.NotCoveredError as error:
            raise probe_not_configured(
                error.reason if mine.may("project:admin") else None
            ) from None
        except forge.ForgeUnavailableError as error:
            details: dict[str, Any] = {}
            # The last complete observation in the shape the answer has (§11).
            if kind == "commit":
                last_commit = probe.last_commit(engine, project, ref)
                if last_commit is not None:
                    at = clock.rfc3339(last_commit.observed_at)
                    details["last"] = {**last_commit.shown(), "observed_at": at}
            else:
                stored = probe.last(engine, project.id, kind, ref)
                if stored is not None:
                    at = clock.rfc3339(stored.observed_at)
                    details["last"] = {**probe.shown(project, kind, stored), "observed_at": at}
            # A spent budget says when the forge is read again (§11.4).
            if error.retry_at is not None:
                details["retry_at"] = clock.rfc3339(error.retry_at)
            raise ApiError(
                503, "probe_unavailable", "the forge did not answer", details or None
            ) from None
        observations.append(observation)
        if isinstance(observation, probe.CommitObservation):
            shown[kind] = observation.shown()
        else:
            shown[kind] = probe.shown(project, kind, observation)
    return JSONResponse(
        {
            "forge": forge.kind_of(project.repository_url),
            "repository": forge.repository_of(project.repository_url),
            "observed_at": clock.rfc3339(min(o.observed_at for o in observations)),
            "fresh": all(o.fresh for o in observations),
            **shown,
        }
    )
