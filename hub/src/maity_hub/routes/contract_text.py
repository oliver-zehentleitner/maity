"""`GET /projects/{owner}/{slug}/tasks/{id}/contract` and `GET /projects/{owner}/{slug}/contract`
(docs/api.md §6.8)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from maity_hub import clock, contract_text, forge
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, engine_of, reader_of
from maity_hub.errors import ApiError, invalid, probe_not_configured
from maity_hub.namespace import ProjectRoute
from maity_hub.routes.tasks import _project_card

router = APIRouter(route_class=ProjectRoute)


def _nothing(field: str, reason: str, message: str) -> ApiError:
    return ApiError(404, "not_found", message, {"fields": {field: reason}})


@router.get("/projects/{owner}/{slug}/tasks/{card_id}/contract")
def read_contract(slug: str, card_id: str, request: Request, caller: AnyCaller) -> JSONResponse:
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
        card = _project_card(conn, mine, card_id)
    if card.kind != "contract":
        raise invalid({"contract": "contracts_only"})
    contract = card.contract
    path = contract["path"]  # every stored contract names its place (0101)
    section = contract.get("section")
    if section is None:
        raise _nothing("contract.section", "unset", "the card names no section")
    project = mine.project
    fg = reader_of(request).for_project(project.id)
    if not fg.configured_for(project.repository_url):
        reason = forge.unread_reason(fg, project.repository_url)
        raise probe_not_configured(reason if mine.may("project:admin") else None)
    # Only the project's own repository (§6.13): the card names a path in it, never another.
    repository = forge.repository_of(project.repository_url)
    branch = project.repository_default_branch or "main"
    try:
        shown = contract_text.read(fg, repository, branch, path, section)
    except forge.NotCoveredError as error:
        raise probe_not_configured(error.reason if mine.may("project:admin") else None) from None
    except forge.ForgeUnavailableError as error:
        held = {"retry_at": clock.rfc3339(error.retry_at)} if error.retry_at is not None else None
        raise ApiError(503, "probe_unavailable", "the forge did not answer", held) from None
    except contract_text.ContractTextError as error:
        if error.reason in ("too_large", "not_text"):
            raise invalid({error.field: error.reason}) from None
        raise _nothing(error.field, error.reason, "the contract's section is not there") from None
    return JSONResponse(shown)


def _matches(header: str | None, etag: str) -> bool:
    """Whether `If-None-Match` names `etag`, weak or strong, or is `*`."""
    if not header:
        return False
    tags = [tag.strip() for tag in header.split(",")]
    return "*" in tags or any(tag.removeprefix("W/") == etag for tag in tags)


@router.get("/projects/{owner}/{slug}/contract")
def read_whole_contract(slug: str, request: Request, caller: AnyCaller) -> Response:
    """The file `settings.contract_path` names, whole, with its table of contents (§6.8
    "The whole contract"). The caller is authorized before `If-None-Match` is compared, so
    one without `project:read` gets `not_found`, never `304`."""
    with engine_of(request).begin() as conn:
        mine = membership(conn, caller, slug)
        mine.require("project:read")
    project = mine.project
    path = (project.settings or {}).get("contract_path") or contract_text.DEFAULT_PATH
    fg = reader_of(request).for_project(project.id)
    if not fg.configured_for(project.repository_url):
        reason = forge.unread_reason(fg, project.repository_url)
        raise probe_not_configured(reason if mine.may("project:admin") else None)
    repository = forge.repository_of(project.repository_url)
    branch = project.repository_default_branch or "main"
    try:
        shown = dict(contract_text.read_whole(fg, repository, branch, path))
    except forge.NotCoveredError as error:
        raise probe_not_configured(error.reason if mine.may("project:admin") else None) from None
    except forge.ForgeUnavailableError as error:
        held = {"retry_at": clock.rfc3339(error.retry_at)} if error.retry_at is not None else None
        raise ApiError(503, "probe_unavailable", "the forge did not answer", held) from None
    except contract_text.ContractTextError as error:
        if error.reason == "not_found_on_forge":
            raise _nothing(error.field, error.reason, "the contract file is not there") from None
        raise invalid({error.field: error.reason}) from None
    etag = shown.pop("etag")
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if _matches(request.headers.get("If-None-Match"), etag):
        return Response(status_code=304, headers=headers)
    return JSONResponse(shown, headers=headers)
