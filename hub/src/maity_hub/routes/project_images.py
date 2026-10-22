"""`/projects/{slug}/logo` and `/projects/{slug}/banner` (docs/api.md §11.2).

`GET` serves the image the project shows (an upload, else the forge's) from the hub's
own origin, revalidated by `ETag`. `PUT` and `DELETE` are a project admin's upload,
human only. The paths are spelled out per kind, so that no `/projects/{slug}/{kind}`
route shadows the other project routes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import Connection

from maity_hub import forge, idempotency, images
from maity_hub.access import membership
from maity_hub.deps import AnyCaller, HumanCaller, engine_of, reader_of
from maity_hub.errors import ApiError, invalid, not_found

router = APIRouter()


def _matches(header: str | None, tag: str) -> bool:
    """`If-None-Match` names this ETag (or `*`); weak tags compare by value."""
    if not header:
        return False
    given = [part.strip().removeprefix("W/") for part in header.split(",")]
    return "*" in given or tag in given


def _image_response(image: images.Image, request: Request) -> Response:
    headers = {**images.HEADERS, "ETag": image.etag}
    if _matches(request.headers.get("if-none-match"), image.etag):
        return Response(status_code=304, headers=headers)
    return Response(content=image.data, media_type=image.content_type, headers=headers)


def _state_loader(kind: str) -> idempotency.Loader:
    def load(conn: Connection, project_id: str, _request: Request) -> dict[str, Any]:
        return {kind: images.views(conn, [project_id])[project_id][kind]}

    return load


def _get(kind: str) -> Callable[..., Response]:
    def get_image(slug: str, request: Request, caller: AnyCaller) -> Response:
        engine = engine_of(request)
        with engine.begin() as conn:
            mine = membership(conn, caller, slug)
            mine.require("project:read")
            project = mine.project
            image = images.current(conn, project.id, kind)
            checked = images.forge_row(conn, project.id, kind) is not None
        if image is None and not checked and forge.kind_of(project.repository_url) == "github":
            # Nothing stored yet: the one read-through; later refreshes are the worker's.
            answered = images.read_through(engine, reader_of(request), project.id, kind)
            with engine.begin() as conn:
                image = images.current(conn, project.id, kind)
            if image is None and not answered:
                raise ApiError(503, "probe_unavailable", "the forge did not answer")
        if image is None:
            raise not_found()
        return _image_response(image, request)

    return get_image


def _put(kind: str) -> Callable[..., JSONResponse]:
    def put_image(slug: str, request: Request, caller: HumanCaller) -> JSONResponse:
        data: bytes = request.scope["state"].get("body", b"")
        declared = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()

        def action(conn: Connection) -> idempotency.Outcome:
            mine = membership(conn, caller, slug)
            mine.require("project:admin")
            if len(data) > images.CAP:
                raise invalid({"body": "too_large"}, "the image is over 1 MiB")
            sniffed = images.sniff(data)
            if sniffed is None or declared != sniffed:
                raise invalid({"body": "unsupported_type"}, "PNG, JPEG or WebP only")
            state = images.upload(
                conn, mine.project.id, kind, data, sniffed, mine.id, caller.actor(mine.id)
            )
            return idempotency.Outcome(200, f"project_{kind}", mine.project.id, {kind: state})

        return idempotency.run(engine_of(request), request, caller, action)

    return put_image


def _delete(kind: str) -> Callable[..., JSONResponse]:
    def delete_image(slug: str, request: Request, caller: HumanCaller) -> JSONResponse:
        def action(conn: Connection) -> idempotency.Outcome:
            mine = membership(conn, caller, slug)
            mine.require("project:admin")
            state = images.remove_upload(conn, mine.project.id, kind, caller.actor(mine.id))
            return idempotency.Outcome(200, f"project_{kind}", mine.project.id, {kind: state})

        return idempotency.run(engine_of(request), request, caller, action)

    return delete_image


for _kind in images.KINDS:
    idempotency.LOADERS[f"project_{_kind}"] = _state_loader(_kind)
    router.add_api_route(f"/projects/{{slug}}/{_kind}", _get(_kind), methods=["GET"])
    router.add_api_route(f"/projects/{{slug}}/{_kind}", _put(_kind), methods=["PUT"])
    router.add_api_route(f"/projects/{{slug}}/{_kind}", _delete(_kind), methods=["DELETE"])
