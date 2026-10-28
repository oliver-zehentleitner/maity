"""`GET /projects/{owner}/{slug}/tasks/{id}/contract` (docs/api.md §6.8)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from maity_hub import contract_text, forge
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
    contract = card.contract or {}
    path = contract.get("path") or contract_text.DEFAULT_PATH
    section = contract.get("section")
    if section is None:
        raise _nothing("contract.section", "unset", "the card names no section")
    project = mine.project
    fg = reader_of(request)
    if not fg.configured_for(project.repository_url):
        raise probe_not_configured("no_grant" if mine.may("project:admin") else None)
    # Only the project's own repository (§6.13): the card names a path in it, never another.
    repository = forge.repository_of(project.repository_url)
    branch = project.repository_default_branch or "main"
    try:
        shown = contract_text.read(fg, repository, branch, path, section)
    except forge.NotCoveredError as error:
        raise probe_not_configured(error.reason if mine.may("project:admin") else None) from None
    except forge.ForgeUnavailableError:
        raise ApiError(503, "probe_unavailable", "the forge did not answer") from None
    except contract_text.ContractTextError as error:
        if error.reason in ("too_large", "not_text"):
            raise invalid({error.field: error.reason}) from None
        raise _nothing(error.field, error.reason, "the contract's section is not there") from None
    return JSONResponse(shown)
